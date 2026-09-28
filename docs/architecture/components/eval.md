# Component: Eval

Status: implemented in P1 (2026-09-27). Baselines are committed by P1 step 11.

## Purpose

`doctranslator_eval` (`apps/eval`) measures translation quality: it translates a fixed set of parallel sentences through the core's public API and scores the output with COMET and chrF against reference translations ([ADR-005](../../decisions/ADR-005-translation-quality-evaluation.md)). It is a development tool, not a user-facing surface.

## Responsibilities

- Download FLORES+ at a pinned revision and load domain sets.
- Run a benchmark for one engine configuration over any subset of the 12 directions, recording everything needed to reproduce and interpret it.
- Score runs: COMET per segment and chrF per direction.
- Compare two runs or baselines with a paired bootstrap, and flag a zh-en regression.
- Write committed baselines that contain scores and segment ids, never text.

## Boundaries

This component owns:
- Benchmark datasets, run directories, scoring, comparison, and baselines.
- Its own configuration loading (environment, `.env`, OS vault).

This component does NOT own:
- Translation. It calls `Translator` from the core's public API only (ADR-003 rule 2).
- COMET itself, which runs in an isolated environment (below).

## Interfaces

### Command line

`uv run doctranslator-eval <command>`, from the repository root (paths and `.env` resolve from there).

| Command | Behavior |
|---------|----------|
| `download-flores` | Download FLORES+ devtest for the four languages at the pinned revision; skip files already present. |
| `run --mode llm\|mt [--dataset flores\|domain:<path>] [--directions all\|zh-en,...] [--limit N]` | Run a benchmark and print a summary. MT mode also takes `--mt-model-dir PATH` (required), `--mt-family small100`, `--device`, `--compute-type`, `--beam-size`, `--cpu-threads`. |
| `score <run_dir>` | Score a translated run again, e.g. after a COMET failure, without translating again. |
| `compare <a> <b>` | Compare `b` against `a`; each is a run directory or a baseline file. Exit code 1 on a zh-en regression. |
| `baseline set <run_dir> [--baselines-dir DIR]` | Write `apps/eval/baselines/<mode>.json` from a complete run made from a clean working tree without `--limit`. |

Expected failures (missing settings or data, COMET failure, unsuitable baseline run, engine errors) print one `error:` line and exit with code 2.

### Configuration

`EvalSettings` (pydantic-settings), prefix `DOCTRANSLATOR_`, reading the environment and then `.env`; empty values count as unset.

| Variable | Use |
|----------|-----|
| `DOCTRANSLATOR_LLM_BASE_URL`, `DOCTRANSLATOR_LLM_MODEL` | LLM mode. |
| `DOCTRANSLATOR_LLM_API_KEY` | LLM mode. Falls back to the OS vault: service `doctranslator`, username `DOCTRANSLATOR_LLM_API_KEY`. |
| `DOCTRANSLATOR_DATA_DIR` | Data directory (default `data`). |
| `HF_TOKEN` | Downloading FLORES+ (gated dataset). |

## Data Model

### Datasets

- FLORES+ `devtest` at revision `5fec6c13f9e5a4db2f745d4ec0d7c9721ddc4f06`, in `<data_dir>/benchmarks/flores_plus/<revision>/devtest/<code>.jsonl` (`cmn_Hans`, `eng_Latn`, `jpn_Jpan`, `spa_Latn`). Rows are joined across languages by `id`; ids must match exactly.
- Domain sets: JSONL rows `{"id", "source_lang", "target_lang", "source", "reference"}`, filtered by direction; duplicate ids are rejected. Identified in manifests by the file's sha256.

### Run directory

`<data_dir>/eval/runs/<run_id>/`, with `run_id = <UTC yyyymmddTHHMMSSZ>-<mode>-<model slug>`:

| File | Content |
|------|---------|
| `manifest.json` | Run id, time, status, error, git commit and dirty flag, dataset and revision, `EngineInfo`, engine configuration (never the API key), hardware, directions, limit, COMET settings, chrF signature. |
| `translations/<direction>.jsonl` | `id`, `source`, `reference`, `hypothesis` per segment. |
| `timing.json` | Per direction: seconds, segments, segments per second, peak resident memory (MB). |
| `scores.json` | Per direction: `n`, mean COMET, corpus chrF. |
| `segment_scores/<direction>.json` | `{segment id: COMET}`. |

Status moves `running` -> `translated` -> `complete`. A translation failure sets `failed` and keeps completed directions. A scoring failure leaves the run `translated` with the error recorded; `score` retries it.

### Baselines

`apps/eval/baselines/<mode>.json` (committed): run id, time, dataset, `EngineInfo`, engine configuration, hardware, COMET settings, chrF signature, per-direction `n`/COMET/chrF, and per-segment COMET keyed by segment id. No source, reference, or hypothesis text (tested).

## Internal Architecture

| Module | Role |
|--------|------|
| `cli.py` | Typer commands; `main()` sets UTF-8 console output and logging, then runs the app. |
| `settings.py` | `EvalSettings` and the vault fallback. |
| `datasets.py` | `Direction`, `ALL_DIRECTIONS` (zh-en first), `Segment`, FLORES+ download and loading, domain sets. |
| `runs.py` | Run directory models and file I/O, run ids, git state. |
| `hardware.py` | `HardwareInfo` (OS, CPU name, cores, RAM, engine device) and `PeakMemory`. |
| `runner.py` | `run_benchmark` (one `Translator` for the whole run), `score_run`, summary table. |
| `scoring.py` | chrF (sacrebleu defaults) and the COMET adapter. |
| `compare.py` | Paired bootstrap comparison and its table. |
| `baselines.py` | Baseline creation, validation, and loading. |

### COMET isolation

COMET (`unbabel-comet` 2.2.7, model `Unbabel/wmt22-comet-da`) needs PyTorch and an older Python, so it never enters the workspace. `scoring.comet` writes sources, references, and hypotheses to a temporary directory, one segment per line with line breaks inside segments replaced by spaces, and runs `uv tool run --python 3.11 --from unbabel-comet==2.2.7 --with "setuptools<81" comet-score ... --gpus 0 --quiet --only_system --to_json` (COMET 2.2.7's torchmetrics imports `pkg_resources`, which setuptools 81 removed; its pinned `jsonargparse` 3.13.1 calls a private argparse method whose signature changed in recent Python 3.12 patch releases, so it runs on 3.11). All directions of a run are scored in one call, so the model loads once. A count mismatch in the output is an error. The first call downloads PyTorch and the model (about 2.5 GB) into the uv and Hugging Face caches.

### Comparison

For each direction present in both inputs, over the segment ids they share: `delta = mean(b) - mean(a)` of per-segment COMET, with a 95% percentile interval from 1,000 paired bootstrap resamples (`random.Random(0)`). The verdict is `better` if the interval is above zero, `worse` if below, otherwise no significant difference. chrF deltas are reported without a test. A regression is a `worse` zh-en.

## Dependencies

Depends on:
- `doctranslator-core[mt]` (public API only), `pydantic-settings`, `keyring`, `huggingface-hub`, `sacrebleu`, `psutil`, `typer`.
- `uv` on PATH for COMET; network access for the first COMET run and for FLORES+.

Used by: developers, and P1 step 11 (baselines).

## Security Considerations

- The LLM API key is never written to a run directory or baseline (tested); the manifest stores the engine configuration without it.
- Baselines are committed and contain no dataset text. Run directories contain text and stay in the gitignored data directory, since domain sets may be confidential.

## Observability

Commands log at `INFO` to stderr: run start, and per direction the segment count and time. HTTP request logging from `httpx` is limited to warnings.

## Testing Strategy

All tests run without network, models, or COMET: the runner uses a fake `Translator` and a stubbed COMET, the COMET adapter uses a fake `comet-score` that writes the verified output shape, and settings tests isolate the environment, `.env`, and the OS vault.
