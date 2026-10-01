# P3 - Fit Check Implementation

> Historical plan. Retained for rationale and evidence, not current implementation instructions. Follow the [current specification](../../plans/unified-translator-design.md) and [execution checklist](../../plans/unified-execution.md).

Accepted follow-on (2026-09-29): [Offline fit v2](offline-fit-v2.md) and [ADR-026](../../decisions/ADR-026-offline-fit-v2.md) amend fitting and placement policy. See that plan for implementation evidence; historical phase/board state below is unchanged.

Status: Revised 2026-09-28 for owner-approved lightweight best-effort fitting. Parent: Feature #9011. [ADR-012](../../decisions/ADR-012-lightweight-fit-policy.md) is authoritative.

Progress (2026-09-28): fit is integrated for PPTX, DOCX and XLSX with saved-output verification, the policy/unsupported/search-limit tests, the synthetic-font corpus and a real-engine run with native spot checks; see the [closure report](../../experiments/fit-measurement/README.md). Remaining for phase closure: reviewed-commit CI (branch not pushed) and the service-level R11 evidence. PDF fit arrives with P4.

## Dependencies and Entry Gate

Preserve P2 formatting, completeness and file-integrity guarantees. Close current measurement research through [P3.0](P3.0-fit-design-validation.md); do not restart engine selection or seek exhaustive native parity. Reuse the fitter/adapters.

Use ADR-012 defaults: 70%/8pt floors, 2.5% steps, half-point quantization, 1pt tolerance. At most 40 candidate measurements per container; stop on first fit/floor/no size change and reuse duplicate candidates. Cache font metrics within a run. Skip unchanged text/unconstrained content. No rendering, model calls or wording changes for fit.

## Responsibilities and Interfaces

- `document.py`: immutable source-container baseline and normalized translated-container description. Points are the geometry unit. Retain content box, padding, rotation, wrap settings, resolved fonts, paragraph spacing/bullets and ordered rich runs. A container may hold multiple paragraph segments.
- `formats/base.py`: separate `LayoutSupport` capability. Exact signatures chosen at the entry gate must describe original/current containers and apply explicit size changes by stable ID.
- `fit/fonts.py`: resolve from an explicit provisioned font manifest, record font-file hashes and fallback mapping. No runtime external font downloads. Missing glyphs and unsupported shaping produce `unmeasurable` diagnostics, not invented dimensions.
- `fit/measure.py`: return measured extents and supported/unsupported diagnostics using the supported lightweight estimator. Never import format packages.
- `fit/fitter.py`: compare and choose scale using format-neutral descriptions only. Formats interpret coordinates and write the chosen sizes.
- `pipeline.py`: measure and preserve originals before replacing text; translate/apply; fit; apply size changes; write/reopen; return report. Callback cancellation remains safe before final publication.

## Algorithm Contract

1. Resolve the original effective fonts and geometry, including inherited properties. Measure original extents with the same engine/environment as translated extents.
2. Compare in each container's local coordinates; permitted extent per constrained axis is the larger of original extent and content bounds. Unsupported geometry must be explicit rather than extending the estimator to emulate every native rule.
3. Measure translation at preserved sizes. Keep sizes if it fits. Never repair existing overflow or change positions, row/column sizes or pagination merely to hide a fit failure.
4. For overflow, apply a common scale to the container's rich runs, respecting the selected per-run floor. Bound iterations and validate the final chosen size by measurement; do not assume discrete line wrapping is perfectly monotonic.
5. If no allowed size fits, retain the floor and record unresolved overflow. If measurement is unavailable, retain original sizes and record unresolved measurement. Never mark that container passed.
6. Apply changes through the adapter. Re-measure serialized/reopened effective styles on representative fixtures, especially shared XLSX styles. A change must not resize unrelated containers.

ADR-012 pins defaults and the stopping rule; unknown measurement retains original sizes and is unresolved. Every run records its measurement strategy and font manifest identity.

## Report and Result Contract

The accepted ADR-012 owner amendment takes precedence: normal UI shows only **Checking layout** and **Skip layout check**. Existing technical diagnostics may remain; expanding per-container reports or building a report viewer is not release work. Implement the cooperative skip contract in [the progress plan](P5-P6-document-progress.md#skip-layout-check): preserve translations and prior adjustments, stop remaining optional fit, then write, verify and persist.

Versioned report includes document format, measurement version, font manifest digest, options and counts for inspected/unchanged/adjusted/unresolved containers. Each adjustment/unresolved entry includes stable location, reason, original/final run sizes, original/translated/final extents and allowed extent where measurable. Do not embed full confidential text in ordinary reports/logs.

Document `fit_status`: `not_applicable` for TXT or documents with no applicable containers, `passed` when all inspected containers fit without changes, `adjusted` when changes resolve all issues, `unresolved` if any issue remains. `skipped` records a user-requested bypass actually observed by the worker and is a valid successful owned result, excluded from normal reusable fit-result cache. Do not fabricate unresolved entries for unvisited containers. `not_run` exists only for intermediate P2 development and is unacceptable for final service success. Unknown measurement values are null with a reason, not zero.

## Bounded Tasks

| Task | Location | Acceptance |
|------|----------|------------|
| P3.1 contracts/fonts/measurement | core types, document, fit modules | Small fixed corpus, mixed scripts/missing fonts; deterministic identity |
| P3.2 generic algorithm | fitter and tests | Original-overflow, floor, unsupported and iteration-bound cases |
| P3.3 Office layout capabilities | format-specific layout modules | PPTX text containers, DOCX fixed elements and XLSX clipping; no generic format imports |
| P3.4 pipeline/CLI/report | pipeline, public types, CLI | Automatic fit, JSON report, cancellation cleanup, fingerprint invalidates P2 output |
| P3.5 acceptance | fixtures, E2E, docs | Both engines, representative native-open/visual spot checks, required checks and CI |

## Completion Criteria

- Required container families are discovered and supported or explicitly unresolved. No entire required format is an unresolved-only stub. DOCX body and PPTX notes have no invented bounds.
- TXT explicitly bypasses fit. Original files unchanged. No required container silently skipped; an explicit user bypass is recorded as `skipped`.
- Retain existing technical reporting of performed adjustments and unresolved measurements; no expanded per-area reporting or user-facing warning view is required. Cache identity includes font/layout/fitter versions and options.
- ADR-012 small corpus covers ordinary paths, growth, floors, Latin/CJK, rich runs, merged cells, missing fonts and reflow controls. Unsupported complex layout is unresolved; exact line/pitch parity is not a gate.
- Saved outputs preserve content/structure; check false passes and unnecessary shrink, and record fit timing. No production renderer/vision/model calls or rewriting for fit.
- All six checks and reviewed-commit CI pass. Record evidence under the pre-GUI release matrix; close P3 only when its actual criteria pass.

PDF is added in P4 using this contract; general visual redesign and agent edits stay in P7.

A missing layout capability for a required format is unresolved, never not_applicable. Passed/adjusted are estimator outcomes, not rendered verification claims. Unchanged containers need no measurement; unknown geometry/fonts on changed applicable containers must not be silently skipped.
