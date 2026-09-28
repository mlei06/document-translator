# /// script
# requires-python = ">=3.14"
# dependencies = ["lxml==6.1.3"]
# ///
"""XLSX recalculation experiment for the ADR-009 calculation gate.

Run from the repository root after make_fixture.ps1:

    uv run docs/experiments/xlsx-recalc/spike.py

labels.xlsx (authored in native Excel) has formulas that depend on translatable labels: COUNTIF
and SUMIF on a label literal, a concatenation, an IF comparison, a VLOOKUP by label, a plain SUM
and a cross-sheet reference. This script translates the literal string cells with targeted XML
edits (苹果 -> Apple, 香蕉 -> Banana and the other labels) and writes two variants:

- keep-caches.xlsx: formula caches untouched, workbook calcPr untouched;
- full-calc.xlsx: same edits plus <calcPr fullCalcOnLoad="1"/> so the opening application
  recalculates every formula.

It also reports which formulas contain a string literal equal to a translated source string, the
diagnostic the production adapter emits. Native values are read with
scripts/native_office_check.ps1 (Excel, UpdateLinks=0, no repair).
"""

import json
import re
import sys
import zipfile
from pathlib import Path

from lxml import etree

ROOT = Path("data/experiments/xlsx-recalc")
S = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
PARSER = etree.XMLParser(resolve_entities=False, no_network=True)
TRANSLATIONS = {
    "苹果": "Apple",
    "香蕉": "Banana",
    "苹果数量": "Apple count",
}
LITERAL = re.compile(r'"((?:[^"]|"")*)"')


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # pyright: ignore[reportAttributeAccessIssue]
    source = ROOT / "labels.xlsx"
    with zipfile.ZipFile(source) as z:
        parts = {n: z.read(n) for n in z.namelist()}
        infos = z.infolist()
    shared = etree.fromstring(parts["xl/sharedStrings.xml"], PARSER)
    translated_sources: set[str] = set()
    for t in shared.iter(f"{{{S}}}t"):
        if t.text in TRANSLATIONS:
            translated_sources.add(t.text)
            t.text = TRANSLATIONS[t.text]
    new_shared = etree.tostring(shared, xml_declaration=True, encoding="UTF-8", standalone=True)

    dependent: list[dict[str, str]] = []
    for name, payload in parts.items():
        if name.startswith("xl/worksheets/sheet") and name.endswith(".xml"):
            sheet = etree.fromstring(payload, PARSER)
            for cell in sheet.iter(f"{{{S}}}c"):
                formula = cell.find(f"{{{S}}}f")
                if formula is None or not formula.text:
                    continue
                literals = {m.group(1).replace('""', '"') for m in LITERAL.finditer(formula.text)}
                hits = sorted(literals & translated_sources)
                if hits:
                    dependent.append({"part": name, "cell": cell.get("r", ""), "literals": ", ".join(hits)})

    workbook = etree.fromstring(parts["xl/workbook.xml"], PARSER)
    calc = workbook.find(f"{{{S}}}calcPr")
    if calc is None:
        calc = etree.SubElement(workbook, f"{{{S}}}calcPr")
    calc.set("fullCalcOnLoad", "1")
    full_calc_workbook = etree.tostring(workbook, xml_declaration=True, encoding="UTF-8", standalone=True)

    variants = {
        "keep-caches.xlsx": {"xl/sharedStrings.xml": new_shared},
        "full-calc.xlsx": {"xl/sharedStrings.xml": new_shared, "xl/workbook.xml": full_calc_workbook},
    }
    for filename, replacements in variants.items():
        with zipfile.ZipFile(ROOT / filename, "w", zipfile.ZIP_DEFLATED) as out:
            for info in infos:
                out.writestr(info, replacements.get(info.filename, parts[info.filename]))
    result = {"formulas_with_translated_literals": dependent, "variants": list(variants)}
    (ROOT / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
