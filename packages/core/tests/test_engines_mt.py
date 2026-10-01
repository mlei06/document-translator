import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from doctranslator_core import MtEngineConfig
from doctranslator_core.engines.mt import MtEngine, MtRuntime
from doctranslator_core.types import EngineUnavailableError, Language, TranslationMode


class FakeTokenizer:
    """Pieces are whitespace-separated words, marked like SentencePiece pieces."""

    def encode(self, text: str, *, out_type: type[str]) -> list[str]:
        return [f"▁{word}" for word in text.split()]

    def decode(self, pieces: list[str]) -> str:
        return " ".join(piece.removeprefix("▁") for piece in pieces)


@dataclass
class FakeResult:
    hypotheses: list[list[str]]


@dataclass
class FakeTranslator:
    """Uppercases every piece, wrapped in the special tokens a real model can emit."""

    calls: list[tuple[list[list[str]], int, int]] = field(
        default_factory=list[tuple[list[list[str]], int, int]]
    )

    def translate_batch(
        self, source: list[list[str]], *, beam_size: int, max_batch_size: int
    ) -> Sequence[FakeResult]:
        self.calls.append((source, beam_size, max_batch_size))
        return [
            FakeResult([["__en__", *(p.upper() for p in tokens[1:-1]), "<unk>", "</s>"]])
            for tokens in source
        ]


def config(model_dir: Path = Path("models/small100"), **overrides: object) -> MtEngineConfig:
    values: dict[str, object] = {"model_dir": model_dir, "model_family": "small100"}
    return MtEngineConfig.model_validate(values | overrides)


def fake_engine(**overrides: object) -> tuple[MtEngine, FakeTranslator]:
    translator = FakeTranslator()
    runtime = MtRuntime(translator=translator, tokenizer=FakeTokenizer(), device="cpu")
    values: dict[str, object] = {"model_dir": "models/small100", "model_family": "small100"}
    return MtEngine(MtEngineConfig.model_validate(values | overrides), runtime=runtime), translator


def test_small100_prefixes_target_token_and_appends_eos() -> None:
    engine, translator = fake_engine(beam_size=2, max_batch_size=8)
    out = engine.translate_batch(["ni hao", "xie xie"], Language.ZH, Language.JA)
    assert translator.calls == [
        ([["__ja__", "▁ni", "▁hao", "</s>"], ["__ja__", "▁xie", "▁xie", "</s>"]], 2, 8)
    ]
    assert out == ["NI HAO", "XIE XIE"]


def test_special_and_language_tokens_are_dropped_from_output() -> None:
    engine, _ = fake_engine()
    assert engine.translate_batch(["a"], Language.ZH, Language.EN) == ["A"]


def test_info_describes_model_and_settings() -> None:
    engine, _ = fake_engine(compute_type="int8", beam_size=1)
    info = engine.info
    assert info.mode is TranslationMode.MT
    assert info.model == "small100"
    assert info.details == {
        "model_family": "small100",
        "device": "cpu",
        "compute_type": "int8",
        "beam_size": "1",
    }


def test_closed_engine_refuses_work() -> None:
    engine, _ = fake_engine()
    engine.close()
    with pytest.raises(RuntimeError, match="closed"):
        engine.translate_batch(["a"], Language.ZH, Language.EN)


def test_missing_extra_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "ctranslate2", None)
    with pytest.raises(EngineUnavailableError, match=r"doctranslator-core\[mt\]"):
        MtEngine(config())


def test_missing_model_files_are_reported(tmp_path: Path) -> None:
    with pytest.raises(EngineUnavailableError, match=r"model\.bin"):
        MtEngine(config(tmp_path))
    (tmp_path / "model.bin").write_bytes(b"weights")
    with pytest.raises(EngineUnavailableError, match=r"sentencepiece\.bpe\.model"):
        MtEngine(config(tmp_path))


def test_unloadable_model_is_reported(tmp_path: Path) -> None:
    (tmp_path / "model.bin").write_bytes(b"not a model")
    (tmp_path / "sentencepiece.bpe.model").write_bytes(b"not a tokenizer")
    (tmp_path / "config.json").write_text("{}")
    (tmp_path / "shared_vocabulary.json").write_text('["token"]')
    with pytest.raises(EngineUnavailableError, match="could not be loaded"):
        MtEngine(config(tmp_path, device="cpu"))
