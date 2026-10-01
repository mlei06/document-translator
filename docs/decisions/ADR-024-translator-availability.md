# ADR-024 - Backend-specific translator availability

Status: Accepted by owner, 2026-09-29. Clarifies ADR-019's configured translator selection.

## Decision

Website amendment: [ADR-027](ADR-027-automatic-website-translation.md) replaces the browser picker/retry/no-rerouting contract with automatic policy traversal. Discovery remains an approved-model filter; shared Davy failure can skip the remote tier. Explicit clients retain this decision's pinned selection behavior. Implementation is pending.

The selector describes translators available on the backend serving the request. Configuration is an explicit allowlist, not proof of availability.

- Local MT entries are selectable only when their required model artifacts are installed on that backend. Check installation without loading weights or running inference. Several decoding presets may share one installed model. Future supported MT adapters supply their own artifact checks; discovering a directory does not enable an unsupported model.
- The current MT catalog validates installation at service startup, together with its pinned artifact identity. Installing or removing models requires restarting the API and workers. The future desktop model manager must perform that reload explicitly; remote Retry connection only refreshes Davy discovery.
- Davy uses one administrator-configured base URL and API key plus an approved list of translation models. Only approved, enabled model IDs returned by authenticated `GET /models` are selectable. Do not send per-model inference probes. Being listed does not guarantee a successful future translation.
- Cache Davy discovery for 60 seconds. An authenticated refresh action can retry, with a five-second minimum interval. A failed refresh removes remote choices until discovery succeeds. Local translators remain usable independently.
- Expose safe connection states: not configured, available, unreachable, authentication failed, no approved models, and invalid discovery response. Never expose credentials, private URLs or upstream error bodies. The UI offers a retry for configured Davy connections and explains network/VPN failures.
- Preserve a saved or default choice that becomes unavailable. Require an explicit replacement choice; never silently switch models. Validate availability again when admitting new work.
- Accepted jobs retain their pinned model and settings. Discovery is not a worker rerouting mechanism. Idempotent replay remains available without requiring the original model to be reachable.

## Consequences

Desktop, hosted and internal-app clients use the same capabilities contract, but each backend reports its own installed MT models and reachable approved Davy models. Disk installation remains separate from bounded, lazy runtime loading. A missing local model must not prevent other installed translators from serving requests. Runtime failures still surface as job failures because neither file checks nor model listing guarantees inference health.
