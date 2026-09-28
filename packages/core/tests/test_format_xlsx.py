"""XLSX adapter: literal cell text only; formulas, values and sheet names preserved (ADR-009)."""

from pathlib import Path

import pytest
from support.fakes import FakeTranslator, copy_fixture
from support.ooxml import CJK, NS, entries, texts, xml

from doctranslator_core.config import DocumentLimits
from doctranslator_core.pipeline import translate_document
from doctranslator_core.types import DocumentTranslationOptions, DocumentTranslationResult, Language

OPTIONS = DocumentTranslationOptions(source=Language.ZH, target=Language.EN)
S = f"{{{NS['s']}}}"


def translate(
    source: Path, translator: FakeTranslator | None = None
) -> tuple[Path, DocumentTranslationResult]:
    output = source.with_name("out.xlsx")
    result = translate_document(
        translator or FakeTranslator(),
        source,
        output,
        options=OPTIONS,
        fingerprint="f",
        limits=DocumentLimits(),
    )
    return output, result


def cells(path: Path, part: str) -> dict[str, tuple[str | None, str | None, str | None]]:
    """Cell reference -> (type, formula, value) for a worksheet."""
    root = xml(path, part)
    return {
        str(c.get("r")): (c.get("t"), c.findtext(f"{S}f"), c.findtext(f"{S}v"))
        for c in root.iter(f"{S}c")
    }


def sheet_parts(path: Path) -> list[str]:
    return sorted(n for n in entries(path) if n.startswith("xl/worksheets/sheet"))


@pytest.mark.parametrize("fixture", ["xlsx/features-shared.xlsx", "xlsx/features-inline.xlsx"])
def test_literal_text_is_translated_and_everything_else_is_kept(
    tmp_path: Path, fixture: str
) -> None:
    source = copy_fixture(fixture, tmp_path)
    output, _ = translate(source)
    for part in sheet_parts(source):
        before, after = cells(source, part), cells(output, part)
        assert before.keys() == after.keys()
        for ref, (kind, formula, value) in before.items():
            if kind in ("s", "inlineStr"):
                assert after[ref][0] == kind, ref
            else:
                assert after[ref] == (kind, formula, value), ref
    workbook_before = xml(source, "xl/workbook.xml")
    workbook_after = xml(output, "xl/workbook.xml")
    names = [s.get("name") for s in workbook_before.iter(f"{S}sheet")]
    assert [s.get("name") for s in workbook_after.iter(f"{S}sheet")] == names
    calc = workbook_after.find(f"{S}calcPr")
    assert calc is not None and calc.get("fullCalcOnLoad") == "1"
    referenced = {
        int(value or "-1")
        for part in sheet_parts(output)
        for kind, _, value in cells(output, part).values()
        if kind == "s"
    }
    if referenced:
        items = list(xml(output, "xl/sharedStrings.xml").iter(f"{S}si"))
        for index in referenced:
            text = "".join(t.text or "" for t in items[index].iter(f"{S}t"))
            assert not CJK.search(text), index
    else:
        # The inline-string fixture keeps an unreferenced shared-string table: left untouched.
        assert entries(output)["xl/sharedStrings.xml"] == entries(source)["xl/sharedStrings.xml"]
    for part in sheet_parts(output):
        inline = [t for t in texts(output, part, "s:t") if CJK.search(t)]
        assert inline == [], part


def test_untouched_parts_are_byte_identical(tmp_path: Path) -> None:
    source = copy_fixture("xlsx/features-shared.xlsx", tmp_path)
    output, result = translate(source)
    before, after = entries(source), entries(output)
    assert list(before) == list(after)
    changed = {n for n in before if before[n] != after[n]}
    # XlsxWriter already wrote fullCalcOnLoad="1", so the workbook part needs no change.
    assert b'fullCalcOnLoad="1"' in before["xl/workbook.xml"]
    assert changed == {"xl/sharedStrings.xml"}
    codes = {d.code for d in result.diagnostics}
    assert {
        "drawing_text_not_translated",
        "comments_not_translated",
        "formulas_recalculate_on_open",
    } <= codes


def test_rich_text_runs_keep_their_properties(tmp_path: Path) -> None:
    source = copy_fixture("xlsx/features-shared.xlsx", tmp_path)
    translator = FakeTranslator()
    output, _ = translate(source, translator)
    assert any("<g1>" in text for text in translator.inputs)
    shared = xml(output, "xl/sharedStrings.xml")
    original = xml(source, "xl/sharedStrings.xml")
    rich_after = [si for si in shared.iter(f"{S}si") if si.find(f"{S}r") is not None]
    rich_before = [si for si in original.iter(f"{S}si") if si.find(f"{S}r") is not None]
    assert len(rich_after) == len(rich_before) >= 1
    bold_before = [
        r.findtext(f"{S}t")
        for r in rich_before[0].iter(f"{S}r")
        if r.find(f"{S}rPr/{S}b") is not None
    ]
    bold_after = [
        r.findtext(f"{S}t")
        for r in rich_after[0].iter(f"{S}r")
        if r.find(f"{S}rPr/{S}b") is not None
    ]
    assert len(bold_after) == len(bold_before) == 1
    assert bold_after[0] and not CJK.search(bold_after[0])


def test_formulas_depending_on_translated_labels_are_reported(tmp_path: Path) -> None:
    source = copy_fixture("xlsx/labels.xlsx", tmp_path)
    output, result = translate(source)
    warned = sorted(
        d.location or ""
        for d in result.diagnostics
        if d.code == "formula_literal_matches_translated_text"
    )
    assert warned == [
        'sheet "数据" / C1',
        'sheet "数据" / C3',
        'sheet "数据" / C4',
        'sheet "数据" / C5',
    ]
    assert cells(output, "xl/worksheets/sheet1.xml")["C1"][1] == 'COUNTIF(A1:A3,"苹果")'


def test_string_starting_with_equals_stays_a_string(tmp_path: Path) -> None:
    source = copy_fixture("xlsx/features-shared.xlsx", tmp_path)
    translator = FakeTranslator(lambda text, target: "=SUM(1,2)" if text == "地区" else f"T:{text}")
    output, _ = translate(source, translator)
    shared = texts(output, "xl/sharedStrings.xml", "s:t")
    index = shared.index("=SUM(1,2)")
    users = [
        (kind, formula)
        for part in sheet_parts(output)
        for kind, formula, value in cells(output, part).values()
        if kind == "s" and value == str(index)
    ]
    assert users and all(u == ("s", None) for u in users)


def test_workbook_without_calc_request_gets_one(tmp_path: Path) -> None:
    source = copy_fixture("xlsx/labels.xlsx", tmp_path)
    assert b"fullCalcOnLoad" not in entries(source)["xl/workbook.xml"]
    output, _ = translate(source)
    calc = xml(output, "xl/workbook.xml").find(f"{S}calcPr")
    assert calc is not None and calc.get("fullCalcOnLoad") == "1"


def test_hidden_sheets_are_translated(tmp_path: Path) -> None:
    source = copy_fixture("xlsx/labels.xlsx", tmp_path)
    from support.ooxml import rewrite

    hidden = rewrite(
        source,
        tmp_path / "hidden.xlsx",
        "xl/workbook.xml",
        lambda data: data.replace(
            b'name="\xe6\xb1\x87\xe6\x80\xbb"', b'name="\xe6\xb1\x87\xe6\x80\xbb" state="hidden"'
        ),
    )
    translator = FakeTranslator()
    output, _ = translate(hidden, translator)
    assert "苹果数量" in translator.inputs
    assert b'state="hidden"' in entries(output)["xl/workbook.xml"]
