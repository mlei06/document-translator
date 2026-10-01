# Laptop MT performance

Experiment and integration authorized 2026-09-29. See [execution plan](../../archive/plans/laptop-mt-performance.md)
and [ADR-025](../../decisions/ADR-025-local-hy-mt.md). Twenty representative benchmark
configurations and successful real-document/service acceptance are recorded below.

The subsequent [PowerPoint lifecycle benchmark](LIFECYCLE.md) measures actual service jobs,
offline fit v2, and LibreOffice page previews on a 13-slide deck.

## Scope

Compare SMALL-100 CTranslate2 CPU thread counts, OpenVINO CPU/Intel Arc, and HY-MT1.5-1.8B
GGUF Q8_0 through llama.cpp CPU/Vulkan. The owner deferred broad accuracy scoring. Output
emptiness/truncation and real-document preservation are still checked. SMALL-100's known empty
answer for the standalone company name is retained as an output flag rather than stopping
performance measurements. A faster incomplete answer is not evidence of a better translator.
Initial files in the experiment root are a failure-case screen: the Lenovo label consumed all
256 decoding steps. The representative `business-mixed-v2` corpus replaces it with another
business label, matching the application's protection of company names. New timing comparisons
use only files under `data/experiments/laptop-mt/representative/`; do not combine both corpora.

Hardware: Intel Core Ultra 7 155H, 64 GB system RAM, integrated Intel Arc, Windows, Balanced
power plan. This is a shared interactive laptop, not an isolated performance lab. The Vulkan
binary reports llama.cpp b11222, commit a97cce86a. No NVIDIA GPU is present.

## Reproduction

From the repository root, after the normal workspace setup and SMALL-100 installation:

```powershell
.venv/Scripts/python.exe docs/experiments/laptop-mt/bench.py `
  --runtime ct2-cpu --threads 4 --beam 1 --batch-size 8 --reps 2 --limit 12 `
  --out data/experiments/laptop-mt/ct2-cpu-t4-b8.json

.venv/Scripts/python.exe docs/experiments/laptop-mt/bench.py `
  --runtime hy-vulkan --threads 4 --concurrency 1 --reps 2 --limit 12 `
  --out data/experiments/laptop-mt/hy-vulkan-t4-c1.json
```

The profiler requires `psutil`. OpenVINO cases use the separate experiment environment
`data/experiments/laptop-mt/ov-env/Scripts/python.exe`, provisioned with the dependency pins in
`../openvino-small100/bench.py` and an editable core package. They reuse the existing exported
SMALL-100 artifacts, without adding OpenVINO/Torch/Transformers to production dependencies.
Use `--runtime ov-cpu` or `ov-gpu`. Only run one inference case at a time.

HY defaults to the installed Q8_0 file. `--model` can select the installed Q4_K_M artifact.
`--threads-batch` controls prompt-processing threads separately. `--concurrency` changes server
slots and client concurrent requests, retaining 4096 context tokens per slot. Context shifting
and prompt caching are disabled. HY uses temperature zero and fixed sampling parameters;
quantization/runtime comparisons can still produce different outputs.

## Measurement interpretation

- Every case is a fresh process; OS disk caches are not flushed. Load timing excludes interpreter
  startup and initial module imports, so is not a full application cold-start measurement.
- The same 12 inputs contain three labels, six sentences and three paragraphs. Mixed-length
  segments make these rates incomparable to the earlier 100-sentence FLORES throughput numbers.
- Warmup uses a full sentence and is reported separately. Each timed repetition records outputs,
  token counts, wall time and a separate resource profile. Hashes identify the actual model files.
- Resource profiles capture process-tree CPU seconds/average cores, RSS, raw per-core system
  load, per-PID GPU engines and shared/dedicated GPU process memory. Use time-weighted means.
  Profile boundaries include sampling overhead outside the inference-only wall-time window.
- GPU utilization is the busiest physical engine among the tracked PIDs, not shader occupancy.
  No PID GPU counter is reported as unavailable, not fabricated as zero. GPU shared memory
  overlaps host memory; do not add it to RSS to estimate total unique memory.
- Windows hybrid per-core counters on this machine can over-report load. They are retained with
  an explicit reliability note; process CPU-time deltas are the primary CPU activity measure.
- Full-system process CPU enumeration proved too expensive and is disabled in timed runs.
  Raw sampler overhead is retained. Subsecond warmup/labels are not robust utilization evidence.
- Use repeated measurements and report their spread. Results are configuration guidance for this
  host, not proof of a universally optimal thread count or an accuracy ranking.

Details: [profiler semantics](PROFILING.md). Raw generated evidence lives in ignored
`data/experiments/laptop-mt/`.

## Representative results

These tables use only the 20 completed `business-mixed-v2` cases in
`data/experiments/laptop-mt/representative/`. Every timed output was nonempty and untruncated;
this is a completion check, not evidence of translation quality. Rates are the median of each
repetition's segments/second, with the observed minimum and maximum in parentheses. Most
cases have two repetitions; the four CT2 confirmation cases have three, and HY CPU at four
threads has one. CPU cores mean process CPU seconds divided by observation wall time:
1.00 means one logical CPU fully occupied. Memory figures are peak MiB during inference.

### SMALL-100 CPU thread sweep

CTranslate2 INT8, greedy (beam 1), batch limit 8, 12 mixed-length segments per repetition.
GPU counters were unavailable for these CPU-only processes, so are omitted rather than
reported as measured zero.

| Threads | Segments/s median (min-max) | Average CPU cores | Peak RSS MiB |
|---:|---:|---:|---:|
| 2 | 3.95 (3.74-4.15) | 1.96 | 476.5 |
| 4 | 4.23 (3.95-4.50) | 3.50 | 476.9 |
| 6 | 3.09 (2.96-3.21) | 3.83 | 478.4 |
| 8 | 3.62 (3.37-3.88) | 4.94 | 479.8 |
| 12 | 2.61 (2.12-3.09) | 5.03 | 482.7 |
| 16 | 2.03 (1.17-2.90) | 5.85 | 483.8 |

Increasing threads beyond four consumed more CPU without improving this workload. Two
threads traded a small initial throughput loss for considerably less CPU activity. The later
confirmation runs below show why these are a 2-4 thread starting range, not a universal optimum.

### SMALL-100 batching, beam settings and OpenVINO

The batch-8 CT2 rows here are the separate three-repetition confirmation runs, not the initial
sweep above. OpenVINO and batch-32 CT2 rows have two repetitions. A batch limit of 32 means
all 12 inputs fit in one batch here; this does not measure a full 32-segment batch.
GPU values are time-weighted busiest-engine mean / observed peak; `n/a` means no valid
PID-attributed GPU sample. OpenVINO uses the existing exported artifact and wrapper, while
CT2 uses its INT8 artifact, so this compares actual deployment paths rather than identical
numerical precision.

| Runtime | Threads | Beam | Batch limit | Segments/s median (min-max) | CPU cores | GPU mean/peak % | RSS MiB | Shared GPU MiB |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| CT2 confirmation | 2 | 1 | 8 | 3.04 (2.61-3.19) | 1.71 | n/a | 478.3 | n/a |
| CT2 confirmation | 4 | 1 | 8 | 3.85 (3.20-4.18) | 3.16 | n/a | 479.7 | n/a |
| CT2 confirmation | 2 | 4 | 8 | 1.76 (1.63-1.76) | 1.87 | n/a | 504.1 | n/a |
| CT2 confirmation | 4 | 4 | 8 | 1.40 (1.21-1.75) | 2.93 | n/a | 503.4 | n/a |
| CT2 | 4 | 1 | 32 | 5.38 (4.70-6.07) | 3.72 | n/a | 495.3 | n/a |
| CT2 | 4 | 4 | 32 | 1.98 (1.55-2.40) | 3.03 | n/a | 534.4 | n/a |
| OpenVINO CPU | 4 | 1 | 8 | 1.19 (1.19-1.20) | 2.90 | n/a | 4791.5 | n/a |
| OpenVINO Arc | 4 | 1 | 8 | 2.40 (2.34-2.45) | 3.02 | 60.34 / 75.12 | 2814.3 | 1618.3 |
| OpenVINO Arc | 4 | 4 | 8 | 1.11 (0.93-1.29) | 2.32 | 28.81 / 50.57 | 3007.6 | 1971.1 |

Arc acceleration worked in OpenVINO, roughly doubling greedy throughput relative to its CPU
path. It still trailed CT2 while using substantially more memory. Beam-4 Arc was also slower
than either CT2 confirmation. Keep OpenVINO experimental for SMALL-100 rather than adding
its dependencies and artifact lifecycle to production on this evidence.

### HY-MT1.5-1.8B Q8_0

Generation and prompt-processing threads were equal in each case. Slots equal client request
concurrency, with 4096 context tokens per slot. All cases use one segment per request;
concurrency allows the server to process independent requests together.

| Runtime | Generation/prompt threads | Slots | Median 12-segment time s | Segments/s median (min-max) | CPU cores | GPU mean/peak % | RSS MiB | Shared GPU MiB |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| CPU | 4 / 4 | 1 | 75.71 | 0.16 (single run) | 3.20 | n/a | 2239.2 | n/a |
| CPU | 8 / 8 | 1 | 116.02 | 0.11 (0.09-0.12) | 3.94 | n/a | 2243.1 | n/a |
| Arc Vulkan | 4 / 4 | 1 | 25.90 | 0.46 (0.45-0.48) | 0.37 | 79.10 / 93.69 | 2631.4 | 2426.7 |
| Arc Vulkan | 2 / 2 | 4 | 12.91 | 0.94 (0.84-1.04) | 0.52 | 82.62 / 93.33 | 3411.0 | 3200.3 |
| Arc Vulkan | 4 / 4 | 4 | 11.79 | 1.02 (0.99-1.04) | 0.51 | 84.83 / 96.00 | 3406.0 | 3200.0 |

Four Vulkan slots provided about 2.2 times the single-slot throughput at four threads, with
peak RSS increasing from 2631 to 3406 MiB. Four CPU/prompt threads was the best measured
Vulkan configuration, although its throughput range overlaps the two-thread case. The
four-thread CPU comparison has only one repetition; its much slower result supports Vulkan
as the practical first choice on this Arc laptop, not a precise universal speedup claim.
All GPU cases reported valid zero dedicated GPU memory, consistent with shared-memory Arc.
Shared GPU memory overlaps host memory and must not be added to RSS as unique total usage.

### Configuration guidance and limits

- SMALL-100: start at 2-4 CPU threads. Four threads with batch limit 32 was the fastest measured
  greedy configuration; two threads is a useful lower-CPU option, particularly for beam 4.
  Keep beam selection explicit because it changes decoding, not merely acceleration.
- HY-MT Q8_0: start with Vulkan, four generation threads, four prompt-processing threads and
  four slots for document throughput. One slot uses less memory but is markedly slower here.
  These results establish workable memory and latency on this 64 GB host; battery drain,
  sustained thermals and foreground responsiveness were not separately measured.
- The thread count for prompt processing was exposed but not swept independently. Q4,
  affinity, long sustained documents and other laptop memory budgets remain unmeasured.
- Sampler wall-time/inference-time ratios were 6.0-14.4% across these cases. This measures
  observer burden including scheduling and time overlapping inference; it is not a measured
  slowdown and must not be subtracted from wall times. Raw profiles retain the exact durations.
  The earlier expensive full-system scan was disabled in every reported phase.
- Windows per-core counters are unreliable on this hybrid CPU. Process CPU-time deltas are
  used above. Background applications and this shared host's changing load remain confounders;
  the observed repeat spread and separate confirmation runs are retained rather than averaged
  into a falsely precise single ranking. These runs do not constitute a quality comparison.

Rebuild the machine-readable aggregates with:

```powershell
.venv/Scripts/python.exe docs/experiments/laptop-mt/summarize.py `
  --directory data/experiments/laptop-mt/representative
```

This writes `summary.json` and `summary.csv` beside the source case files. Case JSON retains
per-repetition outputs, timings, resource samples, versions and artifact hashes.

## Real adapter acceptance

Status: passed for all five document formats and both Chinese/English marker smoke directions
in the fresh-process `data/experiments/laptop-mt/acceptance-v2/acceptance.json` run. A separate
real HTTP/worker job also passed, retaining the selected local translator and verifying the
download hash, nonempty English output and unchanged source bytes.

```powershell
.venv/Scripts/python.exe docs/experiments/laptop-mt/acceptance.py `
  --runtime hy-vulkan --threads 4 --concurrency 4 `
  --out data/experiments/laptop-mt/acceptance-v2
```

The production HY-MT chat adapter used Q8_0, Vulkan, four threads and four slots. All original
inputs retained their hashes; each output reopened in its original format with the same extracted
segment count. The resource window includes document extraction, translation, fit and writing,
plus profiling boundaries. Translation-only seconds are recorded separately below. Preview
rendering occurred afterward, outside these profiles and translation times. The same model
server remained loaded across formats; RSS includes the Python process and server working sets.

| Format | Input/output segments | Translation s | Profile wall s | CPU cores | GPU mean/peak % | RSS MiB | Shared GPU MiB | Status |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| PPTX | 16 / 16 | 11.51 | 13.85 | 0.42 | 71.88 / 91.40 | 3588.5 | 3198.9 | passed |
| DOCX | 15 / 15 | 11.17 | 11.84 | 0.31 | 77.56 / 92.12 | 3596.8 | 3199.3 | passed |
| XLSX | 12 / 12 | 4.94 | 6.10 | 0.33 | 63.88 / 86.59 | 3641.7 | 3199.6 | passed |
| PDF | 4 / 4 | 7.18 | 12.30 | 0.54 | 48.55 / 90.09 | 3755.0 | 3199.6 | passed |
| TXT | 3 / 3 | 2.90 | 3.22 | 0.30 | 77.57 / 90.01 | 3653.7 | 3199.6 | passed |

GPU means are time-weighted; memory is peak sampled MiB. Dedicated GPU memory was measured
as zero for each format. Shared GPU memory overlaps RSS/system memory, so these columns
must not be summed as unique memory. This is a single operational run per format, not a
throughput benchmark or an accuracy evaluation.

The initial prompt placed tag-preservation instructions after the translation delimiter, causing
the model to translate those instructions in a marker smoke case. Prompt revision
`hy-mt-translate-v2` moves preservation instructions before that delimiter and removes literal
example tags. Both final marker directions preserved their tags without emitting the instructions;
untagged prompts retain their previous text. The prompt revision enters translation identity.

Acceptance success does not mean every layout issue disappeared: PPTX used the existing
per-formatted-part fallback once; DOCX retained one unresolved text-box fit warning; XLSX
retained two unresolved fit warnings and adjusted one cell. PDF adjusted two text regions.
These details and existing unsupported-content diagnostics remain in the raw reports.

Failed evidence under `data/experiments/laptop-mt/acceptance/` is retained: it records the
original marker-prompt problem and a transient PDF import failure while workspace files changed
externally. The final fresh-process run passed all five formats; the earlier failures are not
included in the successful resource table.

The external llama.cpp process is administrator-managed. See
[deployment instructions](../../Deployment.md#local-hy-mt-inference).

The isolated service run is recorded in
`data/experiments/laptop-mt/service/e7615be06c7b/acceptance.json`. End-to-end wall time was
14.50 seconds, including profiler setup and service scheduling, not just decoding. Its resource
window measured 0.63 average CPU cores, 15.85% mean / 65.16% peak GPU activity, 3662.5 MiB
peak process-tree RSS and 3180.8 MiB shared GPU memory. This short single-request service
check includes idle/queue time and is not comparable to the sustained inference table.

The local website was configured with `hy-mt-local` (label **HY-MT 1.5 1.8B Q8**), while
retaining both SMALL-100 presets, all six Davy entries and the `small100-beam4` default.
An authenticated request verified the live capabilities catalog after restart; the temporary
verification account was disabled afterward. The previously configured network address was
unavailable, so the website now binds to `https://127.0.0.1:8765`, retaining its existing TLS
certificate. The pre-change private settings backup remains under ignored experiment data.
The loopback llama-server on port 8099 remains running; it is not automatically restarted at boot.

## Code validation

Earlier on 2026-09-29, before the concurrent offline-fit implementation began,
`uv sync --all-packages`, Ruff formatting/lint, Pyright and all 14 import contracts passed.
`uv run pytest` passed 364 tests with two backend integration tests deselected in
595.88 seconds. The real HY-MT acceptance described above is separate from those mocked/unit
and service tests. All five experiment scripts also passed explicit-file Ruff and Pyright.
The prompt-v2 correction separately passed 20 HY tests, Ruff and Pyright. Independent production
review approved the adapter after verifying loopback proxy isolation and the prompt correction.
The final whole-workspace rerun encountered concurrent offline-fit changes in pipeline, render,
types and document tests: sync and all 14 import contracts passed; format failed on 14 files,
lint reported 42 errors and Pyright reported three errors. Pytest finished with **358 passed,
25 failed, two deselected** in 948.44 seconds. All HY-owned tests and all five service CLI E2E
tests passed. Most failures involved the new serialized-text verification in `pipeline.py`;
one involved the new PDF font-floor rejection. These belong to the active offline-fit work and
were not overwritten in this task. The captured failure output and check summary are in
`data/experiments/laptop-mt/checks-final.log` (earlier lint output is summarized, not a full log).
A fresh release gate is required after that work stabilizes. This working tree is not a clean
committed release baseline.
