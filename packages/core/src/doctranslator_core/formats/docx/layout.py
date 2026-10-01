"""DOCX layout capability: text boxes and fixed-width table cells for fit (P3, README fit scope).

Body text reflows and is never a container. A container's runs get their effective properties
from document defaults, the paragraph style chain (``basedOn``), the character style chain and
direct formatting, with theme font references resolved. Word computes single line spacing from
each font's own metrics (``line_metric="font"``), and snaps lines to the section's document grid
when the grid type asks for it. A DrawingML text box's VML fallback copy receives the same sizes.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field, replace

from doctranslator_core.document import LayoutContainer, LayoutParagraph, LayoutPatch, LayoutRun
from doctranslator_core.fit.measure import is_east_asian
from doctranslator_core.formats._ooxml import Element, Package, qn

__all__ = ["DocxLayout"]

EMU_PER_PT = 12700.0
TWIPS_PER_PT = 20.0
DEFAULT_SIZE = 10.0
DEFAULT_BOX_INSETS = (91440, 45720, 91440, 45720)
DEFAULT_CELL_MARGIN_TWIPS = 108
_ON = {None, "1", "true", "on"}


@dataclass
class _Box:
    id: str
    part: str
    location: str
    kind: str
    content: Element
    """``w:txbxContent`` (text box) or ``w:tc`` (table cell)."""
    width_pt: float | None
    height_pt: float | None
    wrap: bool
    mirror: Element | None = None
    """The VML fallback ``w:txbxContent`` of a DrawingML text box."""
    unsupported: str | None = None


@dataclass
class _Mapping:
    runs: list[list[Element]] = field(default_factory=list[list[Element]])
    ends: list[Element | None] = field(default_factory=list[Element | None])
    mirror_runs: list[list[Element]] = field(default_factory=list[list[Element]])


class DocxLayout:
    def __init__(self, package: Package, stories: Sequence[str]) -> None:
        self._package = package
        self._stories = list(stories)
        main = package.main_part()
        self._styles = _Styles(package, main)
        self._theme = _theme_fonts(package, main)
        self._grid = _document_grid(package.xml(main))
        self._mappings: dict[str, _Mapping] = {}
        self._revision: dict[str, int] = {}
        self.boxes: dict[str, _Box] = {}

    # ---- containers --------------------------------------------------------------------------

    def containers(self) -> list[LayoutContainer]:
        self.boxes = {box.id: box for part in self._stories for box in self._find(part)}
        self._mappings.clear()
        return [self._describe(box) for box in self.boxes.values()]

    def _find(self, part: str) -> list[_Box]:
        root = self._package.xml(part)
        label = "body" if part == self._package.main_part() else part.rsplit("/", 1)[-1]
        boxes: list[_Box] = []
        for number, shape in enumerate(root.iter(qn("wps:wsp")), start=1):
            content = shape.find(f"{qn('wps:txbx')}/{qn('w:txbxContent')}")
            if content is None:
                continue
            width, height = _box_size(shape)
            body = shape.find(qn("wps:bodyPr"))
            insets = DEFAULT_BOX_INSETS
            wrap = True
            unsupported = None
            if body is not None:
                insets = tuple(
                    int(body.get(name, str(d)))
                    for name, d in zip(
                        ("lIns", "tIns", "rIns", "bIns"), DEFAULT_BOX_INSETS, strict=True
                    )
                )  # type: ignore[assignment]
                wrap = body.get("wrap", "square") != "none"
                if body.get("vert", "horz") != "horz":
                    unsupported = "vertical_text"
                if body.find(qn("a:spAutoFit")) is not None:
                    height = None  # Word grows the shape to fit its text
            boxes.append(
                _Box(
                    id=f"{part}#textbox{number}",
                    part=part,
                    location=f"{label} / text box {number}",
                    kind="text-box",
                    content=content,
                    width_pt=None
                    if width is None
                    else (width - insets[0] - insets[2]) / EMU_PER_PT,
                    height_pt=None
                    if height is None
                    else (height - insets[1] - insets[3]) / EMU_PER_PT,
                    wrap=wrap,
                    mirror=_vml_mirror(shape),
                    unsupported=unsupported if width is not None else "geometry_unknown",
                )
            )
        for table_number, table in enumerate(root.iter(qn("w:tbl")), start=1):
            if not _fixed_layout(table):
                continue
            margins = _cell_margins(table.find(qn("w:tblPr")))
            grid = [int(c.get(qn("w:w"), "0")) for c in table.iter(qn("w:gridCol"))]
            for r, row in enumerate(table.findall(qn("w:tr")), start=1):
                exact = _exact_height(row)
                column = 0
                for c, cell in enumerate(row.findall(qn("w:tc")), start=1):
                    span = int(_attr(cell.find(f"{qn('w:tcPr')}/{qn('w:gridSpan')}"), "0") or "1")
                    cell_margins = _cell_margins(cell.find(qn("w:tcPr")), margins)
                    width = _cell_width(cell, grid, column, span)
                    column += span
                    boxes.append(
                        _Box(
                            id=f"{part}#table{table_number}/r{r}c{c}",
                            part=part,
                            location=f"{label} / table {table_number} / row {r} / cell {c}",
                            kind="table-cell",
                            content=cell,
                            width_pt=None
                            if width is None
                            else (width - cell_margins[0] - cell_margins[1]) / TWIPS_PER_PT,
                            height_pt=exact,
                            wrap=True,
                            unsupported=None if width is not None else "geometry_unknown",
                        )
                    )
        return boxes

    def _describe(self, box: _Box) -> LayoutContainer:
        mapping = _Mapping()
        paragraphs: list[LayoutParagraph] = []
        paras = [p for p in box.content if p.tag == qn("w:p")]
        mirror_paras = (
            [p for p in box.mirror if p.tag == qn("w:p")] if box.mirror is not None else []
        )
        for index, para in enumerate(paras):
            layout, runs, end = self._paragraph(para, box.kind == "table-cell")
            paragraphs.append(layout)
            mapping.runs.append(runs)
            mapping.ends.append(end)
            mirror = mirror_paras[index] if index < len(mirror_paras) else None
            mapping.mirror_runs.append(
                [r for r in mirror.iter(qn("w:r")) if r.find(qn("w:t")) is not None]
                if mirror is not None
                else []
            )
        self._mappings[box.id] = mapping
        return LayoutContainer(
            id=box.id,
            location=box.location,
            kind=box.kind,
            width_pt=box.width_pt,
            height_pt=box.height_pt,
            wrap=box.wrap,
            paragraphs=tuple(paragraphs),
            unsupported=box.unsupported or _unvalidated(paragraphs),
            revision=self._revision.get(box.id, 0),
            line_metric="font",
        )

    def _paragraph(
        self, para: Element, in_table: bool
    ) -> tuple[LayoutParagraph, list[Element], Element | None]:
        p_pr = para.find(qn("w:pPr"))
        style_id = _attr(p_pr.find(qn("w:pStyle")) if p_pr is not None else None, None)
        paragraph_chain = self._styles.paragraph_chain(style_id, p_pr)
        run_elements: list[Element] = []
        runs: list[LayoutRun] = []
        for run in para.iter(qn("w:r")):
            if _inside_nested(run, para):
                continue
            text = "".join(
                "\t" if child.tag == qn("w:tab") else (child.text or "")
                for child in run
                if child.tag in (qn("w:t"), qn("w:tab"))
            )
            if not text:
                continue
            r_pr = run.find(qn("w:rPr"))
            runs.append(self._run(style_id, r_pr, text))
            run_elements.append(run)
        mark = p_pr.find(qn("w:rPr")) if p_pr is not None else None
        end_run = self._run(style_id, mark, "")
        spacing = _first(paragraph_chain, "w:spacing")
        before = _twips(spacing, "w:before")
        after = _twips(spacing, "w:after")
        line_multiple, line_exact, at_least = _line_rule(spacing)
        indent = _first(paragraph_chain, "w:ind")
        left = _twips(indent, "w:left") or _twips(indent, "w:start")
        right = _twips(indent, "w:right") or _twips(indent, "w:end")
        first = _twips(indent, "w:firstLine") - _twips(indent, "w:hanging")
        snap = self._grid if (in_table and _snaps(paragraph_chain)) else None
        layout = LayoutParagraph(
            runs=tuple(runs),
            end_run=end_run,
            line_spacing=line_multiple,
            line_spacing_pt=line_exact,
            space_before_pt=before,
            space_after_pt=after,
            first_line_start_pt=max(left + first, 0.0),
            other_lines_start_pt=max(left, 0.0),
            right_indent_pt=max(right, 0.0),
            line_minimum_pt=at_least,
            line_grid_pt=snap,
        )
        return layout, run_elements, mark

    def _run(self, style_id: str | None, r_pr: Element | None, text: str) -> LayoutRun:
        chain = self._styles.run_chain(style_id, r_pr)
        size = _value(chain, "w:sz")
        bold = _toggle(chain, "w:b")
        italic = _toggle(chain, "w:i")
        fonts = _first(chain, "w:rFonts")
        latin = self._font(fonts, "ascii")
        east = self._font(fonts, "eastAsia")
        if not east:
            lang = _first(chain, "w:lang")
            tag = (lang.get(qn("w:eastAsia")) or "") if lang is not None else ""
            script = "Jpan" if tag.lower().startswith("ja") else "Hans"
            if any(0x3040 <= ord(c) <= 0x30FF for c in text):
                script = "Jpan"
            east = self._theme.get(f"mn-{script}") or None
        return LayoutRun(
            text=text,
            size_pt=int(size) / 2 if size else DEFAULT_SIZE,
            latin_font=latin,
            east_asian_font=east,
            bold=bold,
            italic=italic,
        )

    def _font(self, fonts: Element | None, slot: str) -> str | None:
        if fonts is None:
            return None
        theme = fonts.get(qn(f"w:{slot}Theme"))
        if theme:
            key = {"major": "mj", "minor": "mn"}["major" if theme.startswith("major") else "minor"]
            kind = "ea" if slot == "eastAsia" else "lt"
            return self._theme.get(f"{key}-{kind}") or None
        return fonts.get(qn(f"w:{slot}")) or None

    # ---- applying sizes ----------------------------------------------------------------------

    def apply_patch(self, patch: LayoutPatch) -> None:
        if patch.operation != "fonts":
            raise ValueError("DOCX only supports explicit target font patches")
        before, after = patch.expected, patch.replacement
        permitted = replace(
            before,
            paragraphs=tuple(
                replace(
                    p,
                    runs=tuple(
                        replace(r, latin_font=n.latin_font, east_asian_font=n.east_asian_font)
                        for r, n in zip(p.runs, q.runs, strict=True)
                    ),
                )
                for p, q in zip(before.paragraphs, after.paragraphs, strict=True)
            ),
        )
        if permitted != after:
            raise ValueError("invalid font patch")
        mapping = self._mappings[before.id]
        for runs, mirrors, paragraph in zip(
            mapping.runs, mapping.mirror_runs, after.paragraphs, strict=True
        ):
            for elements in (runs, mirrors):
                for element, run in zip(elements, paragraph.runs, strict=False):
                    props = element.find(qn("w:rPr"))
                    if props is None:
                        props = element.makeelement(qn("w:rPr"), {})
                        element.insert(0, props)
                    fonts = props.find(qn("w:rFonts"))
                    if fonts is None:
                        fonts = props.makeelement(qn("w:rFonts"), {})
                        props.insert(0, fonts)
                    for slot, name in (
                        ("ascii", run.latin_font),
                        ("hAnsi", run.latin_font),
                        ("eastAsia", run.east_asian_font),
                    ):
                        if name:
                            fonts.set(qn("w:" + slot), name)
                            fonts.attrib.pop(qn("w:" + slot + "Theme"), None)

        self._revision[before.id] = before.revision + 1

    def apply_sizes(self, container_id: str, sizes: Sequence[Sequence[float]]) -> str:
        """Write sizes (half-points) to the runs and the VML mirror; returns the part."""
        mapping = self._mappings[container_id]
        for runs, end, mirror, run_sizes in zip(
            mapping.runs, mapping.ends, mapping.mirror_runs, sizes, strict=True
        ):
            for element, size in zip(runs, run_sizes, strict=True):
                _set_size(element, size)
            for element, size in zip(mirror, run_sizes, strict=False):
                _set_size(element, size)
            if end is not None and run_sizes:
                _set_size_on(end, max(run_sizes))
        return self.boxes[container_id].part


class _Styles:
    """Style lookup with ``basedOn`` inheritance and document defaults."""

    def __init__(self, package: Package, main: str) -> None:
        self._styles: dict[str, Element] = {}
        self._default_paragraph: str | None = None
        self._run_defaults: Element | None = None
        self._paragraph_defaults: Element | None = None
        for rel in package.related(main, "styles"):
            root = package.xml(rel.target)
            defaults = root.find(qn("w:docDefaults"))
            if defaults is not None:
                self._run_defaults = defaults.find(f"{qn('w:rPrDefault')}/{qn('w:rPr')}")
                self._paragraph_defaults = defaults.find(f"{qn('w:pPrDefault')}/{qn('w:pPr')}")
            for style in root.findall(qn("w:style")):
                style_id = style.get(qn("w:styleId"))
                if style_id:
                    self._styles[style_id] = style
                if style.get(qn("w:type")) == "paragraph" and style.get(qn("w:default")) in _ON - {
                    None
                }:
                    self._default_paragraph = style_id

    def _chain(self, style_id: str | None) -> list[Element]:
        chain: list[Element] = []
        seen: set[str] = set()
        while style_id and style_id in self._styles and style_id not in seen:
            seen.add(style_id)
            style = self._styles[style_id]
            chain.append(style)
            style_id = _attr(style.find(qn("w:basedOn")), None)
        return chain

    def paragraph_chain(self, style_id: str | None, p_pr: Element | None) -> list[Element]:
        """``w:pPr`` elements, highest priority first: direct, style chain, defaults."""
        chain: list[Element] = [p_pr] if p_pr is not None else []
        for style in self._chain(style_id or self._default_paragraph):
            properties = style.find(qn("w:pPr"))
            if properties is not None:
                chain.append(properties)
        if self._paragraph_defaults is not None:
            chain.append(self._paragraph_defaults)
        return chain

    def run_chain(self, style_id: str | None, r_pr: Element | None) -> list[Element]:
        """``w:rPr`` elements: direct, character style chain, paragraph style chain, defaults."""
        chain: list[Element] = [r_pr] if r_pr is not None else []
        character = _attr(r_pr.find(qn("w:rStyle")) if r_pr is not None else None, None)
        for source in (self._chain(character), self._chain(style_id or self._default_paragraph)):
            for style in source:
                properties = style.find(qn("w:rPr"))
                if properties is not None:
                    chain.append(properties)
        if self._run_defaults is not None:
            chain.append(self._run_defaults)
        return chain


def _theme_fonts(package: Package, main: str) -> dict[str, str]:
    fonts: dict[str, str] = {}
    for rel in package.related(main, "theme"):
        scheme = package.xml(rel.target).find(f"{qn('a:themeElements')}/{qn('a:fontScheme')}")
        if scheme is None:
            continue
        for prefix, tag in (("mj", "a:majorFont"), ("mn", "a:minorFont")):
            block = scheme.find(qn(tag))
            if block is None:
                continue
            latin, east = block.find(qn("a:latin")), block.find(qn("a:ea"))
            fonts[f"{prefix}-lt"] = latin.get("typeface", "") if latin is not None else ""
            fonts[f"{prefix}-ea"] = east.get("typeface", "") if east is not None else ""
            for font in block.findall(qn("a:font")):
                fonts[f"{prefix}-{font.get('script')}"] = font.get("typeface", "")
    return fonts


def _document_grid(document: Element) -> float | None:
    """Line pitch in points when the last section snaps lines to a grid."""
    sections = list(document.iter(qn("w:sectPr")))
    grid = sections[-1].find(qn("w:docGrid")) if sections else None
    if grid is None or grid.get(qn("w:type")) not in ("lines", "linesAndChars", "snapToChars"):
        return None
    pitch = grid.get(qn("w:linePitch"))
    return int(pitch) / TWIPS_PER_PT if pitch else None


def _unvalidated(paragraphs: list[LayoutParagraph]) -> str | None:
    """Word's layout of East Asian text did not match our model in validation (ADR-012), so a
    container holding any East Asian character is reported unresolved instead of guessed."""
    for paragraph in paragraphs:
        for run in paragraph.runs:
            if any(is_east_asian(ch) for ch in run.text):
                return "east_asian_layout_unvalidated"
    return None


def _box_size(shape: Element) -> tuple[float | None, float | None]:
    parent = shape.getparent()
    while parent is not None and parent.tag not in (qn("wp:anchor"), qn("wp:inline")):
        parent = parent.getparent()
    extent = parent.find(qn("wp:extent")) if parent is not None else None
    if extent is None:
        extent = shape.find(f"{qn('wps:spPr')}/{qn('a:xfrm')}/{qn('a:ext')}")
    if extent is None:
        return None, None
    return float(int(extent.get("cx", "0"))), float(int(extent.get("cy", "0")))


def _vml_mirror(shape: Element) -> Element | None:
    choice = shape.getparent()
    while choice is not None and choice.tag != qn("mc:Choice"):
        choice = choice.getparent()
    if choice is None:
        return None
    alternate = choice.getparent()
    fallback = alternate.find(qn("mc:Fallback")) if alternate is not None else None
    if fallback is None:
        return None
    return next(iter(fallback.iter(qn("w:txbxContent"))), None)


def _fixed_layout(table: Element) -> bool:
    layout = table.find(f"{qn('w:tblPr')}/{qn('w:tblLayout')}")
    return layout is not None and layout.get(qn("w:type")) == "fixed"


def _cell_margins(
    properties: Element | None, inherited: tuple[int, int] | None = None
) -> tuple[int, int]:
    left, right = inherited or (DEFAULT_CELL_MARGIN_TWIPS, DEFAULT_CELL_MARGIN_TWIPS)
    margins = properties.find(qn("w:tblCellMar")) if properties is not None else None
    if properties is not None and margins is None:
        margins = properties.find(qn("w:tcMar"))
    if margins is not None:
        for tag, current in (("left", left), ("start", left)):
            element = margins.find(qn(f"w:{tag}"))
            if element is not None and element.get(qn("w:type"), "dxa") == "dxa":
                left = int(element.get(qn("w:w"), str(current)))
        for tag, current in (("right", right), ("end", right)):
            element = margins.find(qn(f"w:{tag}"))
            if element is not None and element.get(qn("w:type"), "dxa") == "dxa":
                right = int(element.get(qn("w:w"), str(current)))
    return left, right


def _cell_width(cell: Element, grid: list[int], column: int, span: int) -> float | None:
    width = cell.find(f"{qn('w:tcPr')}/{qn('w:tcW')}")
    if (
        width is not None
        and width.get(qn("w:type"), "dxa") == "dxa"
        and int(width.get(qn("w:w"), "0"))
    ):
        return float(int(width.get(qn("w:w"), "0")))
    if grid and column + span <= len(grid):
        return float(sum(grid[column : column + span]))
    return None


def _exact_height(row: Element) -> float | None:
    height = row.find(f"{qn('w:trPr')}/{qn('w:trHeight')}")
    if height is None or height.get(qn("w:hRule")) != "exact":
        return None
    return int(height.get(qn("w:val"), "0")) / TWIPS_PER_PT


def _inside_nested(run: Element, para: Element) -> bool:
    """A run inside a nested text box of this paragraph belongs to the text box, not here."""
    parent = run.getparent()
    while parent is not None and parent is not para:
        if parent.tag in (qn("w:txbxContent"), qn("w:p")):
            return True
        parent = parent.getparent()
    return False


def _attr(element: Element | None, default: str | None) -> str | None:
    if element is None:
        return default
    return element.get(qn("w:val"), default)


def _first(chain: list[Element], tag: str) -> Element | None:
    for element in chain:
        found = element.find(qn(tag))
        if found is not None:
            return found
    return None


def _value(chain: list[Element], tag: str) -> str | None:
    found = _first(chain, tag)
    return found.get(qn("w:val")) if found is not None else None


def _toggle(chain: list[Element], tag: str) -> bool:
    found = _first(chain, tag)
    return found is not None and found.get(qn("w:val")) in _ON


def _twips(element: Element | None, attribute: str) -> float:
    if element is None:
        return 0.0
    value = element.get(qn(attribute))
    return int(value) / TWIPS_PER_PT if value and value.lstrip("-").isdigit() else 0.0


def _line_rule(spacing: Element | None) -> tuple[float, float | None, float | None]:
    """(multiple of single spacing, exact line height, minimum line height)."""
    if spacing is None or spacing.get(qn("w:line")) is None:
        return 1.0, None, None
    line = int(spacing.get(qn("w:line"), "240"))
    rule = spacing.get(qn("w:lineRule"), "auto")
    if rule == "exact":
        return 1.0, line / TWIPS_PER_PT, None
    if rule == "atLeast":
        return 1.0, None, line / TWIPS_PER_PT
    return line / 240, None, None


def _snaps(chain: list[Element]) -> bool:
    found = _first(chain, "w:snapToGrid")
    return found is None or found.get(qn("w:val")) in _ON


def _set_size(run: Element, size: float) -> None:
    properties = run.find(qn("w:rPr"))
    if properties is None:
        properties = run.makeelement(qn("w:rPr"), {})
        run.insert(0, properties)
    _set_size_on(properties, size)


def _set_size_on(properties: Element, size: float) -> None:
    half_points = str(round(size * 2))
    for tag in ("w:sz", "w:szCs"):
        element = properties.find(qn(tag))
        if element is None:
            element = properties.makeelement(qn(tag), {})
            _insert_ordered(properties, element)
        element.set(qn("w:val"), half_points)


# CT_RPr child order (subset around sz/szCs): elements after szCs must stay after it.
_AFTER_SIZE = {
    "highlight",
    "u",
    "effect",
    "bdr",
    "shd",
    "fitText",
    "vertAlign",
    "rtl",
    "cs",
    "em",
    "lang",
    "eastAsianLayout",
    "specVanish",
    "oMath",
    "rPrChange",
}


def _insert_ordered(properties: Element, element: Element) -> None:
    for child in properties:
        if isinstance(child.tag, str) and child.tag.rsplit("}", 1)[-1] in _AFTER_SIZE:
            child.addprevious(element)
            return
    properties.append(element)
