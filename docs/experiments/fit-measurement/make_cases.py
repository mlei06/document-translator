"""Generate the PowerPoint measurement-comparison deck for the P3.0 fit gate.

Run from the repository root:  uv run python docs/experiments/fit-measurement/make_cases.py

Clones the blank slide of tests/fixtures/pptx/deck.pptx into one slide per case group and adds
text boxes with explicit fonts, sizes and widths (wrap on, no autofit). Writes
data/experiments/fit-measurement/cases.pptx and cases.json (case id -> parameters).
"""

import copy
import json
import re
import zipfile
from itertools import product
from pathlib import Path

from lxml import etree

SOURCE = Path("tests/fixtures/pptx/deck.pptx")
OUT = Path("data/experiments/fit-measurement")
P = "http://schemas.openxmlformats.org/presentationml/2006/main"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
EMU = 12700

TEXTS = {
    "zh": "销售额在第三季度增长了百分之十二，主要原因是华东地区的新客户数量显著增加，同时利润率保持稳定。",
    "en": "Revenue grew by twelve percent in the third quarter, mainly because the number of new "
    "customers in East China increased significantly while margins remained stable.",
    "ja": "第3四半期の売上高は12パーセント増加しました。主な理由は華東地域の新規顧客数が大幅に増えたことで、"
    "利益率は安定していました。",
    "es": "Los ingresos crecieron un doce por ciento en el tercer trimestre, principalmente porque el "
    "número de nuevos clientes en el este de China aumentó de forma significativa.",
}
LATIN = ["Aptos", "Calibri", "Arial", "Times New Roman", "Segoe UI"]
EAST = {"zh": ["等线", "Microsoft YaHei", "SimSun"], "ja": ["游ゴシック", "MS Gothic", "Yu Gothic"]}
SIZES = [10, 14, 20, 28]
WIDTHS = [150, 280, 420]


def cases() -> list[dict[str, object]]:
    found: list[dict[str, object]] = []
    for lang, text in TEXTS.items():
        fonts = EAST.get(lang, LATIN)
        for font, size, width in product(fonts, SIZES, WIDTHS):
            found.append({"lang": lang, "text": text, "font": font, "size": size,
                          "width": width, "spacing": 1.0, "bullet": False, "paras": 1})
    for size, spacing in product([14, 20], [1.5, 0.9]):
        found.append({"lang": "en", "text": TEXTS["en"], "font": "Calibri", "size": size,
                      "width": 280, "spacing": spacing, "bullet": False, "paras": 1})
    for lang in ("zh", "en"):
        found.append({"lang": lang, "text": TEXTS[lang], "font": "Arial" if lang == "en" else "等线",
                      "size": 16, "width": 300, "spacing": 1.0, "bullet": True, "paras": 3})
    for index, case in enumerate(found):
        case["id"] = f"c{index:03d}"
    return found


def shape(case: dict[str, object], shape_id: int, x: int, y: int) -> etree._Element:  # pyright: ignore[reportPrivateUsage]
    size = int(case["size"]) * 100  # type: ignore[call-overload]
    font = str(case["font"])
    east = case["lang"] in ("zh", "ja")
    runs_font = f'<a:ea typeface="{font}"/>' if east else f'<a:latin typeface="{font}"/>'
    lang = {"zh": "zh-CN", "ja": "ja-JP", "en": "en-US", "es": "es-ES"}[str(case["lang"])]
    spacing = float(case["spacing"])  # type: ignore[arg-type]
    ln = f'<a:lnSpc><a:spcPct val="{int(spacing * 100000)}"/></a:lnSpc>' if spacing != 1.0 else ""
    bullet = '<a:buFont typeface="Arial"/><a:buChar char="&#8226;"/>' if case["bullet"] else "<a:buNone/>"
    indent = ' marL="285750" indent="-285750"' if case["bullet"] else ""
    para = (
        f'<a:p><a:pPr{indent}>{ln}<a:spcBef><a:spcPts val="600"/></a:spcBef>{bullet}</a:pPr>'
        f'<a:r><a:rPr lang="{lang}" sz="{size}" dirty="0">{runs_font}</a:rPr>'
        f"<a:t>{case['text']}</a:t></a:r></a:p>"
    ) * int(case["paras"])  # type: ignore[call-overload]
    width = int(case["width"]) * EMU  # type: ignore[call-overload]
    xml = (
        f'<p:sp xmlns:p="{P}" xmlns:a="{A}"><p:nvSpPr><p:cNvPr id="{shape_id}" name="{case["id"]}"/>'
        f'<p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr><p:spPr><a:xfrm><a:off x="{x}" y="{y}"/>'
        f'<a:ext cx="{width}" cy="{40 * EMU}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/>'
        f'</a:prstGeom><a:noFill/></p:spPr><p:txBody><a:bodyPr wrap="square" rtlCol="0">'
        f"<a:noAutofit/></a:bodyPr><a:lstStyle/>{para}</p:txBody></p:sp>"
    )
    return etree.fromstring(xml)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    all_cases = cases()
    with zipfile.ZipFile(SOURCE) as source:
        parts = {name: source.read(name) for name in source.namelist()}
        infos = source.infolist()
    blank = etree.fromstring(parts["ppt/slides/slide4.xml"])
    tree = blank.find(f"{{{P}}}cSld/{{{P}}}spTree")
    assert tree is not None
    for child in list(tree)[2:]:
        tree.remove(child)
    slide_rels = re.sub(rb'<Relationship [^>]*chart[^>]*/>', b"", parts["ppt/slides/_rels/slide4.xml.rels"])
    per_slide = 3
    new_parts: dict[str, bytes] = {}
    presentation = etree.fromstring(parts["ppt/presentation.xml"])
    id_list = presentation.find(f"{{{P}}}sldIdLst")
    assert id_list is not None
    pres_rels = parts["ppt/_rels/presentation.xml.rels"]
    content_types = parts["[Content_Types].xml"]
    next_id = max(int(e.get("id", "0")) for e in id_list) + 1
    for number, start in enumerate(range(0, len(all_cases), per_slide), start=1):
        slide = copy.deepcopy(blank)
        spTree = slide.find(f"{{{P}}}cSld/{{{P}}}spTree")
        assert spTree is not None
        for offset, case in enumerate(all_cases[start : start + per_slide]):
            case["slide"] = 100 + number
            spTree.append(shape(case, 10 + offset, 20 * EMU + offset * 310 * EMU, 20 * EMU))
        name = f"ppt/slides/slide{100 + number}.xml"
        new_parts[name] = etree.tostring(slide, xml_declaration=True, encoding="UTF-8", standalone=True)
        new_parts[f"ppt/slides/_rels/slide{100 + number}.xml.rels"] = slide_rels
        rid = f"rIdCase{number}"
        pres_rels = pres_rels.replace(
            b"</Relationships>",
            f'<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
            f'relationships/slide" Target="slides/slide{100 + number}.xml"/></Relationships>'.encode(),
        )
        content_types = content_types.replace(
            b"</Types>",
            f'<Override PartName="/{name}" ContentType="application/vnd.openxmlformats-'
            f'officedocument.presentationml.slide+xml"/></Types>'.encode(),
        )
        entry = etree.SubElement(id_list, f"{{{P}}}sldId")
        entry.set("id", str(next_id))
        entry.set(f"{{{R}}}id", rid)
        next_id += 1
    for child in list(id_list):
        if child.get(f"{{{R}}}id") and not str(child.get(f"{{{R}}}id")).startswith("rIdCase"):
            id_list.remove(child)
    replaced = {
        "ppt/presentation.xml": etree.tostring(presentation, xml_declaration=True, encoding="UTF-8",
                                               standalone=True),
        "ppt/_rels/presentation.xml.rels": pres_rels,
        "[Content_Types].xml": content_types,
    }
    target = OUT / "cases.pptx"
    target.unlink(missing_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as out:
        for info in infos:
            out.writestr(info, replaced.get(info.filename, parts[info.filename]))
        for name, data in new_parts.items():
            out.writestr(name, data)
    (OUT / "cases.json").write_text(json.dumps(all_cases, ensure_ascii=False, indent=1),
                                    encoding="utf-8")
    print(f"{len(all_cases)} cases on {len(new_parts) // 2} slides -> {target}")


if __name__ == "__main__":
    main()
