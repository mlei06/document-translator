# ADR-009: XLSX Preservation and Sheet Names

## Status

Writer/recalculation decision proposed (2026-09-27), not implemented. The owner explicitly approved preserving sheet names and translating cell text for this release. That product requirement is settled; the native recalculation evidence and final writer contract still require architect validation.

## Context

P2 must translate cell text while preserving sheet names, formulas, numbers, dates and formatting. The owner amended the earlier requirement to translate sheet names after reviewing the reference-preservation risk. The completed [experiment](../experiments/xlsx-roundtrip/README.md) found that openpyxl 3.1.5 load/save removes a drawing text box and clears formula caches in the synthetic fixture. Direct text-part edits preserve those features, but neither writer automatically makes referenced sheet renames safe.

The current architecture permits shared OOXML helpers and confines format knowledge to `formats/xlsx/` (ADR-003). It names openpyxl as a contained dependency; it does not require every workbook to be serialized through it. No production XLSX implementation exists.

## Options Considered

1. **Full openpyxl load/save.** Convenient object model; fails the demonstrated preservation cases even with rich-text loading enabled.
2. **Targeted OOXML edits.** Preserve all untouched ZIP entry payloads, selectively change supported text-bearing nodes, and use a format reader to verify output. Requires explicit handling of shared/inline strings and package relationships. Recommended.
3. **Native Excel automation.** Potentially handles more dependencies, but adds a desktop/Windows runtime requirement to the shared core and does not fit the accepted portable server direction. Native Excel remains valuable for acceptance testing.

Sheet-name choices:

- Rename without reference repair: rejected; creates stale references.
- Rewrite formula and other reference text: conflicts with the literal no-formula-change requirement and needs a complete reference strategy, including names, charts, validation, hyperlinks, external references and dynamic references such as `INDIRECT`.
- Preserve original names: selected by the owner for this release. A safe optional subset was considered but is deferred.

## Proposed Decision

Use ZIP-part copying and namespace-preserving XML edits for XLSX. The production writer uses `zipfile` and securely configured lxml; workbook semantics live in `formats/xlsx/`, while package/XML primitives live in `formats/_ooxml/`. openpyxl may be a test oracle or a read-only helper confined to the XLSX package; it is not the production save path. Add import protection when a production dependency first appears, without relaxing existing contracts.

Read workbook/worksheet relationships rather than assume filenames or sheet order. Extract only literal string cells (`s` and `inlineStr`), resolving shared entries once and retaining all cell locations. Formula cells, including string-valued formula caches, are never translation segments. Preserve run properties, styles, whitespace semantics, formulas, numeric/date/boolean values, package relationships and unsupported untouched content. A translation beginning with `=` stays a string. Do not flatten rich text.

Copy untouched entry payloads byte-identically, including drawings and extension parts. Serialize only changed XML parts without dropping namespace declarations used in attribute values such as `mc:Ignorable`. Never extract arbitrary archive paths to disk. Reject malformed/duplicate paths, encrypted or signed packages, unsupported namespaces in text that must be edited, unsupported package containers and resource-limit violations with explicit errors; never call a lossy library save as a fallback. An unknown untouched part is copied, not rejected merely because the adapter does not interpret it.

**Owner-approved sheet-name contract:** preserve every sheet name, including hidden sheets. Do not expose a rename option in this release. Translate literal cell text; preserve formula expressions, numeric/date/boolean values and formatting. Optional safe renaming and general reference rewriting are deferred and must not be implemented from the earlier proposal. The README now reflects this choice.

**Calculation contract remains a design gate:** translating a label used by formulas can change calculation results without changing formula text. The write-strategy experiment establishes cache preservation, not cache correctness after translation. P2.0 must test recalculation in a native engine and decide how to request recalculation without executing external links/macros or claiming that the core computes formulas. Finalize that part of this ADR before implementing the XLSX writer.

## Consequences

- Preserving the package is the default. Features outside the translation scope survive unchanged rather than being reconstructed by an incomplete object model.
- P2 needs package-diff and native-application acceptance fixtures. Reopening with openpyxl alone cannot prove fidelity.
- The preserved-name policy must be reflected in README, tests and the versioned output identity. No unused rename option belongs in public options or the CLI.
- Formula-aware tab translation is not smuggled into a generic XML helper. If later approved, it belongs to the XLSX adapter and needs its own correctness tests.
- P3 can modify only the additional style/layout nodes its accepted fit contract requires. It must retain P2's preservation guarantees.
- PPTX/DOCX writer choices require their own round-trip evidence; this experiment is not proof about those libraries.
