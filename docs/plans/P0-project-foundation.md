# P0 Project Foundation

Board: [Feature #9008](https://chintand.visualstudio.com/AI%20Projects/_workitems/edit/9008)

## Objective

Create the empty but fully working workspace defined by [ADR-003](../decisions/ADR-003-source-structure.md), with formatting, linting, type checking, import boundary contracts, and tests all enforced in CI, so that every later phase lands inside enforced boundaries from its first commit.

P0 contains no product behavior. Every package is an importable skeleton.

## Relevant Architecture

- [`docs/Architecture.md`](../Architecture.md)
- [ADR-002: Language and Stack](../decisions/ADR-002-language-and-stack.md)
- [ADR-003: Source Structure and Core Separation](../decisions/ADR-003-source-structure.md) - layout and dependency rules this phase implements
- [ADR-005: Translation Quality Evaluation](../decisions/ADR-005-translation-quality-evaluation.md) - why COMET is not a workspace dependency

## Dependencies

None.

## Decisions Pinned by This Plan

These were verified on 2026-09-26 by resolving the full future dependency set (core format libraries, MT runtimes, FastAPI, MCP SDK, SQLAlchemy, Alembic, dev tools) with `uv pip compile --only-binary :all:` for both `x86_64-pc-windows-msvc` and `x86_64-unknown-linux-gnu`, and by running the import contracts, Pyright, Ruff, and pytest configuration below against a throwaway copy of this layout (uv 0.12.6, import-linter 2.15, pyright 1.1.414, ruff 0.16.9, pytest 9.1.1).

| Decision | Choice | Reason |
|----------|--------|--------|
| Python | **3.14** (`.python-version` = `3.14`, `requires-python = ">=3.14"`) | Newest stable CPython; every product dependency, including `torch`, `ctranslate2`, and `transformers`, has 3.14 wheels on Windows and Linux. |
| Package and workspace manager | **uv** 0.12.x, `uv.lock` committed | ADR-003 workspace. |
| Build backend | **`uv_build`** (`requires = ["uv_build>=0.12,<0.13"]`) | Native to uv, zero configuration for `src/` layouts. |
| Formatter and linter | **Ruff** | One tool for both. |
| Type checker | **Pyright**, installed as `pyright[nodejs]`, strict mode everywhere | `[nodejs]` bundles Node, so no separate Node install is needed locally or in CI. |
| Test runner | **pytest** | |
| Import contracts | **import-linter**, config in `.importlinter` at the root | ADR-003 dependency rules. |
| CI | **Azure Pipelines**, `azure-pipelines.yml` at the root, Microsoft-hosted `ubuntu-24.04` and `windows-2025` agents, pinned rather than `-latest` | The organization already runs hosted jobs; production is a Windows laptop, so tests also run on Windows. Images are pinned so an OS upgrade (e.g. `ubuntu-latest` moving to Ubuntu 26 on 2026-10-19) is a deliberate change, not a silent one. |
| Environment variable prefix | `DOCTRANSLATOR_` | Consistent naming for all apps. |
| Local data directory | `data/` at the repository root, gitignored | Default location for benchmark data (P1) and job storage (P5); configurable later. |

Not decided here: the CLI framework (P2), and any runtime dependency of any package. P0 adds **no runtime dependencies**; only dev tools go in the root `dev` dependency group.

Python 3.14 is not compatible with `unbabel-comet` (it requires `numpy<2`). That is expected and handled by ADR-005: COMET runs in an isolated tool environment and is never added to the workspace.

## Target Layout

After P0, the repository contains exactly these new or changed paths (docs excluded):

```text
.gitattributes                      # new
.gitignore                          # add data/
.python-version                     # new: 3.14
.env.example                        # new
.importlinter                       # new
azure-pipelines.yml                 # new
pyproject.toml                      # new: workspace root
uv.lock                             # new, generated
packages/
  core/
    pyproject.toml
    src/doctranslator_core/
      __init__.py
      py.typed
      types.py
      config.py
      document.py
      pipeline.py
      engines/__init__.py
      formats/__init__.py
      formats/base.py
      formats/_ooxml/__init__.py
      formats/pptx/__init__.py
      formats/docx/__init__.py
      formats/xlsx/__init__.py
      formats/pdf/__init__.py
      formats/txt/__init__.py
      fit/__init__.py
      render/__init__.py
    tests/test_package.py
apps/
  cli/
    pyproject.toml
    src/doctranslator_cli/{__init__.py, py.typed}
    tests/test_package.py
  server/
    pyproject.toml
    src/doctranslator_server/
      __init__.py
      py.typed
      app.py
      settings.py
      db/__init__.py
      auth/__init__.py
      jobs/__init__.py
      api/__init__.py
      mcp/__init__.py
    tests/test_package.py
  eval/
    pyproject.toml
    src/doctranslator_eval/{__init__.py, py.typed}
    tests/test_package.py
```

Removed: `src/` (including `src/.gitkeep`). `tests/.gitkeep` stays until `tests/e2e/` gets its first test.

Why skeleton modules exist for empty packages: import-linter `protected` and `independence` contracts fail if a module they name is absent from the import graph. Creating the module tree now lets every structural contract be enforced from day one.

`apps/web` is not created in P0; it arrives in P6 with its own toolchain.

## Implementation Steps

Run all commands from the repository root. Commands are shown for PowerShell; they are identical in bash unless noted.

### 1. Repository hygiene

1. Delete `src/` (only contains `.gitkeep`).
2. Create `.gitattributes`:

   ```gitattributes
   * text=auto eol=lf
   *.ps1 text eol=crlf
   *.pptx binary
   *.docx binary
   *.xlsx binary
   *.pdf binary
   *.png binary
   *.jpg binary
   ```

   Binary rules protect test fixture documents (P2 onwards) from line-ending conversion. After adding the file, run `git add --renormalize .` and commit the result separately if it changes anything, so real changes aren't hidden in normalization noise.

3. Append to `.gitignore`:

   ```gitignore
   # Local data: benchmark datasets, job storage, run outputs. Never committed.
   data/
   ```

4. Create `.python-version` containing `3.14`.

### 2. Workspace root `pyproject.toml`

The root is a virtual project (not a package): it declares the workspace, the dev tools, and all shared tool configuration.

```toml
[project]
name = "doctranslator-workspace"
version = "0.0.0"
requires-python = ">=3.14"
dependencies = [
    "doctranslator-core",
    "doctranslator-cli",
    "doctranslator-server",
    "doctranslator-eval",
]

[dependency-groups]
dev = [
    "import-linter",
    "pyright[nodejs]",
    "pytest",
    "ruff",
]

[tool.uv]
package = false

[tool.uv.workspace]
members = ["packages/core", "apps/cli", "apps/server", "apps/eval"]

[tool.uv.sources]
doctranslator-core = { workspace = true }
doctranslator-cli = { workspace = true }
doctranslator-server = { workspace = true }
doctranslator-eval = { workspace = true }

[tool.ruff]
line-length = 100
target-version = "py314"
src = ["packages/core/src", "apps/cli/src", "apps/server/src", "apps/eval/src"]
include = [
    "packages/**/*.py",
    "apps/**/*.py",
    "tests/**/*.py",
    "scripts/**/*.py",
]

[tool.ruff.lint]
select = [
    "E", "W",   # pycodestyle
    "F",        # pyflakes
    "I",        # isort
    "N",        # pep8-naming
    "UP",       # pyupgrade
    "B",        # bugbear
    "SIM",      # simplify
    "PTH",      # use pathlib
    "RUF",      # ruff-specific
    "S",        # bandit security checks
]

[tool.ruff.lint.per-file-ignores]
"**/tests/**" = ["S101"]  # assert is how pytest works

[tool.ruff.lint.isort]
known-first-party = [
    "doctranslator_core",
    "doctranslator_cli",
    "doctranslator_server",
    "doctranslator_eval",
]

[tool.pyright]
include = ["packages", "apps", "tests", "scripts"]
pythonVersion = "3.14"
typeCheckingMode = "strict"
venvPath = "."
venv = ".venv"

[tool.pytest.ini_options]
testpaths = [
    "packages/core/tests",
    "apps/cli/tests",
    "apps/server/tests",
    "apps/eval/tests",
    "tests",
]
addopts = ["--import-mode=importlib", "-ra", "--strict-markers", "--strict-config"]
xfail_strict = true
filterwarnings = ["error"]
```

Notes for the implementer:

- `include` lists (Ruff, Pyright) are positive lists on purpose: they scope checks to the product directories, so no other directory in the repository is ever linted or type checked.
- `--import-mode=importlib` lets test files in different packages share basenames (e.g. every package has `tests/test_package.py`) without `__init__.py` files in test directories. Do not add `__init__.py` to any `tests/` directory.
- `filterwarnings = ["error"]` makes any warning fail the test run. If a third-party warning later needs silencing, add a narrowly-scoped `ignore:` entry with a comment explaining why; never remove the `error` default.
- Pyright is strict everywhere, tests included. Pyright does not honor `typeCheckingMode` inside `executionEnvironments` (verified with 1.1.414), so a lighter mode for tests is not available without weakening everything. In practice strict tests need only return annotations (`-> None`) and typed fixtures. Do not relax strict mode; if a specific third-party library lacks type information, suppress the specific diagnostic at that import with a comment, not project-wide.

### 3. Member distributions

Each member has this `pyproject.toml` shape. Replace `<dist>`, `<description>`, and the dependencies line per the table below.

```toml
[project]
name = "<dist>"
version = "0.1.0"
description = "<description>"
requires-python = ">=3.14"
dependencies = [<dependencies>]

[build-system]
requires = ["uv_build>=0.12,<0.13"]
build-backend = "uv_build"
```

Apps that depend on the core also add:

```toml
[tool.uv.sources]
doctranslator-core = { workspace = true }
```

| Directory | `<dist>` | Import package | `<dependencies>` | Description |
|-----------|----------|----------------|------------------|-------------|
| `packages/core` | `doctranslator-core` | `doctranslator_core` | (none) | Translation core: formats, engines, fit check, rendering. |
| `apps/cli` | `doctranslator-cli` | `doctranslator_cli` | `"doctranslator-core"` | Command-line interface. |
| `apps/server` | `doctranslator-server` | `doctranslator_server` | `"doctranslator-core"` | Web backend: REST API, MCP endpoint, job service. |
| `apps/eval` | `doctranslator-eval` | `doctranslator_eval` | `"doctranslator-core"` | Translation quality benchmark. |

`uv_build` finds `src/<import package>/` from the distribution name automatically; no extra configuration.

### 4. Skeleton modules

Create every Python file listed in [Target Layout](#target-layout). Each non-empty-by-necessity file contains only a module docstring stating its responsibility, taken from ADR-003, so the structure is self-describing. Examples:

```python
# packages/core/src/doctranslator_core/__init__.py
"""Document Translator core: the public API.

Apps import only from this module and ``doctranslator_core.types`` (ADR-003).
"""

__all__: list[str] = []
```

```python
# packages/core/src/doctranslator_core/formats/base.py
"""Abstract base classes for format capabilities (ADR-003, Format packages)."""
```

```python
# apps/server/src/doctranslator_server/jobs/__init__.py
"""Job service: submit, status, results, workers. The only server module that calls the core pipeline."""
```

Docstrings for the remaining modules, verbatim:

| Module | Docstring |
|--------|-----------|
| `doctranslator_core.types` | `Public data types: languages, translation modes, options, results, fit report, errors.` |
| `doctranslator_core.config` | `Configuration types and validation. Never reads the environment.` |
| `doctranslator_core.document` | `Format-neutral internal representation passed between formats, engines, and fit.` |
| `doctranslator_core.pipeline` | `Orchestrates one translation: extract, translate, write back, fit check.` |
| `doctranslator_core.engines` | `Translation engines, one module per translation mode.` |
| `doctranslator_core.formats` | `File-type-specific code, one package per format.` |
| `doctranslator_core.formats._ooxml` | `Shared low-level helpers for the OOXML formats (PPTX, DOCX, XLSX).` |
| `doctranslator_core.formats.pptx` | `PowerPoint (.pptx) support.` |
| `doctranslator_core.formats.docx` | `Word (.docx) support.` |
| `doctranslator_core.formats.xlsx` | `Excel (.xlsx) support.` |
| `doctranslator_core.formats.pdf` | `PDF support.` |
| `doctranslator_core.formats.txt` | `Plain text support.` |
| `doctranslator_core.fit` | `Format-neutral fit check: text measurement and shrink policy.` |
| `doctranslator_core.render` | `Shared rendering infrastructure. No format-specific logic.` |
| `doctranslator_cli` | `Document Translator command-line interface.` |
| `doctranslator_server` | `Document Translator server: REST API, MCP endpoint, and job service in one process (ADR-001).` |
| `doctranslator_server.app` | `Composition root: builds the app and wires its parts together.` |
| `doctranslator_server.settings` | `Server configuration loaded from the environment.` |
| `doctranslator_server.db` | `Persistence: engine and sessions, ORM models, repositories (ADR-004).` |
| `doctranslator_server.auth` | `Authentication for REST and MCP.` |
| `doctranslator_server.api` | `REST routes. Calls jobs only.` |
| `doctranslator_server.mcp` | `MCP tools. Calls jobs only.` |
| `doctranslator_eval` | `Translation quality benchmark (ADR-005).` |

Every package directory also gets an empty `py.typed` marker at its import root (`src/<import package>/py.typed`).

No module contains imports or code beyond its docstring and, in `__init__.py` of each import root, `__all__: list[str] = []`.

### 5. Package smoke tests

Each member gets `tests/test_package.py`. It is the only test in P0, and it exists so every test path collects at least one test (pytest exits with an error when a path collects nothing) and so a broken package layout fails CI.

```python
# packages/core/tests/test_package.py
import importlib

MODULES = [
    "doctranslator_core",
    "doctranslator_core.types",
    "doctranslator_core.config",
    "doctranslator_core.document",
    "doctranslator_core.pipeline",
    "doctranslator_core.engines",
    "doctranslator_core.formats",
    "doctranslator_core.formats.base",
    "doctranslator_core.formats._ooxml",
    "doctranslator_core.formats.pptx",
    "doctranslator_core.formats.docx",
    "doctranslator_core.formats.xlsx",
    "doctranslator_core.formats.pdf",
    "doctranslator_core.formats.txt",
    "doctranslator_core.fit",
    "doctranslator_core.render",
]


def test_all_modules_import() -> None:
    for name in MODULES:
        importlib.import_module(name)
```

The other three follow the same pattern with their own module lists (from Target Layout). The server's list is `doctranslator_server` plus `.app`, `.settings`, `.db`, `.auth`, `.jobs`, `.api`, `.mcp`.

### 6. Import contracts

Create `.importlinter` at the repository root with exactly this content. Contract names cite the ADR-003 rule they enforce, so a failure points straight to the reason.

```ini
[importlinter]
root_packages =
    doctranslator_core
    doctranslator_cli
    doctranslator_server
    doctranslator_eval
include_external_packages = True

[importlinter:contract:core-independent-of-apps]
name = ADR-003 rule 1: the core imports no app and no surface framework
type = forbidden
source_modules = doctranslator_core
forbidden_modules =
    doctranslator_cli
    doctranslator_server
    doctranslator_eval
    fastapi
    starlette
    uvicorn
    mcp
    typer
    click
    sqlalchemy
    alembic

[importlinter:contract:core-internals-private]
name = ADR-003 rule 2: apps import only the core public API
type = protected
protected_modules = doctranslator_core.*
allowed_importers = doctranslator_core
ignore_imports =
    doctranslator_cli.** -> doctranslator_core.types
    doctranslator_server.** -> doctranslator_core.types
    doctranslator_eval.** -> doctranslator_core.types
unmatched_ignore_imports_alerting = none

[importlinter:contract:apps-independent]
name = ADR-003 rule 3: apps do not import each other
type = independence
modules =
    doctranslator_cli
    doctranslator_server
    doctranslator_eval

[importlinter:contract:server-core-entry]
name = ADR-003 rule 4: in the server, only jobs and settings call the core public API
type = protected
protected_modules = doctranslator_core
as_packages = False
allowed_importers =
    doctranslator_core
    doctranslator_cli
    doctranslator_eval
    doctranslator_server.jobs
    doctranslator_server.settings

[importlinter:contract:api-mcp-independent]
name = ADR-003 rule 4: api and mcp do not import each other
type = independence
modules =
    doctranslator_server.api
    doctranslator_server.mcp

[importlinter:contract:db-access]
name = ADR-003 rule 5: only jobs, auth, and the composition root use db
type = protected
protected_modules = doctranslator_server.db
allowed_importers =
    doctranslator_server.jobs
    doctranslator_server.auth
    doctranslator_server.app

[importlinter:contract:engines-formats-independent]
name = ADR-003 rule 6: engines and formats do not import each other
type = independence
modules =
    doctranslator_core.engines
    doctranslator_core.formats

[importlinter:contract:format-packages-independent]
name = ADR-003 rule 6: format packages do not import each other
type = independence
modules =
    doctranslator_core.formats.pptx
    doctranslator_core.formats.docx
    doctranslator_core.formats.xlsx
    doctranslator_core.formats.pdf
    doctranslator_core.formats.txt

[importlinter:contract:fit-render-format-neutral]
name = ADR-003 rule 6: fit and render do not import formats
type = forbidden
source_modules =
    doctranslator_core.fit
    doctranslator_core.render
forbidden_modules = doctranslator_core.formats
```

How the contract types were chosen (keep these reasons when editing contracts later):

- **`protected` for "only X may import Y" rules (2, 4, 5).** `forbidden` contracts also check indirect imports, so "apps must not import `doctranslator_core.pipeline`" would wrongly fail when the CLI imports the public API, which itself imports `pipeline`. `protected` checks direct imports only.
- **Rule 2 protects `doctranslator_core.*` and ignores imports of `.types`.** New core modules are therefore private by default; only `types` is exempt.
- **Rule 4 uses `as_packages = False`** so it restricts importing the top-level `doctranslator_core` module only, not `doctranslator_core.types`.
- **Rule 7 (format libraries) is not in P0.** A `protected` contract fails with "not present in the graph" when nothing imports the protected module. Each format library's contract is added in the change that first imports it (P2, P4). Template for that change:

  ```ini
  [importlinter:contract:pptx-contained]
  name = ADR-003 rule 7: python-pptx only in formats.pptx
  type = protected
  protected_modules = pptx
  allowed_importers = doctranslator_core.formats.pptx
  ```

- **External modules in `forbidden` contracts do not need to be installed.** Rule 1 correctly breaks on `import fastapi` in the core even before FastAPI is a dependency (verified).
- **Adding a format package** means adding it to the `format-packages-independent` list in the same change.

### 7. Environment example

Create `.env.example`. It documents variables the apps will read; P0 code reads none of them.

```dotenv
# Copy to .env and fill in values. .env is gitignored; never commit secrets.
# Variables are read by the apps (CLI, server, eval), never by the core (ADR-003).

# --- LLM translation mode (P1) ---
# Internal OpenAI-compatible LLM server. The URL and key are provided by the server's owners.
DOCTRANSLATOR_LLM_BASE_URL=
DOCTRANSLATOR_LLM_API_KEY=
DOCTRANSLATOR_LLM_MODEL=gemma-4-31b-it

# --- Local data ---
# Benchmark datasets, job storage, and run outputs. Relative paths resolve from the repository root.
DOCTRANSLATOR_DATA_DIR=data
```

The LLM server URL is deliberately left blank: it is configuration, not something to record in the repository.

### 8. Lock and verify locally

```powershell
uv sync --all-packages
uv run ruff format --check
uv run ruff check
uv run pyright
uv run lint-imports
uv run pytest
```

Commit `uv.lock`. All six commands must succeed with no errors and no warnings.

### 9. CI pipeline

Create `azure-pipelines.yml`:

```yaml
trigger:
  branches:
    include:
      - main

variables:
  UV_VERSION: "0.12.6"
  UV_CACHE_DIR: $(Pipeline.Workspace)/.uv-cache

jobs:
  - job: Checks
    displayName: Format, lint, types, import contracts, tests
    pool:
      vmImage: ubuntu-24.04
    steps:
      - checkout: self
        fetchDepth: 1

      - task: Cache@2
        displayName: Cache uv
        inputs:
          key: 'uv | "$(Agent.OS)" | uv.lock'
          restoreKeys: |
            uv | "$(Agent.OS)"
          path: $(UV_CACHE_DIR)

      - bash: |
          set -euo pipefail
          curl -LsSf "https://astral.sh/uv/${UV_VERSION}/install.sh" | sh
          echo "##vso[task.prependpath]$HOME/.local/bin"
        displayName: Install uv

      - bash: |
          set -euo pipefail
          uv sync --locked --all-packages
          uv run ruff format --check
          uv run ruff check
          uv run pyright
          uv run lint-imports
          uv run pytest
        displayName: Run checks

  - job: WindowsTests
    displayName: Tests on Windows
    pool:
      vmImage: windows-2025
    steps:
      - checkout: self
        fetchDepth: 1

      - task: Cache@2
        displayName: Cache uv
        inputs:
          key: 'uv | "$(Agent.OS)" | uv.lock'
          restoreKeys: |
            uv | "$(Agent.OS)"
          path: $(UV_CACHE_DIR)

      - pwsh: |
          $ErrorActionPreference = 'Stop'
          irm "https://astral.sh/uv/$env:UV_VERSION/install.ps1" | iex
          echo "##vso[task.prependpath]$HOME\.local\bin"
        displayName: Install uv

      - pwsh: |
          $ErrorActionPreference = 'Stop'
          uv sync --locked --all-packages
          if ($LASTEXITCODE) { exit $LASTEXITCODE }
          uv run pytest
          if ($LASTEXITCODE) { exit $LASTEXITCODE }
        displayName: Run tests
```

Notes:

- There is deliberately no `pr:` section. Azure Repos ignores YAML `pr:` triggers; pull request validation comes only from the branch policy in step 10. Until that policy exists, CI runs on pushes to `main` only.
- `uv sync --locked` fails if `uv.lock` is out of date with any `pyproject.toml`, which catches dependency changes committed without relocking.
- `uv` installs Python 3.14 itself from `.python-version`; no `UsePythonVersion` task is needed.
- Static checks run once, on Linux. Tests run on both, because the server's production host is Windows.
- When bumping `UV_VERSION`, bump the `uv_build` range in every member `pyproject.toml` to match.

Register the pipeline in Azure DevOps:

```powershell
az pipelines create --organization https://chintand.visualstudio.com --project "AI Projects" `
  --name "Document_Translator CI" --repository Document_Translator --repository-type tfsgit `
  --branch main --yml-path azure-pipelines.yml --skip-first-run false
```

### 10. Branch protection (requires the repository owner's approval)

After the pipeline is green on `main`, and **only with the repository owner's explicit go-ahead** (it changes how everyone pushes: direct pushes to `main` are blocked and changes go through pull requests), add a build validation policy so pull requests into `main` must pass CI. This is the only way CI runs on pull requests in Azure Repos:

```powershell
az repos policy build create --organization https://chintand.visualstudio.com --project "AI Projects" `
  --repository-id <Document_Translator repository ID> --branch main `
  --build-definition-id <pipeline ID> --display-name "CI" `
  --blocking true --enabled true --queue-on-source-update-only false --manual-queue-only false `
  --valid-duration 0
```

Get the repository ID from `az repos show --repository Document_Translator` and the pipeline ID from `az pipelines show --name "Document_Translator CI"`.

### 11. Documentation

In the same change:

- `docs/Structure.md`: describe the real layout (root files, `packages/`, `apps/`, `tests/`), replacing the note that says the target layout comes later. Remove the `/src` section.
- `AGENTS.md`: add a **Checks** section listing the six commands from step 8, stating that all must pass before a task is complete.
- `docs/IMPLEMENTATION_PLAN.md`: P0 status to Done; move the board item through Active to Closed (see Board Tracking there).

## Interfaces

None. P0 defines no public API; `doctranslator_core.__all__` is empty.

## Edge Cases

- **Windows line endings.** Without `.gitattributes`, Git on Windows converts files to CRLF and `ruff format --check` fails in CI on Linux. Step 1 prevents this.
- **Corporate proxy or TLS interception on the laptop.** If `uv sync` fails with certificate errors locally, run it with `--native-tls` (uses the OS trust store) or set `UV_NATIVE_TLS=1`. Do not disable certificate verification.
- **Pyright downloading Node.** `pyright[nodejs]` avoids this. If a plain `pyright` ends up installed, the first run tries to download Node and may fail behind a proxy.
- **Empty root `tests/`.** It holds no tests in P0. That is fine: pytest only fails when the whole run collects nothing, not when one `testpaths` entry is empty (verified).
- **Slow `uv run` on Windows.** Each `uv run` re-checks the workspace install; repeated invocations (such as the contract verification loop in Tests Required) are much faster calling `.venv\Scripts\lint-imports.exe` directly.

## Tests Required

- `test_package.py` in each of the four members (step 5).
- A one-time manual verification that contracts actually enforce, recorded in the pull request description. Temporarily add each violation below, run `uv run lint-imports`, confirm the named contract is **BROKEN**, then revert:

  | Temporary change | Expected broken contract |
  |------------------|--------------------------|
  | `import fastapi` in `doctranslator_core/engines/__init__.py` | rule 1 |
  | `from doctranslator_core import pipeline` in `doctranslator_cli/__init__.py` | rule 2 |
  | `import doctranslator_server` in `doctranslator_cli/__init__.py` | rule 3 |
  | `import doctranslator_core` in `doctranslator_server/api/__init__.py` | rule 4 (core entry) |
  | `from doctranslator_server import api` in `doctranslator_server/mcp/__init__.py` | rule 4 (api-mcp) |
  | `from doctranslator_server import db` in `doctranslator_server/api/__init__.py` | rule 5 |
  | `from doctranslator_core import formats` in `doctranslator_core/engines/__init__.py` | rule 6 (engines-formats) |
  | `from doctranslator_core.formats import pptx` in `doctranslator_core/formats/docx/__init__.py` | rule 6 (format packages) |
  | `from doctranslator_core import formats` in `doctranslator_core/fit/__init__.py` | rule 6 (fit-render) |

- A one-time CI failure check: push a branch with a deliberate formatting error, confirm the pipeline fails, then fix it.

## Completion Criteria

- [x] A fresh clone runs `uv sync --all-packages` and all six commands in step 8 pass, on Windows and Linux. (Windows: fresh clone of `66ce480` on the development laptop. Linux: CI run 196.)
- [x] `uv.lock` is committed and `uv sync --locked` succeeds in CI. (Run 196.)
- [x] Every violation in the Tests Required table breaks its contract, and the passing baseline shows all 9 contracts kept. (Each violation broke exactly its own contract; 9 kept after revert.)
- [x] The Azure Pipelines run on `main` is green for both jobs, and a deliberately broken branch fails. (Pipeline "Document_Translator CI", ID 9: run 196 on `main` succeeded; run 197 on a throwaway branch failed at `ruff format --check`; branch deleted.)
- [x] No package declares any runtime dependency other than `doctranslator-core`.
- [x] `src/` is gone; `docs/Structure.md` matches the repository; `AGENTS.md` lists the checks.
- [x] The build validation policy on `main` is enabled, or the repository owner has explicitly deferred it. (Deferred by the repository owner on 2026-09-26; no pull request was used for P0, so it is recorded here. CI runs on pushes to `main` only until the policy is enabled.)
- [x] Board item #9008 is Closed and `docs/IMPLEMENTATION_PLAN.md` shows P0 as Done.

## Out of Scope

- Any runtime dependency, product code, public API, configuration loading, or CLI entry point.
- `apps/web` and the Node toolchain (P6).
- Rule 7 import contracts (added with each format library, P2 and P4).
- Test coverage thresholds, pre-commit hooks, release packaging, and deployment.
