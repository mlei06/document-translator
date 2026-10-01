"""Read-only analysis: detection before translation and preview text units."""

from pathlib import Path

import pytest
from support.fakes import FIXTURES
from support.pdf import write_image_only, write_mixed

from doctranslator_core import detect_document, document_text
from doctranslator_core.analysis import group_of
from doctranslator_core.types import DocumentFormat, Language, NoExtractableTextError


def test_detects_format_and_source_like_translation(tmp_path: Path) -> None:
    deck = detect_document(FIXTURES / "pptx" / "deck.pptx")
    assert (deck.format, deck.source, deck.status) == (DocumentFormat.PPTX, Language.ZH, "detected")
    assert deck.segments == 16
    english = tmp_path / "notes.txt"
    english.write_text(
        "The quarterly report shows steady growth in every region we serve.\n", encoding="utf-8"
    )
    assert detect_document(english).source is Language.EN
    numbers = tmp_path / "numbers.txt"
    numbers.write_text("123 456\n789\n", encoding="utf-8")
    assert detect_document(numbers).status == "no_text"
    short = tmp_path / "short.txt"
    short.write_text("Hola\n", encoding="utf-8")
    ambiguous = detect_document(short)
    assert ambiguous.status == "ambiguous" and ambiguous.source is None
    assert ambiguous.diagnostics[0].code == "source_ambiguous"


def test_scanned_pdf_is_rejected_before_translation(tmp_path: Path) -> None:
    with pytest.raises(NoExtractableTextError):
        detect_document(write_image_only(tmp_path / "scan.pdf"))


def test_text_units_carry_locations_and_groups(tmp_path: Path) -> None:
    units = document_text(FIXTURES / "pptx" / "deck.pptx")
    assert units[0].location.startswith("slide 1 / ")
    assert {u.group for u in units} == {"slide 1", "slide 2", "slide 3"}
    assert all(u.text.strip() for u in units)
    pdf = document_text(write_mixed(tmp_path / "mixed.pdf"))
    assert {u.group for u in pdf} == {"page 1"}
    workbook = document_text(FIXTURES / "xlsx" / "features-shared.xlsx")
    assert {u.group for u in workbook} == {'sheet "销售数据"', 'sheet "说明"'}


def test_groups_per_format() -> None:
    assert group_of(DocumentFormat.PPTX, "slide 4 notes / paragraph 1") == "slide 4"
    assert group_of(DocumentFormat.DOCX, "footer 1 / paragraph 1") == "footer 1"
    assert group_of(DocumentFormat.PDF, "page 7, text 2") == "page 7"
    assert group_of(DocumentFormat.TXT, "line 1") == "lines 1-40"
    assert group_of(DocumentFormat.TXT, "line 41") == "lines 41-80"
