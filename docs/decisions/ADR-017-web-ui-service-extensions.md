# ADR-017 - Service Extensions for the Web UI

Status: Accepted 2026-09-29 (P6.1). Extends [ADR-015](ADR-015-authentication-and-ownership.md) with browser sessions and adds what the [P6.0 audit](../design/web-gui/AUDIT.md) found missing, on top of the storage model of [ADR-014](ADR-014-storage-ownership-and-retranslation.md) and the [progress/skip plan](../plans/P5-P6-document-progress.md). Everything stays owner-scoped as in ADR-015.

## Context

The owner wants every Lenny mock feature except comment-driven edits and fit notifications. The audit found gaps the P5 API could not support honestly: browser sign-in without keeping an API key in the browser, server-side type and language detection before translation (per-file confirmation and the same-language skip), a real preview (compare slider, side by side, page strip) and bubbles that show only current work across sessions. ADR-014 already supplies the saved library ("Your files") and retranslation; the progress plan supplies stage display and Skip layout check. The P6 plan's rules apply: no fake data, no browser rendering of Office layout, no P7 rendering/edit jobs.

## Decision

### Browser sessions

- `POST /v1/sessions` `{key}` validates a provisioned API key (ADR-015 rules), creates a session and returns the owner plus a CSRF token; it sets cookie `dt_session` (HttpOnly, SameSite=Strict, Path=/, Secure on HTTPS). The key is never stored or returned. `DELETE /v1/sessions/current` revokes the session and clears the cookie.
- `sessions(id, token_digest, csrf_digest, user_id, api_key_id, created_at, last_seen_at, expires_at, revoked_at)` stores only SHA-256 digests of 256-bit random tokens. Idle expiry 30 minutes (sliding, updated at most once a minute), absolute 12 hours. A session is valid only while its key is not revoked and its owner is active.
- A request authenticates with `Authorization: Bearer` or the cookie; if both are present and name different owners, it is rejected (401). Cookie-authenticated state-changing requests need `X-CSRF-Token` and, when sent, an `Origin` equal to the request's own origin (403 `csrf_failed`). Sign-in itself checks `Origin` too.
- Failed sign-ins are limited to 10 per client address per 5 minutes (429); the limiter is per web process (the single-host deployment).
- Session expiry never touches jobs; the UI asks the user to sign in again and resumes from server state.

### Detection before translation: saved documents

The mock's "swallow, then confirm type and language" is `POST /v1/documents` (ADR-014 saved source documents): the upload is validated and run through the core's `detect_document` (format, detected source, `detected`/`ambiguous`/`no_text`) before any translation; unsupported, damaged, encrypted, signed or text-less (scanned) files are rejected with 415/422. Identical bytes resolve to the owner's existing document. The UI then submits `POST /v1/documents/{id}/translations` (target, mode, optional explicit source, a batch item or submission identity) without re-uploading; files already in the target language are simply not submitted.

### Preview package

- After a successful translation the worker builds `preview.zip` and stores it with the immutable job result (`job_results.preview_blob`). It contains `manifest.json` and, for PDF, page images: `{format, groups: [{name, paired, units | source/target}], pages: [{number, source, target}], truncated}`. Text formats pair the original's and the output's `document_text` by location; PDF groups list each page's units unpaired and the pages carry JPEG images of the original and translated page (at most 30 pages, 1000 px wide). A preview that cannot be built never fails the job.
- `GET /v1/jobs/{id}/preview` (manifest) and `.../preview/{name}` (one listed image) follow the job's result availability; `GET /v1/documents/{id}/translations/{tid}/preview` serves the current translation's package. The browser never renders Office layout.

### Bubble lifetime and search

`jobs.dismissed_at`: `POST /v1/jobs/{id}/dismiss` and `/restore`; the UI dismisses when the user opens, downloads or clears a bubble. `GET /v1/jobs?active=true` lists unfinished jobs plus finished jobs not yet dismissed; `q` filters job file names. "Your files" is the ADR-014 library: `GET /v1/documents?q=` with each document's current translations and active jobs, Delete translation and Delete source. Jobs themselves are not deleted by users; their results expire per ADR-014.

### Static hosting

With `DOCTRANSLATOR_WEB_DIR` set (the `apps/web` build), the service serves the SPA at `/`: files that exist (hashed assets cached long-term), otherwise `index.html`; `/v1/*` never returns HTML. Every response carries `Content-Security-Policy` (self only; images also blob:/data:), `X-Content-Type-Options: nosniff` and `Referrer-Policy: same-origin`. No third-party requests: fonts are bundled.

## Consequences

- Migration 0002 adds sessions, job dismissal and preview blobs together with the ADR-014 storage conversion.
- The web process runs document detection on upload (bounded by the upload size and core limits); translation still runs only in workers.
- Preview packages add storage roughly equal to the document text plus page images for PDFs; they follow the result's retention and GC rules.
- The same endpoints serve internal applications; only the cookie transport is browser-specific.
