# P5-P6 - Store and Display Document Processing Progress

Status: Proposed implementation plan requested by the owner. No production behavior is implemented by this document. Applies to the shared service used by the website, service CLI and future desktop app.

## Objective and scope

Show what each document is doing, preserve that information across refresh/disconnect, and expose the same facts to every client. Use one latest progress snapshot on the existing job row and the existing polling API. Do not build a progress-event service, event history table, broker, WebSocket/SSE infrastructure, overall percentage estimator or ETA system.

This task adds reporting, not translation/fit behavior. It does not add numeric/unit validation, another model review, a rendering loop, new fit algorithms or per-slide scheduling. The user's preference is minimal processing and honest feedback.

## Relevant architecture and starting point

- [Job lifecycle](../Architecture.md#job-lifecycle), [ADR-008](../decisions/ADR-008-job-execution-model.md), [P5 service plan](P5-server-and-service-cli.md) and [P6 UI plan](P6-web-ui-integration.md).
- ADR-008 already specifies `status`, `phase`, `progress_done`, `progress_total`, attempts, cancellation and lease fields. Reuse them. P5 owns the claim-token/fencing amendment and database schema; progress cannot bypass those predicates.
- Current core code reports `extract`, `translate`, `fit`, `write` through `TranslationProgress(phase, done, total)`. Extraction/writing are start/end events, translation counts unique initial engine inputs, and fit counts layout containers. Applying translations has no separate event.
- Translation may report `done == total` before formatting fallbacks complete. That is not completion of the translation stage or the document. Core stages have no current slide/sheet completion counts.
- The server is still scaffold in the inspected checkout. Database/API contracts below are targets, not claims of available endpoints. The latest implementation must be inspected before coding; another agent is changing the pipeline in the main checkout.

Local CLI `translate` continues displaying core callbacks without a database or persistent job history. Service CLI commands use the same stored job snapshots as the website.

## User-facing lifecycle

Keep job status separate from stage: `queued`, `running`, `succeeded`, `failed`, `cancelled` remain the only job statuses. Stages are detail while a job runs; warnings are result metadata, not job statuses.

| Event or stored phase | Visible label | Indicator |
|---|---|---|
| Client transferring bytes | Uploading | Byte percentage when the upload transport supplies a reliable total; otherwise spinner |
| Upload sent, awaiting acceptance | Preparing document | Spinner; uploading 100% does not mean accepted |
| `queued` | Waiting to translate | No percentage or invented queue position |
| `running / prepare` | Preparing document | Spinner during worker cache recheck/model readiness |
| `running / extract` | Reading document | Spinner |
| `running / translate`, `done < total` | Translating · 48 of 120 text sections | Stage-only count/bar, not overall document progress |
| `running / translate`, `done == total` | Finishing translation | Spinner until the next phase; formatting fallbacks may still run |
| `running / apply` | Applying translations | Spinner |
| `running / fit` | Checking layout · 12 of 30 text areas | Count/bar when total is positive |
| `running / write` | Saving translated document | Spinner through writing, verification and service persistence |
| `succeeded` | Ready to download | Download and report actions; optional Layout warnings indicator |
| `failed` / `cancelled` | Translation failed / Cancelled | Safe explanation and applicable action; no download for partial output |

These labels are presentation strings mapped from stable codes, not arbitrary server messages. Show no overall percentage. A translation percentage, if rendered beside its bar, is explicitly for that stage and appears only while `0 <= done < total`. `total == 0` never causes division or a 100% claim. Model calls can take time without emitting a new count; do not animate fake increments.

Use text-section counts for all formats in this release. Deduplication means these are unique translation inputs, not slide/page/cell counts. Keep a long paragraph as the pipeline's existing input unit; do not alter segmentation for a progress bar. Do not claim Word page counts or completed slides/sheets. Such context is deferred until a real need justifies mapping all inputs and fallback outcomes to locations.

TXT skips layout checking. Other formats reflect the actual fit callback and final report. `passed` means no measured adjustment was required; `adjusted` means changes were applied; `unresolved` means some locations could not be measured or fitted, possibly alongside successful adjustments. Do not generate warnings before fit finishes, infer warnings from elapsed time, or describe every unresolved result as confirmed overflow.

No-text/already-target-language results can skip translation. Display the existing result diagnostic and available output; never simulate translation stages that did not run.

## Storage and API contract

Use the existing jobs table fields `phase`, `progress_done`, `progress_total`; add `progress_updated_at` (nullable UTC timestamp) for the last saved progress snapshot. Counts are nullable nonnegative integers. Both are null for indeterminate phases; both are set for translation/fit counts, with `done <= total`. Existing job timestamps cover submission/start/completion; do not add per-phase history or stage-duration tables.

The service phase set is `prepare | extract | translate | apply | fit | write`. Only `apply` is a new core enum value; `prepare` belongs to the worker. Job detail and list/batch-item responses expose the same nested projection of these columns:

```json
{
  "status": "running",
  "attempts": 1,
  "cancel_requested": false,
  "cache_hit": false,
  "progress": {
    "phase": "translate",
    "done": 48,
    "total": 120,
    "updated_at": "2026-09-28T20:00:00Z"
  }
}
```

This is an illustrative subset of the existing job response, not a new endpoint. Use `progress: null` before the first attempt and while requeued. Keep the last snapshot for failed/cancelled jobs to explain where they stopped. On success it may remain as historical detail, but `status` controls the Ready display. A cache hit can succeed with no progress snapshot; return `cache_hit: true` and the new owner's existing result/report links, without fabricating phases or copying the producer's progress.

Persist original/output/report blobs and owned document/version references through P5's existing storage contract. Fit status/counts come from the final version's report and existing document summary, not from the progress counter. Do not duplicate document text, model output, local paths, credentials or per-section records in progress. Job/progress retention follows P5 job retention.

## Core and worker changes

1. Emit extraction start before opening/parsing the format adapter so reading time is represented. Preserve callback cancellation/error behavior and cleanup if that early callback raises.
2. Add `ProgressPhase.APPLY`; emit its start after translation plus all formatting fallbacks return, before applying text to the in-memory document, and its end after application. Use the existing binary start/end convention internally. Update CLI phase presentation and callers/tests that enumerate phases.
3. Preserve current translation batching, reuse and counter semantics. The UI's Finishing translation state handles initial-batch completion without inventing fallback totals. No pipeline reordering solely to obtain a smoother bar.
4. Worker sets `prepare` after claim. Map core callbacks into the job snapshot. Normalize extract/apply/write counts to null in the service response; retain translation/fit counts. Clear old counts whenever phase changes.
5. Coalesce count updates to at most one DB write per second per running job, following P5. Persist phase changes and terminal outcomes immediately. Serialize updates; a buffered old-phase callback must never overwrite a later phase or terminal state. Dropping superseded intermediate counts is fine.
6. Persist only under P5's valid current claim/lease and running-state predicates. Keep cancellation checking and lease heartbeat independent of throttled progress writes. A quiet counter is not evidence that a worker died.
7. Leave the UI in Saving while the service verifies/stores blobs and commits its owned result. Only that successful publication transaction sets `succeeded`. A core `write 1/1` event alone cannot enable download.
8. On automatic retry/recovery, reset the snapshot in the requeue transaction; preserve the existing attempt count. Display Waiting to retry when `queued` with prior attempts. New attempts start fresh; progress is not a resumable translation checkpoint.

## UI and client behavior

- Use one shared polling coordinator/query layer for the visible active list, batch summary and selected detail. Poll about every two seconds while visible work is nonterminal, keep one request per resource in flight, back off to 5/10/30 seconds on network/server errors, and honor Retry-After. Stop active polling on terminal results/logout; refresh on focus, reconnect, new submissions or user actions. Suspend hidden-tab polling and refetch when shown.
- Reuse owned `GET /v1/jobs`, `GET /v1/jobs/{id}`, and batch detail/item endpoints. Include the snapshot in list/item results to avoid a request/timer per file. Use existing cursor pagination; load only visible pages. Do not infer global counts from a loaded page.
- A failed poll retains the last known state with Reconnecting feedback. It does not mark jobs failed or resubmit them. An unchanged counter while polls succeed continues showing the current stage. Authentication expiry triggers P6 reauthentication; session changes clear private query data and abandon old in-flight responses. Refetch after mutations so a stale poll cannot undo a confirmed cancellation.
- Upload percentage is client-only and need not be stored in the jobs table. After reload, recover accepted jobs from the backend. Unsubmitted local files require reselection under P6; browser storage is not authoritative job history.
- Keep progress bubbles for current work and completed results awaiting the user's attention, with a stable accessible list for large batches/failures. Preserve P6's owned opened/downloaded/dismissed/put-back behavior; wire these through its audited workspace/history contract rather than using translation success as acknowledgement. Clearing a bubble never deletes a document. This progress task does not add a separate notification system.
- Per-file display: filename, current label, count/bar when meaningful, and a cancel action while allowed. Show Cancellation requested after the server accepts the request; keep the underlying job state until the server confirms cancellation or already-committed success. Do not promise instantaneous interruption of a model call.
- Batch display uses server counts: e.g. 7 ready, 2 failed, 1 running. While submission is open, say 10 files submitted, adding more; a final denominator is unknown. Once sealed, derive finished outcomes from ready + failed + cancelled + rejected, labelled finished rather than successfully translated. Local unsubmitted/upload failures are shown separately. Do not average per-document percentages.
- Keep the main surface quiet: final unresolved fit adds one Layout warnings indicator and a link to the existing report. Detailed reasons and locations belong in result detail/report, not repeated toasts. Downloads stay available for successful unresolved results.
- Reuse P6's visual system. Keep readable text alongside color/icons, accessible progressbar semantics only for real counts, and polite announcements on meaningful phase/terminal changes rather than every counter tick. Do not move focus on updates. Respect reduced motion and maintain keyboard-accessible list/actions. Fast phases may be skipped between polls; do not insert artificial delays to display them.

## Implementation steps and files

1. Core reporting: `packages/core/src/doctranslator_core/{types,pipeline}.py`, affected CLI presentation and progress tests. Add apply events and test callback order/fallback behavior without changing translation results.
2. P5 snapshot: job model/migration, repository/worker and API schemas in `apps/server`. Add the timestamp, map/throttle/fence updates and include snapshots in owned detail/list/item responses. Ratify P5's existing claim/publication contract before implementing it.
3. P6 display: generated API types, shared queries, progress bubble/list/detail and batch views in `apps/web`. Replace prototype timer/random progress; preserve audited assets and interactions. The future desktop uses the same response, without a second job store.
4. Integration review: update the canonical Architecture progress/API reference and operating docs to match implemented behavior. Keep this plan proposed until reviewed; no phase or board completion is implied by drafting it.

## Acceptance and completion

| Test | Required evidence |
|---|---|
| Real file | Upload -> owned job -> real phase/count updates -> persisted file/report -> download; original unchanged |
| Formatting fallback | Initial count reaches total while fallback still runs; UI says Finishing translation, not Ready; apply begins only afterward |
| Publication boundary | Delay/fail blob publication after core write completes; job remains Saving or fails, never exposes a successful partial result |
| Cache hit | Immediate Ready using this user's result/report links; no fake translation animation or another user's IDs |
| Format differences | TXT skips layout; Office/PDF show actual supported events/reports; no fabricated pages/slides/sheets or division by zero |
| Refresh and network loss | Accepted work survives reload/disconnect; latest stored snapshot and result return on reconnect without duplicate submission |
| Retry/cancel/race | Counter resets on a new attempt; stale callbacks cannot overwrite current/terminal state; cancel/publication race obeys P5 |
| Long model call | Counter may stay unchanged while independent heartbeat preserves the lease; no timer-derived failure or percentage |
| Large/open batch | Bounded polling/writes/pages; accurate ready/failed/rejected counts and no fixed denominator before sealing |
| Ownership and UI | Two users cannot read each other's progress/results; accessible status/actions and reduced-motion behavior; no random/mock success |

Use existing fake-engine fixtures for deterministic delays/fallback/race tests, plus a real-engine smoke through the service. Run all six repository checks and P6 frontend/browser checks during implementation. Completion requires the acceptance above; this planning change does not claim those tests have been implemented or passed.
