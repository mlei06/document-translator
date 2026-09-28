# P2 - Document Translation and CLI

Status: Draft for architecture review (2026-09-27), not approved for implementation. Board: [Feature #9010](https://chintand.visualstudio.com/AI%20Projects/_workitems/edit/9010), New until the first implementation plan is approved. The existing roadmap/README remain authoritative where this draft proposes a change.

The [P2-P6 handoff](P2-P6-delivery-handoff.md) governs the full release. P2 builds local `translate`; P5 adds service CLI and persistent batches. Technical decisions are resolved in the architect role before coder handoff.

## Objective

Translate TXT, PPTX, DOCX and XLSX through one core document pipeline and a thin CLI, preserving source files, supported structure and formatting. Produce explicit diagnostics for limitations and fail without publishing a partial output when a translation cannot be written safely.

## Relevant Architecture

- [Architecture](../Architecture.md) and [core architecture section](../Architecture.md#core-api-reference)
- ADR-003: module boundaries and capability classes
- ADR-007: whole-document deduplication and fingerprint
- ADR-008: progress callback and cooperative cancellation
- ADR-005: quality gate, including [P1.1](P1.1-baseline-capture.md)
- Proposed [ADR-009](../decisions/ADR-009-xlsx-preservation.md)

## Current Code and Dependencies

Reuse `Translator`, configuration validation, typed engine errors, LLM batching/retries and SMALL-100 runtime. `document.py`, `pipeline.py`, format packages and the CLI are currently empty scaffolds. Per-call deduplication is not the required document-wide guarantee. Do not copy engine behavior into adapters or the CLI.

P1 delivery verification/closure remains separate from baseline deferral. Complete [P2.0 design validation](P2.0-document-design-validation.md), resolve the gates below, complete architect review under the P2-P6 handoff and promote the accepted contract into the core architecture section before production work. Run P1.1 before any production prompt/model change, even if P2 is otherwise ready.

## Proposed Architecture

### Public API

Add the document method to the existing `Translator`, plus a metadata-only fingerprint function. Re-export the function and options/result/error types through the allowed public modules. The identity type and its preparation/validation contract are a P2.0 design gate:

```python
Translator.translate_document(
    input_path: Path,
    output_path: Path,
    *,
    options: DocumentTranslationOptions,
    on_progress: Callable[[TranslationProgress], None] | None = None,
) -> DocumentTranslationResult

output_fingerprint(
    identity: TranslationIdentity,
    options: DocumentTranslationOptions,
) -> str
```

`translate_texts` stays compatible. A `Translator` is reusable but remains not thread-safe. Adapters and engines never import each other; `pipeline.py` composes them. Format-neutral inline-text handling belongs beside `document.py`, not inside `formats/_ooxml/`; only OOXML primitives belong there.

The fingerprint function must be callable by the job service before dispatch, without constructing a `Translator`, loading MT weights or calling a translation model. Today's MT constructor loads the model, so the earlier instance-only proposal would violate the intended web/worker boundary. A configured immutable engine identity must be prepared/validated outside request-time inference, and the worker must verify it uses that same identity. This is a draft correction, not an implemented API.

| Type | Proposed fields and rules |
|------|---------------------------|
| `DocumentTranslationOptions` | Requested source (`auto` or Language), target, document batch size, protected terms, TXT encoding, preserved sheet names (no rename option). Mode/engine configuration comes from the Translator. No fake fit options before P3. |
| `TranslationProgress` | Phase (`extract`, `translate`, `write`), done, total. Monotonic within each phase; translation units are unique engine inputs. No document text in progress events. |
| `DocumentTranslationResult` | Output path, source requested/resolved, target, format, EngineInfo, fingerprint, segment/unique/pass-through counts, diagnostics, `fit_status=not_run`. An empty fit report must not imply visual verification. |
| `DocumentDiagnostic` | Stable code, severity, stable location and safe message. No credentials or full source text in routine logs. |
| `DocumentError` | Typed invalid/unsupported input, source ambiguity, formatting failure and write failure errors under `TranslationError`. A callback exception propagates unchanged after cleanup. |

Final field types/defaults are a P2.0 deliverable. This draft is not an instruction to implement placeholder or half-specified public types.

### Internal document and adapter model

- A segment is a **paragraph**, not an entire multi-paragraph text frame/table cell. PPTX text frames and DOCX cells may contain several segments. An XLSX literal cell is one segment, possibly with rich runs and embedded line breaks. TXT preserves line endings/blank lines and segments non-empty physical lines for the first implementation.
- Each segment has a document-local stable ID/location, ordered inline spans/objects, original text and an optional container reference. Locations use part identity plus stable object IDs/structural indices, not transient Python object addresses. No library/XML objects cross into generic engine/fit logic.
- Formatting spans carry stable IDs and opaque style references owned by the adapter. Breaks, tabs, fields, hyperlinks and protected tokens require explicit representation; preserving plain text alone is not a round trip.
- Geometry is optional and expressed in points when known. Avoid inventing a page position for reflowing DOCX content or an exact pixel extent for XLSX cells. P3 owns measurement and font fallback. P2 preserves enough source references to add geometry without rescanning semantics into the generic fitter.
- `formats/base.py` supplies `DocumentAdapter` as an ABC for open/extract/apply/save/close, with adapter-owned state per document. The registry selects an adapter from validated content and extension. Implement only the read/write capability now; later layout/render/edit capabilities remain distinct as ADR-003 specifies.

### Translation and formatting

1. Validate input, supported format and destination before engine calls. Reject source/destination aliasing, symlinks/hardlinks resolving to the input, unsupported/encrypted/signed packages and incompatible suffix/content combinations. Resource limits and XML safety settings must be pinned by P2.0.
2. Extract the whole document before translation; resolve source language from representative translatable text with explicit `--from` overriding detection. Empty/numeric-only documents copy unchanged with an explanatory result; explicit source equal to target remains an invalid request, consistent with the text API. Auto-detected target-language documents may return an unchanged copy with an `already_target_language` diagnostic.
3. Protect recognized non-translatable spans and configured product-name terms. Do not skip an entire sentence because it contains a number, URL or short code token. Treat ambiguous prose conservatively.
4. Serialize paragraphs to canonical inline tokens with IDs numbered locally in encounter order. Escape literal markup. The deduplication key is precisely the engine input, language pair and chosen formatting strategy; normalize equivalent local token IDs but retain formatting distinctions, per ADR-007. Styles that differ must not accidentally collapse to one key.
5. Build the unique-input map across the document, then translate bounded batches through the existing text API. Map each result back to every occurrence, preserving each occurrence's original whitespace and local style references. Splitting into batches never clears the document map.
6. Validate output token inventory, identity, nesting, protected payloads and structural boundaries before applying it. Never put all output in the first run. LLM tags have encouraging but limited evidence; the selected MT strategy and failure/fallback behavior are an explicit P2.0 gate. A model response that cannot be safely mapped fails before output publication unless the approved policy defines a visible, fidelity-preserving fallback.
7. Invoke progress after extraction and between translation batches, before writing and before publication. If the callback raises, stop and remove temporary output. No completion callback that can retroactively turn an already-published output into a cancelled job. Current engine requests finish before a batch-boundary cancellation can take effect.
8. Apply validated translations to adapter-owned state, write a temporary file on the destination filesystem, reopen/validate required structural invariants, then atomically publish. Default behavior refuses an existing output; any overwrite option must still prohibit the input and avoid a check-then-overwrite race. On error, retain original input and any existing output. No partial result is a successful document.

### Format contracts

| Format | Required coverage and preservation |
|--------|------------------------------------|
| TXT | Explicit encoding, preserve BOM when applicable, CRLF/LF, blank lines, leading/trailing whitespace and final-newline state. Default strict UTF-8; do not silently guess a legacy encoding. |
| PPTX | Text boxes/placeholders, shapes, nested groups, table cells, speaker notes. Keep paragraph/run properties, hyperlinks and inline breaks. Exclude slide-number/date fields and notes-template boilerplate from translation. No fit/shrink changes in P2. |
| DOCX | Body paragraphs, nested tables, headers/footers (dedupe linked parts), footnotes (exclude separators), styles/runs and hyperlinks. Preserve fields, bookmarks and numbering. Track changes, text boxes and other unsupported text-bearing constructs require an explicit coverage decision/diagnostic, not silent omission. Fixed-element fit is P3. |
| XLSX | Targeted ZIP/XML writes per proposed ADR-009; shared and inline literal strings, rich runs and hidden sheets. Never translate formulas/cached formula strings or alter numbers/dates/booleans. Preserve all untouched parts. Sheet names are preserved by owner decision; native recalculation remains a design gate. |

python-pptx/python-docx remain candidate readers/writers confined to their format packages. P2.0 determines whether their save paths meet the required corpus; do not extrapolate XLSX findings or choose a production serializer without evidence.

### Fingerprint

Version a canonical JSON schema and hash its UTF-8 bytes with SHA-256. Include requested source (`auto` remains distinct), target, output-affecting options, normalization/formatting/detector strategy versions, core distribution version, and the complete output-affecting engine identity/configuration. Include LLM endpoint/model/prompt version/temperature/JSON mode/batch size and MT model/tokenizer artifact hashes, model family, resolved device/compute settings, beam size and batch settings. Hash MT artifacts when preparing/validating an immutable engine identity, not once per segment or upload; the server must have that identity before it claims a cache hit, and workers must verify it matches the loaded runtime. Never include API keys, paths to document/output files, callbacks or logging settings. Do not expose raw engine identity inputs in a user-facing hash.

`EngineInfo` alone is insufficient today: two same-named MT directories or distinct LLM endpoints can produce different output. A model served under an unchanged name can also change: P2.0 must specify a configured deployment revision or another immutable identity contract; a hash cannot detect unannounced remote replacement. Timeout/retry and batching inclusion choices must be documented, conservative where behavior can change. No persistent cache is built in P2.

### CLI

Proposed command:

```text
doctranslator translate INPUT --to en [--from auto] [--mode llm|mt] [-o OUTPUT]
```

Use Typer and app-owned settings. Arguments override environment, then an explicitly selected config file/local `.env`, then defaults; reuse the documented vault convention without importing `apps/eval`. If output is omitted, use `<stem>.<target><suffix>` and refuse collisions. Report progress/diagnostics on stderr and the final path on stdout. Provide a JSON result option for scripting. Exit codes: 0 complete (diagnostics may be present), 2 invalid input/configuration, 3 engine/translation failure, 4 output I/O failure, 130 interruption. `--help` must not load models or require secrets.

Do not advertise PDF, fit, web jobs or automatic visual review before their phases exist. Show `fit_status=not_run` in results and describe P2's limits in help/docs.

## Implementation Sequence and Files

| Task | Files | Dependency and acceptance |
|------|-------|---------------------------|
| P2.0 design validation | Experiments, ADRs, this plan, core architecture section | Resolve all gates below and record architect acceptance |
| P2.1 types and TXT vertical slice | `types.py`, `config.py`, `document.py`, `pipeline.py`, `formats/base.py`, registry, `formats/txt/`, core exports/tests | Fake-engine E2E covers output publication, deduplication, cancellation and unchanged input |
| P2.2 inline text and engine mapping | Format-neutral inline module, pipeline, tests | Approved LLM/MT formatting strategy; prompt changes only after P1.1 |
| P2.3 Office adapters | `formats/_ooxml/`, `pptx/`, `docx/`, `xlsx/`, shared fixtures | Per-format required surfaces and preservation corpus; import contracts added with actual dependencies |
| P2.4 product CLI | `apps/cli`, `.env.example`, package metadata, CLI E2E tests | Only public core imports; configuration/errors/help/progress exercised as a user |
| P2.5 acceptance and docs | Tests, README, component/structure/deployment docs, roadmap and board | Both real engines across all four formats, native open/visual QA, six checks and CI |

Each task gets a bounded coder handoff after architect acceptance; no parallel production edits are required by this draft.

## Tests Required

- Fake-engine E2E through the actual CLI for each format, both modes, normal and failed runs. Same fixture through CLI and public API must have equivalent content/structure; ZIP timestamps alone do not constitute differing translation behavior.
- Duplicate segments across distant paragraphs/slides/sheets and batch boundaries call the engine once; formatting-distinct segments remain distinct. Callback failure before/during write leaves no final partial file.
- Every required format-table surface appears in fixtures. Inputs remain hash-identical. Outputs reopen, and untouched OOXML parts plus protected semantic values are checked. Test inline/shared strings, rich text, merged/hidden sheets, fields, linked headers, footnotes and grouped shapes.
- Malformed/oversized/duplicate-entry archives, unsafe XML, literal tag text, broken returned tags, missing/extra translations, empty output, unavailable fonts where relevant, path aliasing, existing output and unwritable destinations.
- Pass-through embedded in prose, product-name terms, detector ambiguity and explicit override. Source=target and empty documents behave as documented.
- Fingerprint stability and sensitivity to each output-affecting field, remote revision and model bytes; prove secret/path/callback changes do not enter it.
- Real LLM and MT smoke translations for every format on synthetic Chinese-English fixtures, plus all-direction formatted-text validation from P2.0. Separately record target-language correctness and formatting correspondence.
- Native application open without repair plus source/output visual inspection. Fix preservation defects; do not claim the P3 fit guarantee in P2. If native tooling is unavailable, record the unverified criterion rather than substitute a library reopen.
- All six repository checks and CI pass on the reviewed commit.

## Decisions Required Before Approval

1. Apply the owner-approved preserved-sheet-name policy; finalize ADR-009 writer and formula cache/recalculation behavior with native evidence.
2. Select exact LLM/MT formatting strategy and failure/fallback policy using P2.0 evidence.
3. Select PPTX/DOCX save strategies and supported-construct policy.
4. Pin source detector, ambiguity thresholds, protected-term behavior and bounded parser limits.
5. Finalize API field definitions, metadata-only engine deployment/artifact identity preparation, worker identity verification and canonical fingerprint schema. Submission lookup must not load the MT runtime into the web process.

## Completion Criteria

- [ ] All decisions above resolved and approved; core architecture section and README synchronized.
- [ ] Every current/approved amended format requirement has a passing fixture test.
- [ ] Both engines complete all four formats via the CLI; outputs open natively, preserve structure and never modify input.
- [ ] Document-wide reuse, fingerprint and cancellable progress are verified.
- [ ] No silent content loss or lossy formatting fallback; diagnostics and errors match the contract.
- [ ] Six checks and CI pass, docs match implementation and Feature #9010 closes only then.

## Out of Scope

Fit/shrink algorithms (P3), PDF (P4), persistent jobs/cache/auth/storage (P5), web UI (P6), rendering/edit tools (P7), enterprise integration (P8), OCR and new translation models.
