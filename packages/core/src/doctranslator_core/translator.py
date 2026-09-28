"""Text-level translation over an engine, with the invariants every surface relies on."""

import logging
import time
from collections.abc import Sequence
from types import TracebackType
from typing import Self

from doctranslator_core.config import EngineConfig
from doctranslator_core.engines import TranslationEngine, create_engine
from doctranslator_core.types import EngineInfo, EngineResponseError, Language

__all__ = ["Translator"]

logger = logging.getLogger(__name__)


class Translator:
    """Translates text through the engine selected by ``config.mode``.

    Create once and reuse: for MT mode, construction loads the model. Not thread-safe; use one
    ``Translator`` per thread.
    """

    def __init__(self, config: EngineConfig) -> None:
        self._engine: TranslationEngine = create_engine(config)
        self._closed = False

    @property
    def engine_info(self) -> EngineInfo:
        return self._engine.info

    def translate_texts(
        self, texts: Sequence[str], *, source: Language, target: Language
    ) -> list[str]:
        """Return one translation per input, in input order.

        Empty and whitespace-only inputs are returned unchanged and never reach the engine.
        Leading and trailing whitespace is re-applied around each translation. Identical inputs
        (after stripping) are translated once and receive identical outputs.
        """
        if self._closed:
            raise RuntimeError("Translator is closed")
        if source == target:
            raise ValueError(f"source and target language are both {source.value!r}")

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
