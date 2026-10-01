"""Summarize completed laptop MT case JSON without running any model workloads."""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from pathlib import Path
from typing import Any, cast

DEFAULT_DIR = Path(__file__).resolve().parents[3] / "data/experiments/laptop-mt"


def summarize(path: Path, case: dict[str, Any]) -> dict[str, Any]:
    settings = case["settings"]
    phases = case.get("phases", [])
    inference = [p for p in phases if p["name"].startswith("inference_")]
    profiles = [p["profile"] for p in inference if "profile" in p]
    walls = [p["wall_s"] for p in inference if p.get("wall_s", 0) > 0]
    rates = [p["segments_per_s"] for p in inference if p.get("segments_per_s") is not None]

    def peak(key: str) -> float | None:
        values = [p.get(key, {}).get("max") for p in profiles]
        return max((v for v in values if v is not None), default=None)

    def mib(key: str) -> float | None:
        value = peak(key)
        return value / 2**20 if value is not None else None

    def weighted(key: str) -> tuple[float | None, float]:
        pairs = [
            (p.get(key, {}).get("time_weighted_mean"), p.get(key, {}).get("valid_duration_s", 0))
            for p in profiles
        ]
        pairs = [
            (value, duration) for value, duration in pairs if value is not None and duration > 0
        ]
        duration = sum(duration for _, duration in pairs)
        return (
            sum(value * seconds for value, seconds in pairs) / duration if duration else None,
            duration,
        )

    cpu_profiles = [
        p
        for p in profiles
        if p.get("cpu_observation_duration_s", 0) > 0 and p.get("cpu_seconds") is not None
    ]
    cpu_duration = sum(p["cpu_observation_duration_s"] for p in cpu_profiles)
    cpu_seconds = sum(p["cpu_seconds"] for p in cpu_profiles)
    gpu, gpu_duration = weighted("gpu_busiest_engine_pct")
    overheads = [p.get("sampler_wall_s") for p in profiles]
    overhead = sum(overheads) if overheads and all(v is not None for v in overheads) else None
    all_profiles = [p.get("profile", {}) for p in phases]
    compatible = bool(all_profiles) and all(
        p.get("system_process_scan_enabled") is False for p in all_profiles
    )
    flags = [flag for phase in inference for flag in phase.get("flags", [])]
    notes: list[str] = []
    if not compatible:
        notes.append(
            "Full-system scan disabled is not established for every phase; compare separately."
        )
    if gpu is None:
        notes.append("No valid weighted GPU samples; unavailable does not mean zero GPU activity.")
    if len(walls) < settings.get("reps", 0):
        notes.append("Fewer completed inference repetitions than requested.")
    if any(p.get("sampler_errors") for p in all_profiles):
        notes.append("Sampler errors recorded; inspect raw case JSON.")
    if overhead is not None and walls and overhead / sum(walls) > 0.05:
        notes.append("Sampler wall/inference ratio exceeds 5%; inspect observer influence.")
    return {
        "case": path.name,
        "status": case.get("status", "unknown"),
        "runtime": settings.get("runtime"),
        "threads": settings.get("threads"),
        "prompt_threads": (settings.get("threads_batch") or settings.get("threads"))
        if str(settings.get("runtime", "")).startswith("hy-")
        else None,
        "concurrency": settings.get("concurrency", 1),
        "beam": settings.get("beam"),
        "batch": settings.get("batch_size"),
        "inference_seconds": walls,
        "inference_seconds_median": statistics.median(walls) if walls else None,
        "segments_per_s_median": statistics.median(rates) if rates else None,
        "segments_per_s_min": min(rates) if rates else None,
        "segments_per_s_max": max(rates) if rates else None,
        "average_cpu_cores": cpu_seconds / cpu_duration if cpu_duration else None,
        "cpu_observation_duration_s": cpu_duration,
        "gpu_time_weighted_mean_pct": gpu,
        "gpu_valid_duration_s": gpu_duration,
        "gpu_peak_pct": peak("gpu_busiest_engine_pct"),
        "peak_rss_mib": mib("rss_bytes"),
        "peak_shared_gpu_mib": mib("gpu_shared_bytes"),
        "peak_dedicated_gpu_mib": mib("gpu_dedicated_bytes"),
        "empty_outputs": sum(bool(f.get("empty")) for f in flags),
        "truncated_outputs": sum(bool(f.get("truncated")) for f in flags),
        "outputs_valid": case.get("outputs_valid"),
        "compatible_profile": compatible,
        "profiler_inference_sampler_wall_s": overhead,
        "profiler_wall_to_inference_ratio": overhead / sum(walls)
        if overhead is not None and walls
        else None,
        "notes": notes,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "cases", type=Path, nargs="*", help="Explicit case JSON files; default: directory/*.json"
    )
    parser.add_argument("--directory", type=Path, default=DEFAULT_DIR)
    args = parser.parse_args()
    paths = args.cases or sorted(args.directory.glob("*.json"))
    rows: list[dict[str, Any]] = []
    for path in paths:
        if path.name == "summary.json":
            continue
        case = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(case, dict) or "settings" not in case or "phases" not in case:
            continue
        rows.append(summarize(path, cast(dict[str, Any], case)))
    report = {
        "notes": [
            "All resource aggregates cover inference phases only, excluding load and warmup.",
            "No automatic exclusions; compatible_profile checks only the full-system scan flag.",
            "Sampler wall time includes waiting and overlaps inference; the ratio is an observer "
            "burden diagnostic, not measured slowdown or CPU overhead.",
            "GPU means weight valid observation durations; missing telemetry remains null.",
            "RSS may double-count shared pages; GPU shared memory overlaps system memory.",
        ],
        "cases": rows,
    }
    args.directory.mkdir(parents=True, exist_ok=True)
    (args.directory / "summary.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    with (args.directory / "summary.csv").open("w", encoding="utf-8", newline="") as stream:
        if rows:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(
                {
                    key: json.dumps(value) if isinstance(value, list) else value
                    for key, value in row.items()
                }
                for row in rows
            )
    print(f"{'Case':38} {'seg/s':>8} {'CPU':>7} {'GPU%':>7} {'RSS MiB':>9} {'Profile':>8} Status")
    for row in rows:

        def fmt(key: str, row: dict[str, Any] = row) -> str:
            value = row[key]
            return f"{value:.2f}" if value is not None else "n/a"

        print(
            f"{row['case']:38} {fmt('segments_per_s_median'):>8} "
            f"{fmt('average_cpu_cores'):>7} {fmt('gpu_time_weighted_mean_pct'):>7} "
            f"{fmt('peak_rss_mib'):>9} {row['compatible_profile']!s:>8} {row['status']}"
        )


if __name__ == "__main__":
    main()
