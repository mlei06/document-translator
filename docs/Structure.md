# Repository Structure

Use the [documentation index](README.md) to find current contracts, verification and history. The [unified specification](plans/unified-translator-design.md) governs current delivery; superseded plans are archived rather than maintained as competing entry points.

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
  web/                  # authenticated immediate-batch React website
  desktop/              # native shell, installer and packaged runtime build inputs
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

`doctranslator_core`: everything that determines what a translated document looks like. Apps import only `doctranslator_core` and `doctranslator_core.types`. Implemented modules include text/document APIs, `policy`, engines, `inline`/`protect`/`detect`/`identity`, the pipeline, TXT/PPTX/DOCX/XLSX/PDF format packages and standard `fit/` (fonts, measurement, bounded native repairs). `formats/_ooxml/` holds safe package access and run-style tables. The empty `render/` namespace remains an import-contract boundary; production renderer implementations are removed.

## `/apps`

Deployable surfaces, each a distribution depending on the core. They never import each other.

- `cli/` - `doctranslator_cli`: `main` (the `doctranslator` command; local synchronous `translate`), `commands` (service commands `whoami`, `submit`, `batches`, `jobs`, `download`), `service` (REST client: retries, verified atomic downloads), `batch` (manifests, resume state, bounded uploads, waiting, downloads), `settings`, `fonts`, `console`.
- `server/` - `doctranslator_server`: composition roots `app` and `desktop`, settings and CLI, REST/session/desktop wire APIs, authentication, and `jobs/` for shared translation, queue/worker, storage, desktop lifecycle and exports. Only jobs/settings call the public core. `db/` owns ORM models, transactions and repositories; `migrations/` holds Alembic schema revisions. `mcp/` remains a later scaffold.
- `eval/` - `doctranslator_eval`: implemented translation quality benchmark (ADR-005, [evaluation reference](Architecture.md#evaluation-reference)). `baselines/` is the planned location for committed scores; full baselines are still deferred.

`desktop/` contains the Tauri native shell, local HTML/CSS/JavaScript main/activity surfaces, C++ Explorer command, NSIS/sparse identity packaging inputs and PyInstaller build entry point. The shell uses authenticated HTTP and packaged process entry points. Hosted and per-user local installations reuse the server implementation. Signed release and clean-machine acceptance are tracked separately from local compilation.

Each package and app has its own `tests/` directory next to `src/`.

Server `jobs/davy.py` owns cached, authenticated model-list discovery and safe status mapping. `jobs/engines.py` combines that approval filter with local MT artifact readiness and preserves pinned worker identities. The API exposes these through capabilities and authenticated refresh; frontend `ui/DavyStatus.tsx` presents connection feedback without accessing endpoint credentials.

### `/apps/web`

React/TypeScript implementation of the Lenny website. `src/api` owns generated OpenAPI types, same-origin session transport and query coordination; screens/components own sign-in, immediate target-pinned upload batches, progress, private History and presentation preferences. `world`, `lenny` and local assets preserve the visual design. The UI calls REST, never Python/server internals or models directly. Preview and personal translation-setting screens are removed.

`vite.config.ts` builds the SPA and configures Vitest. Playwright configuration and `e2e` exercise a separate deterministic real-service fixture; they do not inject mock production data. Browser reports, screenshots and dependency/build directories are generated artifacts. Run frontend checks independently of the Python workspace checks and regenerate API types through `npm run gen:api` after wire-schema changes.

## `/tests`

Sample documents shared by all test suites (`fixtures/<format>/`, provenance in `fixtures/README.md`), cross-surface end-to-end tests (`e2e/`: the service CLI against the service in another process, crash recovery) and shared test helpers (`support/`: fake translators, a local fake LLM server, a synthetic font, OOXML inspection, synthetic PDFs, server builders with a deterministic engine, the fake-engine service process); `tests` is on the pytest and pyright path so suites import `support.*`. Cross-surface end-to-end tests (`e2e/`) arrive with the service (P5).

## `/scripts`

Unified modules: the core `policy.py` owns the approved automatic order and digest.
Server `jobs/automatic.py`, `shared.py`, and `capacity.py` extend the existing queue with
pinned routing, shared current results/private grants, and global reservations. Desktop
bootstrap/authentication and local asset/export helpers live within the server's existing
composition/auth/jobs boundaries. Production `jobs/preview.py`, `jobs/pages.py`, page
repositories and core/format rendering implementations have been removed. The empty core
`render` package remains only as an import-contract boundary, not an executable renderer.

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

ADR-029's production renderer/preview removal is implemented within the existing package boundaries. Required translation/PDF/font code remains; standalone QA scripts are not runtime dependencies.

Automatic website translation and shared cache/private History extend existing server settings, jobs, repositories and web screens. They add no service/package boundary. The unified specification and current Architecture overview govern their contracts.

Current product specification, execution checklist, desktop UI contract, deferred quality study and task template. Historical phase plans are under `archive/plans/`.

### `/docs/verification`

Current core, website and desktop evidence reports, with tested scope and remaining gates distinguished from implementation claims. Generated artifacts remain in ignored local directories.

### `/docs/archive`

Superseded phase plans and the September 2026 roadmap, retaining board references, rationale and earlier evidence. Archive notices direct readers to current contracts; archived requirements are not implementation authority.

### `/docs/decisions`

Architecture Decision Records (ADRs).

### `/docs/design`

Visual design exploration and source assets gathered ahead of the phase that implements them (for example `web-gui/` for P6). Exploration, not decided architecture. `web-gui/prototype/` holds the runnable single-file mock UI (`lenny.html` plus web-sized assets) that P6 audits and ports; it is not production code and has no build or tests.

### `/docs/experiments`

Small design experiments and their evidence, separate from production code. `xlsx-roundtrip/spike.py` is an isolated, dependency-pinned script comparing two XLSX write strategies. Its disposable workbooks and machine-readable results live in gitignored `data/experiments/xlsx-roundtrip/`; the report and script are tracked here. These scripts are outside the production test/typecheck paths and are verified separately using their documented commands.

`desktop-packaging/` contains the D0 Python runtime packaging probe and build instructions. It exercises the existing CLI with a separately installed model; it is not a production desktop app or persistent server. Generated bundles and execution evidence stay in ignored `data/experiments/desktop-packaging/`.

`laptop-mt/` contains the serial SMALL-100/HY-MT runtime/thread benchmark and Windows
process-tree CPU/GPU profiler. Raw samples and generated documents stay in ignored
`data/experiments/laptop-mt/`. It reuses the SMALL-100 export and runtime experiment in
`openvino-small100/` without promoting that experimental OpenVINO wrapper into production.

## `/.agents`

Agent role prompts (`prompts/`) and reusable skills (`skills/`). See `AGENTS.md`.

`skills/azure-devops/SKILL.md` covers Azure DevOps CLI access, publishing a local Git codebase to a repository in an existing project, and managing board work items that track the implementation plan.
