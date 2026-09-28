# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportUnknownParameterType=false
# pyright: reportMissingTypeStubs=false, reportAttributeAccessIssue=false
# ruff: noqa: RUF001 - the line-breaking tables are CJK punctuation by design
"""Text measurement with real font metrics and line wrapping (P3, ADR-012, ``harfbuzz-v1``).

Characters are shaped with HarfBuzz in the font the document names for their script (Latin font for
non-CJK text, East Asian font for Han, kana and full-width forms). Lines wrap greedily at break
opportunities: after spaces and hyphens, between CJK characters except before closing punctuation
or after opening punctuation, and between characters when a single word is wider than the line.
A glyph that no named font contains, or a font that is not provisioned, makes the container
unmeasurable: no dimension is invented.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from functools import cache

import uharfbuzz as hb

from doctranslator_core.document import LayoutContainer, LayoutParagraph, LayoutRun
from doctranslator_core.fit.fonts import FontLibrary, LoadedFont

__all__ = ["Measured", "Unmeasurable", "is_east_asian", "measure"]

_NO_BREAK_BEFORE = frozenset(
    "、。，．・：；？！）」』】〕〉》〗〙〛｝］｠゛゜ー々ゝゞヽヾぁぃぅぇぉっゃゅょゎゕゖァィゥェォッャュョヮヵヶ"
    "…‥’”,.;:!?)]}%"
)
_HANGING = frozenset("、。，．")
"""Full-width closing marks that may hang past the right margin."""
_NO_BREAK_AFTER = frozenset("（「『【〔〈《〖〘〚｛［｟‘“([{")


_FEATURES = {"kern": False, "liga": False, "clig": False}
"""Office applications apply neither pair kerning nor standard ligatures by default."""


class Unmeasurable(Exception):  # noqa: N818 - a measurement outcome, reported not raised to users
    """The container cannot be measured with the provisioned fonts."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class Measured:
    width_pt: float
    """Widest line including its start offset."""
    height_pt: float
    lines: int


def is_east_asian(ch: str) -> bool:
    o = ord(ch)
    return (
        0x1100 <= o <= 0x11FF
        or 0x2E80 <= o <= 0x303F
        or 0x3040 <= o <= 0x30FF
        or 0x3100 <= o <= 0x31FF
        or 0x3400 <= o <= 0x4DBF
        or 0x4E00 <= o <= 0x9FFF
        or 0xAC00 <= o <= 0xD7AF
        or 0xF900 <= o <= 0xFAFF
        or 0xFE30 <= o <= 0xFE4F
        or 0xFF00 <= o <= 0xFFEF
        or 0x20000 <= o <= 0x2FA1F
    )


@dataclass(slots=True)
class _Glyphs:
    """Per-character layout data for one paragraph."""

    chars: list[str]
    advances: list[float]
    line_heights: list[float]
    """Single-spaced line height each character would give its line, in points."""


@cache
def _hb_font(path: str, index: int) -> hb.Font:
    with open(path, "rb") as handle:  # noqa: PTH123 - cached per font file
        blob = hb.Blob(handle.read())
    return hb.Font(hb.Face(blob, index))


def _advances(font: LoadedFont, text: str) -> list[float]:
    """Advance of each character in font units (ligature advances go to the first character)."""
    shaped = _hb_font(str(font.face.path), font.face.index)
    buffer = hb.Buffer()
    buffer.add_codepoints([ord(c) for c in text])
    buffer.guess_segment_properties()
    hb.shape(shaped, buffer, _FEATURES)
    result = [0.0] * len(text)
    infos = buffer.glyph_infos
    positions = buffer.glyph_positions
    for info, position in zip(infos, positions, strict=True):
        cluster = int(info.cluster)
        if 0 <= cluster < len(result):
            result[cluster] += float(position.x_advance)
    return result


def _font_for(ch: str, run: LayoutRun, library: FontLibrary) -> LoadedFont:
    """The font a document application uses for ``ch``: the script slot, then the other slot."""
    east = is_east_asian(ch)
    names = (run.east_asian_font, run.latin_font) if east else (run.latin_font, run.east_asian_font)
    if all(name is None for name in names):
        raise Unmeasurable("font_unknown")
    unavailable = False
    for name in names:
        if name is None:
            continue
        font = library.resolve(name, bold=run.bold, italic=run.italic)
        if font is None:
            unavailable = True
            continue
        if ord(ch) in font.codepoints or ch.isspace():
            return font
    raise Unmeasurable("font_unavailable" if unavailable else "missing_glyph")


def _glyphs(
    paragraph: LayoutParagraph, sizes: Sequence[float], library: FontLibrary, em: float | None
) -> _Glyphs:
    chars: list[str] = []
    advances: list[float] = []
    heights: list[float] = []
    for run, size in zip(paragraph.runs, sizes, strict=True):
        text = run.text
        index = 0
        while index < len(text):
            font = _font_for(text[index], run, library)
            end = index + 1
            while end < len(text) and _font_for(text[end], run, library) is font:
                end += 1
            chunk = text[index:end]
            scale = size / font.units_per_em
            advances.extend(a * scale for a in _advances(font, chunk))
            chars.extend(chunk)
            heights.extend([size * (em if em is not None else font.line_height_em)] * len(chunk))
            index = end
    return _Glyphs(chars, advances, heights)


def _break_allowed(chars: list[str], index: int) -> bool:
    """May a line break before ``chars[index]``?"""
    before, current = chars[index - 1], chars[index]
    if current in _NO_BREAK_BEFORE or before in _NO_BREAK_AFTER:
        return False
    if before.isspace() and not current.isspace():
        return True
    if before == "-" and current.isalnum():
        return True
    return is_east_asian(before) or is_east_asian(current)


def _empty_line_height(
    paragraph: LayoutParagraph, size: float, library: FontLibrary, em: float | None
) -> float:
    if em is not None:
        return size * em
    run = paragraph.end_run
    name = run.latin_font or run.east_asian_font
    if name is None:
        raise Unmeasurable("font_unknown")
    font = library.resolve(name, bold=run.bold, italic=run.italic)
    if font is None:
        raise Unmeasurable("font_unavailable")
    return size * font.line_height_em


def _spaced(paragraph: LayoutParagraph, single: float) -> float:
    if paragraph.line_spacing_pt is not None:
        return paragraph.line_spacing_pt
    return single * paragraph.line_spacing


def _layout_paragraph(
    paragraph: LayoutParagraph,
    sizes: Sequence[float],
    end_size: float,
    width: float | None,
    library: FontLibrary,
    em: float | None,
) -> tuple[float, float, int]:
    """(widest line incl. start offset, total height incl. spacing, line count)."""
    glyphs = _glyphs(paragraph, sizes, library, em)
    extra = paragraph.space_before_pt + paragraph.space_after_pt
    if not glyphs.chars:
        height = _spaced(paragraph, _empty_line_height(paragraph, end_size, library, em))
        return paragraph.first_line_start_pt, height + extra, 1
    lines: list[tuple[int, int]] = []
    start = 0
    while start < len(glyphs.chars):
        offset = paragraph.first_line_start_pt if not lines else paragraph.other_lines_start_pt
        available = None if width is None else width - offset - paragraph.right_indent_pt
        end = _line_end(glyphs, start, available)
        lines.append((start, end))
        start = end
        while start < len(glyphs.chars) and glyphs.chars[start] == " ":
            start += 1  # spaces at a wrap point are absorbed
    widest = 0.0
    height = 0.0
    for number, (first, last) in enumerate(lines):
        offset = paragraph.first_line_start_pt if number == 0 else paragraph.other_lines_start_pt
        visible = last
        while visible > first and glyphs.chars[visible - 1].isspace():
            visible -= 1
        widest = max(widest, offset + sum(glyphs.advances[first:visible]))
        height += _spaced(paragraph, max(glyphs.line_heights[first:last]))
    return widest, height + extra, len(lines)


def _line_end(glyphs: _Glyphs, start: int, available: float | None) -> int:
    """Exclusive end index of the line starting at ``start``."""
    count = len(glyphs.chars)
    if available is None:
        return count
    total = 0.0
    last_break: int | None = None
    for index in range(start, count):
        if index > start and _break_allowed(glyphs.chars, index):
            last_break = index
        total += glyphs.advances[index]
        if total > available and not glyphs.chars[index].isspace():
            if glyphs.chars[index] in _HANGING and index > start:
                # East Asian hanging punctuation: a closing mark may extend past the margin
                # instead of pushing the previous character to the next line (Office default).
                end = index + 1
                return end if end >= count or _break_allowed(glyphs.chars, end) else index
            if last_break is not None and last_break > start:
                return last_break
            return max(index, start + 1)  # a single word wider than the line wraps by character
    return count


def measure(
    container: LayoutContainer,
    library: FontLibrary,
    sizes: Sequence[Sequence[float]] | None = None,
) -> Measured:
    """Measure the container's text at ``sizes`` (per paragraph, per run; default: as described).

    Raises ``Unmeasurable`` when a font is not provisioned or a glyph is in no named font.
    """
    if container.unsupported is not None:
        raise Unmeasurable(container.unsupported)
    width = container.width_pt if container.wrap else None
    em = container.em_line_height if container.line_metric == "em" else None
    widest = 0.0
    height = 0.0
    lines = 0
    for index, paragraph in enumerate(container.paragraphs):
        run_sizes = list(sizes[index]) if sizes is not None else [r.size_pt for r in paragraph.runs]
        end_size = _end_size(paragraph, run_sizes)
        w, h, n = _layout_paragraph(paragraph, run_sizes, end_size, width, library, em)
        widest = max(widest, w)
        height += h
        lines += n
    return Measured(widest, height, lines)


def _end_size(paragraph: LayoutParagraph, run_sizes: Sequence[float]) -> float:
    """The paragraph mark scales with its runs when they are resized."""
    if not paragraph.runs or not run_sizes:
        return paragraph.end_run.size_pt
    original = max(r.size_pt for r in paragraph.runs)
    return paragraph.end_run.size_pt * (max(run_sizes) / original if original else 1.0)
