# Deployment and Local Operation

Status (2026-09-28): this document distinguishes intended deployment profiles from development operations. Desktop packaging/installer and deployment acceptance remain pending; consult the roadmap and release evidence for current implementation status.

## Intended Deployment Profiles

The owner-approved direction in [ADR-013](decisions/ADR-013-deployment-profiles.md) adds an installable desktop app and internal-application integration alongside the signed-in web service. These are deployment targets, not runnable release instructions.

| Profile | Installation and operation |
|---|---|
| Hosted web/API | Operator installs service/workers on approved company infrastructure, configures TLS/users/storage and models. Users sign in; internal apps use authorized API credentials. |
| Desktop local | User runs installer, selects a supported model download, then opens the app and drops files/folders. Packaged per-user host/workers start automatically; no developer environment or web sign-in is needed for local processing. |
| Desktop connected | User explicitly configures/signs into a company service. Documents are uploaded there; local history is not synchronized automatically and failures never silently switch modes. |
| Internal-app integration | Use versioned REST for persistent jobs/cache/results. Public-core Python embedding is a separate deliberate choice without service persistence. |

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

PDF support uses PyMuPDF (AGPL-3.0), accepted by the owner for the internal service. Before distributing any application that contains it (for example the ADR-013 desktop app), comply with the AGPL for that application or obtain an Artifex commercial license ([ADR-014](decisions/ADR-014-pdf-strategy.md)).

## Configuration and Secrets

See `.env.example` for variable names and the eval component for precedence. The app loads configuration; the core receives typed values and never reads the environment. LLM credentials come from the environment/local `.env`, with the documented Windows credential-vault fallback. Never commit `.env`, credentials, or benchmark text. TLS certificate verification remains enabled and trusts the host's certificate store.

Real LLM integration requires the company network/VPN and configured `DOCTRANSLATOR_LLM_*` settings. Real MT integration needs `DOCTRANSLATOR_TEST_MT_MODEL_DIR` pointing to converted SMALL-100 files. `uv run pytest -m integration` selects those tests; each skips if its settings are absent. A skipped test is not backend verification.

## Planned Hosting

P5 will define authentication, bind address, firewall rules, worker count, storage paths, retention durations, backup/restore and service lifecycle. ADR-004, ADR-007 and ADR-008 already require database migrations, content-addressed files and separate workers with leases. Do not expose an unauthenticated scaffold while these decisions remain open.

P7 adds Streamable HTTP MCP and rendering. Enterprise clients remain blocked on reachable HTTPS hosting and the confidentiality/authentication decisions in P8.

## Verification and Recovery

Local check results do not establish CI success; record CI run IDs and the tested commit when closing a phase. For a failed benchmark scoring step, use the eval `score` command on its translated run directory rather than retranslating. Deployment rollback and persistent data recovery procedures are P5 deliverables; none are currently implemented or verified.

## Delivery Handoff Requirements

The [P2-P6 handoff](plans/P2-P6-delivery-handoff.md) requires a verified operating guide at implementation completion. P5 must document migrations, user/key provisioning/revocation, company TLS, model/font identity, worker lifecycle, manifest submissions, owned history/downloads, retention and a tested database-plus-blobs backup/restore. P6 adds browser sessions, the integrated static build, routed reloads and the same-user web workflow. Proposed command names in plans are not runnable instructions until implemented.

Service CLI and REST use the same server. Local `translate` is a distinct mode without persistent cache/history; documentation must never imply local output is automatically saved to the service. Users own their batches/jobs/documents even when cache bytes are shared.
