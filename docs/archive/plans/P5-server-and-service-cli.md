# P5 - Persistent Service, User Flow and Service CLI

> Historical plan. Retained for rationale and evidence, not current implementation instructions. Follow the [current specification](../../plans/unified-translator-design.md) and [execution checklist](../../plans/unified-execution.md).

> Storage/identity revision, 2026-09-29: follow accepted [ADR-014](../../decisions/ADR-014-storage-ownership-and-retranslation.md) and [the storage transition plan](P5-D2-storage-and-ownership.md). These supersede earlier global-cache, version-0, desktop-library and conflicting retention requirements in this plan. Human/service ownership, local fresh exports, hosted current results and immutable job downloads are the target; implementation is pending.


Status: Detailed execution contract for the pre-GUI handoff. Shared-service CLI is accepted in ADR-010. Authentication and exact database/lease contracts must pass P5.0 architect review and be recorded in accepted ADRs before production work. Parent: Feature #9013.

Progress (2026-09-29): P5.0 accepted (ADR-015, ADR-016). P5.1-P5.6 implemented: storage/auth, REST vertical slice, durable worker, batches/idempotency, service CLI and operations (retention, backup/restore), with API, queue-race, storage, auth and cross-process E2E tests (including a killed-worker recovery). P5.7 real-engine evidence recorded for R01, R05 and R12 in the release evidence; R14 (second machine) and CI remain open. Browser sessions are P6.

## Scope and Dependencies

Build FastAPI REST, users/credentials, immutable storage, database jobs/workers, cached results, bounded batches and CLI HTTP commands. P2 is the development dependency; P3/P4 are required for pre-GUI release acceptance. No React UI, MCP implementation or agent editing in this phase.

Existing server and CLI packages are scaffolds. Preserve ADR-003 boundaries: CLI never imports server; routes call jobs; jobs/auth use repositories; only jobs executes the core pipeline. Server settings prepare core identity without loading models. Serve and worker remain separate processes.

## User Journey

Progress persistence/display is specified in the proposed [P5-P6 progress plan](P5-P6-document-progress.md): reuse ADR-008 job fields, throttle snapshots, fence updates and expose them through existing owned job/batch routes. It adds reporting, not another queue or event-history service.

1. Administrator installs the service, runs migrations, provisions internal TLS/fonts/model identity and creates a user with a stable UUID, display name and optional external subject reserved for future identity integration. Display name is never an authorization key. No public signup in this release.
2. Administrator issues a credential for that user through a local administrative command, delivers it through an approved private channel and never commits it. The user configures the service URL and credential through environment or an OS-backed credential store. Command history, resume manifests and logs never contain the secret.
3. CLI calls `GET /v1/me` and capabilities to show the authenticated identity and supported modes/formats/limits before submitting. A raw API client uses the same Bearer credential. Invalid/revoked credentials produce 401 before creating owned records.
4. User creates a batch, submits files and chosen translation options, and receives per-file job/member IDs. The service derives `owner_id` from authentication; callers cannot choose or override it. Batch, job and document creation use that same owner.
5. The user can list their batches/jobs/documents, check per-file progress and disconnect safely. A resume manifest stores batch/item/job IDs and local file metadata. Subsequent requests reauthenticate; possession of a job ID or manifest is not authorization.
6. Bind the job to an immutable owned result. In saved mode, reuse or update the selected logical document's current language result; temporary mode has no library entry. Return owned IDs, never another owner's IDs or storage paths.
7. User downloads individual documents and reports or has the CLI download all successful batch items. Each file has a distinct local destination. Failed/cancelled items remain visible alongside successes. Normal web/desktop UI shows Checking layout with Skip layout check, then Saving and Ready; technical fit details are optional API/tooling data.
8. User may cancel their jobs or delete their documents. Revoking a key blocks future requests; disabling a user blocks all credentials and new publication under the disabled-user policy below. Existing data follows retention, never transfers ownership by renaming an account.
9. Administrator can rotate/revoke credentials, disable users, inspect operational metadata and run backups/retention. Normal user routes never bypass ownership for an administrator. Any future administrative content-access feature requires a separate explicit contract.

## P5.0 Authentication Decision to Ratify

Use per-user opaque API keys for the internal pre-GUI release. This is the concrete recommended contract for the authentication ADR; P5.0 verifies it against the company deployment before acceptance. Browser login/SSO/OAuth belongs to later design, not an excuse to omit ownership now.

- Generate at least 256 random secret bits, with a non-secret lookup prefix. Store only a cryptographic digest of the random secret, key ID/prefix, user ID, timestamps, label and revocation state. Compare digests in constant time. Do not store retrievable plaintext keys.
- Provision/rotate/revoke through `doctranslator-server users ...` and `keys ...`, restricted to local OS administrators of the deployment. Show a new secret once; do not print it in ordinary logs or evidence files. Key rotation can briefly overlap two keys for the same user.
- `users`: stable ID, display name, active/disabled state, created timestamp; optional future `(issuer, subject)` unique identity mapping. `api_keys`: many keys per user. Deleting a credential does not delete its user's documents.
- Bind to loopback by default. Non-loopback deployments require HTTPS with the company CA, either directly or through a documented trusted reverse proxy. Do not trust caller-supplied identity headers; terminate TLS without disabling client certificate verification. No unauthenticated network mode.
- All user routes authenticate before lookup and enforce owner filters in repository queries. Return the same 404 for absent and other-user resources. List pagination, batch membership, job cancellation, document/report/original retrieval and deletion all apply ownership checks.
- Disable-user operation rejects new requests and requests cancellation of queued/running jobs; completion checks user-active status and cannot publish after disable commits. Already stored documents remain retained but inaccessible until reactivation or authorized cleanup. Revoking one key alone does not cancel accepted work if the user remains active.
- Record audit events for user/key administration, submission, cancellation, deletion and outcomes using IDs and safe error codes. Never log Bearer headers, source text or secrets. ADR-014 scopes reuse to the owner; shared bytes and content hashes provide no cross-owner lookup or access endpoint.

## REST Contract

Use `/v1`, JSON metadata and OpenAPI. Server-generated opaque IDs are UUIDs. UTC timestamps are RFC3339. All list endpoints use stable cursor pagination, default 50/max 200. No endpoint exposes absolute paths or arbitrary blob-hash retrieval.

| Method/path | Request and response contract |
|-------------|-------------------------------|
| `GET /v1/me` | Authenticated user ID/display name; no key material |
| `GET /v1/capabilities` | Available formats/modes, fit status support, effective limits, service/core versions; no internal endpoint/path secrets |
| `POST /v1/batches` | Optional label plus client-generated idempotency UUID; creates an owned open batch, 201; replay returns same resource |
| `GET /v1/batches`, `GET /v1/batches/{id}` | Owned history; lifecycle `open`/`sealed`, counts by member/job status and paginated item link |
| `POST /v1/batches/{id}/items` | One streamed multipart file, JSON options, stable `client_item_id` UUID. Creates one accepted job or a recorded rejected member; never translates synchronously |
| `GET /v1/batches/{id}/items` | Ordered cursor page of item ID/client ID, safe original name, rejection or job ID/status, document/result links when available |
| `POST /v1/batches/{id}/seal` | Stops new member IDs; idempotent replays remain queryable. Accepted jobs already execute while batch is open |
| `POST /v1/batches/{id}/cancel` | Seal and cancel outstanding owned jobs. Completed outputs remain; operation is idempotent |
| `POST /v1/jobs` | Same one-file submission contract without a batch; client submission UUID required |
| `GET /v1/jobs`, `GET /v1/jobs/{id}` | Owned status/progress, attempts, cache_hit, safe error or result links; no other-user result IDs |
| `POST /v1/jobs/{id}/cancel` | Idempotent cancellation; already completed job remains completed |
| `POST /v1/jobs/{id}/skip-fit` | Owned, stage-gated cooperative skip; preserve translations/prior adjustments and save. Persist the request and enforce races/cache rules in [the progress plan](P5-P6-document-progress.md#skip-layout-check). |
| `GET /v1/documents`, `GET /v1/documents/{id}` | Owned history, original name, languages/mode, originating job/current translation links, created/expiry timestamps and fit summary |
| `GET /v1/documents/{id}/translations/{translation_id}/file` | Current owned translation; safe Content-Disposition, content type, size and SHA-256 digest |
| `GET /v1/jobs/{id}/file`, `GET /v1/jobs/{id}/fit-report` | Exact immutable job output/report until advertised expiry; deletion also revokes access |
| `POST /v1/documents/{id}/translations` | Translate saved source without reupload; target/options, submission ID and optional force flag |
| `GET /v1/documents/{id}/translations` | Current language results and active work |
| `GET`, `DELETE /v1/documents/{id}/translations/{translation_id}` | Inspect or remove this owned language result; deletion fences work for this slot |
| `GET /v1/documents/{id}/original` | Stream the owned original; no direct storage URL or ownerless hash lookup |
| `DELETE /v1/documents/{id}` | Remove user's access/references under retention contract; preserves other owners' references; cancels/fences active work and revokes job-based downloads |

Schemas: hosted requests select `retention=saved|temporary`; the website uses saved and the integration example uses temporary. A desktop-profile host enforces local-export behavior. Options carry requested source/target, mode, protected terms, TXT encoding, fit settings and `force_retranslate`; engine endpoints/artifact paths are deployment settings, never arbitrary caller-supplied URLs. Source resolution is per file even in a batch. Returned job metadata includes original name, format, owner ID, source requested/resolved, target/mode, fingerprint, status, progress, submitted/completed timestamps, document ID and fit status when available.

Error envelope: `{code, message, request_id, retryable, details}` with safe field/location details. Use 400 malformed transport, 401 authentication, 404 absent/not-owned, 409 conflict/idempotency mismatch/sealed new item, 413 file too large, 415 unsupported format, 422 invalid options/document, 429 admission quota and 503 temporary infrastructure unavailability. No traceback or source-text echo. Post-acceptance failures live in the job resource rather than retroactively changing its submit HTTP response.

### Submission, Idempotency and Batch Failure

Stream to bounded staging and compute the input digest; never load a whole batch into memory. Validate type/content/options and resolve an output fingerprint before acceptance. For a batch item, return 201/202 with the item/job, including immediately succeeded cache hits. For a fully read invalid file/options, persist a rejected member keyed by `client_item_id` and return its ID with 415/422 so the batch accounts for the failure. Authentication, oversized transport, malformed multipart and admission rejections need not create a member; the client records these unaccepted attempts separately. Seal responses and CLI summaries distinguish server members from locally rejected/unsubmitted entries.

Use unique `(owner_id, submission_id)` for standalone submissions and `(batch_id, client_item_id)` for members, with canonical options and input hash bound to the identity. Same identity and same request returns the original outcome/job; different bytes/options returns 409. Two concurrent identical requests produce one job. Idempotency is submission recovery, not content caching; distinct IDs request new work, subject to the saved-document active-target conflict rule; byte identity alone is not request idempotency. Keep bindings while their batch/job records remain. An expired identity must return a documented expired outcome/tombstone during the retry horizon, not silently duplicate an old accepted job.

The client records its submission identity before network I/O. After uncertain submission, it reuses the identity; it never generates a new ID just because the connection timed out. Seal cannot race a new accepted member: membership validation and insertion are one transaction. Batch cancellation prevents later acceptance. Query accepted item by client ID to recover an uncertain result without reuploading; define that filter in OpenAPI. A manifest changed on disk requires a new submission identity, not mutating the old request.

No giant multi-file multipart or downloadable ZIP is required. API users submit one item repeatedly; CLI provides the multi-file convenience and downloads successes individually. A batch aggregates records, not translation work or engine lifetime. Retried rejected items use a new client ID; the original outcome remains auditable.

## Storage and Database Contract

P5.0 writes the exact ORM/migration/repository schemas before coding. Required entities and constraints:

- Users/API keys as above; batches own member rows, jobs and documents reference stable owner IDs with foreign keys. Never rely on a caller-supplied owner filter.
- Batch members hold ordinal/client item identity, original safe filename, submission binding and either job reference or safe rejection. Batch lifecycle is stored, processing counts derived from members/jobs; do not maintain a competing batch queue/state machine.
- Jobs include ADR-008 fields plus original blob, canonical options, immutable requested engine/fingerprint identity, owner/batch reference and per-attempt claim token. All timestamps use one agreed time source per deployment.
- Owners have `kind=human|service`. Applications enforce their own end-user permissions and authenticate from their backend; external references confer no translator permissions.
- Owned logical source documents reference immutable source blobs. Current translation slots are unique per document/resolved language pair and reference immutable job results containing output/report/fingerprint/fit metadata. No global `translation_results` cache or mandatory edit-version table is required.
- Hosted saved lookup uses only the selected owner's logical document and current compatible result. Temporary mode and local-export profile bypass persistent reuse. Source/content hashes do not merge separate business attachments or confer access.
- Jobs keep their exact result reference until expiration. Replacement swaps only the library's current pointer, after verified blobs and one fenced success transaction. Failures preserve the old pointer. Fit-skipped results may become current but cannot satisfy full-fit reuse.
- Admission permits one active job per saved document/target; distinct concurrent submissions get an owned conflict, while same-ID retries replay the same job. Force bypasses reuse, not idempotency. Different targets may execute concurrently.
- Store immutable files by hashes, never caller-controlled server paths. Coordinate staging/publication pins with cleanup. Deletion revokes all document/job download access and fences active publication; it cannot delete another record's shared bytes.
- Saved originals/current translations remain until deletion within quotas. Temporary results, superseded job outputs and terminal metadata have separate configured expiration, exposed to clients. Local exports retain only temporary working files and minimal bounded recovery records. See the transition plan for operational defaults and tests.

### Reference-Safe Cleanup

Specify upload/publication pins so GC cannot delete a just-written blob before its DB references commit. Use DB-visible pending/pinned blob records and a deletion claim/tombstone: publication must atomically verify availability and add references, while GC atomically proves no references/pins and marks deleting before physical deletion. Publishers encountering deleting blobs wait/re-put safely. Never use an uncoordinated "query count then unlink" algorithm. A grace interval alone is not the concurrency proof.

Retention runs transactionally on references, then performs retryable physical deletes. Saved originals and current output/report references remain live independently of temporary job-result expiration. Backup drains/stops writers and retention, checkpoints/snapshots the DB, copies all referenced blobs and records hashes; restore verifies both before serving. P5.0 documents exact commands for the chosen deployment.

## Queue, Cancellation and Recovery

Before coding, explicitly amend ADR-008's worker-only completion wording to this attempt-fenced contract:

- Claim a queued, available, noncancelled job with one conditional update, increment attempts, assign a fresh unpredictable claim token and worker ID, and lease it. Return ownership only when exactly one row changes.
- Heartbeat, progress, retry/failure and completion require matching job ID, running status and claim token. Heartbeat/completion also require a live lease. Completion transaction additionally checks no cancel request and active owner. A stale attempt cannot publish even if the same worker process later reclaims the job.
- Heartbeat runs independently of model/progress callbacks. On lost claim, stop publication and abandon temporary work; native model calls may finish before cooperative cancellation can take effect.
- Recovery claims expired running rows conditionally on their old token/lease. Requeue within attempt budget; otherwise fail. Cancellation of expired jobs wins over requeue.
- Queued cancellation becomes terminal immediately. Running cancellation records a flag, observed between batches and at final commit. If success committed first, cancellation returns the existing success; if cancellation committed first, success is forbidden. Define and test the transaction ordering.
- Retry only transient engine/network failures, never unsupported input, authentication, malformed output, preservation failure or an invalid document. Core engine retries and job retries both count toward a documented bounded execution budget.
- No partial output is cached/published. Independent workers/models are bounded by host memory; one `Translator` instance is never used concurrently across threads.

## Initial Operational Defaults

These are proposed starting settings for P5.0 validation, not measured capacity claims. Pin effective values and adjustments in the operations ADR and Deployment before production coding. Limits must be visible through capabilities and shared by CLI/API validation.

| Setting | Initial contract |
|---------|------------------|
| File upload | 100 MiB per file, streamed; no multi-file request |
| OOXML expansion | 1 GiB total, 128 MiB per entry, 20,000 entries, maximum compression ratio 1000; reject duplicate/unsafe paths, DTD/entity expansion |
| Upload concurrency | CLI 2, configurable 1-8; server global/per-user admission bounded separately |
| Queue admission | 1,000 nonterminal jobs globally, 200 per user; reserve admission atomically, return 429 + Retry-After when full |
| Workers | 1 by default; configurable after memory measurement, models reused per worker |
| Poll / heartbeat / lease | 1 second idle poll, 20-second heartbeat, 120-second lease; database clock for multi-host |
| Retry | 3 total attempts; backoff 10 then 30 seconds; deterministic bounds, transient errors only |
| Progress writes | At most once per second except phase/terminal changes; separate heartbeat |
| SQLite | WAL, foreign keys on each connection, 5-second busy timeout; short transactions, migrations only |
| Retention | Saved originals/current results until deletion within quota. Proposed P5.0 defaults: temporary results/staging 24 hours, superseded job outputs 7 days, terminal metadata/bindings 30 days; active/recovery/download pins excluded. Advertise expiry and preserve live result provenance independently of expiring jobs |
| Upload timeout | 15-minute total request budget, configurable for internal network; admission reservations expire safely |

P2 parser limits apply to local and service use; service may impose stricter bounds, not bypass core limits. Document and page/segment/container limits also need P2/P4 fixture-based settings. Limit exhaustion is explicit failure/backpressure, never truncation. No execution-timeout may silently kill a healthy job while leaving a publishable stale claim.

## Service CLI Contract

Proposed command grammar to implement and document exactly (these commands do not exist yet):

```text
doctranslator submit FILE... --to en --mode mt --wait --download-dir OUT
doctranslator submit --manifest files.jsonl --to en --mode llm --resume-state run.jsonl
doctranslator batches status BATCH_ID --json
doctranslator batches cancel BATCH_ID
doctranslator jobs list --json
doctranslator jobs status JOB_ID --json
doctranslator jobs cancel JOB_ID
doctranslator download --batch BATCH_ID --output-dir OUT --report
doctranslator download --document DOCUMENT_ID --output-dir OUT --report
```

Service URL comes from `--server` or `DOCTRANSLATOR_SERVER_URL`; credential from `DOCTRANSLATOR_API_KEY` or OS vault, never a `--key` argument. No service command loads models or LLM credentials. `translate INPUT ...` remains the local P2 command and clearly states no server history/cache.

Manifest is UTF-8 JSON Lines, one `{path, source?, target?, mode?}` per item; paths resolve relative to the manifest. Explicit per-item options override submission defaults. Process incrementally; use a bounded work window, and append durable client IDs/status to resume state before advancing. A resume run merges by client item ID, checks local file hash/options and authenticates as the original user/service. Different identity or changed source is an explicit conflict. Do not store credentials in resume state.

Default service `submit` returns accepted IDs after uploads; `--wait` polls with bounded intervals until terminal, then optional downloads. No implicit download without an output directory. CTRL-C stops local waiting/upload scheduling without cancelling already accepted jobs; print/save the batch ID and leave resumable state. Explicit cancel does server cancellation. Interrupted open batches may be resumed or sealed; they do not block workers.

The CLI accepts individual paths or a manifest; shell globs may be expanded explicitly by the CLI only under a documented option, never silently reinterpret filenames. No archive ingestion or recursive directory traversal by default.

Use safe filenames containing sanitized source stem, target and document ID to prevent same-name collisions, with original format suffix; report file lives alongside it. Download to a private temporary path and atomically publish after size/hash verification. Refuse existing destinations unless an explicit overwrite option is supplied; never overwrite an input. Ignore server path separators in suggested filenames. Retry an interrupted download from scratch unless ranged transfer is explicitly implemented and validated.

Progress on stderr, machine-readable per-item JSON Lines on stdout when requested; summary includes accepted/rejected/unsubmitted/succeeded/failed/cancelled/unresolved/download-failed counts. Exit 0 when the requested operation succeeds; 1 when a completed batch/download has any failed/rejected/cancelled/unsubmitted item; 2 invalid configuration/auth/usage; 3 service/network failure preventing completion; 130 local interruption. Unresolved fit is visible success by default; `--fail-on-unresolved` makes it exit 1 without discarding outputs. `submit` without `--wait` means accepted, not translated; state that in output.

## Implementation Tasks and Tests

| Task | Primary files | Required acceptance |
|------|---------------|---------------------|
| P5.0 contracts | auth/operations ADRs, ADR-008 amendment, Architecture, this plan | Exact schemas, defaults, transaction predicates, user flow and OpenAPI examples accepted by architect review |
| P5.1 storage/auth | db models/repositories/migrations, auth, jobs storage, server admin CLI | Empty migration, user/key lifecycle, ownership, immutable blobs and pinned GC |
| P5.2 single-file vertical slice | jobs service, REST, fake worker/core | Authenticated submit -> cache/miss -> owned download/report, no worker needed for cache hit |
| P5.3 durable worker | queue/worker/notifier, serve/worker commands | Kill/reclaim/stale-result/cancel/race tests; independent heartbeat; bounded models |
| P5.4 batches/idempotency | batch/member repositories/service/routes | Streaming long batch, retries after lost response, per-item errors and sealing races |
| P5.5 service CLI | CLI HTTP/settings/manifest modules | User-facing subprocess E2E against actual test server, no server imports/model loading |
| P5.6 operations | retention/backup/startup and Deployment | Disk pressure, retention during active writes, restore hashes, TLS from second host |
| P5.7 integrated release | cross-surface E2E and release evidence | R01-R14 across all five formats with P3 fit and real engines |

Use real temporary SQLite databases and separate processes for claim/death/recovery tests; fake pipelines for deterministic races. Inject time/engine hooks where needed rather than timing-dependent sleeps. Test two owners on every nested resource and recovery path, including deleted documents and revoked keys. Test size/quota races and ensure a malformed member does not lose siblings.

## Completion and Handoff to P6

All P5 functional criteria and the combined P2-P5 release matrix pass. OpenAPI, examples, CLI help, bootstrap, migration, service startup, company TLS, retention and restore instructions match executable commands. Run all six root checks, meaningful integration/native tests and reviewed-commit CI. The evidence includes exact user IDs as synthetic fixtures, never real credentials. P6 receives this working authenticated API; no GUI or MCP work is needed to satisfy this milestone.
