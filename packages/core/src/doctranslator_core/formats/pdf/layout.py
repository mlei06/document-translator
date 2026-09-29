"""PDF placement (ADR-014): where a translated unit may go, which font draws it, how it is written.

Coordinates are PyMuPDF page coordinates in points (origin top left, unrotated page space, the
space both text extraction and ``insert_htmlbox`` use). Nothing here moves or scales artwork.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportMissingTypeStubs=false, reportAttributeAccessIssue=false

import html
import io
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

import pymupdf
from fontTools.ttLib import TTFont

from doctranslator_core.inline import Inline, Keep, Text, Wrap
from doctranslator_core.types import (
    FitOptions,
    FontFace,
    FontManifest,
    InvalidDocumentError,
    Language,
)

__all__ = [
    "Align",
    "Box",
    "FontChoice",
    "FontResolver",
    "PdfStyle",
    "Placement",
    "alignment",
    "container_for",
    "floor_scale",
    "font_css",
    "generic_family",
    "page_bounds",
    "place_html",
    "region_for",
    "unit_html",
]

type Box = tuple[float, float, float, float]
type Align = Literal["left", "center", "right"]

GAP_PT = 2.0
"""Clearance kept between a grown unit and the text or artwork next to it."""
MAX_INSET_PT = 7.2
"""Largest padding assumed inside a box around text (PowerPoint's default inset, 0.1 in)."""
PAGE_MARGIN_PT = 36.0
"""Page margin free-standing text may grow into (0.5 in), unless the page's text is already
closer to the edge."""
BACKGROUND_SHARE = 0.8
"""Drawings or images covering this share of the page are backgrounds, not boxes or obstacles."""
ALIGN_TOLERANCE_PT = 1.5

TARGET_FAMILIES: dict[Language, tuple[tuple[str, ...], tuple[str, ...]]] = {
    Language.EN: (
        ("Arial", "Liberation Sans", "DejaVu Sans"),
        ("Times New Roman", "Liberation Serif", "DejaVu Serif"),
    ),
    Language.ES: (
        ("Arial", "Liberation Sans", "DejaVu Sans"),
        ("Times New Roman", "Liberation Serif", "DejaVu Serif"),
    ),
    Language.ZH: (
        ("Microsoft YaHei", "DengXian", "Noto Sans CJK SC", "Source Han Sans SC"),
        ("SimSun", "Noto Serif CJK SC", "Source Han Serif SC"),
    ),
    Language.JA: (
        ("Yu Gothic", "Meiryo", "MS Gothic", "Noto Sans CJK JP", "Source Han Sans JP"),
        ("Yu Mincho", "MS Mincho", "Noto Serif CJK JP", "Source Han Serif JP"),
    ),
}
"""Deterministic substitutes, in order, when a unit's own font is not provisioned or lacks glyphs
for its translation: (sans-serif, serif) per target language. Without any of them PyMuPDF's
built-in faces draw the text (Nimbus Sans, Charis SIL, Nimbus Mono; Droid Sans Fallback for CJK)."""

_SERIF_HINTS = ("times", "serif", "mincho", "song", "simsun", "georgia", "garamond", "cambria")
_MONO_HINTS = ("mono", "courier", "consolas")
_STYLE_SUFFIX = re.compile(
    r"(regular|roman|book|normal|medium|light|semibold|demibold|bold|black|heavy|italic|oblique"
    r"|mt|ps|psmt|w\d)+$"
)


@dataclass(frozen=True, slots=True)
class PdfStyle:
    """The visible properties that make a run a separate formatting span.

    The font is deliberately not part of it: PDF producers switch fonts inside one run for glyph
    fallback (PowerPoint draws one Chinese word with two fonts), which is not formatting.
    """

    size: float
    bold: bool
    italic: bool
    color: int
    underline: bool = False


def generic_family(font: str) -> str:
    name = font.casefold()
    if any(hint in name for hint in _MONO_HINTS):
        return "monospace"
    if any(hint in name for hint in _SERIF_HINTS) and "sans" not in name:
        return "serif"
    return "sans-serif"


@dataclass(frozen=True, slots=True)
class FontChoice:
    """What draws one style: a provisioned face (``face``) or a PyMuPDF built-in family."""

    family: str
    face: FontFace | None
    substituted: bool
    """True when the unit's own font is not the one used for its translation."""


def _key(name: str) -> str:
    return re.sub(r"[^0-9a-z]", "", name.casefold())


@dataclass
class FontResolver:
    """Maps PDF font names to provisioned faces and checks glyph coverage."""

    manifest: FontManifest | None
    _index: dict[str, list[FontFace]] = field(default_factory=dict[str, list[FontFace]])
    _coverage: dict[tuple[str, int], frozenset[int]] = field(
        default_factory=dict[tuple[str, int], frozenset[int]]
    )
    _blobs: dict[tuple[str, int], bytes] = field(default_factory=dict[tuple[str, int], bytes])

    def __post_init__(self) -> None:
        if self.manifest is None:
            return
        for face in self.manifest.faces:
            for name in (*face.names, *face.typographic_names):
                self._index.setdefault(_key(name), []).append(face)

    def lookup(self, name: str, *, bold: bool, italic: bool) -> FontFace | None:
        """The provisioned face for a PDF font or family name, closest in style."""
        base = _key(name)
        for key in dict.fromkeys((base, _STYLE_SUFFIX.sub("", base))):
            candidates = self._index.get(key) if key else None
            if candidates:
                weight = 700 if bold else 400
                return min(
                    candidates,
                    key=lambda f: ((f.bold != bold) + (f.italic != italic), abs(f.weight - weight)),
                )
        return None

    def covers(self, face: FontFace, text: str) -> bool:
        ident = (str(face.path), face.index)
        codepoints = self._coverage.get(ident)
        if codepoints is None:
            with TTFont(io.BytesIO(self.blob(face)), lazy=True) as font:
                codepoints = frozenset(font.getBestCmap() or {})
            self._coverage[ident] = codepoints
        return all(ord(ch) in codepoints for ch in text if not ch.isspace())

    def blob(self, face: FontFace) -> bytes:
        """The face as a standalone font file (collections are split into one face)."""
        ident = (str(face.path), face.index)
        data = self._blobs.get(ident)
        if data is None:
            raw = face.path.read_bytes()
            if face.path.suffix.lower() in (".ttc", ".otc"):
                with TTFont(io.BytesIO(raw), fontNumber=face.index) as font:
                    out = io.BytesIO()
                    font.save(out)
                    data = out.getvalue()
            else:
                data = raw
            self._blobs[ident] = data
        return data

    def choose(self, font: str, style: PdfStyle, text: str, target: Language) -> FontChoice:
        """Deterministic font for ``text`` originally drawn with ``font`` (ADR-014)."""
        own = self.lookup(font, bold=style.bold, italic=style.italic)
        if own is not None and self.covers(own, text):
            return FontChoice(own.family, own, substituted=False)
        generic = generic_family(font)
        sans, serif = TARGET_FAMILIES[target]
        for family in serif if generic == "serif" else sans:
            face = self.lookup(family, bold=style.bold, italic=style.italic)
            if face is not None and self.covers(face, text):
                return FontChoice(face.family, face, substituted=True)
        if own is not None:  # PyMuPDF's built-in fallback draws the glyphs it lacks
            return FontChoice(own.family, own, substituted=True)
        return FontChoice(generic, None, substituted=True)


def floor_scale(sizes: Iterable[float], options: FitOptions) -> float:
    """The smallest common scale that keeps every run at or above its ADR-012 floor."""
    scale = 0.0
    for size in sizes:
        if size <= options.min_size_pt:
            return 1.0  # a run at or below the absolute minimum is never shrunk
        scale = max(scale, max(options.min_size_pt, options.min_scale * size) / size)
    return min(1.0, scale) if scale else 1.0


def _overlaps_rows(a: Box, b: Box) -> bool:
    return a[1] < b[3] and a[3] > b[1]


def _intersects(a: Box, b: Box) -> bool:
    return a[0] < b[2] and a[2] > b[0] and a[1] < b[3] and a[3] > b[1]


def _contains(outer: Box, inner: Box, tolerance: float = 1.0) -> bool:
    return (
        outer[0] <= inner[0] + tolerance
        and outer[1] <= inner[1] + tolerance
        and outer[2] >= inner[2] - tolerance
        and outer[3] >= inner[3] - tolerance
    )


def _area(box: Box) -> float:
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def container_for(unit: Box, boxes: Sequence[Box]) -> Box | None:
    """The smallest filled or outlined box that encloses ``unit`` (a shape, a table cell)."""
    enclosing = [b for b in boxes if _contains(b, unit)]
    return min(enclosing, key=_area) if enclosing else None


def page_bounds(width: float, height: float, text: Sequence[Box]) -> Box:
    """The area free-standing text may use: the page within its margins."""
    return (
        min([PAGE_MARGIN_PT, *(b[0] for b in text)]),
        min([PAGE_MARGIN_PT, *(b[1] for b in text)]),
        max([width - PAGE_MARGIN_PT, *(b[2] for b in text)]),
        max([height - PAGE_MARGIN_PT, *(b[3] for b in text)]),
    )


def alignment(lines: Sequence[Box], container: Box | None, page_width: float) -> Align:
    """Horizontal alignment from the lines' positions (and their box, for a single line)."""
    if len(lines) > 1:
        lefts = [b[0] for b in lines]
        rights = [b[2] for b in lines]
        centers = [(b[0] + b[2]) / 2 for b in lines]
        if max(lefts) - min(lefts) <= ALIGN_TOLERANCE_PT:
            return "left"
        if max(centers) - min(centers) <= ALIGN_TOLERANCE_PT:
            return "center"
        if max(rights) - min(rights) <= ALIGN_TOLERANCE_PT:
            return "right"
        return "left"
    x0, _, x1, _ = lines[0]
    if container is not None:
        left_gap, right_gap = x0 - container[0], container[2] - x1
        width = container[2] - container[0]
        if left_gap > 3.0 and abs(left_gap - right_gap) <= max(2.0, 0.02 * width):
            return "center"
        if left_gap > right_gap + 6.0 and right_gap <= 2 * MAX_INSET_PT:
            return "right"
        return "left"
    center = (x0 + x1) / 2
    if abs(center - page_width / 2) <= 0.01 * page_width and x0 > 0.15 * page_width:
        return "center"
    return "left"


def region_for(
    unit: Box,
    align: Align,
    container: Box | None,
    obstacles: Sequence[Box],
    bounds: Box,
) -> Box:
    """Where a translated unit may be laid out: its own box grown toward free space.

    Inside a box the unit may use the box minus the padding it had; free-standing text may use
    the page within its margins. Growth stops before other text, artwork or boxes (with a small
    gap); the region never becomes smaller than the unit's original extent. The unit keeps its
    top edge, and its left edge (left aligned), right edge (right aligned) or center.
    """
    x0, y0, x1, y1 = unit
    if container is not None:
        inset = min(x0 - container[0], container[2] - x1, y0 - container[1], container[3] - y1)
        inset = min(max(inset, 0.0), MAX_INSET_PT)
        left, right, bottom = container[0] + inset, container[2] - inset, container[3] - inset
    else:
        left, right, bottom = bounds[0], bounds[2], bounds[3]
    others = [o for o in obstacles if not _intersects(o, unit) and not _contains(o, unit)]
    for other in others:
        if _overlaps_rows(other, unit):
            if other[0] >= x1 - 0.5:
                right = min(right, other[0] - GAP_PT)
            elif other[2] <= x0 + 0.5:
                left = max(left, other[2] + GAP_PT)
    left, right = min(left, x0), max(right, x1)
    if align == "left":
        left = x0
    elif align == "right":
        right = x1
    else:
        center = (x0 + x1) / 2
        half = min(center - left, right - center)
        left, right = center - half, center + half
    for other in others:
        if other[1] >= y1 - 0.5 and other[0] < right and other[2] > left:
            bottom = min(bottom, other[1] - GAP_PT)
    return (left, y0, right, max(bottom, y1))


def unit_html(
    nodes: Sequence[Inline],
    styles: Sequence[PdfStyle],
    families: dict[int, str],
    align: Align,
    line_height: float | None,
    scale: float = 1.0,
) -> str:
    """HTML for a translated unit: one span per run with its font, size, weight and color."""
    parts: list[str] = []

    def emit(items: Sequence[Inline]) -> None:
        for node in items:
            if isinstance(node, Text | Keep):
                style = styles[node.style]
                css = [
                    f"font-family:{families[node.style]}",
                    f"font-size:{style.size * scale:.2f}pt",
                    f"font-weight:{'bold' if style.bold else 'normal'}",
                    f"font-style:{'italic' if style.italic else 'normal'}",
                    f"color:#{style.color & 0xFFFFFF:06x}",
                ]
                if style.underline:
                    css.append("text-decoration:underline")
                parts.append(f'<span style="{";".join(css)}">{html.escape(node.text)}</span>')
            elif isinstance(node, Wrap):
                emit(node.children)

    emit(nodes)
    spacing = f"line-height:{line_height:.3f};" if line_height is not None else ""
    return f'<div style="text-align:{align};{spacing}">{"".join(parts)}</div>'


def font_css(faces: dict[str, FontFace], resolver: FontResolver) -> tuple[str, pymupdf.Archive]:
    """``@font-face`` rules and the archive holding the provisioned faces they name."""
    archive = pymupdf.Archive()
    rules: list[str] = []
    for family, face in faces.items():
        filename = f"{family}.ttf"
        archive.add((resolver.blob(face), filename))
        rules.append(f"@font-face {{font-family: {family}; src: url({filename});}}")
    rules.append("* {margin: 0; padding: 0;}")
    return "\n".join(rules), archive


@dataclass(frozen=True, slots=True)
class Placement:
    """How one unit was written: the rectangle used, the common scale and the height used."""

    rect: Box
    scale: float
    used_height: float
    fitted: bool
    """False when the text overflows its region at the floor (ADR-012 unresolved)."""


def place_html(
    page: pymupdf.Page,
    rect: Box,
    build: Callable[[float], str],
    css: str,
    archive: pymupdf.Archive,
    scale_low: float,
    page_bottom: float,
) -> Placement:
    """Write the unit (``build(scale)`` gives its HTML) into ``rect``, shrinking to ``scale_low``.

    PyMuPDF writes nothing when content does not fit even at ``scale_low``, and text is never
    dropped: the unit then keeps its floor sizes and extends below its region toward
    ``page_bottom`` (unresolved, as overflow in Office). Only if even the rest of the page is too
    small does the writer shrink further, so that every word stays on the page.
    """
    writer: Any = page  # PyMuPDF annotates scale_low as int; it is a float in [0, 1]
    spare, scale = writer.insert_htmlbox(
        pymupdf.Rect(rect), build(1.0), css=css, archive=archive, scale_low=scale_low
    )
    if spare >= 0:
        return Placement(rect, scale, (rect[3] - rect[1]) - spare, fitted=True)
    extended = (rect[0], rect[1], rect[2], max(rect[3], page_bottom))
    floor = build(scale_low)
    for low in (1.0, 0.0):
        spare, scale = writer.insert_htmlbox(
            pymupdf.Rect(extended), floor, css=css, archive=archive, scale_low=low
        )
        if spare >= 0:
            used = (extended[3] - extended[1]) - spare
            return Placement(extended, scale_low * scale, used, fitted=False)
    raise InvalidDocumentError("a translated text unit could not be placed on its page")
