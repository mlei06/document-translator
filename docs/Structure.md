# Repository Structure

<!-- Update this whenever a change alters the repository's conceptual structure, in the same change. This starts generic; make it describe the real layout as the project grows. -->

The layout follows [ADR-003](decisions/ADR-003-source-structure.md): one `uv` workspace in which the translation core is a library and every surface is a separate app depending on it.

```text
pyproject.toml          # workspace root: members, dev tools, Ruff/Pyright/pytest config
uv.lock                 # locked dependencies for the whole workspace
.python-version         # Python version used by uv
.importlinter           # import boundary contracts (ADR-003 dependency rules)
.env.example            # documented configuration variables, no secrets
azure-pipelines.yml     # CI
packages/
  core/                 # doctranslator-core
apps/
  cli/                  # doctranslator-cli
  server/               # doctranslator-server
  eval/                 # doctranslator-eval
tests/
scripts/
docs/
.agents/
```

## Root files

- `pyproject.toml` is a virtual project (not a package). It declares the workspace members, the `dev` dependency group (Ruff, Pyright, pytest, import-linter), and the shared configuration for those tools.
- `.importlinter` holds one contract per ADR-003 dependency rule; contract names cite the rule number.
- `.gitattributes` keeps line endings LF in the repository and marks document and image formats as binary.
- `data/` (gitignored, created on demand) is the default local data directory, never committed: `benchmarks/` (FLORES+), `models/` (converted MT models, e.g. `alirezamsh--small100-ct2-int8/`), `eval/runs/` (benchmark run directories), and later job storage.

## `/packages`

Reusable libraries.

### `/packages/core`

`doctranslator_core`: everything that determines what a translated document looks like. Its module layout (`types`, `config`, `document`, `pipeline`, `engines/`, `formats/<format>/`, `fit/`, `render/`) and responsibilities are defined in ADR-003. Apps import only `doctranslator_core` and `doctranslator_core.types`. Implemented: the text and document APIs, engines, `inline`/`protect`/`detect`/`identity`, the pipeline, TXT/PPTX/DOCX/XLSX/PDF format packages (each Office package and PDF has `adapter.py` and `layout.py`; `formats/_ooxml/` holds safe package access and run-style tables) and `fit/` (fonts, measure, fitter). `render/` is a scaffold (P7).

## `/apps`

Deployable surfaces, each a distribution depending on the core. They never import each other.

- `cli/` - `doctranslator_cli`: `main` (the `doctranslator` command; local synchronous `translate`), `commands` (service commands `whoami`, `submit`, `batches`, `jobs`, `download`), `service` (REST client: retries, verified atomic downloads), `batch` (manifests, resume state, bounded uploads, waiting, downloads), `settings`, `fonts`, `console`.
- `server/` - `doctranslator_server` (the `doctranslator-server` command): `app` (composition root), `settings`, `cli` (migrate, serve, worker, users, keys, retention, backup, restore), `api/` (REST `/v1` routes and wire schemas), `auth/` (API keys, users, ADR-015), `jobs/` (submission service, queue transitions, worker, blob storage, engine identities, retention, backup; the only module calling the core), `db/` (engine and sessions, ORM models, `repositories/`), `mcp/` (scaffold, P7). `apps/server/migrations/` holds the Alembic environment and revisions (ADR-004).
- `eval/` - `doctranslator_eval`: implemented translation quality benchmark (ADR-005, [evaluation reference](Architecture.md#evaluation-reference)). `baselines/` is the planned location for committed scores; full baselines are still deferred.

Planned under [ADR-013](decisions/ADR-013-deployment-profiles.md): a desktop client/launcher, model setup and installer assets. Exact directories/toolkit are chosen at D0; they do not exist merely because the product direction is approved. The client uses HTTP and packaged process entry points, not server Python imports. Hosted and per-user local installations reuse the server implementation.

Each package and app has its own `tests/` directory next to `src/`.

## `/tests`

Sample documents shared by all test suites (`fixtures/<format>/`, provenance in `fixtures/README.md`), cross-surface end-to-end tests (`e2e/`: the service CLI against the service in another process, crash recovery) and shared test helpers (`support/`: fake translators, a local fake LLM server, a synthetic font, OOXML inspection, synthetic PDFs, server builders with a deterministic engine, the fake-engine service process); `tests` is on the pytest and pyright path so suites import `support.*`. Cross-surface end-to-end tests (`e2e/`) arrive with the service (P5).

## `/scripts`

Development, migration, deployment, and maintenance scripts.

- `convert_mt_model.py` converts SMALL-100 to CTranslate2 in a throwaway environment with PyTorch (ADR-006; usage in its docstring).
- `native_office_check.ps1` opens documents read-only in native Word/Excel/PowerPoint, detects repair, optionally exports PDFs and reads Excel formula values (release evidence).
- `render_pdf_pages.py` rasterizes PDFs to PNG for visual spot checks.
- `acceptance_http_client.py` is an independent REST client (only HTTP, no project code) for release evidence: submit, wait, download, verify hashes, confirm inputs unchanged.
- `pdf_independent_check.py` checks translated PDFs with PDFium (the Chrome/Edge PDF engine, in a throwaway environment): page geometry, remaining source text in PDFium's own extraction, and page renders (release evidence).
- `acceptance_local.py` runs every fixture format through the real local CLI with both engines and records outcomes, fit reports and timings.

## `/docs`

Project documentation. See `docs/Architecture.md` for what each document is for.

### `/docs/Architecture.md`

The single architecture document: system context, component responsibilities and boundaries, interfaces, dependencies, inline Mermaid diagrams, file-specific flows, cross-cutting concerns, constraints and tradeoffs. Core and evaluation reference material is included in sections of this file. Link to its headings instead of creating separate component or diagram documents. ADRs retain decision history and plans retain implementation tasks and proposals.

### `/docs/plans`

Detailed implementation plans, one per phase or subphase of `docs/IMPLEMENTATION_PLAN.md`.

### `/docs/decisions`

Architecture Decision Records (ADRs).

### `/docs/design`

Visual design exploration and source assets gathered ahead of the phase that implements them (for example `web-gui/` for P6). Exploration, not decided architecture. `web-gui/prototype/` holds the runnable single-file mock UI (`lenny.html` plus web-sized assets) that P6 audits and ports; it is not production code and has no build or tests.

### `/docs/experiments`

Small design experiments and their evidence, separate from production code. `xlsx-roundtrip/spike.py` is an isolated, dependency-pinned script comparing two XLSX write strategies. Its disposable workbooks and machine-readable results live in gitignored `data/experiments/xlsx-roundtrip/`; the report and script are tracked here. These scripts are outside the production test/typecheck paths and are verified separately using their documented commands.

`desktop-packaging/` contains the D0 Python runtime packaging probe and build instructions. It exercises the existing CLI with a separately installed model; it is not a production desktop app or persistent server. Generated bundles and execution evidence stay in ignored `data/experiments/desktop-packaging/`.

## `/.agents`

Agent role prompts (`prompts/`) and reusable skills (`skills/`). See `AGENTS.md`.

`skills/azure-devops/SKILL.md` covers Azure DevOps CLI access, publishing a local Git codebase to a repository in an existing project, and managing board work items that track the implementation plan.
