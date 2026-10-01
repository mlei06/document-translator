"""Low-overhead process-tree CPU/RSS and Windows per-PID GPU benchmark samples."""

from __future__ import annotations

import ctypes
import os
import re
import statistics
import sys
import threading
import time
from ctypes import wintypes
from datetime import UTC, datetime
from typing import Any

import psutil


class _Value(ctypes.Structure):
    _fields_ = [("status", wintypes.DWORD), ("value", ctypes.c_double)]


class _Item(ctypes.Structure):
    _fields_ = [("name", wintypes.LPWSTR), ("value", _Value)]


class _GpuCounters:
    """English PDH counters; unavailable counters never become synthetic zeroes."""

    def __init__(self) -> None:
        self.query = wintypes.HANDLE()
        self.counters: dict[str, Any] = {}
        self.errors: dict[str, str] = {}
        if sys.platform != "win32":
            self.errors["gpu"] = "Windows PDH unavailable on this platform"
            return
        self.dll = ctypes.WinDLL("pdh")
        self.dll.PdhOpenQueryW.argtypes = [
            wintypes.LPCWSTR,
            ctypes.c_size_t,
            ctypes.POINTER(wintypes.HANDLE),
        ]
        self.dll.PdhAddEnglishCounterW.argtypes = [
            wintypes.HANDLE,
            wintypes.LPCWSTR,
            ctypes.c_size_t,
            ctypes.POINTER(wintypes.HANDLE),
        ]
        self.dll.PdhCollectQueryData.argtypes = [wintypes.HANDLE]
        self.dll.PdhGetFormattedCounterArrayW.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            ctypes.POINTER(wintypes.DWORD),
            ctypes.c_void_p,
        ]
        self.dll.PdhCloseQuery.argtypes = [wintypes.HANDLE]
        status = self.dll.PdhOpenQueryW(None, 0, ctypes.byref(self.query))
        if status:
            self.errors["gpu"] = f"PdhOpenQueryW: {status & 0xFFFFFFFF:#x}"
            return
        for key, path in {
            "engines": r"\GPU Engine(*)\Utilization Percentage",
            "shared_bytes": r"\GPU Process Memory(*)\Shared Usage",
            "dedicated_bytes": r"\GPU Process Memory(*)\Dedicated Usage",
        }.items():
            counter = wintypes.HANDLE()
            status = self.dll.PdhAddEnglishCounterW(self.query, path, 0, ctypes.byref(counter))
            if status:
                self.errors[key] = f"PdhAddEnglishCounterW: {status & 0xFFFFFFFF:#x}"
            else:
                self.counters[key] = counter

    def sample(self, pids: set[int]) -> dict[str, Any]:
        out: dict[str, Any] = {"errors": dict(self.errors)}
        if not self.query:
            return out
        status = self.dll.PdhCollectQueryData(self.query)
        if status:
            out["errors"]["collect"] = f"{status & 0xFFFFFFFF:#x}"
        for key, counter in self.counters.items():
            size, count = wintypes.DWORD(), wintypes.DWORD()
            self.dll.PdhGetFormattedCounterArrayW(
                counter, 0x200 | 0x8000, ctypes.byref(size), ctypes.byref(count), None
            )
            if not size.value:
                out[key] = None
                out["errors"][key] = "No counter instances available"
                continue
            buffer = ctypes.create_string_buffer(size.value)
            status = self.dll.PdhGetFormattedCounterArrayW(
                counter, 0x200 | 0x8000, ctypes.byref(size), ctypes.byref(count), buffer
            )
            if status:
                out[key] = None
                out["errors"][key] = f"PdhGetFormattedCounterArrayW: {status & 0xFFFFFFFF:#x}"
                continue
            items = ctypes.cast(buffer, ctypes.POINTER(_Item))
            values: dict[str, float] = {}
            for index in range(count.value):
                item = items[index]
                match = re.match(r"pid_(\d+)_", item.name)
                if match and int(match[1]) in pids and item.value.status in (0, 1):
                    values[item.name] = item.value.value
            out[key] = values or None
            if not values:
                out["errors"][key] = "No valid counter instances for tracked PIDs"
        engines: dict[str, float] | None = out.get("engines")
        # Sum tracked processes on each physical engine, then select busiest engine.
        physical: dict[str, float] = {}
        for name, value in (engines or {}).items():
            engine = re.sub(r"^pid_\d+_", "", name)
            physical[engine] = physical.get(engine, 0.0) + value
        out["busiest_engine_pct"] = max(physical.values()) if physical else None
        out["shared_total_bytes"] = (
            sum(out["shared_bytes"].values()) if out.get("shared_bytes") else None
        )
        out["dedicated_total_bytes"] = (
            sum(out["dedicated_bytes"].values()) if out.get("dedicated_bytes") else None
        )
        return out

    def close(self) -> None:
        if self.query:
            self.dll.PdhCloseQuery(self.query)
            self.query = wintypes.HANDLE()


class ResourceProfiler:
    """Context manager tracking supplied roots and their observed descendants.

    CPU work in children that exit between samples cannot be recovered on Windows.
    RSS sums working sets and can double-count shared pages. GPU is tracked-PID
    activity only; null means unavailable/no valid instances, never assumed idle.
    """

    def __init__(
        self,
        pids: list[int] | None = None,
        interval_s: float = 1.0,
        *,
        system_processes: bool = False,
    ) -> None:
        if interval_s <= 0:
            raise ValueError("interval_s must be positive")
        self.pids = list(dict.fromkeys(pids if pids is not None else [os.getpid()]))
        self.interval_s = interval_s
        self.system_processes = system_processes
        self.samples: list[dict[str, Any]] = []
        self._stop = threading.Event()
        self._previous: dict[tuple[int, float], float] = {}
        self._observed: dict[tuple[int, float], psutil.Process] = {}
        self._cpu_seconds = 0.0
        self._errors: list[str] = []
        self._system_process_before: dict[tuple[int, float], float] = {}

    def __enter__(self) -> ResourceProfiler:
        self._gpu = _GpuCounters()
        self._epoch_started = time.time()
        self._start = self._at = time.perf_counter()
        self._system_before = psutil.cpu_times(percpu=True)
        self._sample(initial=True)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def _run(self) -> None:
        while not self._stop.wait(self.interval_s):
            try:
                self._sample()
            except Exception as exc:
                self._errors.append(f"{type(exc).__name__}: {exc}")

    def _sample(self, initial: bool = False) -> None:
        sample_started = time.perf_counter()
        errors: list[str] = []
        for pid in self.pids:
            try:
                root = psutil.Process(pid)
                for process in [root, *root.children(recursive=True)]:
                    self._observed[(process.pid, process.create_time())] = process
            except psutil.Error as exc:
                errors.append(f"PID {pid}: {type(exc).__name__}")
        rss = 0
        current: dict[tuple[int, float], float] = {}
        delta = 0.0
        for identity, process in list(self._observed.items()):
            try:
                times = process.cpu_times()
                cpu = times.user + times.system
                rss += process.memory_info().rss
                current[identity] = cpu
                if identity in self._previous:
                    delta += max(0.0, cpu - self._previous[identity])
                elif process.create_time() >= self._epoch_start:
                    delta += cpu
            except psutil.Error as exc:
                errors.append(f"PID {identity[0]}: {type(exc).__name__}")
                del self._observed[identity]
        all_processes: dict[tuple[int, float], float] = {}
        inaccessible = 0
        system_delta = 0.0
        if self.system_processes:
            for process in psutil.process_iter(["pid", "create_time", "cpu_times"], ad_value=None):
                info = process.info
                times = info["cpu_times"]
                if times is None or info["create_time"] is None:
                    inaccessible += 1
                    continue
                # PID 0 accounts for idle CPU time and is not busy process work.
                if info["pid"] == 0:
                    continue
                identity = (info["pid"], info["create_time"])
                total = times.user + times.system
                all_processes[identity] = total
                before = self._system_process_before.get(identity)
                if before is not None:
                    system_delta += max(0.0, total - before)
                elif info["create_time"] >= self._epoch_start:
                    system_delta += total
        self._system_process_before = all_processes
        now = time.perf_counter()
        elapsed = now - self._at
        cpu_pct = delta / elapsed * 100 if not initial and elapsed else None
        if not initial:
            self._cpu_seconds += delta
        pids = {identity[0] for identity in current}
        system_now = psutil.cpu_times(percpu=True)
        per_core: list[float | None] = []
        for before, after in zip(self._system_before, system_now, strict=True):
            # Windows user + system + idle excludes separately reported interrupt/DPC
            # times, which are already contained in system time.
            total = sum(getattr(after, k) - getattr(before, k) for k in ("user", "system", "idle"))
            busy = (after.user - before.user) + (after.system - before.system)
            per_core.append(max(0.0, min(100.0, 100 * busy / total)) if total > 0 else None)
        self._system_before = system_now
        self.samples.append(
            {
                "timestamp_utc": datetime.now(UTC).isoformat(),
                "elapsed_s": now - self._start,
                "interval_s": elapsed,
                "pids": sorted(pids),
                "process_tree_cpu_percent": cpu_pct,
                "process_tree_host_cpu_percent": cpu_pct / (psutil.cpu_count() or 1)
                if cpu_pct is not None
                else None,
                "process_tree_cpu_seconds": self._cpu_seconds,
                "process_tree_rss_bytes": rss if current else None,
                "system_per_core_cpu_percent": per_core if not initial else None,
                "system_observed_process_cpu_cores": system_delta / elapsed
                if self.system_processes and not initial and elapsed
                else None,
                "background_observed_process_cpu_cores": max(0.0, system_delta - delta) / elapsed
                if self.system_processes and not initial and elapsed
                else None,
                "system_processes_unreadable": inaccessible if self.system_processes else None,
                "gpu": self._gpu.sample(pids),
                "process_errors": errors,
            }
        )
        self.samples[-1]["sampler_wall_s"] = time.perf_counter() - sample_started
        self._previous, self._at = current, now

    @property
    def _epoch_start(self) -> float:
        return self._epoch_started

    def __exit__(self, *_: Any) -> None:
        self._stop.set()
        self._thread.join()
        try:
            self._sample()
        finally:
            self._gpu.close()

    def result(self) -> dict[str, Any]:
        def aggregate(values: list[float | None], *, weighted: bool = False) -> dict[str, Any]:
            valid = [value for value in values if value is not None]
            weights = (
                [
                    (value, sample["interval_s"])
                    for value, sample in zip(values, self.samples, strict=True)
                    if value is not None and sample["process_tree_cpu_percent"] is not None
                ]
                if weighted
                else []
            )
            seconds = sum(weight for _, weight in weights)
            return {
                "mean": statistics.mean(valid) if valid else None,
                "mean_method": "arithmetic_sample_mean",
                **(
                    {
                        "time_weighted_mean": sum(value * weight for value, weight in weights)
                        / seconds
                        if seconds
                        else None,
                        "valid_duration_s": seconds,
                    }
                    if weighted
                    else {}
                ),
                "max": max(valid) if valid else None,
                "valid_samples": len(valid),
            }

        duration = self.samples[-1]["elapsed_s"] if self.samples else 0
        cpu_duration = duration - self.samples[0]["elapsed_s"] if self.samples else 0
        return {
            "cpu_observation_duration_s": cpu_duration,
            "sampler_wall_s": sum(s["sampler_wall_s"] for s in self.samples),
            "root_pids": self.pids,
            "interval_s": self.interval_s,
            "logical_cpus": psutil.cpu_count(),
            "duration_s": duration,
            "cpu_seconds": self._cpu_seconds,
            "average_cpu_cores": self._cpu_seconds / cpu_duration if cpu_duration else None,
            "cpu_percent": {
                **aggregate([s["process_tree_cpu_percent"] for s in self.samples]),
                "time_weighted_mean": self._cpu_seconds / cpu_duration * 100
                if cpu_duration
                else None,
            },
            "rss_bytes": aggregate(
                [s["process_tree_rss_bytes"] for s in self.samples], weighted=True
            ),
            "gpu_busiest_engine_pct": aggregate(
                [s["gpu"].get("busiest_engine_pct") for s in self.samples], weighted=True
            ),
            "gpu_shared_bytes": aggregate(
                [s["gpu"].get("shared_total_bytes") for s in self.samples], weighted=True
            ),
            "gpu_dedicated_bytes": aggregate(
                [s["gpu"].get("dedicated_total_bytes") for s in self.samples], weighted=True
            ),
            "system_per_core_cpu_percent": [
                aggregate(
                    [
                        sample["system_per_core_cpu_percent"][index]
                        for sample in self.samples
                        if sample["system_per_core_cpu_percent"] is not None
                    ]
                )
                for index in range(psutil.cpu_count() or 1)
            ],
            "system_process_scan_enabled": self.system_processes,
            "system_cpu_note": (
                "Per-core CPU counters can misreport on hybrid Windows CPUs; use observed "
                "process CPU deltas for contention. Process totals exclude inaccessible and "
                "between-sample exited processes, so are lower bounds."
            ),
            "system_observed_process_cpu_cores": aggregate(
                [s["system_observed_process_cpu_cores"] for s in self.samples], weighted=True
            ),
            "background_observed_process_cpu_cores": aggregate(
                [s["background_observed_process_cpu_cores"] for s in self.samples], weighted=True
            ),
            "sampler_errors": self._errors,
            "samples": self.samples,
        }
