# Unified website implementation evidence

This records the website portion of `docs/plans/unified-translator-design.md`. The current explicit unified specification governs the changes, superseding the old source/model/preview interaction in the existing implementation.

## Implemented decisions

- File selection immediately creates a draft and starts up to three uploads. Clicking a target synchronously pins every current draft member before any asynchronous submission. Upload completion submits only that ready member. Later drops remain a separate draft.
- A server batch seals only when every pinned member is admitted or cancelled. Failed members keep admission open for individual Retry.
- A failed upload retains its file, target and batch membership for individual Retry. Known invalid format/size/empty files remain visible with an error and cannot be retried unchanged. Failed translation jobs can reupload their retained browser File; after reload the user must supply the original again.
- Unsubmitted uploads use `staging=true`. Cancellation and unmount attempt staging deletion; the server staging lifetime is the recovery bound when the browser disconnects.
- Website requests send `selection_policy=website_auto`, `retention=cached` and `download_semantics=current_shared`, without source, model, decoding or force controls. Stable client item IDs recover uncertain admission responses.
- Progress groups have explicit Download, Cancel, Retry and Dismiss controls. The group body does not navigate. Standard fit displays Translating without a percentage. Terminal success determines the green ready ring.
- History uses private history grants and current shared downloads. Downloads check the authenticated response before creating a browser download, so unavailable results display an error and refresh availability.
- Browser settings retain appearance, behavior and target preference only. Removed production preview, translator, protected-word and advanced settings screens and their callers. Theme tokens remain independent of mascot hue; the original glyph paths, meadow artwork and Geist assets are unchanged.
- The queue uses a flowing layout to accommodate growing batches, narrow screens and zoom. Action buttons use short visible labels and complete accessible names so long filenames cannot force horizontal overflow.

## Verification

Before editing, the existing Playwright `same-language selection lets the user choose a different target` case passed. It reproduced the old source-picker and same-language blocking interaction end to end.

Frontend lint, typecheck, production build and formatting checks have passed. The final unit suite passes 35 tests in seven files, including delayed-upload ordering, duplicate-click target pinning, later-draft separation, retry isolation, cancellation fencing, batch sealing and a 250-file admission test with three concurrent uploads. Result-state regressions cover stale progress, safe fallback messaging and unavailable current outputs. The OpenAPI schema and TypeScript definitions were regenerated with `npm run gen:api`.

The real-service browser suite uses real cookie/CSRF authentication, staging, database admission, worker/core processing and authenticated files. Its engine is explicitly deterministic test code, not evidence of real Davy or HY-MT quality. It covers slow uploads, same-language target acceptance, target-only payloads, independent sibling admission, direct downloads, private History deletion, another account's guessed History file denial, isolated upload retry and cancelled admission.

Initial browser verification found and fixed a nested batch-item response mistaken for its job, horizontal overflow from long filenames inside action buttons, clipping at 200% zoom, and a notification overlay obscuring result actions. Notices now remain in document flow. Screenshots exercise 1440/768/375/320 widths, both themes, narrow landscape and 200% zoom; reduced motion and keyboard focus are included. Email/password registration, session isolation during pending uploads, and pointer-following behavior retain independent coverage.

An initial browser run exposed an existing reduced-motion preference-change defect: the mascot frame loop did not resume when motion was enabled after startup. The fix explicitly starts/stops the loop on media preference changes. Targeted verification passed, including returning to reduced motion and checking visible, unclipped keyboard focus at 200% zoom. After the latest detection-metadata API update and corresponding test-engine signature update, the final complete `npm run e2e` run passed all seven tests (6.4 minutes, exit 0).

The final lint, typecheck, format check and build pass. Preserved screenshots are in `apps/web/verification/screenshots`, including `ready-results.png`, the eight width/theme images, and `200-percent-keyboard.png`. Visual inspection confirmed direct action visibility, green complete rings, the mint mascot, retained meadow framing and readable opaque controls. No website-specific external blocker remains. Real-model and packaged-desktop acceptance remain outside these browser results.

## Contrast measurements

WCAG relative-luminance ratios from the shipped semantic colors:

| Pair | Ratio |
| --- | ---: |
| White primary text on `#B51F24` | 6.59:1 |
| Light secondary text on white | 7.00:1 |
| Dark secondary text on `#111822` | 9.29:1 |
| Light active progress against track | 5.23:1 |
| Dark active progress against composited track | 4.84:1 |
| Light success against white | 5.79:1 |
| Dark success against `#111822` | 10.22:1 |

The dark track measurement composites the existing 10% white track over the opaque dark surface. Controls and status labels use opaque surfaces; the meadow treatment applies only to the background layer.

## Desktop UI collaboration

At the desktop owner's request, a bounded UI review also corrected native-shell frontend recovery controls, streamed folder-discovery cancellation, same-identity queue-backpressure retry, per-item target pinning, polling focus preservation, journal-output refresh and locally bundled Geist fonts. `apps/web/verification/review-desktop.mjs` is an explicit test-only Tauri bridge fixture. It passed browser assertions for these interactions and 375px overflow, and saved desktop review images alongside the website evidence. This is frontend evidence only, not a native bridge or installer acceptance claim.

The follow-up native review led to a separate compact `activity.html` frontend for Explorer batches, using the same glyph and fonts. `verification/review-activity.mjs` passed counts, per-file errors, Cancel batch command, Open Lenny command, polling focus retention and narrow-layout checks. Light/dark screenshots are `desktop-activity-light.png` and `desktop-activity-dark.png`; syntax, oxlint and Prettier checks passed. Native activation/installer findings were sent to the desktop owner for correction, including cleanup on early discovery failure, duplicate activation state, cancellation independent of renderer polling and installer PowerShell argument handling.

After direct Open file and Show in folder actions were added to Explorer activity, the updated fixture passed both native-command argument checks and focus retention across polling for each action. Both themes and the 375px overflow check passed again; the refreshed dark screenshot was visually inspected. Fixture formatting and activity/fixture lint are clean. Actual native execution remains separately recorded in desktop evidence.

## Limits

These browser tests do not certify inference quality, packaged desktop behavior, signing, or clean-machine model readiness. They do not establish a production latency improvement. The baseline behavior was captured by the original E2E run; its temporary screenshot was replaced by Playwright's later runs, so no before-image comparison is claimed.
