# Document Translator

Current delivery contract: [Unified translator design](docs/plans/unified-translator-design.md) consolidates website, storage, direct results, desktop installation and visual design. Implementation and acceptance evidence are tracked in [unified execution](docs/plans/unified-execution.md); desktop signing and clean-machine release acceptance remain separate gates.

Translate office documents between languages while preserving their layout and formatting, running on the user's laptop or approved company infrastructure.

## Problem

Teams regularly receive and produce documents (slide decks, reports, spreadsheets, PDFs) in a language their readers don't speak - most often Chinese and English. Translating these today means one of:

- Copying text into a public translation service, which leaks confidential content outside the company.
- Translating by hand, which is slow and expensive.
- Using tools that translate text but destroy the document: fonts, colors, tables, and slide layouts are lost, and translated text overflows its boxes because target-language text is often longer than the source.

The output is a translated document with structure and formatting preserved. Standard layout fitting runs internally; the target website keeps a simple translation-to-download flow without a separate layout-check stage.

## Solution

One shared translation capability, delivered in three forms:

1. **Web service** - users sign in, submit documents, track jobs and download owned results.
2. **Installed desktop app** - setup offers Online only or Online and offline, with one approved offline bundle. Explorer right-click and main-window drag/drop share one queue. Users press Translate with no model/mode controls. The installer provisions Davy access; the app automatically tries the common Davy ladder, then installed device HY-MT, independently of the website service. See [ADR-030](docs/decisions/ADR-030-desktop-online-offline-delivery.md).
3. **Backend for internal applications** - a versioned asynchronous REST API for document submission, progress and results, with shared processing/jobs and explicit saved or temporary retention. Python applications may also use the public core when they own orchestration.

The CLI remains available for local and service use; MCP remains a later agent-facing adapter. All surfaces use the same core and lightweight fit policy. Desktop automatically uses direct Davy or installed local fallback; exports are user-controlled files and are not synchronized to a hosted library.

The unified specification supersedes conflicting earlier implementation handoffs. The desktop implementation includes a native shell, private local runtime, offline asset management and Explorer integration; release readiness requires the evidence listed in the execution record. Lenovo laptop integration/preload remains a later ambition.

## Storage and Retranslation

Website requests use one shared current translation per source hash and target language, with private user History containing filenames and language pairs. Download serves the current shared translation. New verified uploads attempt only higher-ranked models before reusing a compatible result. Originals are retained only for staging and active work/recovery; website outputs have no fixed availability or version guarantee. See [ADR-028](docs/decisions/ADR-028-website-cache-and-retention.md) and the unified specification for budgets, idle eviction and History expiry.

Under [ADR-014](docs/decisions/ADR-014-storage-ownership-and-retranslation.md), local desktop and Explorer processing is files or folders in, files or folders out: always translate each new explicit run, export to the chosen destination with numbered filename collisions, and clean up temporary working copies. No hidden permanent local document library or translation cache is required.

Internal applications retain explicit saved/temporary submission and exact-result contracts with individual service-account authorization. They do not implicitly opt into the website cache. Website submissions explicitly use `website_auto`, `cached` retention and `current_shared` downloads.

## Translator Selection

Website and desktop automatic routing use the pinned common policy: Gemma, ordered approved Davy alternatives, then configured HY-MT. Website reuse stops traversal before equal/lower inference. Every rung starts the whole document afresh and records truthful producer identity; bad input, storage and fit failures do not consume inference rungs. See [ADR-027](docs/decisions/ADR-027-automatic-website-translation.md).

Availability is specific to the serving backend. Automatic requests use bounded discovery, retries and fallback; explicit internal API/CLI translator requests retain their selected-translator semantics. See [ADR-024](docs/decisions/ADR-024-translator-availability.md).

Administrators configure named translators and the website policy. Explicit internal API and CLI clients can select a translator; the website presents target languages only. Jobs pin identities and reuse includes model/settings compatibility. See [configuration](docs/Deployment.md#translator-configuration).

Desktop setup under ADR-030 offers one offline bundle without a model picker; settings manage offline support later. The desktop owns its authenticated llama.cpp process and verifies immutable assets before activation. Hardware and packaged release evidence are recorded separately from unit tests. See [local HY-MT](docs/decisions/ADR-025-local-hy-mt.md).

## Browser Accounts

Email/password sign-in and deployment-enabled account creation follow [ADR-020](docs/decisions/ADR-020-browser-accounts-and-decoding.md). API-key clients remain supported. Website accounts use the standard automatic profile and private History; personal model/decoding controls are absent.

## Users

- **Staff translating their own documents** - via the signed-in web service or installed desktop app. Not necessarily technical.
- **Internal application teams** - integrate translation through the shared REST backend or, deliberately, the public Python core.
- **Engineers and power users** - via the CLI, for single files, batches, and scripting.
- **AI agents on LLM platforms** (Open WebUI now, Copilot and others later) - via the MCP server, acting on a user's behalf.

## Goals

- Translate PPTX, DOCX, XLSX, PDF, and TXT files, producing output in the same format as the input.
- Preserve formatting and structure: fonts, styles, colors, run-level formatting (bold, italic, etc.), tables, lists, slide layouts, and sheet structure.
- Prioritize translation accuracy and preserved formatting, with internal lightweight best-effort overflow mitigation.
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

Translation quality and accuracy take priority. [ADR-026](docs/decisions/ADR-026-offline-fit-v2.md) defines the implemented structure-aware offline fitting policy. The [design spec](docs/plans/offline-fit-v2.md) records exact scope and acceptance requirements.

Standard fitting preserves structure, measures target text even when the source font baseline is unknown, writes provisioned target font substitutions and applies bounded repairs. PowerPoint can grow eligible boxes into free space, reduce paragraph spacing and shrink proportionally. Word body content reflows naturally. PDF preserves paragraph boundaries/right anchors and rejects a document when complete text cannot be legally placed without overlap or below-floor rescue. Floors remain 70% and 8 pt by default. No wording changes, OCR or model calls occur during fitting.

[ADR-029](docs/decisions/ADR-029-standard-fit-direct-download.md) removes thorough fit and all production previews, eliminating the LibreOffice requirement. Standard fit and saved-file verification remain; completed items and History offer direct Download. Bubbles are status groups with explicit actions. XLSX retains standard constrained-cell fitting; TXT fit is not applicable.

The target website uses **Translating**, **Saving**, and **Ready to download**, with no separate layout-check status or personal fit/skip control. Standard fit stays internal under Translating. Complete construction, content checks and safe PDF placement remain mandatory; Ready requires successful publication. Standard Office fit can remain unresolved without claiming rendered visual perfection. Historical thorough/skipped reports remain truthful metadata; they do not restore removed runtime options. Optional model-assisted visual editing remains outside this scope.

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

The installer offers one approved HY-MT1.5-1.8B Q8 offline bundle, explains resource/download requirements and verifies its immutable artifacts. Settings manage that capability without a model picker. Gemma and the other approved Davy models remain remote candidates. SMALL-100 remains available through the separate core/internal-app configuration, not as a desktop installer choice.

P2-P6 delivers the shared service and existing web UI integration. Desktop tracks D0-D2 and internal-client track I1 build on that backend without requiring P7 MCP or P8 enterprise cloud integration. The main desktop flow is open app -> add files/folders -> choose target/destination -> progress -> translated files. Tray notifications are secondary; configurable Explorer shortcuts are a unified desktop release requirement.

Lenovo fleet deployment and eventual OEM preload require separate distribution, hardware and servicing validation. No signed installer, native integration or OEM availability is claimed yet. See [Deployment](docs/Deployment.md) for intended profiles versus runnable operations.

## Open Questions

- Where do the domain benchmark's technical sentences and their reference translations come from (ADR-005)? Until sourced, quality is measured on the general-domain FLORES+ set only.
- PDF strategy: resolved by [ADR-018](docs/decisions/ADR-018-pdf-strategy.md) (translate in place with PyMuPDF). PyMuPDF is AGPL-licensed: before a desktop, fleet or OEM build ships it, decide between AGPL compliance and an Artifex commercial license.
- Deployment must supply the explicit font manifest used by best-effort fit; unavailable fonts produce unresolved diagnostics under ADR-012. Font installation/licensing is an operational concern, not a reason for runtime downloads.
- Fit defaults are settled by ADR-012 (70% and 8pt) and implemented for PPTX, DOCX, XLSX and PDF with bounded acceptance evidence ([fit report](docs/experiments/fit-measurement/README.md), [PDF report](docs/experiments/pdf-strategy/README.md)); reviewed-commit CI remains pending.
- Authentication: the REST API and service CLI use per-user API keys ([ADR-015](docs/decisions/ADR-015-authentication-and-ownership.md)); the web GUI exchanges a key for a browser session (P6). Still open: MCP authentication and platforms like Copilot, which typically expect OAuth.
- Copilot runs in Microsoft's cloud, so documents submitted through it pass through the company's Microsoft 365 tenant. Does that count as "inside the company network" for the confidentiality requirement? Needs a decision before Copilot integration.
- Maximum supported file size and expected job volume?

## Current Status

Text translation works through the internal LLM service and local MT runtimes. The repository includes TXT, PPTX, DOCX, XLSX and PDF translation, local/service CLI commands, the owned-job REST service, web integration and offline fit v2. The translation quality benchmark (`apps/eval`) is in place. See [release evidence](docs/plans/P2-P6-release-evidence.md) and [fit v2 evidence](docs/plans/offline-fit-v2.md#implementation-evidence-2026-09-29) for tested scope and limitations.

Historical phase closure, board synchronization and reviewed-commit CI are distinct from the implementation present in the workspace. Full translation-quality baselines remain deferred under the owner's recorded instruction. MCP delivery remains future work; implementing offline fit does not close those broader delivery gates.

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
