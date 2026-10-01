# ADR-023: Page Rendering for Previews

> Amended by accepted [ADR-026](ADR-026-offline-fit-v2.md), 2026-09-29: structure-aware standard fit, explicit thorough verification, and safe complete PDF placement. Conflicting earlier fit/placement requirements below are historical.

## Status

Superseded for the upcoming runtime by [ADR-029](ADR-029-standard-fit-direct-download.md): remove all previews, page rendering and the production LibreOffice dependency. The implementation/evidence below remains historical/current-code description until removal ships.

Accepted by the owner 2026-09-29. Amends [ADR-017](ADR-017-web-ui-service-extensions.md) ("the browser never renders Office layout" still holds: the server renders) and decides the rendering approach [ADR-003](ADR-003-source-structure.md) left open. Implemented on `release/p2-p6` and verified in a browser against a real local service on 2026-09-29 (see Consequences).

## Context

The web preview showed PDFs as page images but PPTX, DOCX and XLSX only as paired text, which does not show users how their translated document looks. ADR-003 anticipated headless LibreOffice to PDF, then PyMuPDF to images, for P7's visual review.

A first implementation rendered pages while building the preview, before the result was published. LibreOffice took 16-118 s per conversion on the pilot laptop, so every Office download waited for its preview. The owner's requirements: the download must be available as soon as translation finishes; page rendering is a separate, non-blocking step queued as soon as the result is ready; the preview shows the text with a "Rendering pages" indicator and switches to the pages when they exist. File-in, file-out profiles (the desktop app, internal-app API clients) must not pay for previews at all.

## Options Considered

### Render before publication

Pros:
- One step; no new state.

Cons:
- Every download waits for two LibreOffice conversions. Rejected by the owner after it was observed on the pilot.

### Render in the browser (docx-preview, pptx.js)

Pros:
- No server dependency.

Cons:
- Poor fidelity, especially for slides; contradicts ADR-017.

### Microsoft Office automation or a cloud conversion service

Cons:
- Office automation needs a licensed install and is unsupported server-side; cloud conversion sends documents off company infrastructure (README confidentiality). Rejected.

### Render after publication on a separate queue (chosen)

Pros:
- Downloads never wait; failures never fail a job; one mechanism for all layout formats.

Cons:
- Render state, a lease and a second blob per result; LibreOffice becomes a server dependency for Office page previews.

## Decision

- **Rendering (core).** `doctranslator_core.render_pages(path, format, config=RenderConfig)` returns JPEG page images with their sizes. PDF pages are rasterized with PyMuPDF. PPTX (one image per visible slide), DOCX (pages as LibreOffice paginates them) and XLSX (one image per visible sheet, `SinglePageSheets`, tall sheets keep their top) are converted by headless LibreOffice first. Shared conversion/rasterization lives in `render/`; each format's `render.py` chooses its export filter (ADR-003). TXT has no pages.
- **LibreOffice isolation.** One `soffice` process per conversion with its own user profile (a throwaway one, or one reused by a single renderer), seeded to never run macros, never update links, disable active content and block untrusted referer links, so conversion makes no network requests. A conversion past `timeout_s` (default 120 s) is killed with its process tree. Missing LibreOffice raises `RenderUnavailableError`.
- **After publication.** Publishing a result may set `job_results.pages_status = queued`; the job and its download are complete at that point. A renderer thread in each worker process claims the oldest queued render with a fenced token and lease (two conversions plus 120 s), stores a separate pages package (`job_results.pages_blob`: `pages.json` plus images) and records `ready`, `unavailable` (no LibreOffice) or, after one retry, `failed`. Expired leases are requeued, then failed. The text preview package of ADR-017 is unchanged and published with the result.
- **API.** The preview manifest adds `pages_status` (`queued`, `running`, `ready`, `unavailable`, `failed`, `none`) and, when ready, `pages` with `source`/`target` image names (either may be `null` when only one document has that page) and pixel sizes. Page images are served from the pages package; older PDF packages that carry images are still served.
- **Web UI.** The preview shows the text immediately, a "Rendering pages..." ring while `queued`/`running` (polling every 2 s), then the page images with the compare slider and side-by-side view.
- **Profiles: `DOCTRANSLATOR_PAGE_PREVIEWS`.**
  - `eager` (default, the website): queue every non-TXT result at publication.
  - `on_open` (API-heavy services): queue a result only when its preview is first opened.
  - `off` (file-in, file-out: the desktop app, see [D0](../archive/plans/D0-desktop-runtime-contract.md)): never queue, run no renderer thread; the manifest reports `none`.
  Under `eager` and `on_open`, a result with no render yet (including results from before migration 0006) is queued when its preview is opened.

## Consequences

- Migration 0006 adds the render columns to `job_results`; the pages blob is referenced for GC and removed with its result.
- Office page previews need LibreOffice and the deployment's fonts (CJK included) on the worker host; without it they show text (`unavailable`). PDF page previews need only PyMuPDF.
- Rendering shares the worker host's CPU with translation; it never blocks the translation queue.
- LibreOffice on Windows crashes (exit 0xC0000409) while creating a user profile whose files pass the 260-character path limit. The renderer therefore keeps its reused profile under the system temp directory (not the data directory), and a profile is discarded after any failed conversion.
- Browser evidence (pilot laptop, SMALL-100 Greedy, LibreOffice 26.8): for XLSX, PPTX and DOCX fixtures the download was available when the translation finished, the preview showed the text with "Rendering pages...", and the rendered pages replaced it 11-31 s later; a result from before migration 0006 was queued when its preview opened.
- CI must install LibreOffice for the Office rendering tests, which skip without it unless `DOCTRANSLATOR_TEST_REQUIRE_LIBREOFFICE=1`.
