"""PDF adapter (ADR-018): targeted text replacement that keeps every page's artwork.

Extraction reads PyMuPDF's text layout (blocks, lines, spans) and forms translation units:
paragraphs of lines that stack vertically, split at list markers and at lines that end short.
Lines side by side (table cells, separate shapes on one row) are separate units even when PyMuPDF
puts them in one block. Writing removes only the characters of translated units (and underlines
drawn under them) with redaction that keeps images and vector graphics, then places each
translation with PyMuPDF's HTML box layout in the space the unit may use, shrinking within the
ADR-012 floors. Links, annotations, images, drawings and untranslated text stay as they are.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportMissingTypeStubs=false, reportAttributeAccessIssue=false

import functools
import itertools
import re
import statistics
import unicodedata
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import pymupdf

from doctranslator_core.config import DocumentLimits
from doctranslator_core.document import Paragraph
from doctranslator_core.formats.base import DocumentAdapter, PlacementFit
from doctranslator_core.formats.pdf.layout import (
    BACKGROUND_SHARE,
    Align,
    Box,
    FontResolver,
    PdfStyle,
    Placement,
    alignment,
    container_for,
    floor_scale,
    font_css,
    page_bounds,
    place_html,
    region_for,
    unit_html,
)
from doctranslator_core.inline import Inline, Keep, Text, Wrap, plain_text
from doctranslator_core.types import (
    DiagnosticSeverity,
    DocumentDiagnostic,
    DocumentFormat,
    DocumentLimitError,
    Extent,
    FitEntry,
    FitOptions,
    FontFace,
    FontManifest,
    InvalidDocumentError,
    Language,
    NoExtractableTextError,
    UnsupportedDocumentError,
)

__all__ = ["PdfAdapter"]

_TEXT_FLAGS = (
    pymupdf.TEXT_PRESERVE_WHITESPACE | pymupdf.TEXT_MEDIABOX_CLIP | pymupdf.TEXT_DEHYPHENATE
)
"""Ligatures are expanded to their letters; images are not extracted with the text."""
_IMAGE_PAGE_SHARE = 0.5
"""A page whose images cover this share of it gets an untranslated-image-content warning."""
_MAX_LOCATED = 100
# Bullets, dashes and numbers followed by a space, and CJK enumerations.
_LIST_MARKER = re.compile(
    r"^\s*(?:[•·▪■□◦●○‣∙➢►▶✓※]|[\-–—*](?=\s)|\(?\d{1,3}[.)](?=\s)|\d{1,3}、"  # noqa: RUF001
    r"|（[0-9一二三四五六七八九十]{1,3}）)"  # noqa: RUF001
)


def _is_cjk(ch: str) -> bool:
    code = ord(ch)
    return (
        0x3000 <= code <= 0x30FF
        or 0x3400 <= code <= 0x9FFF
        or 0xF900 <= code <= 0xFAFF
        or 0xFF00 <= code <= 0xFFEF
    )


def _normalized(text: str) -> str:
    """Text for comparisons: compatibility forms folded (ligatures) and whitespace removed."""
    return "".join(unicodedata.normalize("NFKC", text).split())


def _box(value: Sequence[float]) -> Box:
    return (float(value[0]), float(value[1]), float(value[2]), float(value[3]))


def _union(boxes: Sequence[Box]) -> Box:
    return (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    )


def _font_name(name: str) -> str:
    """The PDF font name without a subset tag such as ``ABCDEF+``."""
    tag, plus, rest = name.partition("+")
    return rest if plus and len(tag) == 6 and tag.isupper() else name


@dataclass
class _Unit:
    id: int
    page: int
    location: str
    bbox: Box
    line_boxes: list[Box]
    span_boxes: list[Box]
    underline_boxes: list[Box]
    prefix: tuple[Inline, ...]
    """A leading list marker (bullet, number); written back as it is, never translated."""
    nodes: tuple[Inline, ...]
    fonts: dict[int, str]
    """The font drawing most of each style's text in this unit."""
    sizes: list[float]
    line_height: float | None
    source: str
    translated: tuple[Inline, ...] | None = None
    placed: Box | None = None


@dataclass
class _Page:
    width: float
    height: float
    units: list[_Unit] = field(default_factory=list[_Unit])
    kept: list[Box] = field(default_factory=list[Box])
    """Text that is not translated (rotated, unreadable) but must not be covered."""
    boxes: list[Box] = field(default_factory=list[Box])
    """Filled or outlined shapes that can enclose text (shapes, table cells)."""
    obstacles: list[Box] = field(default_factory=list[Box])
    """Artwork translated text must not grow over: drawings and images."""


class PdfAdapter(DocumentAdapter, PlacementFit):
    format = DocumentFormat.PDF

    def __init__(self, path: Path, limits: DocumentLimits) -> None:
        super().__init__()
        self._limits = limits
        try:
            self._doc = pymupdf.open(path, filetype="pdf")
        except Exception as exc:  # PyMuPDF raises several types for damaged files
            raise InvalidDocumentError("the PDF cannot be read") from exc
        try:
            self._check()
        except BaseException:
            self._doc.close()
            raise
        self._styles: list[PdfStyle] = []
        self._style_ids: dict[PdfStyle, int] = {}
        self._pages: dict[int, _Page] = {}
        self._units: list[_Unit] = []
        self._extracted = False
        self._target: Language | None = None

    def _check(self) -> None:
        doc = self._doc
        if doc.needs_pass or doc.is_encrypted:
            raise UnsupportedDocumentError("encrypted or password-protected PDFs are not supported")
        if doc.get_sigflags() > 0:
            raise UnsupportedDocumentError(
                "digitally signed PDFs are not supported: translating would invalidate the "
                "signature"
            )
        if doc.page_count == 0:
            raise InvalidDocumentError("the PDF has no pages")

    # Extraction

    def paragraphs(self) -> list[Paragraph]:
        if not self._extracted:
            self._extract()
        return [Paragraph(u.id, u.location, u.nodes) for u in self._units]

    def _extract(self) -> None:
        self._extracted = True
        characters = 0
        rotated: list[str] = []
        unreadable: list[str] = []
        for number in range(self._doc.page_count):
            page = self._doc[number]
            record = self._artwork(page)
            self._pages[number] = record
            rules = [b for b in record.obstacles if b[3] - b[1] <= 2.0 and b[2] - b[0] >= 2.0]
            layout = cast(dict[str, Any], page.get_text("dict", flags=_TEXT_FLAGS))
            for block in layout["blocks"]:
                if block.get("type") != 0:
                    continue
                lines = [line for line in block["lines"] if _line_text(line).strip()]
                characters += sum(len(_line_text(line).strip()) for line in lines)
                horizontal: list[dict[str, Any]] = []
                for line in lines:
                    dx, dy = line["dir"]
                    if abs(dy) > 0.01 or dx < 0:
                        record.kept.append(_box(line["bbox"]))
                        rotated.append(f"page {number + 1}")
                    else:
                        horizontal.append(line)
                for group in _paragraphs(horizontal):
                    unit = self._unit(number, len(record.units), group, rules)
                    if "�" in unit.source:
                        record.kept.append(unit.bbox)
                        unreadable.append(unit.location)
                        continue
                    record.units.append(unit)
                    self._units.append(unit)
                    if len(self._units) > self._limits.max_segments:
                        raise DocumentLimitError(
                            f"the PDF has more than {self._limits.max_segments} text units"
                        )
            self._image_warning(page, number)
        if characters == 0:
            raise NoExtractableTextError(
                "the PDF has no extractable text (scanned or image-only pages are not "
                "translated; OCR is not supported)"
            )
        self._located(
            rotated,
            "pdf_rotated_text_kept",
            "Rotated or vertical text is not translated and was left as it is.",
        )
        self._located(
            unreadable,
            "pdf_text_unreadable",
            "Text whose characters cannot be extracted (a font without a Unicode mapping) was "
            "left untranslated.",
        )

    def _artwork(self, page: pymupdf.Page) -> _Page:
        width, height = page.cropbox.width, page.cropbox.height
        record = _Page(width, height)
        background = BACKGROUND_SHARE * width * height
        for drawing in page.get_drawings():
            rect = _box(drawing["rect"])
            if (rect[2] - rect[0]) * (rect[3] - rect[1]) >= background:
                continue
            record.obstacles.append(rect)
            closed = any(item[0] in ("re", "qu") for item in drawing["items"])
            if drawing.get("fill") is not None or closed:
                record.boxes.append(rect)
        for info in page.get_image_info():
            rect = _box(info["bbox"])
            if (rect[2] - rect[0]) * (rect[3] - rect[1]) < background:
                record.obstacles.append(rect)
        return record

    def _unit(self, page: int, index: int, lines: list[dict[str, Any]], rules: list[Box]) -> _Unit:
        nodes: list[Inline] = []
        span_boxes: list[Box] = []
        underlines: list[Box] = []
        sizes: list[float] = []
        fonts: dict[int, Counter[str]] = {}
        previous = ""
        for line in lines:
            text = _line_text(line)
            # Lines of one unit join with a space, except around CJK text (no word spaces).
            first = text.lstrip()[:1]
            if previous and first and not previous[-1].isspace():
                last = nodes[-1]
                if not _is_cjk(previous[-1]) and not _is_cjk(first) and isinstance(last, Text):
                    _append(nodes, " ", last.style)
            for span in line["spans"]:
                if not span["text"]:
                    continue
                bbox = _box(span["bbox"])
                underline = _underline(span, bbox, rules)
                if underline is not None:
                    underlines.append(underline)
                style = self._style(span, underline is not None)
                _append(nodes, span["text"], style)
                sizes.append(self._styles[style].size)
                counter = fonts.setdefault(style, Counter())
                counter[_font_name(str(span["font"]))] += len(span["text"].strip())
                if span["text"].strip():
                    span_boxes.append(bbox)
            previous = text
        boxes = [_box(line["bbox"]) for line in lines]
        prefix, body = _split_marker(_strip_ends(nodes))
        return _Unit(
            id=len(self._units),
            page=page,
            location=f"page {page + 1}, text {index + 1}",
            bbox=_union(boxes),
            line_boxes=boxes,
            span_boxes=span_boxes,
            underline_boxes=underlines,
            prefix=prefix,
            nodes=body,
            fonts={style: counter.most_common(1)[0][0] for style, counter in fonts.items()},
            sizes=sizes,
            line_height=_line_height(lines),
            source=plain_text(nodes),
        )

    def _style(self, span: dict[str, Any], underline: bool) -> int:
        flags = int(span["flags"])
        style = PdfStyle(
            size=round(float(span["size"]), 2),
            bold=bool(flags & pymupdf.TEXT_FONT_BOLD) or "bold" in str(span["font"]).casefold(),
            italic=bool(flags & pymupdf.TEXT_FONT_ITALIC),
            color=int(span["color"]),
            underline=underline,
        )
        ident = self._style_ids.get(style)
        if ident is None:
            ident = len(self._styles)
            self._styles.append(style)
            self._style_ids[style] = ident
        return ident

    def _image_warning(self, page: pymupdf.Page, number: int) -> None:
        area = page.rect.width * page.rect.height
        covered = 0.0
        for info in page.get_image_info():
            rect = pymupdf.Rect(info["bbox"]) & page.rect
            covered += rect.width * rect.height if rect.is_valid else 0.0
        if area > 0 and covered / area >= _IMAGE_PAGE_SHARE:
            self.diagnostics.append(
                DocumentDiagnostic(
                    code="untranslated_image_content",
                    severity=DiagnosticSeverity.WARNING,
                    location=f"page {number + 1}",
                    message="This page is mostly images (for example a scan). Text inside "
                    "images is not translated (no OCR).",
                )
            )

    def _located(self, locations: list[str], code: str, message: str) -> None:
        for location in list(dict.fromkeys(locations))[:_MAX_LOCATED]:
            self.diagnostics.append(
                DocumentDiagnostic(
                    code=code,
                    severity=DiagnosticSeverity.WARNING,
                    location=location,
                    message=message,
                )
            )

    # Writing

    def apply(self, paragraph_id: int, nodes: Sequence[Inline], target: Language) -> None:
        self._units[paragraph_id].translated = tuple(nodes)
        self._target = target

    def place(self, options: FitOptions, fonts: FontManifest | None) -> list[FitEntry | None]:
        changed = [u for u in self._units if u.translated is not None]
        if not changed:
            return []
        resolver = FontResolver(fonts)
        outcomes: list[FitEntry | None] = []
        substituted = 0
        for number in sorted({u.page for u in changed}):
            page_outcomes, page_substituted = self._place_page(
                self._doc[number], self._pages[number], options, resolver
            )
            outcomes.extend(page_outcomes)
            substituted += page_substituted
        if substituted:
            self.diagnostics.append(
                DocumentDiagnostic(
                    code="pdf_font_substituted",
                    severity=DiagnosticSeverity.INFO,
                    message="Some translated text uses a substitute font because the original "
                    "font is not provisioned or lacks characters the translation needs.",
                    count=substituted,
                )
            )
        return outcomes

    def _place_page(
        self, page: pymupdf.Page, record: _Page, options: FitOptions, resolver: FontResolver
    ) -> tuple[list[FitEntry | None], int]:
        text_boxes = [u.bbox for u in record.units] + record.kept
        bounds = page_bounds(record.width, record.height, text_boxes)
        changed = [u for u in record.units if u.translated is not None]
        plans: dict[int, tuple[Box, Align]] = {}
        for unit in changed:
            container = container_for(unit.bbox, record.boxes)
            align = alignment(unit.line_boxes, container, record.width)
            others = [b for b in text_boxes if b is not unit.bbox]
            others += [b for b in record.obstacles if b not in unit.underline_boxes]
            plans[unit.id] = (region_for(unit.bbox, align, container, others, bounds), align)

        # Redaction deletes links that overlap it; they are restored at their original places.
        page_links = page.get_links()
        # Underlines belong to the text they decorate: remove them first (only line art fully
        # inside the marked rectangles), then the characters, keeping every other graphic.
        underlines = [b for u in changed for b in u.underline_boxes]
        if underlines:
            for x0, y0, x1, y1 in underlines:
                page.add_redact_annot(pymupdf.Rect(x0 - 0.5, y0 - 0.5, x1 + 0.5, y1 + 0.5))
            page.apply_redactions(
                images=pymupdf.PDF_REDACT_IMAGE_NONE,
                graphics=pymupdf.PDF_REDACT_LINE_ART_REMOVE_IF_COVERED,
                text=pymupdf.PDF_REDACT_TEXT_NONE,
            )
        for unit in changed:
            for x0, y0, x1, y1 in unit.span_boxes:
                shrink = (y1 - y0) * 0.25  # the middle of the line: never a neighbouring line
                page.add_redact_annot(pymupdf.Rect(x0, y0 + shrink, x1, y1 - shrink))
        page.apply_redactions(
            images=pymupdf.PDF_REDACT_IMAGE_NONE,
            graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
            text=pymupdf.PDF_REDACT_TEXT_REMOVE,
        )
        remaining = {_link_key(link) for link in page.get_links()}
        for link in page_links:
            if _link_key(link) not in remaining:
                page.insert_link({k: v for k, v in link.items() if k not in ("xref", "id")})

        outcomes: list[FitEntry | None] = []
        substituted = 0
        target = self._target or Language.EN
        for unit in changed:
            nodes = (*unit.prefix, *(unit.translated or ()))
            families: dict[int, str] = {}
            faces: dict[str, FontFace] = {}
            unit_substituted = False
            for style_id, text in _style_texts(nodes).items():
                font = unit.fonts.get(style_id, "")
                choice = resolver.choose(font, self._styles[style_id], text, target)
                unit_substituted |= choice.substituted
                if choice.face is None:
                    families[style_id] = choice.family
                    continue
                name = next((n for n, f in faces.items() if f == choice.face), f"dtf{len(faces)}")
                faces[name] = choice.face
                families[style_id] = name
            substituted += unit_substituted
            css, archive = font_css(faces, resolver)
            region, align = plans[unit.id]
            build = functools.partial(
                unit_html, nodes, self._styles, families, align, unit.line_height
            )
            placement = place_html(
                page,
                region,
                build,
                css,
                archive,
                floor_scale(unit.sizes, options),
                record.height - 2.0,
            )
            unit.placed = placement.rect
            outcomes.append(_entry(unit, region, placement))
        return outcomes, substituted

    def save(self, path: Path) -> None:
        if any(u.placed is not None for u in self._units):
            self._doc.subset_fonts()
        self._doc.save(path, garbage=3, deflate=True)

    def verify_output(self, reopened: DocumentAdapter) -> None:
        """Page geometry unchanged; every translation present; no source text left behind."""
        if not isinstance(reopened, PdfAdapter):
            raise InvalidDocumentError("the written output is not a PDF")
        out = reopened._doc
        if out.page_count != self._doc.page_count:
            raise InvalidDocumentError("the written PDF has a different number of pages")
        for number, record in self._pages.items():
            before, after = self._doc[number], out[number]
            if before.cropbox != after.cropbox or before.rotation != after.rotation:
                raise InvalidDocumentError(f"page {number + 1} changed size or rotation")
            if not any(u.translated is not None for u in record.units):
                continue
            text = _normalized(cast(str, after.get_text("text", flags=_TEXT_FLAGS)))
            for unit in record.units:
                if unit.translated is None:
                    if _normalized(unit.source) not in text:
                        raise InvalidDocumentError(
                            f"untranslated text is missing from the output ({unit.location})"
                        )
                    continue
                translated = _normalized(plain_text((*unit.prefix, *unit.translated)))
                if translated not in text:
                    raise InvalidDocumentError(
                        f"a translation is missing from the output ({unit.location})"
                    )
                source = _normalized(unit.source)
                if len(source) >= 2 and source not in translated:
                    clip = pymupdf.Rect(unit.bbox)
                    remaining = _normalized(
                        cast(str, after.get_text("text", clip=clip, flags=_TEXT_FLAGS))
                    )
                    if source in remaining:
                        raise InvalidDocumentError(
                            f"source text is still present under a translation ({unit.location})"
                        )

    def close(self) -> None:
        self._doc.close()


def _link_key(link: dict[str, Any]) -> tuple[object, ...]:
    return (link.get("kind"), tuple(link["from"]), link.get("uri"), link.get("page"))


def _line_text(line: dict[str, Any]) -> str:
    return "".join(span["text"] for span in line["spans"])


def _paragraphs(lines: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Group a block's lines into paragraphs.

    A line continues the previous paragraph only if it sits below that paragraph's last line,
    overlaps it horizontally, is at most one line height away, does not start with a list
    marker, and the previous line was full (it reached the block's right edge, so it wrapped).
    """
    if not lines:
        return []
    right = max(_box(line["bbox"])[2] for line in lines)
    groups: list[list[dict[str, Any]]] = []
    for line in lines:
        x0, y0, x1, _ = _box(line["bbox"])
        if groups:
            last = groups[-1][-1]
            lx0, ly0, lx1, ly1 = _box(last["bbox"])
            height = ly1 - ly0
            size = max(float(span["size"]) for span in last["spans"])
            below = y0 >= ly1 - 0.5 * height
            overlaps = x0 < lx1 and x1 > lx0
            close = y0 - ly1 <= height
            full = lx1 >= right - max(3 * size, 0.15 * (right - lx0))
            marker = _LIST_MARKER.match(_line_text(line)) is not None
            if below and overlaps and close and full and not marker:
                groups[-1].append(line)
                continue
        groups.append([line])
    return groups


def _underline(span: dict[str, Any], bbox: Box, rules: list[Box]) -> Box | None:
    """A thin horizontal line drawn just below the span's baseline, spanning most of it."""
    baseline = float(span["origin"][1])
    size = float(span["size"])
    width = bbox[2] - bbox[0]
    for rule in rules:
        overlap = min(rule[2], bbox[2]) - max(rule[0], bbox[0])
        if (
            baseline - 1.0 <= rule[1]
            and rule[3] <= baseline + 0.35 * size
            and overlap >= 0.5 * width
            and rule[2] - rule[0] <= width + size
        ):
            return rule
    return None


def _line_height(lines: list[dict[str, Any]]) -> float | None:
    """Line pitch over font size for multi-line units, so wrapped text keeps its spacing."""
    if len(lines) < 2:
        return None
    baselines = [float(line["spans"][0]["origin"][1]) for line in lines]
    pitches = [b - a for a, b in itertools.pairwise(baselines) if b > a]
    size = max(float(span["size"]) for line in lines for span in line["spans"])
    if not pitches or size <= 0:
        return None
    return min(3.0, max(0.8, statistics.median(pitches) / size))


def _append(nodes: list[Inline], text: str, style: int) -> None:
    last = nodes[-1] if nodes else None
    if isinstance(last, Text) and last.style == style:
        nodes[-1] = Text(last.text + text, style)
    else:
        nodes.append(Text(text, style))


def _strip_ends(nodes: list[Inline]) -> list[Inline]:
    """Drop whitespace-only runs at either end; they carry no translatable content."""
    result = list(nodes)
    while result and isinstance(result[0], Text) and not result[0].text.strip():
        result.pop(0)
    while result and isinstance(result[-1], Text) and not result[-1].text.strip():
        result.pop()
    return result


def _split_marker(nodes: list[Inline]) -> tuple[tuple[Inline, ...], tuple[Inline, ...]]:
    """Separate a leading list marker and the space after it from the paragraph text."""
    first = nodes[0] if nodes else None
    if not isinstance(first, Text):
        return (), tuple(nodes)
    match = _LIST_MARKER.match(first.text)
    if match is None:
        return (), tuple(nodes)
    end = match.end()
    while end < len(first.text) and first.text[end].isspace():
        end += 1
    rest = first.text[end:]
    if not rest.strip() and len(nodes) == 1:
        return (), tuple(nodes)  # the marker is all there is: leave the text to the pipeline
    prefix = Text(first.text[:end], first.style)
    body = [Text(rest, first.style), *nodes[1:]] if rest else nodes[1:]
    return (prefix,), tuple(body)


def _style_texts(nodes: Sequence[Inline]) -> dict[int, str]:
    texts: dict[int, str] = {}

    def walk(items: Sequence[Inline]) -> None:
        for node in items:
            if isinstance(node, Text | Keep):
                texts[node.style] = texts.get(node.style, "") + node.text
            elif isinstance(node, Wrap):
                walk(node.children)

    walk(nodes)
    return texts


def _entry(unit: _Unit, region: Box, placement: Placement) -> FitEntry | None:
    """``None`` when the translation fit at its original sizes."""
    if placement.fitted and placement.scale >= 0.999:
        return None
    rect = placement.rect
    return FitEntry(
        location=unit.location,
        kind="text",
        status="adjusted" if placement.fitted else "unresolved",
        reason="shrunk_to_fit" if placement.fitted else "overflow_at_floor",
        original_sizes_pt=[round(s, 2) for s in unit.sizes],
        final_sizes_pt=[round(s * placement.scale, 2) for s in unit.sizes],
        allowed=Extent(width_pt=region[2] - region[0], height_pt=region[3] - region[1]),
        original_extent=Extent(
            width_pt=unit.bbox[2] - unit.bbox[0], height_pt=unit.bbox[3] - unit.bbox[1]
        ),
        translated_extent=None,
        final_extent=Extent(width_pt=rect[2] - rect[0], height_pt=placement.used_height),
    )
