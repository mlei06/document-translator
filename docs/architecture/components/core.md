# Component: Core

Status: text translation (this document's scope for P1) approved 2026-09-26. Document formats, fit check, and rendering sections are added in P2, P3, and P7.

## Purpose

`doctranslator_core` (`packages/core`) owns everything that determines what a translation looks like. Every surface (CLI, server, eval) calls it through one public API, so the same input and options produce the same output everywhere ([ADR-003](../../decisions/ADR-003-source-structure.md)).

## Responsibilities

- Translate text between Chinese (Simplified), English, Japanese, and Spanish in all 12 directions.
- Provide two translation modes behind one interface: LLM (internal LLM server) and MT (local machine translation model).
- Guarantee text-level invariants shared by every surface: consistent translation of repeated strings, whitespace preservation, and pass-through of empty text.
- Later phases: document formats (P2), fit check (P3), rendering and edits (P7).

## Boundaries

This component owns:
- Language and mode definitions, engine configuration types and their validation.
- The engine interface and both engine implementations, including prompts and model-specific conventions.
- Retries, batching, and concurrency toward the LLM server; model loading and inference for MT.

This component does NOT own:
- Reading configuration from anywhere (environment, `.env`, files, OS vault, arguments). Apps load values and pass typed config in.
- Logging setup, progress display, or command-line handling.
- Benchmark datasets, scoring, or evaluation (that is `apps/eval`).
- Persistence of any kind.

## Interfaces

### Public API

Everything below is importable from `doctranslator_core` (the only module apps may import besides `doctranslator_core.types`).

```python
from doctranslator_core import Translator, LlmEngineConfig, MtEngineConfig
from doctranslator_core.types import Language

config = LlmEngineConfig(base_url=..., api_key=..., model="gemma-4-31b-it")
with Translator(config) as translator:
    out: list[str] = translator.translate_texts(
        ["你好，世界"], source=Language.ZH, target=Language.EN
    )
```

`Translator(config: EngineConfig)`
: Creates the engine for `config.mode`. Construction is cheap for LLM mode; for MT mode it loads the model, which can take seconds, so a `Translator` is meant to be created once and reused for many calls. It is a context manager; `close()` releases the HTTP client or model. Not thread-safe; use one `Translator` per thread.

`Translator.translate_texts(texts: Sequence[str], *, source: Language, target: Language) -> list[str]`
: Returns one translation per input, in input order. Guarantees:
  - `len(result) == len(texts)`.
  - Inputs that are empty or whitespace-only are returned unchanged and never sent to the engine.
  - Leading and trailing whitespace of each input is removed before translation and re-applied to its output unchanged.
  - Identical inputs (after stripping) are translated once and receive identical outputs within a call.
  - `source == target` raises `ValueError`.
  - Any failure raises a `TranslationError` subclass; partial results are never returned.

`Translator.engine_info -> EngineInfo`
: Identifies what produced the translations, for recording alongside results: mode, model identifier, prompt version (LLM) or model family and compute settings (MT).

### Types (`doctranslator_core.types`)

| Type | Definition |
|------|------------|
| `Language` | `StrEnum`: `ZH = "zh"` (Simplified Chinese), `EN = "en"`, `JA = "ja"`, `ES = "es"`. |
| `TranslationMode` | `StrEnum`: `LLM = "llm"`, `MT = "mt"`. |
| `EngineInfo` | Frozen Pydantic model: `mode: TranslationMode`, `model: str`, `details: dict[str, str]` (e.g. `prompt_version`, `model_family`, `device`, `compute_type`). |
| `TranslationError` | Base exception for all translation failures. |
| `EngineUnavailableError(TranslationError)` | The engine cannot be reached or loaded: connection failure, DNS failure, timeout after retries, model directory missing. |
| `EngineAuthenticationError(TranslationError)` | The LLM server rejected the credentials (HTTP 401/403). Never retried. |
| `EngineResponseError(TranslationError)` | The engine answered but the answer is unusable: malformed output that still fails after the recovery strategy, or a non-retryable HTTP error. |

Error messages never include API keys or full request bodies.

### Configuration (`doctranslator_core.config`, re-exported from `doctranslator_core`)

Frozen Pydantic models. Apps construct them from their own configuration sources. `EngineConfig = LlmEngineConfig | MtEngineConfig`, discriminated by `mode`.

`LlmEngineConfig`

| Field | Type | Default | Meaning |
|-------|------|---------|---------|
| `mode` | `Literal[TranslationMode.LLM]` | `LLM` | Discriminator. |
| `base_url` | `HttpUrl` | required | OpenAI-compatible API root, e.g. `https://host:port/v1`. |
| `api_key` | `SecretStr` | required | Bearer token. Never logged or included in errors. |
| `model` | `str` | required | Model name on the server. |
| `timeout_s` | `float` | `120.0` | Per-request timeout. |
| `max_retries` | `int` | `3` | Retries for retryable failures (see Error Handling). |
| `batch_size` | `int` | `16` | Segments per request. |
| `max_concurrency` | `int` | `4` | Concurrent requests per `translate_texts` call. |
| `temperature` | `float` | `0.0` | Sampling temperature; `0.0` for reproducible output. |
| `json_mode` | `bool` | `True` | Send `response_format: {"type": "json_object"}`. Disable for servers that reject it. The internal server accepts it (verified 2026-09-27). |

`MtEngineConfig`

| Field | Type | Default | Meaning |
|-------|------|---------|---------|
| `mode` | `Literal[TranslationMode.MT]` | `MT` | Discriminator. |
| `model_dir` | `Path` | required | Directory of a CTranslate2-converted model, including its tokenizer files. |
| `model_family` | `Literal["small100"]` | required | Selects tokenizer and language-token conventions (see MT engine). The only family is SMALL-100 ([ADR-006](../../decisions/ADR-006-mt-model-selection.md)); another model is added as a new family. |
| `device` | `Literal["cpu", "cuda", "auto"]` | `"auto"` | `auto` uses CUDA when available. |
| `compute_type` | `str` | `"default"` | CTranslate2 compute type (e.g. `int8`, `int8_float16`); `default` keeps the converted precision. |
| `beam_size` | `int` | `4` | Beam search width. Decoding is deterministic. |
| `max_batch_size` | `int` | `32` | Segments per inference batch. |
| `cpu_threads` | `int` | `0` | CPU threads; `0` lets CTranslate2 decide. |

## Dependencies

Depends on:
- `pydantic` (types and config), `httpx` (LLM client), `truststore` (OS certificate store, so the internal CA is trusted without disabling verification).
- Optional extra `[mt]`: `ctranslate2`, `sentencepiece`. No `transformers` or PyTorch at runtime.

Used by: `doctranslator_cli`, `doctranslator_server` (`jobs`, `settings`), `doctranslator_eval`.

## Internal Architecture

| Module | Role |
|--------|------|
| `__init__.py` | Public API: re-exports `Translator`, config types. |
| `types.py` | Public types above. |
| `config.py` | Config models above. |
| `translator.py` | `Translator`: text-level invariants (whitespace, dedupe, pass-through, ordering), delegates to an engine. |
| `engines/base.py` | `TranslationEngine` abstract base class. |
| `engines/__init__.py` | `create_engine(config) -> TranslationEngine`, mapping `TranslationMode` to an engine class. |
| `engines/llm.py` | `LlmEngine`. |
| `engines/llm_prompts.py` | Versioned prompt templates. |
| `engines/mt.py` | `MtEngine`, the SMALL-100 conventions, and `MtRuntime` (the loaded model and tokenizer, injectable for tests). |

### Engine interface

```python
class TranslationEngine(ABC):
    @property
    @abstractmethod
    def info(self) -> EngineInfo: ...

    @abstractmethod
    def translate_batch(
        self, texts: Sequence[str], source: Language, target: Language
    ) -> list[str]:
        """Translate non-empty, stripped, unique texts. Same length and order as input."""

    def close(self) -> None:
        """Release resources. Default: nothing to release."""
```

`Translator` guarantees engines only ever receive non-empty, stripped, deduplicated text, so engines don't re-implement those rules.

### LLM engine

- One `httpx.Client` per engine, with `verify=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)` and `Authorization: Bearer <key>`.
- Splits input into chunks of `batch_size` and sends up to `max_concurrency` chunks at a time (thread pool), reassembling in order.
- Each chunk is one `POST {base_url}/chat/completions` with a system prompt and a user message containing `{"segments": [...]}`; the model must answer `{"translations": [...]}` with the same count.
- Response parsing tolerates Markdown code fences around the JSON. If the JSON is invalid or the count differs, the chunk is split in half and each half retried, recursively, down to single segments. A single segment that still fails raises `EngineResponseError`.
- `PROMPT_VERSION` in `llm_prompts.py` identifies the prompt. Any change to prompt wording or structure bumps it, because translation quality baselines are tied to it (ADR-005).

### MT engine

- Loads a `ctranslate2.Translator` from `model_dir` (`model.bin`) and a `sentencepiece.SentencePieceProcessor` from `model_dir/sentencepiece.bpe.model`. SMALL-100's SentencePiece model is identical to M2M100's, so no model-specific tokenizer code is needed, and no code shipped with a model is ever executed ([ADR-006](../../decisions/ADR-006-mt-model-selection.md)).
- SMALL-100 conditions on the target language only. Each source is `__<target>__`, then the SentencePiece pieces, then `</s>`; there is no target prefix. Language tokens use the `Language` values (`zh`, `en`, `ja`, `es`).
- Output pieces are decoded with SentencePiece after dropping special tokens (`<s>`, `</s>`, `<pad>`, `<unk>`) and language tokens.
- Translates in batches of `max_batch_size` with the configured beam size. `device = "auto"` resolves to `cuda` when CTranslate2 sees a CUDA device, else `cpu`.
- Neither library ships complete type information: the engine declares `Protocol`s for exactly the calls it makes and casts once at load time.

## Error Handling

| Condition | Behavior |
|-----------|----------|
| Connection error, DNS failure, timeout | Retry with exponential backoff (1 s, 2 s, 4 s; ±25% jitter) up to `max_retries`, then `EngineUnavailableError`. |
| HTTP 429, 500, 502, 503, 504 | Retry as above; honor `Retry-After` when present (capped at 30 s). Then `EngineResponseError`. |
| HTTP 401, 403 | `EngineAuthenticationError` immediately. |
| Other HTTP 4xx | `EngineResponseError` immediately (includes status code, not body). |
| Unusable model output | Split-and-retry as described above, then `EngineResponseError`. |
| MT model directory missing or unloadable | `EngineUnavailableError` at `Translator` construction. |
| `[mt]` extra not installed | `EngineUnavailableError` at `Translator` construction, naming the extra to install. |

## Security Considerations

- API keys are `SecretStr` and never appear in logs, exceptions, `EngineInfo`, or reprs.
- TLS verification is always on; trust comes from the OS certificate store.
- The core sends document text only to the configured LLM server.

## Observability

Loggers are named after modules (`doctranslator_core.engines.llm`, ...). The core logs at `DEBUG` per request (chunk size, duration, retry attempts) and at `WARNING` for retries and split-and-retry recoveries. It never logs segment text or credentials. Apps configure handlers and levels.

## Testing Strategy

- `Translator` invariants: tested with a fake engine.
- LLM engine: tested against `httpx.MockTransport` (success, retries, `Retry-After`, auth failure, malformed JSON, count mismatch and splitting, code-fenced JSON). No test contacts a real server.
- MT engine: SMALL-100 conventions tested with a fake CTranslate2 translator and tokenizer injected through `MtRuntime`. Tests that load real models are marked `integration` and skipped by default.

## Known Limitations

- Source language auto-detection is not part of the text API; it arrives with documents in P2.
- LLM output determinism depends on the server honoring `temperature = 0`.
