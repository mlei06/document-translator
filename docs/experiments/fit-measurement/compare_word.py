"""Compare our measurement with Word's layout of fixed-width table cells (P3.0 fit gate).

Run from the repository root after make_word_cases.py and word_metrics.ps1:

    uv run python docs/experiments/fit-measurement/compare_word.py

Describes every cell with the production DOCX layout capability, measures it, and compares the
line count with Word's (``Range.ComputeStatistics(wdStatisticLines)``) and our single line height
with Word's measured line pitch. Writes comparison-word.json.
"""

import json
import os
import statistics
import sys
from collections import defaultdict
from pathlib import Path

from doctranslator_core.config import DocumentLimits
from doctranslator_core.fit.fonts import FontLibrary, build_font_manifest
from doctranslator_core.fit.measure import Unmeasurable, measure
from doctranslator_core.formats.docx import DocxAdapter

ROOT = Path("data/experiments/fit-measurement")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # pyright: ignore[reportAttributeAccessIssue]
    local = Path(os.environ["LOCALAPPDATA"])
    library = FontLibrary(build_font_manifest([
        Path(os.environ.get("WINDIR", "C:\\Windows")) / "Fonts",
        local / "Microsoft" / "Windows" / "Fonts",
        local / "Microsoft" / "FontCache" / "4" / "CloudFonts",
    ]))
    cases = {c["id"]: c for c in json.loads((ROOT / "word-cases.json").read_text(encoding="utf-8"))}
    native = json.loads((ROOT / "word.json").read_text(encoding="utf-8-sig"))
    word = {r["id"]: r for r in native["cases"] if "lines" in r}
    adapter = DocxAdapter(ROOT / "word-cases.docx", DocumentLimits())
    rows: list[dict[str, object]] = []
    try:
        for container in adapter.layout_containers():
            case_id = container.id.split("#", 1)[1].replace("table", "t", 1)
            if case_id not in word:
                continue
            case = cases[case_id]
            try:
                ours = measure(container, library)
            except Unmeasurable as exc:
                rows.append({"id": case_id, "font": case["font"], "error": exc.reason})
                continue
            pitch = word[case_id]["pitch"]
            rows.append({
                "id": case_id, "lang": case["lang"], "font": case["font"], "size": case["size"],
                "word_lines": word[case_id]["lines"], "our_lines": ours.lines,
                "word_pitch": round(pitch, 3) if pitch else None,
                "our_pitch": round(ours.height_pt / ours.lines, 3),
            })
    finally:
        adapter.close()
    measured = [r for r in rows if "error" not in r]
    pitch_errors = [abs(float(r["our_pitch"]) - float(r["word_pitch"])) / float(r["word_pitch"])  # type: ignore[arg-type]
                    for r in measured if r["word_pitch"]]
    by_font: dict[str, list[dict[str, object]]] = defaultdict(list)
    for r in measured:
        by_font[f"{r['lang']}/{r['font']}"].append(r)
    summary = {
        "word": {"version": native["version"], "build": native["build"]},
        "cases": len(rows),
        "unmeasurable": [r for r in rows if "error" in r],
        "lines_exact": sum(1 for r in measured if r["word_lines"] == r["our_lines"]),
        "lines_off_by_one": sum(1 for r in measured
                                if abs(int(r["word_lines"]) - int(r["our_lines"])) == 1),  # type: ignore[call-overload]
        "pitch_rel_error_median": round(statistics.median(pitch_errors), 4) if pitch_errors else None,
        "pitch_rel_error_max": round(max(pitch_errors), 4) if pitch_errors else None,
        "by_font": {k: {"n": len(v), "lines_exact": sum(1 for r in v if r["word_lines"] == r["our_lines"]),
                        "pitch_word": v[0]["word_pitch"], "pitch_ours": v[0]["our_pitch"]}
                    for k, v in sorted(by_font.items())},
    }
    (ROOT / "comparison-word.json").write_text(
        json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
