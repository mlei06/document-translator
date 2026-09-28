# P1 Translation Engines and Benchmark

Board: [Feature #9009](https://chintand.visualstudio.com/AI%20Projects/_workitems/edit/9009)

## Objective

Translate plain text in both LLM and MT modes across all 12 directions between Chinese (Simplified), English, Japanese, and Spanish through the core's public API, and measure each mode's quality with the benchmark defined in [ADR-005](../decisions/ADR-005-translation-quality-evaluation.md). The local MT model is SMALL-100 ([ADR-006](../decisions/ADR-006-mt-model-selection.md)); commit quality baselines for both modes.

## Relevant Architecture

- [Core component](../Architecture.md#core-api-reference) - public API, types, config, engine interface, error handling. **This plan implements that document; read it first.**
- [ADR-003](../decisions/ADR-003-source-structure.md) - module locations and dependency rules
- [ADR-005](../decisions/ADR-005-translation-quality-evaluation.md) - benchmark method, COMET isolation
- [P0 plan](P0-project-foundation.md) - tooling this phase builds on

## Dependencies

- P0 (done).
- **LLM server reachable** (company VPN) for steps 1, 11 (LLM run), and the LLM integration test. Everything else can be built and tested off the VPN.
- `.env` at the repository root with `DOCTRANSLATOR_LLM_BASE_URL`, `DOCTRANSLATOR_LLM_API_KEY`, `DOCTRANSLATOR_LLM_MODEL`, and `HF_TOKEN` (present on the development laptop; never committed). The API key is also stored in Windows Credential Manager under service `doctranslator`, username `DOCTRANSLATOR_LLM_API_KEY`.
- FLORES+ terms accepted on the Hugging Face account behind `HF_TOKEN` (done; verified by downloading all four devtest files).

## Decisions Pinned by This Plan

Verified 2026-09-26 unless noted.

| Decision | Choice | Reason |
|----------|--------|--------|
| HTTP client | `httpx` (sync `Client`, thread pool for concurrency) | Typed, supports `MockTransport` for tests without an extra library. The core API is synchronous. |
| TLS trust | `truststore.SSLContext` passed as `verify=` | Uses the OS certificate store, where the company's internal CA lives; verification is never disabled. |
| LLM protocol | `POST {base_url}/chat/completions`, JSON segments in, JSON translations out | OpenAI-compatible; see Core component, LLM engine. |
| MT model | **SMALL-100** (`alirezamsh/small100`, MIT), CTranslate2 int8 | [ADR-006](../decisions/ADR-006-mt-model-selection.md): the only candidate meeting the throughput bar on the CPU-only laptop with beam search and an unrestricted license. The candidates and exclusions are recorded there. |
| MT runtime | **CTranslate2** with **SentencePiece** used directly; no `transformers` or PyTorch at runtime | Fast int8 CPU inference now; CUDA later on the GPU laptop with a config change. SMALL-100's SentencePiece model is identical to M2M100's, and its language convention is one token, so no tokenizer framework is needed (verified 2026-09-27 with `ctranslate2` 4.8.2 and `sentencepiece` 0.2.2 on Python 3.14). |
| MT model conversion | `ct2-transformers-converter`, run by `scripts/convert_mt_model.py` in a throwaway `uv` environment that includes PyTorch | Keeps PyTorch out of `uv.lock` and every installed package. |
| Eval CLI framework | **Typer** | Typed, standard. P2 uses the same for the product CLI. |
| Eval settings | `pydantic-settings`, prefix `DOCTRANSLATOR_`, reads `.env`; API key falls back to the OS vault via `keyring` | Environment first, vault second. |
| chrF | `sacrebleu` `CHRF()` defaults (char n-gram 6, word n-gram 0, beta 2), corpus level | Standard signature, recorded with every run. |
| COMET | `uv tool run --python 3.11 --from unbabel-comet==2.2.7 --with "setuptools<81" comet-score ... --model Unbabel/wmt22-comet-da --gpus 0 --quiet --only_system --to_json <file>` | ADR-005 isolation. Output JSON verified: `{<hypothesis file path>: [{"src","mt","ref","COMET"}, ...]}` in input order. `setuptools<81` because COMET 2.2.7 pulls a torchmetrics that imports `pkg_resources`, removed in setuptools 81 (without it `comet-score` fails at import). Python 3.11 because COMET 2.2.7 pins `jsonargparse==3.13.1`, which calls argparse's private `_parse_known_args` with its old signature; recent CPython 3.12 patch releases added an `intermixed` parameter, so `comet-score` fails at argument parsing on 3.12 (both found 2026-09-27). |
| FLORES+ revision | `openlanguagedata/flores_plus` at `5fec6c13f9e5a4db2f745d4ec0d7c9721ddc4f06`, split `devtest` | 1,012 rows per language, aligned by `id`, text in `text` (verified). |
| Significance test | Paired bootstrap on per-segment COMET, 1,000 resamples, seed 0, 95% interval | ADR-005. |
| Test selection | pytest marker `integration` for tests needing the LLM server, a real model, or network; deselected by default | CI never needs the VPN, models, or Hugging Face. |

## Target Layout

New or changed files (docs listed under step 12):

```text
pyproject.toml                               # pytest markers, TID251 banned API
.importlinter                                # new engine-library contracts, rule 1 additions
.env.example                                 # already has HF_TOKEN
scripts/convert_mt_model.py                  # new
packages/core/
  pyproject.toml                             # dependencies, [mt] extra
  src/doctranslator_core/
    __init__.py                              # public API exports
    types.py
    config.py
    translator.py                            # new
    engines/__init__.py
    engines/base.py                          # new
    engines/llm.py                           # new
    engines/llm_prompts.py                   # new
    engines/mt.py                            # new
  tests/
    test_package.py                          # add new modules
    test_types_config.py
    test_translator.py
    test_engines_llm.py
    test_engines_mt.py
    test_integration_engines.py              # marked integration
apps/eval/
  pyproject.toml                             # dependencies, console script
  src/doctranslator_eval/
    __init__.py
    cli.py
    settings.py
    datasets.py
    runs.py
    runner.py
    scoring.py
    compare.py
    baselines.py
    hardware.py
  baselines/                                 # committed; created in step 11
  tests/
    test_package.py
    test_settings.py
    test_datasets.py
    test_runner.py
    test_scoring.py
    test_compare.py
    test_baselines.py
```

## Implementation Steps

### 1. Connectivity check (on VPN; blocks only LLM-dependent steps)

From the repository root, with the key taken from `.env` and never printed:

```powershell
uv run --no-project --with httpx --with truststore --with python-dotenv python -c "import os, ssl, httpx, truststore, dotenv; dotenv.load_dotenv(); r = httpx.get(os.environ['DOCTRANSLATOR_LLM_BASE_URL'].rstrip('/') + '/models', headers={'Authorization': 'Bearer ' + os.environ['DOCTRANSLATOR_LLM_API_KEY']}, verify=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT), timeout=30); print(r.status_code, [m['id'] for m in r.json().get('data', [])])"
```

Expected: `200` and a list containing the configured model. Then send one chat completion with `response_format: {"type": "json_object"}` and a two-segment request (same shape as step 6). Record in the pull request:

- whether `json_object` is accepted (if rejected with HTTP 400, set `json_mode` default to `False` in `LlmEngineConfig` and note why in `config.py`);
- round-trip latency for a 16-segment request.

If `401/403`: the key is wrong or revoked; stop and ask the owner. If DNS fails: not on the VPN.

**Result (2026-09-27, on the VPN):** `GET /models` returns 200 and lists `gemma-4-31b-it`. `json_object` is accepted: with it, Gemma returns bare JSON; without it, JSON wrapped in a Markdown code fence (handled by the parser either way). `json_mode` stays `True`. Latency: about 0.4 s for a trivial request, 1.6 s for one 16-segment request. Through `Translator` with default settings, 300 FLORES+ zh-en segments took 17.7 s (16.9 segments/s) with no retries or split-and-retry recoveries. Both integration tests pass.

### 2. Dependencies and tooling

`packages/core/pyproject.toml`:

```toml
dependencies = ["httpx", "pydantic", "truststore"]

[project.optional-dependencies]
mt = ["ctranslate2", "sentencepiece"]
```

`apps/eval/pyproject.toml`:

```toml
dependencies = [
    "doctranslator-core[mt]",
    "huggingface-hub",
    "keyring",
    "psutil",
    "pydantic-settings",
    "sacrebleu",
    "typer",
]

[project.scripts]
doctranslator-eval = "doctranslator_eval.cli:main"
```

Root `pyproject.toml` changes:

```toml
[tool.ruff.lint]
select = [ ..., "TID" ]   # add to the existing list

[tool.ruff.lint.flake8-tidy-imports.banned-api]
"os.environ".msg = "The core never reads the environment (ADR-003). Apps pass configuration in."
"os.getenv".msg = "The core never reads the environment (ADR-003). Apps pass configuration in."

[tool.ruff.lint.per-file-ignores]
"**/tests/**" = ["S101"]
"apps/**" = ["TID251"]      # apps load configuration; only the core is banned
"scripts/**" = ["TID251"]

[tool.pytest.ini_options]
addopts = ["--import-mode=importlib", "-ra", "--strict-markers", "--strict-config", "-m", "not integration"]
markers = ["integration: needs the LLM server, a downloaded model, or network access; run with -m integration"]
```

No change to the sync commands is needed: `apps/eval` depends on `doctranslator-core[mt]` and the workspace root depends on `apps/eval`, so `uv sync --all-packages` (local and CI) already installs `ctranslate2` and `sentencepiece`, and Pyright can resolve them. Confirm after syncing with `uv pip show ctranslate2`.

Run `uv lock` and commit `uv.lock`.

### 3. Import contracts

In `.importlinter`, extend the rule 1 `forbidden_modules` list with `pydantic_settings`, `keyring`, `dotenv`, `psutil`, and `sacrebleu`: the core never loads configuration or does evaluation.

Append engine-library containment contracts (ADR-003 core rules: each engine's libraries stay in that engine). These are `protected` contracts, so add each in the same change that first imports the library, or `lint-imports` fails with "not present in the graph":

```ini
[importlinter:contract:llm-libraries-contained]
name = ADR-003 core rule: HTTP and TLS libraries only in engines.llm (apps may use them)
type = protected
protected_modules =
    httpx
    truststore
allowed_importers =
    doctranslator_core.engines.llm
    doctranslator_cli
    doctranslator_server
    doctranslator_eval

[importlinter:contract:mt-libraries-contained]
name = ADR-003 core rule: MT runtime libraries only in engines.mt
type = protected
protected_modules =
    ctranslate2
    sentencepiece
allowed_importers = doctranslator_core.engines.mt
```

### 4. Types and configuration

Implement `types.py` and `config.py` exactly as specified in the core section of `docs/Architecture.md` (tables in Interfaces). Details:

- Enums are `enum.StrEnum`. Models use `pydantic.BaseModel` with `model_config = ConfigDict(frozen=True, extra="forbid")`.
- `EngineConfig` is `Annotated[LlmEngineConfig | MtEngineConfig, Field(discriminator="mode")]`, so apps can validate a dict into the right type with `TypeAdapter(EngineConfig)`.
- Validation: `batch_size`, `max_concurrency`, `max_batch_size`, `beam_size` are `>= 1`; `max_retries >= 0`; `timeout_s > 0`; `temperature` in `[0, 2]`; `cpu_threads >= 0`.
- A module-level `LANGUAGE_NAMES: dict[Language, str]` in `types.py`: `ZH: "Simplified Chinese"`, `EN: "English"`, `JA: "Japanese"`, `ES: "Spanish"` (used by prompts and reports).

`__init__.py` re-exports and lists in `__all__`: `Translator`, `EngineConfig`, `LlmEngineConfig`, `MtEngineConfig`.

### 5. Engine interface and `Translator`

`engines/base.py`: `TranslationEngine` exactly as in the core section of `docs/Architecture.md`.

`engines/__init__.py`: `create_engine(config: EngineConfig) -> TranslationEngine`, a `match` on `config.mode` that imports `engines.llm` or `engines.mt` inside the branch (so MT libraries load only for MT).

`translator.py`: `Translator` implementing the public guarantees:

1. Validate `source != target` (`ValueError`).
2. For each input, split into `(leading_ws, core_text, trailing_ws)` using `str` whitespace semantics. Empty `core_text` is passed through unchanged.
3. Collect unique `core_text` values in first-seen order; call `engine.translate_batch(unique, source, target)` once.
4. Verify the engine returned exactly `len(unique)` strings; otherwise raise `EngineResponseError` (defensive; engines already guarantee it).
5. Rebuild outputs as `leading_ws + translation + trailing_ws`, in input order.
6. `__enter__` returns `self`; `__exit__` and `close()` call `engine.close()`; calling `translate_texts` after `close()` raises `RuntimeError`.
7. `engine_info` returns `engine.info`.

Log one `DEBUG` line per call: counts of inputs, unique texts, and pass-throughs, and elapsed time. Never log text.

### 6. LLM engine

`engines/llm_prompts.py`:

```python
PROMPT_VERSION = "llm-translate-v1"

SYSTEM_TEMPLATE = """\
You are a professional translator. Translate each segment from {source} to {target}.

Rules:
- Translate every segment completely. Never merge, split, omit, or reorder segments.
- Return exactly one translation per input segment, in the same order.
- Keep numbers, units, URLs, email addresses, file paths, code, product names, and placeholders \
such as {{0}}, %s, or <tag> exactly as written.
- Keep line breaks that appear inside a segment.
- Output only the translation: no notes, explanations, or surrounding quotes.

Respond with a JSON object of the form {{"translations": ["...", "..."]}}."""


def system_prompt(source: Language, target: Language) -> str:
    return SYSTEM_TEMPLATE.format(source=LANGUAGE_NAMES[source], target=LANGUAGE_NAMES[target])


def user_message(segments: Sequence[str]) -> str:
    return json.dumps({"segments": list(segments)}, ensure_ascii=False)
```

`engines/llm.py`, class `LlmEngine(TranslationEngine)`:

- Constructor takes `config: LlmEngineConfig` and an optional keyword `transport: httpx.BaseTransport | None = None` (tests inject `httpx.MockTransport`; production passes nothing). Creates one `httpx.Client(base_url=str(config.base_url), headers={"Authorization": f"Bearer {key}"}, timeout=config.timeout_s, verify=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT), transport=transport)`.
- `info`: `EngineInfo(mode=LLM, model=config.model, details={"prompt_version": PROMPT_VERSION, "temperature": str(config.temperature)})`.
- `translate_batch`: chunk into `batch_size`; run chunks through `concurrent.futures.ThreadPoolExecutor(max_workers=config.max_concurrency)`; collect results in chunk order. The first exception from any chunk cancels the rest and propagates.
- Per chunk, `_translate_chunk(chunk)`:
  1. Build the body: `{"model": ..., "temperature": ..., "messages": [{"role": "system", ...}, {"role": "user", ...}]}` plus `"response_format": {"type": "json_object"}` when `json_mode`.
  2. `_post_with_retries(body)` per the Error Handling table in the core section of `docs/Architecture.md`. Backoff: `min(2 ** attempt, 8) * uniform(0.75, 1.25)` seconds; `Retry-After` (seconds form) overrides, capped at 30. Use an injectable `sleep` callable (default `time.sleep`) so tests don't wait.
  3. Parse `choices[0].message.content`: strip whitespace; if it starts with a Markdown code fence, remove the opening fence line (with optional `json` tag) and the closing fence; `json.loads`; require a dict with key `translations` holding a list of `str` of the same length as `chunk`.
  4. On parse or count failure: if `len(chunk) > 1`, split in half and recurse on each half, logging a `WARNING` (counts only); if `len(chunk) == 1`, raise `EngineResponseError("unusable response for a single segment")`.
- `close()` closes the client.

Pyright strict: parse JSON into `object` and narrow with `isinstance` checks; no `Any` leaks.

### 7. MT engine

`engines/mt.py`, class `MtEngine(TranslationEngine)`:

- Constructor: `MtEngine(config, *, runtime: MtRuntime | None = None)`. `MtRuntime` is a frozen dataclass holding the loaded translator, tokenizer, and resolved device; tests pass one built from fakes, production passes nothing and the model is loaded.
- Loading: lazy `import ctranslate2` and `import sentencepiece`. On `ImportError`, raise `EngineUnavailableError("MT mode requires the 'mt' extra: install doctranslator-core[mt]")`. `model_dir` must contain `model.bin` and `sentencepiece.bpe.model`; otherwise `EngineUnavailableError` naming the missing file. A load failure from either library is also `EngineUnavailableError`.
- Neither library ships complete type information. Private `Protocol`s describe exactly the surface used (`_Ct2Module` with `get_cuda_device_count` and `Translator`, `_Ct2Translator.translate_batch`, `_Ct2Result.hypotheses`, `_SentencePiece.encode`/`decode`), with one `cast` at load time and narrowly-scoped `# pyright: ignore[reportMissingTypeStubs]` on the imports. Everything after the cast is fully typed.
- Device: `auto` resolves to `"cuda"` if `get_cuda_device_count() > 0`, else `"cpu"`. Construct `ctranslate2.Translator(str(model_dir), device=..., compute_type=config.compute_type, intra_threads=config.cpu_threads)` and `sentencepiece.SentencePieceProcessor(model_file=str(model_dir / "sentencepiece.bpe.model"))`.
- SMALL-100 convention ([ADR-006](../decisions/ADR-006-mt-model-selection.md)): each source is `[f"__{target.value}__", *encode(text, out_type=str), "</s>"]`; no target prefix. The source language is not encoded.
- `translate_batch`: call `translate_batch(tokens, beam_size=config.beam_size, max_batch_size=config.max_batch_size)`, take `hypotheses[0]` of each result, drop special tokens (`<s>`, `</s>`, `<pad>`, `<unk>`) and language tokens (`__xx__`), decode with SentencePiece, strip.
- `info`: `EngineInfo(mode=MT, model=model_dir.name, details={"model_family": ..., "device": <resolved>, "compute_type": ..., "beam_size": ...})`.
- `close()` drops the runtime; later calls raise `RuntimeError`.

### 8. MT model conversion script

`scripts/convert_mt_model.py` converts SMALL-100 into `data/models/<name>/` (gitignored via `data/`). It is a development tool, not part of any package, and runs in a throwaway environment so PyTorch never enters the lockfile:

```powershell
uv run --no-project --python 3.14 --with "ctranslate2" --with "transformers[torch]>=5,<6" --with sentencepiece --with huggingface-hub `
  scripts/convert_mt_model.py --quantization int8
```

Behavior, following ADR-006:

- Downloads `config.json` and `model.safetensors` from `alirezamsh/small100`, and `sentencepiece.bpe.model`, `vocab.json`, and `tokenizer_config.json` from `facebook/m2m100_418M` (identical tokenizer files), into one temporary directory, and converts that directory with `ctranslate2.converters.TransformersConverter(<dir>, copy_files=["sentencepiece.bpe.model"]).convert(output_dir, quantization=...)`. The model repository's `tokenization_small100.py` is never downloaded or executed.
- Arguments: `--quantization` (default `int8`), `--output-root` (default `data/models`), `--force`.
- Output directory name: `alirezamsh--small100-ct2-<quantization>`.
- Refuses to overwrite an existing directory without `--force`.
- Writes `conversion.json` in the output directory: both repository IDs with their Hugging Face revision SHAs, quantization, CTranslate2 and transformers versions, UTC timestamp.
- Uses `HF_TOKEN` from the environment if set.

A model converted this way before the script existed is at `data/models/alirezamsh--small100-ct2-int8`. The script reproduces it byte for byte (`model.bin`, `sentencepiece.bpe.model`, `shared_vocabulary.json`, and `config.json` have identical sha256, verified 2026-09-27 with CTranslate2 4.8.2 and transformers 5.17.0), and the MT integration test passes on its output. Do not patch the converter if a future CTranslate2 release fails.

### 9. Eval app

All modules are fully typed (Pyright strict). Untyped third-party calls (`psutil`, `sacrebleu`) are wrapped in one function each, with narrowly-scoped ignores and explicit return types.

**`settings.py`** - `EvalSettings(BaseSettings)`:

```python
model_config = SettingsConfigDict(env_prefix="DOCTRANSLATOR_", env_file=".env", extra="ignore")
llm_base_url: HttpUrl | None = None
llm_api_key: SecretStr | None = None
llm_model: str | None = None
data_dir: Path = Path("data")
hf_token: SecretStr | None = Field(default=None, validation_alias="HF_TOKEN")
```

- `resolved_llm_api_key()`: `llm_api_key` if set, else `keyring.get_password("doctranslator", "DOCTRANSLATOR_LLM_API_KEY")`, else `None`.
- `llm_engine_config() -> LlmEngineConfig`: builds from the fields; raises a clear error naming the missing variables if URL, key, or model is absent.
- `.env` is read relative to the current directory; all commands are documented to run from the repository root.

**`datasets.py`**:

- `Segment` (frozen Pydantic): `id: str`, `source: str`, `reference: str`.
- `Direction` (frozen): `source: Language`, `target: Language`; `str()` renders `zh-en`; `ALL_DIRECTIONS`: the 12 ordered pairs, `zh-en` first.
- FLORES+: `FLORES_REPO = "openlanguagedata/flores_plus"`, `FLORES_REVISION = "5fec6c13f9e5a4db2f745d4ec0d7c9721ddc4f06"`, `FLORES_FILES = {ZH: "cmn_Hans", EN: "eng_Latn", JA: "jpn_Jpan", ES: "spa_Latn"}`.
- `download_flores(data_dir, token)`: downloads `devtest/<code>.jsonl` for the four languages at the pinned revision into `data_dir/benchmarks/flores_plus/<revision>/devtest/` using `huggingface_hub.hf_hub_download` (add `huggingface_hub` to eval dependencies). Skips files already present. Raises a clear error on `GatedRepoError` pointing to the dataset page.
- `load_flores(data_dir, direction) -> list[Segment]`: reads both language files, joins rows by `id`, fails if the id sets differ, returns segments sorted by integer id.
- `load_parallel_jsonl(path, direction) -> list[Segment]`: the domain set format, one JSON object per line: `{"id", "source_lang", "target_lang", "source", "reference"}`; keeps only rows matching `direction`; rejects duplicate ids.
- Datasets are addressed by name on the CLI: `flores` or `domain:<path>`.

**`runs.py`** - run directory format under `data_dir/eval/runs/<run_id>/`, with `run_id = <UTC yyyymmddTHHMMSSZ>-<mode>-<model slug>`:

| File | Content |
|------|---------|
| `manifest.json` | `RunManifest`: `run_id`, `created_at`, `git_commit`, `git_dirty`, `dataset` (name, revision or file hash), `engine_info`, `engine_config` (serialized with the API key excluded), `hardware`, `directions`, `limit`, `comet` (version, model, python), `chrf_signature` |
| `translations/<dir>.jsonl` | one line per segment: `id`, `source`, `reference`, `hypothesis` |
| `timing.json` | per direction: `seconds`, `segments`, `segments_per_second`; peak RSS of the process in MB |
| `scores.json` | per direction: `n`, `comet` (system mean), `chrf` (corpus) |
| `segment_scores/<dir>.json` | `{id: comet}` |

`git_commit` and `git_dirty` come from `git rev-parse HEAD` and `git status --porcelain` (subprocess). All JSON written UTF-8 with `ensure_ascii=False`, `indent=2`.

**`hardware.py`** - `collect_hardware() -> HardwareInfo`: OS and version (`platform`), CPU model string, logical and physical cores, total RAM in GB (`psutil`), and the engine's resolved device from `EngineInfo.details`. `PeakMemory` context manager samples `psutil.Process().memory_info().rss` every 0.5 s on a daemon thread and reports the peak.

**`runner.py`** - `run_benchmark(data_dir, engine_config, dataset, directions, limit) -> RunDir`:

1. Load every direction's segments (first `limit` if set), so a missing dataset fails before any work.
2. Create one `Translator` for the whole run; create the run directory and write the manifest (status `running`).
3. Per direction: translate all sources in one `translate_texts` call inside a timer and `PeakMemory`, write `translations/<dir>.jsonl` and timing.
4. After all directions: status `translated`, then `score_run` (below), which writes `scores.json` and `segment_scores/` and sets status `complete`. The CLI prints a summary table.
5. A translation failure marks the run `failed` with the error message and keeps completed directions. A scoring failure leaves the run `translated` with the error recorded, so `score <run_dir>` can retry without translating again.

**`scoring.py`**:

- `chrf(hypotheses, references) -> float`: `sacrebleu.metrics.chrf.CHRF().corpus_score(hyps, [refs]).score`. `CHRF_SIGNATURE` from the metric's `get_signature()` after scoring once (sacrebleu completes the signature only after a score).
- `comet(sources, references, hypotheses: {label: list[str]}) -> {label: list[float]}`: all labelled hypothesis lists share sources and references. Writes `src.txt`, `ref.txt`, and one `hyp_<n>.txt` per label to a temporary directory, with every `\r` and `\n` in any text replaced by a space (COMET reads one segment per line; a newline would misalign every following segment). Runs the pinned `uv tool run ... comet-score` command with all hypothesis files in one call (one model load), `cwd` set to the temp directory so JSON keys are the bare file names, and returns per-segment `COMET` values in input order. Fails loudly if the JSON segment count differs from the input. `score_run` concatenates all directions of a run into one call and splits the scores back by direction, so a run loads the COMET model once.
- Constants: `COMET_VERSION = "2.2.7"`, `COMET_PYTHON = "3.11"`, `COMET_MODEL = "Unbabel/wmt22-comet-da"`, `COMET_EXTRA_REQUIREMENTS = ["setuptools<81"]` (passed as `--with`). The first call downloads PyTorch for Python 3.11 and the COMET model (about 2.3 GB) into the uv and Hugging Face caches; on the development laptop that took about 55 minutes.
- `uv` is located with `shutil.which("uv")`; a clear error if missing.

**`compare.py`** - `compare(a, b) -> Comparison` where `a` and `b` are loaded runs or baselines (same interface: per-direction segment COMET and system scores):

- Only directions and segment ids present in both are compared; mismatched ids are reported.
- Per direction: `delta_comet = mean(b) - mean(a)`, 95% paired bootstrap interval of the delta (1,000 resamples of segment indices with replacement, `random.Random(0)`), verdict `better` (lower bound > 0), `worse` (upper bound < 0), or `no significant difference`; `delta_chrf` reported without a significance test.
- `regression` is `True` when `zh-en` is `worse`.

**`baselines.py`** - baseline files `apps/eval/baselines/<mode>.json` (committed). Content: `run_id`, `created_at`, `dataset`, `engine_info`, `engine_config` (no secrets), `hardware`, `comet` settings, `chrf_signature`, per-direction `n`, `comet`, `chrf`, and `segment_comet: {direction: {id: score}}`. Segment ids and numbers only: **no source, reference, or hypothesis text** (a test enforces this). Threshold rule (ADR-005): a new run is a regression if `compare(baseline, run).regression`.

**`cli.py`** - Typer app, commands:

| Command | Behavior |
|---------|----------|
| `download-flores` | Download FLORES+ devtest at the pinned revision. |
| `run --mode llm\|mt [--dataset flores\|domain:<path>] [--directions all\|zh-en,en-zh,...] [--limit N]` plus for MT: `--mt-model-dir PATH [--mt-family small100] [--device cpu\|cuda\|auto] [--compute-type T] [--beam-size N] [--cpu-threads N]` | Run a benchmark; print the run directory and a summary. |
| `score <run_dir>` | (Re)score an existing run (e.g. after a COMET failure). |
| `compare <a> <b>` | `a`, `b`: run directories or baseline files. Prints a per-direction table; exit code 1 on regression. |
| `baseline set <run_dir>` | Write `apps/eval/baselines/<mode>.json` from a complete, scored run. Refuses runs with `git_dirty = true` or `limit` set. |

The console entry point `main()` sets UTF-8 console output and configures logging (`INFO` to stderr) before any output, then runs the Typer app. Commands print tables with `typer.echo`. Expected failures print one `error:` line and exit with code 2; `compare` uses exit code 1 only for a regression.

### 10. Tests (no network, no models, no VPN)

| File | Covers |
|------|--------|
| `core/tests/test_types_config.py` | Enum values; config validation bounds; discriminated union parses `{"mode": "llm", ...}` and `{"mode": "mt", ...}`; `api_key` absent from `repr` and `model_dump_json()` output as plain text. |
| `core/tests/test_translator.py` | With a fake engine recording calls: order preserved; duplicates translated once; whitespace-only passthrough never reaches the engine; leading/trailing whitespace re-applied; `source == target` raises; engine returning wrong count raises `EngineResponseError`; use after `close()` raises. |
| `core/tests/test_engines_llm.py` | Via `httpx.MockTransport`: happy path with batching and concurrency preserving order; `json_mode` on/off body shape; code-fenced JSON; count mismatch triggers split and succeeds; persistent garbage on one segment raises `EngineResponseError`; 429 with `Retry-After` retried then succeeds (injected `sleep` records waits); 503 exhausts retries -> `EngineResponseError`; connection error -> `EngineUnavailableError`; 401 -> `EngineAuthenticationError` with no retry; error messages never contain the API key; `Authorization` header present. |
| `core/tests/test_engines_mt.py` | With fake translator and tokenizer objects injected through `MtRuntime`: sources are `__<target>__ + pieces + </s>` with the configured beam and batch sizes and no target prefix; special and language tokens are dropped from output; `info` fields; use after `close()` raises; missing extra, missing `model.bin` or `sentencepiece.bpe.model`, and an unloadable model raise `EngineUnavailableError`. |
| `core/tests/test_integration_engines.py` (`integration`) | Real LLM: `Translator` translates `["你好，世界", "谢谢"]` zh->en to non-empty English (skipped unless the `DOCTRANSLATOR_LLM_*` variables are set). Real MT: if `DOCTRANSLATOR_TEST_MT_MODEL_DIR` is set, translate the same with SMALL-100; otherwise skip. |
| `eval/tests/test_settings.py` | Env and `.env` loading (`tmp_path` + `monkeypatch.chdir`); keyring fallback via a fake keyring backend; missing variables error lists names. |
| `eval/tests/test_datasets.py` | FLORES join by id from small fixture files written to `tmp_path`; id mismatch fails; parallel JSONL filtering and duplicate rejection. |
| `eval/tests/test_runner.py` | `run_benchmark` end to end with `Translator` monkeypatched to a fake (uppercases input) and `scoring.comet` stubbed to fixed scores: asserts every run directory file, manifest fields, `complete` status, `failed` status when the fake raises mid-run, and that the API key appears in no written file. |
| `eval/tests/test_scoring.py` | chrF on known strings; COMET adapter with a fake `comet-score` (monkeypatched subprocess runner writing the verified JSON shape): newline sanitizing, label mapping, count mismatch error. |
| `eval/tests/test_compare.py` | Identical runs -> no significant difference; clearly better/worse synthetic scores -> correct verdicts; determinism with seed; mismatched ids reported; regression only on `zh-en` worse. |
| `eval/tests/test_baselines.py` | Baseline written from a run contains no text from `translations/` (search every source, reference, and hypothesis string); refuses dirty or limited runs. |

`test_package.py` in both packages: add every new module to `MODULES`.

### 11. Run the benchmark and set baselines

**Deferred (owner, 2026-09-27):** SMALL-100 (MT) and Gemma (LLM) are settled for now, so benchmark scoring and baselines are not run yet. The eval app is ready for them; this step and its completion criteria remain open until they are run.

The MT model was chosen before the benchmark existed, on a zh-en throughput bake-off ([ADR-006](../decisions/ADR-006-mt-model-selection.md)); the full benchmark sets the baselines. On the development laptop (CPU only; hardware is recorded automatically), from the repository root:

1. `uv run doctranslator-eval download-flores`
2. **LLM baseline (VPN):** `uv run doctranslator-eval run --mode llm`, then `uv run doctranslator-eval baseline set <run_dir>`.
3. **MT baseline:** convert SMALL-100 (step 8, or reuse the existing conversion), then `uv run doctranslator-eval run --mode mt --mt-model-dir data/models/alirezamsh--small100-ct2-int8`, all 12 directions, with the `cpu_threads` default ADR-006 settles on. Then `uv run doctranslator-eval baseline set <run_dir>`.
4. Add the MT baseline's per-direction COMET and chrF to ADR-006's evidence.
5. Commit both baseline files.

Run logs and full outputs stay in `data/`. Nothing from `data/` is committed.

### 12. Documentation and tracking

In the same change set:

- `docs/Architecture.md#core-api-reference`: update Status and anything that changed during implementation (e.g. `json_mode` default from step 1).
- `docs/Architecture.md#evaluation-reference`: document purpose, commands, run directory format, baseline format, COMET isolation.
- `docs/decisions/ADR-003-source-structure.md`: add `translator.py` to the core module table ("`Translator`: text-level translation over an engine; part of the public API via `__init__.py`").
- `docs/Architecture.md`: keep the overview and implemented status aligned with its core and evaluation sections.
- `docs/Structure.md`: `scripts/convert_mt_model.py`, `apps/eval/baselines/`, `data/models/`.
- `AGENTS.md`: how to run integration tests (`uv run pytest -m integration`; the LLM test needs the VPN).
- `README.md`: open question on the MT model resolved (link ADR-006).
- `docs/IMPLEMENTATION_PLAN.md` and board item #9009: status per Board Tracking.

## Interfaces

Public API added in this phase: exactly the Public API, Types, and Configuration sections of the [core API reference](../Architecture.md#core-api-reference). Nothing else is exported from `doctranslator_core` or `doctranslator_core.types`.

Eval command-line interface: step 9, `cli.py` table.

## Edge Cases

- **Segments containing newlines** (none in FLORES+, common later in documents): the LLM prompt preserves them; COMET input sanitizes them (step 9); `translations/*.jsonl` keeps the originals.
- **Model echoes the source or leaves segments untranslated**: not detected in P1; it shows up as low COMET. Do not add language detection here.
- **Server ignores `temperature = 0`**: reruns may differ slightly; the bootstrap comparison absorbs small noise.
- **JSON mode unsupported**: handled by config (step 1).
- **Chinese or Japanese console output on Windows**: `cli.py` reconfigures `sys.stdout` and `sys.stderr` to UTF-8 at startup (`reconfigure(encoding="utf-8")`), because the default Windows console code page cannot print these scripts.
- **Long runs interrupted**: the run directory stays marked `failed`; start a new run (no resume in P1).
- **COMET's first run** downloads about 2.5 GB; its failures (network, disk) surface as a scoring error and `score <run_dir>` retries scoring without retranslating.
- **HF rate limits or gated access**: `download-flores` reports the dataset page to accept terms on.

## Tests Required

All tests in step 10, passing under the six checks. Integration tests pass when run on the VPN with `-m integration` (LLM) and with the converted SMALL-100 model (MT).

## Completion Criteria

- [x] Connectivity check done; JSON mode support and latency recorded (step 1).
- [x] Both modes translate all 12 directions through `Translator`, exactly as specified in the core section of `docs/Architecture.md` (2026-09-27: two FLORES+ sentences per direction, each output non-empty and in the target script).
- [ ] All six checks pass locally and in CI, including the new import contracts and the core environment-variable ban; no test needs the VPN, a model, or network. (Local: passing, 87 tests. CI: runs when the branch reaches `main` or a pull request.)
- [x] Integration tests pass on the VPN (LLM) and with a converted model (MT).
- [x] FLORES+ downloaded at the pinned revision (all four languages).
- [x] Documentation updated per step 12.
- [ ] Board item #9009 Closed; `docs/IMPLEMENTATION_PLAN.md` shows P1 Done.

### Deferred

The [P1.1 operational draft](P1.1-baseline-capture.md) gives the capture sequence. Board #9009 was verified Active on 2026-09-27 and no CI run was found for `p1-engines-eval`; keep the two unchecked closure criteria above until reviewed-commit CI and board closure are verified. The handoff's claimed closure was premature.

Moved out of P1 by the owner on 2026-09-27; tracked in `docs/IMPLEMENTATION_PLAN.md` under P1. They must be done **before the first change to the LLM prompt, the LLM model, or the MT model**, since that is when a regression check first matters:

- Complete benchmark runs (step 11) for LLM mode and SMALL-100.
- `apps/eval/baselines/llm.json` and `apps/eval/baselines/mt.json` committed, containing no text; `compare` of each against itself reports no significant difference and exit code 0.
- ADR-006 includes the MT baseline's per-direction scores.

## Out of Scope

- Documents of any format, the pipeline, source language detection, and the product CLI (P2).
- A domain benchmark set (the loader exists; sourcing the data is an open question in the README).
- Engine support for local LLMs or any MT model family other than SMALL-100 (ADR-006 compares some as evidence only), GPU benchmarking, and model fine-tuning.
- Human evaluation and LLM-as-judge (ADR-005).
- Caching translations across runs.
