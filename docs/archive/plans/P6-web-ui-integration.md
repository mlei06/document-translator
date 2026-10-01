# P6 - Audit and Integrate the Existing Web UI

> Historical plan. Retained for rationale and evidence, not current implementation instructions. Follow the [current specification](../../plans/unified-translator-design.md) and [execution checklist](../../plans/unified-execution.md).

Current amendment: [ADR-020](../../decisions/ADR-020-browser-accounts-and-decoding.md) authorizes basic email/password registration/sign-in and Lenny-accessible translator/decoding settings. It supersedes the access-key-only/no-password wording below; API-key sign-in remains compatible.

> Translator configuration is governed by accepted [ADR-019](../../decisions/ADR-019-configured-translators.md): selectable configured translator IDs, one default, explicit local/remote location and no automatic fallback. Desktop setup selects supported model downloads; hosted users select admin-enabled translators. Installer delivery remains D0/D1 work.


> Storage/identity revision, 2026-09-29: follow accepted [ADR-014](../../decisions/ADR-014-storage-ownership-and-retranslation.md) and [the storage transition plan](P5-D2-storage-and-ownership.md). These supersede earlier global-cache, version-0, desktop-library and conflicting retention requirements in this plan. Human/service ownership, local fresh exports, hosted current results and immutable job downloads are the target; implementation is pending.


Status: Owner-requested execution plan. Parent: Feature #9014. Implement after the combined P2-P5 backend acceptance gate; audit the mock earlier to identify API gaps. No existing mock is evidence of a working product.

## Objective

Integrate the existing agent-built mock UI into the accepted React/TypeScript application, preserving useful visual/interaction features while making all production data and actions real. The owner explicitly permits dropping, reworking or adding features to fit the design. The result must operate against the authenticated persistent backend and return actual translated files.

## Artifact Discovery and Baseline

Runnable mock: `docs/design/web-gui/prototype/lenny.html` with `prototype/assets/`, an exact copy of the owner's claude.ai artifact (version 13, 2026-09-27). It is a single HTML/CSS/vanilla-JavaScript file with no framework, lockfile or build step, and a simulated backend. [Runnable Prototype](../../design/web-gui/README.md#runnable-prototype) documents its source hash, run instructions, code map, feature inventory (real vs simulated), the owner decisions it reflects and its known gaps against this plan. The rest of `docs/design/web-gui/README.md` and its `assets/` hold the design notes and full-resolution art.

Before editing, record the exact source path/revision, framework/package lock, build/run commands, asset sources and screenshots in `docs/design/web-gui/AUDIT.md`. The README's inventory is a starting point, not the audit: verify it against the running mock. Run the mock and inspect every route, control and responsive state. Preserve a recoverable baseline through Git or an immutable source copy; do not overwrite the only artifact. Do not recreate the UI from the prose while claiming to have integrated the existing mock. If the artifact is unavailable, complete backend work and record this specific P6 blocker.

Inspect existing code for hardcoded users/files/stats, fake delays/progress, placeholder downloads, local-only persistence and mock API handlers. Inventory the actual implementation, including features not listed in the design notes. Do not install unrelated UI libraries or replace the visual system merely to make integration easier.

## Feature Disposition Audit

For every visible feature record: screenshot/route/component, current behavior, data/actions required, backend endpoint(s), keep/rework/drop/add decision and reason, resulting UX/error states, acceptance test. Complete this before large UI edits. Small reversible implementation decisions need no new owner confirmation; changes that weaken the fixed translation/privacy/preservation requirements do.

| Known concept | Integration rule |
|---------------|------------------|
| Lenny, meadow, day/night themes | Preserve useful art direction and polish where present. Mascot motion must not delay submission/status/download or obstruct readable controls. Respect reduced motion and persist only harmless theme preferences locally. |
| Username/password mock | Replace with the real P6 browser-auth flow. Do not invent a successful login or store long-lived API keys in localStorage. Signed-in identity comes from `/v1/me`. |
| Drag/drop and file swallowing | Keep as progressive enhancement to a labeled keyboard-accessible file picker. Show the complete pending file list, type/size validation and upload outcomes; animation never implies server acceptance. |
| Type/language confirmation | Type/validation/source detection are server facts. Browser extension guesses are provisional. Show `detecting`/unknown until the job reports resolved language; permit explicit source selection. |
| One target language per batch | Preserve as the normal flow, with per-file source detection. Reflect actual available engines/formats and limits from capabilities. Do not offer unavailable options. |
| Floating progress bubbles | Bind to real per-file job states/progress. Keep an accessible stable list/table for larger batches and all failures. Indeterminate progress is preferable to invented percentages. |
| Preview page | Always provide real document metadata and download. Normal UI does not show per-section fit issues, fit-warning badges or a required report viewer. PDF/TXT inline viewing may use authorized real output safely. Do not pretend a browser can render Office files. (Amended by ADR-023: the worker renders PDF and Office page images after publication, never delaying the download.) Rework unsupported previews to clear document details and download. |
| Comments requesting fixes | P7 edit jobs are out of scope. Remove/rework the action unless an explicitly scoped real P6 feedback feature is justified and persisted with ownership. No fake “fix applied” or comments implying translation changes. |
| History, counts and settings if present | Query owned persisted records. Add backend support only when needed for an audited in-scope feature; otherwise remove the misleading view. Do not infer global totals from one page of results. |

A drop decision removes the affordance from production rather than leaving an unexplained dead control. Disabled controls are appropriate only for a clear transient/permission state with an accessible explanation. Keep mock/demo fixtures in explicit development/test tooling excluded from production startup.

## User and Authentication Flow

Use the same stable users and owner checks as CLI/API. Recommended first-release browser flow: exchange a user's provisioned API key over HTTPS for an opaque server session, then discard the key from browser state. Rework the mock username/password form into a clear access-key sign-in unless an accepted company SSO integration replaces this contract. No new password database or public self-registration is implied.

P6's architect must extend the P5 authentication ADR and OpenAPI before coding:

- `POST /v1/sessions`: validate user key, rotate/create a server-side session, set Secure/HttpOnly/SameSite cookie, return user metadata and a CSRF token. Never return/store the long-lived key. Protect login against cross-origin requests and rate-limit failed attempts.
- `GET /v1/me`: works with session or API key; returns current identity. Define credential precedence and reject conflicting session/Bearer identities rather than silently selecting one.
- `DELETE /v1/sessions/current`: invalidate session and clear cookie. Logout also clears client query caches, selected files and owned-data views.
- Store only session-token hashes server-side, with user/key provenance, creation/idle/absolute expiry and revocation. Proposed defaults: 30-minute idle, 12-hour absolute lifetime. User disable, key revocation or logout invalidates associated sessions. Session expiration cannot destroy accepted jobs.
- Same-origin SPA/API in production. Protect cookie-authenticated mutations with CSRF token plus trusted Origin checks; no wildcard credentialed CORS. Local development proxy must preserve the same request semantics.
- Redirect unauthenticated users to sign-in with safe local return routes. After authentication, reload owned history. On expired session, stop polling, explain reauthentication and retain only safe resumable job IDs; every later request rechecks ownership.

Long-lived API credentials remain appropriate for CLI/API. Browser sessions are another transport for the same owner identity, not a separate user table. Never trust owner IDs, display names or cached browser identity for authorization.

## Saved Document Behavior

Apply ADR-014: library source records with current language results, not one library tile per attempt. Normal Translate reuses only the selected document's compatible current result. Translate again and Always generate a new translation send a new submission ID with force; network retries preserve that ID. Keep the old download during replacement, swap only after success, and preserve it on failure/cancel. Show active-target conflicts as the existing job. Offer Delete translation and Delete source with the concrete scope; source deletion revokes job-based downloads. Do not expose model ranking or version history. Temporary integration jobs are not permanent library entries.

## Real Workflow and Data Contract

Use the proposed [P5-P6 progress plan](P5-P6-document-progress.md) when replacing mock progress: stage-specific counts, indeterminate reading/applying/checking layout/saving, persistent snapshots and one bounded polling coordinator. Success comes from published backend results; initial translation counts reaching their total do not imply completion.

1. Sign in and fetch identity/capabilities. Show unavailable service/engine states honestly.
2. Select one/many supported files, target/mode and optional source override; show validation and estimated upload count, not invented translation duration.
3. Create batch and submit each file through the bounded P5 endpoints, assigning stable client item IDs before upload. Distinguish local validation, upload, accepted/queued, processing and completed states.
4. Handle admission 429 with retry/backoff and pause/resume controls. One file error does not discard accepted siblings. Browsers cannot resume access to arbitrary local files after reload: restore server jobs and ask the user to reselect unmatched unsubmitted files, validating hash/metadata before retry.
5. Seal completed submission batches; poll visible jobs/batch summaries at a bounded rate, back off on errors and stop on terminal/logout. Do not create one timer per file for large batches. Pagination/virtualization keep long batches responsive.
6. Job detail displays actual mode/source/target, cache reuse, timestamps, progress stage, safe failure diagnostics and authenticated downloads. During fit, show **Checking layout** and **Skip layout check**. A skip request stops remaining optional fit, keeps prior adjustments and proceeds through Saving to Ready. Follow the progress plan for pending/error/race behavior; do not show per-section fit problems or fit-warning badges. Technical report endpoints may remain available to API/tooling clients.
7. History is backend-backed and survives reload/device changes. Detail routes refetch by ID and handle deleted/not-owned/expired records. Local storage is never the history source of truth.
8. Download actual bytes through owned API routes, with safe filenames. Batch “download all” must honestly handle browser multiple-download restrictions; individual downloads remain available. If adding a ZIP export, design bounded authenticated streaming and retention as an explicit API extension with tests, not a client memory concatenation of an arbitrary batch.
9. Cancellation/deletion confirm the concrete target where needed, show pending/error state and reconcile server results. Cancelled jobs never become visual successes due to an animation timer. Logout or a second user's login must not expose the first user's cached data.

Use a generated OpenAPI TypeScript client/types; centralize transport/auth/error mapping. Keep local selection/animation state separate from server job state. Implement data fetching with one consistent cache/query strategy selected after inspecting the mock's dependencies. Never duplicate translation/fit/cache logic in React.

## Build and Integration Tasks

| Task | Deliverable | Exit evidence |
|------|-------------|---------------|
| P6.0 audit | Source inventory, baseline screenshots, feature disposition, API gap list | Every actual route/control accounted for; existing style/assets understood |
| P6.1 auth/API extensions | Session ADR amendment, schemas/routes, generated client | Real login/logout/expiry/revocation, CSRF and two-user tests |
| P6.2 import and connect | `apps/web`, retained components/assets, service data layer | Build runs; mock fixtures unavailable in production; real metadata/history |
| P6.3 workflows | Upload/batch/job/detail/download/skip-fit/error/recovery views | Browser completes real five-format workflow |
| P6.4 visual/accessibility | Responsive/reduced-motion/keyboard/error-state polish | Screenshots and interaction audit at desktop and narrow viewport |
| P6.5 ship | Static build served by backend, CI, operating docs/evidence | Fresh deployment and routed reloads work; full matrix below passes |

Add frontend install/build/typecheck/lint/component and browser E2E commands to package scripts and CI using the mock's reviewed/pinned toolchain where appropriate. Do not make Python-only CI look like complete P6 verification. Serve SPA fallback only for UI routes; `/v1` errors must never return HTML. No document content or private assets are sent to public analytics/CDNs.

## Browser Acceptance Matrix

| ID | Scenario | Required result |
|----|----------|-----------------|
| W01 | Sign in, reload, logout, expired/revoked session, switch users | Real stable identity, no leaked prior-user views/cache, correct reauth and owned history |
| W02 | Upload all five formats in both modes against real backend | Actual downloadable translated bytes; technical fit outcomes remain truthful; source hashes unchanged |
| W03 | Mixed batch with malformed/oversized/unsupported and duplicate-named inputs | Valid siblings complete; per-file outcomes, bounded admission handling, usable large-batch view |
| W04 | Repeat translation, change target/fit setting, force | UI reflects genuine cache hit/miss and returned identities, no fake instant completion |
| W05 | Disconnect/reload during upload/translation, restart server | Accepted jobs reappear; unsubmitted files are clearly identified for reselection; no duplicate accepted jobs |
| W06 | Cancel, failed engine, skip fit, unresolved fit, delete/expire document | Skip during fit reaches a real downloadable result after saving; late/repeated requests reconcile correctly; no unresolved-section UI or fit-warning badges; truthful failures and no stale download bypass |
| W07 | Keyboard, focus, screen-reader names, narrow viewport, reduced motion, day/night contrast | Usable alternative to drag/drop/mascot; readable progress/errors; no motion-dependent interaction |
| W08 | Audit every visible control and production network request | Real scoped backend behavior or documented removal/rework; no fake users/stats/results/timer completion, no external document leakage |

Use deterministic backend fixtures for failure/race UI tests in addition to real engine smoke flows. Capture representative final screenshots and inspect them for clipping, alignment, contrast and obstructed controls; fix evident defects. Test routed refresh, empty/loading/error states and second-machine internal TLS access. Record results plus the feature audit in `docs/archive/plans/P2-P6-release-evidence.md` during implementation. All six Python checks and frontend checks/CI must pass before P6 closes.
