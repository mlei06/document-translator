# Deployment and Local Operation

## Unified runtime configuration

The automatic website API is implemented as verified staging followed by target-only
submission. Configure `DOCTRANSLATOR_WEB_TRANSLATION_POLICY` as JSON with revision
`web-auto-v2`, `davy_order` equal to `gemma`, `nemotron-3-ultra`,
`nemotron-3-super-120b`, `gpt-oss-120b-thinking`, `gpt-oss-120b`, `laguna-s-2.1`, and
`local_translator_id` equal to `hy-mt-local`. Configure candidate identities through the
existing translator/Davy settings. Gemma must bind to `gemma-4-31b-it`; website HY-MT
must use the loopback HY-MT protocol with a deployment revision. Missing policy is a
configuration error, not permission to select an arbitrary model.

Set global blob and workspace budgets with `DOCTRANSLATOR_GLOBAL_BLOB_BUDGET_BYTES`
and `DOCTRANSLATOR_GLOBAL_WORK_BUDGET_BYTES` (defaults 100 GiB and 8 GiB). Reserve
additional filesystem capacity for database/WAL, logs, models and backups. Admission
preserves the larger of 5 GiB or 10% free volume capacity. Default input/output/report/work
caps are 100 MiB, 200 MiB, 16 MiB and 1 GiB. Retention sweeps run every five minutes.

Website clients upload to `POST /v1/documents?staging=true` immediately, then submit
`POST /v1/documents/{id}/translations` with `target`, `selection_policy=website_auto`,
`retention=cached`, `download_semantics=current_shared` and a stable submission ID or
batch/client-item identity. `GET /v1/history` and its authorized `/{id}/file` resolve current
results; deletion revokes only that user's grant. Removed preview and skip-fit routes
return 404, and thorough fit requests are rejected. LibreOffice is no longer required.

Desktop bootstrap is `doctranslator-server desktop` with the versioned secret envelope
on inherited stdin. Do not invoke it by putting a credential in command-line arguments.
The runtime and shell release evidence distinguish unsigned local builds from signed
clean-machine installer acceptance. Existing secrets and model assets are not rewritten
automatically when applying source changes.

The older deployment examples below are historical where they specify preview/thorough
operations or personalized website translation controls; those features are removed.

> Current target contract: [Unified translator design](plans/unified-translator-design.md). Both products use Gemma, Nemotron 3 Ultra, Nemotron 3 Super, GPT-OSS Thinking, GPT-OSS, Laguna, then available HY-MT. Desktop has no mode controls and calls Davy directly with the website deployment's Davy inference key injected during restricted installer packaging. Do not put that secret in repository configuration, documentation or logs. The shared client key is recoverable by recipients; rotation must update website and desktop distribution together. These are design requirements, not live environment changes.







## Local HY-MT inference

The `hy-mt` LLM protocol supports HY-MT1.5-1.8B served by an explicitly managed llama.cpp
process ([ADR-025](decisions/ADR-025-local-hy-mt.md)). This is local inference despite using
the existing `llm` wire mode. It requires installed GGUF weights and a compatible llama.cpp
binary; it does not download models or supervise the process.

For the tested Core Ultra 7 155H / Intel Arc laptop, use:

```powershell
data/tools/llama.cpp/vulkan/llama-server.exe `
  -m data/models/gguf/HY-MT1.5-1.8B-Q8_0.gguf `
  --alias hy-mt --host 127.0.0.1 --port 8099 `
  -ngl 99 -t 4 -tb 4 -c 16384 -np 4 --no-context-shift --cache-ram 0
```

These are measured settings for this host, not universal performance defaults. See the
[laptop experiment](experiments/laptop-mt/README.md) for measured settings and hardware.
For CPU inference, use the CPU build and `-ngl 0`. Keep context capacity per slot when
increasing `-np`; align client concurrency with the number of server slots. Disabling context
shift ensures oversized inputs fail rather than silently discarding earlier source tokens.

For the local CLI, create a private settings file:

```dotenv
DOCTRANSLATOR_MODE=llm
DOCTRANSLATOR_LLM_PROTOCOL=hy-mt
DOCTRANSLATOR_LLM_EXECUTION_LOCATION=server
DOCTRANSLATOR_LLM_BASE_URL=http://127.0.0.1:8099/v1/
DOCTRANSLATOR_LLM_API_KEY=local
DOCTRANSLATOR_LLM_MODEL=hy-mt
DOCTRANSLATOR_LLM_DEPLOYMENT_REVISION=replace-with-gguf-sha256-and-runtime-settings-revision
DOCTRANSLATOR_LLM_MAX_CONCURRENCY=4
DOCTRANSLATOR_LLM_MAX_OUTPUT_TOKENS=2048
```

Use `doctranslator translate INPUT --from zh --to en --config PATH` as usual. `local` is a
placeholder for an unauthenticated loopback server; when server authentication is enabled,
configure the matching secret privately. Server-local configurations ignore HTTP proxy
environment variables. Never point this configuration at an unapproved remote endpoint.

For web/service selection, add an entry to the existing `DOCTRANSLATOR_TRANSLATORS` JSON list:

```json
{
  "id": "hy-mt-local",
  "label": "HY-MT 1.5 1.8B Q8",
  "engine": {
    "mode": "llm",
    "protocol": "hy-mt",
    "execution_location": "server",
    "base_url": "http://127.0.0.1:8099/v1/",
    "api_key": "local",
    "model": "hy-mt",
    "deployment_revision": "replace-with-gguf-sha256-and-runtime-settings-revision",
    "max_concurrency": 4,
    "max_output_tokens": 2048
  }
}
```

Preserve existing entries/default unless deliberately changing them, and restart API/workers
after configuration changes. HY-MT appears as **On server** and is not a Davy model. The configured
entry is not a health check: an unavailable external server produces an explicit job failure.
The model revision is operator-declared, not remotely attested; update it whenever weights or
generation-affecting runtime settings change. `max_loaded_local_models` does not unload this
external model, so stop unused llama.cpp processes explicitly. No model is silently substituted.

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

Old demo renderer settings no longer apply. Initialize the current schema before starting matched API/workers and the rebuilt website; the unified service publishes direct output/report files only.

LAN demo exception approved by the owner on 2026-09-29: the laptop binds HTTPS to its Wi-Fi address `10.41.41.102:8765`, with two workers. A temporary self-signed certificate in ignored `data/website/tls-demo/` expires 2026-10-06; coworkers must accept its browser warning. This is a temporary exception to ADR-015's company-issued certificate requirement, not the production certificate policy. The Windows firewall rule `DocumentTranslator-Demo-HTTPS-8765` permits TCP 8765 only on Wi-Fi, Domain/Private profiles, from `10.41.40.0/22`. An IP/subnet change requires reconfiguration and a matching certificate. Use the HTTPS Wi-Fi URL on the laptop too; the listener is no longer on loopback. Remove the demo firewall rule and restore the loopback configuration when LAN access is no longer needed. Never distribute the private key.

The web `npm run build` command typechecks, then awaits Vite's build API through `scripts/build.mjs`. The script exits after successful output writes because native file handles can otherwise leave the completed Vite build process running on Windows. Build errors still produce a nonzero exit.

### Translator configuration

Availability follows [ADR-024](decisions/ADR-024-translator-availability.md): local MT models must have their required artifacts installed on this backend. Missing models are omitted from new-job choices without loading every model or disabling other installed models. Local installation is checked at startup; restart API/workers after installing or removing models. Davy Retry connection does not reload the local catalog.

For Davy, set `DOCTRANSLATOR_DAVY_BASE_URL` to the OpenAI-compatible API base (including `/v1` when required), `DOCTRANSLATOR_DAVY_API_KEY` to its secret, and `DOCTRANSLATOR_DAVY_MODELS` to an approved JSON list such as `[{"id":"gemma","label":"Gemma","model":"gemma-4-31b-it"}]`. Each model supports `enabled`, `json_mode`, `batch_size`, `max_concurrency` and `deployment_revision`. Use exact model IDs from your deployment. Remove corresponding generic LLM entries from `DOCTRANSLATOR_TRANSLATORS` so they do not bypass Davy discovery. The default can name an enabled Davy entry even when the connection is temporarily unavailable.

The service intersects that list with authenticated `GET /models`, caching discovery for 60 seconds. `POST /v1/translators/refresh` returns refreshed capabilities and is authenticated, with browser CSRF protection and a five-second retry floor. No per-model inference probes run. Missing credentials, network/VPN failures, rejected credentials and no matching models are distinct UI states. A model being listed does not prove inference health. Configuration changes still require an API/worker restart.

[ADR-019](decisions/ADR-019-configured-translators.md) defines installation choices. The shared service administrator configures translators; website users choose enabled entries. LLM support is built in, but no LLM is offered without connection configuration. Configured does not guarantee remote reachability, and failure never silently switches models or sends local-mode files remotely.

For multiple translators, set `DOCTRANSLATOR_TRANSLATORS` to a JSON list and `DOCTRANSLATOR_DEFAULT_TRANSLATOR_ID` to an enabled ID. Each entry has `id`, `label`, `enabled` and `engine`. Example entry for an already-installed supported model:

```json
{
  "id": "small100",
  "label": "SMALL-100",
  "enabled": true,
  "engine": {
    "mode": "mt",
    "model_dir": "data/models/alirezamsh--small100-ct2-int8",
    "model_family": "small100",
    "device": "auto",
    "compute_type": "int8"
  }
}
```

An LLM entry uses `engine.mode=llm` with `base_url`, `api_key`, `model` and `deployment_revision`; supply real connection values through the protected deployment configuration, not committed examples or browser settings. Multiple entries may use the same mode. Supported runtime adapters remain limited to those actually implemented; a configured name does not install a new model or certify another model family.

Without a translator list, the existing `DOCTRANSLATOR_MT_*` and `DOCTRANSLATOR_LLM_*` settings create legacy `mt` and `llm` IDs. Local synchronous CLI configuration remains separate. API requests use `translator_id`; legacy `mode` callers are still supported. Capabilities return safe names, IDs, execution location and default, never secrets or model paths. Hosted local inference is labelled **On server**, not **On this device**.

`DOCTRANSLATOR_MAX_LOADED_LOCAL_MODELS` defaults to 1 per worker. Models load only when selected. Compatible SMALL-100 Beam 4/Greedy presets share weights and tokenizer, passing decoding settings per inference call. The bound counts distinct runtimes, not presets; exceeding it closes all bindings of the least-recently-used local runtime. Account for the number of worker processes when budgeting RAM/VRAM. Restart API and workers together when changing configuration. Queued jobs retain their selected ID/fingerprint and fail explicitly if the configured model identity no longer matches; they never switch to the new default.

Desktop installer/setup selection and subsequent downloads/removal remain D0/D1 deliverables. It will use the supported catalog, show download/disk/hardware information, offer a default and permit an explicit remote-only setup. This service configuration is not a shipped installer.

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

### Upgrade compatibility for batch retries

Migration `0003` preserves existing jobs and their pinned model identity. Accepted pre-upgrade submissions remain replayable. A rejected batch item created before this migration has no persisted translator selection; retrying that old item can return `409` instead of the original rejection. Submit a corrected item with a new item identity. This does not duplicate translation work.

### Local website with accounts and model presets

[ADR-020](decisions/ADR-020-browser-accounts-and-decoding.md) adds email/password sign-in and optional account creation. Set `DOCTRANSLATOR_REGISTRATION_ENABLED=true` to allow registration; it defaults to false. Passwords must contain 8 to 128 characters. Password-backed sessions retain the same owner scope, cookie/CSRF protections and expiry as key-backed sessions. API keys remain available to CLI/internal clients. Email verification and password recovery are not implemented by this basic account flow.

For the current local instance, ignored `data/website.env` configures HTTPS on loopback port 8765, persistent state under `data/website`, the built `apps/web/dist`, and two workers. The configured local presets are `small100-beam4`, `small100-greedy`, and `hy-mt-local`, alongside six existing Davy entries. SMALL-100 shares one installed bundle with beam sizes 4 and 1; its beam-4 preset remains the default. HY-MT requires the separate loopback llama-server described above. This private settings file contains endpoint credentials and must remain untracked. The previous network bind address was unavailable during HY-MT integration, so it was replaced with loopback while retaining TLS settings.

Build the frontend with `npm run build` from `apps/web`, then run from the repository root:

```powershell
uv run doctranslator-server --env-file data/website.env migrate
uv run doctranslator-server --env-file data/website.env serve
```

Open `https://127.0.0.1:8765` using the configured certificate trust and sign in. Click Lenny to open translator settings. Changes affect future submissions and retranslation; accepted jobs retain their selected preset. The service must remain running for the website and workers to function.


### Protected words and maintained names

Users manage private protected words in **Lenny settings > Protected words**. Save applies to new submissions across devices. The built-in company/product list can be disabled; syntax protection remains active. Explicit API `protected_terms` add to the account list, and optional `use_default_dictionary` overrides its switch for that submission. Existing CLI clients inherit service account preferences when they omit the override.

Maintainers edit `packages/core/src/doctranslator_core/protected_names.txt`, review ambiguous names carefully, run protection regressions, and deploy/restart the service. The packaged dictionary digest and protection version prevent reuse of older incompatible results. Do not modify that data file inside a running installation. Local core document callers can set `use_default_dictionary=False` and supply their own `protected_terms`.

### Offline fit modes

New translations use fit v2 `standard` automatically. It performs local structure, font and geometry work without invoking an Office renderer or another translation model. Explicit internal API clients can configure supported fit floors. Website automatic requests use the fixed standard profile and expose no fit controls.

Thorough fit, preview rendering and production LibreOffice integration have been removed. Standard fit may report unresolved constraints honestly. PDF construction requires legal placement; impossible placement returns `layout_unresolvable` without publishing a damaged PDF.

Output fingerprints pin standard-fit settings and relevant font identities. Restart matched API/workers after deploying code or changing configuration. Website shared downloads resolve the current slot, while explicit internal-app exact-result promises remain separate.
