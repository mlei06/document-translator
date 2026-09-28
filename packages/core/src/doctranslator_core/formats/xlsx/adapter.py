"""XLSX adapter: literal cell text through targeted edits (ADR-009).

Translates referenced shared strings (once each, however many cells use them) and inline strings,
keeping rich-text runs. Formulas, their cached values, numbers, dates, booleans, sheet names and
every untouched part are preserved. When the workbook has formulas, ``fullCalcOnLoad`` asks the
opening application to recalculate, and formulas whose string literals equal translated text are
reported per cell.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

from doctranslator_core.config import DocumentLimits
from doctranslator_core.document import LayoutContainer, Paragraph
from doctranslator_core.formats._ooxml import Element, Package, qn
from doctranslator_core.formats._ooxml.runs import StyleTable, clean_text
from doctranslator_core.formats.base import DocumentAdapter, LayoutSupport
from doctranslator_core.formats.xlsx.layout import XlsxLayout
from doctranslator_core.inline import Inline, Keep, Obj, Text, Wrap, plain_text
from doctranslator_core.types import (
    DiagnosticSeverity,
    DocumentDiagnostic,
    DocumentFormat,
    DocumentLimitError,
    InvalidDocumentError,
    Language,
)

__all__ = ["XlsxAdapter"]

EXCEL_CELL_LIMIT = 32_767
MAX_FORMULA_WARNINGS = 100
_XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
_LITERAL = re.compile(r'"((?:[^"]|"")*)"')


@dataclass
class _StringRef:
    """A shared-string item or an inline-string element, with the cells that show it."""

    part: str
    element: Element
    """``s:si`` or ``s:is``."""
    cells: list[str] = field(default_factory=list[str])
    source_text: str = ""


@dataclass
class _Sheet:
    name: str
    part: str


class XlsxAdapter(DocumentAdapter, LayoutSupport):
    format = DocumentFormat.XLSX

    def __init__(self, path: Path, limits: DocumentLimits) -> None:
        super().__init__()
        self.package = Package.open(path, limits)
        self._styles = StyleTable(frozenset(), frozenset())
        self._refs: list[_StringRef] = []
        self._paragraphs: list[Paragraph] = []
        self._formulas: list[tuple[str, str, str]] = []  # (sheet, cell, formula text)
        self._translated_sources: set[str] = set()
        self._workbook = ""
        self.sheets: list[_Sheet] = []
        try:
            self._scan()
            self._layout = XlsxLayout(
                self.package, self._workbook, [(s.name, s.part) for s in self.sheets]
            )
        except BaseException:
            self.package.close()
            raise

    # ---- reading -----------------------------------------------------------------------------

    def _scan(self) -> None:
        self._workbook = self.package.main_part()
        workbook = self.package.xml(self._workbook)
        rels = {r.id: r for r in self.package.relationships(self._workbook)}
        sheets_element = workbook.find(qn("s:sheets"))
        sheet_elements: list[Element] = list(sheets_element) if sheets_element is not None else []
        for sheet in sheet_elements:
            rel = rels.get(str(sheet.get(qn("r:id"), "")))
            if rel is None or rel.external or not self.package.has(rel.target):
                continue
            if rel.type.endswith("/worksheet"):
                self.sheets.append(_Sheet(str(sheet.get("name", "")), rel.target))
        shared_part = next(
            (r.target for r in self.package.related(self._workbook, "sharedStrings")), None
        )
        shared_items: list[Element] = []
        if shared_part is not None:
            shared_items = self.package.xml(shared_part).findall(qn("s:si"))
        shared_refs: dict[int, _StringRef] = {}
        for sheet in self.sheets:
            self._scan_sheet(sheet, shared_part, shared_items, shared_refs)
        for index in sorted(shared_refs):
            self._add(shared_refs[index])
        self._report_unsupported()

    def _scan_sheet(
        self,
        sheet: _Sheet,
        shared_part: str | None,
        shared_items: list[Element],
        shared_refs: dict[int, _StringRef],
    ) -> None:
        data = self.package.xml(sheet.part).find(qn("s:sheetData"))
        if data is None:
            return
        for cell in data.iter(qn("s:c")):
            reference = str(cell.get("r", ""))
            formula = cell.find(qn("s:f"))
            if formula is not None:
                self._formulas.append((sheet.name, reference, formula.text or ""))
                continue
            kind = cell.get("t")
            location = f'sheet "{sheet.name}" / {reference}'
            if kind == "s" and shared_part is not None:
                value = cell.find(qn("s:v"))
                try:
                    index = int((value.text or "") if value is not None else "")
                except ValueError as exc:
                    raise InvalidDocumentError(
                        f"invalid shared string index at {location}"
                    ) from exc
                if not 0 <= index < len(shared_items):
                    raise InvalidDocumentError(f"shared string index out of range at {location}")
                ref = shared_refs.setdefault(index, _StringRef(shared_part, shared_items[index]))
                ref.cells.append(location)
            elif kind == "inlineStr":
                inline = cell.find(qn("s:is"))
                if inline is not None:
                    self._add(_StringRef(sheet.part, inline, [location]))

    def _add(self, ref: _StringRef) -> None:
        nodes = self._nodes(ref.element)
        if not any(isinstance(n, Text) and n.text.strip() for n in nodes):
            return
        ref.source_text = plain_text(nodes)
        self._refs.append(ref)
        location = ref.cells[0]
        if len(ref.cells) > 1:
            location += f" (and {len(ref.cells) - 1} more cells)"
        self._paragraphs.append(Paragraph(len(self._refs) - 1, location, tuple(nodes)))

    def _nodes(self, item: Element) -> list[Inline]:
        nodes: list[Inline] = []
        for child in item:
            if child.tag == qn("s:t"):
                nodes.append(Text(child.text or "", self._styles.id_for(None)))
            elif child.tag == qn("s:r"):
                text = child.find(qn("s:t"))
                nodes.append(
                    Text(
                        (text.text or "") if text is not None else "",
                        self._styles.id_for(child.find(qn("s:rPr"))),
                    )
                )
        return nodes

    def _report_unsupported(self) -> None:
        drawings = sum(
            1
            for sheet in self.sheets
            for rel in self.package.related(sheet.part, "drawing")
            if any((t.text or "").strip() for t in self.package.xml(rel.target).iter(qn("a:t")))
        )
        comments = sum(len(self.package.related(sheet.part, "comments")) for sheet in self.sheets)
        if drawings:
            self._info(
                "drawing_text_not_translated",
                drawings,
                "Text in shapes and text boxes on sheets is not translated.",
            )
        if comments:
            self._info("comments_not_translated", comments, "Cell comments are not translated.")

    def _info(self, code: str, count: int, message: str) -> None:
        self.diagnostics.append(
            DocumentDiagnostic(
                code=code, severity=DiagnosticSeverity.INFO, message=message, count=count
            )
        )

    def paragraphs(self) -> list[Paragraph]:
        return list(self._paragraphs)

    # ---- writing -----------------------------------------------------------------------------

    def apply(self, paragraph_id: int, nodes: Sequence[Inline], target: Language) -> None:
        del target  # cell text carries no language tag
        ref = self._refs[paragraph_id]
        texts = [(clean_text(t), s) for t, s in _flat_texts(nodes) if t]
        if sum(len(t) for t, _ in texts) > EXCEL_CELL_LIMIT:
            raise DocumentLimitError(
                f"the translation of {ref.cells[0]} exceeds Excel's {EXCEL_CELL_LIMIT}-character "
                "cell limit"
            )
        item = ref.element
        keep = [c for c in item if c.tag not in (qn("s:t"), qn("s:r"))]  # phonetic runs, extensions
        for child in list(item):
            item.remove(child)
        plain_style = self._styles.id_for(None)
        if all(s == plain_style for _, s in texts):
            _append_text(item, "".join(t for t, _ in texts))
        else:
            for text, style in texts:
                run = etree.SubElement(item, qn("s:r"))
                properties = self._styles.template(style)
                if properties is not None:
                    run.append(properties)
                _append_text(run, text)
        for child in keep:
            item.append(child)
        self._translated_sources.add(ref.source_text)
        self.package.mark_modified(ref.part)

    def layout_containers(self) -> list[LayoutContainer]:
        return self._layout.containers()

    def apply_run_sizes(self, container_id: str, sizes: Sequence[Sequence[float]]) -> None:
        for part in self._layout.apply_sizes(container_id, sizes):
            self.package.mark_modified(part)

    def save(self, path: Path) -> None:
        if self._translated_sources and self._formulas:
            self._request_recalculation()
        self.package.save(path)

    def _request_recalculation(self) -> None:
        workbook = self.package.xml(self._workbook)
        calc = workbook.find(qn("s:calcPr"))
        if calc is None:
            calc = etree.Element(qn("s:calcPr"))
            _insert_calc_pr(workbook, calc)
        if calc.get("fullCalcOnLoad") != "1":
            calc.set("fullCalcOnLoad", "1")
            self.package.mark_modified(self._workbook)
        self._info(
            "formulas_recalculate_on_open",
            len(self._formulas),
            "The workbook has formulas. Spreadsheet applications recalculate them on "
            "open; cached values stay from before translation until the workbook is "
            "recalculated and saved.",
        )
        matches = [
            (sheet, cell)
            for sheet, cell, formula in self._formulas
            if {m.group(1).replace('""', '"') for m in _LITERAL.finditer(formula)}
            & self._translated_sources
        ]
        for sheet, cell in matches[:MAX_FORMULA_WARNINGS]:
            self.diagnostics.append(
                DocumentDiagnostic(
                    code="formula_literal_matches_translated_text",
                    severity=DiagnosticSeverity.WARNING,
                    location=f'sheet "{sheet}" / {cell}',
                    message="This formula compares against text that was translated; its "
                    "result can change after recalculation (formulas are not modified).",
                )
            )
        if len(matches) > MAX_FORMULA_WARNINGS:
            self.diagnostics.append(
                DocumentDiagnostic(
                    code="formula_literal_matches_translated_text",
                    severity=DiagnosticSeverity.WARNING,
                    message="More formulas compare against translated text than are listed.",
                    count=len(matches) - MAX_FORMULA_WARNINGS,
                )
            )

    def close(self) -> None:
        self.package.close()


def _flat_texts(nodes: Sequence[Inline]) -> list[tuple[str, int]]:
    out: list[tuple[str, int]] = []
    for node in nodes:
        match node:
            case Text(text=t, style=s) | Keep(text=t, style=s):
                out.append((t, s))
            case Wrap(children=children):
                out.extend(_flat_texts(children))
            case Obj():
                pass
    return out


def _append_text(parent: Element, text: str) -> None:
    element = etree.SubElement(parent, qn("s:t"))
    element.text = text
    if text != text.strip():
        element.set(_XML_SPACE, "preserve")


# calcPr's position in CT_Workbook: after definedNames, before oleSize and later elements.
_AFTER_CALC_PR = (
    "oleSize",
    "customWorkbookViews",
    "pivotCaches",
    "smartTagPr",
    "smartTagTypes",
    "webPublishing",
    "fileRecoveryPr",
    "webPublishObjects",
    "extLst",
)


def _insert_calc_pr(workbook: Element, calc: Element) -> None:
    for child in workbook:
        if isinstance(child.tag, str) and child.tag.rsplit("}", 1)[-1] in _AFTER_CALC_PR:
            child.addprevious(calc)
            return
    workbook.append(calc)
