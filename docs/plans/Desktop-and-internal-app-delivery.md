# Desktop and Internal-App Delivery

Status: Owner-approved product direction (2026-09-28), under ADR-013. D0 technical choices remain design work. This plan does not claim an installer or desktop runtime exists and does not expand the current P2-P6 execution handoff.

## Outcome and Priorities

Users install an application, choose a supported translation model to download, open the app and drop files/folders into it. They receive same-format translated files, lightweight fit reports and durable local progress/history. No terminal, manually started service or web sign-in is required for local translation. The signed-in web service and internal REST backend remain supported.

Primary delivery is the desktop window and installer. System-tray progress/completion notifications are useful secondary behavior. Explorer right-click translation is optional backlog. Lenovo managed deployment/preload is an ambition after a proven desktop release, not an assumed distribution commitment.

## Dependencies

D0 may start with the working core. D1/D2 release requires P2-P5: all five formats, ADR-012 fit, persistent jobs/cache/storage and a stable REST contract. P6 assets/components can be reused when suitable, but the desktop is not blocked on MCP/P7 or enterprise cloud/P8. Existing P2-P6 work continues; this document does not authorize a production desktop scaffold before D0 closes.

## D0 - Desktop Packaging and Local Host Design

Run one bounded proof of installation on a clean Windows machine using the existing Python runtime and an actual supported model. Record a desktop packaging ADR covering:

- Desktop toolkit and installer, signed binaries, supported Windows versions/CPU architectures, runtime and native-dependency packaging. Reuse web components where practical without putting translation in the UI.
- Per-user host/worker launch, readiness/version handshake, single-instance behavior, crash/restart, idle model unloading and explicit quit. Closing a window while jobs run must explain whether work continues; an explicit quit must leave jobs recoverable.
- Authenticated loopback contract: current-user bootstrap, protected credential storage, host/origin checks, cross-user denial and no anonymous access. Unrelated browser pages must not be able to invoke the local service. Do not require opening a firewall port.
- Per-user app data, model directory, temporary storage, history/retention and output destinations. Preserve process/import boundaries; reuse the server executable via process/HTTP interfaces.
- Model artifact catalog, license/redistribution review, verified installation, resource checks and update compatibility. Installer and in-app model settings use one installation path, not separate download implementations.

Exit: clean-machine install -> selected model ready -> one real offline translation -> reopen output -> restart with intact local history. Document actual installer/host commands only after this proof. No comparison of many frameworks absent a concrete blocker.

## D1 - Installer and Model Selection

1. Installer or its launched setup wizard lets the user select from supported model bundles and shows download size, installed space, supported languages, resource guidance and license before download.
2. Offer the approved SMALL-100 bundle first. Add alternatives only after their backend, tokenizer, conversion, quality and packaging contracts pass. A one-model initial catalog is honest; multiple untested names are not.
3. Use approved HTTPS artifact sources or company mirrors. Pin version and integrity metadata in a trusted catalog; reject corruption/incompatible bundles and never execute repository-supplied model code.
4. Check disk space and runtime compatibility, show real download/verification status, allow cancellation/retry/resume, and activate only after successful verification/load. An installed app is not automatically local-translation-ready.
5. A failed/cancelled model download leaves a usable setup/retry screen. Remote-only configuration may skip local assets explicitly; it must not imply offline readiness.
6. Settings can add/select/remove supported models later. Do not remove a bundle used by a running job; pin job model identity and invalidate cache on output-affecting changes.
7. Package fonts needed by the chosen fit policy only when redistribution is permitted. Missing fonts still produce explicit best-effort diagnostics, not a blocked translation engine.
8. Installer, upgrade and uninstall handle binaries, models, credentials and retained user data deliberately. Do not silently delete originals, exported results or history.

## D2 - Desktop File and Folder Workflow

- Open app; drag files/folders or use file/folder pickers. Enumerate supported files recursively into a preview with counts, supported/unsupported/read-error outcomes, language/model and output destination.
- Do not follow reparse points by default. Exclude the selected generated-output tree from input traversal, prevent recursive ingestion of earlier results, deduplicate the same selected source path, and stream large enumerations with backpressure.
- Export to a selected output root, preserving relative paths beneath distinct selected roots. Resolve collisions explicitly without overwriting existing files. Keep source bytes unchanged; unreadable/locked files produce per-item failures while other files continue.
- Submit one file per durable job through the selected runtime. Closing/reopening UI or restarting the local host must not fabricate success or lose accepted jobs. Provide honest phase/count progress, cancellation, retry, reports and open-file/open-folder actions.
- Default to local processing with the installed model. Local ownership is the OS user. An explicitly selected hosted connection requires sign-in and clearly states that files will be uploaded; no implicit local/remote fallback or history synchronization.
- Main-window queue/history works independently of tray/notification availability. If tray progress is included, clicking it opens the real queue; completion notifications link to the appropriate result. Respect disabled notifications and aggregate batch completion instead of emitting hundreds of alerts.
- Translation fidelity and ADR-012 fit are identical to equivalent core/service requests. Do not add desktop-specific fit/model prompts.

## I1 - Backend for Internal Applications

Use the existing OpenAPI/REST upload -> durable job -> status/cancel -> output/report flow. Add an integration guide and one independent client example, not a new orchestration framework. Specify versioning, capabilities/limits, authentication, idempotent submissions, bounded batches, retry/backoff and retention. Test dedicated service accounts and reject unauthorized ownership/delegation. Neither API clients nor desktop apps read database/blob internals.

A public-core Python embedding example may serve applications needing synchronous in-process translation. State explicitly that callers own their files/lifecycle and receive no service history/cache automatically. Internal API use does not depend on MCP.

## Acceptance

| ID | Required evidence |
|---|---|
| D01 | Clean supported Windows install without developer tools; selected model downloaded, verified and usable. |
| D02 | With network disabled after installation, real supported-model translation succeeds and output opens. |
| D03 | Interrupted/corrupt download, insufficient disk and incompatible bundle give recoverable explicit outcomes; active model remains intact. |
| D04 | Mixed nested folders, duplicate names, unsupported/locked files and existing output tree yield safe paths and complete per-item accounting. |
| D05 | Real translations for all five formats; originals unchanged, content/protected values preserved, honest ADR-012 reports. |
| D06 | UI/host restart, cancellation and partial failure preserve accepted jobs/results; no simulated progress or success. |
| D07 | Local endpoints/data isolated from another OS user and unrelated web origin; local mode sends no document content remotely. |
| D08 | Explicit hosted connection signs in, uploads and returns owned results; failure does not silently switch deployment. |
| D09 | Upgrade/uninstall and model switching preserve promised data and job/model identity; no developer dependencies on target machine. |
| I01 | Independent internal client submits/retries/polls/downloads; service-account isolation and unauthorized delegation rejection verified. |

Record tested build, OS/architecture, model hashes, timings, installer/output artifacts and actual outcomes. Desktop UI receives usability/accessibility checks; native application spot checks protect document integrity. Required repository checks remain applicable to implementation.

## Later Considerations

Explore Explorer right-click translation only after D2 is usable. If pursued, use a thin activation adapter and the same queue, with system-tray progress/completion notifications as selected by the owner. It must not load models or translate inside Explorer.

For Lenovo, start with a managed-device pilot. OEM preload requires separate agreements, model/font redistribution rights, signed servicing/rollback, resource/battery measurements and supported hardware validation. Do not assume an NPU is required or supported. This is a product ambition, not a blocker for ordinary installer distribution.
