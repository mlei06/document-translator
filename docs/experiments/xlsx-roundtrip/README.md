# XLSX Preservation Experiment

Completed 2026-09-27. This is structural feasibility evidence for P2, not a production adapter or proof of native Excel rendering fidelity.

## Question and Method

Can a translator change cell text using openpyxl load/save without losing other workbook content? Does editing only text-bearing OOXML parts avoid those losses? What happens when a translated tab name has incoming references?

Run from the repository root:

```powershell
uv run docs/experiments/xlsx-roundtrip/spike.py
```

The script pins openpyxl 3.1.5, XlsxWriter 3.2.5, Pillow 12.1.1 and lxml 6.0.2 in an isolated environment. The recorded run used Python 3.14.7 on Windows. It writes only synthetic fixtures and results under `data/experiments/xlsx-roundtrip/`, which is gitignored. `results.json` records package versions, changed/missing entries, warnings and reopened workbook observations. A failed assertion exits nonzero; do not pipe the command through a filter that masks its exit code.

XlsxWriter creates a shared-string workbook containing Chinese labels, rich text with a bold red run, formulas with known cached values, a cross-sheet formula, a named range, internal and external hyperlinks, numbers, dates, a boolean, a literal string beginning with `=`, a comment, validation, conditional formatting, merged cells, explicit row/column sizes, frozen panes, a chart, a bitmap image and a drawing text box. A second fixture converts cell storage to inline strings while retaining the unused shared-string part. Both input packages are hashed before/after to prove they were not modified.

For each fixture, compare openpyxl load/save (`rich_text=True`, changing rich runs without flattening them) against targeted XML writes, both with and without a tab rename. Translation is a deterministic `T:` marker, applied to each text run to isolate serialization from engine behavior. The XML path edits both shared and inline text and asserts that it actually changed text.

## Results

| Fixture and writer | Existing ZIP entries changed, names kept / renamed | Source entries absent in output | Text-box shapes | SUM cached value | Stale reference after rename |
|--------------------|---------------------------------------------------|--------------------------------|-----------------|------------------|------------------------------|
| Shared strings, openpyxl | 13 / 13 | 3 | 0 (source: 1) | `None` (source: 295) | Yes |
| Shared strings, targeted XML | 1 / 2 | 0 | 1 | 295 | Yes |
| Inline strings, openpyxl | 13 / 13 | 3 | 0 | `None` | Yes |
| Inline strings, targeted XML | 3 / 4 | 0 | 1 | 295 | Yes |

All eight cases reopened through openpyxl. Both writers translated the checked plain/rich cell text and preserved the checked bold run, formula expressions, numeric/date/boolean values, comment text, validation, conditional-format rule count, merged range, cell style, dimensions, freeze panes, chart count and image count. The library path's missing entry names were `xl/sharedStrings.xml`, `xl/comments1.xml` and `xl/drawings/vmlDrawing1.vml`; comments were relocated, not lost. Entry-count changes alone are therefore not a content-loss test. The independently counted missing text-box shape and cleared caches are the concrete losses.

The XML path copied every entry outside its changed-part allowlist byte-for-byte (uncompressed payloads, not the entire ZIP byte stream), added/removed no entries, and preserved the drawing shape and both formula caches. In the inline case it also translated the retained, unreferenced shared-string table; a production adapter should translate only referenced entries. A rename adds `xl/workbook.xml` to the changed parts.

Renaming `销售数据` to `Sales` left `='销售数据'!B2`, the named range, the chart references and the internal hyperlink pointing to the old name. The experiment detects stale reference text; it does not claim to have recalculated `#REF!` in Excel. Copying OOXML faithfully does not make a rename semantically safe.

## Corrections to the Prior Spike

The prior script crashed while printing Chinese rich text under Windows cp1252. Its shell pipeline nevertheless reported exit code 0. It also edited only `sharedStrings.xml`, while its openpyxl-created fixture used inline strings, so its XML comparison would have been a no-op. The completed script uses UTF-8 console output, checks actual edits, and covers both storage representations.

The prior tag spike's saved output reports Gemma v1/v2 at 30/30 and SMALL-100 at 20/30. Those historical results were inspected, not rerun here. They do not establish safe formatting for arbitrary documents or all 12 directions.

## Interpretation and Limits

Recommend targeted OOXML writes for XLSX and use openpyxl as an independent reader in tests. This conclusion is consistent with upstream's warning that openpyxl does not preserve every Excel item, including shapes ([tutorial](https://openpyxl.readthedocs.io/en/stable/tutorial.html#loading-from-a-file)). Upstream also documents that structural edits do not generally manage formula/table/chart dependencies for clients ([editing worksheets](https://openpyxl.readthedocs.io/en/stable/editing_worksheets.html)).

This is two synthetic storage variants of one feature-rich workbook, not a customer-workbook compatibility corpus. Native Excel/LibreOffice open, repair detection, recalculation and visual comparison were not performed. Macro-enabled files, encryption, signatures, pivot tables, slicers, external workbooks, phonetic runs and arbitrary extension parts remain untested. Preserved formula caches can become semantically stale when translated strings are formula inputs; production cache/recalculation behavior needs a separate test and decision. A production adapter also needs relationship resolution, namespace preservation, safe parsing and resource bounds, none of which this narrow script claims to implement completely.

The proposed decision and unresolved requirement are in [ADR-009](../../decisions/ADR-009-xlsx-preservation.md). Product implementation and native-application acceptance belong to [P2](../../plans/P2-document-translation-and-cli.md).
