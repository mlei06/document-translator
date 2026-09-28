# ADR-013 - Web Service, Desktop App and Internal Translation Backend

## Status

Accepted product direction, 2026-09-28. Installer, desktop toolkit and local authentication implementation require the bounded D0 design gate. No desktop implementation or OEM shipping agreement is implied.

## Context

The owner wants three supported uses: a signed-in web service, an installed laptop application accepting files and folders, and a translation backend for other internal applications. The desktop installer must let users choose a model to download. Right-click translation is an optional future consideration, not the desktop release goal. Lenovo laptop integration is a long-term ambition.

## Options Considered

- Remote-only desktop wrapper: insufficient because it does not provide local translation.
- Independent desktop pipeline/storage: rejected because formatting, fit, cache and recovery would diverge.
- One core and job-service implementation with local and hosted deployment profiles: selected.

## Decision

1. Keep the Python translation core, format adapters and lightweight fit policy (ADR-012). Keep P5/P6's authenticated hosted service and web UI.
2. Add a Windows-first installed desktop app. The primary flow is open app, drag/drop or pick files/folders, choose language/model/destination, submit a batch, inspect progress and retrieve translated files. Model setup is part of installation/onboarding; no developer Python, terminal or manually started server is required.
3. The desktop app uses a managed per-user local host and worker running the same job/cache/storage implementation as the hosted service. The desktop does not import server internals or maintain a separate translation queue. Reuse REST contracts through authenticated loopback; choose the exact bootstrap mechanism at D0. Do not expose a LAN listener by default.
4. Local use derives ownership from a trusted OS-user bootstrap, without requiring a company web sign-in. Local requests still require authentication and current-user isolation. Hosted use requires service credentials. Desktop may explicitly connect to an approved remote service, but never silently upload local-mode documents or fall back between hosts.
5. Local and hosted histories/caches are independent installations, not automatically synchronized. The synchronous local CLI remains a separate lightweight path without persistent history (ADR-010).
6. Installer/onboarding offers a curated catalog of supported model artifacts with language coverage, compatibility, download/installed size, resource guidance and license. Download only the selected compatible bundle, verify integrity and activate atomically after a load smoke check. Support interrupted-download recovery and later model selection/removal in app settings. Keep document content out of model-download requests.
7. Initial local engine support remains the existing SMALL-100/CTranslate2 path. More choices require runtime compatibility, redistribution rights and translation-quality evidence. Do not list arbitrary model repositories as supported. Gemma is currently an internal remote endpoint, not a promised downloadable desktop model.
8. Internal applications use the versioned asynchronous REST job API by default, with scoped credentials, durable jobs, status/cancel, downloads and reports. Machine clients use dedicated service identities mapped to owned records; acting for a human requires explicit trusted delegation. Client-supplied owner IDs cannot confer access. Python callers may embed the public core if they deliberately own orchestration and do not expect service cache/history.
9. Folder submission enumerates supported files incrementally with bounded concurrency, per-item outcomes and recoverable batches. Preserve relative directory structure on export, avoid overwrite, and exclude generated output trees and reparse-point traversal by default. Originals remain unchanged.
10. Tray progress/completion notifications may complement the desktop window; the window remains the complete workflow. Explorer right-click commands and Lenovo preload/managed distribution are later optional work, never prerequisites for the drag/drop desktop app.

## Amendments and Boundaries

ADR-001 still governs hosted MCP; no desktop-specific MCP deployment is added. ADR-002's Python core and React web stack remain; desktop toolkit is not selected by this decision. ADR-003 import boundaries remain: a future desktop app is a client and process launcher, not a second core/server. ADR-004/007/008 job persistence, reuse and recovery apply independently to each runtime. Local bootstrap extends hosted authentication rather than bypassing it.

Confidentiality now explicitly includes processing on the user's device. Hosted processing stays on approved company infrastructure. Downloading model assets is separate from document processing and does not authorize public inference endpoints. General consumer distribution and Lenovo OEM preload require separate licensing, privacy, hardware, servicing and distribution decisions.

## Consequences

P2-P6 remains the current delivery handoff. Desktop and internal-app integration have explicit follow-on tracks with dependencies on the working backend, not on P7/P8. Packaging adds supported-OS/architecture, runtime/model installation, update and uninstall obligations. No NPU/GPU acceleration, ARM support, arbitrary-model support or fleet/OEM readiness is claimed until validated.
