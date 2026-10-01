"""Format-neutral representation passed between format adapters, the pipeline and fit."""

from dataclasses import dataclass
from typing import Literal

from doctranslator_core.inline import Inline

__all__ = [
    "LayoutContainer",
    "LayoutParagraph",
    "LayoutPatch",
    "LayoutRun",
    "Paragraph",
]


@dataclass(frozen=True, slots=True)
class Paragraph:
    """One translatable paragraph as an adapter describes it.

    ``id`` is the adapter's handle for ``apply``; ``location`` is the stable, human-readable
    location used in diagnostics and fit reports (never document text).
    """

    id: int
    location: str
    nodes: tuple[Inline, ...]


@dataclass(frozen=True, slots=True)
class LayoutRun:
    """A run of text with its effective (inherited and resolved) font properties."""

    text: str
    size_pt: float
    latin_font: str | None
    """Font for Latin and other non-CJK characters, as the document names it."""
    east_asian_font: str | None
    """Font for Han, kana and full-width characters."""
    bold: bool = False
    italic: bool = False
    fallback_fonts: tuple[str, ...] = ()
    """Fonts the document declares for scripts its run fonts lack (theme Hans/Jpan/Hant),
    tried in order when neither run font contains a character."""


@dataclass(frozen=True, slots=True)
class LayoutParagraph:
    runs: tuple[LayoutRun, ...]
    end_run: LayoutRun
    """Properties at the paragraph mark; gives an empty paragraph its line height."""
    line_spacing: float = 1.0
    """Multiple of single line spacing (ignored when ``line_spacing_pt`` is set)."""
    line_spacing_pt: float | None = None
    """Exact line height in points."""
    space_before_pt: float = 0.0
    space_after_pt: float = 0.0
    first_line_start_pt: float = 0.0
    """Where the first line's text starts, from the content box's left edge."""
    other_lines_start_pt: float = 0.0
    """Where continuation lines start."""
    right_indent_pt: float = 0.0
    line_minimum_pt: float | None = None
    """Smallest line height ("at least" spacing)."""
    line_grid_pt: float | None = None
    """Line heights are rounded up to multiples of this document-grid pitch."""


@dataclass(frozen=True, slots=True)
class LayoutContainer:
    """A fixed-size text container in its own local coordinates (points, insets removed).

    ``width_pt``/``height_pt`` are ``None`` for an unconstrained axis. With ``wrap`` false, lines
    only break at explicit paragraph ends and ``width_pt`` limits how far text may extend.
    ``unsupported`` explains why the container cannot be measured (for example vertical text).
    """

    id: str
    location: str
    kind: str
    width_pt: float | None
    height_pt: float | None
    wrap: bool
    paragraphs: tuple[LayoutParagraph, ...]
    unsupported: str | None = None
    line_metric: Literal["em", "font"] = "font"
    """How single line spacing is computed: ``em`` is a fixed ``em_line_height`` times the font
    size (PowerPoint); ``font`` uses each font's own ascent and descent (Word, Excel)."""
    em_line_height: float = 1.2
    page_index: int | None = None
    bounds_pt: tuple[float, float, float, float] | None = None
    content_bounds_pt: tuple[float, float, float, float] | None = None
    growth_bounds_pt: tuple[float, float, float, float] | None = None
    revision: int = 0
    spacing_supported: bool = False


@dataclass(frozen=True, slots=True)
class LayoutPatch:
    """Validated, optimistic patch containing no arbitrary document edits."""

    expected: LayoutContainer
    replacement: LayoutContainer
    operation: Literal["fonts", "geometry", "spacing"]
