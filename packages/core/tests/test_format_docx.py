"""DOCX adapter: coverage, structure preservation and reported limits (ADR-011)."""

from pathlib import Path

from lxml import etree
from support.fakes import FakeTranslator, copy_fixture
from support.ooxml import CJK, NS, entries, rewrite, texts, xml

from doctranslator_core.config import DocumentLimits
from doctranslator_core.pipeline import translate_document
from doctranslator_core.types import DocumentTranslationOptions, DocumentTranslationResult, Language

OPTIONS = DocumentTranslationOptions(source=Language.ZH, target=Language.EN)
W = f"{{{NS['w']}}}"


def translate(
    source: Path, translator: FakeTranslator | None = None
) -> tuple[Path, DocumentTranslationResult]:
    output = source.with_name("out.docx")
    result = translate_document(
        translator or FakeTranslator(),
        source,
        output,
        options=OPTIONS,
        fingerprint="f",
        limits=DocumentLimits(),
    )
    return output, result


def test_all_required_surfaces_are_translated(tmp_path: Path) -> None:
    source = copy_fixture("docx/report.docx", tmp_path)
    output, _ = translate(source)
    for part in ("word/document.xml", "word/header1.xml", "word/footer1.xml", "word/footnotes.xml"):
        remaining = [t for t in texts(output, part, "w:t") if CJK.search(t)]
        assert remaining == [], (part, remaining)


def test_untranslated_by_design_content_is_kept_and_reported(tmp_path: Path) -> None:
    source = copy_fixture("docx/report.docx", tmp_path)
    output, result = translate(source)
    assert texts(output, "word/document.xml", "w:delText") == ["尚未"]
    assert texts(output, "word/comments.xml", "w:t") == texts(source, "word/comments.xml", "w:t")
    codes = {d.code for d in result.diagnostics}
    assert {
        "comments_not_translated",
        "tracked_changes_present",
        "field_results_not_translated",
    } <= codes
    date = [e for e in xml(output, "word/document.xml").iter(f"{W}fldSimple")]
    assert [e.findtext(f"{W}r/{W}t") for e in date] == ["2026-09-30"]


def test_text_box_copies_share_one_translation(tmp_path: Path) -> None:
    source = copy_fixture("docx/report.docx", tmp_path)
    translator = FakeTranslator()
    output, _ = translate(source, translator)
    assert translator.inputs.count("重要提示：请按时提交") == 1
    boxes = [
        "".join(t.text or "" for t in box.iter(f"{W}t"))
        for box in xml(output, "word/document.xml").iter(f"{W}txbxContent")
    ]
    assert len(boxes) == 2 and boxes[0] == boxes[1] and not CJK.search(boxes[0])


def test_structure_hyperlinks_fields_and_formatting_are_preserved(tmp_path: Path) -> None:
    source = copy_fixture("docx/report.docx", tmp_path)
    translator = FakeTranslator()
    output, _ = translate(source, translator)
    assert "更多信息请访问<g1><g2>项目主页</g2></g1>。" in translator.inputs
    assert "报告日期：<x1/>，参见 <g1><g2>项目计划</g2></g1>。" in translator.inputs
    doc = xml(output, "word/document.xml")
    before = xml(source, "word/document.xml")
    for tag in (
        "hyperlink",
        "fldSimple",
        "fldChar",
        "instrText",
        "tbl",
        "footnoteReference",
        "commentRangeStart",
        "commentRangeEnd",
        "commentReference",
        "ins",
        "del",
        "drawing",
        "pict",
        "sectPr",
    ):
        assert len(list(doc.iter(W + tag))) == len(list(before.iter(W + tag))), tag
    link = next(doc.iter(f"{W}hyperlink"))
    assert link.get(f"{{{NS['r']}}}id") == next(before.iter(f"{W}hyperlink")).get(
        f"{{{NS['r']}}}id"
    )
    bold = [r for r in doc.iter(f"{W}r") if r.find(f"{W}rPr/{W}b") is not None]
    assert [r.findtext(f"{W}t") for r in bold] == ["xxxx"]
    changed = {n for n, d in entries(source).items() if entries(output)[n] != d}
    assert changed == {
        "word/document.xml",
        "word/header1.xml",
        "word/footer1.xml",
        "word/footnotes.xml",
    }


def test_bookmarks_at_paragraph_edges_do_not_reach_the_engine(tmp_path: Path) -> None:
    source = copy_fixture("docx/report.docx", tmp_path)
    heading = (
        b"<w:t>\xe9\xa1\xb9\xe7\x9b\xae\xe8\xbf\x9b\xe5\xba\xa6\xe6\x8a\xa5\xe5\x91\x8a</w:t></w:r>"
    )

    def add_bookmark(data: bytes) -> bytes:
        start = data.index(heading)
        run_start = data.rindex(b"<w:r>", 0, start)
        marked = (
            data[:run_start]
            + b'<w:bookmarkStart w:id="7" w:name="_Toc1"/>'
            + data[run_start : start + len(heading)]
            + b'<w:bookmarkEnd w:id="7"/>'
            + data[start + len(heading) :]
        )
        return marked

    edited = rewrite(source, tmp_path / "marked.docx", "word/document.xml", add_bookmark)
    translator = FakeTranslator()
    output, _ = translate(edited, translator)
    assert "项目进度报告" in translator.inputs
    doc = xml(output, "word/document.xml")
    para = next(p for p in doc.iter(f"{W}p") if p.find(f"{W}bookmarkStart") is not None)
    tags = [etree.QName(c).localname for c in para]
    assert tags[tags.index("bookmarkStart") + 1] == "r"
    assert tags[-1] == "bookmarkEnd" or tags[tags.index("bookmarkEnd") - 1] == "r"


def test_field_spanning_paragraphs_is_never_translated(tmp_path: Path) -> None:
    source = copy_fixture("docx/report.docx", tmp_path)
    toc = (
        (
            '<w:p xmlns:w="{w}"><w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText>'
            ' TOC \\o "1-3" </w:instrText></w:r><w:r><w:fldChar w:fldCharType="separate"/></w:r>'
            "<w:r><w:t>目录第一项</w:t></w:r></w:p>"
            '<w:p xmlns:w="{w}"><w:r><w:t>目录第二项</w:t></w:r><w:r>'
            '<w:fldChar w:fldCharType="end"/></w:r></w:p>'
        )
        .format(w=NS["w"])
        .encode()
    )

    def add_toc(data: bytes) -> bytes:
        body = data.index(b"<w:body>") + len(b"<w:body>")
        return data[:body] + toc + data[body:]

    edited = rewrite(source, tmp_path / "toc.docx", "word/document.xml", add_toc)
    translator = FakeTranslator()
    output, _ = translate(edited, translator)
    assert not any("目录" in text for text in translator.inputs)
    assert "目录第一项" in texts(output, "word/document.xml", "w:t")
    assert "目录第二项" in texts(output, "word/document.xml", "w:t")
