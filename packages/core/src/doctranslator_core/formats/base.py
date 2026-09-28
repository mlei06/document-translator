"""Format capability abstract base classes (ADR-003). Implemented only where applicable."""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from pathlib import Path

from doctranslator_core.document import Paragraph
from doctranslator_core.inline import Inline
from doctranslator_core.types import DocumentDiagnostic, DocumentFormat, Language

__all__ = ["DocumentAdapter"]


class DocumentAdapter(ABC):
    """Reads one document, exposes its translatable paragraphs and writes the translated file.

    An adapter owns its parsed state for one document. Style ids and object keys in the inline
    nodes it returns are its own; ``apply`` receives nodes that reuse them.
    """

    format: DocumentFormat

    def __init__(self) -> None:
        self.diagnostics: list[DocumentDiagnostic] = []

    @abstractmethod
    def paragraphs(self) -> list[Paragraph]:
        """Every translatable paragraph in document order."""

    @abstractmethod
    def apply(self, paragraph_id: int, nodes: Sequence[Inline], target: Language) -> None:
        """Replace a paragraph's content with translated nodes."""

    @abstractmethod
    def save(self, path: Path) -> None:
        """Write the (translated) document to ``path``, which does not exist yet."""

    def close(self) -> None:  # noqa: B027 - optional hook with a no-op default
        """Release resources. Default: nothing to release."""
