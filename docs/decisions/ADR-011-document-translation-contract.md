# ADR-011: Document Translation Contract (Formatting, Writers, Detection, Identity)

## Status

Accepted (2026-09-28) in the architect role under the [P2-P6 handoff](../plans/P2-P6-delivery-handoff.md), from the P2.0 evidence below. Completes the P2.0 gates for formatting, PPTX/DOCX writers, source detection, protection and output identity. The XLSX calculation gate is settled in [ADR-009](ADR-009-xlsx-preservation.md).

## Context

P2 must translate TXT, PPTX, DOCX and XLSX through one core pipeline while preserving rich text in both engines, never flattening formatting, never silently dropping content, and exposing a cache fingerprint that the server can compute without loading a model (ADR-007, ADR-008). The [P2.0 plan](../plans/P2.0-document-design-validation.md) required evidence before choosing each strategy. Exact types and signatures are in the [core API reference](../Architecture.md#core-api-reference).

## Evidence

All experiments are reproducible from `docs/experiments/`; outputs live in gitignored `data/experiments/`. Recorded on Windows 11, Python 3.14.7, Office 16 build 20326.

**Formatting** ([formatting experiment](../experiments/formatting/README.md)): 12 synthetic formatted paragraphs (emphasis at start/middle/end, two and three spans, nesting, a link span, a placeholder, a line break, moved emphasis, literal `<`, numbers) in all 12 directions, 144 cases per engine.

| Engine | XML tags valid | Meaning proxy of valid (chrF vs plain) | Bracket tags valid | Per-span translation (chrF vs plain) |
|--------|----------------|----------------------------------------|--------------------|--------------------------------------|
| Gemma (`gemma-4-31b-it`, prompt `llm-translate-v1`) | 144/144 | 92.5 | 144/144 | 81.2 |
| SMALL-100 (CT2 int8, beam 4) | 89/144 | 73.9 | 43/144 | 57.9 |

Inspection confirmed Gemma moves emphasis with its words (`<g1>昨天</g1>` -> `... <g1>yesterday</g1>.`). SMALL-100 failures were mostly lost opening tags; its valid outputs sometimes put a space inside the opening tag. Projection (below) recovered 29 of SMALL-100's 55 invalid cases with the span on the correct words, for 118/144 (82%) structurally valid MT output before the per-span fallback. Translating each span separately preserves formatting but clearly degrades meaning (57.9 for MT), so it is the last resort.

**Writers** ([OOXML round-trip experiment](../experiments/ooxml-roundtrip/README.md)): a PowerPoint-authored deck (placeholders, notes, rich runs, hyperlink, table, group, text box, slide-number field, SmartArt, chart) and a generated DOCX (heading, rich run, hyperlink, simple and complex fields, nested table, header, footer, footnote, comment, tracked insertion/deletion, DrawingML text box with VML fallback). Every text run was prefixed with a marker.

| Fixture | Writer | Package entries rewritten | Text in edited parts missed |
|---------|--------|---------------------------|-----------------------------|
| deck.pptx | python-pptx 1.0.2 | 45 (all loaded XML parts, including charts, layouts, masters) | none in slides/notes |
| deck.pptx | targeted part edits | 4 (the three slides and the notes slide) | none |
| report.docx | python-docx 1.2.0 | 4 | hyperlink text, field result, tracked insertion, both text-box copies, footnote |
| report.docx | targeted part edits | 5 (document, header, footer, footnotes, comments) | none |

Native open results for these files are recorded in the experiment report.

**Detection** ([detection experiment](../experiments/detection/README.md)): FLORES+ devtest (1,012 sentences per language) with lingua-language-detector 2.2.0 restricted to zh/en/ja/es: 99.95% on sentences, 100% on 808 five-sentence documents, 98.5% on 3-word/12-character prefixes (errors mostly en/es). Japanese with kana removed was classified as Chinese 1,010/1,011 times by lingua and by a script rule: kana-free Japanese is not distinguishable from Chinese, so it is an ambiguity rule, not an accuracy claim.

## Decision

### 1. Segments and inline structure

A segment is a paragraph (PPTX `a:p`, DOCX `w:p`, one XLSX shared/inline string, one non-empty TXT line). Format adapters describe a paragraph as inline nodes: `Text(text, style)`, `Keep(text, style)` (never translated), `Obj(key)` (break, tab, field, drawing, bookmark...) and `Wrap(key, children)` (hyperlink, content control, tracked insertion). Styles and keys are opaque adapter ids. Adjacent same-style text merges; a whitespace-only style change is absorbed into its neighbour. The engine input marks every non-dominant style run and wrapper as `<gN>...</gN>` and every Keep/Obj as `<xN/>`, numbered in encounter order. The document-wide deduplication key is exactly this engine input (ADR-007 layer 1): identical inputs are translated once and each occurrence restores its own styles and objects.

### 2. Formatting strategy (both engines)

1. Paragraphs with one style and no objects are sent as plain text.
2. Tagged paragraphs are validated after translation: identical tag inventory, well-formed nesting, same parent for every tag, no emptied style span and non-empty output. Whitespace just inside a paired tag is moved outside it.
3. If validation fails, **projection**: translate the paragraph with only its `<xN/>` tags and each span's text separately; wrap each span translation's unique, case-insensitive occurrence in the paragraph translation, respecting nesting. The result is validated again.
4. If projection fails, **per-span fallback**: translate each text run separately and rebuild the paragraph with every run's own formatting (Latin targets get a space between adjacent letter/digit runs; CJK targets lose spaces between CJK characters). The result carries a `formatting_fallback` warning diagnostic with the paragraph's location.

Tags are never stripped and text is never reassigned to the first run. The fallback is deterministic, preserves every run's formatting and is visible in the result. The LLM prompt is unchanged (`llm-translate-v1` already instructs placeholders to be kept), so P1.1 is not triggered by P2.

### 3. Protection and pass-through

- `Keep` spans (sent as `<xN/>`): URLs, email addresses, Windows/UNC/Unix paths, caller-supplied protected terms (exact, case-sensitive) and literal text that looks like an engine tag. Numbers stay in the text (converting them to placeholders harms measure words and agreement); the prompt instructs the LLM to keep them.
- A segment is passed through unchanged, without reaching the engine, when it has no letters (numbers, symbols, dates in digits), is entirely protected, or contains no character of the resolved source language's script: for zh/ja sources no Han/kana; for en/es sources no Latin letter. Counts are reported as `passed_through`.

### 4. Source detection

Offline `lingua-language-detector` 2.2.0 limited to the four languages, on up to 20,000 characters of translatable text (tags and protected text removed), with version `detect-v1`:

1. Count kana, Han and Latin letters. With no letters the document has no translatable text: the output is an unchanged copy with `no_translatable_text`.
2. If Han+kana >= Latin: Japanese when kana >= 10% of Han+kana; otherwise Chinese when there are at least 10 Han characters; fewer is `SourceLanguageAmbiguousError`. A kana-free Chinese decision carries the info diagnostic `detected_without_kana`.
3. Otherwise lingua decides English vs Spanish; fewer than 20 Latin letters or a confidence below 0.70 raises `SourceLanguageAmbiguousError`.

An explicit source always overrides detection. Explicit source == target is `ValueError`. An auto-detected source equal to the target produces an unchanged copy with `already_target_language`.

### 5. Writers: targeted OOXML edits for PPTX, DOCX and XLSX

All three Office formats copy every ZIP entry byte-for-byte except the XML parts that contain translated text (and parts a later fit/recalculation change must edit). Changed parts are parsed with lxml (`resolve_entities=False`, `no_network=True`, no DTD loading) and serialized with their namespace declarations. python-pptx, python-docx and openpyxl are not production dependencies; they may be used by tests as independent readers. Packages are rejected before translation when they are encrypted (OLE compound file), contain `_xmlsignatures/`, have duplicate or unsafe entry names, or exceed the resource limits (section 7). Unknown untouched parts are copied, not rejected.

Coverage policy (unsupported text is reported, never silently counted as translated):

| Format | Translated | Reported, not translated |
|--------|------------|--------------------------|
| PPTX | Slide shapes, placeholders, nested groups, table cells, speaker notes; non-placeholder shapes on the slide layouts and masters the slides use | Chart text (`chart_text_not_translated`), SmartArt (`smartart_text_not_translated`), placeholder prompt text on layouts/masters (never rendered; not reported); slide-number/date fields are objects |
| DOCX | Body, nested tables, content controls, text boxes (DrawingML and its VML fallback, identical translation), headers/footers (each part once), footnotes, endnotes, tracked insertions, HYPERLINK field results | Comments (`comments_not_translated`), tracked deletions stay source text (`tracked_changes_present` warning), other field results are objects regenerated by Word (`field_results_not_translated`) |
| XLSX | Referenced shared and inline literal strings, rich runs, hidden sheets (ADR-009) | Drawing text boxes and legacy comments (`drawing_text_not_translated`, `comments_not_translated`) |

Written runs keep the source run's properties; where a run carries a language tag (`lang` in DrawingML, `w:lang` in Word) it is set to the target language.

### 6. Output identity and fingerprint

`prepare_identity(config)` returns a `TranslationIdentity` without loading a model or calling a server: LLM base URL, model, configured `deployment_revision`, prompt version, temperature, JSON mode and batch size; MT family, SHA-256 of every file in the model directory, resolved device, compute type, beam size and batch size. `Translator.identity` computes the same value from the loaded engine, so a worker verifies it runs the identity a job was fingerprinted with. `output_fingerprint(identity, options, fonts)` hashes canonical JSON (sorted keys, schema version 1) of: core distribution version, strategy versions (inline, detection, protection, each format writer, fit policy and measurement), the identity, every output-affecting option and the font manifest digest. Credentials, paths, callbacks and logging never enter it. The LLM `deployment_revision` is how an operator declares that a model served under an unchanged name has changed; a hash cannot detect that on its own.

### 7. Resource limits (defaults, configurable by the app)

Office packages: 1 GiB total uncompressed, 128 MiB per entry, 20,000 entries, compression ratio 1,000. TXT: 100 MiB. Any document: 200,000 segments. Exceeding a limit raises `DocumentLimitError` before engine calls; nothing is truncated.

## Consequences

- One formatting pipeline serves both engines; MT output has lower fluency when the fallback triggers, and the result says so.
- Targeted edits require the adapters to understand relationships, inheritance and run structure directly, which is more code than using the object-model libraries, but it is the only option in the evidence that neither rewrites untouched parts nor misses text.
- Chart, SmartArt and comment text remain in the source language in this release, visibly reported.
- Adding lxml and lingua to the core is recorded in its dependencies; lingua ships language models inside its wheel (no network at runtime).
