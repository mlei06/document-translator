# ADR-005: Translation Quality Evaluation

## Status

Accepted (2026-09-26)

## Context

The system has two translation modes (LLM and MT), and several decisions depend on measuring translation quality: which local MT model to use, which LLM prompt to use, and whether a change made translation better or worse. The README leaves the quality bar and its measurement open.

Quality could be evaluated at three levels: the translation engine on clean text, the full document pipeline against reference documents, and human review. This ADR evaluates the engine only.

## Options Considered

### Scope

- **Engine benchmark only.** Translate a fixed set of parallel sentences through each engine and score against reference translations. Cheap to build from public data, repeatable, and answers the model and prompt questions directly.
- **Plus document-level scoring.** Score translated documents per text container against reference translated documents. Catches quality lost to how the pipeline splits text, but needs reference translations of real documents, which do not exist yet.
- **Plus human review.** The ground truth, but needs bilingual reviewers for each language on an ongoing basis.

### Metrics

- **COMET** (`Unbabel/wmt22-comet-da`): neural, reference-based; the current standard with the best correlation to human judgment. Apache 2.0, runs locally.
- **chrF**: character n-gram overlap. Deterministic, fast, and works on Chinese and Japanese without word segmentation.
- **BLEU**: familiar, but word-based; needs language-specific tokenizers for Chinese and Japanese and correlates worse with human judgment than either option above.
- **Reference-free COMET** (CometKiwi, XCOMET): non-commercial licenses (CC BY-NC-SA), so not usable for company work.
- **LLM-as-judge**: the only LLM currently known on the internal server is Gemma, which is also the LLM mode's translator, so it would be judging its own output.

## Decision

Evaluate translation engines with a benchmark of parallel sentences, scored by COMET (primary) and chrF (secondary). Document-level scoring and human review are out of scope.

### Benchmark data

| Set | Content | Directions | Storage |
|-----|---------|------------|---------|
| FLORES+ (`devtest` split) | ~1,000 general-domain sentences, professionally translated into all four languages | All 12 | Downloaded by a script into the local data directory; not committed |
| Domain set | Technical and business sentences representative of company documents, with reference translations | As available, Chinese -> English first | Local data directory, listed in a manifest; never committed (may be confidential) |

The domain set exists because FLORES+ is general-domain text that LLMs have likely seen in training, which can inflate LLM mode scores. Until domain references exist, the benchmark runs on FLORES+ alone and reports that limitation with every result.

Languages map to FLORES+ codes: Chinese `cmn_Hans`, English `eng_Latn`, Japanese `jpn_Jpan`, Spanish `spa_Latn`.

### Running the benchmark

- The benchmark runs through the core's public API, like any other surface. The core exposes a text-level translation function (texts, source language, target language, mode, config) for this purpose.
- Runs are on demand, not in CI: they need the LLM server and the COMET model.
- Translation settings are deterministic for evaluation (e.g. temperature 0 in LLM mode), so reruns are comparable.
- Each run records: engine and mode, model name, prompt version, engine config, git commit, date, dataset and version, and per-direction COMET and chrF.

### Results and comparison

- Full run output, including per-segment translations, is written to the local data directory, never committed (domain set output may be confidential).
- Aggregate scores for the accepted baseline of each mode are committed as JSON in `apps/eval/baselines/`. These contain no document or sentence content.
- Comparing two runs uses paired bootstrap resampling per direction, so small differences within noise are reported as not significant rather than as wins or regressions.
- Chinese -> English is the deciding direction. A change that significantly lowers Chinese -> English COMET is a regression regardless of other directions.
- Absolute quality thresholds are set from the first baseline run, not guessed in advance, and recorded in the baselines.

### Location

A separate distribution, `apps/eval` (`doctranslator_eval`), depending on the core plus `unbabel-comet` and `sacrebleu`. Its heavy dependencies (COMET pulls in PyTorch and a ~2 GB model) stay out of the core, CLI, and server.

## Consequences

- Choosing the MT model, choosing or changing the LLM prompt, and comparing LLM mode against MT mode are all decided by benchmark results.
- The core's public API gains a text-level translation function. It is part of the public API, not an eval-only backdoor.
- Quality lost in the document pipeline (text split across formatting runs, lost context) is not measured. Pipeline correctness (no dropped text, preserved formatting, preserved numbers and formulas) is covered by ordinary tests, not by this benchmark.
- Scores for Japanese and Spanish directions rest on automated metrics alone, with no human calibration.
- Downloading FLORES+ requires accepting its terms on Hugging Face (CC BY-SA 4.0).
- Building the domain set requires sourcing technical sentences with trustworthy reference translations. Until then, LLM mode results may look better than they are on real documents.
