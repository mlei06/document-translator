# ADR-019 - Supported Models and Configured Translators

Status: Accepted by owner, 2026-09-29. Supersedes ADR-006's single-model installation constraint and the one-MT/one-LLM service configuration assumption. Existing supported model adapters remain authoritative; this decision does not certify new model families.

## Decision

Website amendment: [ADR-027](ADR-027-automatic-website-translation.md) supersedes user model selection and no-fallback rules for hosted browser submissions only. The Gemma/Davy/HY-MT policy is specified, not implemented. Explicit API/CLI and desktop choices retain this contract.

Availability is further specified by [ADR-024](ADR-024-translator-availability.md): installed local MT artifacts and cached approved Davy `/models` discovery determine new-job eligibility. Generic LLM entries retain the configuration behavior below.

- One supported-model catalog describes validated model/runtime combinations; an installation chooses zero or more configured translators from supported adapters. Do not accept arbitrary executable model repository code.
- Shared website administrators configure/enable translators and choose one default. Ordinary users select enabled translators; they cannot configure server paths, endpoints or secrets.
- Desktop setup installs the app, then lets the user select one or more supported local model bundles, with one recommended default and visible download/disk/hardware requirements. Remote-only setup is explicit. Later settings add/remove models and select a default, subject to managed-device policy. D0/D1 installer gates still apply; documenting this is not shipping an installer.
- LLM adapter support is included, but a translator is selectable only when configured/enabled with the required assets or connection settings. Remote reachability can still fail at execution; do not claim configured means healthy. Never silently switch to another translator or remote processing.
- Present one **Translator** selector using configured names and execution location. MT/LLM are internal engine categories, not the user's primary selector. In hosted mode say **On server** or **Remote service**, never imply a server-local model runs on the user's device.
- Each translator has a stable `translator_id`, label, engine configuration and enabled flag. Models/revisions and relevant settings determine output fingerprints. Jobs persist their selected ID and fingerprint. Workers verify the configured/loaded identity against the pinned fingerprint; changed or missing configuration fails explicitly instead of running a different model.
- Multiple installed models are not all loaded into RAM/VRAM. Load lazily and bound retained loaded runtimes per worker; default to one local model retained per worker, evicting the least-recently-used runtime when loading a different model beyond that bound. Compatible decoding presets share one loaded runtime. A desktop idle-unload policy remains part of D0. Disk installation and runtime loading are separate.
- API capabilities expose safe configured translator metadata and `default_translator_id`; never credentials, private model paths or connection URLs. Submission accepts `translator_id`. Preserve legacy `mode` clients by resolving a configured translator of that mode deterministically (prefer configured default when matching); reject a conflicting explicit ID/mode. Legacy single-engine environment settings remain supported when no translator list is supplied.
- No automatic quality ranking, model routing, new inference adapters or hot configuration control plane. Configuration changes take effect on runtime restart; active work must not silently switch identities.

## Delivery contract

Implement server configuration/catalog, API/job selection and migration, worker identity/load behavior, service CLI selection, generated OpenAPI and the web selector. Preserve ADR-014 storage/reuse and fit-skip behavior. The desktop installer uses this contract when D0/D1 is implemented. Update deployment examples and tests for multiple translators in the same mode, disabled/unknown IDs, explicit default, legacy mode behavior, secret-safe capabilities and fingerprint changes.

Resume P6 by fixing session-bound pending work, bounded submission/polling and frontend test setup. Separately fix retention so active worker directories cannot be removed just because their modification time is old. Browser tests must use the actual service with deterministic engines for repeatable lifecycle checks; real-model acceptance remains distinct evidence.

## Runtime reuse amendment (owner accepted, 2026-09-29)

Beam 4 and Greedy remain distinct configured translator IDs, job identities and output fingerprints. They share SMALL-100 weights and tokenizer within a worker when model path/artifact, family, resolved device, precision and CPU-thread configuration match. Beam size and inference batch size are call-time settings, excluded from runtime grouping but retained in output identity.

Use immutable decoding bindings over the shared runtime. A native inference call receives its own beam size and batch limit; changing one binding must not mutate another. Closing one binding does not invalidate an independently held binding. Runtime eviction closes all catalog bindings for the evicted group. The configured maximum counts distinct loaded local runtimes, not UI presets. Each worker still handles one document at a time and owns its own runtime cache; no cross-worker or global model pool is introduced.
