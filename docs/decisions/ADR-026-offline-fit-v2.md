# ADR-026 - Structure-Aware Offline Fit and Optional Rendered Verification

Status: Accepted by the owner, 2026-09-29, through the explicit instruction "implement this offline fit check". Implemented in the workspace; scoped evidence and repository verification are recorded in the companion plan.

## Context and authority

Later owner direction: [ADR-029](ADR-029-standard-fit-direct-download.md) removes thorough/rendered verification and previews. Standard structure-aware fit, complete-content checks and safe PDF placement from this decision remain. Earlier rendering requirements below are superseded for the target runtime; removal is not yet implemented.

The current implementation instruction accepts this design for PDF, PPTX and DOCX. This decision supersedes ADR-012 shrink-only/source-measurement coupling, ADR-018 unsafe overflow placement, and ADR-023 pre-publication rendering restrictions only for explicitly selected thorough fit. The other preservation, ownership, skip, and asynchronous preview requirements remain. The detailed implementation contract is [Offline fit v2](../plans/offline-fit-v2.md).

Inspection of two owner-supplied documents established concrete gaps:

- A Chinese-to-English PowerPoint result inspected 122 containers, left 91 unresolved with `missing_glyph`, and adjusted zero. One English instruction measured 64.8 pt high in a 36.3 pt content area; a failed Chinese-source measurement prevented target fitting.
- The English resume extractor classifies right-column dates/locations as left-aligned and merges some project headings, technology stacks and skill categories into preceding paragraphs. Intersecting source font boxes can remove genuine neighbours from the PDF obstacle list. The exact historical output report was unavailable, so attribution of every collision to the overflow fallback is not established.
- ADR-023 records 16-118 s per LibreOffice conversion on the pilot laptop. A mandatory pair of conversions before every download would contradict the owner's explicit preview-latency decision. Prior conversational estimates of a few seconds per Office render are not performance evidence.

## Alternatives

| Option | Assessment |
|---|---|
| Tune only font metrics and shrink harder | Does not repair incorrect extraction, lost anchors or collisions; degrades readability. |
| Replace all formats with a reconstructed intermediate document | Risks structure and fidelity, including editable Office content. No evidence justifies replacement of the adapters. |
| Render every result repeatedly before download | Better evidence in supported cases, but conflicts with measured latency and current publication behavior. |
| Add a vision model as the primary fitter | Does not meet this offline scope and leaves structural errors to a probabilistic repair loop. |
| Improve structure/placement and deterministic fitting; offer explicit thorough verification | Chosen approach. Addresses reproduced causes, preserves fast default operation and permits stronger evidence when requested. |

## Decision

1. Retain the adapters, HarfBuzz estimator, MuPDF PDF placement, shared core and immutable result model. Separate extraction correctness, layout adaptation and saved-output verification.
2. Default to `standard` offline fitting: no model calls, no Office conversion on the publication path. Add `thorough` as an explicit option that can delay publication for bounded local rendering. Existing asynchronous previews remain unchanged.
3. Resolve source and target font coverage separately. A missing source glyph must not suppress target measurement. Use deterministic provisioned target fallback written into the output; never assert that a guessed source fallback reproduces native Office layout.
4. Permit bounded PPTX text-box growth into proven free space, bounded paragraph-spacing reduction, and then proportional shrinking. Preserve anchors, semantic breaks, protected content and the current 70%/8 pt floors. Do not move neighbouring objects or reconstruct slides.
5. Fix PDF paragraph boundaries and infer right-column anchors conservatively. Preserve the fixed page and place all translated text in legal regions. Remove the fallback that intentionally grows through neighbours or shrinks below the floor. If complete legal placement is impossible, fail with a typed placement error instead of publishing a known overlapping PDF. This is an explicit change to ADR-018, including its skipped-fit path.
6. Let DOCX body text reflow and change page count naturally. Improve constrained-element measurement without importing unvalidated East Asian multipliers. Unsupported layouts remain explicit.
7. Report geometric checks separately from rendered checks. No image-similarity score or geometric pass is a visual-perfection guarantee. Keep the current simple UI and skip action; a warnings UI is not authorized by this design request.

## Accepted amendments

- ADR-012: add bounded geometry/spacing edits, independent target measurement, and explicitly selected runtime rendering; retain skip, preservation, floors and normal UI behavior.
- ADR-018: revise extraction/alignment/obstacle rules and replace deliberate collision/below-floor placement with a typed failure when no legal complete output exists.
- ADR-023: permit pre-publication rendering only for explicitly selected `thorough`; preserve non-blocking preview defaults and file-in/file-out opt-out.
- ADR-003: extend existing capability interfaces within current module boundaries; do not weaken import contracts.

Implementation must update the canonical Architecture fit/render/interface sections and affected README requirements before production coding. The companion plan's OF0 gate resolves measured renderer correspondence limitations before OF4 implementation. No new service, general document editor, external model or background mutation of published files is proposed.

## Consequences

Standard fitting becomes more useful but remains best effort. Thorough mode can take substantially longer and verifies only the renderer and supported checks recorded in its report. Some previously successful but overlapping PDFs will instead return a placement failure; this is a deliberate integrity-versus-availability tradeoff accepted by the owner. XLSX retains its existing fitting behavior and TXT stays not applicable.
