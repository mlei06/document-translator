# Fit Measurement Experiment (Closed)

Closed 2026-09-28 under [ADR-012](../../decisions/ADR-012-lightweight-fit-policy.md). This report records what was compared, what the production estimator supports, and what it deliberately reports as unresolved. It does not claim native layout parity, and no further font-by-font tuning is planned.

## What Was Compared

Host: Windows 11 Pro 26200, Office 16 build 20326, fonts from `C:\Windows\Fonts`, the user font directory and Office's cloud-font cache (392 faces). The production code under test is `fit/measure.py` (HarfBuzz shaping via uharfbuzz 0.56.2, fontTools 4.66.0, greedy line breaking with CJK kinsoku and hanging full-width stops) plus each format's layout description.

**PowerPoint** (`make_cases.py`, `powerpoint_metrics.ps1`, `compare.py`): 198 text boxes (wrap on, no autofit) in zh/en/ja/es across Aptos, Calibri, Arial, Times New Roman, Segoe UI, 等线, Microsoft YaHei, SimSun, Yu Gothic/游ゴシック and MS Gothic; 10/14/20/28 pt; 150/280/420 pt wide; 1.0/1.5/0.9 line spacing; three bulleted multi-paragraph boxes. PowerPoint's own line count (`TextRange.Lines`) and text height (`TextRange2.BoundHeight`) were read through automation.

| Result | Value |
|--------|-------|
| Line count identical to PowerPoint | 195 / 198 |
| Off by one line | 3 (Latin text at the exact wrap boundary: Segoe UI 20 pt, Aptos 14 pt, Times New Roman 28 pt) |
| Height error, median / 95th percentile / maximum | 0% / 0% / one line |

Observations used by the PPTX description (all from this data): PowerPoint's single line height is 1.2 x the font size for every font tested; space before the first paragraph does not move text and space before later paragraphs adds; spacing below 100% is exactly 1.2 x size x percentage, while above 100% PowerPoint's height is about 0.19 x size less than that (so the estimate is slightly conservative there); full-width `、。，．` may hang past the margin; Office applies no pair kerning or standard ligatures by default; font names match the legacy family (name ID 1) or full name (ID 4) before a typographic family, because typographic families group variants such as Aptos Display and Arial Narrow.

**Word** (`make_word_cases.py`, `word_metrics.ps1`, `compare_word.py`): a fixed-layout table (75/150/225 pt columns) in the same four languages across Calibri, Arial, Times New Roman, Microsoft YaHei, SimSun, DengXian, Yu Gothic and MS Gothic at 9/11/14 pt, 81 cells. Word's line count (`ComputeStatistics(wdStatisticLines)`) and line pitch (vertical position of first and last characters) were read without saving (Word saves hang on this host). Text boxes could not be read through automation (no text range for DrawingML-only boxes), so Word text boxes are not validated by this experiment.

| Script | Cells | Line count identical | Line pitch |
|--------|-------|----------------------|------------|
| Latin (en, es) | 36 | 36 | within 0.1% using win ascent + descent plus uncovered hhea line gap |
| East Asian (zh, ja) | 45 | 32 (13 cells: we count one line fewer) | not matched by any single font-metric rule without an empirical multiplier |

ADR-012 does not endorse the East Asian multipliers that fitted this data (a 1.3 factor and a win-only metric for CJK fonts); they were removed and not promoted to production rules.

## Supported Cases (production)

| Format | Supported (measured, may pass or be adjusted) | Reported unresolved (sizes kept) |
|--------|-----------------------------------------------|----------------------------------|
| PPTX | Changed text in shapes, placeholders (geometry inherited from layout/master), group-scaled shapes and table cells; wrap on/off; `normAutofit` scale; bullets, indents, paragraph and line spacing | Vertical text; unknown geometry; fonts or glyphs not in the manifest. Shapes with "resize shape to fit text" are height-unconstrained (PowerPoint grows them), notes have no container |
| DOCX | Changed Latin text in fixed-layout table cells and DrawingML text boxes (VML fallback copy resized identically); exact row heights; line rules; document grid snapping | Any container holding East Asian text (`east_asian_layout_unvalidated`); vertical text; unknown geometry; missing fonts/glyphs. Body text and auto-layout tables reflow and are never containers |
| XLSX | Changed cell text clipped by a non-empty neighbour, wrapped cells limited by column (merged: range) width and custom row height; fitted size written to a cloned font/cell format for that cell only | Rich-text runs with their own sizes; rotated or shrink-to-fit cells; missing fonts/glyphs. Unwrapped text beside an empty cell spills (not constrained); row heights and column widths never change |
| TXT | Not applicable | |

Estimator constants (ADR-012): 70% relative and 8 pt absolute floor, 2.5% scale steps, 0.5 pt quantization, 1 pt tolerance, at most 40 candidate measurements per container. XLSX column widths assume a maximum digit width of 7 px at an 11 pt default font (scaled with the default size) and 2 px cell padding per side, which is Excel's behaviour for its default fonts. `passed` and `adjusted` mean only that the supported estimator found no excess.

Characters that neither run font contains are measured with the document's theme script fonts (Hans, Jpan, Hant: the fonts Office substitutes for East Asian text in a Latin font); a character in none of the document's fonts is `missing_glyph`.

## Acceptance Corpus (ADR-012)

Frozen corpus: the four fixture formats in `tests/fixtures/` (native PowerPoint deck with placeholders, table, group and text box; generated DOCX with body, tables and a text box; XlsxWriter workbook with merged cells and rich text), synthetic-font tests for growth, floors, source overflow, missing fonts, unsupported geometry and search limits, and the real-engine runner `scripts/acceptance_local.py` (`data/acceptance/p3/local/summary.json`, 2026-09-28, Gemma and SMALL-100, zh -> en, Windows and Office cloud fonts):

| Format | Fit outcome (both engines) | Fit time vs translation time |
|--------|----------------------------|------------------------------|
| TXT | not_applicable | 0 s |
| PPTX | passed: 14 containers inspected, none needed shrinking | 1.2-4.4 s vs 2.2-2.8 s (first-run font loading; the library is now shared across documents) |
| DOCX | unresolved: the text box holds Chinese source text (`east_asian_layout_unvalidated`) | 0.02 s |
| XLSX | unresolved: 10 of 12 cells fit; one rich-text cell with explicit run sizes (`rich_text_sizes`); one clipped label still overflowing at the 8 pt floor (`overflow_at_floor`) | 0.1-0.9 s |

Every input was unchanged. All eight outputs opened in native PowerPoint, Excel and Word (build 20326). Visual spot checks of the PowerPoint and Excel exports: translated text inside every passed PowerPoint shape and table cell (no false pass); the Excel label reported `overflow_at_floor` is visibly clipped at 8 pt, as reported; no unnecessary shrinking seen; formatting (red bold runs, hyperlinks, merged title, chart, text box) preserved. The `########` date cells in the workbook are the same in the source and unrelated to translation.

## Saved-Output Verification

After writing, the pipeline reopens the output as the same format and checks that every container's run sizes in the file equal the sizes the fit check applied (`pipeline._verify`); a mismatch fails the job instead of publishing. Formats without layout support report `not_run` (never `not_applicable`); only TXT and documents without applicable containers report `not_applicable`.

## Known Limits and Follow-ups

- Word text boxes: not validated natively (automation limitation above); Latin text boxes use the same paragraph model as validated cells.
- East Asian text in Word: unresolved until an independent validation supports a model. This is common for zh -> en DOCX with fixed containers; the report says so per container.
- Line spacing above 100% in PowerPoint over-estimates height by about 0.19 x size, which can cause a small unnecessary shrink.
- Missing company fonts produce `font_unavailable`; provision them through the configured font directories.

Outputs: `data/experiments/fit-measurement/` (`comparison.json`, `comparison-word.json`, the generated cases and the raw Office metrics).
