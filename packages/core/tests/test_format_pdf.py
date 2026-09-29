"""PDF adapter (ADR-018): replacement keeps artwork, removes source text, fits by placement."""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportMissingTypeStubs=false, reportAttributeAccessIssue=false

import hashlib
import re
from pathlib import Path

import pymupdf
import pytest
from support.fakes import FakeTranslator
from support.fonts import TEST_FONT, synthetic_font_manifest
from support.pdf import (
    LINK_URI,
    drawings,
    image_count,
    links,
    page_text,
    text_blocks,
    write_image_only,
    write_mixed,
    write_pdf,
)

from doctranslator_core.config import DocumentLimits
from doctranslator_core.formats.pdf.adapter import PdfAdapter
from doctranslator_core.formats.pdf.layout import (
    FontResolver,
    PdfStyle,
    alignment,
    floor_scale,
    region_for,
)
from doctranslator_core.inline import Text
from doctranslator_core.pipeline import translate_document
from doctranslator_core.types import (
    DocumentTranslationOptions,
    DocumentTranslationResult,
    FitOptions,
    FitStatus,
    InvalidDocumentError,
    Language,
    NoExtractableTextError,
    UnsupportedDocumentError,
)

OPTIONS = DocumentTranslationOptions(source=Language.ZH, target=Language.EN)
CJK = re.compile(r"[㐀-鿿]")


def translate(
    source: Path, translator: FakeTranslator | None = None
) -> tuple[Path, DocumentTranslationResult]:
    output = source.with_name("out.pdf")
    result = translate_document(
        translator or FakeTranslator(),
        source,
        output,
        options=OPTIONS,
        fingerprint="f",
        limits=DocumentLimits(),
    )
    return output, result


def english(text: str, _: Language) -> str:
    """A plausible English length: about two Latin letters per Chinese character."""
    return " ".join("word" for _ in range(max(1, len(CJK.findall(text)) // 2)))


def test_text_is_replaced_and_artwork_links_and_numbers_are_kept(tmp_path: Path) -> None:
    source = write_mixed(tmp_path / "mixed.pdf")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    translator = FakeTranslator(english)
    output, result = translate(source, translator)

    text = page_text(output)
    assert not CJK.search(text), "no source text may remain extractable"
    assert text.count("word") >= 20
    assert "3" in text  # the page number is not translatable and stays
    assert image_count(output) == image_count(source) == 1
    assert links(output) == [LINK_URI]
    # every drawing of the source except the link underline is still there
    kept = [d for d in drawings(source) if d != (72.0, 432.0, 168.0, 432.0)]
    after = drawings(output)
    assert all(d in after for d in kept)
    with pymupdf.open(source) as before_doc, pymupdf.open(output) as after_doc:
        assert after_doc[0].rect == before_doc[0].rect
    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest
    assert result.fit_report.format.value == "pdf"
    assert result.fit_report.measurement.startswith("pdf-v1")
    assert result.fit_report.inspected == 10  # every translated unit, not the page number
    assert result.counts.segments == 11


def test_units_follow_paragraphs_list_items_and_cells(tmp_path: Path) -> None:
    source = write_mixed(tmp_path / "mixed.pdf")
    translator = FakeTranslator()
    translate(source, translator)
    inputs = translator.inputs
    # the two-line paragraph is one engine input; list markers never reach the engine
    assert "本季度销售额增长了百分之十二，主要原因是华东地区的新客户数量显著增加。" in inputs
    assert {"销售额增长", "利润率稳定", "客户数量增加"} <= set(inputs)
    assert "华东地区" in inputs and "华南地区" in inputs  # side-by-side cells stay separate
    assert not any("·" in text or "•" in text for text in inputs)
    # the red span keeps its own formatting through a tag
    assert any(text.startswith("<g1>成本控制</g1>") for text in inputs)


def test_list_markers_are_written_back(tmp_path: Path) -> None:
    source = write_mixed(tmp_path / "mixed.pdf")
    output, _ = translate(source, FakeTranslator(english))
    assert page_text(output).count("·") + page_text(output).count("•") == 3


def test_growth_shrinks_within_the_floor(tmp_path: Path) -> None:
    source = write_mixed(tmp_path / "mixed.pdf")
    label = FakeTranslator(lambda text, _: "longer " * 6 if text == "分析趋势" else "Text")
    _, result = translate(source, label)
    [entry] = result.fit_report.entries  # the centered label in its small box
    assert (entry.location, entry.status, entry.reason) == (
        "page 1, text 9",
        "adjusted",
        "shrunk_to_fit",
    )
    [original], [final] = entry.original_sizes_pt, entry.final_sizes_pt
    assert max(8.0, 0.7 * original) - 0.01 <= final < original
    assert result.fit_report.status is FitStatus.ADJUSTED


def test_overflow_at_floor_is_unresolved_and_text_is_never_dropped(tmp_path: Path) -> None:
    def build(page: pymupdf.Page) -> None:
        page.draw_rect(pymupdf.Rect(72, 72, 172, 100), color=(0, 0, 0), fill=(0.9, 0.9, 0.9))
        page.insert_text((78, 90), "分析", fontname="china-s", fontsize=12)
        page.insert_text((72, 140), "下一段文字", fontname="china-s", fontsize=12)

    source = write_pdf(tmp_path / "box.pdf", build)
    words = " ".join(f"word{i}" for i in range(40))
    translator = FakeTranslator(lambda text, _: words if text == "分析" else "Next paragraph")
    output, result = translate(source, translator)
    assert result.fit_report.status is FitStatus.UNRESOLVED
    [entry] = result.fit_report.entries
    assert entry.reason == "overflow_at_floor"
    assert entry.final_sizes_pt == [8.4]  # 70% of 12 pt: floor sizes are kept
    assert "".join(words.split()) in "".join(page_text(output).split())


def test_small_text_is_never_shrunk(tmp_path: Path) -> None:
    assert floor_scale([7.0, 12.0], FitOptions()) == 1.0
    assert floor_scale([12.0], FitOptions()) == pytest.approx(0.7)
    assert floor_scale([10.0], FitOptions()) == pytest.approx(0.8)
    assert floor_scale([], FitOptions()) == 1.0


def test_region_grows_into_free_space_but_not_over_neighbours() -> None:
    unit = (100.0, 100.0, 150.0, 112.0)
    bounds = (36.0, 36.0, 559.0, 806.0)
    right_neighbour = (300.0, 101.0, 350.0, 111.0)
    below = (100.0, 160.0, 200.0, 172.0)
    region = region_for(unit, "left", None, [right_neighbour, below], bounds)
    assert region == (100.0, 100.0, 298.0, 158.0)
    cell = (95.0, 95.0, 200.0, 125.0)
    inside = region_for(unit, "left", cell, [right_neighbour, below], bounds)
    assert inside == (100.0, 100.0, 195.0, 120.0)
    # a centered unit grows symmetrically
    centered = region_for((127.5, 100.0, 167.5, 112.0), "center", cell, [], bounds)
    assert centered[0] - cell[0] == pytest.approx(cell[2] - centered[2])
    # the region never shrinks below the original extent
    tight = region_for(unit, "left", None, [(151.0, 100.0, 160.0, 112.0)], bounds)
    assert tight[2] >= unit[2]


def test_alignment_from_lines_boxes_and_page() -> None:
    box = (100.0, 100.0, 200.0, 130.0)
    assert alignment([(130.0, 110.0, 170.0, 120.0)], box, 595) == "center"
    assert alignment([(105.0, 110.0, 150.0, 120.0)], box, 595) == "left"
    assert alignment([(150.0, 110.0, 195.0, 120.0)], box, 595) == "right"
    assert alignment([(250.0, 50.0, 345.0, 70.0)], None, 595) == "center"
    lines = [(100.0, 0.0, 200.0, 10.0), (120.0, 12.0, 180.0, 22.0)]
    assert alignment(lines, None, 595) == "center"


def test_fonts_resolve_by_postscript_name_and_fall_back(tmp_path: Path) -> None:
    resolver = FontResolver(synthetic_font_manifest(tmp_path))
    face = resolver.lookup("TestSans-Bold", bold=True, italic=False)
    assert face is not None and face.family == TEST_FONT
    assert resolver.lookup("TestSansMT", bold=False, italic=False) is not None
    assert resolver.lookup("Unknown", bold=False, italic=False) is None
    style = PdfStyle(size=12, bold=False, italic=False, color=0)
    assert resolver.choose("TestSans", style, "Hello", Language.EN).substituted is False
    fallback = resolver.choose("Missing-Font", style, "Hello", Language.EN)
    assert fallback.face is None and fallback.family == "sans-serif" and fallback.substituted
    assert resolver.choose("TimesNewRomanPS-BoldMT", style, "Hi", Language.EN).family == "serif"


def test_font_substitution_is_disclosed(tmp_path: Path) -> None:
    source = write_mixed(tmp_path / "mixed.pdf")
    _, result = translate(source, FakeTranslator(english))
    codes = {d.code: d for d in result.diagnostics}
    assert codes["pdf_font_substituted"].count == 10


def test_scanned_pdf_is_a_typed_no_extractable_text_error(tmp_path: Path) -> None:
    source = write_image_only(tmp_path / "scan.pdf")
    with pytest.raises(NoExtractableTextError, match="OCR"):
        translate(source)
    assert not (tmp_path / "out.pdf").exists()


def test_mostly_image_page_with_text_is_reported(tmp_path: Path) -> None:
    def build(page: pymupdf.Page) -> None:
        pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 10, 10), False)
        page.insert_image(pymupdf.Rect(0, 0, 595, 600), pixmap=pixmap)
        page.insert_text((72, 700), "图片说明文字", fontname="china-s", fontsize=12)

    source = write_pdf(tmp_path / "scan-text.pdf", build)
    _, result = translate(source)
    [warning] = [d for d in result.diagnostics if d.code == "untranslated_image_content"]
    assert warning.location == "page 1"


def test_encrypted_and_signed_pdfs_are_rejected(tmp_path: Path) -> None:
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "机密文字", fontname="china-s")
    encrypted = tmp_path / "encrypted.pdf"
    doc.save(encrypted, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="u", owner_pw="o")
    signed = tmp_path / "signed.pdf"
    doc.xref_set_key(doc.pdf_catalog(), "AcroForm", "<</Fields[]/SigFlags 3>>")
    doc.save(signed)
    doc.close()
    with pytest.raises(UnsupportedDocumentError, match="encrypted"):
        translate(encrypted)
    with pytest.raises(UnsupportedDocumentError, match="signed"):
        translate(signed)


def test_rotated_text_is_kept_and_reported(tmp_path: Path) -> None:
    def build(page: pymupdf.Page) -> None:
        page.insert_text((72, 100), "正文文字", fontname="china-s", fontsize=12)
        page.insert_text((300, 400), "旋转文字", fontname="china-s", fontsize=12, rotate=90)

    source = write_pdf(tmp_path / "rotated.pdf", build)
    output, result = translate(source)
    assert "旋转文字" in page_text(output)
    assert "正文文字" not in page_text(output)
    assert "pdf_rotated_text_kept" in {d.code for d in result.diagnostics}


def test_rotated_page_is_translated_in_place(tmp_path: Path) -> None:
    def build(page: pymupdf.Page) -> None:
        page.insert_text((72, 100), "旋转页面", fontname="china-s", fontsize=12)
        page.set_rotation(90)

    source = write_pdf(tmp_path / "page90.pdf", build)
    output, _ = translate(source)
    with pymupdf.open(output) as doc:
        assert doc[0].rotation == 90
    [block] = text_blocks(output)
    assert block[0] == pytest.approx(72, abs=1)  # same place as the source text
    assert not CJK.search(page_text(output))


def test_verification_detects_a_missing_translation(tmp_path: Path) -> None:
    source = write_mixed(tmp_path / "mixed.pdf")
    adapter = PdfAdapter(source, DocumentLimits())
    first = adapter.paragraphs()[0]
    adapter.apply(first.id, (Text("Hello", 0),), Language.EN)  # applied but never placed
    written = tmp_path / "written.pdf"
    adapter.save(written)
    reopened = PdfAdapter(written, DocumentLimits())
    reopened.paragraphs()
    with pytest.raises(InvalidDocumentError, match="missing"):
        adapter.verify_output(reopened)
    reopened.close()
    adapter.close()


def test_output_fonts_are_subset(tmp_path: Path) -> None:
    source = write_mixed(tmp_path / "mixed.pdf")
    output, _ = translate(source, FakeTranslator(english))
    assert output.stat().st_size < 200_000
