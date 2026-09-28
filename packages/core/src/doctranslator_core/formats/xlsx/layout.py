"""XLSX layout capability: changed cell text for the best-effort fit check (ADR-012).

A cell holding translatable text is a container. Its bounds come from the column width (merged
cells: the merged range) and, when the row has a custom height, the row height. Wrapped text breaks
at the width; unwrapped text is only horizontally constrained when it cannot spill into an empty
neighbour (non-empty neighbour or a merged range). Row heights, column widths, sheet names and
formulas are never changed. A fitted size is written to a cloned font and cell format used by that
cell alone, so cells sharing a style are unaffected. Rich-text runs with their own sizes are not
resized (unresolved).

Column widths are in characters of the default font's maximum digit width; this adapter estimates
that width as 7 px for an 11 pt default font, scaled by the default size (the value Excel uses for
its default Calibri and Aptos fonts), and leaves 2 px padding on each side. These are estimates.
"""

import copy
import re
from collections.abc import Sequence
from dataclasses import dataclass

from doctranslator_core.document import LayoutContainer, LayoutParagraph, LayoutRun
from doctranslator_core.formats._ooxml import Element, Package, qn

__all__ = ["XlsxLayout"]

PX_TO_PT = 0.75
DEFAULT_COLUMN_CHARS = 8.43
DEFAULT_ROW_PT = 15.0
CELL_PADDING_PT = 2 * PX_TO_PT
_REF = re.compile(r"([A-Z]+)(\d+)")


@dataclass
class _Cell:
    id: str
    part: str
    sheet: str
    ref: str
    element: Element
    item: Element
    """The shared-string ``s:si`` or inline ``s:is`` holding the text."""


def _column_index(letters: str) -> int:
    value = 0
    for letter in letters:
        value = value * 26 + (ord(letter) - 64)
    return value


def _split(ref: str) -> tuple[int, int]:
    match = _REF.fullmatch(ref)
    if match is None:
        raise ValueError(ref)
    return _column_index(match.group(1)), int(match.group(2))


class XlsxLayout:
    def __init__(self, package: Package, workbook: str, sheets: Sequence[tuple[str, str]]) -> None:
        self._package = package
        self._sheets = list(sheets)
        styles = next((r.target for r in package.related(workbook, "styles")), None)
        self._styles_part = styles
        self._cells: dict[str, _Cell] = {}
        self._clones: dict[tuple[int, float], int] = {}
        shared = next((r.target for r in package.related(workbook, "sharedStrings")), None)
        self._shared = package.xml(shared).findall(qn("s:si")) if shared else []

    # ---- styles ------------------------------------------------------------------------------

    def _styles(self) -> Element | None:
        return self._package.xml(self._styles_part) if self._styles_part else None

    def _fonts(self) -> list[Element]:
        styles = self._styles()
        fonts = styles.find(qn("s:fonts")) if styles is not None else None
        return fonts.findall(qn("s:font")) if fonts is not None else []

    def _xfs(self) -> list[Element]:
        styles = self._styles()
        xfs = styles.find(qn("s:cellXfs")) if styles is not None else None
        return xfs.findall(qn("s:xf")) if xfs is not None else []

    def _cell_font(self, style: int) -> tuple[Element | None, Element | None]:
        xfs = self._xfs()
        xf = xfs[style] if 0 <= style < len(xfs) else None
        fonts = self._fonts()
        font_id = int(xf.get("fontId", "0")) if xf is not None else 0
        font = fonts[font_id] if 0 <= font_id < len(fonts) else None
        return xf, font

    def _default_size(self) -> float:
        fonts = self._fonts()
        return _font_size(fonts[0]) if fonts else 11.0

    # ---- containers --------------------------------------------------------------------------

    def containers(self) -> list[LayoutContainer]:
        self._cells.clear()
        result: list[LayoutContainer] = []
        digit_px = round(7 * self._default_size() / 11)
        for name, part in self._sheets:
            root = self._package.xml(part)
            widths, default_width = _column_widths(root)
            rows = {int(r.get("r", "0")): r for r in root.iter(qn("s:row"))}
            default_row = _default_row_height(root)
            occupied = {
                str(c.get("r"))
                for c in root.iter(qn("s:c"))
                if c.find(qn("s:v")) is not None or c.find(qn("s:is")) is not None
            }
            merges = _merges(root)
            for cell in root.iter(qn("s:c")):
                item = self._text_item(cell)
                if item is None:
                    continue
                ref = str(cell.get("r", ""))
                try:
                    column, row = _split(ref)
                except ValueError:
                    continue
                container_id = f"{part}!{ref}"
                self._cells[container_id] = _Cell(container_id, part, name, ref, cell, item)
                result.append(
                    self._describe(
                        container_id,
                        name,
                        ref,
                        column,
                        row,
                        cell,
                        item,
                        widths,
                        default_width,
                        rows,
                        default_row,
                        occupied,
                        merges,
                        digit_px,
                    )
                )
        return result

    def _text_item(self, cell: Element) -> Element | None:
        if cell.find(qn("s:f")) is not None:
            return None
        kind = cell.get("t")
        if kind == "inlineStr":
            return cell.find(qn("s:is"))
        if kind == "s":
            value = cell.findtext(qn("s:v")) or ""
            if value.isdigit() and int(value) < len(self._shared):
                return self._shared[int(value)]
        return None

    def _describe(
        self,
        container_id: str,
        sheet: str,
        ref: str,
        column: int,
        row: int,
        cell: Element,
        item: Element,
        widths: dict[int, float],
        default_width: float,
        rows: dict[int, Element],
        default_row: float,
        occupied: set[str],
        merges: list[tuple[int, int, int, int]],
        digit_px: int,
    ) -> LayoutContainer:
        style = int(cell.get("s", "0"))
        xf, font = self._cell_font(style)
        alignment = xf.find(qn("s:alignment")) if xf is not None else None
        wrap = alignment is not None and alignment.get("wrapText") in ("1", "true")
        vertical = alignment is not None and (
            alignment.get("textRotation") not in (None, "0") or alignment.get("shrinkToFit") == "1"
        )
        merge = next((m for m in merges if m[0] <= column <= m[2] and m[1] <= row <= m[3]), None)
        first_col, first_row, last_col, last_row = merge or (column, row, column, row)
        width_pt = (
            sum(
                _chars_to_pt(widths.get(c, default_width), digit_px)
                for c in range(first_col, last_col + 1)
            )
            - 2 * CELL_PADDING_PT
        )
        custom = [rows.get(r) for r in range(first_row, last_row + 1)]
        heights = [
            float(r.get("ht", default_row)) if r is not None else default_row for r in custom
        ]
        fixed_height = merge is not None or any(
            r is not None and r.get("customHeight") in ("1", "true") for r in custom
        )
        constrained_width = (
            wrap or merge is not None or _neighbour_occupied(column, row, alignment, occupied)
        )
        runs = self._runs(item, font)
        paragraph = LayoutParagraph(
            runs=tuple(runs),
            end_run=LayoutRun(
                "",
                _font_size(font) if font is not None else 11.0,
                _font_name(font),
                _font_name(font),
            ),
        )
        unsupported = None
        if vertical:
            unsupported = "rotated_or_shrink_to_fit_cell"
        elif any(
            r.find(f"{qn('s:rPr')}/{qn('s:sz')}") is not None for r in item.findall(qn("s:r"))
        ):
            unsupported = "rich_text_sizes"
        return LayoutContainer(
            id=container_id,
            location=f'sheet "{sheet}" / {ref}',
            kind="cell",
            width_pt=width_pt if constrained_width else None,
            height_pt=sum(heights) if fixed_height else None,
            wrap=wrap,
            paragraphs=(paragraph,),
            unsupported=unsupported,
            line_metric="font",
        )

    def _runs(self, item: Element, font: Element | None) -> list[LayoutRun]:
        base_size = _font_size(font) if font is not None else 11.0
        base_name = _font_name(font)
        base_bold = _flag(font, "s:b")
        base_italic = _flag(font, "s:i")
        runs: list[LayoutRun] = []
        plain = item.find(qn("s:t"))
        if plain is not None:
            runs.append(
                LayoutRun(plain.text or "", base_size, base_name, base_name, base_bold, base_italic)
            )
        for run in item.findall(qn("s:r")):
            properties = run.find(qn("s:rPr"))
            size = properties.find(qn("s:sz")) if properties is not None else None
            name = properties.find(qn("s:rFont")) if properties is not None else None
            family = name.get("val") if name is not None else base_name
            runs.append(
                LayoutRun(
                    run.findtext(qn("s:t")) or "",
                    float(size.get("val", base_size)) if size is not None else base_size,
                    family,
                    family,
                    _flag(properties, "s:b") if properties is not None else base_bold,
                    _flag(properties, "s:i") if properties is not None else base_italic,
                )
            )
        return runs

    # ---- applying sizes ----------------------------------------------------------------------

    def apply_sizes(self, container_id: str, sizes: Sequence[Sequence[float]]) -> list[str]:
        """Give the cell its own font at the fitted size; returns the changed parts."""
        cell = self._cells[container_id]
        size = max(s for row in sizes for s in row)
        style = int(cell.element.get("s", "0"))
        key = (style, size)
        if key not in self._clones:
            self._clones[key] = self._clone_style(style, size)
        cell.element.set("s", str(self._clones[key]))
        return [cell.part] + ([self._styles_part] if self._styles_part else [])

    def _clone_style(self, style: int, size: float) -> int:
        styles = self._styles()
        assert styles is not None  # noqa: S101 - a cell style exists when fonts were described
        fonts_element = styles.find(qn("s:fonts"))
        xfs_element = styles.find(qn("s:cellXfs"))
        assert fonts_element is not None and xfs_element is not None  # noqa: S101
        xf, font = self._cell_font(style)
        new_font = copy.deepcopy(font) if font is not None else _empty_font(styles)
        size_element = new_font.find(qn("s:sz"))
        if size_element is None:
            size_element = new_font.makeelement(qn("s:sz"), {})
            new_font.insert(0, size_element)
        size_element.set("val", _format_size(size))
        fonts_element.append(new_font)
        fonts_element.set("count", str(len(fonts_element.findall(qn("s:font")))))
        new_xf = copy.deepcopy(xf) if xf is not None else xfs_element.makeelement(qn("s:xf"), {})
        new_xf.set("fontId", str(len(fonts_element.findall(qn("s:font"))) - 1))
        new_xf.set("applyFont", "1")
        xfs_element.append(new_xf)
        xfs_element.set("count", str(len(xfs_element.findall(qn("s:xf")))))
        return len(xfs_element.findall(qn("s:xf"))) - 1


def _empty_font(styles: Element) -> Element:
    return styles.makeelement(qn("s:font"), {})


def _format_size(size: float) -> str:
    return str(int(size)) if size == int(size) else f"{size:g}"


def _font_size(font: Element | None) -> float:
    size = font.find(qn("s:sz")) if font is not None else None
    return float(size.get("val", "11")) if size is not None else 11.0


def _font_name(font: Element | None) -> str | None:
    name = font.find(qn("s:name")) if font is not None else None
    return name.get("val") if name is not None else None


def _flag(element: Element | None, tag: str) -> bool:
    found = element.find(qn(tag)) if element is not None else None
    return found is not None and found.get("val", "1") not in ("0", "false")


def _chars_to_pt(chars: float, digit_px: int) -> float:
    pixels = int(((256 * chars + int(128 / digit_px)) / 256) * digit_px)
    return pixels * PX_TO_PT


def _column_widths(sheet: Element) -> tuple[dict[int, float], float]:
    widths: dict[int, float] = {}
    cols = sheet.find(qn("s:cols"))
    for col in cols.findall(qn("s:col")) if cols is not None else []:
        width = col.get("width")
        if width is None:
            continue
        for index in range(int(col.get("min", "1")), int(col.get("max", "1")) + 1):
            widths[index] = float(width)
    format_pr = sheet.find(qn("s:sheetFormatPr"))
    default = DEFAULT_COLUMN_CHARS
    if format_pr is not None and format_pr.get("defaultColWidth"):
        default = float(format_pr.get("defaultColWidth", DEFAULT_COLUMN_CHARS))
    return widths, default


def _default_row_height(sheet: Element) -> float:
    format_pr = sheet.find(qn("s:sheetFormatPr"))
    if format_pr is not None and format_pr.get("defaultRowHeight"):
        return float(format_pr.get("defaultRowHeight", DEFAULT_ROW_PT))
    return DEFAULT_ROW_PT


def _merges(sheet: Element) -> list[tuple[int, int, int, int]]:
    ranges: list[tuple[int, int, int, int]] = []
    merged = sheet.find(qn("s:mergeCells"))
    for merge in merged.findall(qn("s:mergeCell")) if merged is not None else []:
        parts = str(merge.get("ref", "")).split(":")
        if len(parts) != 2:
            continue
        try:
            (c1, r1), (c2, r2) = _split(parts[0]), _split(parts[1])
        except ValueError:
            continue
        ranges.append((c1, r1, c2, r2))
    return ranges


def _letters(column: int) -> str:
    letters = ""
    while column:
        column, remainder = divmod(column - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def _neighbour_occupied(
    column: int, row: int, alignment: Element | None, occupied: set[str]
) -> bool:
    """Would unwrapped text be clipped instead of spilling into the neighbouring cell?"""
    horizontal = alignment.get("horizontal", "general") if alignment is not None else "general"
    sides = {"right": [-1], "center": [-1, 1]}.get(horizontal, [1])
    return any(
        column + side >= 1 and f"{_letters(column + side)}{row}" in occupied for side in sides
    )
