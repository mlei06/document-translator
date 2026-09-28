# PPTX/DOCX Writer Experiment

Completed 2026-09-28 for the P2.0 serialization gate. Evidence for [ADR-011](../../decisions/ADR-011-document-translation-contract.md); not a production adapter.

## Question and Method

Is python-pptx/python-docx serialization sufficient, or must the adapters patch selected OOXML parts? The XLSX experiment's findings do not transfer, so both formats were tested directly.

```powershell
powershell -ExecutionPolicy Bypass -File docs/experiments/ooxml-roundtrip/make_fixtures.ps1 -Part pptx   # native PowerPoint
uv run docs/experiments/ooxml-roundtrip/build_docx.py                                                   # generated DOCX
uv run docs/experiments/ooxml-roundtrip/spike.py
powershell -ExecutionPolicy Bypass -File scripts/native_office_check.ps1 -OutDir data/experiments/ooxml-roundtrip/native <files>
```

- `deck.pptx`, authored by PowerPoint 16 (build 20326) through COM: title and subtitle placeholders, speaker notes, bullets with a bold red run, an italic run and a hyperlink, a 3x2 table, two grouped shapes, a text box, a slide-number field, SmartArt and a chart.
- `report.docx`, generated with python-docx plus raw WordprocessingML: heading, bold run, footnote (with separator notes), external hyperlink, simple DATE field, complex HYPERLINK field, table with a nested table, header, footer, comment, tracked insertion and deletion, and a DrawingML text box with its VML fallback. Word automation on this host hangs when saving documents that contain fields, comments or tracked changes (a hidden prompt; the script does not change the user's Word options), so the DOCX is generated instead of authored in Word.

Each writer prefixes every text run with `T:`. The library writers traverse everything their object model exposes (groups recursively, tables, notes; body, nested tables, headers and footers). The targeted writer copies every ZIP entry and rewrites only slides/notes (PPTX) or document/header/footer/footnote/comment parts (DOCX), changing every `a:t`/`w:t` node in them. Results: `data/experiments/ooxml-roundtrip/results.json`.

## Results

| Fixture | Writer | Entries rewritten | Missing / added entries | Text missed in the edited scope |
|---------|--------|-------------------|-------------------------|---------------------------------|
| deck.pptx | python-pptx 1.0.2 | 45: every loaded XML part and relationship file, including the chart, all 12 layouts, the master and `docProps/core.xml` | 0 / 0 | none in slides and notes (SmartArt and layout/master text are outside the object-model traversal) |
| deck.pptx | targeted | 4: `slide1-3.xml`, `notesSlide1.xml` | 0 / 0 | none |
| report.docx | python-docx 1.2.0 | 4 | 0 / 0 | hyperlink text, DATE field result, tracked insertion, both text-box copies, footnote, comment |
| report.docx | targeted | 5: document, header, footer, footnotes, comments | 0 / 0 | none |

Native open (PowerPoint 16.0 build 20326, read-only, repair disabled): the source deck and both PPTX outputs opened; the PowerPoint PDF export of the targeted output shows the bold red run, italic span, hyperlink, table, group, text box and slide-number field intact. Word results are in `data/experiments/ooxml-roundtrip/native.jsonl`; Word's PDF export hung on this host in the same way as its saves, so DOCX visual inspection uses the release pipeline's own checks instead.

## Interpretation

python-pptx rewrites far more of the package than the translation touches, and python-docx's object model does not reach several required DOCX surfaces (footnotes, hyperlinks, text boxes, fields, tracked insertions); using it would require direct XML access anyway. Targeted part edits reached every text node in scope and left every other entry byte-identical. The production adapters use targeted edits for all three Office formats. PowerPoint splits runs at language boundaries (`1,250` and `万元` are separate runs with different `lang`), so the adapters exclude language tags from the run style key.

This is one native deck and one generated document, not a customer corpus. The production test suite adds XML-built fixtures for fields, content controls, masters, charts and malformed packages, and the release evidence repeats native opens on translated outputs.
