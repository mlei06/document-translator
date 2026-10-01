# Laptop translation performance and HY-MT integration

> Historical plan. Retained for rationale and evidence, not current implementation instructions. Follow the [current specification](../../plans/unified-translator-design.md) and [execution checklist](../../plans/unified-execution.md).

Status: Benchmarks and integration verified, 2026-09-29. Final whole-workspace check gate
is pending concurrent offline-fit implementation; do not treat the shared working tree as a
validated release. See [measured evidence](../../experiments/laptop-mt/README.md).

## Scope and authority

The owner explicitly requested GPU acceleration, stronger laptop translation models and a CPU
thread sweep, with CPU/GPU profiling for every test. The current instruction defers the full
translation-quality study otherwise required by P1.1 before a model/prompt change. This task
uses basic output and document-preservation checks; it does not claim measured quality superiority.
Existing SMALL-100 configurations remain available.

## Execution

1. Reuse installed SMALL-100 CT2/OpenVINO artifacts, HY-MT1.5-1.8B Q8_0/Q4_K_M GGUFs and
   llama.cpp CPU/Vulkan binaries. Record versions, artifact identity, power state and settings.
2. Profile each fresh-process case: loading, warmup and repeated inference separately. Record
   process-tree CPU time/utilization, system per-core load, working set, PID-attributed GPU
   engine counters and GPU memory. Missing telemetry is unavailable, never a fabricated zero.
3. Run serially against a fixed mixed-length Chinese-to-English sample. Sweep CT2 threads
   2/4/6/8/12/16; compare OpenVINO CPU/Arc and HY-MT CPU/Arc. Hold decoding constant within
   each comparison. Screen first, repeat finalists and test batch/concurrency separately.
4. Integrate HY-MT through its own plain-text prompting protocol behind the existing LLM
   configuration and TranslationEngine interface. An explicitly configured loopback llama-server
   is administrator-managed. Its model memory/lifecycle is external to the in-process MT LRU.
   It is not discovered through Davy, is never an automatic fallback, and reports its configured
   execution location. Record a deployment revision for weights/runtime/settings identity.
5. Integrate OpenVINO into production only if the experiment establishes useful performance
   and a robust compatible runtime. Otherwise retain the measured experiment and CT2 path.
6. Exercise real HY-MT document translation and configured service selection. Check nonempty
   outputs, no output-limit truncation, preserved document structure and tagged text handling.
7. Run the six repository checks and a focused independent review. Publish measured results,
   chosen settings and remaining limitations. Do not conflate smoke samples with a quality study.

## Implementation contract

Core owns model prompting, response validation and output identity. Apps own configuration.
Add an explicit HY-MT protocol to LlmEngineConfig; retain existing JSON-batch behavior by
default. HY-MT sends one segment per request, preserves order under bounded concurrency,
rejects truncated/malformed responses and uses the existing document pipeline. Configured
translators expose only safe ID/label/location metadata. CLI settings can select this protocol.
No new translation mode, global model pool, automatic download or desktop installer is introduced.

Raw benchmark inputs/outputs, samples and generated documents live in ignored
`data/experiments/laptop-mt/`. Experiment scripts and aggregate evidence live under
`docs/experiments/laptop-mt/`. Existing unrelated in-progress workspace changes are preserved.

## Execution outcome

Twenty representative configurations completed with per-phase CPU/GPU/memory profiles.
CTranslate2 remains the SMALL-100 runtime; 2-4 CPU threads are the measured starting range.
OpenVINO Arc worked but was slower and larger than CT2, so it remains experimental.
HY-MT1.5-1.8B Q8_0 uses llama.cpp Vulkan with four generation/prompt threads and four slots.
Its production adapter passed both marker directions, all five document formats, and a real
HTTP/worker job with verified download hashes. Existing fit/unsupported-content diagnostics
remain visible in reports; this is not a translation accuracy study or a layout perfection claim.

The live website exposes `hy-mt-local`, retains its SMALL-100 default and existing Davy entries,
and uses the separately running loopback model server. Prompt v2 fixes instruction echo found
by real-model acceptance, with regression tests and independent review approval.

## Owner-requested lifecycle extension

Profile a real 13-slide PowerPoint through upload, extraction, translation, offline fit v2,
publication/download and asynchronous LibreOffice previews. Compare HY-MT Q8 Vulkan with
SMALL-100 beam 4 using identical source bytes, four CPU threads and serial jobs. Measure
three standard-fit repetitions per model (first plus two warm), and one thorough-fit sample
per model. Preserve per-stage CPU/GPU/memory traces and output integrity evidence. Report
startup separately, account for HY eager versus CT2 lazy loading, and avoid adding nested
rendered-fit timings twice. Evidence: [lifecycle report](../../experiments/laptop-mt/LIFECYCLE.md).
