# ADR-012 - Lightweight Best-Effort Fit

> Website amendment under ADR-028: one fixed standard fit profile replaces personal website fit/skip controls for shared cached work. Core fitting and existing explicit API/local desktop behavior remain; advanced personal fit choices are local-desktop-only in the new product flow. This specification is not implemented yet.

> Amended by accepted [ADR-026](ADR-026-offline-fit-v2.md), 2026-09-29: structure-aware standard fit, explicit thorough verification, and safe complete PDF placement. Conflicting earlier fit/placement requirements below are historical.

> Superseded in part on 2026-09-29 by [ADR-014](ADR-014-storage-ownership-and-retranslation.md): local exports always translate fresh with temporary working storage; hosted owners retain one current result per document/language pair, with owner-scoped reuse and immutable job results. Human and application service accounts are owners. Earlier global-cache, mandatory version-history, desktop-library and conflicting retention requirements below are historical; ADR-014 takes precedence. Fit skip remains supported, but no separate old full-fit cache is retained.


Status: Accepted by owner on 2026-09-28; implementation reconciliation pending.

## Owner amendment - Simple display and user skip (2026-09-28)

The owner's latest instruction supersedes earlier requirements to expose unresolved locations/warnings in the normal UI or to require every successful document to finish fit checking.

- Run lightweight fit by default. During that stage show only **Checking layout** and **Skip layout check**, with no container counts, unresolved-section list or layout-warning badge. On successful publication show **Ready to download**.
- Skip stops further optional fit work at a safe checkpoint, preserves all translated text and already-applied adjustments, and continues writing/verifying/storing the document. It does not cancel the job, retranslate, roll back completed adjustments or make an unfinished file downloadable. The current native measurement may finish before the request takes effect.
- Persist the user's skip request on the existing job so disconnect/retry does not lose it. Record an effective bypass as `fit_status=skipped`, distinct from `not_applicable`, a successful fit and the old `not_run` scaffold state. Existing technical diagnostics may remain for troubleshooting; do not add or expand per-section reporting as a release requirement.
- Save skipped outputs as normal owned downloadable documents, but do not insert or replace the reusable full-fit cache entry. A fully fitted cached result remains usable. Normal completed fit with unresolved internal findings still follows ADR-007.
- Skipping optional fit never skips required file construction, complete text placement, integrity verification, ownership checks or persistence. This also applies to PDF when placement and optional fitting share a writer.

The [progress/skip implementation plan](../plans/P5-P6-document-progress.md#skip-layout-check) owns the button, endpoint, cooperative checkpoints and race tests. This amendment accepts product behavior, not a claim that the control exists yet. Where the original decision below requires visible warnings or exhaustive per-location reporting, this amendment takes precedence.

## Context

The owner prioritizes translation quality and accuracy, fast processing and minimal fit work. Earlier absolute visual guarantees and broad native-layout comparisons encouraged an expanding Office measurement experiment. This decision supersedes those fit requirements in README, Architecture and P3/P3.0. ADR-003 component boundaries and ADR-007 caching of complete results with unresolved fit findings remain unchanged.

## Options Considered

- Exhaustive native parity: rejected for this milestone; it expands layout research without directly improving translation accuracy.
- No fit assessment: rejected; obvious constrained overflow and honest diagnostics are still required.
- Lightweight best-effort fit: accepted; reuse current work, bound adjustments and expose uncertainty.

## Decision

- Fit is a lightweight overflow safeguard, not a native-rendering or visual-quality guarantee. Preserve translated wording, rich formatting, protected content and file structure. Never retranslate, summarize, truncate or paraphrase to fit.
- Preserve normal reflow and existing layout behavior. Inspect only changed constrained text containers. DOCX body and PPTX notes have no invented fixed bounds; TXT has no fit work.
- Retain the existing shared fitter, font manifest and adapters where useful. Use provisioned fonts, shaping and bounded wrapping for supported layouts. No production Office/LibreOffice rendering loop, vision calls, external font downloads or replacement layout engine is required.
- Missing fonts/glyphs, uncertain geometry or unvalidated layout behavior retain original sizes and produce explicit unresolved diagnostics. Required container families must be accounted for; unsupported measurement is not an empty document or a pass.
- Compare source and translation using the same estimator. Allowed extent is the larger of source extent and bounds per constrained axis. Preserve source overflow. Do not move objects, change row/column dimensions or force pagination to hide failures.
- Retain current defaults: 70% relative floor, 8pt absolute floor, 2.5% scale steps, half-point size quantization and 1pt tolerance. Scale rich runs proportionally subject to their individual floors; never enlarge or further shrink a run originally at/below the absolute minimum. Bound search to at most 40 candidate measurements per container, stop on first fit or no further size change, and reuse duplicate candidates. These are estimator defaults, not native-accuracy claims.
- At a reliably measured floor overflow, keep floor sizes and report unresolved. On measurement uncertainty or a search cap reached before a reliable floor result, retain original sizes and report the reason. A measured pass means only that the supported estimator found no excess.
- Return the same versioned report through CLI/API/UI and cache it with the output. Include policy/estimator/font identity in the fingerprint. Unresolved fit may accompany a successful download; missing text, corrupt files and lost protected content remain failures.

## Per-format scope

| Format | Minimum fit responsibility |
|---|---|
| TXT | Not applicable. |
| PPTX | Changed constrained shapes, placeholders and table cells; preserve geometry. |
| DOCX | Constrained boxes/cells only; body and unconstrained dimensions reflow naturally. |
| XLSX | Changed constrained cell text with wrap/merge awareness; preserve sheet names, formulas and row/column geometry. |
| PDF | Fit replacement text during placement using the selected writer's layout facilities where available; avoid a duplicate independent layout engine. |

## Validation and stop line

Close the current experiment with existing evidence, unsupported cases and limitations. Do not chase exact line-count/pitch parity, tune font-specific multipliers indefinitely or promote rules inferred from one fixture set into universal Office behavior. This ADR does not endorse experimental hhea/1.3 multiplier claims.

Freeze a small corpus: one representative document per Office format containing ordinary growth, constrained overflow, rich runs and reflow controls as applicable; cover Latin/CJK, merged XLSX cells and missing fonts across it. Use two PDFs in P4 (ordinary text and mixed artwork/text). Existing fixtures can satisfy this corpus. Native open/visual spot checks are acceptance activities, not runtime dependencies. Add cases only for concrete preservation, false-pass, excessive-shrink or content-loss defects; defer cosmetic differences.

Record obvious clipping incorrectly reported as passed, unnecessary shrink, unchanged source hashes, preserved text/structure and fit timing separately from translation timing. Do not build render infrastructure or microbenchmarks just to prove speed. Known unreliable layouts become unresolved until validated. Policy tests cover floors, source overflow, missing measurement, bounded iterations and reports.

Completion requires real fit integration for all required formats, honest outcomes and bounded acceptance evidence, not every container passing. An entire format must not become an unresolved-only stub. P7 remains later optional visual review/editing; service ownership/cache/persistence and P6 scope are unchanged.

## Consequences

The release may return readable translations with unresolved layout warnings and cannot promise native visual parity. Translation preservation remains mandatory. Existing experimental code must be reconciled with this policy before claiming P3 complete; recording the decision is not implementation or test evidence.
