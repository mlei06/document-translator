# ADR-025 - HY-MT through an explicitly configured local inference server

Status: Accepted implementation direction under the owner's 2026-09-29 instruction to benchmark
and integrate laptop translation. Performance settings remain subject to measurement.

## Context

The current owner instruction prioritizes acceleration, thread tuning and HY-MT integration,
with CPU/GPU profiling. It explicitly defers broad accuracy work. This supersedes P1.1's
full-quality-baseline prerequisite for this bounded task, not the requirement to preserve text,
formatting and explicit failure behavior. No measured quality superiority is claimed.

SMALL-100 uses CTranslate2 in-process. HY-MT1.5-1.8B is a causal translation model with official
GGUF artifacts and model-specific plain-text prompts. Its interface is not interchangeable
with SMALL-100 language tokens or the existing JSON-batch LLM prompt.

## Decision

Website amendment: [ADR-027](ADR-027-automatic-website-translation.md) explicitly selects HY-MT Q8_0 Vulkan, four generation/prompt threads and four slots as the final hosted fallback after Davy. This supersedes the no-automatic-fallback restriction below for that policy only; external process ownership and identity requirements remain unchanged. Routing implementation is pending.

- Preserve the TranslationEngine interface and existing MT/LLM wire modes. Add an explicit
  HY-MT protocol to the LLM engine configuration, with the current JSON-batch protocol as default.
- A dedicated core adapter sends one segment per request to an OpenAI-compatible llama.cpp
  chat endpoint, preserves input order with bounded concurrency and validates completion.
  Output-limit truncation is an error. The existing pipeline validates/restores inline markers.
- The administrator starts and owns the local llama-server process and explicitly configures
  its loopback endpoint, model alias and deployment revision. The revision identifies the GGUF,
  runtime build and generation-affecting server settings; the HTTP client does not independently
  attest the running model. Do not expose endpoint details or credentials through capabilities.
- Execution location is explicit. Server-local endpoints must use loopback; ordinary remote
  LLM configurations keep their existing default. HY-MT is separate from Davy discovery.
  Configured availability does not promise that an external inference server is currently healthy.
- No automatic remote fallback, model download, arbitrary model code execution or process
  supervisor is introduced. The in-process MT model LRU does not manage externally served models.
  Run only the selected external model when memory matters; desktop lifecycle remains D0 work.
- Model protocol, prompt revision and generation settings enter output identity. Existing
  JSON-batch identities remain compatible unless their output settings change.
- Benchmark SMALL-100 OpenVINO separately before deciding whether its extra dependencies and
  runtime conversion merit production integration. Do not copy the experimental runtime wrapper
  into production without explicit artifact, identity and lifecycle support.

## Validation and limitations

Use the installed HY-MT1.5-1.8B Q8_0 artifact first, CPU and Arc Vulkan. Profile load/warmup and
each timed inference repetition; retain raw samples and distinguish unavailable GPU counters
from idle measured counters. Check real documents and mocked transport failure/order/identity
cases. Run all six repository checks. Publish performance evidence without presenting a small
synthetic sample as a comprehensive accuracy benchmark or a universal laptop default.

This is a developer/admin-operated local integration, not a completed model installer. Existing
ADR-006 distribution/licensing concerns remain unresolved by a successful local benchmark.
