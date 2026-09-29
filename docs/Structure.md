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

`doctranslator_core`: everything that determines what a translated document looks like. Its module layout (`types`, `config`, `document`, `pipeline`, `engines/`, `formats/<format>/`, `fit/`, `render/`) and responsibilities are defined in ADR-003. Apps import only `doctranslator_core` and `doctranslator_core.types`. Only the text API, types/config and engines are implemented; document, pipeline, format, fit and render files are scaffolds.

## `/apps`

Deployable surfaces, each a distribution depending on the core. They never import each other.

- `cli/` - `doctranslator_cli`: package scaffold for the P2 command-line interface.
- `server/` - `doctranslator_server`: scaffolds for the future REST/MCP web process and workers (ADR-008) (`app`, `settings`, `db/`, `auth/`, `jobs/`, `api/`, `mcp/`). No service is runnable yet.
- `eval/` - `doctranslator_eval`: implemented translation quality benchmark (ADR-005, [evaluation reference](Architecture.md#evaluation-reference)). `baselines/` is the planned location for committed scores; full baselines are still deferred.

Planned under [ADR-013](decisions/ADR-013-deployment-profiles.md): a desktop client/launcher, model setup and installer assets. Exact directories/toolkit are chosen at D0; they do not exist merely because the product direction is approved. The client uses HTTP and packaged process entry points, not server Python imports. Hosted and per-user local installations reuse the server implementation.

Each package and app has its own `tests/` directory next to `src/`.

## `/tests`

Cross-surface end-to-end tests (`e2e/`) and sample documents shared by all test suites (`fixtures/`), per ADR-003. Empty until those tests exist.

## `/scripts`

Development, migration, deployment, and maintenance scripts.

- `convert_mt_model.py` converts SMALL-100 to CTranslate2 in a throwaway environment with PyTorch (ADR-006; usage in its docstring).

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

## `/.agents`

Agent role prompts (`prompts/`) and reusable skills (`skills/`). See `AGENTS.md`.

`skills/azure-devops/SKILL.md` covers Azure DevOps CLI access, publishing a local Git codebase to a repository in an existing project, and managing board work items that track the implementation plan.

### Additional model experiments

Optional TranslateGemma and HY-MT2 profiles share the LLM HTTP engine; model-native
prompt construction lives in `engines/translation_prompts.py` and stays separate
from the existing generic JSON-batch prompt. `scripts/local_translation_model.ps1`
starts/stops pinned local CUDA servers and creates ignored per-model configuration.
`docs/experiments/translation-profiles/` holds the operation guide and reproducible
FLORES subset benchmark. Downloaded runtimes, GGUF files, local API keys, logs and
raw benchmark output stay in ignored `data/`.
