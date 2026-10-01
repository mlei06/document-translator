"""Exercise the production catalog/core stack with a fake native CT2 constructor."""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import ValidationError
from support.server import server_settings

from doctranslator_core.types import DocumentTranslationOptions, FontManifest, Language
from doctranslator_server.jobs.engines import EngineCatalog


@pytest.fixture
def native(monkeypatch: pytest.MonkeyPatch) -> Mock:
    def translate(source: list[list[str]], **kwargs: object) -> list[SimpleNamespace]:
        return [SimpleNamespace(hypotheses=[tokens[1:-1]]) for tokens in source]

    create = Mock(return_value=Mock(translate_batch=Mock(side_effect=translate)))
    monkeypatch.setitem(
        sys.modules,
        "ctranslate2",
        SimpleNamespace(Translator=create, get_cuda_device_count=lambda: 0),
    )

    class Tokenizer:
        def __init__(self, **kwargs: object) -> None:
            pass

        def encode(self, text: str, **kwargs: object) -> list[str]:
            return text.split()

        def decode(self, pieces: list[str]) -> str:
            return " ".join(pieces)

    monkeypatch.setitem(
        sys.modules, "sentencepiece", SimpleNamespace(SentencePieceProcessor=Tokenizer)
    )
    return create


def catalog(tmp_path: Path, variants: list[dict[str, object]], limit: int = 1) -> EngineCatalog:
    entries: list[dict[str, object]] = []
    for index, overrides in enumerate(variants):
        config = {
            "mode": "mt",
            "model_dir": str(tmp_path / "model"),
            "model_family": "small100",
            "device": "cpu",
            "beam_size": 4,
        } | overrides
        directory = Path(str(config["model_dir"]))
        directory.mkdir(exist_ok=True)
        (directory / "model.bin").write_bytes(b"model")
        (directory / "sentencepiece.bpe.model").write_bytes(b"tokenizer")
        (directory / "config.json").write_text("{}")
        (directory / "shared_vocabulary.json").write_text('["token"]')
        entries.append({"id": str(index), "label": str(index), "engine": config})
    settings = server_settings(
        tmp_path, translators=entries, default_translator_id="0", max_loaded_local_models=limit
    )
    return EngineCatalog(settings, FontManifest(faces=()))


def test_decoding_presets_reuse_native_model_and_keep_pinned_identity(
    tmp_path: Path, native: Mock
) -> None:
    engines = catalog(tmp_path, [{}, {"beam_size": 1, "max_batch_size": 8}])
    options = DocumentTranslationOptions(source=Language.EN, target=Language.ZH)
    beam = engines.translator("0")
    for identifier in ["0", "1", "0"]:
        binding = engines.translator(identifier)
        assert binding.translate_texts(["Hello world"], source=Language.EN, target=Language.ZH) == [
            "Hello world"
        ]
        assert engines.loaded_fingerprint(binding, options) == engines.fingerprint(
            identifier, options
        )
    assert native.call_count == 1
    assert [call.kwargs for call in native.return_value.translate_batch.call_args_list] == [
        {"beam_size": 4, "max_batch_size": 32},
        {"beam_size": 1, "max_batch_size": 8},
        {"beam_size": 4, "max_batch_size": 32},
    ]
    assert engines.fingerprint("0", options) != engines.fingerprint("1", options)
    greedy = engines.translator("1")
    engines.close()
    for binding in [beam, greedy]:
        with pytest.raises(RuntimeError, match="closed"):
            binding.translate_texts(["Hello"], source=Language.EN, target=Language.ZH)


def test_binding_close_and_validation_are_independent(tmp_path: Path, native: Mock) -> None:
    engines = catalog(tmp_path, [{}])
    beam = engines.translator("0")
    with pytest.raises(ValidationError):
        beam.with_mt_decoding(beam_size=0, max_batch_size=32)
    greedy = beam.with_mt_decoding(beam_size=1, max_batch_size=8)
    beam.close()
    assert greedy.translate_texts(["Hello"], source=Language.EN, target=Language.ZH) == ["Hello"]
    with pytest.raises(RuntimeError, match="closed"):
        beam.with_mt_decoding(beam_size=4, max_batch_size=32)
    greedy.close()
    engines.close()
    assert native.call_count == 1


@pytest.mark.parametrize(
    "change",
    [{"device": "cuda"}, {"compute_type": "int8"}, {"cpu_threads": 2}, {"model_dir": "other"}],
)
def test_incompatible_runtime_settings_do_not_share(
    tmp_path: Path, native: Mock, change: dict[str, object]
) -> None:
    if "model_dir" in change:
        change = {"model_dir": str(tmp_path / "other")}
    engines = catalog(tmp_path, [{}, change])
    first = engines.translator("0")
    engines.translator("1")
    assert native.call_count == 2
    with pytest.raises(RuntimeError, match="closed"):
        first.translate_texts(["Hello"], source=Language.EN, target=Language.ZH)
    engines.close()


def test_lru_counts_weights_and_evicts_all_aliases(tmp_path: Path, native: Mock) -> None:
    engines = catalog(
        tmp_path, [{}, {"beam_size": 1}, {"cpu_threads": 2}, {"cpu_threads": 3}], limit=2
    )
    beam = engines.translator("0")
    greedy = engines.translator("1")
    second = engines.translator("2")
    assert native.call_count == 2
    assert engines.translator("1") is greedy  # Refresh the whole first runtime group.
    engines.translator("3")
    assert native.call_count == 3
    with pytest.raises(RuntimeError, match="closed"):
        second.translate_texts(["Hello"], source=Language.EN, target=Language.ZH)
    assert engines.translator("0") is beam
    engines.translator("3")
    engines.translator("2")  # Both aliases are now the least recently used group.
    for binding in [beam, greedy]:
        with pytest.raises(RuntimeError, match="closed"):
            binding.translate_texts(["Hello"], source=Language.EN, target=Language.ZH)
    assert native.call_count == 4
    engines.close()
