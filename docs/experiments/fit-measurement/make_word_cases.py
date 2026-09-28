"""Generate the Word measurement-comparison document for the P3.0 fit gate.

Run from the repository root:  uv run python docs/experiments/fit-measurement/make_word_cases.py

Replaces the body of tests/fixtures/docx/report.docx with a fixed-layout table (columns of 75, 150
and 225 pt; one row per font/size; the same text in each cell) and DrawingML text boxes, with
explicit fonts and sizes and single or 1.5 line spacing. Writes
data/experiments/fit-measurement/word-cases.docx and word-cases.json.
"""

import json
import re
import zipfile
from itertools import product
from pathlib import Path

SOURCE = Path("tests/fixtures/docx/report.docx")
OUT = Path("data/experiments/fit-measurement")
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = (
    f'xmlns:w="{W}" xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
    'xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape" '
    'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"'
)
TEXTS = {
    "zh": "销售额在第三季度增长了百分之十二，主要原因是华东地区的新客户数量显著增加，同时利润率保持稳定。",
    "en": "Revenue grew by twelve percent in the third quarter, mainly because the number of new "
    "customers in East China increased significantly while margins remained stable.",
    "ja": "第3四半期の売上高は12パーセント増加しました。主な理由は華東地域の新規顧客数が大幅に増えたことで、"
    "利益率は安定していました。",
    "es": "Los ingresos crecieron un doce por ciento en el tercer trimestre, principalmente porque el "
    "número de nuevos clientes en el este de China aumentó de forma significativa.",
}
FONTS = [("en", "Calibri"), ("en", "Arial"), ("en", "Times New Roman"), ("es", "Calibri"),
         ("zh", "Microsoft YaHei"), ("zh", "SimSun"), ("zh", "DengXian"), ("ja", "Yu Gothic"),
         ("ja", "MS Gothic")]
SIZES = [9, 11, 14]
COLUMNS = [1500, 3000, 4500]  # twips


def run(lang: str, font: str, size: int, text: str) -> str:
    if lang in ("zh", "ja"):
        fonts = f'<w:rFonts w:eastAsia="{font}" w:hint="eastAsia"/>'
        tag = f'<w:lang w:eastAsia="{"zh-CN" if lang == "zh" else "ja-JP"}"/>'
    else:
        fonts = f'<w:rFonts w:ascii="{font}" w:hAnsi="{font}"/>'
        tag = ""
    return (f'<w:r><w:rPr>{fonts}<w:sz w:val="{size * 2}"/><w:szCs w:val="{size * 2}"/>{tag}'
            f"</w:rPr><w:t>{text}</w:t></w:r>")


def paragraph(lang: str, font: str, size: int, line: int = 240) -> str:
    return (f'<w:p><w:pPr><w:spacing w:before="0" w:after="0" w:line="{line}" w:lineRule="auto"/>'
            f"</w:pPr>{run(lang, font, size, TEXTS[lang])}</w:p>")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    cases: list[dict[str, object]] = []
    rows: list[str] = []
    for r, ((lang, font), size) in enumerate(product(FONTS, SIZES), start=1):
        cells = ""
        for c, width in enumerate(COLUMNS, start=1):
            cases.append({"id": f"t1/r{r}c{c}", "kind": "cell", "lang": lang, "font": font,
                          "size": size, "width_twips": width, "line": 240})
            cells += (f'<w:tc><w:tcPr><w:tcW w:w="{width}" w:type="dxa"/></w:tcPr>'
                      f"{paragraph(lang, font, size)}</w:tc>")
        rows.append(f"<w:tr>{cells}</w:tr>")
    grid = "".join(f'<w:gridCol w:w="{w}"/>' for w in COLUMNS)
    table = (f'<w:tbl><w:tblPr><w:tblW w:w="9000" w:type="dxa"/><w:tblLayout w:type="fixed"/>'
             f'<w:tblBorders><w:insideV w:val="single" w:sz="4"/></w:tblBorders></w:tblPr>'
             f"<w:tblGrid>{grid}</w:tblGrid>{''.join(rows)}</w:tbl>")
    boxes = ""
    for number, ((lang, font), line) in enumerate(product(FONTS[::2], [240, 360]), start=1):
        width = 150 + 60 * (number % 3)
        cases.append({"id": f"textbox{number}", "kind": "textbox", "lang": lang, "font": font,
                      "size": 12, "width_pt": width, "line": line})
        cx, cy = width * 12700, 300 * 12700
        boxes += (
            f'<w:p><w:r><w:drawing><wp:anchor distT="0" distB="0" distL="0" distR="0" simplePos="0" '
            f'relativeHeight="{number}" behindDoc="0" locked="0" layoutInCell="1" allowOverlap="1">'
            f'<wp:simplePos x="0" y="0"/><wp:positionH relativeFrom="page"><wp:posOffset>'
            f'{(40 + (number - 1) % 3 * 180) * 12700}</wp:posOffset></wp:positionH>'
            f'<wp:positionV relativeFrom="page"><wp:posOffset>{(60 + (number - 1) // 3 * 320) * 12700}'
            f'</wp:posOffset></wp:positionV><wp:extent cx="{cx}" cy="{cy}"/><wp:wrapNone/>'
            f'<wp:docPr id="{100 + number}" name="textbox{number}"/><a:graphic><a:graphicData '
            f'uri="http://schemas.microsoft.com/office/word/2010/wordprocessingShape"><wps:wsp>'
            f'<wps:cNvSpPr txBox="1"/><wps:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" '
            f'cy="{cy}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></wps:spPr>'
            f"<wps:txbx><w:txbxContent>{paragraph(lang, font, 12, line)}</w:txbxContent></wps:txbx>"
            f'<wps:bodyPr lIns="91440" tIns="45720" rIns="91440" bIns="45720" wrap="square">'
            f"<a:noAutofit/></wps:bodyPr></wps:wsp></a:graphicData></a:graphic></wp:anchor>"
            f"</w:drawing></w:r></w:p>"
        )
    with zipfile.ZipFile(SOURCE) as source:
        parts = {info.filename: source.read(info.filename) for info in source.infolist()}
        infos = source.infolist()
    document = parts["word/document.xml"].decode("utf-8")
    section = re.findall(r"<w:sectPr.*?</w:sectPr>", document, re.S)[-1]
    body = f"<w:body>{table}<w:p/><w:p><w:r><w:br w:type=\"page\"/></w:r></w:p>{boxes}{section}</w:body>"
    document = re.sub(r"<w:body>.*</w:body>", lambda _: body, document, flags=re.S)
    root_tag = re.search(r"<w:document[^>]*>", document)
    assert root_tag is not None
    missing = " ".join(
        declaration for declaration in NS.split(" ")
        if declaration.split("=")[0] not in root_tag.group(0)
    )
    document = document.replace("<w:document ", f"<w:document {missing} ", 1)
    target = OUT / "word-cases.docx"
    target.unlink(missing_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as out:
        for info in infos:
            out.writestr(info, document.encode("utf-8") if info.filename == "word/document.xml"
                         else parts[info.filename])
    (OUT / "word-cases.json").write_text(json.dumps(cases, ensure_ascii=False, indent=1),
                                         encoding="utf-8")
    print(f"{len(cases)} cases -> {target}")


if __name__ == "__main__":
    main()
