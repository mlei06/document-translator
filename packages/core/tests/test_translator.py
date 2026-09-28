from collections.abc import Sequence

import pytest

import doctranslator_core.translator as translator_module
from doctranslator_core import MtEngineConfig, Translator
from doctranslator_core.config import EngineConfig
from doctranslator_core.engines import TranslationEngine
from doctranslator_core.types import (
    EngineInfo,
    EngineResponseError,
    Language,
    TranslationIdentity,
    TranslationMode,
)


class FakeEngine(TranslationEngine):
    """Translates by prefixing the target language; records every batch it receives."""

    def __init__(self, *, drop_one: bool = False) -> None:
        self.batches: list[list[str]] = []
        self.closed = 0
        self._drop_one = drop_one

    @property
    def info(self) -> EngineInfo:
        return EngineInfo(mode=TranslationMode.MT, model="fake", details={})

    @property
    def identity(self) -> TranslationIdentity:
        return TranslationIdentity(mode=TranslationMode.MT, model="fake", details={})

    def translate_batch(
        self, texts: Sequence[str], source: Language, target: Language
    ) -> list[str]:
        self.batches.append(list(texts))
        out = [f"{target.value}:{text}" for text in texts]
        return out[:-1] if self._drop_one else out

    def close(self) -> None:
        self.closed += 1


@pytest.fixture
def engine(monkeypatch: pytest.MonkeyPatch) -> FakeEngine:
    fake = FakeEngine()

    def create_engine(config: EngineConfig) -> TranslationEngine:
        return fake

    monkeypatch.setattr(translator_module, "create_engine", create_engine)
    return fake


def make_translator() -> Translator:
    return Translator(MtEngineConfig.model_validate({"model_dir": "m", "model_family": "small100"}))


def test_order_whitespace_and_passthrough(engine: FakeEngine) -> None:
    texts = ["  你好\n", "", "谢谢", " \t ", "再见  "]
    with make_translator() as t:
        out = t.translate_texts(texts, source=Language.ZH, target=Language.EN)
    assert out == ["  en:你好\n", "", "en:谢谢", " \t ", "en:再见  "]
    assert engine.batches == [["你好", "谢谢", "再见"]]


def test_duplicates_translated_once(engine: FakeEngine) -> None:
    with make_translator() as t:
        out = t.translate_texts(["a", " a ", "b", "a"], source=Language.EN, target=Language.JA)
    assert out == ["ja:a", " ja:a ", "ja:b", "ja:a"]
    assert engine.batches == [["a", "b"]]


def test_nothing_to_translate_skips_engine(engine: FakeEngine) -> None:
    with make_translator() as t:
        assert t.translate_texts(["", "  "], source=Language.EN, target=Language.ZH) == ["", "  "]
        assert t.translate_texts([], source=Language.EN, target=Language.ZH) == []
    assert engine.batches == []


def test_same_source_and_target_rejected(engine: FakeEngine) -> None:
    with make_translator() as t, pytest.raises(ValueError, match="both"):
        t.translate_texts(["a"], source=Language.EN, target=Language.EN)


def test_wrong_count_from_engine_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeEngine(drop_one=True)

    def create_engine(config: EngineConfig) -> TranslationEngine:
        return fake

    monkeypatch.setattr(translator_module, "create_engine", create_engine)
    with make_translator() as t, pytest.raises(EngineResponseError):
        t.translate_texts(["a", "b"], source=Language.EN, target=Language.ES)


def test_close_releases_engine_once_and_blocks_use(engine: FakeEngine) -> None:
    t = make_translator()
    assert t.engine_info.model == "fake"
    t.close()
    t.close()
    assert engine.closed == 1
    with pytest.raises(RuntimeError, match="closed"):
        t.translate_texts(["a"], source=Language.EN, target=Language.ZH)
