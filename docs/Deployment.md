# Deployment and Local Operation

Status (2026-09-27): local development and the eval CLI are available. There is no deployed document CLI, REST service, web GUI, or MCP endpoint. Laptop hosting is an accepted P5 direction, not a working deployment.

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

The existing command is `uv run doctranslator-eval --help`. The product command `doctranslator translate` is proposed for P2 and does not exist yet. SMALL-100 conversion is documented in `scripts/convert_mt_model.py`; model files remain under gitignored `data/models/`.

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
