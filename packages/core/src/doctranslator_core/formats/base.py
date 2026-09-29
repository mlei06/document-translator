"""Format capability abstract base classes (ADR-003). Implemented only where applicable."""

from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from pathlib import Path

from doctranslator_core.document import LayoutContainer, Paragraph
from doctranslator_core.inline import Inline
from doctranslator_core.types import (
    DocumentDiagnostic,
    DocumentFormat,
    FitEntry,
    FitOptions,
    FontManifest,
    Language,
)

__all__ = ["DocumentAdapter", "LayoutSupport", "PlacementFit"]


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


class PlacementFit(ABC):
    """Formats whose writer lays out translated text itself (PDF; ADR-012, ADR-018).

    Instead of describing containers for the shared estimator, the adapter places every changed
    text unit with its writer's layout facility, shrinking within the ADR-012 floors, and reports
    one outcome per unit it placed.
    """

    @abstractmethod
    def place(
        self,
        options: FitOptions,
        fonts: FontManifest | None,
        should_skip: Callable[[], bool] | None = None,
    ) -> tuple[list[FitEntry | None], bool]:
        """Place every translated unit; ``None`` for a unit that fit at its original sizes.

        Returns the outcomes and whether optional fitting was skipped: once ``should_skip``
        returns true, remaining units are still placed completely but without shrinking.
        """


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

    def verify_output(self, reopened: DocumentAdapter) -> None:  # noqa: B027
        """Check the written file, reopened as ``reopened``, against what this adapter wrote.

        Raise ``InvalidDocumentError`` on a mismatch. Default: no format-specific checks.
        """

    def close(self) -> None:  # noqa: B027 - optional hook with a no-op default
        """Release resources. Default: nothing to release."""
