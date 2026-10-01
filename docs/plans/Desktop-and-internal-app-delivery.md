# Desktop and Internal-App Delivery

> Current authority: [Unified translator design](unified-translator-design.md) incorporates the surviving desktop runtime/installer requirements and supersedes all conflicting text below, including mode/model selectors, individual credential provisioning, old model order and deferred Explorer delivery. Desktop automatically uses the installer-provisioned shared Davy key and then installed HY-MT. Historical packaging evidence and separate I1 integration scope remain valid.

> Superseding desktop specification: [ADR-030](../decisions/ADR-030-desktop-online-offline-delivery.md) and [Online/Offline delivery](desktop-online-offline-delivery.md). The latest owner instruction selects direct-Davy Online processing independently of the website service; desktop does not use its cache/History. Two installation choices, one offline bundle, Automatic/Online/Offline modes and first-class Explorer translation replace conflicting D0/D1/D2 text below. ADR-029 removes preview/thorough-fit/skip-fit UI. Existing I1 internal API scope remains separate. No desktop implementation is claimed.

> Translator configuration is governed by accepted [ADR-019](../decisions/ADR-019-configured-translators.md): selectable configured translator IDs, one default, explicit local/remote location and no automatic fallback. Desktop setup selects supported model downloads; hosted users select admin-enabled translators. Installer delivery remains D0/D1 work.


> Storage/identity revision, 2026-09-29: follow accepted [ADR-014](../decisions/ADR-014-storage-ownership-and-retranslation.md) and [the storage transition plan](P5-D2-storage-and-ownership.md). These supersede earlier global-cache, version-0, desktop-library and conflicting retention requirements in this plan. Human/service ownership, local fresh exports, hosted current results and immutable job downloads are the target; implementation is pending.


Status: Owner-approved product direction (2026-09-28), under ADR-013. D0 technical choices remain design work. This plan does not claim an installer or desktop runtime exists and does not expand the current P2-P6 execution handoff.

## Outcome and Priorities

Users install an application, choose a supported translation model to download, open the app and drop files/folders into it. They receive same-format translated files and active/recoverable progress and user-controlled exported files. During fit, show Checking layout and Skip layout check using [the shared progress contract](P5-P6-document-progress.md#skip-layout-check); then save and offer the file without per-section fit details or warning badges. No terminal, manually started service or web sign-in is required for local translation. The signed-in web service and internal REST backend remain supported.

Primary delivery is the desktop window and installer. System-tray progress/completion notifications are useful secondary behavior. Explorer right-click translation is optional backlog. Lenovo managed deployment/preload is an ambition after a proven desktop release, not an assumed distribution commitment.

## Dependencies

D0 may start with the working core. D1/D2 release requires P2-P5: all five formats, ADR-012 fit, recoverable jobs and a stable REST contract with the ADR-014 local-export profile. P6 assets/components can be reused when suitable, but the desktop is not blocked on MCP/P7 or enterprise cloud/P8. Existing P2-P6 work continues; this document does not authorize a production desktop scaffold before D0 closes.

## D0 - Desktop Packaging and Local Host Design

The [D0 runtime contract](D0-desktop-runtime-contract.md) defines the bounded packaging experiment and proposed integration requirements for the desktop, P5 and model owners. Keep Python for the translation/backend layer and use a native desktop shell. Tauri remains a candidate pending a compiled shell and installer acceptance; the CLI packaging probe alone does not complete D0.

Run one bounded proof of installation on a clean Windows machine using the existing Python runtime and an actual supported model. Record a desktop packaging ADR covering:

- Desktop toolkit and installer, signed binaries, supported Windows versions/CPU architectures, runtime and native-dependency packaging. Reuse web components where practical without putting translation in the UI.
- Per-user host/worker launch, readiness/version handshake, single-instance behavior, crash/restart, idle model unloading and explicit quit. Closing a window while jobs run must explain whether work continues; an explicit quit must leave jobs recoverable.
- Authenticated loopback contract: current-user bootstrap, protected credential storage, host/origin checks, cross-user denial and no anonymous access. Unrelated browser pages must not be able to invoke the local service. Do not require opening a firewall port.
- Per-user app data, model directory, temporary storage, bounded job/temporary retention and output destinations. Preserve process/import boundaries; reuse the server executable via process/HTTP interfaces.
- Model artifact catalog, license/redistribution review, verified installation, resource checks and update compatibility. Installer and in-app model settings use one installation path, not separate download implementations.

Exit: clean-machine install -> selected model ready -> one real offline translation -> reopen output -> restart with recoverable active work and intact exported files. Document actual installer/host commands only after this proof. No comparison of many frameworks absent a concrete blocker.

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
- Submit one file per durable job through the selected runtime. Closing/reopening UI or restarting the local host must not fabricate success or lose accepted jobs. Provide honest phase/count progress, cancellation, retry, Skip layout check during fit, and open-file/open-folder actions. Every new explicit run translates fresh; no local result cache or permanent source/result library. Reserve numbered collision names atomically and publish verified files safely.
- Default to local processing with the installed model. Local ownership is the OS user. An explicitly selected hosted connection requires sign-in and clearly states that files will be uploaded; no implicit local/remote fallback or history synchronization.
- Main-window queue and bounded recent-operation list work independently of tray/notification availability. If tray progress is included, clicking it opens the real queue; completion notifications link to the appropriate result. Respect disabled notifications and aggregate batch completion instead of emitting hundreds of alerts.
- Translation fidelity and ADR-012 fit are identical to equivalent core/service requests. Do not add desktop-specific fit/model prompts.

## I1 - Backend for Internal Applications

Use the existing OpenAPI/REST upload -> durable job -> status/cancel -> exact job output/report flow. Dedicated service accounts authenticate the calling backend, which authorizes its own users. Default the integration example to temporary result retention; saved mode is available when needed. External references never grant permission. Add an integration guide and one independent client example, not a new orchestration framework. Specify versioning, capabilities/limits, authentication, idempotent submissions, bounded batches, retry/backoff and retention. Test dedicated service accounts and reject unauthorized ownership/delegation. Neither API clients nor desktop apps read database/blob internals.

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
