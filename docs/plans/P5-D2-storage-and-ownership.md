# P5-D2 - Storage and Ownership Transition

Website follow-on: [ADR-028](../decisions/ADR-028-website-cache-and-retention.md) and [the cache/retention specification](website-cache-and-retention.md) supersede permanent-library/current-pointer-only reuse for new website work after cutover. Preserve this plan's legacy saved guarantees, API saved/temporary and desktop behavior. The follow-on is specified, not implemented.

Status: Implementation handoff for accepted [ADR-014](../decisions/ADR-014-storage-ownership-and-retranslation.md), 2026-09-29.

Progress (2026-09-29, `release/p2-p6`): items 1-7 and 10's hosted parts are implemented in the service (owner kinds, `documents`/`document_translations`/`job_results`, saved and temporary retention, retranslation without re-upload, one active job per document and target, fenced publication with current-pointer swap, deletion fencing, retention and quota, migration 0002 converting existing data). Item 8 (desktop local export) is desktop-track work; item 9 (P6 library UI) is in progress. The routes use `/v1/documents/{id}/translations` and `/v1/jobs/{id}/file` as proposed; the earlier `/versions/0` routes were never released and are removed. This amends P5/P6 and D0/D2, not translation algorithms or model integration.

## Starting point and precedence

The inspected documentation worktree has a scaffold server (`app.py`, settings and empty auth/db/jobs packages), not an implemented storage layer. Other agents are implementing P2-P6 separately. Inspect their actual schema/routes before applying this plan. ADR-014 supersedes earlier global cache, mandatory version-0, desktop history/cache and saved-document expiry contracts. Preserve queue fencing, ownership, progress/fit skip, format fidelity and engine behavior.

## Bounded work

1. Reconcile P5 design/migrations with owner kinds human/service. Reuse the existing owner table; no parallel application-user system. Key revocation, disabled owners, session isolation and scoped credential rules apply to both kinds where relevant.
2. Define logical source documents separately from blobs and translation results. Suggested entities are `owners`, `documents` (owner/source/name/external reference), `document_translations` (document/language pair/current result), `job_results` (immutable output/report/fingerprint/fit metadata), existing `jobs` and blob metadata. These are conceptual names; use the implementation's naming where equivalent. No new global translation-cache or edit-version table is required.
3. Implement saved/temporary request retention and local-export runtime behavior. Saved lookup checks only the selected owner's logical document's current compatible result. Temporary and local export always execute. Pin source/options/model on acceptance and report requested/resolved language distinctly.
4. Add saved-document submission and retranslation without reupload. Canonical proposed routes: `POST /v1/documents/{id}/translations` with target/options/submission ID; `GET /v1/documents/{id}/translations`; `GET` and `DELETE /v1/documents/{id}/translations/{translation_id}`; `GET /v1/documents/{id}/translations/{translation_id}/file`; `GET /v1/jobs/{id}/file` and `/fit-report` for immutable job results. All lookups enforce ownership, deletion and expiry. Replace earlier `/versions/0` contracts in generated clients; if already shipped, introduce explicit compatibility/deprecation rather than silently repurposing them.
5. Enforce one active saved job per document/target slot in the DB. Same idempotency key replays; different key gets 409 and owned active-job ID. Serialize admission with deletion. Recheck reuse before processing. Force skips both lookups; skip-fit results never satisfy full-fit reuse. Record cache_hit only when actual reuse occurs.
6. Write and verify new blobs, then fenced publication creates the immutable job result and atomically updates the current translation pointer. Retain the previous pointer on failure. Job downloads stay pinned to their own results. Delete/cancel/disable-owner can fence publication. Account for pending output space without evicting saved documents automatically.
7. Add reference-safe cleanup, bounded terminal job/result retention and advertised temporary expiration. Proposed operational starting values, to be ratified in P5.0: temporary hosted results and abandoned local working files 24 hours after terminal state; superseded hosted job outputs 7 days; terminal metadata 30 days. These never expire current saved documents or active/recoverable work. Choose per-owner byte quotas from deployment disk capacity before launch; expose configured limits in capabilities and test enforcement.
8. Desktop uses existing authenticated local host/queue, with no persistent reuse or library. Add trusted native export publication/reconciliation, output-root exclusions, safe relative paths, atomically numbered filenames and cleanup after acknowledged export. Keep private temporary input snapshots only while needed. Crash between rename and acknowledgment must recognize the same reserved output/digest rather than produce another numbered file. Destination write failure is an export failure with retry, never a false completed export.
9. P6 library shows sources with current language results, Download, Translate again, Delete translation/source and Always generate a new translation. Keep the old result downloadable while replacement runs. No model-ranked replacement or version-history screen. One active job per target makes repeat-click behavior explicit. The future desktop only needs active/recent operation outcomes and output locations, not a saved document library.
10. Provide one service-account document integration example: external authorization -> temporary job -> poll -> download -> attach in caller. Keep app credentials out of frontend code. External references cannot bypass permissions; webpage text translation remains deferred.

## Migration and rollout

Inspect actual implemented tables and deployments first. For a fresh scaffold, create the target schema directly. For existing stored data, back up and use additive migration: preserve document ownership and job-result bindings, establish current pointers deterministically from each document's successful results, and leave historical references until their announced retention expires. Do not merge business documents solely on matching hash. Report conflicts for review rather than deleting results. Update ADR-007 references, API schema, generated clients and operating docs in the same implementation changes.

## Acceptance

| Scenario | Required result |
|---|---|
| Two users upload identical bytes | One physical source blob, independent private records; hash knowledge cannot read/attach another user's document |
| Two case attachments contain identical bytes | Independent logical attachments may share bytes; replacement/deletion does not cross their boundaries |
| Normal repeat / changed settings / force | Compatible saved result reused; incompatible or force request runs; temporary/local always run |
| Lost submission response | Same ID returns same job even with force; no extra model run from transport retry |
| Concurrent same target / different target | Same-target admission conflicts safely; different targets may run concurrently |
| Replacement failure, cancellation or deletion race | Old success preserved on failure/cancel; deletion cannot resurrect source/output or permit job-download bypass |
| Job A replaced by job B | Library returns B; retained job A returns exactly A until its advertised result expiry |
| Fit skipped | Output downloadable/current, actual skipped metadata, no full-fit reuse; no hidden old-cache retention |
| Local repeat / filename collision / parallel export | Fresh processing and unique numbered outputs; originals/prior exports untouched |
| Crash during input/export or destination unavailable | Source snapshot/digest and reserved output reconciled; clear recoverable outcome, no corrupt final file or duplicate acknowledged export |
| Cleanup while upload/publication/download active | Pins/references prevent deletion races; exported local files never removed by GC |
| Quota and retention | No silent saved-document expiry; bounded temporary/history data; clear storage rejection and advertised expiry |
| Service identity isolation | Calling app owns jobs; no browser credential exposure or arbitrary owner injection; external references are not permissions |

Run all six root checks plus relevant DB/API, real-file E2E and P6/native export tests during implementation. Record evidence without claiming a documentation change implements these behaviors. Do not change phase completion or board status merely for this plan.
