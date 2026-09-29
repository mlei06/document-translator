# P2-P6 Release Evidence

Evidence for the [P2-P6 delivery handoff](P2-P6-delivery-handoff.md). Every row records the tested commit, the command or test, engine/runtime/application/font versions, the outcome and where artifacts live. Rows are filled only from real runs; an empty outcome means not yet tested. Generated documents and outputs stay under gitignored `data/` and are never committed.

## Progress

Branch: `release/p2-p6` (baseline commit `57a7671`, "Add P2-P6 release plans and design material").

**Current phase and step:** P5 service implemented (ADR-015, ADR-016) with R01, R03-R13 evidence below; R02 waits on the paused P1.1 baselines and R14 on a second machine. Next: P6 (web UI).

**Owner decisions during this run (2026-09-28):** ADR-012 lightweight best-effort fit (supersedes native-parity fit); ADR-013 deployment profiles and the desktop/internal-app plan (follow-on tracks, not part of P2-P6); P6 web UI keeps every mock feature except prompt/comment-driven document edits and fit-check notifications (fit runs silently; reports stay stored for diagnostics); all COMET scoring stopped by the owner; PyMuPDF approved for PDF (AGPL accepted for the internal service, recorded in ADR-014).

**P1.1 baselines paused by the owner:** the SMALL-100 full run is translated but unscored (`data/eval/runs/20260928T055619Z-mt-alirezamsh--small100-ct2-int8`; rescore with `doctranslator-eval score <run_dir>`, no retranslation); the Gemma run was not captured. CPU-only COMET needed roughly 3 h and ~50 core-hours on this laptop. R02's engine-quality evidence depends on these baselines.

**Done**

- Read all governing documents; inspected existing code (P1 engines/eval implemented; everything else scaffolds).
- Baseline checks on `57a7671`: six root checks pass (87 passed); real LLM and MT integration tests pass.
- P2.0 complete: formatting, PPTX/DOCX writer, XLSX recalculation and detection experiments under `docs/experiments/`; ADR-011 and ADR-009 accepted; Document API in Architecture (`ea17aae`).
- P2 implemented (`6c46841`, `68c67d6`): document API, detection, protection, tags/projection/per-span fallback, targeted OOXML adapters for PPTX/DOCX/XLSX, TXT adapter, local `doctranslator translate` CLI; 165 tests; six checks pass.
- P2 real-engine local acceptance (`scripts/acceptance_local.py`, `data/acceptance/p2/local/summary.json`): all four formats x both engines exit 0, inputs unchanged, only reported out-of-scope parts keep source text; all six Office outputs open natively (Office 16 build 20326, `data/acceptance/p2/local/native.jsonl`). Two MT visual defects found in PowerPoint renders were fixed with regression tests.

- P3 fit integrated under ADR-012 for PPTX/DOCX/XLSX with saved-output verification, corpus and native spot checks (`40d73af`..`d6e23c3`; `docs/experiments/fit-measurement/README.md`).
- P4 PDF: strategy spike and ADR-014 (PyMuPDF 1.28.2 targeted replacement, writer-driven fit), `formats/pdf` adapter, pipeline `PlacementFit` and `verify_output`, CLI; 17 PDF tests plus a CLI PDF test. Real-engine acceptance (both engines, a PowerPoint-exported deck and a text page, zh to en): all exit 0, verification passed, inputs unchanged; independent PDFium 153.0.7999.0 check finds 0 source CJK characters and matching geometry (`data/acceptance/p4/local/`, `pdfium.jsonl`).

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
| R05 | `8146731` | `test_api.py::test_cache_hit_skips_the_engine_and_force_bypasses_it`, `test_identity_change_between_submission_and_worker_fails_the_job`; core identity tests (target, mode, deployment revision, fit floor, font manifest in the fingerprint); real service resubmission | Windows 11 26200, Python 3.14.7, SQLite (stdlib), FastAPI 0.141.1, SQLAlchemy 2.1.1; SMALL-100 ct2 int8 and gemma-4-31b-it | Pass: identical resubmission completes at once with no engine call (real: 0.1-0.2 s, `cache_hit` true); target/mode/fit-floor/engine-version changes miss; force bypasses submission and worker lookups and replaces the cache pointer | `data/acceptance/p5/r05-cache-hit.jsonl` |
| R06 | `8146731` | `test_queue.py::test_two_concurrent_misses_both_publish_with_one_cache_winner`, `test_worker_rechecks_the_cache_before_translating` | fake engine | Pass: both concurrent misses publish their own documents, one cache row, no unique-key failure | test logs |
| R07 | `8146731` | `tests/e2e/test_service_cli.py::test_resume_reuses_identities_and_creates_no_duplicates`; `test_api.py::test_idempotent_replay_and_mismatch` | fake engine | Pass: rerunning with the same resume state returns the same batch and 3 jobs (no duplicates); replay of a submission ID returns the original job; different bytes/options are 409 | test logs |
| R08 | `8146731` | `tests/e2e/test_recovery.py` (service process killed mid-translation, restarted on the same data); `test_queue.py::test_stale_attempt_cannot_publish_after_reclaim`, `test_expired_lease_cannot_publish_even_without_reclaim`, `test_recovery_budget_then_worker_lost` | fake engine | Pass: the job recovers after lease expiry and succeeds on attempt 2 with one document; a stale attempt (old token) cannot heartbeat, progress, fail or publish after reclaim; attempts exhausted gives `worker_lost` | test logs |
| R09 | `8146731` | `test_queue.py` cancellation tests; `test_api.py::test_batch_cancel_stops_outstanding_jobs` | fake engine | Pass: queued cancel is immediate; running cancel publishes nothing; cancel after success keeps the success; batch cancel cancels outstanding jobs only | test logs |
| R10 | `8146731` | `test_api.py::test_users_cannot_see_each_others_records`, `test_every_route_requires_a_valid_key`; `test_auth.py`; E2E `test_authentication_and_ownership` | fake engine | Pass: other-user job/document/file/report/original/cancel/delete are 404; lists are empty; a cache hit gives the second user their own IDs; revoked keys and disabled users are 401; keys never appear in CLI output | test logs |
| R11 | `8146731` | Core fit tests (`test_fit.py`, `test_fit_formats.py`, `test_format_pdf.py`: source overflow, growth, floor, missing font/glyph, search limit, DOCX body, TXT) and R01 service reports | as R01 | Pass at core level; the service stores and returns the same versioned reports (R01: passed, adjusted, unresolved with reasons, not_applicable for TXT). No service-specific fit logic exists | `data/acceptance/p5/out-*/*.report.json` |
| R12 | `8146731` | `test_storage.py` (pins, GC lock, cache expiry keeps user results, deleted/expired documents free blobs, backup/restore round trip and damaged backup); real `doctranslator-server backup` of the running service, `restore` into an empty directory, second service on port 8766 | Windows 11 26200, Python 3.14.7, SQLite (stdlib), FastAPI 0.141.1, SQLAlchemy 2.1.1 | Pass: 34 blobs backed up while running; restore verified every hash; all 26 documents download with identical SHA-256 and size from the restored service | `data/acceptance/p5/backup/`, `r12-restore.txt` |
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
