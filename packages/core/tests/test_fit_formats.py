"""Fit integration for XLSX and DOCX with the synthetic font (ADR-012 support boundary)."""

from pathlib import Path

import pytest
from support.fakes import FakeTranslator, copy_fixture
from support.fonts import TEST_FONT, synthetic_font_manifest
from support.ooxml import NS, rewrite, xml

from doctranslator_core.config import DocumentLimits
from doctranslator_core.pipeline import translate_document
from doctranslator_core.types import (
    DocumentTranslationOptions,
    DocumentTranslationResult,
    FitEntry,
    FitStatus,
    FontManifest,
    Language,
)

S = f"{{{NS['s']}}}"
W = f"{{{NS['w']}}}"
OPTIONS = DocumentTranslationOptions(source=Language.ZH, target=Language.EN)


@pytest.fixture(scope="module")
def manifest(tmp_path_factory: pytest.TempPathFactory) -> FontManifest:
    return synthetic_font_manifest(tmp_path_factory.mktemp("fonts"))


def _labels_in_test_font(tmp_path: Path) -> Path:
    source = copy_fixture("xlsx/labels.xlsx", tmp_path)
    return rewrite(
        source,
        tmp_path / "fit.xlsx",
        "xl/styles.xml",
        lambda d: d.replace(b'<name val="Aptos Narrow"/>', f'<name val="{TEST_FONT}"/>'.encode()),
    )


def _run(
    path: Path,
    manifest: FontManifest,
    words: dict[str, str],
    options: DocumentTranslationOptions = OPTIONS,
) -> DocumentTranslationResult:
    return translate_document(
        FakeTranslator(lambda text, target: words.get(text, "x")),
        path,
        path.with_name("out" + path.suffix),
        options=options,
        fingerprint="f",
        limits=DocumentLimits(),
        fonts=manifest,
    )


def test_xlsx_clipped_cell_is_shrunk_with_its_own_style(
    tmp_path: Path, manifest: FontManifest
) -> None:
    # Column A is 48 pt wide (45 pt of text room); B is occupied, so A's text would be clipped.
    source = _labels_in_test_font(tmp_path)
    result = _run(source, manifest, {"苹果": "Apple pie", "香蕉": "Banana", "苹果数量": "x"})
    entries = {e.location: e for e in result.fit_report.entries}
    apple = entries['sheet "数据" / A1']
    assert (apple.status, apple.final_sizes_pt) == ("adjusted", [10.0])
    out = tmp_path / "out.xlsx"
    cells = {c.get("r"): c for c in xml(out, "xl/worksheets/sheet1.xml").iter(f"{S}c")}
    styles = xml(out, "xl/styles.xml")
    xfs = styles.findall(f"{S}cellXfs/{S}xf")
    fonts = styles.findall(f"{S}fonts/{S}font")
    a1_font = fonts[int(xfs[int(cells["A1"].get("s", "0"))].get("fontId", "0"))]
    assert a1_font.find(f"{S}sz").get("val") == "10"  # type: ignore[union-attr]
    assert cells["A2"].get("s", "0") == "0"  # "Banana" fits; its shared style is untouched
    assert fonts[0].find(f"{S}sz").get("val") == "11"  # type: ignore[union-attr]
    assert result.fit_status is FitStatus.ADJUSTED


def test_xlsx_overflow_at_floor_is_unresolved(tmp_path: Path, manifest: FontManifest) -> None:
    source = _labels_in_test_font(tmp_path)
    result = _run(source, manifest, {"苹果": "Apple pie and cream", "香蕉": "B", "苹果数量": "x"})
    apple = next(e for e in result.fit_report.entries if e.location.endswith("/ A1"))
    assert (apple.status, apple.reason, apple.final_sizes_pt) == (
        "unresolved",
        "overflow_at_floor",
        [8.0],
    )
    assert result.fit_status is FitStatus.UNRESOLVED


def test_xlsx_text_that_can_spill_is_not_constrained(
    tmp_path: Path, manifest: FontManifest
) -> None:
    # 苹果数量 on sheet 汇总 A1 has B1 occupied by a formula: constrained. Clear it by editing B1
    # out of the second sheet so the cell may spill into the empty neighbour.
    source = _labels_in_test_font(tmp_path)
    spill = rewrite(
        source,
        tmp_path / "spill.xlsx",
        "xl/worksheets/sheet2.xml",
        lambda d: d[: d.index(b'<c r="B1"')] + d[d.index(b"</c>", d.index(b'<c r="B1"')) + 4 :],
    )
    result = _run(spill, manifest, {"苹果": "A", "香蕉": "B", "苹果数量": "Apple count long label"})
    assert not any(
        e.location.endswith("/ A1") and "汇总" in e.location for e in result.fit_report.entries
    )


def _docx_with_fixed_cell(tmp_path: Path, text: str) -> Path:
    """The report fixture with a 75 pt fixed-layout cell, 15 pt exact row, Test Sans 10 pt."""
    source = copy_fixture("docx/report.docx", tmp_path)
    fonts = f'<w:rFonts w:ascii="{TEST_FONT}" w:hAnsi="{TEST_FONT}" w:eastAsia="{TEST_FONT}"/>'
    table = (
        f'<w:tbl xmlns:w="{NS["w"]}"><w:tblPr><w:tblW w:w="1500" w:type="dxa"/>'
        '<w:tblLayout w:type="fixed"/></w:tblPr><w:tblGrid><w:gridCol w:w="1500"/></w:tblGrid>'
        '<w:tr><w:trPr><w:trHeight w:val="300" w:hRule="exact"/></w:trPr><w:tc><w:tcPr>'
        '<w:tcW w:w="1500" w:type="dxa"/></w:tcPr><w:p><w:pPr>'
        '<w:spacing w:before="0" w:after="0"/></w:pPr><w:r><w:rPr>'
        f'{fonts}<w:sz w:val="20"/></w:rPr><w:t>{text}</w:t></w:r></w:p></w:tc></w:tr></w:tbl>'
    ).encode()

    def add_table(data: bytes) -> bytes:
        body = data.index(b"<w:body>") + len(b"<w:body>")
        return data[:body] + table + data[body:]

    return rewrite(source, tmp_path / "cell.docx", "word/document.xml", add_table)


def _cell_entry(result: DocumentTranslationResult) -> FitEntry | None:
    return next(
        (e for e in result.fit_report.entries if "table 1 / row 1 / cell 1" in e.location), None
    )


def test_docx_fixed_cell_with_east_asian_text_is_unresolved(
    tmp_path: Path, manifest: FontManifest
) -> None:
    edited = _docx_with_fixed_cell(tmp_path, "固定单元格")
    result = _run(edited, manifest, {"固定单元格": "Fixed cell text"})
    cell = _cell_entry(result)
    # Source East Asian layout stays unknown; the supported Latin target is fitted (ADR-026).
    assert cell is not None
    assert (cell.status, cell.reason, cell.final_sizes_pt) == (
        "unresolved",
        "source_measurement_unknown",
        [8.5],
    )


def test_docx_fixed_cell_with_latin_text_is_fitted(tmp_path: Path, manifest: FontManifest) -> None:
    # 75 pt cell minus 2 x 5.4 pt margins = 64.2 pt; one 10 pt line of Test Sans is 12.8 chars.
    edited = _docx_with_fixed_cell(tmp_path, "Celda fija")
    options = DocumentTranslationOptions(source=Language.ES, target=Language.EN)
    result = _run(edited, manifest, {"Celda fija": "Fixed cell texts"}, options)
    cell = _cell_entry(result)
    assert cell is not None
    assert (cell.status, cell.reason) == ("adjusted", "shrunk_to_fit")
    assert cell.final_sizes_pt[0] < 10.0
    sizes = [
        e.get(f"{W}val") for e in xml(tmp_path / "out.docx", "word/document.xml").iter(f"{W}sz")
    ]
    assert str(round(cell.final_sizes_pt[0] * 2)) in sizes
