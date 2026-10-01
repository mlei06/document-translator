"""DOCX adapter: targeted edits of document, header, footer, footnote and endnote parts (ADR-011).

Every ``w:p`` in a story part is a paragraph, including paragraphs in table cells, content controls
and text boxes (DrawingML and the VML fallback copy). Inside a paragraph:

- each run becomes ``Text`` for its ``w:t`` content and ``Obj`` for every other run child (tabs,
  breaks, drawings, note references), each object keeping the run's properties;
- ``w:hyperlink``, tracked insertions, inline content controls, smart tags and HYPERLINK fields are
  ``Wrap`` nodes; other field results, tracked deletions and math are ``Obj`` (never translated);
- zero-width markers (bookmarks, comment ranges, permissions) at the start or end of a paragraph
  stay there without reaching the engine; in the middle they are objects. Proofing marks
  (``w:proofErr``) are dropped: Word recomputes them.

Scanning never modifies the tree. Original elements are moved only when ``apply`` rewrites the
paragraph that contains them, so untranslated content stays byte-identical in its part.
"""

import copy
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

from doctranslator_core.config import DocumentLimits
from doctranslator_core.document import LayoutContainer, LayoutPatch, Paragraph
from doctranslator_core.formats._ooxml import Element, Package, qn
from doctranslator_core.formats._ooxml.runs import StyleTable, clean_text
from doctranslator_core.formats.base import DocumentAdapter, LayoutRepairSupport, LayoutSupport
from doctranslator_core.formats.docx.layout import DocxLayout
from doctranslator_core.inline import Inline, Keep, Obj, Text, Wrap
from doctranslator_core.types import (
    DiagnosticSeverity,
    DocumentDiagnostic,
    DocumentFormat,
    Language,
)

__all__ = ["DocxAdapter"]

_LANG = {Language.ZH: "zh-CN", Language.EN: "en-US", Language.JA: "ja-JP", Language.ES: "es-ES"}
_MARKERS = {
    qn("w:bookmarkStart"),
    qn("w:bookmarkEnd"),
    qn("w:commentRangeStart"),
    qn("w:commentRangeEnd"),
    qn("w:permStart"),
    qn("w:permEnd"),
    qn("w:moveFromRangeStart"),
    qn("w:moveFromRangeEnd"),
    qn("w:moveToRangeStart"),
    qn("w:moveToRangeEnd"),
    qn("w:customXmlInsRangeStart"),
    qn("w:customXmlInsRangeEnd"),
}
_WRAPPERS = {
    qn("w:hyperlink"),
    qn("w:ins"),
    qn("w:moveTo"),
    qn("w:smartTag"),
    qn("w:customXml"),
    qn("w:sdt"),
    qn("w:dir"),
    qn("w:bdo"),
}
_WRAPPER_PROPERTIES = {qn("w:smartTagPr"), qn("w:customXmlPr"), qn("w:sdtPr"), qn("w:sdtEndPr")}
_SKIPPED_NOTES = {"separator", "continuationSeparator", "continuationNotice"}
_HYPERLINK_FIELD = re.compile(r"^\s*HYPERLINK\b", re.IGNORECASE)
_XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"


@dataclass
class _Object:
    """Original elements emitted unchanged; with ``run`` they go inside a copy of that run."""

    elements: list[Element]
    run: Element | None = None


@dataclass
class _Wrapper:
    """How to rebuild a wrapper around translated children."""

    template: Element | None
    """Shallow copy of the wrapper element with its property children; ``None`` for fields."""
    content_tag: str | None = None
    """For ``w:sdt``: children go inside this child element (``w:sdtContent``)."""
    before: list[Element] = field(default_factory=list[Element])
    after: list[Element] = field(default_factory=list[Element])
    """For complex HYPERLINK fields: original runs emitted around the children."""


@dataclass
class _ParagraphRef:
    part: str
    element: Element
    leading: list[Element]
    trailing: list[Element]


class DocxAdapter(DocumentAdapter, LayoutSupport, LayoutRepairSupport):
    format = DocumentFormat.DOCX

    def __init__(self, path: Path, limits: DocumentLimits) -> None:
        super().__init__()
        self.package = Package.open(path, limits)
        self._styles = StyleTable(frozenset(), frozenset({"lang", "noProof", "webHidden"}))
        self._objects: list[_Object] = []
        self._wrappers: list[_Wrapper] = []
        self._refs: list[_ParagraphRef] = []
        self._paragraphs: list[Paragraph] = []
        self._deletions = 0
        self._field_results = 0
        self._stories: list[str] = []
        try:
            self._scan()
            self._layout = DocxLayout(self.package, self._stories)
        except BaseException:
            self.package.close()
            raise

    # ---- reading -----------------------------------------------------------------------------

    def _scan(self) -> None:
        main = self.package.main_part()
        self._scan_story(main, "body")
        seen: set[str] = {main}
        for kind in ("header", "footer", "footnotes", "endnotes"):
            for number, rel in enumerate(self.package.related(main, kind), start=1):
                if rel.target in seen:
                    continue
                seen.add(rel.target)
                label = kind if kind in ("footnotes", "endnotes") else f"{kind} {number}"
                self._scan_story(rel.target, label)
        for rel in self.package.related(main, "comments"):
            if any((t.text or "").strip() for t in self.package.xml(rel.target).iter(qn("w:t"))):
                self._report(
                    "comments_not_translated",
                    DiagnosticSeverity.INFO,
                    "Comments are not translated.",
                )
        if self._deletions:
            self._report(
                "tracked_changes_present",
                DiagnosticSeverity.WARNING,
                "The document has tracked deletions; deleted text stays in the source "
                "language. Accept or reject changes before translating for a clean "
                "result.",
                self._deletions,
            )
        if self._field_results:
            self._report(
                "field_results_not_translated",
                DiagnosticSeverity.INFO,
                "Field results (dates, page numbers, tables of contents, references) "
                "are not translated; update fields in Word to regenerate them.",
                self._field_results,
            )

    def _report(
        self, code: str, severity: DiagnosticSeverity, message: str, count: int = 1
    ) -> None:
        self.diagnostics.append(
            DocumentDiagnostic(code=code, severity=severity, message=message, count=count)
        )

    def _scan_story(self, part: str, label: str) -> None:
        self._stories.append(part)
        paragraphs = list(self.package.xml(part).iter(qn("w:p")))
        field_depth = 0
        for number, para in enumerate(paragraphs, start=1):
            note = _ancestor(para, (qn("w:footnote"), qn("w:endnote")))
            if note is not None and note.get(qn("w:type")) in _SKIPPED_NOTES:
                continue
            nodes, field_depth = self._paragraph_nodes(para, field_depth)
            if not any(isinstance(n, Text) and n.text.strip() for n in _flatten(nodes)):
                continue
            leading, core, trailing = self._split_markers(nodes)
            kind = _context(para)
            location = f"{label} / paragraph {number}" + (f" ({kind})" if kind else "")
            self._refs.append(_ParagraphRef(part, para, leading, trailing))
            self._paragraphs.append(Paragraph(len(self._refs) - 1, location, tuple(core)))

    def _paragraph_nodes(self, para: Element, field_depth: int) -> tuple[list[Inline], int]:
        """Inline nodes; ``field_depth`` carries complex fields that span paragraphs."""
        nodes: list[Inline] = []
        children = [c for c in para if c.tag != qn("w:pPr")]
        index = 0
        while index < len(children):
            child = children[index]
            if field_depth > 0:
                # Inside a field result that began in an earlier paragraph: never translated.
                field_depth = _field_depth_after(child, field_depth)
                nodes.append(self._object([child]))
                index += 1
                continue
            if child.tag == qn("w:r") and _field_char(child) == "begin":
                end = _field_end(children, index)
                if end is None:
                    # The field continues into later paragraphs.
                    self._field_results += 1
                    for rest in children[index:]:
                        field_depth = _field_depth_after(rest, field_depth)
                        nodes.append(self._object([rest]))
                    break
                nodes.append(self._complex_field(children[index : end + 1]))
                index = end + 1
                continue
            nodes.extend(self._inline(child))
            index += 1
        return nodes, field_depth

    def _complex_field(self, runs: list[Element]) -> Inline:
        """A complete ``begin ... separate ... end`` field inside one paragraph."""
        instruction = "".join(t.text or "" for r in runs for t in r.iter(qn("w:instrText")))
        separate = next((i for i, r in enumerate(runs) if _field_char(r) == "separate"), None)
        nested = sum(1 for r in runs if _field_char(r) == "begin") > 1
        if _HYPERLINK_FIELD.match(instruction) and separate is not None and not nested:
            result = [n for run in runs[separate + 1 : -1] for n in self._inline(run)]
            self._wrappers.append(_Wrapper(None, None, runs[: separate + 1], [runs[-1]]))
            return Wrap(len(self._wrappers) - 1, tuple(result))
        self._field_results += 1
        return self._object(runs)

    def _inline(self, element: Element) -> list[Inline]:
        tag = element.tag
        if not isinstance(tag, str) or tag == qn("w:proofErr"):
            return []
        if tag == qn("w:r"):
            return self._run(element)
        if tag == qn("w:fldSimple"):
            if _HYPERLINK_FIELD.match(element.get(qn("w:instr"), "")):
                children = [n for run in element for n in self._inline(run)]
                return [Wrap(self._wrapper(element), tuple(children))]
            self._field_results += 1
            return [self._object([element])]
        if tag in (qn("w:del"), qn("w:moveFrom")):
            self._deletions += 1
            return [self._object([element])]
        if tag in _WRAPPERS:
            content = element.find(qn("w:sdtContent")) if tag == qn("w:sdt") else element
            if content is None:
                return [self._object([element])]
            children = [
                n
                for child in content
                if child.tag not in _WRAPPER_PROPERTIES
                for n in self._inline(child)
            ]
            return [Wrap(self._wrapper(element), tuple(children))]
        return [self._object([element])]  # markers, math and unknown inline content

    def _run(self, run: Element) -> list[Inline]:
        properties = run.find(qn("w:rPr"))
        style = self._styles.id_for(properties)
        nodes: list[Inline] = []
        pending: list[Element] = []
        for child in run:
            if child.tag == qn("w:rPr") or not isinstance(child.tag, str):
                continue
            if child.tag == qn("w:t"):
                if pending:
                    nodes.append(self._object(pending, run))
                    pending = []
                nodes.append(Text(child.text or "", style))
            else:
                pending.append(child)
        if pending:
            nodes.append(self._object(pending, run))
        return nodes

    def _object(self, elements: list[Element], run: Element | None = None) -> Obj:
        self._objects.append(_Object(elements, run))
        return Obj(len(self._objects) - 1)

    def _wrapper(self, element: Element) -> int:
        template = etree.Element(element.tag, attrib=dict(element.attrib))
        for child in element:
            if child.tag in _WRAPPER_PROPERTIES:
                template.append(copy.deepcopy(child))
        content_tag: str | None = None
        if element.tag == qn("w:sdt"):
            content_tag = qn("w:sdtContent")
            etree.SubElement(template, content_tag)
        self._wrappers.append(_Wrapper(template, content_tag))
        return len(self._wrappers) - 1

    def _split_markers(
        self, nodes: list[Inline]
    ) -> tuple[list[Element], list[Inline], list[Element]]:
        """Keep zero-width markers at the paragraph's edges out of the engine input."""
        start, end = 0, len(nodes)
        while start < end and self._is_marker(nodes[start]):
            start += 1
        while end > start and self._is_marker(nodes[end - 1]):
            end -= 1
        leading = [
            e for n in nodes[:start] if isinstance(n, Obj) for e in self._objects[n.key].elements
        ]
        trailing = [
            e for n in nodes[end:] if isinstance(n, Obj) for e in self._objects[n.key].elements
        ]
        return leading, nodes[start:end], trailing

    def _is_marker(self, node: Inline) -> bool:
        if not isinstance(node, Obj):
            return False
        entry = self._objects[node.key]
        return entry.run is None and all(e.tag in _MARKERS for e in entry.elements)

    def paragraphs(self) -> list[Paragraph]:
        return list(self._paragraphs)

    # ---- writing -----------------------------------------------------------------------------

    def apply(self, paragraph_id: int, nodes: Sequence[Inline], target: Language) -> None:
        ref = self._refs[paragraph_id]
        rendered = [*ref.leading, *self._render_all(nodes, target), *ref.trailing]
        para = ref.element
        for child in list(para):
            if child.tag != qn("w:pPr"):
                para.remove(child)
        for element in rendered:
            para.append(element)
        self.package.mark_modified(ref.part)

    def _render_all(self, nodes: Sequence[Inline], target: Language) -> list[Element]:
        return [e for node in nodes for e in self._render(node, target)]

    def _render(self, node: Inline, target: Language) -> list[Element]:
        match node:
            case Text(text=t, style=s) | Keep(text=t, style=s):
                if not t:
                    return []
                run = etree.Element(qn("w:r"))
                properties = self._styles.template(s)
                if properties is not None:
                    _set_language(properties, target)
                    run.append(properties)
                text = etree.SubElement(run, qn("w:t"))
                value = clean_text(t)
                text.text = value
                if value != value.strip():
                    text.set(_XML_SPACE, "preserve")
                return [run]
            case Obj(key=k):
                entry = self._objects[k]
                if entry.run is None:
                    return list(entry.elements)
                run = etree.Element(qn("w:r"), attrib=dict(entry.run.attrib))
                properties = entry.run.find(qn("w:rPr"))
                if properties is not None:
                    run.append(copy.deepcopy(properties))
                for element in entry.elements:
                    run.append(element)
                return [run]
            case Wrap(key=k, children=children):
                wrapper = self._wrappers[k]
                rendered = self._render_all(children, target)
                if wrapper.template is None:
                    return [*wrapper.before, *rendered, *wrapper.after]
                shell = copy.deepcopy(wrapper.template)
                container = shell.find(wrapper.content_tag) if wrapper.content_tag else shell
                target_element = container if container is not None else shell
                for element in rendered:
                    target_element.append(element)
                return [shell]

    def layout_containers(self) -> list[LayoutContainer]:
        return self._layout.containers()

    def layout_context(self) -> list[LayoutContainer]:
        return self.layout_containers()

    def apply_layout_patch(self, patch: LayoutPatch) -> None:
        current = next(c for c in self.layout_containers() if c.id == patch.expected.id)
        if current != patch.expected:
            raise ValueError("stale layout patch")
        self._layout.apply_patch(patch)
        self.package.mark_modified(self._layout.boxes[current.id].part)

    def apply_run_sizes(self, container_id: str, sizes: Sequence[Sequence[float]]) -> None:
        self.package.mark_modified(self._layout.apply_sizes(container_id, sizes))

    def save(self, path: Path) -> None:
        self.package.save(path)

    def close(self) -> None:
        self.package.close()


def _set_language(properties: Element, target: Language) -> None:
    lang = properties.find(qn("w:lang"))
    if lang is None:
        return
    if target in (Language.ZH, Language.JA):
        lang.set(qn("w:eastAsia"), _LANG[target])
    else:
        lang.set(qn("w:val"), _LANG[target])


def _flatten(nodes: Sequence[Inline]) -> list[Inline]:
    flat: list[Inline] = []
    for node in nodes:
        flat.append(node)
        if isinstance(node, Wrap):
            flat.extend(_flatten(node.children))
    return flat


def _ancestor(element: Element, tags: tuple[str, ...]) -> Element | None:
    parent = element.getparent()
    while parent is not None:
        if parent.tag in tags:
            return parent
        parent = parent.getparent()
    return None


def _context(para: Element) -> str:
    if _ancestor(para, (qn("w:txbxContent"),)) is not None:
        return "text box"
    if _ancestor(para, (qn("w:tc"),)) is not None:
        return "table cell"
    return ""


def _field_char(run: Element) -> str | None:
    char = run.find(qn("w:fldChar"))
    return char.get(qn("w:fldCharType")) if char is not None else None


def _field_end(children: list[Element], begin: int) -> int | None:
    depth = 0
    for index in range(begin, len(children)):
        kind = _field_char(children[index]) if children[index].tag == qn("w:r") else None
        if kind == "begin":
            depth += 1
        elif kind == "end":
            depth -= 1
            if depth == 0:
                return index
    return None


def _field_depth_after(element: Element, depth: int) -> int:
    for char in element.iter(qn("w:fldChar")):
        kind = char.get(qn("w:fldCharType"))
        if kind == "begin":
            depth += 1
        elif kind == "end":
            depth -= 1
    return max(depth, 0)
