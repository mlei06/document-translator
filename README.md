# Document Translator

Translate office documents between languages while preserving their layout and formatting, running on the user's laptop or approved company infrastructure.

## Problem

Teams regularly receive and produce documents (slide decks, reports, spreadsheets, PDFs) in a language their readers don't speak - most often Chinese and English. Translating these today means one of:

- Copying text into a public translation service, which leaks confidential content outside the company.
- Translating by hand, which is slow and expensive.
- Using tools that translate text but destroy the document: fonts, colors, tables, and slide layouts are lost, and translated text overflows its boxes because target-language text is often longer than the source.

The output is a translated document with structure and formatting preserved, plus explicit warnings where layout could not be fitted reliably.

## Solution

One shared translation capability, delivered in three forms:

1. **Web service** - users sign in, submit documents, track jobs and download owned results.
2. **Installed desktop app** - users select a supported model to download during setup, then open the app and drag in files or folders. Local translation works offline once its runtime/model is installed. The app manages its local service and workers; no terminal or web sign-in is required for local mode.
3. **Backend for internal applications** - a versioned asynchronous REST API for document submission, progress and results, with the same job/cache/storage behavior. Python applications may also use the public core when they own orchestration.

The CLI remains available for local and service use; MCP remains a later agent-facing adapter. All surfaces use the same core and lightweight fit policy. Desktop users may explicitly select a hosted company service instead of local processing; histories/caches are not automatically synchronized.

The current implementation handoff remains P2-P6. The [desktop and internal-app plan](docs/plans/Desktop-and-internal-app-delivery.md) adds installer/model setup and drag/drop delivery. Explorer right-click translation is only a later consideration. Lenovo laptop integration/preload is a long-term ambition after a proven installable app, not a current shipping commitment.

## Users

- **Staff translating their own documents** - via the signed-in web service or installed desktop app. Not necessarily technical.
- **Internal application teams** - integrate translation through the shared REST backend or, deliberately, the public Python core.
- **Engineers and power users** - via the CLI, for single files, batches, and scripting.
- **AI agents on LLM platforms** (Open WebUI now, Copilot and others later) - via the MCP server, acting on a user's behalf.

## Goals

- Translate PPTX, DOCX, XLSX, PDF, and TXT files, producing output in the same format as the input.
- Preserve formatting and structure: fonts, styles, colors, run-level formatting (bold, italic, etc.), tables, lists, slide layouts, and sheet structure.
- Prioritize translation accuracy and preserved formatting, with lightweight best-effort overflow mitigation and explicit unresolved warnings.
- Keep document content on the user's device or approved company infrastructure; never silently upload local-mode documents.
- Translate in both directions between Chinese, English, Japanese, and Spanish, with Chinese -> English as the primary focus and highest quality bar, on technical and business content.
- Offer more than one translation mode, so users can trade quality against speed and availability.
- Build the translation core once and reuse it across the CLI, web GUI, and MCP server.
- Handle realistic document sizes (tens of slides, hundreds of pages) in reasonable time without manual intervention.

## Non-Goals

- Translating content embedded in images (screenshots, diagrams saved as pictures) - no OCR in scope.
- Human translation workflows: translation memory management, reviewer assignment, glossary approval processes.
- Languages beyond Chinese, English, Japanese, and Spanish, even where a model supports them.
- Real-time or streaming translation of live content (chat, meetings, subtitles).
- Public cloud translation endpoints or an internet-facing public service. Broader Lenovo/OEM distribution is a separately gated long-term ambition.
- Editing or authoring documents beyond what is needed to translate them and fix translation-induced layout problems.
- Keeping font sizes consistent across related elements (e.g. all slide titles) when the fit check shrinks text; each container is fitted independently.

## Requirements

### Functional

**Formats**

| Format | Requirement |
|--------|-------------|
| PPTX | Translate text in text boxes, placeholders, tables, grouped shapes, and speaker notes. Preserve slide layout and run-level formatting. |
| DOCX | Translate body text, tables, headers, footers, and footnotes. Preserve styles and run-level formatting. |
| XLSX | Translate literal cell text. Preserve sheet names, formulas, numbers, dates and formatting. |
| PDF | Produce a translated PDF that preserves page layout as closely as practical. |
| TXT | Translate plain text, preserving line and paragraph structure. |

**Languages**

All 12 directions between Chinese (Simplified), English, Japanese, and Spanish are supported. Chinese -> English is the primary direction: it is tested most thoroughly and quality decisions are made against it first.

**Translation modes**

The user selects a mode per job. Both modes produce the same output format and go through the same fit check; only the translation engine differs.

| Mode | Engine | Characteristics |
|------|--------|-----------------|
| LLM | Prompting the internal LLM server (OpenAI-compatible chat completions API, API key auth) | Higher quality and context awareness; depends on the internal server being reachable. |
| MT | A machine translation model hosted locally on the machine running the translator | Works without the LLM server; faster and more predictable, lower quality on nuanced text. |

**Translation**

- Source and target languages are selectable per job; source language can be auto-detected.
- Text that should not be translated (numbers, code, URLs, email addresses, product names) passes through unchanged.
- Repeated strings within a document translate consistently.

**Visual quality**

Translation quality and accuracy take priority. Automatic post-processing is a lightweight, best-effort overflow safeguard, not a native-layout or visual-perfection guarantee. [ADR-012](docs/decisions/ADR-012-lightweight-fit-policy.md) records the owner-approved scope.

*Layer 1 - automatic fit (all surfaces).* Preserve wording and formatting, allow natural reflow and inspect changed constrained containers. Use the same supported font/wrapping estimator for source and translation. Allow the larger of container bounds and source extent, then apply bounded proportional font shrinking only when overflow is reliably measurable. Defaults are 70% relative and 8pt absolute floors; original smaller text is not enlarged or further shrunk. Unknown measurements retain original sizes and produce unresolved warnings. Never rewrite, shorten or truncate translations to fit.

Every result carries a fit report. A measured pass is not rendered visual approval. Unresolved fit is compatible with complete translation; lost text or corrupt output is not. No runtime rendering loop, vision review or exhaustive Office emulation is required.

| Format | Minimum fit scope |
|---|---|
| PPTX | Changed constrained boxes, placeholders, shapes and table cells; preserve geometry. |
| PDF | Replacement text placement under the selected PDF strategy; explicit unsupported cases. |
| XLSX | Changed constrained cell text, respecting wrapping/merges; preserve row/column sizes. |
| DOCX | Constrained boxes/cells only; body and unconstrained dimensions reflow naturally. |
| TXT | Not applicable. |

Existing overflow/overlaps are not repaired. Objects are not moved and pagination is not forced. A small representative acceptance corpus checks integrity, content preservation and obvious clipping; native checks are acceptance activities, not production dependencies.

*Layer 2 - later optional visual review (P7).* An MCP agent may inspect rendered pages and request supported corrections as new versions. This is outside P2-P6 and does not block its release.

**Users and jobs (service CLI, REST, web GUI and later MCP)**

- Translation runs as an asynchronous job: submit, check status and progress, retrieve result.
- Every accepted file is an independent job owned by an authenticated user. Batches, document history, output files and reports are tied to that stable user identity; users can only access their own resources.
- The service CLI and REST API share one job/cache/storage service. Long mixed-format batches use bounded per-file uploads and recoverable submission IDs, with no fixed total batch-count ceiling; resource limits and admission backpressure are explicit.
- The local synchronous CLI remains available without persistent job history or document-cache reuse.
- P6 audits the existing mock UI, preserves useful features and integrates real authenticated backend data; simulated production results are not acceptable.
- Failed jobs report a clear reason; a partial failure (e.g. one unparseable element) does not silently drop content.

### Non-Functional

- **Confidentiality** - document content and translations stay on the user's device or approved company infrastructure. Self-hosted models and services on the internal network are allowed; external cloud translation or LLM APIs are not.
- **Fidelity** - an output file must always open cleanly in its native application. The input file is never modified.
- **Translation quality** - measured by an engine benchmark: parallel sentences in all 12 directions, scored with COMET and chrF against reference translations ([ADR-005](docs/decisions/ADR-005-translation-quality-evaluation.md)). Chinese -> English is the deciding direction; no change may significantly lower its score. Absolute thresholds are set from the first baseline run.
- **Performance** - batch translation work so large documents are not bottlenecked on per-string model calls; exact targets to be set once the model backend is chosen.
- **Observability** - jobs log timing per phase and counts of translated elements, so slow or lossy translations can be diagnosed.
- **Extensibility** - adding a file format or a translation backend should not require changes to the other formats or surfaces.

## Constraints

- Translation models run on the user's device or approved company servers. Installer model downloads do not authorize remote document inference.
- The MCP server is platform-neutral: standard MCP over the Streamable HTTP transport, with no Open WebUI-specific tools, file handling, or behavior. Both Open WebUI's native MCP integration and Microsoft Copilot Studio support only Streamable HTTP (not stdio). The MCP endpoint is served by the web backend process ([ADR-001](docs/decisions/ADR-001-mcp-server-deployment.md)).
- Everything lives in one repository, with a shared core consumed by the CLI, web GUI, and MCP server.
- The LLM server API key is supplied through configuration (environment or a local secrets file) and is never committed to the repository.
- The LLM server's TLS certificate is issued by the company's internal CA. Certificate verification stays on; the host must trust that CA.

## External Dependencies

- **Internal LLM server** - company-hosted, OpenAI-compatible chat completions API with Bearer API key auth, currently serving Gemma (`gemma-4-31b-it`). Required for LLM mode only. The endpoint URL, model name, and key are configuration, not code.
- **Open WebUI** - the company's Open WebUI instance, the initial MCP client for development and testing. Required for the MCP flow only, and replaceable by any MCP-capable platform.

## Deployment and Delivery

[ADR-013](docs/decisions/ADR-013-deployment-profiles.md) defines three profiles:

| Profile | Runtime and identity |
|---|---|
| Hosted web/API | Company-hosted job service and workers; authenticated users and authorized internal-app credentials. A developer laptop can host the initial pilot. |
| Desktop local | Installer-managed per-user runtime, model and storage; OS-user ownership and authenticated local access. No company account needed for local processing. |
| Internal-app backend | The same versioned hosted REST API; optional public-core embedding for Python callers who own lifecycle/storage. |

The installer offers a curated compatible model catalog, explains resource/download requirements and verifies selected artifacts. SMALL-100 is the initial supported local engine; internal Gemma is currently a remote option, not a promised downloadable desktop model. Additional model choices require compatibility, licensing and quality validation.

P2-P6 delivers the shared service and existing web UI integration. Desktop tracks D0-D2 and internal-client track I1 build on that backend without requiring P7 MCP or P8 enterprise cloud integration. The main desktop flow is open app -> add files/folders -> choose translation options/destination -> progress -> translated files. Tray notifications are secondary; Explorer integration is optional later work.

Lenovo fleet deployment and eventual OEM preload require separate distribution, hardware and servicing validation. No signed installer, native integration or OEM availability is claimed yet. See [Deployment](docs/Deployment.md) for intended profiles versus runnable operations.

## Open Questions

- Where do the domain benchmark's technical sentences and their reference translations come from (ADR-005)? Until sourced, quality is measured on the general-domain FLORES+ set only.
- PDF strategy: resolved by [ADR-014](docs/decisions/ADR-014-pdf-strategy.md) (translate in place with PyMuPDF). PyMuPDF is AGPL-licensed: before a desktop, fleet or OEM build ships it, decide between AGPL compliance and an Artifex commercial license.
- Deployment must supply the explicit font manifest used by best-effort fit; unavailable fonts produce unresolved diagnostics under ADR-012. Font installation/licensing is an operational concern, not a reason for runtime downloads.
- Fit defaults are settled by ADR-012 (70% and 8pt) and implemented for PPTX, DOCX, XLSX and PDF with bounded acceptance evidence ([fit report](docs/experiments/fit-measurement/README.md), [PDF report](docs/experiments/pdf-strategy/README.md)); reviewed-commit CI remains pending.
- What authentication do the web GUI and MCP server need when exposed on the laptop's IP, and later to platforms like Copilot (which typically expect OAuth or API key auth)?
- Copilot runs in Microsoft's cloud, so documents submitted through it pass through the company's Microsoft 365 tenant. Does that count as "inside the company network" for the confidentiality requirement? Needs a decision before Copilot integration.
- Maximum supported file size and expected job volume?

## Current Status

Text translation works in both modes: LLM mode through the internal LLM server (Gemma) and MT mode through SMALL-100, which runs locally ([ADR-006](docs/decisions/ADR-006-mt-model-selection.md)). The translation quality benchmark (`apps/eval`) is in place. Document formats and the CLI are next (P2).

P1 still has delivery verification/closure work recorded in its plan. Full quality baselines were explicitly deferred and must be captured before any prompt or model change. P2 is in design: its [draft plan](docs/plans/P2-document-translation-and-cli.md) and [XLSX experiment](docs/experiments/xlsx-roundtrip/README.md) distinguish proposed behavior from approved requirements. No document translation command, fit check, running web service, or MCP endpoint exists yet.

## Delivery Handoff

The [P2-P6 handoff](docs/plans/P2-P6-delivery-handoff.md) is the execution entry point for completing the five-format backend and integrating the existing mock web GUI. It includes the user/ownership flow, technical design gates, phase tasks, CLI/API contracts and backend/browser release matrices. It describes required work, not completed functionality.

## Documentation

- [Architecture](docs/Architecture.md)
- [Implementation Plan](docs/IMPLEMENTATION_PLAN.md)
- [Repository Structure](docs/Structure.md)
- [Architecture Diagrams and Main Flow](docs/Architecture.md#main-translation-flow)
- [Implementation Plans](docs/plans/)
- [Architecture Decisions](docs/decisions/)
- [Deployment](docs/Deployment.md)
- [Agent Instructions](AGENTS.md)
