"""Summarize completed lifecycle reports; stage rows are overlapping windows, not additive."""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

DEFAULT_DIR = Path(__file__).resolve().parents[3] / "data/experiments/laptop-mt/lifecycle"


def conversion_side(event: dict[str, Any]) -> str:
    """Classify only unambiguous production filenames; retain the original path in events."""
    name = str(event.get("input_name", "")).replace("\\", "/").rsplit("/", 1)[-1]
    return {"input.pptx": "source", "output.pptx": "target"}.get(name, "unspecified")


def stage_row(events: list[dict[str, Any]], base: dict[str, Any]) -> dict[str, Any]:
    ordered = sorted(events, key=lambda e: float(e["start"]))
    end = float("-inf")
    overlap = False
    for event in ordered:
        overlap |= float(event["start"]) < end
        end = max(end, float(event["end"]))
    resources: list[dict[str, Any]] = [e.get("resources", {}) for e in events]
    cpu_pairs = [
        (r.get("cpu_interval_estimated_seconds"), r.get("cpu_observed_window_s", 0))
        for r in resources
    ]
    cpu_pairs = [(v, d) for v, d in cpu_pairs if v is not None and d > 0]
    gpu_pairs = [
        (r.get("gpu_timeweighted_pct_estimate"), r.get("gpu_valid_overlap_s", 0)) for r in resources
    ]
    gpu_pairs = [(v, d) for v, d in gpu_pairs if v is not None and d > 0]
    cpu_duration = sum(d for _, d in cpu_pairs)
    gpu_duration = sum(d for _, d in gpu_pairs)

    def peak_mib(key: str) -> float | None:
        values = [r[key] for r in resources if r.get(key) is not None]
        return max(values) / 2**20 if values else None

    return base | {
        "row_kind": "stage",
        "stage": events[0]["name"],
        "thread_name": events[0].get("thread_name"),
        "thread_id": events[0].get("thread_id"),
        "conversion_side": conversion_side(events[0])
        if events[0]["name"].startswith("libreoffice")
        else None,
        "event_count": len(events),
        "event_ids": [e["id"] for e in events],
        "inclusive_wall_s": sum(e["wall_s"] for e in events),
        "exclusive_same_thread_wall_s": sum(e.get("exclusive_wall_s", e["wall_s"]) for e in events),
        "cpu_cores_estimate": sum(v for v, _ in cpu_pairs) / cpu_duration
        if cpu_duration and not overlap
        else None,
        "cpu_valid_window_s": cpu_duration if not overlap else None,
        "gpu_mean_pct_estimate": sum(v * d for v, d in gpu_pairs) / gpu_duration
        if gpu_duration and not overlap
        else None,
        "gpu_valid_window_s": gpu_duration if not overlap else None,
        "peak_rss_mib": peak_mib("point_sample_rss_peak_bytes"),
        "peak_shared_gpu_mib": peak_mib("point_sample_shared_gpu_peak_bytes"),
        "short_or_unsampled_events": sum(
            bool(r.get("short_or_unsampled", True)) for r in resources
        ),
        "overlapping_same_group_events": overlap,
        "failed_events": sum("error_type" in e for e in events),
    }


def summarize(path: Path, report: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    base = {
        "case": path.parent.name,
        "model": report.get("model"),
        "fit_mode": report.get("fit_mode"),
        "status": report.get("status"),
    }
    events: list[dict[str, Any]] = report.get("events", [])
    startup = sum(float(e["wall_s"]) for e in events if e["name"] == "startup" and "end" in e)
    rows: list[dict[str, Any]] = []
    for run in report.get("runs", []):
        rep = run["rep"]
        row = base | {
            "row_kind": "milestones",
            "rep": rep,
            "temperature": "first_document" if rep == 1 else "warm",
            "startup_s": startup if rep == 1 else None,
        }
        for name in ("publication", "download", "pages_ready", "all_pages_download"):
            value = run.get(f"{name}_latency_s")
            row[f"{name}_latency_s"] = value
            row[f"startup_plus_{name}_s"] = (
                startup + value if rep == 1 and value is not None else None
            )
        rows.append(row)
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        if "end" in event:
            groups[
                (
                    event.get("rep", 0),
                    event["name"],
                    event.get("thread_id"),
                    conversion_side(event) if event["name"].startswith("libreoffice") else None,
                )
            ].append(event)
    for key, group in groups.items():
        rep = key[0]
        rows.append(
            stage_row(
                group,
                base
                | {
                    "rep": rep,
                    "temperature": "startup"
                    if rep == 0
                    else "first_document"
                    if rep == 1
                    else "warm",
                },
            )
        )
    return rows, base | {"source_report": str(path), "events": events}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=DEFAULT_DIR)
    args = parser.parse_args()
    rows: list[dict[str, Any]] = []
    cases: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for path in sorted(args.directory.glob("*/report.json")):
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            skipped.append({"path": str(path), "reason": "incomplete JSON write"})
            continue
        if report.get("status") not in ("ok", "error") or "profile" not in report:
            skipped.append(
                {"path": str(path), "reason": "not finalized", "status": report.get("status")}
            )
            continue
        case_rows, case = summarize(path, report)
        rows.extend(case_rows)
        cases.append(case)
    output = {
        "notes": [
            "Each stage aggregates same-name events on one thread only. Different stage "
            "rows overlap; never sum parent and child rows.",
            "Exclusive wall excludes direct same-thread children, not concurrent threads. "
            "Resource estimates remain inclusive windows.",
            "CPU/GPU weighted means use valid observed duration. Concurrent work is "
            "included; short intervals are estimates, not isolated stage measurements.",
            "Overlapping events within a group suppress combined CPU/GPU means; raw "
            "events are retained.",
            "Peak memory uses in-span sample points only. Missing peaks are null. "
            "LibreOffice subprocess CPU can be missed between samples.",
            "First-document latency excludes startup: HY loads during startup, CT2 during "
            "first worker execution. Startup-plus-first milestones include both.",
            "Milestones are cumulative from upload start, not additive stages. Startup- "
            "plus-first excludes the small startup-to-upload bookkeeping gap.",
            "Shared GPU memory overlaps host RSS. No global sum of concurrent event "
            "durations or CPU values is produced.",
        ],
        "rows": rows,
        "cases": cases,
        "skipped": skipped,
    }
    args.directory.mkdir(parents=True, exist_ok=True)
    (args.directory / "summary.json").write_text(
        json.dumps(output, indent=2) + "\n", encoding="utf-8"
    )
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with (args.directory / "summary.csv").open("w", encoding="utf-8", newline="") as stream:
        if fields:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(
                {k: json.dumps(v) if isinstance(v, list) else v for k, v in row.items()}
                for row in rows
            )
    print(
        f"Summarized {len(cases)} finalized cases, {len(rows)} rows; "
        f"skipped {len(skipped)} unfinished reports."
    )


if __name__ == "__main__":
    main()
