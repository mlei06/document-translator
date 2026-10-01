# ADR-029 - Standard fit and direct downloads without previews

Status: Owner-approved direction, 2026-09-29; specification only, implementation pending. Supersedes ADR-023 production previews and ADR-026 optional thorough/rendered verification. Standard structure-aware fitting remains authoritative. Amends earlier P6/P7 rendering assumptions; adding rendering again requires a new decision.

## Context

The owner wants to remove thorough fit and previews to eliminate the LibreOffice dependency, reduce time to download and simplify the code. Current core thorough mode invokes rendered verification. The server also builds preview packages before publication, and separate page rendering uses LibreOffice for Office formats. The web opens Preview from floating bubbles and History. Standard fit uses document structure, fonts and geometry without Office conversion.

## Decision

- Remove thorough mode and production previews across the shipped core/server/CLI/desktop runtime, not merely the website controls. Do not retain an advanced desktop thorough option or a hidden text/PDF preview substitute. Personal desktop options can customize supported translation behavior, but do not restore removed features.
- Keep standard fit, format-native construction, complete-content checks, serialized-file verification and safe PDF placement. Keep PyMuPDF for actual PDF translation and font/geometry libraries needed by standard fit. No replacement renderer or cloud conversion service.
- Do not expose Checking layout as a website status. Keep Translating during internal standard fit, then Saving during actual output persistence and Ready to download only after successful publication. Preserve backend fit diagnostics/timing; no timing assumption or artificial delay controls this mapping.
- Publish output and minimal report as soon as translation, standard fit and required integrity checks complete. No preview package, rasterization, rendered verification, page queue or preview polling is on or after this product path.
- Floating bubbles display filename, language direction, progress/state and explicit actions. Their body is no longer a button and opens no preview/details screen. Completed available work offers direct Download; active work offers Cancel; terminal work offers Dismiss. Errors and small diagnostic details are inline. History offers the same direct current-result download semantics under ADR-028.
- Do not download automatically at job completion. A deliberate Download click starts transfer without an intermediate page. Dismissing a bubble only clears the current workspace display, not private History or shared output.
- New thorough requests fail clearly as unsupported; never silently claim standard fit performed rendered checks. Existing completed translations/reports remain downloadable under their existing contracts. Drain old work before removing the renderer; do not silently change pinned in-flight jobs.
- Remove LibreOffice discovery/configuration/process management and production install/CI requirements when implementing. Do not remove unrelated installed software from the user's machine. Archived research or optional manual external QA may remain clearly separate from shipped runtime and required checks.

## Consequences

The normal path becomes upload, translation, standard layout fitting, validated publication, direct download. No click on an animated bubble is needed to navigate elsewhere. Download still needs an explicit user action; status/error/cancel controls remain accessible.

Standard fitting remains best effort and does not prove native rendered appearance. Required safeguards against missing content, broken files and unsafe PDF placement remain. Office page rendering is already asynchronous today, so removing it alone is not a guaranteed large download speedup; removing synchronous preview packaging and selected thorough verification eliminates their actual overhead. Measure remaining latency rather than promise a numeric improvement.

See [Architecture](../Architecture.md#standard-fit-and-direct-downloads-adr-029) and [delivery specification](../plans/standard-fit-direct-download.md).
