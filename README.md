# Document Translator

Translate office documents between languages while preserving their layout and formatting, running entirely on infrastructure inside the company network.

## Problem

Teams regularly receive and produce documents (slide decks, reports, spreadsheets, PDFs) in a language their readers don't speak - most often Chinese and English. Translating these today means one of:

- Copying text into a public translation service, which leaks confidential content outside the company.
- Translating by hand, which is slow and expensive.
- Using tools that translate text but destroy the document: fonts, colors, tables, and slide layouts are lost, and translated text overflows its boxes because target-language text is often longer than the source.

The output of a useful translator is not "the translated text"; it is a document that looks like the original and can be sent as-is.

## Solution

A document translation system with one shared translation core and three ways to use it, delivered in this order:

1. **CLI** - a local command-line tool that translates a file and writes a translated copy in the same format.
2. **Web GUI** - a browser interface where users upload a document, choose languages, and download the result.
3. **MCP server** - exposes translation as tools for agents on LLM platforms. A user uploads a file in chat; the agent submits a translation job, monitors it until completion, then uses its vision capabilities to inspect rendered pages of the output for visual problems (text overflow, overlapping elements, clipped or unreadable text) and edits the document to fix them. Open WebUI is the first platform, used as a development and test client; enterprise platforms such as Microsoft Copilot are the long-term targets.

All three surfaces use the same core, so a file translates identically no matter how it was submitted.

## Users

- **Staff translating their own documents** - via the web GUI or an agent chat. Not necessarily technical.
- **Engineers and power users** - via the CLI, for single files, batches, and scripting.
- **AI agents on LLM platforms** (Open WebUI now, Copilot and others later) - via the MCP server, acting on a user's behalf.

## Goals

- Translate PPTX, DOCX, XLSX, PDF, and TXT files, producing output in the same format as the input.
- Preserve formatting and structure: fonts, styles, colors, run-level formatting (bold, italic, etc.), tables, lists, slide layouts, and sheet structure.
- Produce documents that look right, not just read right: detect and correct text overflow and other visual defects caused by translation.
- Keep all document content inside the company network.
- Translate in both directions between Chinese, English, Japanese, and Spanish, with Chinese -> English as the primary focus and highest quality bar, on technical and business content.
- Offer more than one translation mode, so users can trade quality against speed and availability.
- Build the translation core once and reuse it across the CLI, web GUI, and MCP server.
- Handle realistic document sizes (tens of slides, hundreds of pages) in reasonable time without manual intervention.

## Non-Goals

- Translating content embedded in images (screenshots, diagrams saved as pictures) - no OCR in scope.
- Human translation workflows: translation memory management, reviewer assignment, glossary approval processes.
- Languages beyond Chinese, English, Japanese, and Spanish, even where a model supports them.
- Real-time or streaming translation of live content (chat, meetings, subtitles).
- Public or external-facing availability; this is an internal tool.
- Editing or authoring documents beyond what is needed to translate them and fix translation-induced layout problems.
- Keeping font sizes consistent across related elements (e.g. all slide titles) when the fit check shrinks text; each container is fitted independently.

## Requirements

### Functional

**Formats**

| Format | Requirement |
|--------|-------------|
| PPTX | Translate text in text boxes, placeholders, tables, grouped shapes, and speaker notes. Preserve slide layout and run-level formatting. |
| DOCX | Translate body text, tables, headers, footers, and footnotes. Preserve styles and run-level formatting. |
| XLSX | Translate cell text and sheet names. Never alter formulas, numbers, or dates. |
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

Translation must never make the layout worse than the original. This is enforced in two layers.

*Layer 1 - fit check (translation core, all surfaces).* Runs automatically after translation, for every format with fixed-size text containers:

1. For each text container, measure the rendered extent of the original text (using real font metrics and line wrapping at the container's width, not character counts).
2. The translated text's allowed space is the larger of the container's bounds and the original text's rendered extent. Original text that already overflowed its container is treated as intentional and is not "fixed".
3. If the translated text's rendered extent exceeds the allowed space, reduce its font size step by step until it fits, down to a floor (a minimum percentage of the original size and a minimum point size, both configurable).
4. If it still does not fit at the floor, stop shrinking and record it as an unresolved issue.

Every job produces a fit report listing each adjusted container (location, original and final size) and each unresolved issue.

Overlap is judged only relative to the original. Overlap between elements that already existed in the source document (text over images, labels inside shapes) is intentional design and is never flagged or changed.

Per format:

| Format | Fit check scope |
|--------|-----------------|
| PPTX | All text containers: text boxes, placeholders, shapes, table cells. |
| PDF | All text blocks. |
| XLSX | Cell text clipped by column width or row height. |
| DOCX | Fixed-size elements only (text boxes, fixed-width table cells); body text reflows naturally. |
| TXT | Not applicable. |

*Layer 2 - visual review (MCP flow only).* The MCP server renders output pages to images and exposes them through MCP tools. The platform's agent inspects them, prioritizing pages listed in the fit report, and checks for problems the geometric check cannot judge: awkward line breaks, text that fits but reads as cramped, and unresolved issues from layer 1. It applies fixes through MCP tools. Rendering happens on the server so the review works with any agent that has vision, regardless of platform.

**Jobs (web GUI and MCP server)**

- Translation runs as an asynchronous job: submit, check status and progress, retrieve result.
- Failed jobs report a clear reason; a partial failure (e.g. one unparseable element) does not silently drop content.

### Non-Functional

- **Confidentiality** - document content and translations never leave the company network. Self-hosted models and services on the internal network are allowed; external cloud translation or LLM APIs are not.
- **Fidelity** - an output file must always open cleanly in its native application. The input file is never modified.
- **Translation quality** - measured by an engine benchmark: parallel sentences in all 12 directions, scored with COMET and chrF against reference translations ([ADR-005](docs/decisions/ADR-005-translation-quality-evaluation.md)). Chinese -> English is the deciding direction; no change may significantly lower its score. Absolute thresholds are set from the first baseline run.
- **Performance** - batch translation work so large documents are not bottlenecked on per-string model calls; exact targets to be set once the model backend is chosen.
- **Observability** - jobs log timing per phase and counts of translated elements, so slow or lossy translations can be diagnosed.
- **Extensibility** - adding a file format or a translation backend should not require changes to the other formats or surfaces.

## Constraints

- Translation models run locally or on self-hosted servers inside the company network.
- The MCP server is platform-neutral: standard MCP over the Streamable HTTP transport, with no Open WebUI-specific tools, file handling, or behavior. Both Open WebUI's native MCP integration and Microsoft Copilot Studio support only Streamable HTTP (not stdio). The MCP endpoint is served by the web backend process ([ADR-001](docs/decisions/ADR-001-mcp-server-deployment.md)).
- Everything lives in one repository, with a shared core consumed by the CLI, web GUI, and MCP server.
- The LLM server API key is supplied through configuration (environment or a local secrets file) and is never committed to the repository.
- The LLM server's TLS certificate is issued by the company's internal CA. Certificate verification stays on; the host must trust that CA.

## External Dependencies

- **Internal LLM server** - company-hosted, OpenAI-compatible chat completions API with Bearer API key auth, currently serving Gemma (`gemma-4-31b-it`). Required for LLM mode only. The endpoint URL, model name, and key are configuration, not code.
- **Open WebUI** - the company's Open WebUI instance, the initial MCP client for development and testing. Required for the MCP flow only, and replaceable by any MCP-capable platform.

## Hosting

Initially, the web GUI and MCP server run on a single developer laptop on the company network. Coworkers use the web GUI by connecting to the laptop's IP address, and Open WebUI connects to the MCP server at the same address. This means:

- Availability depends on the laptop being on, awake, and on the network. There is no uptime guarantee at this stage.
- Job throughput is bounded by the laptop's hardware, especially in MT mode, where the model runs on the laptop.
- The deployment should not assume the laptop is permanent: moving to a shared server later should be a configuration and deployment change, not a redesign.
- Cloud platforms such as Copilot Studio cannot reach a laptop on the internal network. Integrating with them requires a stable HTTPS endpoint they can reach, so it depends on moving off the laptop first.

## Delivery Phases

1. **CLI** - translation core plus CLI covering all five formats.
2. **Web GUI and job service** - asynchronous jobs, upload/download through the browser.
3. **MCP server** - platform-neutral agent integration with job monitoring and vision-based visual QA and correction, validated against Open WebUI.
4. **Enterprise platform integration** - Copilot and similar platforms, once the service runs on a reachable server.

The detailed roadmap lives in the [Implementation Plan](docs/IMPLEMENTATION_PLAN.md).

## Open Questions

- Where do the domain benchmark's technical sentences and their reference translations come from (ADR-005)? Until sourced, quality is measured on the general-domain FLORES+ set only.
- PDF strategy: translate the PDF in place, or convert to an editable format, translate, and re-render?
- Text measurement needs the documents' fonts (or their metrics) on the machine running the fit check. How are fonts provisioned, and what happens when a document uses a font that isn't available? To be decided by ADR, along with the text layout engine.
- Default shrink floor (minimum percentage of original size and minimum point size).
- What authentication do the web GUI and MCP server need when exposed on the laptop's IP, and later to platforms like Copilot (which typically expect OAuth or API key auth)?
- Copilot runs in Microsoft's cloud, so documents submitted through it pass through the company's Microsoft 365 tenant. Does that count as "inside the company network" for the confidentiality requirement? Needs a decision before Copilot integration.
- Maximum supported file size and expected job volume?

## Current Status

Text translation works in both modes: LLM mode through the internal LLM server (Gemma) and MT mode through SMALL-100, which runs locally ([ADR-006](docs/decisions/ADR-006-mt-model-selection.md)). The translation quality benchmark (`apps/eval`) is in place. Document formats and the CLI are next (P2).

## Documentation

- [Architecture](docs/Architecture.md)
- [Implementation Plan](docs/IMPLEMENTATION_PLAN.md)
- [Repository Structure](docs/Structure.md)
- [Architecture Components](docs/architecture/components/)
- [Implementation Plans](docs/plans/)
- [Architecture Decisions](docs/decisions/)
- [Deployment](docs/Deployment.md)
- [Agent Instructions](AGENTS.md)
