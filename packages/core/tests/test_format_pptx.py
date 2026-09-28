"""PPTX adapter: coverage, formatting preservation and untouched parts (ADR-011)."""

import hashlib
from pathlib import Path

from support.fakes import FakeTranslator, copy_fixture
from support.ooxml import CJK, NS, entries, rewrite, texts, xml

from doctranslator_core.config import DocumentLimits
from doctranslator_core.pipeline import translate_document
from doctranslator_core.types import DocumentTranslationOptions, Language

OPTIONS = DocumentTranslationOptions(source=Language.ZH, target=Language.EN)
A = f"{{{NS['a']}}}"


def translate(source: Path, translator: FakeTranslator | None = None) -> Path:
    output = source.with_name("out.pptx")
    translate_document(
        translator or FakeTranslator(),
        source,
        output,
        options=OPTIONS,
        fingerprint="f",
        limits=DocumentLimits(),
    )
    return output


def test_every_slide_and_notes_text_is_translated(tmp_path: Path) -> None:
    source = copy_fixture("pptx/deck.pptx", tmp_path)
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    output = translate(source)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    for part in (
        "ppt/slides/slide1.xml",
        "ppt/slides/slide2.xml",
        "ppt/slides/slide3.xml",
        "ppt/notesSlides/notesSlide1.xml",
    ):
        remaining = [t for t in texts(output, part, "a:t") if CJK.search(t)]
        assert remaining == [], part


def test_only_edited_parts_change(tmp_path: Path) -> None:
    source = copy_fixture("pptx/deck.pptx", tmp_path)
    output = translate(source)
    before, after = entries(source), entries(output)
    assert list(before) == list(after)
    changed = {name for name in before if before[name] != after[name]}
    assert changed == {
        "ppt/slides/slide1.xml",
        "ppt/slides/slide2.xml",
        "ppt/slides/slide3.xml",
        "ppt/notesSlides/notesSlide1.xml",
    }


def test_run_formatting_and_hyperlinks_are_kept(tmp_path: Path) -> None:
    source = copy_fixture("pptx/deck.pptx", tmp_path)
    translator = FakeTranslator()
    output = translate(source, translator)
    assert "<g1>销售额</g1>增长了百分之十二" in translator.inputs
    body = xml(output, "ppt/slides/slide2.xml")
    runs = [r for r in body.iter(f"{A}r")]
    bold = [r for r in runs if (rpr := r.find(f"{A}rPr")) is not None and rpr.get("b") == "1"]
    assert [r.findtext(f"{A}t") for r in bold] == ["xxx"]
    color = bold[0].find(f"{A}rPr/{A}solidFill/{A}srgbClr")
    assert color is not None and color.get("val") == "FF0000"
    links = [r for r in runs if r.find(f"{A}rPr/{A}hlinkClick") is not None]
    assert [r.findtext(f"{A}t") for r in links] == ["xxxx"]


def test_language_split_runs_merge_and_lang_is_retagged(tmp_path: Path) -> None:
    source = copy_fixture("pptx/deck.pptx", tmp_path)
    translator = FakeTranslator()
    output = translate(source, translator)
    assert "1,250 万元" in translator.inputs
    langs = {r.get("lang") for r in xml(output, "ppt/slides/slide3.xml").iter(f"{A}rPr")}
    assert "zh-CN" not in langs


def test_fields_charts_and_smartart(tmp_path: Path) -> None:
    source = copy_fixture("pptx/deck.pptx", tmp_path)
    translator = FakeTranslator()
    output = translate_document(
        translator,
        source,
        tmp_path / "out.pptx",
        options=OPTIONS,
        fingerprint="f",
        limits=DocumentLimits(),
    )
    fields = list(xml(tmp_path / "out.pptx", "ppt/slides/slide3.xml").iter(f"{A}fld"))
    assert [f.get("type") for f in fields] == ["slidenum"]
    codes = {d.code: d.count for d in output.diagnostics}
    assert codes["chart_text_not_translated"] == 1
    assert codes["smartart_text_not_translated"] == 1


def test_master_static_text_is_translated_and_prompts_are_not(tmp_path: Path) -> None:
    source = copy_fixture("pptx/deck.pptx", tmp_path)
    shape = (
        '<p:sp xmlns:p="{p}" xmlns:a="{a}"><p:nvSpPr><p:cNvPr id="99" name="Footer text"/>'
        "<p:cNvSpPr/><p:nvPr/></p:nvSpPr><p:spPr/><p:txBody><a:bodyPr/><a:p><a:r>"
        '<a:rPr lang="zh-CN"/><a:t>公司机密</a:t></a:r></a:p></p:txBody></p:sp>'
    ).format(p=NS["p"], a=NS["a"])

    def add_shape(data: bytes) -> bytes:
        return data.replace(b"</p:spTree>", shape.encode() + b"</p:spTree>", 1)

    edited = rewrite(
        source, tmp_path / "master.pptx", "ppt/slideMasters/slideMaster1.xml", add_shape
    )
    translator = FakeTranslator()
    output = translate(edited, translator)
    assert "公司机密" in translator.inputs
    master = texts(output, "ppt/slideMasters/slideMaster1.xml", "a:t")
    assert "EN:xxxx" in master
    assert "Click to edit Master title style" in master
