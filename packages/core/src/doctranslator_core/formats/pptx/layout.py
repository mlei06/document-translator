"""PPTX layout capability: describe slide text containers for fit and apply font sizes (P3).

Resolves what PowerPoint renders: shape geometry (inherited from layout/master placeholders,
scaled by enclosing groups), body insets and wrapping, and each run's effective size and fonts
through the run -> shape list style -> layout placeholder -> master placeholder -> master text
style -> presentation default chain, with theme font references and per-script theme fonts.
Speaker notes are not fit containers.
"""

import copy
from collections.abc import Sequence
from dataclasses import dataclass, field, replace

from doctranslator_core.document import LayoutContainer, LayoutParagraph, LayoutPatch, LayoutRun
from doctranslator_core.formats._ooxml import Element, Package, qn
from doctranslator_core.formats.pptx.model import Container

__all__ = ["PptxLayout"]

EMU_PER_PT = 12700.0
DEFAULT_SIZE = 18.0
DEFAULT_INSETS = (91440, 45720, 91440, 45720)  # left, top, right, bottom (EMU)
CELL_MARGINS = (91440, 45720, 91440, 45720)
_TITLE_TYPES = {"title", "ctrTitle"}
_OTHER_TYPES = {"dt", "ftr", "sldNum", "hdr"}
_BULLETS = (qn("a:buChar"), qn("a:buAutoNum"), qn("a:buBlip"))
_BULLET_SETTINGS = (*_BULLETS, qn("a:buNone"))


@dataclass
class _Theme:
    fonts: dict[str, str]
    """``mj-lt``, ``mj-ea``, ``mn-lt``, ``mn-ea`` and ``mj-Hans``/``mn-Jpan``-style script fonts."""


@dataclass
class _Mapping:
    """Which XML elements each layout run and paragraph mark came from."""

    runs: list[list[Element]]
    ends: list[Element | None]
    font_scale: float
    paragraph_elements: list[Element] = field(default_factory=list[Element])


class PptxLayout:
    def __init__(self, package: Package) -> None:
        self._package = package
        self._themes: dict[str, _Theme] = {}
        self._mappings: dict[str, _Mapping] = {}
        self._containers: dict[str, Container] = {}
        self._revision: dict[str, int] = {}
        self._cache: dict[str, LayoutContainer] = {}
        presentation = package.xml(package.main_part())
        self._default_style = presentation.find(qn("p:defaultTextStyle"))

    # ---- containers --------------------------------------------------------------------------

    def containers(self, containers: Sequence[Container]) -> list[LayoutContainer]:
        result: list[LayoutContainer] = []
        self._containers = {str(c.key): c for c in containers}
        for container in containers:
            if container.kind == "notes":
                continue
            key = str(container.key)
            if key not in self._cache:
                self._cache[key] = self._describe(container)
            result.append(self._cache[key])
        return result

    def invalidate(self, container_id: str) -> None:
        self._cache.pop(container_id, None)

    def _describe(self, container: Container) -> LayoutContainer:
        key = str(container.key)
        if container.kind == "table-cell":
            width, height, body_pr, insets = self._cell_geometry(container.element)
            chain_sources = self._table_sources(container)
            placeholder_bodies: list[Element] = []
        else:
            placeholder_bodies = self._placeholder_shapes(container)
            width, height = self._shape_size(container.element, placeholder_bodies)
            body_pr = self._merged_body(container.tx_body, placeholder_bodies)
            insets = tuple(
                int(body_pr.get(name, str(default)))
                for name, default in zip(
                    ("lIns", "tIns", "rIns", "bIns"), DEFAULT_INSETS, strict=True
                )
            )
            chain_sources = self._shape_sources(container, placeholder_bodies)
        unsupported: str | None = None
        vert = body_pr.get("vert", "horz")
        if vert not in ("horz",):
            unsupported = "vertical_text"
        if width is None or height is None:
            unsupported = unsupported or "geometry_unknown"
        wrap = body_pr.get("wrap", "square") != "none"
        autofit = self._autofit(container.tx_body, placeholder_bodies)
        font_scale = 1.0
        spacing_reduction = 0.0
        if autofit is not None and autofit.tag == qn("a:normAutofit"):
            font_scale = int(autofit.get("fontScale", "100000")) / 100000
            spacing_reduction = int(autofit.get("lnSpcReduction", "0")) / 100000
        content_w = None if width is None else (width - insets[0] - insets[2]) / EMU_PER_PT
        content_h = None if height is None else (height - insets[1] - insets[3]) / EMU_PER_PT
        if autofit is not None and autofit.tag == qn("a:spAutoFit"):
            content_h = None  # PowerPoint grows the shape to fit its text
        paragraphs, mapping = self._paragraphs(
            container, chain_sources, font_scale, spacing_reduction
        )
        mapping.font_scale = font_scale
        if paragraphs:
            paragraphs[0] = replace(paragraphs[0], space_before_pt=0.0)
            paragraphs[-1] = replace(paragraphs[-1], space_after_pt=0.0)
        self._mappings[key] = mapping
        bounds, growth = self._bounds(container)
        return LayoutContainer(
            spacing_supported=next(container.tx_body.iter(qn("a:br")), None) is None,
            page_index=container.slide_index - 1 if container.slide_index else None,
            bounds_pt=bounds,
            growth_bounds_pt=growth,
            content_bounds_pt=(
                bounds[0] + insets[0] / EMU_PER_PT,
                bounds[1] + insets[1] / EMU_PER_PT,
                bounds[2] - insets[2] / EMU_PER_PT,
                bounds[3] - insets[3] / EMU_PER_PT,
            )
            if bounds
            else None,
            revision=self._revision.get(key, 0),
            id=key,
            location=container.location,
            kind=container.kind,
            width_pt=content_w,
            height_pt=content_h,
            wrap=wrap,
            paragraphs=tuple(paragraphs),
            unsupported=unsupported,
            line_metric="em",
        )

    def _bounds(
        self, container: Container
    ) -> tuple[tuple[float, float, float, float] | None, tuple[float, float, float, float] | None]:
        shape = container.element
        bounds = _explicit_bounds(shape)
        if bounds is None or container.kind != "shape" or container.slide_index is None:
            return bounds, None
        body = container.tx_body.find(qn("a:bodyPr"))
        if body is not None and (
            body.get("anchor", "t") != "t" or body.find(qn("a:spAutoFit")) is not None
        ):
            return bounds, None
        # Growth preserves only the top-left anchor. Other alignments remain font-fit only.
        if any(p.get("algn", "l") != "l" for p in container.tx_body.iter(qn("a:pPr"))):
            return bounds, None
        tree = shape.getparent()
        if tree is None or tree.tag != qn("p:spTree"):
            return bounds, None
        size = self._package.xml(self._package.main_part()).find(qn("p:sldSz"))
        if size is None:
            return bounds, None
        x0, y0, x1, y1 = bounds
        right = min(x1 + (x1 - x0) * 0.2, int(size.get("cx", "0")) / EMU_PER_PT - 2)
        bottom = min(y1 + (y1 - y0) * 0.2, int(size.get("cy", "0")) / EMU_PER_PT - 2)
        obstacles: list[tuple[float, float, float, float]] = []
        objects = list(tree)
        part = container.part
        for relation in ("slideLayout", "slideMaster"):
            related = self._package.related(part, relation)
            if not related:
                break
            part = related[0].target
            inherited = self._package.xml(part).find(f"{qn('p:cSld')}/{qn('p:spTree')}")
            if inherited is not None:
                objects.extend(o for o in inherited if next(o.iter(qn("p:ph")), None) is None)
        for other in objects:
            if other is shape or other.tag in (qn("p:nvGrpSpPr"), qn("p:grpSpPr"), qn("p:extLst")):
                continue
            b = _explicit_bounds(other)
            if b is None:
                return bounds, None
            preset = other.find(f"{qn('p:spPr')}/{qn('a:prstGeom')}")
            # A plain text-free containing shape is a card, never permission to leave it.
            if (
                b[0] <= x0
                and b[1] <= y0
                and b[2] >= x1
                and b[3] >= y1
                and other.tag == qn("p:sp")
                and preset is not None
                and preset.get("prst") in ("rect", "roundRect")
                and next(other.iter(qn("a:t")), None) is None
            ):
                right = min(right, b[2] - min(2.0, b[2] - x1))
                bottom = min(bottom, b[3] - min(2.0, b[3] - y1))
                continue
            if _intersects(bounds, b):
                return bounds, None
            obstacles.append(b)
        # Reserve the full grown rectangle, including corner collisions.
        for b in obstacles:
            if b[0] >= x1 and b[1] < bottom and b[3] > y0:
                right = min(right, b[0] - min(2.0, b[0] - x1))
            if b[1] >= y1 and b[0] < right and b[2] > x0:
                bottom = min(bottom, b[1] - min(2.0, b[1] - y1))
        grown = (x0, y0, max(x1, right), max(y1, bottom))
        return bounds, grown if grown != bounds else None

    def apply_patch(self, patch: LayoutPatch) -> None:
        before, after = patch.expected, patch.replacement
        container = self._containers[before.id]
        mapping = self._mappings[before.id]
        if patch.operation == "fonts":
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
            for elements, paragraph in zip(mapping.runs, after.paragraphs, strict=True):
                for element, run in zip(elements, paragraph.runs, strict=True):
                    props = element.find(qn("a:rPr"))
                    if props is None:
                        props = element.makeelement(qn("a:rPr"), {})
                        element.insert(0, props)
                    for slot, name in (("latin", run.latin_font), ("ea", run.east_asian_font)):
                        if name:
                            font = props.find(qn("a:" + slot))
                            if font is None:
                                font = props.makeelement(qn("a:" + slot), {})
                                props.append(font)
                            font.set("typeface", name)
        elif patch.operation == "geometry":
            if after.bounds_pt != before.growth_bounds_pt or after.bounds_pt is None:
                raise ValueError("unsupported growth")
            if before.bounds_pt is None or before.content_bounds_pt is None:
                raise ValueError("missing base geometry")
            dw = after.bounds_pt[2] - before.bounds_pt[2]
            dh = after.bounds_pt[3] - before.bounds_pt[3]
            c = before.content_bounds_pt
            permitted = replace(
                before,
                bounds_pt=after.bounds_pt,
                content_bounds_pt=(c[0], c[1], c[2] + dw, c[3] + dh),
                width_pt=before.width_pt + dw if before.width_pt is not None else None,
                height_pt=before.height_pt + dh if before.height_pt is not None else None,
            )
            if permitted != after:
                raise ValueError("invalid geometry patch")
            ext = container.element.find(f"{qn('p:spPr')}/{qn('a:xfrm')}/{qn('a:ext')}")
            if ext is None:
                raise ValueError("missing explicit geometry")
            b = after.bounds_pt
            ext.set("cx", str(round((b[2] - b[0]) * EMU_PER_PT)))
            ext.set("cy", str(round((b[3] - b[1]) * EMU_PER_PT)))
        elif patch.operation == "spacing":
            if not before.spacing_supported:
                raise ValueError("spacing edits are unsupported for this container")
            permitted = replace(
                before,
                paragraphs=tuple(
                    replace(p, space_before_pt=q.space_before_pt, space_after_pt=q.space_after_pt)
                    for p, q in zip(before.paragraphs, after.paragraphs, strict=True)
                ),
            )
            if permitted != after or any(
                q.space_before_pt < p.space_before_pt * 0.5
                or q.space_after_pt < p.space_after_pt * 0.5
                or q.space_before_pt > p.space_before_pt
                or q.space_after_pt > p.space_after_pt
                or min(q.space_before_pt, q.space_after_pt) < 0
                for p, q in zip(before.paragraphs, after.paragraphs, strict=True)
            ):
                raise ValueError("invalid spacing patch")
            for para, paragraph in zip(mapping.paragraph_elements, after.paragraphs, strict=True):
                props = para.find(qn("a:pPr"))
                if props is None:
                    props = para.makeelement(qn("a:pPr"), {})
                    para.insert(0, props)
                for tag, value in (
                    ("spcBef", paragraph.space_before_pt),
                    ("spcAft", paragraph.space_after_pt),
                ):
                    old = props.find(qn("a:" + tag))
                    if old is not None:
                        props.remove(old)
                    spacing = props.makeelement(qn("a:" + tag), {})
                    spacing.append(
                        props.makeelement(qn("a:spcPts"), {"val": str(round(value * 100))})
                    )
                    props.append(spacing)
        self._revision[before.id] = before.revision + 1
        if patch.operation == "geometry":
            for key, other in self._containers.items():
                if other.part == container.part:
                    self.invalidate(key)
        else:
            self.invalidate(before.id)

    # ---- geometry ----------------------------------------------------------------------------

    def _shape_size(
        self, shape: Element, placeholders: list[Element]
    ) -> tuple[float | None, float | None]:
        for candidate in (shape, *placeholders):
            ext = candidate.find(f"{qn('p:spPr')}/{qn('a:xfrm')}/{qn('a:ext')}")
            if ext is not None:
                scale_x, scale_y = _group_scale(shape)
                return int(ext.get("cx", "0")) * scale_x, int(ext.get("cy", "0")) * scale_y
        return None, None

    def _cell_geometry(
        self, cell: Element
    ) -> tuple[float | None, float | None, Element, tuple[int, int, int, int]]:
        row = cell.getparent()
        table = row.getparent() if row is not None else None
        if row is None or table is None:
            return None, None, cell, CELL_MARGINS
        cells = row.findall(qn("a:tc"))
        columns = [int(c.get("w", "0")) for c in table.iter(qn("a:gridCol"))]
        start = sum(int(c.get("gridSpan", "1")) for c in cells[: cells.index(cell)])
        span = int(cell.get("gridSpan", "1"))
        width = float(sum(columns[start : start + span])) if columns else None
        height = float(int(row.get("h", "0")))
        frame = _ancestor(table, qn("p:graphicFrame"))
        if frame is not None and width is not None:
            scale_x, scale_y = _group_scale(frame)
            width, height = width * scale_x, height * scale_y
        properties = cell.find(qn("a:tcPr"))
        margins = CELL_MARGINS
        if properties is not None:
            margins = (
                int(properties.get("marL", str(CELL_MARGINS[0]))),
                int(properties.get("marT", str(CELL_MARGINS[1]))),
                int(properties.get("marR", str(CELL_MARGINS[2]))),
                int(properties.get("marB", str(CELL_MARGINS[3]))),
            )
        body = cell.find(f"{qn('a:txBody')}/{qn('a:bodyPr')}")
        return width, height, body if body is not None else cell, margins

    def _merged_body(self, tx_body: Element, placeholders: list[Element]) -> Element:
        merged = copy.deepcopy(tx_body.find(qn("a:bodyPr")))
        if merged is None:
            merged = tx_body.makeelement(qn("a:bodyPr"), {})
        for placeholder in placeholders:
            inherited = placeholder.find(f"{qn('p:txBody')}/{qn('a:bodyPr')}")
            if inherited is None:
                continue
            for name, value in inherited.attrib.items():
                if name not in merged.attrib:
                    merged.set(name, value)
        return merged

    def _autofit(self, tx_body: Element, placeholders: list[Element]) -> Element | None:
        for body in (tx_body, *(p.find(qn("p:txBody")) for p in placeholders)):
            body_pr = body.find(qn("a:bodyPr")) if body is not None else None
            if body_pr is None:
                continue
            for child in body_pr:
                if child.tag in (qn("a:normAutofit"), qn("a:spAutoFit"), qn("a:noAutofit")):
                    return child
        return None

    # ---- inheritance -------------------------------------------------------------------------

    def _placeholder_shapes(self, container: Container) -> list[Element]:
        """The layout and master placeholder shapes a slide placeholder inherits from."""
        placeholder = container.element.find(f"{qn('p:nvSpPr')}/{qn('p:nvPr')}/{qn('p:ph')}")
        if placeholder is None:
            return []
        kind = placeholder.get("type", "body")
        index = placeholder.get("idx")
        chain: list[Element] = []
        part = container.part
        for relation in ("slideLayout", "slideMaster"):
            related = self._package.related(part, relation)
            if not related:
                break
            part = related[0].target
            match = _find_placeholder(
                self._package.xml(part), kind, index, by_type_only=relation == "slideMaster"
            )
            if match is not None:
                chain.append(match)
        return chain

    def _master_of(self, part: str) -> str | None:
        if part.startswith("ppt/slideMasters/"):
            return part
        for relation in ("slideLayout", "slideMaster"):
            related = self._package.related(part, relation)
            if not related:
                continue
            part = related[0].target
            if part.startswith("ppt/slideMasters/"):
                return part
        return None

    def _text_style(self, container: Container) -> Element | None:
        master = self._master_of(container.part)
        if master is None:
            return None
        styles = self._package.xml(master).find(qn("p:txStyles"))
        if styles is None:
            return None
        placeholder = container.element.find(f"{qn('p:nvSpPr')}/{qn('p:nvPr')}/{qn('p:ph')}")
        if placeholder is None or container.kind == "table-cell":
            name = "p:otherStyle"
        else:
            kind = placeholder.get("type", "body")
            if kind in _TITLE_TYPES:
                name = "p:titleStyle"
            elif kind in _OTHER_TYPES:
                name = "p:otherStyle"
            else:
                name = "p:bodyStyle"
        return styles.find(qn(name))

    def _shape_sources(self, container: Container, placeholders: list[Element]) -> list[Element]:
        """List-style containers in priority order (each has ``a:lvlNpPr`` children)."""
        sources: list[Element] = []
        own = container.tx_body.find(qn("a:lstStyle"))
        if own is not None:
            sources.append(own)
        for placeholder in placeholders:
            style = placeholder.find(f"{qn('p:txBody')}/{qn('a:lstStyle')}")
            if style is not None:
                sources.append(style)
        text_style = self._text_style(container)
        if text_style is not None:
            sources.append(text_style)
        if self._default_style is not None:
            sources.append(self._default_style)
        return sources

    def _table_sources(self, container: Container) -> list[Element]:
        sources: list[Element] = []
        own = container.tx_body.find(qn("a:lstStyle"))
        if own is not None:
            sources.append(own)
        text_style = self._text_style(container)
        if text_style is not None:
            sources.append(text_style)
        if self._default_style is not None:
            sources.append(self._default_style)
        return sources

    def _theme(self, part: str) -> _Theme:
        master = self._master_of(part) or part
        cached = self._themes.get(master)
        if cached is not None:
            return cached
        fonts: dict[str, str] = {}
        for rel in self._package.related(master, "theme"):
            scheme = self._package.xml(rel.target).find(
                f"{qn('a:themeElements')}/{qn('a:fontScheme')}"
            )
            if scheme is None:
                continue
            for prefix, tag in (("mj", "a:majorFont"), ("mn", "a:minorFont")):
                block = scheme.find(qn(tag))
                if block is None:
                    continue
                for slot in ("latin", "ea"):
                    element = block.find(qn(f"a:{slot}"))
                    if element is not None:
                        fonts[f"{prefix}-{'lt' if slot == 'latin' else 'ea'}"] = element.get(
                            "typeface", ""
                        )
                for font in block.findall(qn("a:font")):
                    fonts[f"{prefix}-{font.get('script')}"] = font.get("typeface", "")
        theme = _Theme(fonts)
        self._themes[master] = theme
        return theme

    # ---- paragraphs --------------------------------------------------------------------------

    def _paragraphs(
        self,
        container: Container,
        sources: list[Element],
        font_scale: float,
        spacing_reduction: float,
    ) -> tuple[list[LayoutParagraph], _Mapping]:
        theme = self._theme(container.part)
        header_bold = self._table_header_bold(container)
        paragraphs: list[LayoutParagraph] = []
        mapping = _Mapping([], [], font_scale)
        for para in container.tx_body.findall(qn("a:p")):
            p_pr = para.find(qn("a:pPr"))
            level = int(p_pr.get("lvl", "0")) + 1 if p_pr is not None else 1
            chain = [
                e
                for e in (p_pr, *(s.find(qn(f"a:lvl{level}pPr")) for s in sources))
                if e is not None
            ]
            defaults = [d for d in (e.find(qn("a:defRPr")) for e in chain) if d is not None]
            lines: list[list[tuple[LayoutRun, Element]]] = [[]]
            for child in para:
                if child.tag in (qn("a:r"), qn("a:fld")):
                    text = child.findtext(qn("a:t")) or ""
                    run = self._run(
                        child.find(qn("a:rPr")), defaults, theme, text, font_scale, header_bold
                    )
                    lines[-1].append((run, child))
                elif child.tag == qn("a:br"):
                    lines.append([])
            end_element = para.find(qn("a:endParaRPr"))
            end_run = self._run(end_element, defaults, theme, "", font_scale, header_bold)
            spacing = _line_spacing(chain, spacing_reduction)
            before = _paragraph_space(chain, "a:spcBef", end_run.size_pt)
            after = _paragraph_space(chain, "a:spcAft", end_run.size_pt)
            first_start, other_start = _indents(chain)
            for number, line in enumerate(lines):
                paragraphs.append(
                    LayoutParagraph(
                        runs=tuple(r for r, _ in line),
                        end_run=end_run,
                        line_spacing=spacing[0],
                        line_spacing_pt=spacing[1],
                        space_before_pt=before if number == 0 else 0.0,
                        space_after_pt=after if number == len(lines) - 1 else 0.0,
                        first_line_start_pt=first_start if number == 0 else other_start,
                        other_lines_start_pt=other_start,
                    )
                )
                mapping.paragraph_elements.append(para)
                mapping.runs.append([e for _, e in line])
                mapping.ends.append(end_element if number == len(lines) - 1 else None)
        return paragraphs, mapping

    def _table_header_bold(self, container: Container) -> bool:
        """Bold from the table style's first-row text style, for cells in the first row."""
        if container.kind != "table-cell":
            return False
        row = container.element.getparent()
        table = row.getparent() if row is not None else None
        if row is None or table is None or table.find(qn("a:tr")) is not row:
            return False
        properties = table.find(qn("a:tblPr"))
        if properties is None or properties.get("firstRow") not in ("1", "true"):
            return False
        style_id = properties.findtext(qn("a:tableStyleId"))
        if not style_id or not self._package.has("ppt/tableStyles.xml"):
            return False
        for style in self._package.xml("ppt/tableStyles.xml").findall(qn("a:tblStyle")):
            if style.get("styleId") == style_id:
                text = style.find(f"{qn('a:firstRow')}/{qn('a:tcTxStyle')}")
                return text is not None and text.get("b") == "on"
        return False

    def _run(
        self,
        r_pr: Element | None,
        defaults: list[Element],
        theme: _Theme,
        text: str,
        font_scale: float,
        header_bold: bool,
    ) -> LayoutRun:
        chain = [e for e in (r_pr, *defaults) if e is not None]
        size = next((int(e.get("sz", "0")) / 100 for e in chain if e.get("sz")), DEFAULT_SIZE)
        bold = next((e.get("b") in ("1", "true") for e in chain if e.get("b")), header_bold)
        italic = next((e.get("i") in ("1", "true") for e in chain if e.get("i")), False)
        latin = _typeface(chain, "a:latin", theme)
        east = _typeface(chain, "a:ea", theme)
        if not east:
            lang = next((str(e.get("lang")) for e in chain if e.get("lang")), "")
            alt = next((str(e.get("altLang")) for e in chain if e.get("altLang")), "")
            script = _script_for(lang, alt, text)
            east = theme.fonts.get(f"mn-{script}") or None
        fallbacks = tuple(
            name
            for key in _fallback_order(text)
            if (name := theme.fonts.get(f"mn-{key}") or theme.fonts.get(f"mj-{key}"))
        )
        return LayoutRun(
            text=text,
            size_pt=size * font_scale,
            fallback_fonts=fallbacks,
            latin_font=latin or theme.fonts.get("mn-lt") or None,
            east_asian_font=east,
            bold=bold,
            italic=italic,
        )

    # ---- applying sizes ----------------------------------------------------------------------

    def apply_sizes(self, container_id: str, sizes: Sequence[Sequence[float]]) -> None:
        """Write effective sizes (divided by any autofit font scale PowerPoint applies)."""
        mapping = self._mappings[container_id]
        self.invalidate(container_id)
        for runs, end, run_sizes in zip(mapping.runs, mapping.ends, sizes, strict=True):
            for element, size in zip(runs, run_sizes, strict=True):
                _set_size(element, "a:rPr", size / mapping.font_scale)
            if end is not None and run_sizes:
                end.set("sz", str(round(max(run_sizes) / mapping.font_scale * 100)))


def _set_size(run: Element, tag: str, size_pt: float) -> None:
    properties = run.find(qn(tag))
    if properties is None:
        properties = run.makeelement(qn(tag), {})
        run.insert(0, properties)
    properties.set("sz", str(round(size_pt * 100)))


def _typeface(chain: list[Element], tag: str, theme: _Theme) -> str | None:
    for element in chain:
        font = element.find(qn(tag))
        if font is not None:
            face = font.get("typeface", "")
            if face.startswith("+"):
                return theme.fonts.get(face[1:]) or None
            return face or None
    return None


def _script_for(lang: str, alt: str, text: str) -> str:
    for tag in (lang, alt):
        lowered = tag.lower()
        if lowered.startswith("ja"):
            return "Jpan"
        if lowered.startswith(("zh-tw", "zh-hk", "zh-mo")):
            return "Hant"
        if lowered.startswith("zh"):
            return "Hans"
        if lowered.startswith("ko"):
            return "Hang"
    has_kana = any(0x3040 <= ord(c) <= 0x30FF for c in text)
    return "Jpan" if has_kana else "Hans"


def _fallback_order(text: str) -> tuple[str, ...]:
    """Theme script fonts Office substitutes for East Asian text: Japanese first when the text
    has kana, otherwise Simplified Chinese."""
    if any(0x3040 <= ord(c) <= 0x30FF for c in text):
        return ("Jpan", "Hans", "Hant")
    return ("Hans", "Jpan", "Hant")


def _line_spacing(chain: list[Element], reduction: float) -> tuple[float, float | None]:
    for element in chain:
        spacing = element.find(qn("a:lnSpc"))
        if spacing is None:
            continue
        percent = spacing.find(qn("a:spcPct"))
        if percent is not None:
            return max(int(percent.get("val", "100000")) / 100000 - reduction, 0.1), None
        points = spacing.find(qn("a:spcPts"))
        if points is not None:
            return 1.0, int(points.get("val", "0")) / 100
    return max(1.0 - reduction, 0.1), None


def _paragraph_space(chain: list[Element], tag: str, size: float) -> float:
    for element in chain:
        spacing = element.find(qn(tag))
        if spacing is None:
            continue
        points = spacing.find(qn("a:spcPts"))
        if points is not None:
            return int(points.get("val", "0")) / 100
        percent = spacing.find(qn("a:spcPct"))
        if percent is not None:
            return int(percent.get("val", "0")) / 100000 * size * 1.2
    return 0.0


def _indents(chain: list[Element]) -> tuple[float, float]:
    margin = next((int(e.get("marL", "0")) for e in chain if e.get("marL") is not None), 0)
    indent = next((int(e.get("indent", "0")) for e in chain if e.get("indent") is not None), 0)
    bullet = next((c.tag for e in chain for c in e if c.tag in _BULLET_SETTINGS), qn("a:buNone"))
    first = margin + indent
    if bullet in _BULLETS and indent < 0:
        first = margin  # the bullet sits in the hanging indent; text starts at the margin
    return max(first, 0) / EMU_PER_PT, max(margin, 0) / EMU_PER_PT


def _group_scale(element: Element) -> tuple[float, float]:
    scale_x = scale_y = 1.0
    parent = element.getparent()
    while parent is not None:
        if parent.tag == qn("p:grpSp"):
            xfrm = parent.find(f"{qn('p:grpSpPr')}/{qn('a:xfrm')}")
            ext = xfrm.find(qn("a:ext")) if xfrm is not None else None
            child = xfrm.find(qn("a:chExt")) if xfrm is not None else None
            if ext is not None and child is not None:
                cx, ccx = int(ext.get("cx", "0")), int(child.get("cx", "0"))
                cy, ccy = int(ext.get("cy", "0")), int(child.get("cy", "0"))
                scale_x *= cx / ccx if ccx else 1.0
                scale_y *= cy / ccy if ccy else 1.0
        parent = parent.getparent()
    return scale_x, scale_y


def _ancestor(element: Element, tag: str) -> Element | None:
    parent = element.getparent()
    while parent is not None and parent.tag != tag:
        parent = parent.getparent()
    return parent


def _find_placeholder(
    root: Element, kind: str, index: str | None, *, by_type_only: bool
) -> Element | None:
    normalized = {"ctrTitle": "title", "subTitle": "body", "obj": "body"}.get(kind, kind)
    candidates: list[tuple[Element, str, str | None]] = []
    for shape in root.iter(qn("p:sp")):
        ph = shape.find(f"{qn('p:nvSpPr')}/{qn('p:nvPr')}/{qn('p:ph')}")
        if ph is not None:
            candidates.append((shape, ph.get("type", "body"), ph.get("idx")))
    if index is not None and not by_type_only:
        for shape, _, idx in candidates:
            if idx == index:
                return shape
    for shape, other_kind, _ in candidates:
        other = {"ctrTitle": "title", "subTitle": "body", "obj": "body"}.get(other_kind, other_kind)
        if other == normalized:
            return shape
    return None


def _explicit_bounds(shape: Element) -> tuple[float, float, float, float] | None:
    if _ancestor(shape, qn("p:grpSp")) is not None:
        return None
    transform = shape.find(f"{qn('p:spPr')}/{qn('a:xfrm')}")
    if transform is None:
        transform = shape.find(qn("p:xfrm"))
    if transform is None or any(
        transform.get(k, "0") not in ("0", "false") for k in ("rot", "flipH", "flipV")
    ):
        return None
    off, ext = transform.find(qn("a:off")), transform.find(qn("a:ext"))
    if off is None or ext is None:
        return None
    x, y = int(off.get("x", "0")) / EMU_PER_PT, int(off.get("y", "0")) / EMU_PER_PT
    return x, y, x + int(ext.get("cx", "0")) / EMU_PER_PT, y + int(ext.get("cy", "0")) / EMU_PER_PT


def _intersects(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    return min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1])
