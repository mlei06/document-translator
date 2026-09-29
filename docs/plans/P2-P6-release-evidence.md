# P2-P6 Release Evidence

Evidence for the [P2-P6 delivery handoff](P2-P6-delivery-handoff.md). Every row records the tested commit, the command or test, engine/runtime/application/font versions, the outcome and where artifacts live. Rows are filled only from real runs; an empty outcome means not yet tested. Generated documents and outputs stay under gitignored `data/` and are never committed.

## Progress

Branch: `release/p2-p6` (baseline commit `57a7671`, "Add P2-P6 release plans and design material").

**Storage revision (2026-09-29):** the owner-approved ADR-014 (from the desktop/packaging documentation) replaced the shared cache and version-0 documents after R01-R13 were recorded. The service was migrated (commit after `70bb3f9`); R05, R06, R10 and R12 were rerun against the migrated ADR-014 service with real engines (rows below); the other rows' behaviours are covered again by the updated tests.

**Current phase and step:** P5 service implemented (ADR-015, ADR-016) with R01, R03-R13 evidence below; R02 waits on the paused P1.1 baselines and R14 on a second machine. Next: P6 (web UI).

**Owner decisions during this run (2026-09-28):** ADR-012 lightweight best-effort fit (supersedes native-parity fit); ADR-013 deployment profiles and the desktop/internal-app plan (follow-on tracks, not part of P2-P6); P6 web UI keeps every mock feature except prompt/comment-driven document edits and fit-check notifications (fit runs silently; reports stay stored for diagnostics); all COMET scoring stopped by the owner; PyMuPDF approved for PDF (AGPL accepted for the internal service, recorded in ADR-018).

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

- P6: audit the Lenny mock and integrate it into `apps/web` against `/v1` (browser sessions per ADR-015), W01-W08.
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
