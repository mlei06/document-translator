# Backend-specific translator availability

Decision: [ADR-024](../decisions/ADR-024-translator-availability.md).

## Delivered behavior

- One backend-owned catalog drives CLI/API/web selection. Configured local MT entries require complete supported model artifacts at startup. SMALL-100 currently requires nonempty `model.bin`, `sentencepiece.bpe.model`, `config.json` and `shared_vocabulary.json`. This is an installation check, not an inference probe.
- Davy uses shared connection settings and an explicit approved model list. Authenticated `GET /models` is the only discovery request. Its cached response filters eligible Davy entries without altering generic LLM configuration behavior.
- Capabilities carry connection status; the browser polls every 60 seconds and provides manual retry. Missing selected/default models cannot silently fall back. Installed MT choices remain independent of Davy connectivity.
- Admission checks current eligibility. Workers keep the originally pinned identity; idempotent replay does not depend on discovery.

## Deployment verification

On 2026-09-29 the real Davy `/models` request returned HTTP 200. The owner approved Gemma, GPT-OSS 120B, GPT-OSS 120B Thinking, Laguna S 2.1, Nemotron 3 Super 120B and Nemotron 3 Ultra. These are configured in the ignored local website settings. The embedding and reranker entries are excluded. No per-model inference health requests were sent, and listing is not evidence of translation quality for these models.

Required regression evidence: GET-only discovery, approved-ID filtering, cached/single-flight refresh, safe connection failures, missing/partial local bundles, unavailable default admission, preserved replay/pinned identity, authenticated/CSRF refresh, browser connection transitions and explicit installed-model selection. Installation/removal requires restarting API/workers; dynamic desktop model-management remains future work.

Verified locally: 37 focused backend tests; Python dependency sync, formatting, lint, type checking and import contracts; frontend type checking, lint, formatting, 41 unit tests and production build; all six Playwright lifecycle tests. The Davy browser test covers offline/reconnect/authentication-failure transitions and explicit selection of an installed translator to complete a real service job. Desktop and mobile screenshots were inspected. A real catalog check returned both SMALL-100 presets and all six approved Davy IDs without loading weights or calling inference.

The full Python run completed with 338 passing tests and one obsolete empty-file fixture failure. The fixture was corrected for the stricter artifact requirement; its seven-test module passed in the focused run and `uv run pytest --lf` subsequently passed the remaining case. Three additional missing-artifact variants added during the full run passed in the focused run. No outstanding test failures remain.

Live rollout: the ignored website configuration and frontend bundle are updated. At verification completion, an existing Gemma job was still running, so the port-8765 service was deliberately left uninterrupted. Restart the API/workers after that job finishes to activate discovery and the additional Davy models. Port 8770 remains stopped. No per-model translation-quality acceptance is claimed by this delivery.
