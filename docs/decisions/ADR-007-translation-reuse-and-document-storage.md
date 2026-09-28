# ADR-007: Translation Reuse and Document Storage

## Status

Accepted (2026-09-27)

## Context

Translation is the expensive step: seconds to minutes per document, on a shared LLM server or on the host's CPU. Work is wasted in three ways:

1. **Within a document.** The same paragraph (a repeated header, footer, table label, or bullet) appears in many places. The README already requires repeated strings to translate consistently.
2. **Across uploads of the same file.** A document forwarded to several coworkers, or uploaded twice by the same person, is translated again from scratch.
3. **Across versions of a document.** Version 3 of a deck differs from version 2 by a few slides, but every slide is translated again.

Separately, users (through the web GUI) and agents (through MCP visual review, P7) change a translated document after translation. Those changes belong to one user's copy and must not affect anyone else, including other users who receive the same translation from a cache.

Forces:

- **The core has no persistence** ([ADR-003](ADR-003-source-structure.md)). Anything that outlives one translation lives in the server.
- **Documents are files, not rows** ([ADR-004](ADR-004-job-storage.md) rule 1). The database holds metadata and references.
- **Output must reflect current behavior.** A changed prompt, MT model, fit floor, or core release must never be answered with a translation produced by the old behavior.
- **Hosting moves.** The laptop uses local disk; a shared or cloud host will use object storage (Azure Blob or S3-compatible) and PostgreSQL. This must be a configuration change.
- **Confidentiality and retention.** Stored documents grow without bound unless cleaned up, and ADR-004 already requires a retention policy before the server is shared.
- **Scope.** The README lists translation memory management as a non-goal. Automatic reuse of machine output is not translation memory, but reuse must not grow into curated, human-edited translation memory by accident.

## Options Considered

### Within-document reuse

- **Deduplicate per `translate_texts` call only** (what `Translator` guarantees today). Correct only if the pipeline translates the whole document in one call; any chunking (per slide, for progress reporting) translates a repeated string once per chunk and can translate it differently.
- **Deduplicate across the whole document in the pipeline.** The pipeline extracts every segment first and translates the unique ones, regardless of how it batches or reports progress. Chosen.

### Whole-document cache key

- **Hash of the input bytes only.** Returns stale output after any prompt, model, fit, or core change.
- **Hash of the input bytes plus a fingerprint of everything that determines the output.** Chosen. The fingerprint is computed by the core, so the rule for "what affects output" lives where the behavior lives.

### Cache store

- **Redis.** Keeps multi-megabyte files in memory, is not durable by default, and adds a service to run. The lookup it would speed up is one indexed query per upload, next to minutes of translation.
- **Database index plus content-addressed files.** Uses the storage ADR-004 already mandates, is durable, and moves to PostgreSQL and object storage with configuration. Chosen.

### Persistent segment cache (reuse across versions of a document)

A store of (source text, languages, engine fingerprint) -> translation, consulted before calling the engine. It is the only layer that helps with case 3, because re-saving an office file changes its bytes (timestamps and metadata inside the zip) even when the content does not change. It requires the core to accept an injected cache interface, which changes an ADR-003 core rule, and it needs care to stay clear of the translation memory non-goal.

- **Build now.** Cost and a core rule change before there is evidence of the hit rate.
- **Defer, with the data to decide.** Chosen. The server logs document cache hits and misses, and the fingerprint defined here is reused as part of the segment cache key if it is built.

### User copies and edits

- **Edit the job's output file in place.** Corrupts the shared cache when the output came from it, and loses history.
- **Copy the output for every user on every translation.** Safe, but stores one full copy per user for identical, unedited documents.
- **Immutable content-addressed files, with per-user documents made of versions (copy on write).** Version 0 references the translated file without copying it; each edit writes a new file and a new version. Chosen.

## Decision

Three layers, plus per-user documents.

### Layer 1: within-document deduplication (core, P2)

The pipeline collects every translatable segment of a document before translating and sends each unique segment to the engine once, however it batches work or reports progress. Repeated segments receive identical translations. The deduplication key is the segment as the engine receives it, including any inline formatting placeholders, so two segments that differ only in formatting are not merged. The segment granularity and placeholder format are designed with `document.py` in P2.

### Layer 2: whole-document cache (server, P5)

- **Output fingerprint.** The core's public API exposes a deterministic fingerprint of the options and engine that produced a translation: requested source language (including auto-detect as its own value), target language, mode, `EngineInfo` (model, prompt version or MT model and compute settings), fit options, and the core distribution version. Apps treat it as opaque. Any change to what determines output changes the fingerprint; when in doubt, the core includes the value.
- **Key.** `(sha256 of the input bytes, output fingerprint)`.
- **Record.** A `translation_results` row per key: output file reference, fit report reference, the `EngineInfo` that produced it, `created_at`, `last_used_at`. Unique on the key.
- **Lookup.** At job submission, and again by the worker immediately before translating ([ADR-008](ADR-008-job-execution-model.md)). A hit completes the job without translating.
- **What is cached.** Only complete, successful pipeline output. Failed or partial jobs are never cached. Output with unresolved fit issues is complete and is cached. Anything changed after the pipeline (user edits, agent visual review edits) is never cached.
- **Scope.** One cache shared by all users. Anyone submitting the exact bytes already holds the document, so a hit reveals no content. It does reveal, through an immediate result, that someone translated the same file before; this is accepted for an internal tool and recorded for the authentication ADR.
- **Bypass.** Submissions accept a `force_retranslate` option. It skips the lookup, translates, and replaces the cache entry for that key.
- **Duplicate work.** Two identical submissions in flight at the same time may both translate. The unique key keeps the first result; the second worker's pre-translation lookup catches most cases. No locking.
- **Surfaces.** The server owns the cache. Under [ADR-010](ADR-010-shared-service-cli.md), service CLI commands use it through REST; local synchronous `translate` has no database and does not use it.

### Layer 3: persistent segment cache (deferred)

Not built. It is reconsidered when the logged cache statistics show that a significant share of misses are near-duplicates of cached documents. If built, it is a core-defined abstract interface that `Translator` accepts and the server implements, which requires a new ADR amending the ADR-003 core persistence rule, and it stores only machine output, never user edits.

### Files: content-addressed blobs

- Every stored file (uploads, translated outputs, fit reports, edited versions, later rendered pages) is a blob named by the sha256 of its content, e.g. `blobs/sha256/ab/abcdef...`, relative to the configured storage root. A blob is written once and never modified, so the same blob can be referenced by the cache and by any number of user documents.
- Blob access goes through one server-side storage interface (`put`, `get`, `exists`, `delete`, by hash). The first implementation is the local data directory; an object storage implementation is added when the server moves off the laptop, with no change to its callers.
- The database stores blob hashes, never file contents or absolute paths.

### Per-user documents and versions

- A `documents` row belongs to one owner (defined by the authentication ADR) and records the original upload blob, languages, options, and the `translation_results` entry it started from, if any.
- `document_versions` rows record `document_id`, `version_no`, `blob_hash`, `parent_version_id`, `created_by` (`translation`, `user_edit`, `agent_edit`), and `created_at`. Version 0 is the translation and references the translated blob directly, so a cache hit stores nothing new.
- An edit reads the latest version, applies the change, writes a new blob, and adds the next version. It never touches a blob or a cache entry. Two edits based on the same version conflict: the second one fails and is retried by the client against the new latest version.
- Downloads return the latest version by default; earlier versions remain available, which provides undo.
- The version's file is the source of truth. Edit operations may be recorded for audit and display, but are never replayed to reconstruct a file.
- User edits never flow back into any cache.

### Retention

- Cache entries expire when unused (`last_used_at`) for a configurable period.
- User documents expire on their own configurable policy, independent of the cache.
- A blob is deleted only when no cache entry, document version, or job references it. Cache expiry never removes a file a user document still uses.
- Default durations are set in the P5 plan and documented in `docs/Deployment.md`.

## Consequences

- P2 adds whole-document deduplication to the pipeline's tested guarantees and the output fingerprint to the core's public API.
- P5 builds the blob storage interface, the `translation_results`, `documents`, and `document_versions` tables with their migration, cache lookup at submission, `force_retranslate`, retention with reference-based blob cleanup, and hit/miss logging. It also needs the authentication ADR, because documents have owners.
- P7 edit tools produce new document versions and never modify cached output.
- A core release invalidates the whole cache (the core version is part of the fingerprint). This trades hit rate for never serving output from old behavior.
- Byte-identical input is the only case layer 2 catches. Near-identical documents are translated again until layer 3 is justified and built.
- Backups must include the blob store together with the database, as ADR-004 already requires for the data directory.
- The immediate response to a cached document is a small cross-user signal, to be weighed in the authentication ADR.
