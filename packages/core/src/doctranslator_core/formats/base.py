"""Format capability abstract base classes (ADR-003). Implemented only where applicable."""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from pathlib import Path

from doctranslator_core.document import LayoutContainer, Paragraph
from doctranslator_core.inline import Inline
from doctranslator_core.types import DocumentDiagnostic, DocumentFormat, Language

__all__ = ["DocumentAdapter", "LayoutSupport"]


class LayoutSupport(ABC):
    """Fixed-size text containers for the fit check, and applying the sizes it chooses.

    ``layout_containers`` describes the document's current state: called before translation it
    gives the original baseline, after ``apply`` the translated layout, with the same ids. Which
    containers are reported expresses the format's fit scope (ADR-003): reflowing body text is
    never a container. Sizes are points, per paragraph and run as described.
    """

    @abstractmethod
    def layout_containers(self) -> list[LayoutContainer]: ...

    @abstractmethod
    def apply_run_sizes(self, container_id: str, sizes: Sequence[Sequence[float]]) -> None: ...


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
