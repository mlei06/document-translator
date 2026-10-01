"""Independent measurement and saved Office patch regressions."""

from dataclasses import replace
from pathlib import Path

from support.fakes import copy_fixture
from support.fonts import TEST_FONT, synthetic_font_manifest

from doctranslator_core.config import DocumentLimits
from doctranslator_core.document import LayoutContainer, LayoutParagraph, LayoutPatch, LayoutRun
from doctranslator_core.fit.fitter import fit_container
from doctranslator_core.fit.fonts import FontLibrary
from doctranslator_core.fit.office import target_fonts
from doctranslator_core.formats.pptx.adapter import PptxAdapter
from doctranslator_core.types import FitOptions


def box(text: str, font: str = TEST_FONT) -> LayoutContainer:
    run = LayoutRun(text, 10, font, font)
    return LayoutContainer(
        "1", "test", "shape", 100, 12, True, (LayoutParagraph((run,), run),), line_metric="em"
    )


def test_unknown_source_does_not_block_target(tmp_path: Path) -> None:
    library = FontLibrary(synthetic_font_manifest(tmp_path))
    result = fit_container(
        box("source", "Absent"),
        box("aaaa bbbb cccc dddd eeee"),
        FitOptions(),
        library,
        independent_source=True,
    )
    assert result.status == "unresolved"
    assert result.sizes == [[8.0]]
    assert result.entry is not None
    assert result.entry.reason == "source_measurement_unknown"
    assert result.entry.original_extent is None
    assert result.entry.final_extent is not None
    assert result.entry.final_extent.height_pt == 9.6
    library.close()


def test_target_fallback_has_explicit_slot(tmp_path: Path) -> None:
    library = FontLibrary(synthetic_font_manifest(tmp_path))
    current = box("English", "Absent")
    current = replace(
        current,
        paragraphs=tuple(
            replace(p, runs=tuple(replace(r, fallback_fonts=(TEST_FONT,)) for r in p.runs))
            for p in current.paragraphs
        ),
    )
    resolved = target_fonts(current, library)
    assert resolved.paragraphs[0].runs[0].latin_font == TEST_FONT
    assert resolved.paragraphs[0].runs[0].text == "English"
    library.close()


def test_font_patch_roundtrip_and_stale_rejection(tmp_path: Path) -> None:
    import pytest

    path = copy_fixture("pptx/deck.pptx", tmp_path)
    adapter = PptxAdapter(path, DocumentLimits())
    current = next(c for c in adapter.layout_context() if any(p.runs for p in c.paragraphs))
    updated = replace(
        current,
        paragraphs=tuple(
            replace(
                p,
                runs=tuple(
                    replace(r, latin_font=TEST_FONT, east_asian_font=TEST_FONT) for r in p.runs
                ),
            )
            for p in current.paragraphs
        ),
    )
    patch = LayoutPatch(current, updated, "fonts")
    adapter.apply_layout_patch(patch)
    with pytest.raises(ValueError, match="stale"):
        adapter.apply_layout_patch(patch)
    output = tmp_path / "patched.pptx"
    adapter.save(output)
    reopened = PptxAdapter(output, DocumentLimits())
    actual = next(c for c in reopened.layout_context() if c.id == current.id)
    assert all(r.latin_font == TEST_FONT for p in actual.paragraphs for r in p.runs)
    reopened.close()
    adapter.close()


def test_growth_respects_obstacle_and_roundtrips(tmp_path: Path) -> None:
    from support.ooxml import rewrite

    source = copy_fixture("pptx/deck.pptx", tmp_path)

    def shape(number: int, x: int, width: int, text: str) -> str:
        return f'''<p:sp>
<p:nvSpPr>
<p:cNvPr id="{number}" name="box{number}"/>
<p:cNvSpPr txBox="1"/>
<p:nvPr/>
</p:nvSpPr>
<p:spPr>
<a:xfrm>
<a:off x="{x}" y="1270000"/>
<a:ext cx="{width}" cy="1270000"/>
</a:xfrm>
<a:prstGeom prst="rect">
<a:avLst/>
</a:prstGeom>
</p:spPr>
<p:txBody>
<a:bodyPr/>
<a:lstStyle/>
<a:p>
<a:r>
<a:rPr sz="1200">
<a:latin typeface="Test Sans"/>
</a:rPr>
<a:t>{text}</a:t>
</a:r>
</a:p>
</p:txBody>
</p:sp>'''

    body = (
        """<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
<p:cSld>
<p:spTree>
<p:nvGrpSpPr>
<p:cNvPr id="1" name=""/>
<p:cNvGrpSpPr/>
<p:nvPr/>
</p:nvGrpSpPr>
<p:grpSpPr/>"""
        + shape(2, 1270000, 1270000, "left")
        + shape(3, 2667000, 1270000, "right")
        + "</p:spTree></p:cSld></p:sld>"
    )
    path = rewrite(
        source, tmp_path / "growth.pptx", "ppt/slides/slide1.xml", lambda _: body.encode()
    )
    adapter = PptxAdapter(path, DocumentLimits())
    current = next(c for c in adapter.layout_context() if c.page_index == 0)
    assert current.bounds_pt == (100, 100, 200, 200)
    assert current.growth_bounds_pt == (100, 100, 208, 220)
    assert current.content_bounds_pt is not None
    assert current.width_pt is not None and current.height_pt is not None
    b = current.content_bounds_pt
    grown = replace(
        current,
        bounds_pt=current.growth_bounds_pt,
        width_pt=current.width_pt + 8,
        height_pt=current.height_pt + 20,
        content_bounds_pt=(b[0], b[1], b[2] + 8, b[3] + 20),
    )
    adapter.apply_layout_patch(LayoutPatch(current, grown, "geometry"))
    output = tmp_path / "grown.pptx"
    adapter.save(output)
    reopened = PptxAdapter(output, DocumentLimits())
    result = next(c for c in reopened.layout_context() if c.id == current.id)
    assert result.bounds_pt == grown.bounds_pt
    neighbour = next(
        c for c in reopened.layout_context() if c.page_index == 0 and c.id != current.id
    )
    assert neighbour.bounds_pt == (210, 100, 310, 200)
    reopened.close()
    adapter.close()


def test_skip_discards_uncommitted_candidates(tmp_path: Path) -> None:
    from doctranslator_core.fit.office import fit_office_container

    library = FontLibrary(synthetic_font_manifest(tmp_path))
    current = replace(
        box("aaaa bbbb cccc dddd eeee"),
        bounds_pt=(0, 0, 100, 12),
        content_bounds_pt=(0, 0, 100, 12),
        growth_bounds_pt=(0, 0, 120, 14.4),
    )
    patches: list[LayoutPatch] = []
    calls = 0

    def stop() -> bool:
        nonlocal calls
        calls += 1
        return calls >= 4

    outcome = fit_office_container(
        box("short"), current, FitOptions(), library, patches.append, lambda: [current], stop
    )
    assert outcome.status == "skipped"
    assert patches == []
    library.close()


def test_missing_bold_face_does_not_claim_supported_measurement(tmp_path: Path) -> None:
    library = FontLibrary(synthetic_font_manifest(tmp_path))
    original = box("bold")
    bold = replace(
        original,
        paragraphs=tuple(
            replace(p, runs=tuple(replace(r, bold=True) for r in p.runs))
            for p in original.paragraphs
        ),
    )
    assert target_fonts(bold, library).unsupported == "target_font_style_unavailable"
    library.close()


def test_growth_report_records_serialized_operations(tmp_path: Path) -> None:
    from doctranslator_core.fit.office import fit_office_container

    library = FontLibrary(synthetic_font_manifest(tmp_path))
    current = replace(
        box("aaaa bbbb cccc dddd eeee"),
        bounds_pt=(0, 0, 100, 12),
        content_bounds_pt=(0, 0, 100, 12),
        growth_bounds_pt=(0, 0, 120, 14.4),
    )
    initial = current

    def apply(patch: LayoutPatch) -> None:
        nonlocal current
        assert patch.expected == current
        current = patch.replacement

    outcome = fit_office_container(
        box("short"), current, FitOptions(), library, apply, lambda: [current]
    )
    assert outcome.entry is not None
    assert outcome.entry.operations == ("geometry",)
    assert outcome.entry.original_bounds_pt == initial.bounds_pt
    assert outcome.entry.final_bounds_pt == current.bounds_pt == (0, 0, 120, 14.4)
    assert outcome.entry.original_fonts == outcome.entry.final_fonts == ((TEST_FONT, TEST_FONT),)
    assert set(outcome.entry.timings_s) == {"font_resolution", "measurement", "repair"}
    library.close()
