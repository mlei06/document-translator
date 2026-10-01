# P2-P6 Release Evidence

> Historical plan. Retained for rationale and evidence, not current implementation instructions. Follow the [current specification](../../plans/unified-translator-design.md) and [execution checklist](../../plans/unified-execution.md).

Offline fit v2 follow-on (2026-09-29): implementation, scoped native-document replays and final repository checks are recorded in [the fit v2 plan](offline-fit-v2.md#implementation-evidence-2026-09-29). Historical v1 evidence below is not v2 acceptance evidence; this follow-on does not change phase or board closure.

Evidence for the [P2-P6 delivery handoff](P2-P6-delivery-handoff.md). Every row records the tested commit, the command or test, engine/runtime/application/font versions, the outcome and where artifacts live. Rows are filled only from real runs; an empty outcome means not yet tested. Generated documents and outputs stay under gitignored `data/` and are never committed.

## Progress

Branch: `release/p2-p6` (baseline commit `57a7671`, "Add P2-P6 release plans and design material").

**Storage revision (2026-09-29):** the owner-approved ADR-014 (from the desktop/packaging documentation) replaced the shared cache and version-0 documents after R01-R13 were recorded. The service was migrated (commit after `70bb3f9`); R05, R06, R10 and R12 were rerun against the migrated ADR-014 service with real engines (rows below); the other rows' behaviours are covered again by the updated tests.

**Current phase and step:** P5 service implemented (ADR-015, ADR-016) with R01, R03-R13 evidence below; R02 waits on the paused P1.1 baselines and R14 on a second machine. P6 React integration and ADR-019 configured-translator work are in progress; completion depends on browser evidence and CI.

**Owner decisions during this run (2026-09-28):** ADR-012 lightweight best-effort fit (supersedes native-parity fit); ADR-013 deployment profiles and the desktop/internal-app plan (follow-on tracks, not part of P2-P6); P6 web UI keeps every mock feature except prompt/comment-driven document edits and fit-check notifications (Checking layout has a skip control; reports stay stored for diagnostics without per-area warnings); all COMET scoring stopped by the owner; PyMuPDF approved for PDF (AGPL accepted for the internal service, recorded in ADR-018).

**P1.1 baselines paused by the owner:** the SMALL-100 full run is translated but unscored (`data/eval/runs/20260928T055619Z-mt-alirezamsh--small100-ct2-int8`; rescore with `doctranslator-eval score <run_dir>`, no retranslation); the Gemma run was not captured. CPU-only COMET needed roughly 3 h and ~50 core-hours on this laptop. R02's engine-quality evidence depends on these baselines.

**Done**

- Read all governing documents; inspected existing code (P1 engines/eval implemented; everything else scaffolds).
- Baseline checks on `57a7671`: six root checks pass (87 passed); real LLM and MT integration tests pass.
- P2.0 complete: formatting, PPTX/DOCX writer, XLSX recalculation and detection experiments under `docs/experiments/`; ADR-011 and ADR-009 accepted; Document API in Architecture (`ea17aae`).
- P2 implemented (`6c46841`, `68c67d6`): document API, detection, protection, tags/projection/per-span fallback, targeted OOXML adapters for PPTX/DOCX/XLSX, TXT adapter, local `doctranslator translate` CLI; 165 tests; six checks pass.
- P2 real-engine local acceptance (`scripts/acceptance_local.py`, `data/acceptance/p2/local/summary.json`): all four formats x both engines exit 0, inputs unchanged, only reported out-of-scope parts keep source text; all six Office outputs open natively (Office 16 build 20326, `data/acceptance/p2/local/native.jsonl`). Two MT visual defects found in PowerPoint renders were fixed with regression tests.

- P3 fit integrated under ADR-012 for PPTX/DOCX/XLSX with saved-output verification, corpus and native spot checks (`40d73af`..`d6e23c3`; `docs/experiments/fit-measurement/README.md`).
- P4 PDF: strategy spike and ADR-018 (PyMuPDF 1.28.2 targeted replacement, writer-driven fit), `formats/pdf` adapter, pipeline `PlacementFit` and `verify_output`, CLI; 17 PDF tests plus a CLI PDF test. Real-engine acceptance (both engines, a PowerPoint-exported deck and a text page, zh to en): all exit 0, verification passed, inputs unchanged; independent PDFium 153.0.7999.0 check finds 0 source CJK characters and matching geometry (`data/acceptance/p4/local/`, `pdfium.jsonl`).

- P5 (`917e59d`, `8146731`): ADR-015/016, users and keys, SQLite/Alembic schema, blob storage with pins and GC, REST `/v1`, attempt-fenced queue and workers, retention, backup/restore, `doctranslator-server` administration, service CLI; 45 server tests, 6 cross-process E2E tests; 247 tests pass. Real-service acceptance in `data/acceptance/p5/`.

**Next**

- Finish P6 acceptance W01-W08 against the integrated `apps/web`; record real-model, restart/revocation, accessibility and full-control evidence before phase closure.
- R02 after the owner resumes P1.1 baselines; R14 on a second internal machine; CI after the owner allows a push.

**Open blockers and environment limits**

| Blocker | Missing item | Rows blocked |
|---------|--------------|--------------|
| CI | Pipelines run only on `main` and pull requests; this branch has not been pushed (the owner asked for no push/PR). | CI evidence for every row and phase closure |
| Second machine | No second internal machine available to this session | R14 |
| Word save/export | Word on this host opens documents but hangs on any save or PDF export (a hidden prompt, likely a policy such as mandatory sensitivity labels; this session has no interactive desktop). PowerPoint and Excel export fine. | DOCX visual renders (native open works and is recorded) |

Notes for a fresh session: background shells die with the session, so long jobs are started with `Start-Process` (detached). `scripts/native_office_check.ps1` needs one Office app at a time; Office automation takes about a minute per application start here.

## Environment

| Item | Version |
|------|---------|
| OS | Windows 11 Pro 10.0.26200 |
| Python / uv | 3.14.7 / 0.12.6 |
| Node / npm | 24.19.0 / 11.17.0 |
| Office | Microsoft Office 16 (Word, Excel, PowerPoint), exact build recorded per native row |
| LLM | Internal OpenAI-compatible server, model `gemma-4-31b-it` |
| MT | SMALL-100, CTranslate2 int8 (`data/models/alirezamsh--small100-ct2-int8`) |

## Backend Release Matrix (R01-R14)

| ID | Tested commit | Command / test | Versions | Outcome | Artifacts |
|----|---------------|----------------|----------|---------|-----------|
| R01 | `8146731` | Real `doctranslator-server serve --workers 1` on loopback; service CLI `submit ... --download-dir` and independent `scripts/acceptance_http_client.py --force`, both engines, TXT/PPTX/DOCX/XLSX/2 PDFs, zh -> en; `native_office_check.ps1`; `pdf_independent_check.py` | Windows 11 26200, Python 3.14.7, SQLite (stdlib), FastAPI 0.141.1, SQLAlchemy 2.1.1; SMALL-100 ct2 int8 and gemma-4-31b-it; Office 16 build 20326; PDFium 153.0.7999.0 | Pass: 24/24 jobs succeeded (12 CLI, 12 HTTP), English output, SHA-256 verified, inputs unchanged; 6/6 Office outputs open natively (formulas recalculate); 4/4 PDFs 0 CJK left; fit reports passed/adjusted/unresolved/not_applicable as expected (DOCX CJK text box and XLSX rich-text/floor unresolved, see P3) | `data/acceptance/p5/` (`submit-*.jsonl`, `http-*.jsonl`, `native.jsonl`, `pdfium.jsonl`) |
| R02 | | | | Not yet tested | |
| R03 | `8146731` | `tests/e2e/test_service_cli.py::test_mixed_batch_with_failures_downloads_every_success` (CLI subprocess, real HTTP service process, deterministic engine); `apps/server/tests/test_api.py::test_batch_lifecycle_with_mixed_items` | as R01 (fake engine) | Pass: same bytes and basename in two folders give two documents and distinct output names; unsupported and malformed files are recorded rejections; 6 valid siblings succeed and download; inputs unchanged; exit 1 reports the rejections | test logs |
| R04 | `8146731` | `tests/e2e/test_service_cli.py::test_a_long_manifest_drains_through_admission_backpressure` (8-file manifest, per-user admission 2, slow engine) | as R01 (fake engine) | Pass: CLI backs off on 429 `queue_full`, every item accepted and succeeded; uploads stream from disk with a window of `--concurrency` requests (no memory measurement recorded) | test logs |
| R05 | `fe44e73` + fixes | Real service on the migrated acceptance data (`scratchpad adr14_accept.py`, recorded in `adr14-r05-r06-r10.json`); `test_api.py::test_reuse_is_owner_scoped_and_force_replaces_the_current_result`, `test_temporary_jobs_never_reuse_and_expire`; `test_queue.py::test_skipped_fit_is_saved_but_never_reused`; core identity tests | Windows 11 26200, Python 3.14.7, FastAPI 0.141.1, SQLAlchemy 2.1.1; SMALL-100 ct2 int8 and gemma-4-31b-it | Pass (ADR-014): identical saved resubmission reuses the owner's current translation (201 in 0.22 s, no engine call); target, mode and fit-floor changes translate again; force replaces the current translation after success while the earlier job stays downloadable until its 7-day expiry; temporary jobs always run and expire after 24 h; a skipped fit is saved but never reused | `data/acceptance/p5/adr14-r05-r06-r10.json` |
| R06 | `fe44e73` + fixes | Real service: two concurrent forced submissions of one saved document and target by one owner, and the same bytes by two owners at once; `test_api.py::test_one_active_job_per_document_and_target`; `test_queue.py::test_two_owners_translate_the_same_bytes_independently` | Windows 11 26200, Python 3.14.7, FastAPI 0.141.1, SQLAlchemy 2.1.1; SMALL-100 ct2 int8 and gemma-4-31b-it | Pass (ADR-014): one owner's concurrent requests serialize (202 plus 409 `translation_active` naming the winning job, which succeeds); two owners both translate into their own documents; no unique-key failure | as R05 |
| R07 | `8146731` | `tests/e2e/test_service_cli.py::test_resume_reuses_identities_and_creates_no_duplicates`; `test_api.py::test_idempotent_replay_and_mismatch` | fake engine | Pass: rerunning with the same resume state returns the same batch and 3 jobs (no duplicates); replay of a submission ID returns the original job; different bytes/options are 409 | test logs |
| R08 | `8146731` | `tests/e2e/test_recovery.py` (service process killed mid-translation, restarted on the same data); `test_queue.py::test_stale_attempt_cannot_publish_after_reclaim`, `test_expired_lease_cannot_publish_even_without_reclaim`, `test_recovery_budget_then_worker_lost` | fake engine | Pass: the job recovers after lease expiry and succeeds on attempt 2 with one document; a stale attempt (old token) cannot heartbeat, progress, fail or publish after reclaim; attempts exhausted gives `worker_lost` | test logs |
| R09 | `8146731` | `test_queue.py` cancellation tests; `test_api.py::test_batch_cancel_stops_outstanding_jobs` | fake engine | Pass: queued cancel is immediate; running cancel publishes nothing; cancel after success keeps the success; batch cancel cancels outstanding jobs only | test logs |
| R10 | `fe44e73` + fixes | Real service with two users; `test_api.py::test_users_cannot_see_each_others_records`, `test_documents_are_owner_scoped_and_deduplicated`, session tests; `test_auth.py`; E2E `test_authentication_and_ownership` | Windows 11 26200, Python 3.14.7, FastAPI 0.141.1, SQLAlchemy 2.1.1; SMALL-100 ct2 int8 and gemma-4-31b-it | Pass: another owner's identical bytes are not reused (their own document, translated fresh); all cross-owner job/document/file/original/cancel requests are 404; revoked keys, disabled users and conflicting credentials are 401; keys never appear in CLI output | as R05 |
| R11 | `8146731` | Core fit tests (`test_fit.py`, `test_fit_formats.py`, `test_format_pdf.py`: source overflow, growth, floor, missing font/glyph, search limit, DOCX body, TXT) and R01 service reports | as R01 | Pass at core level; the service stores and returns the same versioned reports (R01: passed, adjusted, unresolved with reasons, not_applicable for TXT). No service-specific fit logic exists | `data/acceptance/p5/out-*/*.report.json` |
| R12 | `fe44e73` + fixes | `test_storage.py` (pins, GC lock, superseded results expire only for their jobs, deleted documents free blobs after metadata retention, saved documents never expire, backup/restore); `test_migrations.py` (0001 data converted without loss); real migration of the P5 acceptance data to 0002, live `backup`, `restore` into an empty directory, second service on port 8766 | Windows 11 26200, Python 3.14.7, FastAPI 0.141.1, SQLAlchemy 2.1.1; SMALL-100 ct2 int8 and gemma-4-31b-it | Pass: 48 blobs backed up while running and verified on restore; all 36 downloadable job results identical (SHA-256) from the restored service; the migration found and fixed one issue (0001 terminal `phase='done'`), now covered by the migration test | `data/acceptance/p5/backup-adr14/`, `r12-adr14-restore.txt` |
| R13 | `8146731` | E2E `test_download_never_overwrites_without_consent`; `service.py` download (temporary file, size and SHA-256 check, hard-link publish) | fake engine | Pass: re-download refuses an existing (edited) file and exits 1; `--overwrite` replaces it; no `.part` files remain; interrupted transfers leave no destination file (by construction; no network-fault injection recorded) | test logs |
| R14 | | | | Blocked: no second machine | |

## Browser Acceptance Matrix (W01-W08)

| ID | Tested commit | Command / test | Versions | Outcome | Artifacts |
|----|---------------|----------------|----------|---------|-----------|
| W01 | | | | Not yet tested | |
| W02 | | | | Not yet tested | |
| W03 | | | | Not yet tested | |
| W04 | | | | Not yet tested | |
| W05 | | | | Not yet tested | |
| W06 | | | | Not yet tested | |
| W07 | | | | Not yet tested | |
| W08 | | | | Not yet tested | |

## Checks and CI

| Commit | Six root checks | Frontend checks | CI run |
|--------|-----------------|-----------------|--------|
| `57a7671` | Pass (87 passed, 2 deselected) | n/a | Not run (branch not pushed) |
| `8146731` | Pass (247 passed, 2 deselected) | n/a | Not run (branch not pushed) |
| P4 commit (this row's commit) | Pass (197 passed, 2 deselected) | n/a | Not run (branch not pushed) |

## Configured translators and P6 continuation (2026-09-29)

Working tree based on `4a45b83`, not pushed. ADR-019 records the accepted website-admin and desktop-setup configuration contract. This pass implements named translator configuration, safe capabilities, job-pinned translator IDs/fingerprints, migration 0003, lazy bounded local runtimes, service CLI selection, and one web Translator selector. Installer downloads and new inference adapters remain separate deliverables.

Review corrections include session-bound uploads/submissions/downloads, bounded translation submission, complete active-job pagination, recovery from unavailable selections, retention protection for live worker directories, legacy-session reauthentication, and idempotent retries after configuration changes or rejected inputs. The active-directory and old-session failures were reproduced before their fixes; both targeted regressions pass.

Browser tests use the actual HTTP service with deterministic translation engines. They exercise application integration, not real-model quality or the full W01-W08 acceptance matrix. Existing backend real-model evidence above is historical and must not be presented as validation of the new browser flow. Outstanding release evidence includes W02 all five formats with real engines, complete restart/revocation and control/accessibility checks, CI, R14, and the owner-paused R02 quality baselines.

Validation for this working tree:

- `uv sync --all-packages`, `uv run ruff format --check`, `uv run ruff check`, `uv run pyright`, and `uv run lint-imports` pass after corrections. All 14 import contracts remain intact.
- `uv run pytest`: 278 passed, 2 real-backend integration tests deselected, 568.59 seconds. The rejected-item retry regression was added after collection; the final configured-translator module was then rerun separately: 4 passed in 7.93 seconds.
- Frontend typecheck, lint, formatting, build and 24 unit tests pass. Three Chromium browser tests pass against the real service with deterministic engines: authenticated upload/translation/download/reload/owner isolation; logout aborting pending uploads; and constrained PPTX layout skip with forced replacement and retained prior-job download.
- Desktop (1280x720) and mobile (390x844) screenshots visually inspected. This is not a full accessibility or visual-state audit. Browser log/screenshots: `data/experiments/p6-browser-20260929/`. Root check logs: `data/implementation-*.log`.
- CI configuration now includes generated-schema drift detection and frontend checks/browser tests, but no remote CI run or push occurred.

## Local website accounts and decoding (2026-09-29)

ADR-020 adds owner-requested email/password registration and sign-in while preserving API-key clients and existing ownership. Migration 0004 preserves existing key-backed sessions; password sessions do not depend on an API key. Registration is opt-in, and the running loopback instance enables it.

The local instance uses ignored `data/website.env`, persistent `data/website`, port 8765 and the built web UI. Its three presets are SMALL-100 Beam 4, SMALL-100 Greedy and Gemma. Real HTTP registration returned 201. A temporary English-to-Chinese TXT job succeeded and downloaded changed Chinese output for each preset (13.1 s, 18.9 s and 3.2 s respectively, including cold-load/polling overhead; these are smoke timings, not comparative benchmarks). Artifacts: `data/website-smoke/results.json` and the three output text files.

The account implementation passed focused registration, login, duplicate email, disabled user, registration-flag, origin/CSRF and limiter checks. Populated 0003-to-0004 migration with an existing API key/session passed. The independent authentication review found no blocking issue for this internal/local scope. Full P6 acceptance remains separate from this local run.

Owner follow-up sets the password minimum to 8 characters. The API boundary tests pass with exactly 8 characters and reject 7; the form and generated OpenAPI use the same minimum. The final frontend build is served by the running instance.

Actual-browser verification against port 8765 passed with an exactly 8-character password: account creation, Lenny menu, Gemma selection, SMALL-100 Beam 4-to-Greedy selection, TXT submission pinned to `small100-greedy`, and a downloaded Chinese result. Updated desktop/mobile account/settings screenshots are under `data/experiments/p6-account-presets-20260929/`.

Final 8-character frontend build: generated API schema, typecheck/build, lint and formatting pass; 26 unit tests and 4 browser tests pass (3.6 minutes). The four browser tests include account creation/login/reload and decoding selection, plus the prior lifecycle, fit-skip/replacement and logout-isolation regressions. Actual-instance smoke and test logs are preserved with the screenshots above.

Final root checks after the 8-character change all pass: dependency sync, formatting, lint, pyright, all 14 import contracts, and `uv run pytest` (282 passed, 2 deselected in 518.23 seconds). Logs and exit codes: `data/accounts-final-*.log` and `data/accounts-final-checks.json`. The actual local service remains running on port 8765.

## Empty SMALL-100 output correction (2026-09-29)

The reported Greedy PDF failure was reproduced: one input (联想) produced a blank answer. Beam 4 returned a nonempty but incorrect company-name translation, so no model-switch workaround was introduced. ADR-021 preserves the encoded source for blank answers and records `empty_translation_preserved`. The pipeline strategy fingerprint was bumped.

The reported PDF now completes and verifies with the actual Greedy model: 62 segments, 54 unique inputs, one preserved-empty diagnostic; output/report are in `data/small100-investigation/fixed.pdf` and `fixed.report.json`. Original inputs remain unchanged. Focused pipeline/identity tests pass (24); a further formatted-PowerPoint preservation regression passes with its module (3 tests).

The running website was restarted without active jobs. Actual-browser signup, SMALL-100 Greedy selection, upload, completed preview warning and authenticated download pass on port 8765. Download retains 联想 while translating the other paragraph. Synthetic-data evidence: `data/empty-output-browser/`. Frontend build/typecheck, lint, formatting and 29 unit tests pass.

Final verification: all six root checks pass after fixing one line-length lint finding; full suite 282 passed, 2 deselected in 458.69 seconds. The formatted-empty-output regression added after collection passed in its separate 3-test module run. Frontend checks and the actual-model browser workflow above passed. The running service contains the fix.


## Shared SMALL-100 runtime (2026-09-29)

ADR-019 now specifies immutable decoding bindings over one compatible native runtime per worker. Beam 4 and Greedy retain independent configured IDs and output fingerprints. Runtime limits and LRU eviction count whole model groups; closing one binding does not invalidate another held binding. Architecture and deployment documentation reflect the contract.

A real CT2 reproduction of Beam 4 -> Greedy -> Beam 4 loaded the model three times before this change and once afterward. Every loaded fingerprint matched its prepared job identity. Afterward, the small single-sentence calls took 3.89 s (cold), 0.15 s and 0.25 s. These are smoke timings, not controlled performance benchmarks. Evidence: `data/small100-reuse/before.json` and `after.json`.

The local service restarted without active jobs. A synthetic account submitted three temporary English-to-Chinese TXT uploads in that same preset sequence. All completed and downloaded translated output. Reports confirm beam sizes 4, 1, 4, matching fingerprints for the two Beam 4 jobs and a distinct Greedy fingerprint. Evidence: `data/small100-reuse/http.json` and the three report JSON files. No frontend behavior or concurrency policy changed.

Final verification: all six root checks pass, including all 14 import contracts and 290 tests (2 real-backend integration tests deselected, 389.74 seconds). Real SMALL-100 verification was performed separately as described above. Logs and exit codes: `data/reuse-final-*.log` and `data/reuse-final-checks.json`. The restarted local website contains this change.

## Literal protection and account dictionaries (2026-09-29)

ADR-022 adds conservative literal syntax, a packaged company/product names dictionary and account-owned custom words. Settings has a labelled editor, the read-only built-in list, an enable switch, explicit Save and error feedback. Personal words persist through authenticated GET/PUT; migration 0005 adds account storage. New jobs snapshot merged terms and default-list choice, while idempotent replays keep the old job. The protection version and effective dictionary digest invalidate incompatible saved results.

The reported PowerPoint was replayed with actual SMALL-100 Greedy through the full document pipeline. Slide 7's GitHub URL now stays exact; slide 10's title is `ElevenLabs 设置`, and both environment assignments stay exact. PowerPoint-exported images of slides 7 and 10 were visually inspected: the repeated output and overflow are absent. Evidence and translated deck: `data/pptx-debug/protected.pptx`, `protected-report.json`, `protected-7.png`, `protected-10.png`. This verifies the reported failure, not general translation accuracy.

The local database migrated to 0005 and the website restarted. A synthetic account saved `Project Atlas`, submitted an actual Greedy TXT job and downloaded translated output retaining the custom name, Lenovo, ElevenLabs, a bare URL and an environment assignment. Evidence: `data/pptx-debug/live-protected.txt`. Account choices do not mutate other users, existing jobs or their output files.

Root validation exposed unfinished renderer lint/type/test compatibility issues in the shared checkout. Standard-location discovery now respects the core's no-environment rule, subprocess typing is explicit and the existing PDF test uses the current page-image API. Deterministic server/browser lifecycle fixtures explicitly use the text-preview fallback rather than depending on a developer's LibreOffice installation. This does not validate native Office preview rendering; the reported slide inspection used PowerPoint separately.

Verification: dependency sync, Ruff formatting/lint, pyright and all 14 import contracts pass. The complete Python run finished with 314 passed, 2 integration tests deselected and one obsolete legacy-request fixture failure in 938.63 seconds. That fixture incorrectly included the new dictionary option in a pre-0003 payload; corrected to represent the actual historical request, its entire 4-test module passes. Production replay logic was unchanged by that correction. Logs: `data/protection-tests.log`, `data/protection-legacy-final.log`, and `data/protection-pytest-final-recheck.log`.

Final `uv run pytest --lf` passes with exit 0, confirming the sole full-run failure is resolved. Frontend generated-schema/build, lint, formatting and 32 unit tests pass. All five Chromium lifecycle tests pass (7.3 minutes), including dictionary save/reload, submission/download, account isolation and the existing login/fit-skip/logout flows. Desktop/mobile dictionary screenshots were visually inspected in `apps/web/test-results/`. Logs: `data/protection-web-*.log` and `data/protection-browser.log`. The migrated live instance's health check returns OK and its real-model dictionary smoke passes. No commit or push was performed.
