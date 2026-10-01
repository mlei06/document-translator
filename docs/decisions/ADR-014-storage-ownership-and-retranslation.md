# ADR-014 - Storage, Ownership and Retranslation by Deployment Profile

## Status

Website amendment: [ADR-028](ADR-028-website-cache-and-retention.md) specifies a shared standard cache, private History and current-result downloads for new website work. It supersedes owner-only reuse, permanent website libraries and new exact-job output retention below. Legacy saved files keep their promises until explicit conversion/deletion; existing API saved/temporary and local desktop contracts remain unchanged. The amendment is not yet implemented.

Accepted product and architecture direction, 2026-09-29, from the owner's explicit decisions. Implementation pending. Supersedes conflicting storage/reuse/version rules in ADR-004, ADR-007, ADR-010, ADR-012 and ADR-013. Retains their core boundaries, within-document deduplication, fingerprints, job recovery and fit behavior.

## Context

Desktop and future Explorer translation should behave like archive extraction: files/folders in, translated files/folders out to a chosen destination. Repeated explicit runs translate again and allocate new output names. A hidden permanent document library or translation cache is unnecessary.

The shared website offers a saved document library and fast reuse of compatible translations. Internal applications may instead retrieve a temporary result and keep it in their own system. File-byte deduplication, document ownership, processing attempts and result reuse are separate concerns.

## Options considered

- Permanent shared cache and document version history everywhere: rejected for this milestone; exceeds the local workflow and retains unnecessary outputs.
- Separate translation engines/queues for each surface: rejected; processing behavior and job controls remain shared.
- Shared processing with explicit local-export, hosted-saved and hosted-temporary storage behavior: selected. These are deployment/request policies in the existing service, not new services or a general policy engine.

## Decision

### Identity and access

Use stable owner records with `kind=human|service`. API keys and browser sessions authenticate an owner; credentials are not owners. Desktop bootstrap derives the current OS user's local human identity without web sign-in. A dedicated application service account owns its submitted jobs and retained documents. Never accept an arbitrary caller-provided owner ID.

An integrating app authorizes its own users/cases and calls the translator from its backend. Its credential must not reach browsers. Optional opaque external document/user references are correlation/audit metadata, not authorization or delegated access. No mirrored account for every external end user is required. External users requiring direct translator access need a later explicit delegation design.

### Local export

- Every new explicit submission invokes translation, regardless of prior runs. Keep within-run text deduplication and model reuse, but no persistent result lookup/cache or saved source-document library.
- Users select files/folders, language/model and an export root. Preserve relative directories under distinct input roots, exclude generated output roots and skip reparse traversal by default.
- Use language-tagged output names and numbered collisions, e.g. `report.zh.docx`, `report.zh (2).docx`. Reserve destinations atomically; concurrent jobs must not choose the same name. Never overwrite sources, prior exports or user edits.
- Write/verify a temporary output on the destination filesystem, then publish without replacing an existing file. The trusted desktop/native export boundary handles local paths; hosted APIs never accept arbitrary filesystem paths. The service/core retain existing separation.
- Keep only bounded job/control metadata and temporary working inputs/results needed for active work and crash recovery. Remove working copies after confirmed export; on failure/cancel retain only for a bounded recovery period. Logs contain no document text. Exported files belong to the user and are never garbage-collected by the app.
- Retry of an interrupted request uses its existing submission ID. A new explicit run gets a new ID. Recovery must reconcile the recorded reserved destination and output digest before publishing again, avoiding accidental duplicate exports after a crash.
- A temporary accepted input snapshot protects active work from source-file changes; it is not a permanent archive. Missing/corrupt recovery input fails visibly and asks for resubmission rather than translating silently changed source bytes.
- Explorer integration, if implemented later, invokes the same local runtime/export flow. It is not a third pipeline or storage system.

### Hosted saved documents

- Store immutable file bytes by server-computed SHA-256, plus private logical document records. Deduplicate identical bytes within this company deployment; hashes never authorize reads or attach another owner's document. Receive/verify bytes or use an already-owned reference before linking content. No public hash-existence endpoint.
- Separate ownership from physical storage. Two users or two business attachments may point to the same source blob without sharing visibility, filenames, metadata or replacement behavior.
- Website repeated upload of identical bytes resolves to that user's existing library source record by default. An application may create distinct logical documents for distinct external attachments even when bytes match. Content identity is not business identity. Changed bytes create a new source revision/document; no inferred version lineage.
- Each owned source document has one current translation per resolved source/target language pair. Requests with auto source language retain both requested and resolved values. Fingerprints still distinguish auto/explicit requests and all output-affecting choices.
- The current result is the initial reusable result. Lookup stays within the owner's selected logical document and requires matching input hash and output fingerprint. No separate global `translation_results` cache or persistent segment cache is required. Fingerprints include model revision, prompt, relevant settings, protected terms, fit policy and core identity under the existing contract.
- Translate reuses a compatible result. Translate again or `force_retranslate=true` bypasses reuse and produces a replacement. An Always generate a new translation setting resolves to that flag on each new submission; it does not rerun saved documents automatically. Do not rank models to decide which explicit successful request becomes current.
- Save/verify new bytes before a fenced database transaction publishes success and swaps only this document/language pair's current result reference. Failure/cancel preserves the previous result. Never mutate shared bytes in place or change another owner's references.
- Serialize active work per logical document/target language (a conservative guard covering auto source detection). Same request ID replays its outcome. A distinct submission while that slot is active gets an owned conflict with the active job ID; UI shows it rather than starting competing replacements. Different documents/targets still run concurrently.
- An effective fit skip is a valid current downloadable result with `fit_status=skipped`, but is not eligible for normal full-fit reuse. It may replace the previous current result; do not retain an extra hidden full-fit cache. A later normal request translates again. This replaces ADR-012's references to preserving a separate reusable cache entry.
- Delete translation removes only that language's current result. Delete source removes the source and all its translations from the owner's library. Deletion cancels/fences active publication for that document and revokes job-based access too. It never affects another document referencing the same bytes.

### Jobs, results and retention

Jobs describe attempts, not permanent document copies. Each successful hosted job references an immutable result containing output/report references and production metadata. The library's current pointer may change, but a retained job download must return that job's exact output, never a later replacement. Old results can temporarily coexist while retained jobs or active downloads reference them. There is no user-visible version browser or P7 edit history in this milestone.

Saved originals/current results remain until deletion, within configured per-owner quotas; do not silently expire documents presented as saved. Reject new work when its required storage cannot be admitted, leaving existing results intact. Temporary hosted requests do not create permanent library entries or reuse past translations; results expire on an advertised deployment-configured deadline. Service accounts choose `retention=saved|temporary`; saved is the website behavior, temporary is the integration example default. Authentication kind alone does not determine retention.

Expose expiration on temporary results and old job-result downloads. Publish concrete retention/quota settings before service launch. Release settings must bound staging, terminal job metadata and superseded result retention. Active work/download pins and library references take precedence over cleanup. Delete a blob only after a transaction establishes no live references/pins and prevents concurrent publication from attaching a deleting blob. Backups follow a documented retention schedule; logical deletion is not a claim of immediate backup erasure.

### Internal applications

Default integration: authorize end user in the calling app, submit under its service account, poll job, download exact result, save as a case attachment and let temporary translator data expire. The app enforces case access. Apps needing translator-hosted retention use saved mode and their own logical attachment references. No cross-app authorization via content hash.

Page translation is a separate text-block interface using the existing text core, not a document upload or HTML/script rewrite. Its public API is deferred; document-service completion must not claim webpage translation is implemented.

## Consequences and execution

The [storage transition plan](../archive/plans/P5-D2-storage-and-ownership.md) defines implementation order and acceptance. Architecture diagrams live only in [Architecture](../Architecture.md). Update schemas, OpenAPI, clients and recovery tests together; inspect the implementation agent's branch before migration. Do not destructively collapse existing owned versions or job results to match this decision. P7 must revisit explicit edit/version requirements when it starts.

## Research informing this decision

These document public behavior, not undisclosed vendor storage internals. Our retention and current-result policies are product choices.

- [Moodle file internals](https://moodledev.io/docs/5.2/apis/subsystems/files/internals): shared content storage with separate logical references and access contexts. Our hash choice is SHA-256.
- [Azure document translation](https://learn.microsoft.com/en-us/azure/ai-services/translator/document-translation/latest/overview): source/target storage for batch processing and direct-return synchronous processing.
- [CloudConvert jobs](https://cloudconvert.com/docs/api-reference/jobs) and [exports](https://cloudconvert.com/docs/import-export/export-files): processing jobs, temporary outputs and export to caller storage.
- [Amazon Textract asynchronous operations](https://docs.aws.amazon.com/textract/latest/dg/api-async.html): idempotent request tokens and temporary/caller-controlled result storage.
- [Cloudinary transformations](https://cloudinary.com/documentation/image_transformations): processing-dependent derived assets and version-aware delivery.


## Owner amendment: desktop export destination, 2026-09-30

The desktop defaults to the current Windows Downloads known folder, or a user-selected export folder. The shell supplies an explicit destination for new main-window and Explorer submissions; do not derive it from the source path or mirror the source folder hierarchy. Language-tagged names and atomic numbered collisions remain. Source paths are temporary ingestion/retry metadata; export uses the accepted snapshot and does not require the original to remain in place. Successful publication clears the source path from the export journal. Previously accepted jobs retain their already-pinned export destination.
