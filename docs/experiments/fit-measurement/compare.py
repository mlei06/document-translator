"""Compare our measurement with PowerPoint's layout of the same text boxes (P3.0 fit gate).

Run from the repository root after make_cases.py and powerpoint_metrics.ps1:

    uv run python docs/experiments/fit-measurement/compare.py

Describes every case box with the production PPTX layout capability, measures it with the
production HarfBuzz measurement, and compares line counts and text height with PowerPoint's
(``TextRange.Lines`` count and ``TextRange2.BoundHeight``). Writes comparison.json and prints a
summary by script, font and size.
"""

import json
import os
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

from doctranslator_core.config import DocumentLimits
from doctranslator_core.fit.fonts import FontLibrary, build_font_manifest
from doctranslator_core.fit.measure import Unmeasurable, measure
from doctranslator_core.formats.pptx import PptxAdapter

ROOT = Path("data/experiments/fit-measurement")


def font_directories() -> list[Path]:
    local = Path(os.environ["LOCALAPPDATA"])
    return [
        Path(os.environ.get("WINDIR", "C:\\Windows")) / "Fonts",
        local / "Microsoft" / "Windows" / "Fonts",
        local / "Microsoft" / "FontCache" / "4" / "CloudFonts",
    ]


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # pyright: ignore[reportAttributeAccessIssue]
    started = time.perf_counter()
    manifest = build_font_manifest(font_directories())
    manifest_s = time.perf_counter() - started
    library = FontLibrary(manifest)
    cases = {c["id"]: c for c in json.loads((ROOT / "cases.json").read_text(encoding="utf-8"))}
    native = json.loads((ROOT / "powerpoint.json").read_text(encoding="utf-8-sig"))
    by_id = {row["id"]: row for row in native["cases"]}
    adapter = PptxAdapter(ROOT / "cases.pptx", DocumentLimits())
    rows: list[dict[str, object]] = []
    try:
        names = {str(c.key): c.location.split('"')[1] for c in adapter.containers
                 if '"' in c.location}
        for container in adapter.layout_containers():
            case_id = names.get(container.id, "")
            if case_id not in cases:
                continue
            ppt = by_id[case_id]
            try:
                ours = measure(container, library)
            except Unmeasurable as exc:
                rows.append({"id": case_id, "error": exc.reason})
                continue
            rows.append({
                "id": case_id,
                "lang": cases[case_id]["lang"],
                "font": cases[case_id]["font"],
                "size": cases[case_id]["size"],
                "width": cases[case_id]["width"],
                "ppt_lines": ppt["lines"],
                "our_lines": ours.lines,
                "ppt_height": round(ppt["bound_height"], 2),
                "our_height": round(ours.height_pt, 2),
                "height_error": round(ours.height_pt - ppt["bound_height"], 2),
                "height_error_rel": round((ours.height_pt - ppt["bound_height"]) / ppt["bound_height"], 4),
            })
    finally:
        adapter.close()
    measured = [r for r in rows if "error" not in r]
    exact_lines = sum(1 for r in measured if r["ppt_lines"] == r["our_lines"])
    off_by_one = sum(1 for r in measured if abs(int(r["ppt_lines"]) - int(r["our_lines"])) == 1)  # type: ignore[call-overload]
    rel = [abs(float(r["height_error_rel"])) for r in measured]  # type: ignore[arg-type]
    summary = {
        "office": {"version": native["version"], "build": native["build"]},
        "manifest": {"faces": len(manifest.faces), "seconds": round(manifest_s, 1)},
        "cases": len(rows),
        "unmeasurable": [r for r in rows if "error" in r],
        "lines_exact": exact_lines,
        "lines_off_by_one": off_by_one,
        "height_rel_error_median": round(statistics.median(rel), 4) if rel else None,
        "height_rel_error_p95": round(sorted(rel)[int(len(rel) * 0.95) - 1], 4) if rel else None,
        "height_rel_error_max": round(max(rel), 4) if rel else None,
    }
    groups: dict[str, list[dict[str, object]]] = defaultdict(list)
    for r in measured:
        groups[f"{r['lang']}/{r['font']}"].append(r)
    summary["by_font"] = {
        key: {
            "n": len(items),
            "lines_exact": sum(1 for r in items if r["ppt_lines"] == r["our_lines"]),
            "mean_height_error_rel": round(statistics.mean(float(r["height_error_rel"]) for r in items), 4),  # type: ignore[arg-type]
        }
        for key, items in sorted(groups.items())
    }
    (ROOT / "comparison.json").write_text(
        json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
