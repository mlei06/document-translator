"""Format-neutral representation passed between format adapters, the pipeline and fit."""

from dataclasses import dataclass

from doctranslator_core.inline import Inline

__all__ = ["Paragraph"]


@dataclass(frozen=True, slots=True)
class Paragraph:
    """One translatable paragraph as an adapter describes it.

    ``id`` is the adapter's handle for ``apply``; ``location`` is the stable, human-readable
    location used in diagnostics and fit reports (never document text).
    """

    id: int
    location: str
    nodes: tuple[Inline, ...]
