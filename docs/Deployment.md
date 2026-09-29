# Deployment and Local Operation

> Accepted storage/identity revision (2026-09-29): [ADR-014](decisions/ADR-014-storage-ownership-and-retranslation.md) and [the storage transition plan](plans/P5-D2-storage-and-ownership.md) supersede earlier shared-cache/version-history and desktop-library requirements. Local runs always export fresh to a chosen path; hosted saved mode keeps owner-scoped current results; internal apps can use temporary results. The hosted parts (saved documents with current translations, temporary jobs, owner-scoped reuse, immutable job results) are implemented in the service below; the desktop local-export profile is a desktop-track deliverable.


Status (2026-09-29): this document distinguishes intended deployment profiles from implemented operations. The shared service (P5) and local CLI are implemented and verified on one Windows host; desktop packaging and non-loopback TLS deployment remain pending.

## Intended Deployment Profiles

The owner-approved direction in [ADR-013](decisions/ADR-013-deployment-profiles.md) adds an installable desktop app and internal-application integration alongside the signed-in web service. These are deployment targets, not runnable release instructions.

| Profile | Installation and operation |
|---|---|
| Hosted web/API | Operator installs service/workers on approved company infrastructure, configures TLS/users/storage and models. Users sign in; internal apps use authorized API credentials. |
| Desktop local | User runs installer, selects a supported model download, then opens the app and drops files/folders. Packaged per-user host/workers start automatically; no developer environment or web sign-in is needed for local processing. |
| Desktop connected | User explicitly configures/signs into a company service. Documents are uploaded there; local history is not synchronized automatically and failures never silently switch modes. |
| Internal-app integration | Use versioned REST under a dedicated application service account; choose temporary results or a saved library explicitly. Public-core Python embedding is a separate deliberate choice without service persistence. |

Desktop setup must document supported OS/architecture, installer signature, runtime/model sizes and licenses, download sources, integrity verification, retry/recovery, per-user data paths, output naming, retention, updates and uninstall. No model is ready until verification/load succeeds. Local MT works offline after assets are installed; internal Gemma requires company connectivity. Additional downloadable models require validated catalog entries, not arbitrary names.

The main desktop workflow is open -> drag/drop files or folders -> select options/destination -> translate -> open results. Tray progress/notifications are secondary. Right-click integration is only a later consideration. Lenovo deployment/preload is a long-term goal requiring a separate managed pilot and distribution/servicing decisions.

The [desktop/internal-app delivery plan](plans/Desktop-and-internal-app-delivery.md) defines D0-D2/I1. Do not publish invented installer commands or claim packaging is complete. Existing developer instructions below remain separate from the intended end-user installer.

## Local Development

From the repository root, with `uv` installed:

```powershell
uv sync --all-packages
uv run ruff format --check
uv run ruff check
uv run pyright
uv run lint-imports
uv run pytest
```

The repository selects Python through `.python-version`; package requirements are Python 3.14 or newer. `uv.lock` owns workspace dependency versions. Optional heavyweight COMET tooling runs outside the workspace as described in the [eval component](Architecture.md#evaluation-reference).

The evaluation entry point is `uv run doctranslator-eval --help`. SMALL-100 conversion is documented in `scripts/convert_mt_model.py`; model files remain under gitignored `data/models/`.

### Local document translation (implemented)

```powershell
uv run doctranslator translate report.docx --to en                 # mode from DOCTRANSLATOR_MODE (default mt)
uv run doctranslator translate deck.pptx --to en --from zh --mode llm --json
```

Output defaults to `<name>.<target><suffix>` beside the input and is never overwritten; `<output>.report.json` holds diagnostics and the fit report. Exit codes: 0 success (warnings possible), 2 invalid input/configuration, 3 engine failure, 4 output path, 130 interrupted. Nothing is stored on a server and there is no cache or history (ADR-010).

Fit uses a font manifest built from `DOCTRANSLATOR_FONT_DIRS` (directories separated by `;` on Windows, `:` elsewhere). The default is the platform font directories; on Windows that includes the user font directory and Office's cloud-font cache, where Office keeps fonts such as Aptos and DengXian. The manifest is cached in `%LOCALAPPDATA%\doctranslator\font-manifest.json` (or `~/.cache/doctranslator/`) and rebuilt for changed files only. Missing fonts make affected containers unresolved; they never block translation. PDF output embeds (subset) the provisioned fonts it uses and falls back to PyMuPDF's built-in faces when none fits; provision the fonts your documents use (and Microsoft YaHei/DengXian, Yu Gothic or Noto CJK for Chinese/Japanese targets) for the closest look.

PDF support uses PyMuPDF (AGPL-3.0), accepted by the owner for the internal service. Before distributing any application that contains it (for example the ADR-013 desktop app), comply with the AGPL for that application or obtain an Artifex commercial license ([ADR-018](decisions/ADR-018-pdf-strategy.md)).

## Configuration and Secrets

See `.env.example` for variable names and the eval component for precedence. The app loads configuration; the core receives typed values and never reads the environment. LLM credentials come from the environment/local `.env`, with the documented Windows credential-vault fallback. Never commit `.env`, credentials, or benchmark text. TLS certificate verification remains enabled and trusts the host's certificate store.

Real LLM integration requires the company network/VPN and configured `DOCTRANSLATOR_LLM_*` settings. Real MT integration needs `DOCTRANSLATOR_TEST_MT_MODEL_DIR` pointing to converted SMALL-100 files. `uv run pytest -m integration` selects those tests; each skips if its settings are absent. A skipped test is not backend verification.

## Shared Service (implemented)

The service is one command on a Windows host in the repository checkout (`uv sync --all-packages` first). Design: [ADR-015](decisions/ADR-015-authentication-and-ownership.md) (users, keys, ownership, network) and [ADR-016](decisions/ADR-016-service-execution-and-operations.md) (queue, storage, retention, backup, defaults). Verified on this laptop over loopback on 2026-09-29 (release evidence R01, R05, R12); a non-loopback TLS deployment and a second client machine are not yet verified (R14).

### Configure

Settings come from the environment or a `.env` file in the working directory (`--env-file` overrides); see `.env.example`.

| Setting | Default | Meaning |
|---|---|---|
| `DOCTRANSLATOR_DATA_DIR` | `data/server` | Database (`doctranslator.db`), `blobs/`, `staging/`, `work/` and the font-manifest cache |
| `DOCTRANSLATOR_MT_MODEL_DIR` | none | Enables MT mode (converted SMALL-100) |
| `DOCTRANSLATOR_LLM_BASE_URL`, `_API_KEY`, `_MODEL`, `_DEPLOYMENT_REVISION` | none | Enable LLM mode (Gemma); the revision is part of the cache identity |
| `DOCTRANSLATOR_FONT_DIRS` | platform and Office font folders | Fonts for fit and PDF output |
| `DOCTRANSLATOR_SERVER_HOST`, `_PORT` | `127.0.0.1`, `8765` | Bind address |
| `DOCTRANSLATOR_SERVER_TLS_CERT`, `_TLS_KEY` | none | Required for a non-loopback bind unless `DOCTRANSLATOR_SERVER_BEHIND_PROXY=true` (a trusted TLS-terminating proxy) |
| `DOCTRANSLATOR_WORKERS` | `1` | Worker processes started by `serve` (each MT worker loads its own model) |
| `DOCTRANSLATOR_MAX_UPLOAD_BYTES` | 100 MiB | Per-file upload limit |
| `DOCTRANSLATOR_MAX_QUEUED_JOBS`, `_PER_USER` | 1000, 200 | Admission limits (429 with `Retry-After` when full) |
| `DOCTRANSLATOR_TEMPORARY_RETENTION_HOURS`, `_SUPERSEDED_RETENTION_DAYS`, `_JOB_RETENTION_DAYS`, `_STAGING_RETENTION_HOURS` | 24, 7, 30, 24 | Retention (ADR-014): temporary results, replaced translations, terminal job metadata, abandoned uploads. Saved documents never expire |
| `DOCTRANSLATOR_OWNER_QUOTA_BYTES` | 20 GiB | Saved library limit per owner (sources plus current translations); new documents beyond it are rejected (`quota_exceeded`) |
| `DOCTRANSLATOR_WEB_DIR` | none | Built web UI (`apps/web/dist`) served at `/` |
| `DOCTRANSLATOR_LEASE_S`, `_HEARTBEAT_S`, `_POLL_S`, `_MAX_ATTEMPTS` | 120, 20, 1, 3 | Worker lease, heartbeat, idle poll and attempt budget |

The server refuses to start on a non-loopback address without TLS or the proxy declaration. With TLS, issue the certificate from the company CA; clients verify it through their OS trust store.

### Install, provision and start

```powershell
uv run doctranslator-server migrate                                   # create or upgrade the schema; run after every upgrade
uv run doctranslator-server users create "Mei Chen"                   # prints the user ID
uv run doctranslator-server keys create <user-id> --label laptop      # prints the key ONCE; deliver it privately
uv run doctranslator-server serve --workers 1                         # REST on http://127.0.0.1:8765/v1 plus supervised workers
```

`serve` and `worker` refuse an unmigrated database. `serve --workers N` restarts a crashed worker after 5 s, doubling to at most 60 s, and runs retention hourly (`--no-retention` disables it). `doctranslator-server worker` runs one extra worker (for example as a separate service); stop workers with CTRL+C or CTRL+BREAK (they finish or abandon the current job; an abandoned job is retried after its lease expires). The OpenAPI document is at `/v1/openapi.json`, interactive docs at `/v1/docs`, liveness at `/v1/health`.

Key and user administration: `users list|disable|enable`, `keys list <user-id>|revoke <key-id>`. Disabling a user blocks all of their keys at once and cancels their unfinished jobs; revoking one key leaves accepted work running. Service identities for internal applications are users created with `--kind service`.

### Use it from the CLI

Each user sets the service URL and their key, then works with batches:

```powershell
$env:DOCTRANSLATOR_SERVER_URL = "http://127.0.0.1:8765"   # or https://<host> with a company certificate
$env:DOCTRANSLATOR_API_KEY = "<key>"                        # or store it in the Windows Credential Manager (service "doctranslator", name DOCTRANSLATOR_API_KEY)
uv run doctranslator whoami
uv run doctranslator submit deck.pptx report.docx --to en --mode mt --wait --download-dir out
uv run doctranslator submit --manifest files.jsonl --to en --mode llm --resume-state run.jsonl --download-dir out --json
uv run doctranslator batches status <batch-id>
uv run doctranslator jobs list --status failed
uv run doctranslator download --batch <batch-id> --output-dir out
uv run doctranslator download --job <job-id> --output-dir out
uv run doctranslator submit report.pdf --to en --temporary --wait --download-dir out   # no saved document, never reused
```

A manifest is UTF-8 JSON Lines, one `{"path": ..., "source": ..., "target": ..., "mode": ...}` per file (paths relative to the manifest; per-line values override the command options). `--resume-state` records each file's submission identity before uploading, so rerunning the same command after an interruption or lost response reuses identities and never creates duplicate jobs; a file that changed since is reported as a conflict. Submission uploads at most `--concurrency` files at a time (default 2) and backs off on 429. Without `--wait`, files are accepted but not yet translated. CTRL+C stops submitting or waiting but never cancels accepted jobs; `batches cancel` does. Downloads are named `<stem>.<target>.<job-id-prefix><suffix>` with `.report.json` beside them, verified by SHA-256 and published atomically; an existing file is never replaced without `--overwrite`. Exit codes: 0 success, 1 some items failed/rejected/cancelled/unsubmitted or could not be downloaded (and unresolved fit with `--fail-on-unresolved`), 2 configuration/authentication/usage, 3 service unreachable, 130 interrupted. Saved mode (the default) files each upload in your library: submitting the same bytes and options again reuses the current translation at once; `--force` translates again and replaces it after success, while earlier job downloads stay available for 7 days. Two files with identical bytes in one batch share one saved document; the second waits for the first and reuses its result. Raw HTTP clients use the same endpoints with `Authorization: Bearer <key>` (example: `scripts/acceptance_http_client.py`).

### Operate

```powershell
uv run doctranslator-server retention run          # also runs hourly inside serve
uv run doctranslator-server backup D:ackups6-09-29
# restore: stop the service, point DOCTRANSLATOR_DATA_DIR at an EMPTY directory, then
uv run doctranslator-server restore D:ackups6-09-29
```

Backup may run while the service is up: it snapshots the database with SQLite's online backup, holds the cleanup lock while copying every referenced blob, and writes `manifest.json` with every hash. Restore verifies the database and every blob hash before placing anything and refuses a directory that already has a database. Logs go to stderr and never contain keys, document text or file paths; the database keeps an audit table of administration, authentication failures, submissions, cancellations, deletions and outcomes. Moving to PostgreSQL or several hosts requires the row locks noted in ADR-016 and shared blob storage first.

P7 adds Streamable HTTP MCP and rendering. Enterprise clients remain blocked on reachable HTTPS hosting and the confidentiality/authentication decisions in P8.

## Verification and Recovery

Local check results do not establish CI success; record CI run IDs and the tested commit when closing a phase. For a failed benchmark scoring step, use the eval `score` command on its translated run directory rather than retranslating. Service data recovery is the backup/restore procedure above (verified by restoring a live backup into an empty directory and comparing every document download, release evidence R12). Rolling back a code upgrade means restoring the backup taken before `migrate`.

## Delivery Handoff Requirements

The [P2-P6 handoff](plans/P2-P6-delivery-handoff.md) requires a verified operating guide at implementation completion. P5 must document migrations, user/key provisioning/revocation, company TLS, model/font identity, worker lifecycle, manifest submissions, owned history/downloads, retention and a tested database-plus-blobs backup/restore. P6 adds browser sessions, the integrated static build, routed reloads and the same-user web workflow. Proposed command names in plans are not runnable instructions until implemented.

Service CLI and REST use the same server. Local `translate` is a distinct mode without persistent cache/history; documentation must never imply local output is automatically saved to the service. Human and service accounts own their batches/jobs/documents even when physical bytes are shared. Saved originals/current translations have quotas, not automatic expiry; temporary results and superseded job outputs expose expiration. Configure cleanup, backup retention and recovery bounds before launch.
