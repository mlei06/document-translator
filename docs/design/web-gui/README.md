# Web GUI Design Material

Design exploration for the web GUI ([P6](../../IMPLEMENTATION_PLAN.md#p6---web-gui)), gathered ahead of that phase. Nothing here is decided architecture; it is input for the P6 plan and the frontend component doc.

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
