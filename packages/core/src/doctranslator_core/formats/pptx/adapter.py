"""PPTX adapter: targeted edits of slide, notes, layout and master parts (ADR-011)."""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from lxml import etree

from doctranslator_core.config import DocumentLimits
from doctranslator_core.document import LayoutContainer, Paragraph
from doctranslator_core.formats._ooxml import Element, Package, qn
from doctranslator_core.formats._ooxml.runs import StyleTable, clean_text
from doctranslator_core.formats.base import DocumentAdapter, LayoutSupport
from doctranslator_core.formats.pptx.layout import PptxLayout
from doctranslator_core.formats.pptx.model import Container
from doctranslator_core.inline import Inline, Keep, Obj, Text, Wrap
from doctranslator_core.types import (
    DiagnosticSeverity,
    DocumentDiagnostic,
    DocumentFormat,
    Language,
)

__all__ = ["PptxAdapter"]

_LANG_TAGS = {
    Language.ZH: "zh-CN",
    Language.EN: "en-US",
    Language.JA: "ja-JP",
    Language.ES: "es-ES",
}
_CHART_URI = "http://schemas.openxmlformats.org/drawingml/2006/chart"
_DIAGRAM_URI = "http://schemas.openxmlformats.org/drawingml/2006/diagram"
_TABLE_URI = "http://schemas.openxmlformats.org/drawingml/2006/table"


@dataclass
class _ParagraphRef:
    part: str
    element: Element
    container: int


class PptxAdapter(DocumentAdapter, LayoutSupport):
    format = DocumentFormat.PPTX

    def __init__(self, path: Path, limits: DocumentLimits) -> None:
        super().__init__()
        self.package = Package.open(path, limits)
        self._styles = StyleTable(
            frozenset({"lang", "altLang", "dirty", "err", "noProof", "smtClean", "smtId", "bmk"}),
            frozenset(),
        )
        self._objects: list[Element] = []
        self._refs: list[_ParagraphRef] = []
        self._paragraphs: list[Paragraph] = []
        self.containers: list[Container] = []
        self._charts = 0
        self._diagrams = 0
        try:
            self._scan()
            self._layout = PptxLayout(self.package)
        except BaseException:
            self.package.close()
            raise

    # ---- reading -----------------------------------------------------------------------------

    def _scan(self) -> None:
        presentation = self.package.main_part()
        root = self.package.xml(presentation)
        rels = {r.id: r for r in self.package.relationships(presentation)}
        slides: list[str] = []
        id_list = root.find(qn("p:sldIdLst"))
        slide_ids: list[Element] = list(id_list) if id_list is not None else []
        for slide_id in slide_ids:
            rel = rels.get(str(slide_id.get(qn("r:id"), "")))
            if rel is not None and not rel.external and self.package.has(rel.target):
                slides.append(rel.target)
        layouts: list[str] = []
        masters: list[str] = []
        for index, slide in enumerate(slides, start=1):
            self._scan_tree(slide, f"slide {index}", index)
            for layout in self.package.related(slide, "slideLayout"):
                if layout.target not in layouts:
                    layouts.append(layout.target)
            for notes in self.package.related(slide, "notesSlide"):
                self._scan_notes(notes.target, index)
        for layout in layouts:
            for master in self.package.related(layout, "slideMaster"):
                if master.target not in masters:
                    masters.append(master.target)
        for layout in layouts:
            name = self._c_sld_name(layout)
            self._scan_tree(layout, f"layout {name}", None, skip_placeholders=True)
        for master in masters:
            self._scan_tree(
                master, f"master {self._c_sld_name(master)}", None, skip_placeholders=True
            )
        if self._charts:
            self._report(
                "chart_text_not_translated",
                self._charts,
                "Chart titles, labels and data are not translated in this release.",
            )
        if self._diagrams:
            self._report(
                "smartart_text_not_translated",
                self._diagrams,
                "SmartArt text is not translated in this release.",
            )

    def _c_sld_name(self, part: str) -> str:
        c_sld = self.package.xml(part).find(qn("p:cSld"))
        name = c_sld.get("name") if c_sld is not None else None
        return f'"{name}"' if name else part.rsplit("/", 1)[-1]

    def _report(self, code: str, count: int, message: str) -> None:
        self.diagnostics.append(
            DocumentDiagnostic(
                code=code, severity=DiagnosticSeverity.INFO, message=message, count=count
            )
        )

    def _scan_tree(
        self, part: str, label: str, slide_index: int | None, *, skip_placeholders: bool = False
    ) -> None:
        tree = self.package.xml(part).find(f"{qn('p:cSld')}/{qn('p:spTree')}")
        if tree is not None:
            self._scan_shapes(part, tree, label, slide_index, skip_placeholders)

    def _scan_shapes(
        self,
        part: str,
        parent: Element,
        label: str,
        slide_index: int | None,
        skip_placeholders: bool,
    ) -> None:
        for child in parent:
            tag = child.tag
            if tag == qn("p:sp"):
                placeholder = child.find(f"{qn('p:nvSpPr')}/{qn('p:nvPr')}/{qn('p:ph')}")
                if placeholder is not None and skip_placeholders:
                    continue
                body = child.find(qn("p:txBody"))
                if body is not None:
                    kind = "placeholder" if placeholder is not None else "shape"
                    location = f"{label} / shape {_shape_name(child, qn('p:nvSpPr'))}"
                    self._scan_body(part, child, body, kind, location, slide_index)
            elif tag == qn("p:grpSp"):
                self._scan_shapes(part, child, label, slide_index, skip_placeholders)
            elif tag == qn("p:graphicFrame"):
                self._scan_frame(part, child, label, slide_index)
            elif tag == qn("mc:AlternateContent"):
                for branch in child:
                    self._scan_shapes(part, branch, label, slide_index, skip_placeholders)

    def _scan_frame(self, part: str, frame: Element, label: str, slide_index: int | None) -> None:
        data = frame.find(f"{qn('a:graphic')}/{qn('a:graphicData')}")
        uri = data.get("uri") if data is not None else None
        if uri == _CHART_URI:
            self._charts += 1
        elif uri == _DIAGRAM_URI:
            self._diagrams += 1
        elif uri == _TABLE_URI and data is not None:
            table = data.find(qn("a:tbl"))
            if table is None:
                return
            name = _shape_name(frame, qn("p:nvGraphicFramePr"))
            for r, row in enumerate(table.iter(qn("a:tr")), start=1):
                for c, cell in enumerate(row.findall(qn("a:tc")), start=1):
                    body = cell.find(qn("a:txBody"))
                    if body is not None:
                        location = f"{label} / table {name} / row {r} / cell {c}"
                        self._scan_body(part, cell, body, "table-cell", location, slide_index)

    def _scan_notes(self, part: str, slide_index: int) -> None:
        tree = self.package.xml(part).find(f"{qn('p:cSld')}/{qn('p:spTree')}")
        if tree is None:
            return
        for shape in tree.iter(qn("p:sp")):
            placeholder = shape.find(f"{qn('p:nvSpPr')}/{qn('p:nvPr')}/{qn('p:ph')}")
            if placeholder is None or placeholder.get("type") != "body":
                continue
            body = shape.find(qn("p:txBody"))
            if body is not None:
                self._scan_body(part, shape, body, "notes", f"slide {slide_index} notes", None)

    def _scan_body(
        self,
        part: str,
        element: Element,
        body: Element,
        kind: str,
        location: str,
        slide_index: int | None,
    ) -> None:
        container = len(self.containers)
        self.containers.append(
            Container(container, part, kind, location, element, body, slide_index)
        )
        for number, para in enumerate(body.findall(qn("a:p")), start=1):
            nodes = self._nodes(para)
            if not any(isinstance(n, Text) and n.text.strip() for n in nodes):
                continue
            self._refs.append(_ParagraphRef(part, para, container))
            self._paragraphs.append(
                Paragraph(len(self._refs) - 1, f"{location} / paragraph {number}", tuple(nodes))
            )

    def _nodes(self, para: Element) -> list[Inline]:
        nodes: list[Inline] = []
        for child in para:
            tag = child.tag
            if tag in (qn("a:pPr"), qn("a:endParaRPr")) or not isinstance(tag, str):
                continue
            if tag == qn("a:r"):
                text = child.find(qn("a:t"))
                value = (text.text or "") if text is not None else ""
                nodes.append(Text(value, self._styles.id_for(child.find(qn("a:rPr")))))
            else:  # a:br, a:fld (slide numbers, dates), math and extension content
                nodes.append(Obj(self._object(child)))
        return nodes

    def _object(self, element: Element) -> int:
        self._objects.append(element)
        return len(self._objects) - 1

    def paragraphs(self) -> list[Paragraph]:
        return list(self._paragraphs)

    # ---- writing -----------------------------------------------------------------------------

    def apply(self, paragraph_id: int, nodes: Sequence[Inline], target: Language) -> None:
        ref = self._refs[paragraph_id]
        para = ref.element
        end = para.find(qn("a:endParaRPr"))
        for child in list(para):
            if child.tag not in (qn("a:pPr"), qn("a:endParaRPr")):
                para.remove(child)
        new = [element for node in nodes for element in self._render(node, target)]
        for element in new:
            if end is not None:
                end.addprevious(element)
            else:
                para.append(element)
        self.package.mark_modified(ref.part)

    def _render(self, node: Inline, target: Language) -> list[Element]:
        match node:
            case Text(text=t, style=s) | Keep(text=t, style=s):
                if not t:
                    return []
                run = etree.Element(qn("a:r"))
                properties = self._styles.template(s)
                if properties is not None:
                    if properties.get("lang") is not None:
                        properties.set("lang", _LANG_TAGS[target])
                    run.append(properties)
                etree.SubElement(run, qn("a:t")).text = clean_text(t)
                return [run]
            case Obj(key=k):
                return [self._objects[k]]
            case Wrap(children=children):
                return [e for child in children for e in self._render(child, target)]

    def layout_containers(self) -> list[LayoutContainer]:
        return self._layout.containers(self.containers)

    def apply_run_sizes(self, container_id: str, sizes: Sequence[Sequence[float]]) -> None:
        self._layout.apply_sizes(container_id, sizes)
        self.package.mark_modified(self.containers[int(container_id)].part)

    def save(self, path: Path) -> None:
        self.package.save(path)

    def close(self) -> None:
        self.package.close()


def _shape_name(element: Element, nv_tag: str) -> str:
    nv = element.find(nv_tag)
    c_nv = nv.find(qn("p:cNvPr")) if nv is not None else None
    if c_nv is None:
        return "(unnamed)"
    return f'"{c_nv.get("name", "")}" (id {c_nv.get("id", "?")})'
