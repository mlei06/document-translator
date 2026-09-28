# ADR-009: XLSX Preservation and Sheet Names

## Status

Accepted (2026-09-28). The owner approved preserving sheet names and translating cell text for this release (2026-09-27). The writer and calculation contract were accepted in the architect role under the [P2-P6 handoff](../plans/P2-P6-delivery-handoff.md) after the native recalculation evidence below.

## Context

P2 must translate cell text while preserving sheet names, formulas, numbers, dates and formatting. The owner amended the earlier requirement to translate sheet names after reviewing the reference-preservation risk. The completed [write-strategy experiment](../experiments/xlsx-roundtrip/README.md) found that openpyxl 3.1.5 load/save removes a drawing text box and clears formula caches in the synthetic fixture. Direct text-part edits preserve those features, but neither writer automatically makes referenced sheet renames safe.

The architecture confines format knowledge to `formats/xlsx/` (ADR-003) and permits shared OOXML helpers.

## Options Considered

1. **Full openpyxl load/save.** Convenient object model; fails the demonstrated preservation cases even with rich-text loading enabled.
2. **Targeted OOXML edits.** Preserve all untouched ZIP entry payloads, selectively change supported text-bearing nodes, and use a format reader to verify output. Requires explicit handling of shared/inline strings and package relationships. Chosen.
3. **Native Excel automation.** Potentially handles more dependencies, but adds a desktop/Windows runtime requirement to the shared core and does not fit the portable server direction. Native Excel remains the acceptance-test oracle.

Sheet-name choices:

- Rename without reference repair: rejected; creates stale references.
- Rewrite formula and other reference text: conflicts with the literal no-formula-change requirement and needs a complete reference strategy, including names, charts, validation, hyperlinks, external references and dynamic references such as `INDIRECT`.
- Preserve original names: selected by the owner for this release.

Calculation choices (evidence: [recalculation experiment](../experiments/xlsx-recalc/README.md), Excel 16 build 20326):

- Keep caches untouched: Excel trusts them and shows values that disagree with the translated cells (a COUNTIF of a translated label still shows 2). Rejected: it silently trusts stale caches.
- Clear caches: readers without a calculation engine would see empty values, and Excel would still need a recalculation request. Rejected.
- Keep caches and request full recalculation on open, with diagnostics. Chosen.

## Decision

Use ZIP-part copying and namespace-preserving XML edits for XLSX. The production writer uses `zipfile` and securely configured lxml; workbook semantics live in `formats/xlsx/`, while package/XML primitives live in `formats/_ooxml/`. openpyxl is not a production dependency; tests may use it as an independent reader.

Read workbook/worksheet relationships rather than assume filenames or sheet order. Extract only literal string cells (`s` and `inlineStr`), translating each referenced shared-string entry once and retaining all its cell locations. Formula cells, including string-valued formula caches (`t="str"`), are never translation segments. Preserve run properties, styles, whitespace semantics (`xml:space="preserve"` where needed), formulas, numeric/date/boolean values, package relationships and unsupported untouched content. A translation beginning with `=` stays a string. Rich text is never flattened. Phonetic runs are left untouched.

Copy untouched entry payloads byte-identically, including drawings and extension parts. Never extract archive paths to disk. Reject malformed/duplicate paths, encrypted or signed packages, macro-enabled content types and resource-limit violations with explicit errors; never call a lossy library save as a fallback. An unknown untouched part is copied, not rejected.

**Sheet names:** preserve every sheet name, including hidden sheets. There is no rename option in this release.

**Calculation:** the core never evaluates formulas. When a translated workbook contains at least one formula, the writer sets `fullCalcOnLoad="1"` on `workbook.xml`'s `calcPr` (creating it if absent) so spreadsheet applications recalculate on open, keeps the saved caches for readers without a calculation engine, and reports:

- `formulas_recalculate_on_open` (info): the workbook contains formulas; cached values are from before translation until a spreadsheet application recalculates and saves it.
- `formula_literal_matches_translated_text` (warning, one per formula cell location, capped at 100 plus a count): a formula's string literal equals the source text of a translated cell, so its result can change after translation (the evidence showed COUNTIF/SUMIF becoming 0 and VLOOKUP becoming #N/A).

## Consequences

- Preserving the package is the default. Features outside the translation scope survive unchanged rather than being reconstructed by an incomplete object model.
- A workbook whose formulas compare against translated labels opens with different results. That is the faithful consequence of preserving formula expressions, and the result says so per cell.
- `workbook.xml` becomes a changed part whenever formulas exist.
- P2 needs package-diff and native-application acceptance fixtures. Reopening with a library alone cannot prove fidelity.
- P3 can modify only the additional style/layout nodes its accepted fit contract requires, retaining P2's preservation guarantees.
