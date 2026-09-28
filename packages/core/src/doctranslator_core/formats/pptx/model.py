"""PPTX model types shared by the adapter and its layout capability."""

from dataclasses import dataclass

from doctranslator_core.formats._ooxml import Element

__all__ = ["Container"]


@dataclass
class Container:
    """A text body: a shape, a table cell or a notes body. Used by layout (fit) support."""

    key: int
    part: str
    kind: str
    """``shape``, ``placeholder``, ``table-cell`` or ``notes``."""
    location: str
    element: Element
    """The ``p:sp`` shape, or the ``a:tc`` cell for tables."""
    tx_body: Element
    slide_index: int | None
    """1-based slide index, ``None`` for layouts, masters and notes."""
