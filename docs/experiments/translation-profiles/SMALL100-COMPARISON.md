# Same-host SMALL-100 comparison

Requested 2026-09-28, resumed 2026-09-29. This is a limited comparison of usable
CPU configurations, not the full multilingual production baseline.

## Protocol

- Host: Windows, Intel Core Ultra 7 265K (20 cores/logical processors).
- First 100 Chinese-to-English FLORES+ devtest sentences, revision
  `5fec6c13f9e5a4db2f745d4ec0d7c9721ddc4f06`; identical sources/references and order.
- Two complete passes per configuration. Warm-up uses the last dataset sentence,
  outside the measured prefix; model loading and scoring are excluded from timing.
- CPU only, eight configured inference threads. One model process at a time.
  No builds, conversions or scoring during measured runs. Downloads may occur.
  Ordinary desktop background processes are not stopped or CPU-affinity pinned.
- SMALL-100: CTranslate2 4.8.2 int8, batch 32, beam4 and beam1 (greedy).
- HY-MT2 1.8B Q8 and AngelSlim2-bit: model-card sampling0.7/0.6/20/repeat1.05,
  seed0, output4096; one HTTP request slot, no prompt cache, context8192.
- TranslateGemma4B Q4: official raw prompt, greedy, output2048, one HTTP request
  slot, no prompt cache, context8192; CPU runtime because GPU validation failed.
- Report median workflow throughput and each pass's chrF. Batch32 MT versus
  single-slot LLM is an intentional deployment comparison, not matched decoding
  work, per-sentence latency, or each architecture's maximum tuned throughput.
- COMET is scored separately after all timed inference; model/version/revision
  and raw scores are retained. Repeated outputs from one source are not independent
  test examples. The corpus has 100 unique sources, not 200.

## SMALL-100 setup

Used existing `scripts/convert_mt_model.py` without changing production code:
SMALL-100 revision `8ab680e26a596d2e3d2d2d17ae0f68df1037328c`, M2M100 tokenizer
revision `55c2e61bbf05dfb8d7abccdc3fae6fc8512fd636`, CTranslate2 4.8.2,
Transformers5.17.0. Converted model and conversion.json are under
`data/models/alirezamsh--small100-ct2-int8/`.

Configs: `data/local-models/small100-beam4.env` and `small100-greedy.env` explicitly
select CPU, int8 and eight threads. The repository's existing real integration test
first selected CUDA automatically and failed due to absent cublas64_12.dll; the
comparison configs avoid automatic device selection. CPU test outcome recorded
with final results.

Reproduce one SMALL-100 run from the repository root:

```powershell
uv run python docs/experiments/translation-profiles/compare_local.py --config data/local-models/small100-beam4.env --label small100-beam4 --output data/experiments/small100-comparison/new-small100-beam4.json
```

For each LLM, start its launcher with `-Threads 8 -NoPromptCache`, use that
model's generated config with the same comparison script, and stop it before the
next model. The script refuses to overwrite prior evidence.

Raw output: `data/experiments/small100-comparison/`. A file is complete only when
`complete` is true and both passes contain100 aligned, nonblank hypotheses.
These local, ignored files include text; public summaries should omit credentials.

## Interpretation limits

Scores apply to this Chinese-to-English prefix, not other language pairs, domains,
or formatted documents. Vendor sampling and beam/greedy decoding are deliberate
model-specific settings. Two timing passes do not establish statistical confidence
in throughput. SMALL-100 beam4 completed before the interruption; later runs resumed
the next day on the same host. First-prefix sampling is not a randomized corpus.
No accepted baseline is overwritten, and no production model is replaced.

## Completed setup checks

All six repository checks passed after setup: locked dependency sync, formatting,
lint, type checking,13 import contracts and242 unit/contract tests. The real
SMALL-100 integration test passed on CPU (one MT test passed; LLM integration
was deselected). Use an explicit CPU configuration on this host: automatic device
selection otherwise finds the NVIDIA card but cannot load CTranslate2's CUDA12
cuBLAS dependency. No GPU speed is claimed for SMALL-100.

A sixth configuration, `small100-beam4-singlebatch`, uses `--mt-batch-size 1` as a
control for batching. It still submits the same full text list through Translator,
but CTranslate2's maximum inference batch is one. All twelve timed passes completed;
all six configurations returned identical hypotheses between their two passes.
The repeated timing measurements therefore do not add independent quality samples.

## Results

| Model / configuration | Sentences/sec (median) | Observed speed range | chrF | COMET |
|---|---:|---:|---:|---:|
| SMALL-100 int8, beam 4, batch 32 | 7.99 | 7.90–8.08 | 50.72 | 0.8173 |
| SMALL-100 int8, greedy, batch 32 | 25.26 | 25.13–25.39 | 50.37 | 0.8088 |
| SMALL-100 int8, beam 4, batch 1 | 3.15 | 3.14–3.16 | 50.90 | 0.8162 |
| HY-MT2 1.8B Q8 | 0.45 | 0.45–0.45 | 58.39 | 0.8718 |
| HY-MT2 1.8B AngelSlim 2-bit | 0.32 | 0.31–0.32 | 58.46 | 0.8670 |
| TranslateGemma 4B Q4 | 0.34 | 0.34–0.35 | 56.77 | 0.8668 |

COMET 2.2.7 used the pinned wmt22-comet-da checkpoint; all three LLM variants exceeded SMALL-100 beam4 on this selected prefix. Full metrics and paired bootstrap evidence are in workspace outputs/small100-comparison-metrics.json. These results do not replace the pending full multilingual baseline.
