# /// script
# requires-python = ">=3.14"
# dependencies = ["python-docx==1.2.0", "lxml==6.1.3"]
# ///
"""Builds the DOCX fixture for the OOXML round-trip experiment.

Run from the repository root:  uv run docs/experiments/ooxml-roundtrip/build_docx.py

Word automation on the experiment host hangs when saving documents with fields, comments or
tracked changes, so this fixture is generated: python-docx builds the body, tables, header and
footer, then raw WordprocessingML adds what python-docx cannot author (footnote, hyperlink, simple
and complex fields, a DrawingML text box with its VML fallback, a comment and tracked changes).
Writes data/experiments/ooxml-roundtrip/fixtures/report.docx. Synthetic text only.
"""

import zipfile
from io import BytesIO
from pathlib import Path

import docx
from docx.enum.table import WD_TABLE_ALIGNMENT
from lxml import etree

OUT = Path("data/experiments/ooxml-roundtrip/fixtures/report.docx")
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = (
    'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
    'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
    'xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape" '
    'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
    'xmlns:v="urn:schemas-microsoft-com:vml" '
    'xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml"'
)

TEXTBOX = f"""<w:p {NS}><w:r><mc:AlternateContent><mc:Choice Requires="wps"><w:drawing>
<wp:anchor distT="0" distB="0" distL="114300" distR="114300" simplePos="0" relativeHeight="251659264"
 behindDoc="0" locked="0" layoutInCell="1" allowOverlap="1"><wp:simplePos x="0" y="0"/>
<wp:positionH relativeFrom="column"><wp:posOffset>3200400</wp:posOffset></wp:positionH>
<wp:positionV relativeFrom="paragraph"><wp:posOffset>0</wp:posOffset></wp:positionV>
<wp:extent cx="2286000" cy="762000"/><wp:effectExtent l="0" t="0" r="0" b="0"/><wp:wrapSquare wrapText="bothSides"/>
<wp:docPr id="10" name="Text Box 10"/><wp:cNvGraphicFramePr/>
<a:graphic><a:graphicData uri="http://schemas.microsoft.com/office/word/2010/wordprocessingShape">
<wps:wsp><wps:cNvSpPr txBox="1"/><wps:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="2286000" cy="762000"/></a:xfrm>
<a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:ln w="6350"><a:solidFill><a:srgbClr val="000000"/></a:solidFill></a:ln></wps:spPr>
<wps:txbx><w:txbxContent><w:p><w:r><w:t>重要提示：请按时提交</w:t></w:r></w:p></w:txbxContent></wps:txbx>
<wps:bodyPr rot="0" vert="horz" wrap="square" lIns="91440" tIns="45720" rIns="91440" bIns="45720" anchor="t"><a:noAutofit/></wps:bodyPr>
</wps:wsp></a:graphicData></a:graphic></wp:anchor></w:drawing></mc:Choice>
<mc:Fallback><w:pict><v:shape id="Text Box 10" o:spid="_x0000_s1026" type="#_x0000_t202"
 xmlns:o="urn:schemas-microsoft-com:office:office" style="position:absolute;margin-left:252pt;width:180pt;height:60pt;z-index:251659264">
<v:textbox><w:txbxContent><w:p><w:r><w:t>重要提示：请按时提交</w:t></w:r></w:p></w:txbxContent></v:textbox></v:shape></w:pict>
</mc:Fallback></mc:AlternateContent></w:r></w:p>"""

FIELDS = f"""<w:p {NS}><w:r><w:t xml:space="preserve">报告日期：</w:t></w:r>
<w:fldSimple w:instr=" DATE \\@ &quot;yyyy-MM-dd&quot; "><w:r><w:t>2026-09-30</w:t></w:r></w:fldSimple>
<w:r><w:t xml:space="preserve">，参见 </w:t></w:r>
<w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText xml:space="preserve"> HYPERLINK "https://intranet.example.com/plan" </w:instrText></w:r>
<w:r><w:fldChar w:fldCharType="separate"/></w:r><w:r><w:rPr><w:u w:val="single"/></w:rPr><w:t>项目计划</w:t></w:r>
<w:r><w:fldChar w:fldCharType="end"/></w:r><w:r><w:t>。</w:t></w:r></w:p>"""

TRACKED = f"""<w:p {NS}><w:r><w:t xml:space="preserve">本季度目标</w:t></w:r>
<w:ins w:id="101" w:author="Reviewer" w:date="2026-09-27T00:00:00Z"><w:r><w:t>已经</w:t></w:r></w:ins>
<w:del w:id="102" w:author="Reviewer" w:date="2026-09-27T00:00:00Z"><w:r><w:delText>尚未</w:delText></w:r></w:del>
<w:r><w:t>完成。</w:t></w:r></w:p>"""


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    document = docx.Document()
    document.add_heading("项目进度报告", level=1)
    para = document.add_paragraph("本项目已完成")
    para.add_run("第一阶段").bold = True
    para.add_run("的全部工作。")
    link_para = document.add_paragraph("更多信息请访问")
    table = document.add_table(rows=2, cols=2)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.LEFT
    table.cell(0, 0).text = "任务"
    table.cell(0, 1).text = "状态"
    table.cell(1, 0).text = "需求分析"
    inner = table.cell(1, 1).add_table(rows=1, cols=2)
    inner.cell(0, 0).text = "已完成"
    inner.cell(0, 1).text = "九月"
    section = document.sections[0]
    section.header.paragraphs[0].text = "内部资料 请勿外传"
    section.footer.paragraphs[0].text = "版权所有"

    # Hyperlink run (relationship added through python-docx's part API)
    rel = document.part.relate_to(
        "https://intranet.example.com/project",
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
        is_external=True,
    )
    link_para._p.append(  # noqa: SLF001 - fixture builder edits raw XML deliberately
        etree.fromstring(
            f'<w:hyperlink {NS} r:id="{rel}"><w:r><w:rPr><w:u w:val="single"/></w:rPr>'
            "<w:t>项目主页</w:t></w:r></w:hyperlink>"
        )
    )
    link_para.add_run("。")
    body = document.element.body
    for xml in (FIELDS, TRACKED, TEXTBOX):
        body.insert(len(body) - 1, etree.fromstring(xml))
    # Comment anchored on the bold paragraph (python-docx 1.2 supports comments)
    document.add_comment(para.runs[1], text="请确认日期。", author="Reviewer")
    buffer = BytesIO()
    document.save(buffer)
    OUT.write_bytes(add_footnote(buffer.getvalue()))
    print(OUT, OUT.stat().st_size)


def add_footnote(package: bytes) -> bytes:
    """Add footnotes.xml (separators plus one note) and reference it from the first bold run."""
    footnotes = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:footnotes {NS}>'
        '<w:footnote w:type="separator" w:id="-1"><w:p><w:r><w:separator/></w:r></w:p></w:footnote>'
        '<w:footnote w:type="continuationSeparator" w:id="0"><w:p><w:r><w:continuationSeparator/></w:r></w:p></w:footnote>'
        '<w:footnote w:id="1"><w:p><w:pPr><w:pStyle w:val="FootnoteText"/></w:pPr>'
        '<w:r><w:rPr><w:vertAlign w:val="superscript"/></w:rPr><w:footnoteRef/></w:r>'
        '<w:r><w:t xml:space="preserve"> 数据来源：内部系统。</w:t></w:r></w:p></w:footnote></w:footnotes>'
    ).encode()
    source = zipfile.ZipFile(BytesIO(package))
    out = BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target:
        for item in source.infolist():
            data = source.read(item.filename)
            if item.filename == "[Content_Types].xml":
                data = data.replace(
                    b"</Types>",
                    b'<Override PartName="/word/footnotes.xml" ContentType="application/'
                    b'vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml"/></Types>',
                )
            elif item.filename == "word/_rels/document.xml.rels":
                data = data.replace(
                    b"</Relationships>",
                    b'<Relationship Id="rIdFootnotes" Type="http://schemas.openxmlformats.org/'
                    b'officeDocument/2006/relationships/footnotes" Target="footnotes.xml"/>'
                    b"</Relationships>",
                )
            elif item.filename == "word/document.xml":
                root = etree.fromstring(data)
                bold = root.find(f".//{{{W}}}b/../..")
                assert bold is not None
                ref = etree.fromstring(
                    f'<w:r {NS}><w:rPr><w:vertAlign w:val="superscript"/></w:rPr>'
                    '<w:footnoteReference w:id="1"/></w:r>'
                )
                bold.addnext(ref)
                data = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
            target.writestr(item, data)
        target.writestr("word/footnotes.xml", footnotes)
    return out.getvalue()


if __name__ == "__main__":
    main()
