# P3 - Fit Check Implementation

Status: Execution plan for the pre-GUI handoff; production measurement choice remains gated by [P3.0](P3.0-fit-design-validation.md). Parent: Feature #9011.

## Dependencies and Entry Gate

P2 document adapters/public result API pass their acceptance tests. Complete P3.0 before implementing `fit/measure.py`: accepted font/measurement ADR, tested installation on the selected Python/Windows environment, native comparisons, exact coordinate and font-resolution interfaces. Do not choose character-count estimation as a substitute.

The architect records defaults and numerical tolerances in Architecture and the ADR. Candidate release policy is a 70% relative floor and 8-point absolute floor, with proportional mixed-run scaling and deterministic bounded search; verify on the fixture corpus before accepting. Never enlarge a source run already below the absolute floor. If evidence requires different defaults, record them before coding and include them in the fingerprint.

## Responsibilities and Interfaces

- `document.py`: immutable source-container baseline and normalized translated-container description. Points are the geometry unit. Retain content box, padding, rotation, wrap settings, resolved fonts, paragraph spacing/bullets and ordered rich runs. A container may hold multiple paragraph segments.
- `formats/base.py`: separate `LayoutSupport` capability. Exact signatures chosen at the entry gate must describe original/current containers and apply explicit size changes by stable ID.
- `fit/fonts.py`: resolve from an explicit provisioned font manifest, record font-file hashes and fallback mapping. No runtime external font downloads. Missing glyphs and unsupported shaping produce `unmeasurable` diagnostics, not invented dimensions.
- `fit/measure.py`: return measured extents and supported/unsupported diagnostics using the accepted layout engine. Never import format packages.
- `fit/fitter.py`: compare and choose scale using format-neutral descriptions only. Formats interpret coordinates and write the chosen sizes.
- `pipeline.py`: measure and preserve originals before replacing text; translate/apply; fit; apply size changes; write/reopen; return report. Callback cancellation remains safe before final publication.

## Algorithm Contract

1. Resolve the original effective fonts and geometry, including inherited properties. Measure original extents with the same engine/environment as translated extents.
2. Compare in each container's local coordinates; permitted extent per constrained axis is the larger of original extent and content bounds. The measurement ADR must define how rotation, clipping and one-axis constraints are represented.
3. Measure translation at preserved sizes. Keep sizes if it fits. Never repair existing overflow or change positions, row/column sizes or pagination merely to hide a fit failure.
4. For overflow, apply a common scale to the container's rich runs, respecting the selected per-run floor. Bound iterations and validate the final chosen size by measurement; do not assume discrete line wrapping is perfectly monotonic.
5. If no allowed size fits, retain the floor and record unresolved overflow. If measurement is unavailable, retain original sizes and record unresolved measurement. Never mark that container passed.
6. Apply changes through the adapter. Re-measure serialized/reopened effective styles on representative fixtures, especially shared XLSX styles. A change must not resize unrelated containers.

Exact shrink increments/search tolerance and line-box comparison are entry-gate outputs, not coder choices. Every run records its measurement strategy and font manifest identity.

## Report and Result Contract

Versioned report includes document format, measurement version, font manifest digest, options and counts for inspected/unchanged/adjusted/unresolved containers. Each adjustment/unresolved entry includes stable location, reason, original/final run sizes, original/translated/final extents and allowed extent where measurable. Do not embed full confidential text in ordinary reports/logs.

Document `fit_status`: `not_applicable` for TXT or documents with no applicable containers, `passed` when all inspected containers fit without changes, `adjusted` when changes resolve all issues, `unresolved` if any issue remains. `not_run` exists only for intermediate P2 development and is unacceptable for final service success. Unknown measurement values are null with a reason, not zero.

## Bounded Tasks

| Task | Location | Acceptance |
|------|----------|------------|
| P3.1 contracts/fonts/measurement | core types, document, fit modules | Native comparison corpus, mixed scripts and missing fonts; deterministic identity |
| P3.2 generic algorithm | fitter and tests | Original-overflow, floor, unsupported and iteration-bound cases |
| P3.3 Office layout capabilities | format-specific layout modules | PPTX text containers, DOCX fixed elements and XLSX clipping; no generic format imports |
| P3.4 pipeline/CLI/report | pipeline, public types, CLI | Automatic fit, JSON report, cancellation cleanup, fingerprint invalidates P2 output |
| P3.5 acceptance | fixtures, E2E, docs | Both engines, real fonts/native renders, required checks and CI |

## Completion Criteria

- All README fixed-container scopes covered; DOCX body and PPTX notes do not get invented fixed bounds.
- TXT explicitly bypasses fit. Original files unchanged. No required container silently skipped.
- Report identifies every adjustment and unresolved measurement/overflow. Cache identity includes font/layout/fitter versions and options.
- Native comparison covers CJK/Latin, rich runs, wrapping, bullets, grouped/rotated shapes, table cells, merged spreadsheet cells and source overflow.
- All six checks and reviewed-commit CI pass. Record evidence under the pre-GUI release matrix; close P3 only when its actual criteria pass.

PDF is added in P4 using this contract; general visual redesign and agent edits stay in P7.
