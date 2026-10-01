# Offline Fit v2 - Design Specification

Status: Implemented in the workspace, 2026-09-29, following owner approval. Repository checks pass; native-document acceptance scope and remaining corpus limits are recorded below.

## Objective

Reduce translation-induced clipping, collisions and unnecessary font shrinking in PPTX, DOCX and text-based PDF, entirely on the device or configured company worker. Preserve all translated wording, protected text, inline styles, document structure and editable Office content. Improve the actual saved file, not only its preview.

Use the current fast fitter as one component of a pipeline that first preserves structure, then adapts supported layouts, then verifies the saved output. Do not promise visual perfection or exact native Office parity.

## Relevant architecture and decisions

- [Architecture: fit check](../Architecture.md#fit-check), core pipeline, PDF and page-rendering sections.
- [ADR-003](../decisions/ADR-003-source-structure.md): shared-core boundaries and format-owned capabilities.
- [ADR-011](../decisions/ADR-011-document-translation-contract.md): translation and formatting preservation.
- [ADR-012](../decisions/ADR-012-lightweight-fit-policy.md): current floors, shrink policy, skip and simple UI.
- [ADR-014](../decisions/ADR-014-storage-ownership-and-retranslation.md): owner-scoped reuse and immutable results.
- [ADR-018](../decisions/ADR-018-pdf-strategy.md): PDF replacement and placement.
- [ADR-023](../decisions/ADR-023-page-rendering-for-previews.md): existing local render infrastructure and asynchronous previews.
- [ADR-026](../decisions/ADR-026-offline-fit-v2.md): policy changes and alternatives.

Authority: the user explicitly requested implementation of this spec, accepting ADR-026 and its stated changes. This plan does not mark P3/P4/P7 Active or complete, and does not change board state. Canonical component documentation remains in Architecture; interface sketches below describe the accepted requirements; concrete implementation scope and evidence are recorded below.

## Evidence and reproducible baselines

| Case | Observed evidence | Required response |
|---|---|---|
| `AI-Video-Workflow.zh.en (2).pptx`, English to Chinese to English | Exact output SHA-256 `0d238d7a87aecd6ba57db03a36fa99120162bd1c3f2ddae644a1a1565fb51acd`; saved Gemma job report: 122 inspected, 31 unchanged, 91 unresolved, zero adjusted, skip false. Slides 4-6 visibly collide in a native PowerPoint export. | Reproduce source font coverage failure and the visible collisions before implementing changes. |
| Slide 6, shape 21 | Chinese source resolves both font slots to Segoe UI, with no fallback; source measurement raises `missing_glyph`. English measures three lines / 64.8 pt in 36.3 pt available height. | Measure the target even when the source baseline is unknown; resolve and persist actual target font coverage. |
| `Michael_Lei_Resume.zh.pdf`, English to Chinese | Output SHA-256 `d360d14d6a6dbe898da340b72426fc85492c7c385b941d1c586071f4d0f50076`; rendered output has colliding dates/locations and merged headings. Replaying extraction on English original reproduces wrong anchors and merged project/skills units. Exact historical output report not recovered. | Correct extraction and region allocation before tuning shrink. Do not claim every historical collision was proven to arise from the fallback. |
| Rendering cost | ADR-023 records 16-118 s per Office conversion; smaller browser fixtures became visible 11-31 s after publication. | Keep default publication free of Office conversion. Measure thorough cost on representative files. |

Owner files are currently in `C:/Users/mlei4/Downloads/`; diagnostic renders and the matched deck report are in ignored `data/fit-diagnosis/`. These private files are local acceptance inputs, not portable CI fixtures. Produce minimal synthetic fixtures reproducing each structural pattern, with no personal text or original media committed. Retain hashes and environment information in acceptance records.

## Scope and invariant requirements

In scope: deterministic font handling, PPTX constrained text, DOCX constrained cells/boxes, PDF unit reconstruction/placement, neighbour-aware checks, report identity, optional local rendering, integration through the current core/CLI/API.

Out of scope: Gemma or any vision model; OCR; summarization/retranslation for fit; deleting content; arbitrary object movement; automatic page/slide insertion; changing page size; general document redesign; a new visual editor; consistent font sizes across unrelated slide titles; changing XLSX's fit algorithm. TXT and XLSX retain their existing behavior and regression coverage.

Hard invariants:

- Never alter an input. Never publish a corrupt file or lose translated/protected content to improve appearance.
- Preserve links, bullets, tables, artwork, fields, structural paragraph boundaries and rich runs. Layout patches cannot replace translation nodes.
- Baselines are immutable snapshots of this job's input. A round trip is a new translation, not recovery of the original language or its former font sizes.
- Retain the floor per run: no lower than `max(8 pt, 70% of input size)` by default; runs already at/below 8 pt do not shrink. Existing caller floor configuration remains honored.
- Existing source defects are not automatically repaired, but must not be enlarged or used as permission for new collisions with neighbours.
- No inference network calls, font downloads or remote rendering. Provisioned font availability is established before repair. Reuse existing renderer isolation and resource limits.

## Operating modes and publication

| Mode | Before publication | Meaning |
|---|---|---|
| `standard` (default) | Correct extraction; font resolution; deterministic fitting; saved-file content/integrity and supported geometry checks | Estimated fit with explicit uncertainty. No Office render dependency. PDF uses its writer's real layout and reopened geometry. |
| `thorough` (explicit request) | Standard work plus source/candidate local rendering, supported checks and at most one additional repair round | Evidence tied to a particular renderer, font environment and coverage. Office download can take longer. |

Do not automatically select thorough based on an unresolved result. Requests pin the selected mode at acceptance. CLI exposes `--fit-mode standard|thorough`; REST adds `fit.mode` with the same default. A later UI selector must explain that thorough checking can delay the download; until such a selector is delivered, the existing UI submits standard mode. No warning-badge redesign in this scope.

ADR-023 preview configuration remains independent: `off` prevents preview jobs, but does not override an explicitly requested thorough check. Standard mode never starts pre-publication Office rendering. Post-publication previews must never trigger edits or replace downloaded results.

If thorough rendering is unavailable, fails, times out or has incomplete coverage, retain the latest valid candidate, report `unresolved` with the precise verification reason, and publish if mandatory content/placement checks pass. Do not label it render-verified. A user skip remains `skipped`, preserves committed safe repairs and completes mandatory saving/verification. Skip cannot authorize missing PDF text, deliberate collision placement or below-floor text.

## Processing sequence

1. Read input and snapshot structure, effective styles, anchors, container bounds and obstacles. Resolve paragraph boundaries before submitting translation units.
2. Resolve source font coverage and record baseline certainty. Record unit IDs, input object IDs and protected-content inventory.
3. Translate through the unchanged selected engine and formatting contract. Preserve paragraph/explicit line-break structure.
4. Resolve target fonts independently; serialize approved target substitutions before measuring the candidate.
5. Measure all changed supported target containers even if their source measurement failed. Allocate legal space and select bounded deterministic repairs.
6. Write a candidate to job-private storage. Reopen it and verify content, object structure, chosen effective styles and supported geometry.
7. In thorough mode, render source once and candidate once, assess supported checks, optionally apply one repair batch and render the final candidate once more. PDF uses the existing source/output directly. Never retranslate during this loop.
8. Choose the best valid candidate, assemble its report, and atomically publish the matching file/report through current persistence. Clean up other candidates. Only then may asynchronous previews run.

## Font resolution and independent source/target measurement

Reuse `FontLibrary`, the deployment manifest and HarfBuzz. Resolution order is declared run font, document theme/script fallback, then an explicit provisioned per-script fallback list. Reuse PDF's established CJK family preferences where compatible, keeping shared font policy in a neutral module rather than importing one format into another. Pin actual face hashes, style and fallback-policy version. Font names alone do not establish coverage.

For the target, verify coverage of every run. When fallback is necessary, write the selected face into the relevant Latin/East Asian run slots; preserve bold/italic with a matching face or report unsupported styling. Do not measure with one font while leaving a different font for Office to substitute. Split runs only at script/font boundaries and preserve inline semantics. No blanket document-wide font replacement.

For the source, do not assume a selected fallback matches the font Office originally displayed. Record `declared`, `validated_fallback` or `unknown` evidence. Only a validated baseline may expand the allowed extent beyond nominal bounds. Unknown source extent remains null, never zero and never guessed from character count.

When source measurement is unknown but target measurement is valid, fit the target against nominal content bounds and supported neighbour clearance. Such a fit can safely remove a known target overflow, but retain `source_measurement_unknown` in the report and aggregate `unresolved` until supported rendered evidence resolves that uncertainty. If source and target are both unknown, leave sizes unchanged and identify the unsupported scope.

Only allow legacy source-overflow extent within the available obstacle-free region. Do not turn inherited source overflow into unrestricted permission to intersect another object.

## Deterministic repair policy

Evaluate allowed candidates without modifying the accepted candidate in place. Adapter patches include the base candidate revision and expected original properties; stale/mismatched patches are rejected. Order and tie-breaking must be stable by page, object ID and operation type.

Candidate preference is lexicographic: (1) full content/integrity, (2) no new confirmed clipping/collision, (3) fewer remaining supported overflow findings, (4) least font reduction, (5) least geometry/spacing change. Unknown regions cannot be counted as repaired. Reject any candidate that introduces a new confirmed defect, even if it fixes more defects elsewhere.

PPTX candidate order:

1. Keep the original candidate if it fits.
2. Grow an eligible text box toward verified free space, with its alignment anchor fixed. Cap width and height growth independently at 20% of the input outer dimension and stop 2 pt before obstacles or the slide edge. For pre-existing gaps below 2 pt, preserve that gap rather than moving objects. Process shared free space deterministically and update reservations after each accepted growth.
3. Reduce positive paragraph before/after spacing to 75% of its input value, then 50%, if necessary. Preserve zero spacing, indents and line spacing; do not compress glyph line height.
4. Apply the existing proportional shrink search to the surviving candidates, preserving per-run floors and half-point quantization. Evaluate no more than 40 distinct size candidates per operation profile, four profiles maximum (original, grown, grown/75% spacing, grown/50% spacing).
5. Keep the best valid result with explicit unresolved findings if no candidate fits. Do not claim a measurement pass for unknown layouts.

Growth is initially supported only for ordinary unrotated text boxes/shapes whose containing geometry permits it. Exclude tables, placeholders with inherited geometry, connectors, grouped/scaled shapes, auto-growing shapes and shapes with unsupported transforms from growth; their existing supported font fitting remains available. Never move/resize pictures, diagrams, other boxes, tables or slide masters. For an explicit enclosing card, stay inside its content bounds. Ambiguous containment disables growth. Preserved intentional overlaps inside a group/background do not become generic obstacles; adapter evidence must identify that relationship, otherwise growth is disabled.

Preserve explicit OOXML paragraphs and hard breaks in v2. Do not guess that an authored line break is disposable. Automatic wrap boundaries are not inserted as new semantic paragraphs. Removing presentation-only hard breaks is a separate future policy, not a hidden fit action.

## PDF structure and placement

Retain targeted replacement with MuPDF. Do not convert PDFs into Word documents or flatten them into images.

Extraction changes:

- Build line records with baseline, font metrics, span styles, indentation and column membership. MuPDF blocks are evidence, not authoritative paragraphs.
- Do not merge across a new list marker, column boundary, heading/body style transition, or a labelled row such as a technology stack or skills category. Style changes within a line remain rich runs, not automatic paragraph splits.
- Join wrapped lines only when baseline progression, indentation, style role and the preceding line's occupied width support continuation. Otherwise preserve separate units and their ordering. Record the grouping rule/version; do not use a model.
- Infer right alignment from repeated right edges in the same column/role (at least two lines within 1.5 pt), even for separate one-line units. A single isolated short line with uncertain alignment retains its original region and cannot grow horizontally. The resume dates/locations must share a right anchor and expand left into free space.

Region changes:

- Preserve meaningful heading/paragraph relationships and do not allocate the same new free space to two units. Allocate source regions first, then reserve accepted target footprints in reading order with stable IDs.
- Replace the rule excluding every intersecting box. Use baseline order and actual glyph/line footprints where available to distinguish overlapping font ascender/descender boxes from genuine content overlap. If uncertain, disallow growth rather than dropping the neighbour.
- Include images, non-background drawings, neighbouring text, page/crop bounds and enclosing shapes. Preserve page dimensions and artwork. Column regions cannot cross into another column simply because a source line is short.
- Use MuPDF's layout to trial placement, including target font metrics. Check the complete set of final footprints after placement, not only each unit against original neighbours.
- On no legal placement at the floor, return `layout_unresolvable` with affected IDs and no final PDF. Never silently append a page, leave the source text in place, extend through a neighbour, drop text or shrink below the floor. Trials occur before destructive final redaction; the input and unpublished working candidate remain intact. This policy is accepted in ADR-026.

The same complete-placement rule applies when fit is skipped. Skip stops searching optional repairs; it does not make illegal placement acceptable. A document may therefore fail complete PDF construction after a skip, with a specific error rather than an incomplete download.

## DOCX policy

Normal body text, auto-layout tables and unconstrained dimensions reflow. Changed page count is not a defect by itself. Preserve section/page breaks, keep-with-next, widow/orphan settings, lists, fields, headers and footers. Do not reduce whole-document font size to reproduce the original page count.

For fixed cells and DrawingML boxes, resolve target fonts and measure independently from source as above. Keep current shrink support; no row-height changes, table resizing or floating-object movement in v2. Do not promote empirical East Asian line-height multipliers. Where target CJK wrapping/grid behavior is unvalidated, report uncertainty instead of claiming success.

OF0 scope resolution: DOCX page correspondence must follow stable paragraph identity and text anchors, not original page number. This implementation has no validated paginated DOCX anchors; thorough DOCX remains partial, with unknown correspondence and no render-directed repair. Fixed-cell/floating-object rendered detection is deferred until those anchors are validated. Standard constrained fitting remains supported.

## Rendered verification and limits

Reuse `render/office.py`, format-owned export filters and PyMuPDF. Extend the internal rendering path to retain temporary exported PDF text geometry alongside images; the current `render_pages` JPEG-only contract is insufficient to map findings back to objects. Public preview behavior remains compatible. Generic render modules do not import format adapters.

Source and target must use the same renderer build, font environment and export settings. Record all three. Renderer substitution or content dropped during export is a verification limitation, not automatic evidence that the editable document is corrupt.

Checks combine adapter geometry, text inventories and exported PDF glyph positions:

- Target text exceeding its legal container or page bounds.
- Newly intersecting text footprints, excluding source-intentional overlaps. OF0 does not validate artwork collision detection; that check remains unsupported.
- Anchored correspondence coverage: absent or ambiguous matches are unknown. OF0 does not establish visible-glyph or missing-content proof, so neither is reported as a confirmed defect. Duplicate text, ligatures, fields and reordered runs never justify global substring matching alone.
- Applied font floors and serialized edits still match the final output.

Images are evidence for acceptance/manual QA, not an automatic aesthetic score. Do not add raw pixel similarity, OCR, or a claim that deterministic rules assess visual taste. Invisible/clipped glyphs and ambiguous object matches remain unsupported unless a concrete detector is validated. The report enumerates checks and coverage; `complete` means those supported checks ran, not that every possible visual defect was excluded.

PPTX correspondence uses slide number plus stable object IDs, text anchors and adapter bounds. If mapping is ambiguous, do not apply render-directed edits. DOCX uses paragraph anchors as described above. PDF uses original unit IDs carried through placement and reopened text geometry.

The Office converter currently converts the full document. Do not budget on incremental slide rendering without a validated implementation. Re-rasterizing selected pages can save image work but not necessarily the conversion. DOCX repairs can repaginate later content and require a full conversion.

## Interfaces and module ownership

Extend existing contracts rather than introduce a new layout service:

| Location | Proposed change |
|---|---|
| `types.py` | Add `FitOptions.mode`; report version 2; typed verification state/findings; `LayoutUnresolvableError` mapped to API code `layout_unresolvable`. |
| `document.py` | Extend normalized containers with page-local outer/content bounds, anchor, declared obstacle relationships, source-evidence certainty and supported operations. Carry revision and stable IDs in internal layout patches. |
| `formats/base.py` | Add a separate optional `LayoutRepairSupport` capability for `layout_context()` and `apply_layout_patch(patch)`; keep current `LayoutSupport` and PDF `PlacementFit`. Unsupported adapters are not forced to implement geometry edits. |
| `fit/fonts.py`, `measure.py`, `fitter.py` | Independent source/target resolution, neutral candidate search and geometry checks; no format imports or XML logic. |
| `formats/pptx/layout.py` | Effective font-slot serialization, transform/containment evidence and supported patch application. |
| `formats/docx/layout.py` | Constrained target measurement and uncertainty; no generic DOCX pagination emulation. |
| `formats/pdf/adapter.py`, `layout.py` | Unit boundaries, anchors, region reservation, MuPDF trial placement and safe final write. |
| `render/`, format `render.py` | Temporary rendered PDF/geometry access; unchanged offline isolation; format-owned correspondence metadata. |
| `pipeline.py` | Snapshot, translation, candidate lifecycle, optional verification, skip, final verification and output/report pairing. |
| Apps | Parse/configure options, persist reports, preserve progress/ownership/reuse; no duplicated fit policy. |

Layout patches contain only IDs, expected revision/properties and one of explicit run-font assignment, explicit run sizes, outer box bounds or paragraph before/after spacing. They contain no arbitrary XML, code or text replacement. Adapters validate the allowed operation before application. No public general-edit API is part of this task.

## Reporting, identity and reuse

Keep existing `FitStatus` values; add version-2 evidence fields instead of redefining `passed` as visually perfect. Unknown source measurements, unsupported changed containers, render failure or incomplete requested thorough coverage make the aggregate `unresolved`. Effective user bypass takes precedence as `skipped`; known findings and performed work remain available. TXT stays `not_applicable`. Ordinary DOCX body reflow is not an invented constrained container, although thorough body checks can produce findings.

Report additions:

- Requested mode and effective scope, policy/font-resolution version, renderer identity when used.
- Verification state: `not_requested`, `complete`, `partial`, `unavailable`, `failed`, `budget_exceeded`, or `skipped`.
- Coverage counts for changed units/pages, checked units/pages and unsupported/unvisited scope; no fabricated passes for unvisited pages.
- Findings with stable location, check type, certainty (`confirmed` or `unknown`), source-relative disposition, applied operation and before/after geometry/sizes. No full document text in normal logs/reports.
- Timings separated into font resolution, measurement, repair, source render, target render and verification. Runtime timings are evidence, not identity inputs.

Version all output-affecting extraction/font/fit strategies. Standard and thorough requests cannot share a reusable result. Thorough identity includes renderer build, export settings and effective font identity; if renderer identity is unavailable, the result is not eligible as a completed thorough result. Bump PDF strategy for changed grouping and placement. Old reports remain readable through version-aware decoding; old cached outputs never acquire v2 claims retroactively.

Existing owner-scoped reuse applies to standard completed results, including honest unresolved results. Thorough results with incomplete/failed checks and all skipped results are excluded from full-fit reuse. Jobs retain their exact immutable artifacts; a later preview or diagnosis cannot change them.

Only reuse preview renders when the source/output hashes and render/font/settings identity exactly match and coverage/resolution are sufficient. Reuse of the existing JPEG package alone is insufficient for geometry checks. Avoid a new persistent geometry cache in v2; keep geometry job-private and allow duplicate asynchronous previews initially if extending persistence would delay the direct path.

## Resource budgets and performance experiment

Planning targets, not measured guarantees: standard incremental fit work on the pilot should aim for a warm-run median below 5 s for the one-page resume and below 10 s for the 13-slide deck. Measure separately from translation; record cold font loading too. These are release investigation thresholds, not permission to omit required placement/integrity checks.

Thorough budget: one source render, one candidate render, at most one repair batch and one final render. Reuse the existing 120 s per-conversion timeout, with a 360 s overall optional-work deadline checked before and during subprocess work. Default to at most 50 pages of geometric/render analysis and existing raster size limits; larger documents are explicitly partial, never silently complete. Limit checks to the requested budget in deterministic page order. No uncapped per-page repair loop, per-candidate Office conversion or automatic retry after a deadline.

One Office conversion at a time per worker renderer; never share a live LibreOffice profile concurrently between fit and preview work. Thorough fit and preview work use a shared bounded conversion slot, with fit ahead of queued previews; do not interrupt a running preview. Slot wait counts against the optional deadline and is measured separately. No extra daemon or queue service is needed.

Benchmark the three modes: current v1, v2 standard, v2 thorough. Freeze translated strings from recorded results to isolate layout cost, then run representative end-to-end translations with the existing engines. Start with five warm repetitions and two cold runs per representative case; report individual samples, median and range, not a statistically unsupported p95. Include file bytes, page/shape counts, renderer/fonts, hardware, concurrency and peak memory. Expand repetitions only when variability prevents a decision. Test preview contention separately. If budgets are missed, retain explicit opt-in thorough behavior and record the evidence; do not silently weaken checks or invent speed claims.

## Delivery tasks and gates

| Task | Work | Completion gate |
|---|---|---|
| OF0 evidence and contract validation | Reproduce native-visible deck/resume failures; create synthetic fixtures; inspect Word constrained examples; test exported text/object correspondence and measure renderer cost. No production repair changes. | Recorded baseline and a bounded renderer capability matrix. Architect resolves correspondence/coverage details and updates this spec and Architecture before OF4 coding. ADR-026 acceptance precedes policy changes. |
| OF1 fonts and independent measurement | Fix source/target coupling, serialize target fallback, report certainty and pin identity. | Slide 6 English target is measured despite Chinese-source uncertainty; matching output font coverage; missing-font cases remain honest. |
| OF2 PDF structure/placement | Paragraph roles, right anchors, conservative obstacles, shared region reservations and typed no-fit failure. | Resume structure and dates preserved in saved render; impossible fixture fails without corrupted/partial publication; no loss of translated/protected content. |
| OF3 standard Office repairs | Bounded PPTX candidates; DOCX constrained support/uncertainty; saved-file geometry checks. | Native inspection of slides 4-6 shows no new collisions; no unrelated layout edits; Word reflows correctly and unsupported cases are explicit. |
| OF4 thorough verification | Reuse existing conversion; temporary PDF geometry; correspondence, bounded repair and final verification. | Each supported detector finds seeded defects, controls stay clean, partial/unavailable/deadline cases are honest and preserve valid results. |
| OF5 integration and acceptance | CLI/API options, reports, cache identity, skip/races, performance and documentation. | All required repository checks, native acceptance and latency evidence; standard downloads never wait for Office previews. |

OF1 and OF2 can be implemented as separate small changes after acceptance; OF3 depends on OF1; OF4 depends on the OF0 renderer gate and OF1-OF3. Do not delegate unresolved architectural choices to coders. The owner approved these tasks through the implementation request; none is complete merely by appearing here.

## Tests and completion criteria

Start bug fixes with the owner-visible reproduction, not a synthetic estimator assertion alone. Store private evidence in ignored data; committed synthetic fixtures must remain independently reproducible.

Required cases:

- Segoe UI Chinese source with measurable English target; target CJK fallback present/absent; mixed scripts, bold/italic and protected strings; cold/warm font resolution.
- Original-to-Chinese-to-English deck run with preserved breaks; inherited styles, groups, rotated text, tables, narrow gaps and two boxes competing for free space; candidate rollback and deterministic ordering.
- Resume-style right columns; dense baselines whose font boxes overlap; headings adjoining body text; project title/technology rows; multiple columns; bullet continuations; intentional source overlaps.
- PDF floor reached, insufficient page space, failed trial placement and skip during placement: no dropped text, below-floor rescue or colliding successful result.
- DOCX Latin/CJK fixed cells, text boxes, grid snapping, floating objects, headers/footers, explicit page breaks and ordinary body expansion to additional pages; no attempt to restore original page count.
- Render text ambiguity, missing renderer/fonts, truncated page budget, timeout, crash, skip during conversion, cancellation before publication and mismatched final candidate/report.
- Standard/thorough cache separation, renderer version changes, old report decoding, incomplete thorough not reused, owner boundaries, immutable downloads and preview concurrency.
- Existing TXT/XLSX preservation and skip behavior remain intact.

Acceptance requires all known confirmed collisions in the supported owner examples fixed or explicitly rejected as unplaceable, zero lost/protected text regressions, zero new confirmed collisions in the acceptance corpus, and no detector falsely labelling a known unsupported case as verified. Record unnecessary shrink and false positives against clean controls, not only defects fixed. Visually inspect native PowerPoint/Word output as acceptance evidence; production does not depend on Office automation. Sample renders cannot establish a document-wide guarantee outside measured coverage.

Run from the root: `uv sync --all-packages`, `uv run ruff format --check`, `uv run ruff check`, `uv run pyright`, `uv run lint-imports`, `uv run pytest`. For implementation acceptance, run the existing LibreOffice render tests with `DOCTRANSLATOR_TEST_REQUIRE_LIBREOFFICE=1` in the prepared test environment. Real backend tests use the repository's explicit integration configuration; do not change translation prompts/models or resume deferred COMET work for this fit task.

At implementation completion, synchronize Architecture, README visual-quality requirements, P3/P4 follow-on references, deployment font/render requirements and release evidence. Never mark historical v1 evidence as proof of v2 behavior.

## Implementation evidence, 2026-09-29

The owner-authorized implementation retains the existing adapters and engine calls. Standard is the default in the core, CLI and API. Thorough is explicit through `FitOptions(mode="thorough")`, `--fit-mode thorough`, or API `fit.mode`. Published artifacts stay immutable. No browser controls or model-assisted editing were added.

OF0 resolved rendered scope to anchored container/page text-footprint overflow and text-to-text collisions. It does not prove glyph visibility, detect missing text from failed correspondence, or inspect artwork collisions. DOCX has no validated paginated anchors in this implementation and reports partial thorough coverage. Existing constrained-cell/box measurement remains active, and ordinary Word body text is not shrunk to restore page count.

Private owner documents and exports remain under ignored `data/`; they are not repository fixtures:

| Evidence | Result and limit |
|---|---|
| `data/experiments/offline-fit-v2/office-replay.json`, `deck-v2-final.pptx`, `slide-final-{4,5,6}.png` | Replayed the recorded English outputs against the Chinese intermediate deck. Saved output reopened, then exported with native PowerPoint. Previously colliding text on slides 4-6 is readable without the reproduced overlaps. Missing source CJK metrics remain unresolved evidence even when target fitting succeeds. |
| `data/experiments/offline-fit-v2/office-timings.json` | Five fit-loop samples for the 13-slide deck, with reused font library and concurrent development/checks. The tightened-geometry samples were 1.983, 2.979, 1.809, 3.265, 1.743 s; the final style-policy replay under full-suite contention measured 5.58, 5.94, 5.14, 3.80, 4.20 s. These are not total translation latency or a percentile guarantee. Parsing, manifest creation, writing and native export are excluded. |
| `data/experiments/offline-fit-v2/render-probe.json` | One owner-deck LibreOffice conversion took 69.335 s. This confirms that thorough mode must remain opt-in; it is not evidence for a few-second Office render. |
| `data/experiments/offline-fit-v2/anchored-deck-probe.json` | 119 of 122 units uniquely mapped across 13 slides; geometry analysis took 1.792 s. Three units remain unknown. A same-file comparison produced only source-present findings, not new defects. |
| `data/fit-diagnosis/resume-v2-right-column-replay.{pdf,png,json}` | Exact historical Chinese wording for all 12 date/location units replayed against the original resume; other wording stayed English. Saved/reopened and visually inspected: right anchors retained, no observed date/location wrapping or collisions. Latest extraction has 58 units, joining clear producer-block continuations while preserving project/technology/skills rows. |
| Resume placement samples | 1.048, 0.859, 0.526, 0.550, 0.542 s; median 0.550 s. One page, 7,090-byte source, PyMuPDF 1.28.2, built-in CJK font, Windows 11 / Intel Family 6 Model 170. Concurrent checks were active; these are not isolated performance acceptance measurements. |

The earlier all-CJK synthetic resume replay validates placement mechanics but is not historical translation acceptance. A full exact replay of the historical resume remains unverified because its merged output paragraphs cannot be mapped unambiguously to the corrected units. No missing wording was invented. Broader native Word pagination and cross-language corpus acceptance remains follow-up evidence, not a claim established by these two owner examples.

Regression coverage includes independent source/target measurement, serialized target fallback and exact style uncertainty, bounded growth/clearance and unchanged neighbours, stale patch rejection, skip rollback, PDF transactional trial failure, right anchors and paragraph roles, render ambiguity/budgets/cancellation, repair acceptance/rollback, old report decoding, mode/renderer fingerprint separation and exclusion of unresolved thorough results from reuse. Standard unresolved reuse remains unchanged; thorough unresolved reuse is deliberately conservative even when some checks completed.

Office adjusted/unresolved entries record applied operations, before/after bounds/fonts/spacing and font-resolution/measurement/repair timings. PDF retains aggregate placement timing and thorough sessions separate render/queue/verification timings. Final repository checks: `uv sync --all-packages`, `uv run ruff format --check` (173 files), `uv run ruff check`, `uv run pyright` (zero errors), `uv run lint-imports` (14 contracts kept), and `uv run pytest` all passed. The full run used `DOCTRANSLATOR_TEST_REQUIRE_LIBREOFFICE=1`: 402 passed, two integration tests deselected, 675.31 s. A final collision-enumeration regression added after collection passed in the full 14-test detector suite; the CLI PDF test was strengthened to request thorough mode and passed separately. The two backend integration tests were not run; no translation prompt/model change is part of this work. This evidence does not close or change the historical P3/P4/P7 board states.
