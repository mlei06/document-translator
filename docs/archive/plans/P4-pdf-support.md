# P4 - PDF Design and Implementation

> Historical plan. Retained for rationale and evidence, not current implementation instructions. Follow the [current specification](../../plans/unified-translator-design.md) and [execution checklist](../../plans/unified-execution.md).

Accepted follow-on (2026-09-29): [Offline fit v2](offline-fit-v2.md) and [ADR-026](../../decisions/ADR-026-offline-fit-v2.md) amend PDF extraction, right anchors and safe placement. See that plan for implementation evidence; historical phase/board state below is unchanged.

Status: Execution plan for the pre-GUI handoff; the PDF strategy must be validated and recorded before production implementation. Parent: Feature #9012.

Progress (2026-09-29): P4.0 closed with [ADR-018](../../decisions/ADR-018-pdf-strategy.md) and the [strategy experiment](../../experiments/pdf-strategy/README.md); P4.1-P4.3 implemented (`formats/pdf`, pipeline `PlacementFit`/`verify_output`, CLI; tests in `packages/core/tests/test_format_pdf.py` and the CLI suite); P4.4 local acceptance with both engines and an independent PDFium check recorded in the experiment report. Remaining for closure: reviewed-commit CI (branch not pushed) and service acceptance with PDF (P5).

## Scope and Dependencies

P2 core and P3 measurement/fit contracts are complete. Translate extractable text in text-based PDF through both engines; preserve page size, artwork and reading content, write PDF and run fit on all supported text blocks. No OCR. Scanned/image-only content must be explicitly reported, not falsely counted as translated.

Fit scope follows [ADR-012](../../decisions/ADR-012-lightweight-fit-policy.md): use the selected PDF writer's placement/layout facilities where available, with bounded shrinking and explicit uncertainty. Do not add a second independent layout engine or render/vision correction loop. Never shorten translations for fit. Use ADR-012's two-document fit corpus; the structural/source-removal tests below remain required because they protect document integrity.

## P4.0 Strategy Gate

Work as architect first. Use synthetic PDF fixtures for Chinese/English/Japanese/Spanish, embedded/subset fonts, columns, mixed styles, tables, rotations, transparency, text over vector/image artwork, ligatures and scanned/mixed pages.

Start with targeted PDF text replacement retaining artwork. Demonstrate source-text removal and background preservation. Compare reconstruction through an editable intermediate only if this direct path exposes a concrete blocker. A white rectangle overlay that hides artwork or leaves searchable original text underneath is not acceptable. Do not apply broad redactions that erase adjacent graphics.

Record in a PDF-strategy ADR: extraction/reading-order rules, span/block segmentation, font embedding and licensing, text removal/reinsertion method, graphics preservation, supported rotations/writing modes, unsupported-construct behavior and comparison evidence. Validate the candidate library on the repository's Python/OS combination and review deployment licensing before pinning it. PyMuPDF is anticipated by ADR-003, not a prevalidated algorithm.

If neither candidate meets required fidelity, record the failing cases and escalate the concrete scope/strategy conflict. Do not ship an untested universal conversion pipeline or silently drop blocks. Native visual comparisons and output text extraction are both necessary: a screenshot alone cannot detect retained hidden source text.

## Production Contract After the Gate

- `formats/pdf/adapter.py` owns extraction, stable page/block/span locations and PDF-specific writeback; `layout.py` owns coordinate normalization and applying fit changes. Engine and generic fit code never import it.
- Preserve an immutable original baseline with page dimensions/crop/rotation, original text extents and supported font metrics. Map PDF coordinates to the common point-based container description and back with round-trip tests.
- Group text into meaningful translation units without joining unrelated columns/cells. Retain inline emphasis; apply P2's selected formatting strategy.
- Protect non-text artwork and links/annotations that are in the preservation contract. Preserve untouched pages; changed pages must retain required semantic structures. The strategy ADR must enumerate rejection cases before implementation.
- Use P3's original-relative fit policy; fallback font substitution must be deterministic, disclosed and fingerprinted. Missing glyphs are unresolved or a typed failure, never blank success.
- For mixed scanned/text pages, preserve image content and emit an untranslated-image-content diagnostic. For a PDF with no extractable translatable text, return a typed `no_extractable_text` outcome rather than claim translated success. No OCR fallback.
- Signed/encrypted/unsupported PDFs are rejected before translation unless an explicit supported policy is validated; do not invalidate signatures silently or ask for passwords in logs.
- Write to temporary output, reopen and validate page count/dimensions, text presence/target script and required structure, then publish atomically. Input remains byte-identical.
- Output fingerprint includes PDF strategy/version, fonts and every output-affecting option.

## Bounded Tasks

| Task | Files | Evidence |
|------|-------|----------|
| P4.0 strategy | experiment/report, ADR, Architecture | Candidate comparison and accepted exact extraction/writeback contract |
| P4.1 extraction/locations | PDF adapter, fixtures/tests | Every required text block accounted for, multi-column/rotated tests |
| P4.2 layout/writeback | PDF layout and adapter | Original baseline, source removal, preserved artwork, correct new glyphs |
| P4.3 integration | registry, pipeline, CLI, identity/report | Both engines, normal/failed/cancelled output, consistent fit results |
| P4.4 acceptance | E2E/native evidence/docs | CLI supports all five formats; all required checks and CI |

## Completion Criteria

- Target-language PDF in both modes with no native-open error, accidental duplicate/hidden source layer or missing artwork on required fixtures.
- Original-relative fit/report verified on supported blocks, including growth beyond floor and missing-font behavior.
- Every extracted text block is translated, intentionally protected or explicitly rejected/reported under the approved coverage contract.
- PDF CLI and public API agree; source remains unchanged; cancellation/failed writes publish no output.
- Record native-view application/font versions, representative source/output views and structural/text extraction comparisons in the release evidence. A library reopen alone is insufficient.
- Six root checks and reviewed-commit CI pass. Service acceptance with PDF is required before the pre-GUI milestone, even if P5 implementation began earlier.
