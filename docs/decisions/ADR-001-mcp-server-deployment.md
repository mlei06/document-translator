# ADR-001: MCP Server Deployment

## Status

Accepted (2026-09-26)

## Context

The document translator exposes translation to AI agents through an MCP server (see [README](../../README.md), delivery phase 3). The same system also has a web GUI backed by an asynchronous job service (phase 2). This ADR decides how the MCP server is deployed relative to that backend, and which MCP transport it uses.

Forces:

- **Platforms.** Open WebUI is the first MCP client, used for development and testing. Enterprise platforms such as Microsoft Copilot are the long-term targets. The server must not be tied to any one platform.
- **Transport support.** Open WebUI's native MCP integration supports only the Streamable HTTP transport. Using a stdio server with it requires the `mcpo` proxy running on the Open WebUI host. Microsoft Copilot Studio also supports only Streamable HTTP (it dropped SSE after August 2025) and requires a stable HTTPS endpoint.
- **Hosting.** Initially everything runs on a single developer laptop on the company network, and later on a shared server. Fewer processes to run and keep alive on the laptop is better.
- **Shared behavior.** Jobs submitted by an agent and by a web user must be processed identically, share one queue, and be visible to the same status and result logic.
- **Long-running jobs.** Translation takes seconds to minutes. Agents submit a job, poll its status, and fetch results and rendered pages, so the MCP layer must not hold job state in memory tied to a connection.

## Options Considered

### A. stdio server spawned by the MCP client, calling the web backend's HTTP API

The platform launches the MCP server as a local subprocess and talks to it over stdio. The server translates tool calls into HTTP requests against the web backend.

Pros:
- No network endpoint for MCP itself; the backend's HTTP API is the only exposed surface.
- The standard setup for desktop clients (e.g. VS Code, Claude Desktop).

Cons:
- Neither target platform supports it natively. Open WebUI would need `mcpo` running on its host, and Copilot Studio cannot use it at all.
- Our code has to be installed and updated on every client host (the Open WebUI server, which we may not control), instead of only on our server.
- Adds an HTTP hop and a second auth boundary between the MCP layer and the job service.

### B. Standalone Streamable HTTP MCP service, calling the web backend's HTTP API

The MCP server runs as its own process with its own HTTP endpoint and acts as a client of the web backend's API.

Pros:
- Works natively with Open WebUI and Copilot Studio.
- MCP can be scaled, restarted, or secured independently of the web backend.

Cons:
- Two processes to deploy, configure, monitor, and keep alive, for no current benefit on a single laptop.
- Extra network hop and a second authentication boundary between MCP and the job service.
- Every job-service capability the MCP tools need must first be exposed on the public web API, even if the web GUI doesn't need it.

### C. Streamable HTTP MCP endpoint in the web backend process, calling the job service in-process

The web backend serves both the web API and the MCP endpoint (at a stable path such as `/mcp`) from the same process. MCP tools call the same application-layer job service the web API calls.

Pros:
- Works natively with Open WebUI and Copilot Studio.
- One process to deploy and keep alive; one configuration; one job queue shared by web users and agents.
- No extra network hop or internal auth boundary; the MCP layer and the web API are two thin adapters over the same service.
- One origin and one auth mechanism to secure when exposed on the laptop's IP and later to cloud platforms.

Cons:
- MCP cannot be scaled or restarted independently of the web GUI.
- A fault or load spike in one surface affects the other.
- A heavy dependency in the MCP adapter would land in the web backend process too.

## Decision

Option C. The MCP server is a Streamable HTTP endpoint served by the web backend process, not a separate service and not a stdio server.

Rules that make this decision hold:

1. **Thin adapter.** The MCP layer contains only protocol handling: tool definitions, argument validation, and mapping to and from the job service. All translation, job, fit-check, and rendering logic lives in the shared core and job service, never in MCP tool handlers.
2. **No connection-bound state.** Job state lives in the job service's persistent store. The MCP layer holds nothing that is lost when a connection drops or the process restarts, beyond the MCP session itself.
3. **Platform-neutral.** Tools use standard MCP only. Nothing specific to Open WebUI (or any other client) goes into tool names, arguments, file handling, or behavior.
4. **Stable endpoint.** The MCP endpoint path is fixed and does not change between releases, since external platforms are configured with it.

## Consequences

- Phase 3 builds on the phase 2 backend: the MCP endpoint cannot ship before the web backend and job service exist.
- The web backend's framework must be able to host a Streamable HTTP MCP endpoint alongside its regular routes. This is a requirement for the backend framework decision.
- Web GUI and MCP authentication must be designed together, since they share one process and origin. Auth is decided in its own ADR.
- How agents pass input files to the MCP server and receive results and rendered pages is not decided here. It must be designed in the MCP tool contract so it works across platforms, not only in Open WebUI.
- The Open WebUI host must be able to reach the laptop's IP over the company network. Verify this before phase 3 work starts.
- Copilot and other cloud platforms cannot reach the laptop. Integrating with them requires moving the backend to a server with a stable HTTPS endpoint (README, delivery phase 4).
- If the MCP workload later needs independent scaling, isolation, or a separate release cadence, rule 1 keeps the split cheap: move the MCP adapter into its own process and put the job service behind an internal API. That would supersede this ADR with option B.
