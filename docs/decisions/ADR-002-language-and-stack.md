# ADR-002: Language and Stack

## Status

Accepted (2026-09-26)

## Context

The system has four parts: a translation core, a CLI, a web backend serving both the REST API and the MCP endpoint ([ADR-001](ADR-001-mcp-server-deployment.md)), and a web GUI. The core must read and rewrite PPTX, DOCX, XLSX, PDF, and TXT files with formatting intact, measure rendered text for the fit check, render pages to images, call an OpenAI-compatible LLM server, and run a local machine translation model. The backend must host a Streamable HTTP MCP endpoint alongside regular HTTP routes.

## Options Considered

### Python for core, CLI, and backend

Pros:
- Mature libraries for every format: `python-pptx`, `python-docx`, `openpyxl`, PyMuPDF.
- First-class local MT model tooling (Hugging Face `transformers`, CTranslate2).
- Official MCP Python SDK, whose Streamable HTTP server mounts into an ASGI app, so FastAPI can serve the REST API and MCP from one process as ADR-001 requires.
- One language for everything except the browser UI.

Cons:
- Weaker static typing than TypeScript; needs a type checker enforced in CI to compensate.

### TypeScript/Node for core, CLI, and backend

Pros:
- Official MCP TypeScript SDK; one language shared with the web GUI.

Cons:
- Office and PDF manipulation libraries are far less capable, and formatting fidelity is the product's core requirement.
- Local MT inference is poorly supported; MT mode would likely need a Python sidecar anyway, giving two languages in the backend.

### Web GUI: separate TypeScript SPA vs. server-rendered templates

A separate SPA talks to the backend only through the REST API, so the UI physically cannot reach into the core or the job service. Server-rendered templates avoid a second toolchain, but put UI code inside the backend package, where it can call anything the backend can.

## Decision

- **Core, CLI, and backend:** Python, with type hints enforced by a type checker in CI.
- **Backend framework:** FastAPI, with the MCP endpoint provided by the official MCP Python SDK and mounted into the same app.
- **Web GUI:** a separate React + TypeScript single-page app that uses only the REST API. It is built to static files that the backend serves.

The exact Python version, package manager, and frontend build tooling are pinned in the first implementation plan, based on wheel availability for the MT model runtime.

## Consequences

- The repository has two toolchains: Python for everything except `web`, and Node for `web`.
- The REST API is the only contract between the web GUI and the backend. Anything the GUI needs must be exposed there.
- Format support depends on the Python libraries' coverage. Gaps (for example, elements `python-pptx` does not model) must be handled with direct OOXML manipulation inside the relevant format module, not by switching languages.
