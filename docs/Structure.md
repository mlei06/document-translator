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
- `data/` (gitignored, created on demand) is the default local data directory for benchmark datasets, job storage, and run outputs. It is never committed.

## `/packages`

Reusable libraries.

### `/packages/core`

`doctranslator_core`: everything that determines what a translated document looks like. Its module layout (`types`, `config`, `document`, `pipeline`, `engines/`, `formats/<format>/`, `fit/`, `render/`) and responsibilities are defined in ADR-003. Apps import only `doctranslator_core` and `doctranslator_core.types`.

## `/apps`

Deployable surfaces, each a distribution depending on the core. They never import each other.

- `cli/` - `doctranslator_cli`: command-line interface.
- `server/` - `doctranslator_server`: one process serving the REST API, the MCP endpoint, and the job service (`app`, `settings`, `db/`, `auth/`, `jobs/`, `api/`, `mcp/`).
- `eval/` - `doctranslator_eval`: translation quality benchmark (ADR-005).

Each package and app has its own `tests/` directory next to `src/`.

## `/tests`

Cross-surface end-to-end tests (`e2e/`) and sample documents shared by all test suites (`fixtures/`), per ADR-003. Empty until those tests exist.

## `/scripts`

Development, migration, deployment, and maintenance scripts.

## `/docs`

Project documentation. See `docs/Architecture.md` for what each document is for.

### `/docs/architecture`

System architecture documentation: `components/` (per-component detail) and `diagrams/` (Mermaid diagrams).

### `/docs/plans`

Detailed implementation plans, one per phase or subphase of `docs/IMPLEMENTATION_PLAN.md`.

### `/docs/decisions`

Architecture Decision Records (ADRs).

## `/.agents`

Agent role prompts (`prompts/`) and reusable skills (`skills/`). See `AGENTS.md`.

`skills/azure-devops/SKILL.md` covers Azure DevOps CLI access, publishing a local Git codebase to a repository in an existing project, and managing board work items that track the implementation plan.
