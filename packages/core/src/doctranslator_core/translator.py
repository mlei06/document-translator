"""Text-level translation over an engine, with the invariants every surface relies on."""

import logging
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from types import TracebackType
from typing import Self

from doctranslator_core import pipeline
from doctranslator_core.config import DocumentLimits, EngineConfig
from doctranslator_core.engines import TranslationEngine, create_engine, with_mt_decoding
from doctranslator_core.fit.fonts import FontLibrary
from doctranslator_core.identity import output_fingerprint
from doctranslator_core.types import (
    DocumentDetection,
    DocumentTranslationOptions,
    DocumentTranslationResult,
    EngineInfo,
    EngineResponseError,
    FontManifest,
    Language,
    TranslationIdentity,
    TranslationProgress,
)

__all__ = ["Translator"]

logger = logging.getLogger(__name__)


class Translator:
    """Translates text and documents through the engine selected by ``config.mode``.

    Create once and reuse: for MT mode, construction loads the model. Not thread-safe; use one
    ``Translator`` per thread. ``fonts`` is the provisioned font manifest for fit measurement;
    ``limits`` bounds document parsing (defaults: ``DocumentLimits()``).
    """

    def __init__(
        self,
        config: EngineConfig,
        *,
        fonts: FontManifest | None = None,
        limits: DocumentLimits | None = None,
    ) -> None:
        self._engine: TranslationEngine = create_engine(config)
        self._fonts = fonts
        # One library per Translator: loaded fonts are reused across documents.
        self._font_library = FontLibrary(fonts) if fonts is not None else None
        self._limits = limits or DocumentLimits()
        self._closed = False

    @property
    def engine_info(self) -> EngineInfo:
        return self._engine.info

    def with_mt_decoding(self, *, beam_size: int, max_batch_size: int) -> Translator:
        """Return a separate decoding binding sharing this MT model and tokenizer.

        Settings are immutable and supplied to every inference call. Closing either binding
        leaves the other usable. Like this translator, bindings are worker-local, not thread-safe.
        """
        if self._closed:
            raise RuntimeError("Translator is closed")
        engine = with_mt_decoding(self._engine, beam_size=beam_size, max_batch_size=max_batch_size)
        binding = object.__new__(Translator)
        binding._engine = engine
        binding._fonts = self._fonts
        binding._font_library = FontLibrary(self._fonts) if self._fonts is not None else None
        binding._limits = self._limits
        binding._closed = False
        return binding

    @property
    def identity(self) -> TranslationIdentity:
        """The loaded engine's output identity (ADR-011); compare with ``prepare_identity``."""
        return self._engine.identity

    def translate_document(
        self,
        input_path: Path,
        output_path: Path,
        *,
        options: DocumentTranslationOptions,
        on_progress: Callable[[TranslationProgress], None] | None = None,
        should_skip_fit: Callable[[], bool] | None = None,
        detection_metadata: DocumentDetection | None = None,
    ) -> DocumentTranslationResult:
        """Translate one document into a new file of the same format (see the Document API).

        ``should_skip_fit`` lets the caller stop remaining optional fit work (ADR-012 amendment).
        ``detection_metadata`` reuses best-effort ingestion display data without detecting again.
        """
        if self._closed:
            raise RuntimeError("Translator is closed")
        return pipeline.translate_document(
            self,
            input_path,
            output_path,
            options=options,
            fingerprint=output_fingerprint(self.identity, options, self._fonts),
            limits=self._limits,
            fonts=self._fonts,
            on_progress=on_progress,
            font_library=self._font_library,
            should_skip_fit=should_skip_fit,
            detection_metadata=detection_metadata,
        )

    def translate_texts(
        self, texts: Sequence[str], *, target: Language, source: Language | None = None
    ) -> list[str]:
        """Return one translation per input, in input order.

        Empty and whitespace-only inputs are returned unchanged and never reach the engine.
        Leading and trailing whitespace is re-applied around each translation. Identical inputs
        (after stripping) are translated once and receive identical outputs.
        """
        if self._closed:
            raise RuntimeError("Translator is closed")

        started = time.perf_counter()
        parts = [_split_whitespace(text) for text in texts]
        unique = list(dict.fromkeys(core for _, core, _ in parts if core))
        translated = self._engine.translate_batch(unique, source, target) if unique else []
        if len(translated) != len(unique):
            raise EngineResponseError(
                f"engine returned {len(translated)} translations for {len(unique)} texts"
            )
        by_text = dict(zip(unique, translated, strict=True))
        result = [
            leading + by_text[core] + trailing if core else leading
            for leading, core, trailing in parts
        ]

        logger.debug(
            "translated %d inputs (%d unique, %d passed through) in %.2f s",
            len(texts),
            len(unique),
            sum(1 for _, core, _ in parts if not core),
            time.perf_counter() - started,
        )
        return result

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._engine.close()
            if self._font_library is not None:
                self._font_library.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()


def _split_whitespace(text: str) -> tuple[str, str, str]:
    """Split into (leading whitespace, stripped text, trailing whitespace).

    Whitespace-only text is returned whole as the leading part, so it round-trips unchanged.
    """
    core = text.strip()
    if not core:
        return text, "", ""
    start = len(text) - len(text.lstrip())
    return text[:start], core, text[start + len(core) :]
