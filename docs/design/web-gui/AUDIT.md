# P6.0 Audit - Lenny Mock to Production Web UI

Audited 2026-09-29 for [P6](../../plans/P6-web-ui-integration.md); revised the same day for [ADR-014](../../decisions/ADR-014-storage-ownership-and-retranslation.md) (saved library, retranslation) and the [progress/skip plan](../../plans/P5-P6-document-progress.md). Scope rule from the owner (2026-09-28): the website keeps every feature the mock has, except updating documents by prompting/commenting and notifying users about the fit check; it shows Checking layout with a Skip layout check control, without per-area fit warnings (reports stay stored for diagnostics). Where the P6 plan and the owner rule agree a control is fake, it is reworked into a real feature or dropped with the reason below.

> Updated contract: ADR-014 current translations and exact job downloads replace any historical version-0 links; no user-facing fit-report view is required. ADR-019 replaces the mode switch with a configured Translator selector. Keep source mock observations below as history, not authority over these accepted contracts.

## Source of Record

| Item | Value |
|---|---|
| Artifact | `docs/design/web-gui/prototype/lenny.html` (SHA-256 `30e6b5d83e42858a9ce864ee2d5b4dad37e9c6e2ddc7dc47384ad4a48fe817d4`, claude.ai "Meet Lenny" v13, 2026-09-27) plus `prototype/assets/` (7 WebP) |
| Technology | One HTML/CSS/vanilla-JS file, no framework, package manager, lockfile or build; Google Fonts (Geist, Geist Mono) is its only network request |
| Baseline preserved | Git history (`docs/design/web-gui/prototype/` unchanged by P6); the port lives in `apps/web` |
| Run | Open the file in Edge, or `python -m http.server 8000 --directory docs/design/web-gui/prototype` |
| Screenshots | `audit/*.jpg`, captured by `audit/capture-mock.mjs` (Playwright driving installed Edge 1440x900 and 390x844, light and dark) |
| Verified in this audit | Sign-in (username/password focus reactions), uncrop transition, header, account and Lenny menus, sample-file swallow, language confirmation, target question, bubbles (progress, done), preview compare and side by side, Your files, Lenny settings, night theme, phone layout |

Defects observed in the mock (fixed in the port): the night-theme speech bubble text is nearly invisible (`16-app-night.jpg`); target languages offered (Korean, French, German, free text) are not supported by the engines.

## Feature Disposition

Status: **keep** (real behavior with the same design), **rework** (same design, real data or a changed contract), **drop** (removed from production, with reason). Every row has an acceptance check in the P6 browser matrix (W01-W08) or a component test.

| # | Feature (screenshot) | Mock behavior | Decision | Production behavior and backend |
|---|---|---|---|---|
| 1 | Sign-in page, `login-02` layout with the meadow and Lenny (01-03, 17, 18) | Any username/password | **rework** | Access-key sign-in: `POST /v1/sessions` exchanges a provisioned API key for an HttpOnly session cookie and CSRF token; the key is never stored in the browser. Lenny's field reactions stay ("Paste your access key", eyes closed while typing the key). Errors are shown, never a fake success |
| 2 | "Forgot your password?" | Lenny replies | **rework** | "Lost your key?": Lenny explains that an administrator issues a new one (no password database exists) |
| 3 | "Sign in with your work account" | Lenny replies | **drop** | No company SSO exists (ADR-015); a button implying it would be a dead control |
| 4 | "Need access? Ask your IT admin" | Lenny replies | **keep** | Explains key provisioning |
| 5 | "Prototype: any username..." note and header "Prototype" badge | Marks the mock | **drop** | Not a prototype any more |
| 6 | Sign-in to app uncrop transition, sign-out reverse (04) | Presentation | **keep** | Never delays data loading; skipped under reduced motion |
| 7 | Header: brand, Your files, day/night toggle, account menu with display name (04, 05) | Name typed at sign-in | **rework** | Identity from `GET /v1/me` |
| 8 | Account menu: Your files, Lenny settings, Start over, Sign out (05) | Local | **keep / rework** | Sign out calls `DELETE /v1/sessions/current` and clears all cached user data; Start over clears pending local files and moves finished bubbles to Your files |
| 9 | World: day/night stills, drifting clouds, pollen/fireflies, parallax, vignette, no page scroll | Presentation | **rework** | Same assets and ambient drift; reduced motion stops drift and particles. Remove cursor-driven background parallax: only Lenny follows the pointer. |
| 10 | Lenny: SVG rig, gaze follows pointer and dragged files, blink, speech with mouth, sleep after idle, boop, context menu (06) | Presentation | **keep** | Motion never blocks controls; speech mirrored in an `aria-live` region |
| 11 | Drag and drop anywhere with spotlight, swallow animation (07) | Extension check only | **rework** | Each file uploads to `POST /v1/documents` (a saved source document, ADR-014); the server sniffs the format and detects the source language (and rejects scans, encrypted/signed PDFs, unsupported or damaged files) before Lenny "swallows" it; animation never implies acceptance. Keyboard/labelled file picker is equivalent |
| 12 | "Pick files" button and picker | Local | **keep** | Same upload path |
| 13 | "Feed me sample files" | Four fake file names | **rework** | Uploads real bundled synthetic sample documents (PPTX, DOCX, XLSX, PDF, TXT) through the same path |
| 14 | Per-file type and detected language with a correction dropdown (07) | Guessed from file names | **rework** | Type and language are server facts from the upload; the dropdown lists supported languages only (zh, en, ja, es) plus "Detect automatically" |
| 15 | "Om nom" confirmation list, "That's everything", "Or drop in more" (07) | Local | **keep** | Lists every pending file with size and upload state (uploading, ready, rejected with reason) |
| 16 | Target question: quick chips, free-text language, "Wait, I have more files" (08) | Any language | **rework** | Chips come from `GET /v1/capabilities` languages; free text dropped (unsupported languages would be a fake option); engine choice (MT/LLM) shown when both are available |
| 17 | Default target language skips the question (settings) | Local | **keep** | Local preference (harmless per P6 plan) |
| 18 | "Already in <language>: Skip it / Translate anyway" | Name guess | **rework** | Uses the detected or user-selected source language. Offer "Choose another language" without losing uploads, or skip matching files and submit the remaining files. Identical explicit source/target pairs are rejected by the service, so do not offer "Translate anyway". |
| 19 | Progress bubbles with ring, sparkles, done state (09, 10, 20) | Random timer | **rework** | Bound to real job status and the stored progress snapshot (progress plan labels: Waiting to translate, Preparing, Reading, Translating N of M, Finishing translation, Applying, Checking layout, Saving, Ready to download); counts only while translating, otherwise indeterminate; failures shown in the bubble and in Your files |
| 20a | (new) **Skip layout check** during Checking layout | - | **add** | Owner decision (ADR-012 amendment): `POST /v1/jobs/{id}/skip-fit`; shows Skipping layout check until the server moves to Saving; never a fake success |
| 20 | Fit-warning badges ("2 to check", "1 to check") and "Text doesn't fit" markers (10, 11, 13) | Invented | **drop** | Owner decision: no fit notifications. Fit reports stay stored and downloadable from the file details |
| 21 | Bubble × moves it to Your files (never deletes) | Local | **rework** | `POST /v1/jobs/{id}/dismiss`; server-side so it holds across devices |
| 22 | Bubbles show only current work and come back next session; "Welcome back" summary | Extrapolated timers | **rework** | `GET /v1/jobs?active=true` (unfinished, or finished and not yet opened, downloaded or dismissed); Lenny reports how many finished while away |
| 23 | Phone dock of bubbles (20) | Presentation | **keep** | Same data |
| 24 | Preview: header, Compare slider, Side by side, page strip, page navigation, keyboard (11, 12) | Placeholder drawings | **rework** | Real preview built by the worker and served from the job's or translation's result: PDF pages rendered from the actual source and translated PDF (compare slider and side by side on images); PPTX/DOCX/XLSX/TXT shown as source and translated text per slide, sheet, part or line (the same compare and side-by-side views, linked highlighting between source and translation). No browser rendering of Office layout is claimed; Download is always offered |
| 25 | Preview notes panel with Lenny and comment box, "Ask Lenny to fix it", page/text-box comment targets, versions | Timer "fix" | **drop** (comments) / **rework** (panel) | Owner decision: no prompt/comment edits. The panel keeps Lenny with the real facts: languages, engine, cache reuse, finished time, retention, download and fit-report download |
| 26 | Download (preview and Your files) | Message only | **rework** | Real bytes from `GET /v1/documents/{id}/versions/0/file`; marks the job as seen |
| 27 | "Download all" | Message only | **rework** | Downloads each finished file in turn and explains that the browser may ask to allow multiple downloads; individual downloads remain |
| 28 | Your files panel grouped by batch with time and target (13) | `localStorage` | **rework** | The ADR-014 library: `GET /v1/documents` (owned source documents with their current translation per language and active jobs); survives reload and devices. Translate again (force) and Always generate a new translation (a local preference that sends force) keep the old download until the replacement succeeds |
| 29 | Search by file name | Local | **rework** | `GET /v1/documents?q=` server-side |
| 30 | Filters All / Translating / Done / Skipped | Local | **rework** | All / Translating (a target has an active job) / Done (has a current translation); failures are shown on the bubbles and job details; skipped files never reach the server, so "Skipped" is dropped |
| 31 | "Deletes in N days" | 7-day client timer | **rework** | Saved documents do not expire (ADR-014): shown as Saved with the owner's storage use and quota from `GET /v1/me`; temporary results and replaced translations show their expiry |
| 32 | Preview, download, put back on the meadow, delete with confirmation (13) | Local | **rework** | Open preview; download the current translation; put the latest job back on the meadow (`POST /v1/jobs/{id}/restore`); Delete translation or Delete source with the concrete scope confirmed (ADR-014: source deletion also revokes job downloads) |
| 33 | "Add example history" | Fake history | **drop** | History is real data only |
| 34 | Lenny settings: color swatches and hue, sprout, theme System/Day/Night, default language, follow cursor, playful reactions (15) | `localStorage` | **keep** | Local, harmless preferences per the P6 plan (per browser, not per user) |
| 35 | Toasts and speech feedback | Local | **keep** | Real outcomes only |

## API Gaps (closed in P6.1, ADR-017)

| Gap | Contract |
|---|---|
| Browser sessions | `POST /v1/sessions`, `DELETE /v1/sessions/current`; cookie plus CSRF token; Origin check; failed-login rate limit; idle and absolute expiry; revoked with the key or user |
| Detection before translation | `POST /v1/documents` (ADR-014 saved document with format, detected source and rejection reasons); `POST /v1/documents/{id}/translations` submits without re-uploading |
| Real preview | Worker-built preview package per immutable result: `GET /v1/jobs/{id}/preview[/{name}]` and `GET /v1/documents/{id}/translations/{tid}/preview[/{name}]` |
| Bubble lifetime | `dismissed_at` per job: `POST /v1/jobs/{id}/dismiss`, `/restore`; opening or downloading marks it too; `GET /v1/jobs?active=true` |
| History search and deletion | The ADR-014 library (`GET /v1/documents?q=`, delete translation/source); `GET /v1/jobs?q=&status=&active=`; `result_expires_at` in job responses |
| Progress and fit skip | Progress snapshots in job responses and `POST /v1/jobs/{id}/skip-fit` (progress plan) |
| Static hosting | The service serves the built SPA with a UI-route fallback; `/v1` never returns HTML |

## Technology Choices for the Port

React 19 + TypeScript 5.9 + Vite 8 (`apps/web`), TanStack Query for server state, `openapi-typescript` + `openapi-fetch` for a typed client generated from `/v1/openapi.json`, self-hosted Geist via `@fontsource`, Vitest + Testing Library for components, Playwright (installed Edge) for browser acceptance, oxlint and Prettier. The world and Lenny rig are ported into typed, framework-independent modules mounted by React components, preserving the mock's art and motion; the mock's single global state object becomes React state for UI and TanStack Query for server data.
