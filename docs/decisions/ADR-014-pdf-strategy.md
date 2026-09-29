# ADR-014 - PDF Strategy: Targeted Text Replacement with PyMuPDF

Status: Accepted 2026-09-29 (P4.0 gate). The owner approved PyMuPDF on 2026-09-28 ("just use pymupdf"), accepting its AGPL-3.0 license for this internal service. Evidence: [PDF strategy experiment](../experiments/pdf-strategy/README.md).

## Context

P4 must translate text-based PDFs (no OCR) while keeping page size, artwork and reading content, remove the source text rather than hide it, and fit replacement text within ADR-012's floors using the PDF writer's own layout facilities (ADR-012 per-format scope). A PDF has no paragraphs, boxes or table cells: only positioned glyphs, vector paths and images. P4 asked to start with targeted replacement and to consider an editable intermediate only if the direct path hit a concrete blocker.

## Options Considered

- **Targeted replacement in the PDF (PyMuPDF / MuPDF):** read positioned text, remove only the translated characters with redaction that keeps images and vector graphics, write the translation with MuPDF's HTML box layout (`insert_htmlbox`, which shrinks to a lower bound). Accepted: the spike and the production corpus show source removal, preserved artwork and working fit with one library.
- **Editable intermediate (PDF to DOCX, translate, back to PDF):** loses page fidelity on every document (fonts, positions, vector art) to fix problems the direct path does not have. Not pursued; no blocker was found.
- **White-rectangle overlay:** forbidden by P4 (hides artwork, leaves searchable source text).
- **Licensing alternatives (pypdf/pdfplumber plus reportlab):** no redaction that keeps artwork and no HTML text layout; would need a second layout engine, which ADR-012 rules out.

## Decision

**Library.** `pymupdf==1.28.2`, imported only by `formats.pdf` (and later `render`), enforced by an import-linter contract. AGPL-3.0: acceptable for the internal service where no modified PyMuPDF is distributed. Before any distribution of the desktop/internal apps (ADR-013) or other redistribution, revisit: comply with AGPL for the distributed application or buy an Artifex commercial license.

**Rejection before translation.** Encrypted or password-protected PDFs and digitally signed PDFs (any signature flags) are `UnsupportedDocumentError`: translation would invalidate a signature, and passwords are never requested. A PDF with no extractable characters (scanned or image-only) is `NoExtractableTextError` (`no_extractable_text`), never an unchanged "successful" copy. Unreadable files are `InvalidDocumentError`.

**Extraction and units.** Text comes from MuPDF's layout (`get_text("dict")`) with ligatures expanded and line-end hyphenation joined. A translation unit is a paragraph of lines within one MuPDF block: a line joins the previous one only if it is below it, overlaps it horizontally, is at most one line height away, the previous line reached the block's right edge (it wrapped) and the line does not start with a list marker. Lines side by side (table cells, separate shapes on one row) are separate units even when MuPDF puts them in one block. A leading list marker (bullet, dash, "1.", "(1)", "1、", "（一）") is kept out of the engine input and written back unchanged. Lines of a unit join with a space except around CJK characters. Units are in page and MuPDF block order; the location is `page N, text K`.

**Formatting.** A span's size, bold, italic, color and underline form its style; different styles become ADR-011 tagged spans. The font is not part of the style: PDF producers switch fonts inside one run for glyph fallback (PowerPoint's PDF export draws one Chinese word with two fonts), which is not formatting. Each style is written with the font that drew most of its text in that unit. Underlines are thin horizontal paths just below a span's baseline; they are removed with the text and redrawn as `text-decoration: underline` under the translation.

**Kept, reported content.** Rotated or vertical text is not translated (`pdf_rotated_text_kept`); text without a Unicode mapping is not translated (`pdf_text_unreadable`); pages whose images cover at least half the page get `untranslated_image_content`. All three stay on the page as they are. Numbers-only and protected text pass through untouched (ADR-011). Page rotation is supported: extraction and writing share unrotated page coordinates.

**Removal.** Per changed page: underline paths are removed first (redaction removing only line art fully inside the marked rectangles), then characters (redaction with `text=REMOVE`, `images=NONE`, `graphics=LINE_ART_NONE`) over the middle half of each translated span's box, so neighbouring lines are never touched. Redaction deletes overlapping link annotations; they are re-inserted unchanged at their original rectangles. Untranslated text, images, vector graphics, annotations and untouched pages are not modified.

**Placement and fit (ADR-012 for PDF).** Each unit gets a region: inside the smallest filled or outlined shape that encloses it (minus its original padding, at most 7.2 pt), otherwise the page within 36 pt margins; the region then stops 2 pt before other text, drawings and images to the right, left and below, and is never smaller than the original text. The unit keeps its top edge and its alignment (left, center or right from line positions, the enclosing shape or the page center). The translation is written with `insert_htmlbox` into the region with `scale_low` equal to the smallest common scale that keeps every run at or above `max(8 pt, 70%)` (runs at or below 8 pt never shrink). MuPDF's own layout decides line breaks and the scale; there is no second estimator. Outcomes: fit at original sizes (passed, no entry), shrunk (`adjusted`, `shrunk_to_fit`), or not fitting at the floor: the text is written at floor sizes extending below its region (`unresolved`, `overflow_at_floor`); only if even the rest of the page is too small does MuPDF shrink further. Text is never dropped. The fit report's `measurement` is the PDF strategy version.

**Fonts.** Each style uses the provisioned face (font manifest) matching its PDF font name (subset tag removed; PostScript or family names; style suffixes such as `-BoldMT` ignored) if that face covers every character of the translation. Otherwise the first provisioned face that covers it from a fixed per-target list (en/es: Arial, Liberation Sans, DejaVu Sans, or the serif list; zh: Microsoft YaHei, DengXian, Noto/Source Han Sans SC; ja: Yu Gothic, Meiryo, MS Gothic, Noto/Source Han Sans JP); otherwise the original face with MuPDF's built-in fallback for missing glyphs, or MuPDF's built-in faces (Nimbus Sans, Charis SIL, Nimbus Mono, Droid Sans Fallback). Substitution is reported (`pdf_font_substituted`, info, with a count). Faces from collections are split into single-face files; new fonts are subset before saving. The font manifest digest and `STRATEGIES["pdf"]` (which names the PyMuPDF version) are in the output fingerprint.

**Verification before publishing.** The written PDF is reopened: page count, crop boxes and rotations unchanged; every translation (with its marker) present in the page text; every untranslated unit on a changed page still present; no source text of a translated unit still extractable inside its original box. A failure is `InvalidDocumentError` and nothing is published.

**Capability.** PDF implements a `PlacementFit` capability (`place(options, fonts)` returns one outcome per changed unit) instead of `LayoutSupport`, and `DocumentAdapter.verify_output` for its checks. This amends ADR-003's capability table for PDF: ADR-012 requires the writer's layout, and `LayoutSupport` exists to feed the shared estimator.

## Consequences

- One pinned native dependency (MuPDF inside the wheel); CJK fallback fonts come with it. Its AGPL license must be revisited before any distribution.
- Growth is bounded by the space around each unit, so dense pages (reports with tight paragraph spacing) shrink more than Office documents, which reflow; nothing below a unit moves. Overflowing text can overlap content below it and is always reported unresolved.
- Unit detection is heuristic. Multi-column layouts rely on MuPDF's block separation; unusual layouts can split or join paragraphs. Rotated, vertical and unmapped text is left untranslated and reported.
- Link rectangles keep their original position and may no longer match the moved text exactly.
- Output is larger than the input when new fonts are embedded (subset); a zh to en slide deck grew from 177 KB to 430 KB.
