# PowerPoint lifecycle profiling

Status: eight real document runs completed 2026-09-29 local time (2026-09-30 UTC),
after completion of offline fit v2.

## Workload and scope

Use the same Chinese intermediate deck as the offline-fit investigation: 13 visible slides,
84,302,616 bytes, SHA-256
`868de6e17d03c9743d297ba1924582df2aa220668fb1d9968555de60da7330ad`.
The private source is copied to ignored `data/experiments/laptop-mt/lifecycle/source.pptx`.
It is translated Chinese to English using SMALL-100 CTranslate2 INT8, beam 4, four CPU threads,
batch limit 32; or HY-MT1.5-1.8B Q8_0, Vulkan, four generation/prompt threads and four slots.
Both models use identical source bytes, fonts and render settings. This is a lifecycle
performance measurement, not a translation quality comparison.

The experiment uses isolated service data and real HTTP requests with the production job,
translation, fit and page-rendering implementations. It runs one job at a time and waits for
all page previews before submitting another. A controlled single-worker process avoids
competition between benchmark jobs. Service startup/model loading and first-document costs
are separated from subsequent documents; an unflushed OS file cache is not a disk-cold test.
HY's external server loads during startup, while SMALL-100 loads lazily on its first job.
Compare startup plus the first job for a cold application comparison, and subsequent jobs
for warm document latency. A first-job-only comparison would unfairly exclude HY loading.

Standard fit and opt-in thorough fit are separate scenarios. Thorough fit may render source
and candidate before publication, and may perform a bounded additional repair/render.
Asynchronous previews independently render source and output after publication. Report
download-ready and all-previews-ready times separately. Do not count nested thorough work
twice: the existing core `write` timing includes serialized verification and thorough fitting.

## Metrics and correctness

- Record exact wall-clock event spans for startup, upload/admission, queue, engine load,
  extraction/protection, model calls, formatting recovery/application, standard fit,
  serialization/integrity/publication, optional rendered fit, preview conversion/rasterization,
  packaging and downloads.
- Use one continuous process-tree CPU/RSS and PID-attributed GPU trace. Weight sampling
  intervals by overlap with each event; label estimates and short-stage coverage explicitly.
  Whole-process CPU during overlapping threads is not CPU caused exclusively by that stage.
- Include LibreOffice descendants; CPU from processes that exit between samples can be missed,
  and sampled peak memory is a lower-bound observation. Shared GPU memory overlaps host memory.
- Preserve exact raw events, resource samples, observer cost, model/font/renderer identities,
  output hashes, fit diagnostics and individual repetition times under ignored experiment data.
- Check source bytes unchanged, output download hash, reopened slide count, preview status,
  13 source/target page pairs and all 26 downloaded JPEG dimensions. Verify document download
  succeeds while previews are still queued/running. No external translation service is used.

The live website's obsolete `DOCTRANSLATOR_SOFFICE_PATH` override was removed. Migration
reported revision `0006`; the idle site was restarted and both page-renderer workers detected
`C:/Program Files/LibreOffice/program/soffice.com`. Existing TLS and translator settings remain.

## Results

### Standard fit: completed three repetitions per model

Seconds; warm values are the mean of repetitions 2 and 3, not a large-sample estimate.

| Milestone | SMALL-100 beam 4 | HY-MT Q8 Vulkan |
| --- | ---: | ---: |
| Measured service startup | 3.43 | 12.37 |
| Startup + first publication | 137.39 | 164.71 |
| First publication, excluding startup | 133.96 | 152.34 |
| Warm publication mean (range) | 101.54 (88.60-114.47) | 160.29 (153.31-167.27) |
| Warm download completed | 105.65 | 164.47 |
| Warm all previews ready mean (range) | 149.87 (131.95-167.80) | 226.84 (217.49-236.20) |
| Warm all JPEG downloads completed | 150.79 | 228.14 |

On these two warm runs, SMALL-100 was **1.58x faster to publication**, **1.60x faster in
translation/recovery**, and **1.51x faster to all previews ready**. These are ratios of means
for this deck, not universal model speedups. All milestones except the explicitly combined
startup rows are cumulative from upload start. The first CT2 model load took 2.09 seconds;
HY model-server loading took 10.49 seconds inside startup. CLI imports and initial workload
metadata gathering precede the profiler and are excluded from measured service startup.

| Stage (inclusive event window) | SMALL-100 beam 4 | HY-MT Q8 Vulkan |
| --- | ---: | ---: |
| Upload/admission response | 2.96 | 2.83 |
| Queue wait, persisted created-to-started timestamps | 0.167 | 0.058 |
| Extraction | 0.060 | 0.067 |
| Translation including formatting recovery | 94.35 | 151.20 |
| Apply translated text | 0.044 | 0.041 |
| Standard fit | 1.27 | 2.27 |
| Save, verify, atomic file publication | 0.94 | 1.08 |
| Text preview packaging | 0.10 | 0.17 |
| Result publication/page queue transaction | 0.010 | 0.011 |
| Download translated PPTX | 4.11 | 4.18 |
| LibreOffice source conversion for previews | 22.78 | 31.27 |
| LibreOffice translated conversion for previews | 21.37 | 30.00 |
| Rasterize both PDFs to JPEGs | 2.33 | 3.51 |
| Download all 26 JPEGs | 0.90 | 1.28 |

These are selected spans, not an additive accounting ledger: downloads and background
previews overlap, upload response can overlap worker startup, and lifecycle overhead remains.
All spans, nesting, coverage and resources are in the machine-readable summary.
Queue wait is derived from job timestamps retained in each raw report; it overlaps admission
response timing and is too short for an independent one-second resource sample.

### Resource observations during warm standard-fit stages

CPU is duration-weighted average occupied logical cores in the owned process tree (one core
= 100% in process-style CPU reporting), not percent of all 22 logical cores. GPU is the
PID-attributed busiest-engine counter. RSS is the maximum observed sample across both warm
runs in MiB, including the resident model and any owned LibreOffice process.

| Model / stage | CPU cores | GPU activity | Peak RSS MiB |
| --- | ---: | ---: | ---: |
| SMALL-100 translation/recovery | 3.34 | no attributed sample | 998 |
| SMALL-100 standard fit | 1.18 | no attributed sample | 634 |
| SMALL-100 save/verify | 1.01 | no attributed sample | 642 |
| SMALL-100 source preview conversion | 1.09 | 0% | 1,504 |
| SMALL-100 target preview conversion | 0.99 | 0% | 1,508 |
| SMALL-100 rasterization | 0.92 | no attributed sample | 674 |
| HY translation/recovery | 0.51 | 85-86% | 3,623 |
| HY standard fit | 0.88 | 0-6% interval estimate | 3,623 |
| HY save/verify | 0.97 | 0% | 3,622 |
| HY source preview conversion | 1.04 | 0% | 4,526 |
| HY target preview conversion | 0.98 | 0% | 4,538 |
| HY rasterization | 0.86 | 0% | 3,656 |

SMALL-100 is explicitly configured for CT2 CPU. Missing PID GPU instances are retained as
missing observations, not converted to measured zeros. The short HY fit-stage GPU estimate
can include translation at the sampling-interval boundary; it does not show GPU-accelerated
fit computation. Subsecond stages can have no in-span memory sample. Full coverage and
missing-value fields are preserved for every event, including upload and download.

The source conversion uses identical bytes for both models, yet its timing varies too.
Do not attribute that difference to model architecture. Serial case ordering, an interactive
host, caches and scheduler/power behavior limit causal comparisons. No thermal measurements
were taken. The live site and its separate HY daemon remained available but idle; resource
metrics cover only the benchmark-owned process tree.

See [earlier model-only results](README.md) for context; those short mixed-input measurements
must not be substituted for this document lifecycle.

### Thorough fit: one fresh-process sample per model

These are screening samples, not warm means. Use the directly instrumented thorough span
to estimate its cost; subtracting whole jobs would mix different translation and host times.

| Stage or milestone, seconds | SMALL-100 beam 4 | HY-MT Q8 Vulkan |
| --- | ---: | ---: |
| Translation/recovery | 82.40 | 147.77 |
| Standard fit portion | 1.62 | 3.07 |
| Additional thorough check, inclusive | 62.08 | 67.03 |
| Source LibreOffice conversion inside thorough | 29.66 | 35.59 |
| Candidate LibreOffice conversion inside thorough | 30.60 | 29.34 |
| Geometry verification inside thorough | 0.64 | 0.65 |
| Save/verify/publish, including thorough | 62.82 | 67.79 |
| Publication from upload start | 158.14 | 228.53 |
| Startup + publication | 160.57 | 237.21 |
| All previews ready from upload start | 209.56 | 280.43 |
| Later preview source conversion | 27.43 | 26.60 |
| Later preview target conversion | 20.23 | 21.81 |
| Later rasterization, both PDFs | 2.34 | 2.15 |

Each thorough span averaged 0.94 CPU cores and 0% measured GPU activity. Peak owned RSS
was 1,579 MiB for SMALL-100 and 4,544 MiB for HY. There were two conversions per thorough
check and two more for asynchronous previews; no additional repair-render occurred.
Thorough verification itself took less than one second, so conversion dominates this cost.
Keeping standard fit as the default avoids placing about a minute of rendering on the
download path. A possible future optimization is safe reuse of compatible verification
renders for previews, but this experiment does not implement or assume that reuse.

## Integrity, diagnostics and limitations

All eight jobs succeeded with unchanged source bytes, matching download SHA-256, 13 slides
in each reopened ZIP package, and 26 decoded JPEG downloads per run. Every PPTX download
completed while preview status was still `running`. All 13 page pairs eventually became
ready without truncation. Each job had 165 segments, 33 passed-through segments and 131
unique inputs. HY needed no formatting fallback; SMALL-100 needed one per document.

Standard fit inspected 122 containers and marked 91 unresolved, principally because source
measurement was unknown. Both thorough checks returned `partial`, checking all 13 pages
and 119/122 units with three unknown text correspondences. SMALL-100 reported 16 confirmed
source-present findings and no confirmed introduced findings. HY reported 19 source-present
and four introduced findings (three container-footprint findings and one collision).
Visual spot checks included standard slides 4/6 and HY thorough slide 9; the latter shows
a heading/body collision. Successful lifecycle completion is not a clean-layout claim.
No translation accuracy scoring was performed.

MuPDF emitted unsupported Screen-annotation appearance warnings for this media-rich deck.
Static previews completed; embedded media appearance/playback is not validated by JPEGs.
The laptop was on AC, Balanced mode, with 16 physical/22 logical cores and about 64 GiB RAM.

Sampler elapsed work was 63.74/685.57 seconds for HY standard, 33.50/501.69 for SMALL-100
standard, 23.97/290.20 for HY thorough, and 12.03/213.17 for SMALL-100 thorough. This is
5.6-9.3% sampling-thread wall occupancy, not a measured application slowdown; there is no
unprofiled control. Process CPU includes profiler/API orchestration work. Sampled memory and
short-lived LibreOffice CPU can underestimate peaks/tails. Shared GPU memory overlaps host
memory and must not be added to RSS. Individual samples and coverage are retained.

## Reproduction and artifacts

Run one command at a time from the repository root, using fresh output directories:

```powershell
uv run python docs/experiments/laptop-mt/lifecycle.py --input data/experiments/laptop-mt/lifecycle/source.pptx --model small100 --fit-mode standard --reps 3 --out data/experiments/laptop-mt/lifecycle/small100-standard
uv run python docs/experiments/laptop-mt/lifecycle.py --input data/experiments/laptop-mt/lifecycle/source.pptx --model hy --fit-mode standard --reps 3 --out data/experiments/laptop-mt/lifecycle/hy-standard
uv run python docs/experiments/laptop-mt/lifecycle.py --input data/experiments/laptop-mt/lifecycle/source.pptx --model small100 --fit-mode thorough --reps 1 --out data/experiments/laptop-mt/lifecycle/small100-thorough
uv run python docs/experiments/laptop-mt/lifecycle.py --input data/experiments/laptop-mt/lifecycle/source.pptx --model hy --fit-mode thorough --reps 1 --out data/experiments/laptop-mt/lifecycle/hy-thorough
uv run python docs/experiments/laptop-mt/lifecycle_summary.py
```

Actual measurement order was HY standard, SMALL-100 standard, HY thorough, SMALL-100 thorough.
The controlled harness uses the production HTTP service, worker and page renderer in one
process with threads; the live site uses separate worker processes. This tests the full
service path but is not a concurrent production-load or browser-network benchmark.

- [Per-stage CSV, 218 rows](../../../data/experiments/laptop-mt/lifecycle/summary.csv)
- [Summary JSON with raw nested events](../../../data/experiments/laptop-mt/lifecycle/summary.json)
- [Output integrity checks](../../../data/experiments/laptop-mt/lifecycle/integrity.json)
- [Host metadata](../../../data/experiments/laptop-mt/lifecycle/host.json)
- Each case's `report.json` contains raw CPU/GPU samples, fit reports, runtime identities,
  hashes and coverage; adjacent PPTX/JPEG outputs remain in ignored local experiment data.

The scripts only instrument the experiment process. No production pipeline changes were
needed for this lifecycle benchmark. The site preview enablement described above is active.

Validation after all profiling finished: `uv sync --all-packages`, `uv run ruff format
--check`, `uv run ruff check`, `uv run pyright`, `uv run lint-imports` and `uv run pytest`
all passed. Pytest: **403 passed, 2 integration tests deselected**, 374.82 seconds. All 14
import contracts held. Explicit Ruff format/lint and Pyright checks also passed for the three
lifecycle experiment scripts. No test or model benchmark ran concurrently with a measured job.
