# XLSX Recalculation Experiment

Completed 2026-09-28 for the ADR-009 calculation gate. Evidence for [ADR-009](../../decisions/ADR-009-xlsx-preservation.md).

## Question and Method

When translated labels are formula inputs, what does a user see in native Excel if the translator keeps formula caches, and what if it requests recalculation on open?

```powershell
powershell -ExecutionPolicy Bypass -File docs/experiments/xlsx-recalc/make_fixture.ps1   # native Excel authors labels.xlsx
uv run docs/experiments/xlsx-recalc/spike.py                                            # targeted translation, two variants
powershell -ExecutionPolicy Bypass -File scripts/native_office_check.ps1 -OutDir data/experiments/xlsx-recalc/native <files>
```

`labels.xlsx` (Excel 16 build 20326) has labels 苹果/香蕉/苹果 with values 10/20/30 and formulas `COUNTIF(A1:A3,"苹果")`, `A1&"汇总"`, `IF(A2="香蕉","是","否")`, `SUMIF(A1:A3,"苹果",B1:B3)`, `VLOOKUP("香蕉",A1:B3,2,FALSE)`, `SUM(B1:B3)` and a cross-sheet reference to the COUNTIF. The spike translates the shared strings (苹果 -> Apple, 香蕉 -> Banana, 苹果数量 -> Apple count) with targeted XML edits, formula expressions unchanged per the owner's decision, and writes `keep-caches.xlsx` (caches and `calcPr` untouched) and `full-calc.xlsx` (plus `<calcPr fullCalcOnLoad="1"/>`). The check opens each workbook read-only in Excel (external links not updated) and reads every formula cell's displayed value. A copy with truncated sheet XML is the negative control for repair detection.

## Results

| Formula | Source | Caches kept | `fullCalcOnLoad` |
|---------|--------|-------------|------------------|
| `COUNTIF(A1:A3,"苹果")` | 2 | 2 (stale) | 0 |
| `A1&"汇总"` | 苹果汇总 | 苹果汇总 (stale; A1 now shows Apple) | Apple汇总 |
| `IF(A2="香蕉","是","否")` | 是 | 是 (stale) | 否 |
| `SUMIF(A1:A3,"苹果",B1:B3)` | 40 | 40 (stale) | 0 |
| `VLOOKUP("香蕉",A1:B3,2,FALSE)` | 20 | 20 (stale) | #N/A |
| `SUM(B1:B3)` | 60 | 60 | 60 |
| `'数据'!C1` (other sheet) | 2 | 2 (stale) | 0 |

All three workbooks opened in Excel without repair; the corrupted control failed to open, so a workbook that needs repair is reported as a failure rather than silently fixed. The spike found the four formulas whose string literals equal translated labels (C1, C3, C4, C5).

## Interpretation

Excel trusts saved caches of a workbook last calculated by the same version, so keeping caches silently shows values that no longer agree with the translated cells. Requesting full recalculation on open makes Excel show results consistent with the translated workbook, and exposes that label-literal formulas now evaluate differently: with formula expressions preserved, `COUNTIF(...,"苹果")` over cells that now say "Apple" is legitimately 0. The production rule is therefore to request recalculation and to warn, per formula, when a formula's string literal equals translated text. The core never evaluates formulas itself. Other readers that trust caches (for example libraries reading cached values) still see the saved caches until the workbook is recalculated and saved by a spreadsheet application; the diagnostic says so.
