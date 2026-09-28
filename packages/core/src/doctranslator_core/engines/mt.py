"""MT mode: a local CTranslate2 model.

The runtime (``ctranslate2``, ``sentencepiece``) is imported lazily, so an install without the
``[mt]`` extra works in LLM mode.
"""

import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

from doctranslator_core.config import MtEngineConfig
from doctranslator_core.engines.base import TranslationEngine
from doctranslator_core.types import (
    EngineInfo,
    EngineUnavailableError,
    Language,
    TranslationIdentity,
    TranslationMode,
)

__all__ = ["MtEngine", "MtRuntime", "artifact_sha256", "prepare_identity"]

_SPECIAL_TOKENS = frozenset({"<s>", "</s>", "<pad>", "<unk>"})
_LANGUAGE_TOKEN = re.compile(r"__[a-z]{2,3}__")


class _Ct2Result(Protocol):
    @property
    def hypotheses(self) -> list[list[str]]: ...


class _Ct2Translator(Protocol):
    def translate_batch(
        self,
        source: list[list[str]],
        *,
        beam_size: int,
        max_batch_size: int,
    ) -> Sequence[_Ct2Result]: ...


class _Ct2Module(Protocol):
    """The part of the untyped ``ctranslate2`` module this engine uses."""

    def get_cuda_device_count(self) -> int: ...

    def Translator(  # noqa: N802 - mirrors the library's class name
        self, model_path: str, *, device: str, compute_type: str, intra_threads: int
    ) -> _Ct2Translator: ...


class _SentencePiece(Protocol):
    def encode(self, text: str, *, out_type: type[str]) -> list[str]: ...

    def decode(self, pieces: list[str]) -> str: ...


@dataclass(frozen=True)
class MtRuntime:
    """The loaded model and tokenizer. Tests construct one from fakes."""

    translator: _Ct2Translator
    tokenizer: _SentencePiece
    device: str
    artifact_sha256: str = ""
    """SHA-256 of the model directory's files (``artifact_sha256``); tests may leave it empty."""


class MtEngine(TranslationEngine):
    def __init__(self, config: MtEngineConfig, *, runtime: MtRuntime | None = None) -> None:
        """``runtime`` exists for tests; production passes nothing and the model is loaded."""
        self._config = config
        self._runtime: MtRuntime | None = runtime if runtime is not None else _load_runtime(config)

    @property
    def info(self) -> EngineInfo:
        return EngineInfo(
            mode=TranslationMode.MT,
            model=self._config.model_dir.name,
            details={
                "model_family": self._config.model_family,
                "device": self._require_runtime().device,
                "compute_type": self._config.compute_type,
                "beam_size": str(self._config.beam_size),
            },
        )

    @property
    def identity(self) -> TranslationIdentity:
        runtime = self._require_runtime()
        return _identity(self._config, runtime.device, runtime.artifact_sha256)

    def translate_batch(
        self, texts: Sequence[str], source: Language, target: Language
    ) -> list[str]:
        runtime = self._require_runtime()
        # small100 conditions on the target language only: the target token leads the source.
        # The source language is implied by the text.
        prefix = f"__{target.value}__"
        tokens = [[prefix, *runtime.tokenizer.encode(text, out_type=str), "</s>"] for text in texts]
        results = runtime.translator.translate_batch(
            tokens,
            beam_size=self._config.beam_size,
            max_batch_size=self._config.max_batch_size,
        )
        return [runtime.tokenizer.decode(_content_pieces(r.hypotheses[0])).strip() for r in results]

    def close(self) -> None:
        self._runtime = None

    def _require_runtime(self) -> MtRuntime:
        if self._runtime is None:
            raise RuntimeError("MT engine is closed")
        return self._runtime


def prepare_identity(config: MtEngineConfig) -> TranslationIdentity:
    """The MT engine's output identity without loading the model.

    Hashes the model directory and resolves ``device="auto"`` (which imports CTranslate2 only to
    count CUDA devices). Raises ``EngineUnavailableError`` if the directory is missing.
    """
    if not config.model_dir.is_dir():
        raise EngineUnavailableError(f"MT model directory not found: {config.model_dir}")
    return _identity(config, _resolve_device(config), artifact_sha256(config.model_dir))


def artifact_sha256(model_dir: Path) -> str:
    """SHA-256 over the sorted relative names and contents of every file in the directory."""
    digest = hashlib.sha256()
    for path in sorted(p for p in model_dir.rglob("*") if p.is_file()):
        digest.update(path.relative_to(model_dir).as_posix().encode("utf-8") + b"\0")
        with path.open("rb") as handle:
            while chunk := handle.read(1 << 20):
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()


def _identity(config: MtEngineConfig, device: str, artifact: str) -> TranslationIdentity:
    return TranslationIdentity(
        mode=TranslationMode.MT,
        model=config.model_dir.name,
        details={
            "model_family": config.model_family,
            "artifact_sha256": artifact,
            "device": device,
            "compute_type": config.compute_type,
            "beam_size": str(config.beam_size),
            "max_batch_size": str(config.max_batch_size),
        },
    )


def _resolve_device(config: MtEngineConfig) -> str:
    if config.device != "auto":
        return config.device
    try:
        import ctranslate2  # pyright: ignore[reportMissingTypeStubs]
    except ImportError as exc:
        raise EngineUnavailableError(
            "MT mode requires the 'mt' extra: install doctranslator-core[mt]"
        ) from exc
    ct2 = cast(_Ct2Module, ctranslate2)
    return "cuda" if ct2.get_cuda_device_count() > 0 else "cpu"


def _content_pieces(pieces: list[str]) -> list[str]:
    return [p for p in pieces if p not in _SPECIAL_TOKENS and not _LANGUAGE_TOKEN.fullmatch(p)]


def _load_runtime(config: MtEngineConfig) -> MtRuntime:
    try:
        import ctranslate2  # pyright: ignore[reportMissingTypeStubs]
        import sentencepiece  # pyright: ignore[reportMissingTypeStubs]
    except ImportError as exc:
        raise EngineUnavailableError(
            "MT mode requires the 'mt' extra: install doctranslator-core[mt]"
        ) from exc

    model_dir = config.model_dir
    tokenizer_file = model_dir / "sentencepiece.bpe.model"
    for required in (model_dir / "model.bin", tokenizer_file):
        if not required.is_file():
            raise EngineUnavailableError(f"MT model file not found: {required}")

    ct2 = cast(_Ct2Module, ctranslate2)
    device = config.device
    if device == "auto":
        device = "cuda" if ct2.get_cuda_device_count() > 0 else "cpu"
    try:
        translator = ct2.Translator(
            str(model_dir),
            device=device,
            compute_type=config.compute_type,
            intra_threads=config.cpu_threads,
        )
        tokenizer = sentencepiece.SentencePieceProcessor(model_file=str(tokenizer_file))
    except (RuntimeError, ValueError, OSError) as exc:
        raise EngineUnavailableError(f"MT model could not be loaded from {model_dir}") from exc
    return MtRuntime(
        translator=translator,
        tokenizer=cast(_SentencePiece, tokenizer),
        device=device,
        artifact_sha256=artifact_sha256(model_dir),
    )
