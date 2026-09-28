# Implementation Plan

<!--
This is the roadmap / dependency graph for the project, not the detailed how-to for any one phase - that level of detail goes in docs/plans/. Give every phase an ID (P0, P1, P2, ...) and subphases as needed (P2.1, P2.2). Those IDs are used to name files in docs/plans/, e.g. docs/plans/P2.1-authentication.md.
-->

Phases build the system from the inside out: the workspace, then the translation engines and the benchmark that measures them, then documents and the CLI, then the server surfaces. The README's delivery phases map onto these as follows: CLI is P0-P4, Web GUI and job service is P5-P6, MCP server is P7, enterprise platform integration is P8.

## Board Tracking

Each phase is one **Feature** on the Azure DevOps board (organization `chintand`, project `AI Projects`, tag `Document Translator`), under the Epic [**Document Translator** (#9007)](https://chintand.visualstudio.com/AI%20Projects/_workitems/edit/9007). The board item ID is listed under each phase heading.

Keep phase status and the board in sync:

| Phase status here | Board state | When |
|-------------------|-------------|------|
| Not started | New | Default |
| In progress | Active | The phase's first plan in `docs/plans/` is approved |
| Done | Closed | Every completion criterion below is met and verified |

Updating a phase here (goal, deliverables, completion criteria, status) and updating its board item happen in the same change.

## Dependency Graph

```mermaid
flowchart LR
    P0[P0 Foundation] --> P1[P1 Engines and benchmark]
    P1 --> P2[P2 Documents and CLI]
    P2 --> P3[P3 Fit check]
    P3 --> P4[P4 PDF]
    P2 --> P5[P5 Server and jobs]
    P5 --> P6[P6 Web GUI]
    P4 --> P7[P7 MCP and visual review]
    P5 --> P7
    P7 --> P8[P8 Enterprise platforms]
```

P5 can start once P2 is done, in parallel with P3 and P4.

---

## P0 - Project Foundation

Board: [Feature #9008](https://chintand.visualstudio.com/AI%20Projects/_workitems/edit/9008) | Status: Done | Plan: [P0-project-foundation.md](plans/P0-project-foundation.md)

### Goal

An empty but fully working workspace in the layout of [ADR-003](decisions/ADR-003-source-structure.md), with every check enforced in CI, so all later code lands inside enforced boundaries from its first commit.

### Dependencies

None.

### Deliverables

- `uv` workspace root with pinned Python version, and skeleton distributions for `packages/core`, `apps/cli`, `apps/server`, and `apps/eval`, each importable with an empty public API. (`apps/web` is created in P6.)
- Shared tooling configured at the root: formatter and linter, static type checker, test runner.
- Import-linter contracts for all dependency rules in ADR-003.
- Azure Pipelines CI running format check, lint, type check, import contracts, and tests on `main`, and on pull requests through a build validation branch policy.
- `.env.example` documenting configuration variables, with no secret values.
- Scaffold root `src/` removed; `docs/Structure.md` describes the real layout.

### Completion Criteria

- A fresh clone installs with one `uv sync` and all checks pass locally and in CI.
- A deliberately forbidden import (e.g. core importing FastAPI) fails the import contract check, verified once and reverted.
- `docs/Structure.md` matches the repository.

---

## P1 - Translation Engines and Benchmark

Board: [Feature #9009](https://chintand.visualstudio.com/AI%20Projects/_workitems/edit/9009) | Status: In progress | Plan: [P1-translation-engines-and-benchmark.md](plans/P1-translation-engines-and-benchmark.md) (approved 2026-09-27)

### Goal

Translate plain text in both LLM and MT modes across all 12 language directions, and measure the quality of each with the benchmark from [ADR-005](decisions/ADR-005-translation-quality-evaluation.md).

### Dependencies

- P0

### Deliverables

- Core component doc (`docs/architecture/components/core.md`) with the `TranslationEngine` interface and public text translation API.
- Core `types.py` and `config.py`: languages, modes, options, engine configuration.
- `engines/llm.py`: internal LLM server client (OpenAI-compatible, API key, internal CA trust), batching, retries, versioned prompts, deterministic settings for evaluation.
- `engines/mt.py`: local MT model engine, runtime imported lazily behind the `[mt]` extra, model selectable by configuration.
- Public text-level translation function in the core API.
- `apps/eval`: FLORES+ download script, benchmark runner, COMET and chrF scoring, paired bootstrap comparison, run recording.
- ADR selecting the MT model ([ADR-006](decisions/ADR-006-mt-model-selection.md): SMALL-100).

### Completion Criteria

- Both modes translate all 12 directions through the public API.
- LLM engine is tested against a fake HTTP server (errors, retries, auth failures); no test needs the real server.
- The MT model ADR is accepted.

### Deferred

The owner moved the benchmark baselines out of P1 on 2026-09-27, since SMALL-100 and Gemma are settled for now. A full benchmark run for both modes and committed baselines (P1 plan step 11) must be done **before the first change to the LLM prompt, the LLM model, or the MT model**: that is when a regression check first matters. The eval app that produces them is complete.

---

## P2 - Document Translation and CLI

Board: [Feature #9010](https://chintand.visualstudio.com/AI%20Projects/_workitems/edit/9010) | Status: Not started

### Goal

Translate TXT, PPTX, DOCX, and XLSX files end to end from the command line, preserving formatting and structure as specified in the README format table.

### Dependencies

- P1

### Deliverables

- Core component doc extended with `document.py` (the format-neutral representation) and the format capability interfaces.
- `document.py`, `formats/base.py`, the format registry, and `formats/_ooxml/`.
- `DocumentAdapter` implementations for TXT, PPTX, DOCX, and XLSX.
- `pipeline.py`: extract, translate in batches, write back. Every unique segment of a document is translated once, however the pipeline batches work, so repeated strings translate identically ([ADR-007](decisions/ADR-007-translation-reuse-and-document-storage.md) layer 1).
- Public API additions for the server: a deterministic output fingerprint of the options and engine that determine a translation (ADR-007 layer 2), and an optional pipeline progress callback that can abort the run by raising ([ADR-008](decisions/ADR-008-job-execution-model.md) rule 8).
- Pass-through of non-translatable text (numbers, code, URLs, email addresses); source language auto-detection.
- `apps/cli`: input, output, source and target language, mode; configuration from environment and files; progress output; meaningful exit codes.
- Sample documents for each format in `tests/fixtures/`.

### Completion Criteria

- Every requirement in the README format table for TXT, PPTX, DOCX, and XLSX is covered by a passing test against fixtures.
- Outputs reopen cleanly with their format library; the input file is never modified.
- Numbers, URLs, and Excel formulas, numbers, and dates are unchanged in output (tested).
- A partial failure is reported and never silently drops content (tested).
- A repeated segment reaches the engine once per document and receives identical translations everywhere, including across pipeline batches (tested).
- The output fingerprint changes when any option or engine setting that affects output changes, and is stable otherwise (tested).
- The CLI translates every fixture in both modes.

---

## P3 - Fit Check

Board: [Feature #9011](https://chintand.visualstudio.com/AI%20Projects/_workitems/edit/9011) | Status: Not started

### Goal

Translated text never overflows beyond what the original did: layer 1 of the README visual quality requirement, for PPTX, DOCX, and XLSX.

### Dependencies

- P2

### Deliverables

- ADR for text measurement and font provisioning (layout engine, where fonts come from, behavior when a font is missing).
- `fit/`: text measurement, font lookup, allowed-space and shrink algorithm, with a configurable floor and decided defaults.
- `LayoutSupport` implementations for PPTX, DOCX, and XLSX, reporting containers per the README fit scope table.
- Fit report in the translation result; the CLI prints a summary and writes it as JSON.

### Completion Criteria

- Fixture tests show: text that grows is shrunk until it fits; original overflow is left as is; text that cannot fit at the floor is reported as unresolved and not shrunk further.
- Per-format fit scope matches the README table (e.g. DOCX body text is never resized).

---

## P4 - PDF Support

Board: [Feature #9012](https://chintand.visualstudio.com/AI%20Projects/_workitems/edit/9012) | Status: Not started

### Goal

Translate PDF files with layout preserved as closely as practical, including the fit check.

### Dependencies

- P3

### Deliverables

- ADR for the PDF strategy (translating in place versus converting through an editable format).
- `formats/pdf/`: `DocumentAdapter` and `LayoutSupport`.
- PDF fixtures, including Chinese source documents.

### Completion Criteria

- PDF fixtures translate in both modes, and outputs open cleanly with text in the target language at the original positions.
- The fit check runs on PDF text blocks and its report is correct on fixtures.
- The CLI supports all five formats: the README delivery phase 1 (CLI) is complete.

---

## P5 - Server and Job Service

Board: [Feature #9013](https://chintand.visualstudio.com/AI%20Projects/_workitems/edit/9013) | Status: Not started

### Goal

Run translations as persistent asynchronous jobs behind a REST API, hosted on the laptop and reachable by coworkers.

### Dependencies

- P2

### Deliverables

- ADR for authentication of REST and MCP (documents have owners; also weighs the cross-user cache signal recorded in ADR-007).
- Server component doc (`docs/architecture/components/server.md`).
- `apps/server`: FastAPI app, settings, `cli.py` (`serve`, `worker`), `db/` (SQLAlchemy models, repositories), initial Alembic migration, `jobs/`, `auth/`, `api/` with OpenAPI schema.
- Job execution per [ADR-008](decisions/ADR-008-job-execution-model.md): the jobs table as the queue, worker processes with leases, retries, recovery, progress, and cancellation; `serve --workers N` on the laptop.
- Storage and reuse per [ADR-007](decisions/ADR-007-translation-reuse-and-document-storage.md): content-addressed blob storage behind a storage interface (local disk implementation), `translation_results`, `documents`, and `document_versions`, the whole-document cache with `force_retranslate`, and cache hit/miss logging.
- Retention per ADR-007 with decided default durations: cache entries and user documents expire independently, and blobs are deleted only when unreferenced.
- `docs/Deployment.md` for laptop hosting: running the server, binding to the network, firewall, configuration and secrets, backup.

### Completion Criteria

- A job submitted over REST survives a server restart and completes.
- Killing a worker process mid-job leads to another worker completing the job; a document that crashes workers fails after the maximum number of attempts with a clear reason (tested).
- The API stays responsive while workers translate.
- Submitting a byte-identical document with the same options completes from the cache without translating; changing an option, the engine, or passing `force_retranslate` translates again (tested).
- Cache expiry never deletes a file that a user document version still references (tested).
- A coworker's machine can submit a job and download the result over the laptop's IP.
- An end-to-end test shows the CLI and REST API produce identical output for the same document and options.
- Migrations build the database from empty; the server never creates tables outside migrations.

---

## P6 - Web GUI

Board: [Feature #9014](https://chintand.visualstudio.com/AI%20Projects/_workitems/edit/9014) | Status: Not started

### Goal

Non-technical coworkers translate documents in a browser: README delivery phase 2.

### Dependencies

- P5

### Deliverables

- `apps/web`: React + TypeScript SPA with an API client generated from the server's OpenAPI schema.
- Upload, language and mode selection, job progress, download, and fit report view.
- Built SPA served by the server; web build, lint, and tests in CI.

### Completion Criteria

- A coworker completes upload, translate, and download in a browser against the laptop, for every format.
- The SPA uses only the REST API.

---

## P7 - MCP Server and Visual Review

Board: [Feature #9015](https://chintand.visualstudio.com/AI%20Projects/_workitems/edit/9015) | Status: Not started

### Goal

Agents on LLM platforms translate documents, then inspect rendered pages and fix visual problems: README delivery phase 3, validated against Open WebUI.

### Dependencies

- P4
- P5

### Deliverables

- Verified network path from the Open WebUI host to the laptop (checked first; blocks the rest).
- ADR for rendering (expected: headless LibreOffice to PDF, then PyMuPDF to images).
- MCP tool contract in the server component doc, including how files move between the platform and the server.
- `render/`, plus `RenderSupport` and `EditSupport` for PPTX, DOCX, XLSX, and PDF.
- `mcp/`: Streamable HTTP tools for submitting jobs, checking status, fetching results and fit reports, fetching page images, and applying edits.
- Edit and render jobs on the ADR-008 queue. Each edit adds a document version and never changes cached output (ADR-007); an edit based on a stale version fails with a conflict.

### Completion Criteria

- In Open WebUI, a user uploads a document and the agent completes the full loop: translate, review page images, apply a fix, and confirm it on a re-rendered page.
- The tools work unchanged from a second, non-Open WebUI MCP client (e.g. MCP Inspector), showing they are platform-neutral.

---

## P8 - Enterprise Platform Integration

Board: [Feature #9016](https://chintand.visualstudio.com/AI%20Projects/_workitems/edit/9016) | Status: Not started

### Goal

Make the MCP server available to enterprise platforms such as Microsoft Copilot.

### Dependencies

- P7
- Blocked until: the server runs on a host with a stable HTTPS endpoint reachable by the platform; a decision on whether documents passing through the company's Microsoft 365 tenant satisfies the confidentiality requirement; platform authentication (e.g. OAuth) is designed.

### Deliverables

To be planned when the blockers are resolved.

### Completion Criteria

To be planned when the blockers are resolved.
