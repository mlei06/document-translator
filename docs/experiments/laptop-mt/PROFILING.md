# Resource profiling

`profiling.py` requires `psutil` (use the experiment environment or `uv run --with psutil`).

```python
from profiling import ResourceProfiler

with ResourceProfiler(pids=[worker_pid, server_pid], interval_s=1.0) as profile:
    run_translation()
record["resources"] = profile.result()
```

Omit `pids` to track the current process. Descendants are discovered recursively and deduplicated; an explicitly supplied llama-server PID is useful when the server was started elsewhere. Use a fresh context for each load, warmup, and timed repetition. Read the result after exiting the context.

Each sample records a UTC timestamp, monotonic elapsed time, observed PIDs, process-tree CPU seconds and utilization, summed RSS, system per-logical-core utilization, Windows GPU Engine counters matched to the tracked PIDs, and dedicated/shared GPU process-memory counters. GPU engine instance names retain adapter and physical-engine identity. The busiest-engine metric sums tracked PIDs on each physical engine and takes the largest engine value; it does not sum percentages across unrelated engines or include other applications.

CPU utilization uses 100 percent for one logical CPU; host-normalized utilization divides by the logical CPU count. `average_cpu_cores` and `cpu_percent.time_weighted_mean` derive from cumulative observed CPU seconds / elapsed seconds. Other means are arithmetic sample means, including a potentially short final sample. Per-core counters describe the whole system, not just the benchmark. RSS can double-count shared pages. Shared GPU memory overlaps system memory and should not be added to RSS as a unique-memory estimate.

Missing counters, access failures, and absent valid GPU PID instances are reported explicitly and remain null, not zero. Valid idle counters report zero. The first GPU rate sample normally has no baseline and is unavailable. Very short runs may have no valid GPU rate sample. Child processes that start and exit between samples cannot be accounted for. Sampling the current process includes profiler overhead; use identical sampling for comparable configurations. Observed GPU usage verifies activity, not kernel efficiency or compute-unit occupancy.

Smoke validation on this Windows machine used an idle Python process and read-only sampling of the existing Desktop Window Manager process. The latter exposed nonzero per-PID 3D activity, approximately 834 MiB shared GPU memory, and valid zero dedicated GPU memory. No model workload was started for profiler validation.
