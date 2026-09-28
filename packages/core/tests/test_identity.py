"""Output identity and fingerprint (ADR-011 section 6)."""

from pathlib import Path

import pytest

from doctranslator_core import LlmEngineConfig, MtEngineConfig, output_fingerprint, prepare_identity
from doctranslator_core.engines.llm import LlmEngine
from doctranslator_core.engines.mt import MtEngine, MtRuntime
from doctranslator_core.types import (
    DocumentTranslationOptions,
    EngineUnavailableError,
    FitOptions,
    FontFace,
    FontManifest,
    Language,
    TranslationIdentity,
    TranslationMode,
)

LLM = LlmEngineConfig.model_validate(
    {"base_url": "https://llm.internal/v1", "api_key": "secret-key", "model": "gemma"}
)
OPTIONS = DocumentTranslationOptions(target=Language.EN)


def test_llm_identity_is_metadata_only_and_matches_the_engine() -> None:
    prepared = prepare_identity(LLM)
    assert prepared.mode is TranslationMode.LLM
    assert "secret-key" not in prepared.model_dump_json()
    engine = LlmEngine(LLM)
    try:
        assert engine.identity == prepared
    finally:
        engine.close()


def test_mt_identity_hashes_artifacts_without_loading(tmp_path: Path) -> None:
    (tmp_path / "model.bin").write_bytes(b"weights")
    (tmp_path / "sentencepiece.bpe.model").write_bytes(b"tokenizer")
    config = MtEngineConfig(model_dir=tmp_path, model_family="small100", device="cpu")
    prepared = prepare_identity(config)
    assert prepared.details["device"] == "cpu"

    class Runtime:
        def translate_batch(
            self, source: list[list[str]], *, beam_size: int, max_batch_size: int
        ) -> list[object]:
            return []

        def encode(self, text: str, *, out_type: type[str]) -> list[str]:
            return []

        def decode(self, pieces: list[str]) -> str:
            return ""

    from doctranslator_core.engines.mt import artifact_sha256

    runtime = MtRuntime(Runtime(), Runtime(), "cpu", artifact_sha256(tmp_path))  # type: ignore[arg-type]
    assert MtEngine(config, runtime=runtime).identity == prepared
    (tmp_path / "model.bin").write_bytes(b"other weights")
    assert prepare_identity(config) != prepared


def test_mt_identity_requires_the_model_directory(tmp_path: Path) -> None:
    config = MtEngineConfig(model_dir=tmp_path / "missing", model_family="small100", device="cpu")
    with pytest.raises(EngineUnavailableError):
        prepare_identity(config)


def test_fingerprint_is_stable_and_sensitive_to_every_output_affecting_input() -> None:
    identity = prepare_identity(LLM)
    base = output_fingerprint(identity, OPTIONS)
    assert base == output_fingerprint(prepare_identity(LLM), OPTIONS)
    rotated_key = LLM.model_copy(update={"api_key": "another"})
    assert output_fingerprint(prepare_identity(rotated_key), OPTIONS) == base
    assert (
        output_fingerprint(prepare_identity(LLM.model_copy(update={"timeout_s": 5.0})), OPTIONS)
        == base
    )

    variants = [
        output_fingerprint(identity, OPTIONS.model_copy(update={"target": Language.JA})),
        output_fingerprint(identity, OPTIONS.model_copy(update={"source": Language.ZH})),
        output_fingerprint(identity, OPTIONS.model_copy(update={"protected_terms": ("X",)})),
        output_fingerprint(identity, OPTIONS.model_copy(update={"txt_encoding": "gbk"})),
        output_fingerprint(identity, OPTIONS.model_copy(update={"fit": FitOptions(min_scale=0.8)})),
        output_fingerprint(identity, OPTIONS.model_copy(update={"fit": FitOptions(min_size_pt=9)})),
        output_fingerprint(prepare_identity(LLM.model_copy(update={"model": "other"})), OPTIONS),
        output_fingerprint(
            prepare_identity(LLM.model_copy(update={"deployment_revision": "2"})), OPTIONS
        ),
        output_fingerprint(prepare_identity(LLM.model_copy(update={"temperature": 0.5})), OPTIONS),
        output_fingerprint(identity, OPTIONS, _fonts("a")),
        output_fingerprint(identity, OPTIONS, _fonts("b")),
    ]
    assert len({base, *variants}) == len(variants) + 1


def test_font_manifest_digest_ignores_paths() -> None:
    assert _fonts("a", Path("C:/x/f.ttf")).digest == _fonts("a", Path("/usr/share/f.ttf")).digest


def _fonts(sha: str, path: Path = Path("f.ttf")) -> FontManifest:
    return FontManifest(
        faces=(
            FontFace(
                family="Arial", names=("Arial",), bold=False, italic=False, path=path, sha256=sha
            ),
        )
    )


def test_identity_digest_is_canonical() -> None:
    a = TranslationIdentity(mode=TranslationMode.MT, model="m", details={"a": "1", "b": "2"})
    b = TranslationIdentity(mode=TranslationMode.MT, model="m", details={"b": "2", "a": "1"})
    assert a.digest == b.digest
