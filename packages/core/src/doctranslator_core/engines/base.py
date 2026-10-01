"""The translation engine interface implemented by every translation mode."""

from abc import ABC, abstractmethod
from collections.abc import Sequence

from doctranslator_core.types import EngineInfo, Language, TranslationIdentity


class TranslationEngine(ABC):
    @property
    @abstractmethod
    def info(self) -> EngineInfo: ...

    @property
    @abstractmethod
    def identity(self) -> TranslationIdentity:
        """Everything about the loaded engine that can change its output (ADR-011)."""

    @abstractmethod
    def translate_batch(
        self, texts: Sequence[str], source: Language | None = None, target: Language | None = None
    ) -> list[str]:
        """Translate non-empty, stripped, unique texts. Same length and order as input."""

    def close(self) -> None:  # noqa: B027 - optional hook with a no-op default
        """Release resources. Default: nothing to release."""
