# P2-P6 - Document Translation Delivery Handoff

## Start Here

This is the entry point for the agent implementing the owner's requested release: P2-P5's complete persistent translation service, followed by P6's audit and integration of the existing mock web UI. Read `AGENTS.md`, `README.md`, `docs/Architecture.md`, accepted ADRs, then this plan and its phase plans. Architecture remains consolidated in `docs/Architecture.md`; this file specifies execution and release acceptance.

The owner explicitly chose a shared service for CLI/API and preservation of XLSX sheet names, then extended the handoff to include the existing mock UI in P6. Those choices supersede the older local-only CLI and mandatory sheet-translation wording. Supported file families are TXT, PPTX, DOCX, XLSX and text-based PDF. OCR, legacy binary Office formats, arbitrary archive uploads, P7 MCP/visual edits and P8 integrations are excluded. P6 may preserve, rework, drop or add UI features to match the working system; no fabricated backend behavior may remain in production.

## Required Outcome

A user supplies one file or a mixed-format batch through the CLI or REST API. Every accepted file gets its own durable job. The service checks the complete-output cache, translates misses with the selected SMALL-100/Gemma mode, fits applicable containers against the original, persists the original/output/report and returns owned download references. Successful files remain available when siblings fail or the client disconnects. Restarting the service does not lose accepted jobs or completed results.

"Any number of files" means a streaming/resumable manifest with no fixed total batch-count ceiling. It does not mean an unlimited multipart request, unlimited memory, unbounded worker concurrency or unlimited disk. Admission limits are observable and retryable; no file is silently skipped. A batch can exceed the number of jobs allowed to wait simultaneously because workers drain it while the client submits further items.

"Fit checked" means the actual P3/P4 measurement policy ran on all required supported containers. TXT and documents proven to contain no applicable containers report `not_applicable`; other Office/PDF results report `passed`, `adjusted` or `unresolved`. `not_run` is forbidden in a successful pre-GUI service result. An unresolved fit report is a complete result under ADR-007, not a claim that every output is visually perfect. Missing/unsupported measurement must be explicit and counted as unresolved, never as a pass or an empty-container result.

## Current Starting Point

- Implemented: P1 text engines, per-call deduplication, typed config/errors, evaluation app and enforced package boundaries.
- Scaffolds: document API/pipeline, all format adapters, fit, product CLI and server. Inspect files before editing; do not assume plan signatures already exist.
- P1 delivery closure is outstanding. Baselines are deferred until immediately before the first production prompt/model change; P2 formatting may trigger that prerequisite.
- XLSX experiment: targeted XML retained features lost by an openpyxl full save. This is structural evidence, not native-render/recalculation acceptance.
- Earlier local checks passed; rerun on the implementation being delivered. Never use old check results or a main-branch CI run as proof for new code.
- Mock web UI: runnable and committed at `docs/design/web-gui/prototype/lenny.html` (open it in a Chromium browser; any username signs in). It is one HTML/CSS/vanilla-JavaScript file with no framework, build or tests, so P6 ports it into the React + TypeScript `apps/web`. It is not a front end to wire up as-is. See [Existing Mock UI](#existing-mock-ui).

## Existing Mock UI

The owner's "Lenny" prototype is the input to P6. [Runnable Prototype](../design/web-gui/README.md#runnable-prototype) in the design README has the source hash, run instructions, code map, full feature inventory, owner decisions and known gaps. In summary:

- **Flow it demonstrates:**
  - shadcn `login-02` sign-in, uncropping into a full-screen meadow (day/night)
  - drag-and-drop or file-picker upload into the mascot, with per-file type/language confirmation
  - one target language per batch, a default-language setting and a same-language skip prompt
  - progress bubbles
  - a preview with compare slider, page strip and side by side
  - a "Your files" history panel with search, filters, retention countdown, put-back and confirmed delete
  - a welcome-back flow and Lenny settings (color, theme, default language, motion toggles)
- **Everything behind the screens is simulated:**
  - any credentials sign in
  - type and language are guessed in the browser
  - progress and fit warnings come from timers and random chance
  - preview pages are placeholders
  - comment "fixes" are timers
  - downloads only show a message
  - history lives in `localStorage` per username
- **Owner product decisions it carries:** bubbles show only current work (translating, or finished and not yet opened or downloaded) and return next session; everything else is in history; clearing never deletes; retention is visible. The page does not scroll over the world. Sharp stills are preferred over video.
- **API gaps it surfaces** for the P6.0 audit, beyond the P6 plan's session endpoints:
  - server-side detection before translation, for the same-language skip
  - per-job opened/downloaded state and an active/unseen jobs query
  - owned, paginated, searchable history
  - honest "download all"
  - page images and text mapping for the compare view, which are P7 unless P6 explicitly scopes them

The P6 plan's integration rules govern where they conflict with the mock (for example, comment fixes are P7 scope, and the password form becomes access-key sessions).

## Authority and Working Method

The handoff fixes product scope and surface behavior. It is not evidence that unrun experiments passed. One agent can work sequentially as architect, coder and reviewer under `AGENTS.md`; it need not spawn agents.

For each technical design gate, first perform the bounded experiment, choose the approach that satisfies the fixed requirements, record the evidence/decision in an ADR and exact interfaces in `Architecture.md`, then review the phase plan before entering the coder role. Routine technical decisions within this contract can be resolved by that agent in the architect role. Do not ask the owner to choose a library or tune an implementation constant.

Escalate only when evidence requires a product/accepted-architecture change, such as dropping a required format/container, flattening rich text, introducing OCR/external translation, changing formula semantics, or moving persistence into the core. Missing credentials, licensed native applications or company font assets are concrete environment blockers: continue independent work, report the exact missing evidence, and do not mark the release complete.

No coder receives an unresolved architecture question. This is a complete multi-role execution path, not a claim that all components are coder-ready today. Current phase states stay unchanged during documentation preparation; update the roadmap and board as the implementing agent accepts a phase contract and starts it.

## Execution Order

| Step | Contract | Required exit evidence |
|------|----------|------------------------|
| 0 | P1 delivery review; [P1.1](P1.1-baseline-capture.md) before prompt/model changes | Existing behavior understood; reviewed-commit checks/CI; baselines when triggered |
| 1 | [P2.0](P2.0-document-design-validation.md) | Serializer/formatting/detection choices validated; XLSX recalculation policy settled; exact public types and identity preparation specified |
| 2 | [P2](P2-document-translation-and-cli.md) | Four formats through local CLI, required text surfaces and formatting preserved, native-open evidence |
| 3 | [P3.0](P3.0-fit-design-validation.md), then [P3](P3-fit-check.md) | Fonts/measurement proven; original-relative fit and complete reports on all Office formats |
| 4 | [P4](P4-pdf-support.md) | Evidence-backed PDF strategy; translated PDF plus fit in both modes |
| 5 | [P5.0](P5.0-server-design-validation.md), then [P5](P5-server-and-service-cli.md) | Durable service, owner auth, bounded batch API, service CLI, cache, recovery and retention |
| 6 | Backend release matrix below | Combined five-format service works from CLI and an independent HTTP client; operating guide verified |
| 7 | [P6 UI audit and integration](P6-web-ui-integration.md) | Existing mock inventoried, useful features integrated with real user-owned data, browser acceptance and visual/accessibility QA |

P5 schema/API work may proceed once P2's public contract is accepted, but do not advertise the release while P3/P4 remain unfinished. The simplest sequential path is preferred unless independent work materially helps.

## Contract Decisions the Agent Must Finish

| Gate | Fixed requirement | Evidence and decision artifact |
|------|-------------------|--------------------------------|
| Rich-text translation | Preserve emphasis/inline objects in both modes; no first-run flattening | P2.0 all-direction formatted corpus; accepted strategy and explicit error policy |
| Office save paths | No loss of required/untouched content | P2.0 package comparisons and native opens/renders; serializer decision |
| XLSX calculation | Preserve names/formula expressions/numeric/date cells; never silently trust stale caches | Label-dependent native recalculation fixture; finish ADR-009 without changing the owner-approved name policy |
| Detection | Offline zh/en/ja/es; explicit override; ambiguity visible | P2.0 fixture results and pinned detector/thresholds |
| Output identity | Submission needs no model load; workers verify identity | Canonical schema, artifact/deployment revisions, fit/font identity tests |
| Fit/fonts | Real shaping/wrapping and original-relative overflow; source baseline retained | P3.0 native comparison and measurement/font ADR |
| PDF | Text translation with retained page artwork and no hidden source-text substitution | P4 strategy experiment, extraction and native-view evidence |
| Service auth/leases | Owned results, revocable credentials, stale workers cannot publish | P5.0 ADRs and race tests against the detailed P5 contract |

## Pre-GUI Release Acceptance

All tests use synthetic or approved internal material. Keep confidential documents and generated outputs out of Git.

| ID | End-to-end scenario | Required result |
|----|---------------------|-----------------|
| R01 | Every format through service CLI and independent HTTP client, each engine, zh -> en | Target text, same-format download, unchanged input hash, structural/native-open checks and fit report |
| R02 | All 12 language directions, both engines | Engine quality evidence plus representative formatted document corpus; no disappearing emphasis/glyphs or unsupported-language fallback |
| R03 | Mixed batch: repeated bytes under different filenames, same basename in different folders, malformed input, unsupported extension and valid files | Unique output paths, explicit per-item outcomes, valid siblings complete, no overwrite or silent skip |
| R04 | Manifest longer than admission window; bounded upload concurrency | Memory does not grow with total file bytes, 429/backoff handled, every item accounted for; no fixed total-count cap |
| R05 | Resubmit completed file with identical identity; then change target, mode, deployment revision, fit floor or font manifest; then force | Hit makes no engine/fit calls; each behavior change misses; force bypasses both lookups |
| R06 | Two concurrent identical misses | Both may run; one ordinary cache winner, independently valid user outputs, no unique-key crash or lost ownership |
| R07 | Kill client after accepted upload but before it receives response | Resume with same item/idempotency identity finds the original job, not another job |
| R08 | Restart API; kill worker mid-translation; allow lease to expire; run old completion | Accepted jobs recover within retry budget; stale attempt cannot publish/delete new output |
| R09 | Cancel queued/running jobs while batches continue | Correct terminal job states, no partial successful output, sibling jobs unaffected |
| R10 | Two users and revoked credentials | Cross-owner metadata/download/report/cancel access denied; shared cache never exposes someone else's document IDs |
| R11 | Source already overflows; translation fits, grows, reaches floor; missing glyph/font; DOCX body; TXT | Original-relative measurement, deterministic shrink floor, explicit unresolved cases, body unchanged, TXT not applicable |
| R12 | Expire cache, then retrieve retained user result; run GC during upload/completion; backup and restore | Referenced originals/outputs/reports remain intact; restored service downloads matching hashes |
| R13 | Network failure during download; duplicate filenames; rerun download | Atomic local publication and safe resume/retry; existing files never silently overwritten |
| R14 | Service CLI on a second internal machine | Authenticated submit/status/report/download through documented TLS and company CA configuration |

Real-backend tests are required for R01/R02; deterministic fake engines are additionally required for cache-call counts, queue races and repeatable fit tests. An integration test skipped for missing settings is not a pass. Native application evidence cannot be replaced solely by library reopening. Record installed applications/font versions with the result.

## Delivery Evidence and Stop Line

Create `docs/plans/P2-P6-release-evidence.md` during implementation with a row for each R01-R14 and P6's W01-W08: tested commit, command/test, engine/runtime/font versions, outcome and artifact location. Record CI run ID for the delivered commit and native-open/repair/visual checks. Do not prefill successes.

Update README, Architecture, Deployment, phase plans, roadmap and board in the same changes. Run all six root checks from AGENTS.md, relevant real-backend and native acceptance tests, and CI. The deployment guide must let a fresh authorized user migrate/bootstrap credentials, start service/workers, submit a multi-file manifest, inspect outcomes, download files/reports and restore a backup.

After the backend gate, complete P6 using that working REST/OpenAPI contract. Stop after the integrated web GUI passes its acceptance matrix. Do not add MCP tools or implement P7 visual editing under the guise of connecting mock controls. Final delivery includes the feature disposition audit and truthful browser evidence, not just a compiled frontend.

## Copyable Prompt for the Next Agent

> Implement the release described in docs/plans/P2-P6-delivery-handoff.md. Read AGENTS.md and the linked architecture/ADRs/plans first, inspect the existing code and preserve unrelated changes. Work through the technical design gates in the architect role, record evidence and accepted contracts, then implement and review each bounded phase. CLI and API must use the same persistent service; every batch, job and document belongs to an authenticated user. Preserve XLSX sheet names. Support TXT/PPTX/DOCX/XLSX/text-based PDF, resumable mixed batches, both engines, original-relative fit, exact-byte cache reuse and durable owned results. Complete R01-R14, then audit the existing mock web UI (docs/design/web-gui/prototype/lenny.html, documented in the design README's Runnable Prototype section) and integrate it against the real backend under P6. Preserve useful features and deliberately rework/drop/add features as needed; remove fake production data and simulated job success. Complete W01-W08 and publish truthful release evidence. Do not implement P7 MCP/visual edits, weaken preservation requirements, claim skipped tests passed, or stop at scaffolds. Escalate concrete product conflicts/environment blockers while continuing independent authorized work.
