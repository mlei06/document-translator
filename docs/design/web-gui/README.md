# Web GUI Design Material

Design exploration for the web GUI ([P6](../../IMPLEMENTATION_PLAN.md#p6---web-gui)), gathered ahead of that phase. Nothing here is decided architecture; it is input for the P6 plan and the web UI section of `docs/Architecture.md`.

## Concept

The GUI is built around Lenny, a cute, lovable mascot ("Om nom, a PowerPoint!") who is always on screen:

- **Sign-in:** modelled on shadcn's `login-02` block (form on the left, image filling the right half), with Lenny's world as the image. Lenny says "Enter your username" and "Enter your password" as each field is focused, and closes its eyes on the password field.
- **Entering the app:** the same background uncrops to fill the screen, pushing the form out to the left, while Lenny moves to the center.
- **Uploading:** Lenny's eyes follow the cursor and the dragged file. Lenny swallows dropped files, then confirms the detected file type and language.
- **Translating:** the user picks one target language per batch. Lenny spits the files back out as floating bubbles that show translation progress.
- **Previewing:** clicking a bubble opens a preview page, with Lenny present. The user can comment on a page or a text box to request a fix.

## Assets

| File | What it is |
| --- | --- |
| `assets/meadow-day-original.png` | Day background as generated (2912x1632), with clouds. The style reference (`--sref`) for every other generated asset. |
| `assets/meadow-day-clear-sky.png` | The same image with the clouds removed (2912x1632). Grass, hills and treeline are the original pixels; only the sky behind the clouds was rebuilt as a matching gradient. This is the day background. |
| `assets/meadow-night-original.png` | Night background for dark mode (2912x1632): stars, a moon upper right, and fireflies in the grass. It lines up with the day image (same hills and flowers), so switching themes can crossfade between them. It has no clouds. |
| `assets/cloud-*.png` | Individual clouds on the same flat sky blue, cut out and drifted across the sky in code. `cumulus-1`, `cumulus-2`, `puffy-small-1`, `wispy-2` and `soft-distant-1` match the meadow's style closely. `wispy-1` and `towering-1` are more brushy and warmer in color; use them sparingly, if at all. `cumulus-2`, `puffy-small-1`, `wispy-2` and `soft-distant-1` were cut from one generated sheet of four. |

## Background treatment

- **Sharp stills, no video.** Grass animation loops were tried (Veo image-to-video, crossfaded into seamless loops). They came out at 1280x720, visibly softer than the 2912x1632 stills at full-screen size, and the stills were preferred.
- **Clouds:** separate cutouts drifting slowly across the upper sky in code, each at its own speed and wrapping around the edges. They fade out before the horizon so they never pass behind the hills. At night they are dimmed to a moonlit grey and fewer are shown.
- **Depth:** the ground and cloud layers shift slightly with the pointer at different amounts.
- **Reduced motion:** clouds stay put and the pointer shift is off.

Open items:

- Twinkling for the fireflies painted into the night image, if wanted: glow sprites layered on top in code.
- A tall version for phones.
- If the grass should move after all: animate the full-size still in code (WebGL), which keeps it sharp.

## Runnable Prototype

This is the existing mock that [P6](../../plans/P6-web-ui-integration.md) audits and integrates. It is a design prototype with a simulated backend, not a working product.

### Source of record

- **Files:** `prototype/lenny.html` and `prototype/assets/` (7 WebP images). The repository copy is canonical.
- **Origin:** exact copy of the owner's claude.ai artifact "Meet Lenny" (<https://claude.ai/artifact/FwuVacar3ZE23yxHEuPQHe>, private to the owner), published version 13 on 2026-09-27. SHA-256 of `lenny.html`: `30e6b5d83e42858a9ce864ee2d5b4dad37e9c6e2ddc7dc47384ad4a48fe817d4`. The originating agent's working copy was temporary and no longer exists.
- **Technology:** one self-contained file of HTML, CSS and vanilla JavaScript. No framework, package manager, lockfile or build step. The only external request is Google Fonts (Geist, Geist Mono). It is not the React + TypeScript app that ADR-002 requires, so integrating it means porting its components, styles and assets into `apps/web`, not wrapping this file.
- **Assets:** `meadow-day.webp` is the clear-sky day still and `meadow-night.webp` the night still, both at 2912x1632 and WebP quality 84. The five `cloud-*.webp` files are the matching `assets/cloud-*.png` sources with the flat blue background converted to transparency and trimmed. `cloud-wispy-1` and `cloud-towering-1` are not used.

### Running it

- Open `docs/design/web-gui/prototype/lenny.html` directly in a Chromium browser, or serve the folder with `python -m http.server 8000 --directory docs/design/web-gui/prototype` and open <http://localhost:8000/lenny.html>.
- Any username and password signs in. State is kept in browser `localStorage` per username, under the keys `lenny.jobs.<username>` and `lenny.settings`. Clear them to start fresh.
- The claude.ai host wraps the file with `<!doctype html>`, a UTF-8 charset and `<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">`. Add that viewport tag when checking phone widths locally.
- **Verified:** Microsoft Edge (Chromium) at 1440x900, 1366x768 and 390x844, in light and dark.
- **Not verified:** Firefox and Safari. The file uses `color-mix()`, CSS container queries, `@property` and `backdrop-filter`.

### Code map

The script is one closure, in this order. Central state lives in the object `S`.

1. Theme tokens (CSS custom properties; dark via `prefers-color-scheme` or `data-theme`).
2. World: stills, cloud drift, pollen/firefly canvas, pointer parallax.
3. Lenny: SVG from `lennySVG()`, spring rig `rigLoop()`, expressions as CSS classes (`blink`, `hop`, `chew`, `gulp`, `boop`, `talk`, `sleep`, `happy`, `shy`).
4. Settings and menus.
5. Persistence and history (`loadJobs`, `doSaveJobs`, `openHistory`).
6. Theme.
7. Speech (`speak`, `setSay`).
8. Eating files (`eat`, `detect`, `fly`).
9. Bubbles (`makeBubble`, `translate`, `renderBubble`, a 380 ms progress timer).
10. Preview (`pageCard`, `renderPreview`, compare slider).
11. Event handlers.
12. Sign-in and the sign-in-to-app transition.
13. Drag and drop.

### Feature inventory

| Area | What the user sees | Real or simulated in the mock |
| --- | --- | --- |
| Sign-in | shadcn `login-02` layout: username, password, "Forgot your password?", "Sign in with your work account", "Ask your IT admin". Lenny reacts to field focus, closes his eyes on the password field and can be booped. A caption card sits on the meadow. | Simulated. Any credentials are accepted. The links only make Lenny reply. |
| Transition | On sign-in the meadow uncrops to full screen, the form is pushed out and Lenny flies to the center. Sign-out reverses it. | Presentation only. |
| Header | Brand, a "Your files" button, a day/night toggle, a "Prototype" badge and an account menu (Your files, Lenny settings, Start over, Sign out). | The display name is whatever was typed at sign-in. |
| World | Day and night stills, drifting clouds, pollen or fireflies, parallax and a vignette. The page never scrolls; dialogs scroll internally. | Presentation only. |
| Lenny | Lit SVG with spring-driven gaze and lean toward the pointer and dragged files, blinking, word-by-word speech with a moving mouth, and sleep after 40 s idle. Clicking him boops him and opens a context menu. | Presentation only. |
| Upload | Drag and drop anywhere (the meadow dims around a spotlight on Lenny), a file picker, "Try sample files" with 4 built-in names, and the swallow animation. Unsupported extensions are spat back out. | File type comes from the extension only. Nothing is uploaded. |
| Source language | Detected language per file, correctable in a dropdown. | Guessed in the browser from the Unicode script of the file name, or the first 4 KB of a TXT file. |
| Target language | Quick choices plus a free-text language. A default language skips the question. Files already in the target language get a "Skip it / Translate anyway" prompt. | Client-side only. |
| Progress bubbles | Glass orbs with a progress ring, fit-warning badges, sparkles on completion, and an × that moves a bubble to Your files. Bubbles become a swipeable dock on phones. | Simulated. Progress comes from a random timer. Fit warnings are invented: always 2 on PPTX, a 30% chance on other formats. |
| Preview | Compare view (draggable before/after divider), side by side with linked highlighting, a page strip with warning and version markers, keyboard page navigation, and a notes panel with Lenny. | Simulated. Pages are placeholder drawings; only the 4 sample files have real title strings. |
| Comments and fixes | A comment on a page or text box leads to "Lenny is asking Gemma to fix..." and a new page version. | Simulated with a timer. P6 treats edit jobs as P7 scope. |
| Download | Per-file "Download" and "Download all". | Only shows a message. |
| Your files | Files grouped by batch, with search, status filters, a "Deletes in N days" countdown, and preview, download, "put back on the meadow" and delete with confirmation. "Add example history" fills an empty list. | Simulated. Stored in `localStorage` per username, with client-side retention of 7 days and client-generated example history. |
| Welcome back | Bubbles return only for files still translating, or finished but not yet opened or downloaded. Lenny reports what finished while the user was away. | Simulated. Progress while away is extrapolated from elapsed time. |
| Lenny settings | Color (6 swatches plus a hue slider), sprout, theme (System/Day/Night), default target language, follow-cursor and playful-reaction switches. | `localStorage`. |
| Accessibility | Keyboard menus (arrows, Home, End, Esc), a keyboard-operable compare slider, an `aria-live` speech region, focus return, and reduced-motion handling. Text never depends on an entrance animation finishing. | Partially done. There has been no screen-reader or contrast audit. |

### Owner decisions reflected in the mock

These were made in design sessions on 2026-09-26 and 2026-09-27. The P6 plan still governs where it conflicts.

- Lenny is cute and playful ("Om nom, a PowerPoint!") and built as hand-authored SVG with code animation. The bible-strong avatar lab was rejected: its runtime is AGPL-3.0, and it has no mouth or cursor tracking.
- The sign-in page follows shadcn `login-02`, with Lenny's world as its image, and uncrops into the app.
- One target language per batch.
- Sharp stills were preferred over 720p Veo grass-video loops. Clouds drift in code.
- The page must not scroll over the world.
- **File lifetime:** bubbles show only current work (translating, or finished but not yet opened or downloaded). Everything else lives in "Your files". Clearing a bubble never deletes it; deleting is explicit. Retention is visible to the user.
- Clicking Lenny opens quick actions and settings, including a default target language.

### Known gaps against the P6 contract

These are inputs for the P6.0 audit, not decisions:

- **Sign-in:** the username/password mock must become the P6 access-key session flow.
- **Detection:** the mock guesses file type and language in the browser. The P6 plan requires these to be server facts. The same-language skip also needs the detected source language before translation starts, which is an API gap.
- **Progress and fit:** percentages and warnings are invented and need binding to real job states and fit reports.
- **Bubble lifetime:** the rule needs per-job opened and downloaded timestamps (or a seen flag), plus a query for active and unseen jobs. This is an API gap.
- **Your files:** needs owned, paginated job listing with search and status filters. "Put back on the meadow" is UI state and can be local or a server flag.
- **Preview:** the compare view, page strip and linked highlighting need page images and source-to-target text mapping, which the P6 API does not provide. Rework per the P6 preview rule.
- **Comments and fixes:** remove or rework (P7 scope).
- **Download all:** needs honest handling of browser multiple-download limits, or a bounded ZIP API.
- **Default target language:** decide whether it is a harmless local preference or a server-side user setting.
- **Fonts:** Google Fonts is a third-party request. Self-host Geist for the internal deployment.
- **Code quality:** single file, no tests, no types. Treat it as a reference implementation to port.

## P6 Integration Contract

The owner has requested audit and integration of the existing runnable mock, preserving useful features and reworking/dropping/adding features as needed. Follow [P6](../../plans/P6-web-ui-integration.md), inventory the exact artifact source (the [runnable prototype](#runnable-prototype) above) in `AUDIT.md`, and connect real authenticated data from the P5 service. These concept notes/assets are not proof of a runnable UI or backend integration. Do not leave simulated production progress, fake history or placeholder downloads. Preview/fix concepts need real in-scope support or explicit rework; they do not automatically authorize P7 rendering/editing.
