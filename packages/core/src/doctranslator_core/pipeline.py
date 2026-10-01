"""Orchestrates one document translation: extract, translate, apply, fit, write, publish.

The pipeline composes a format adapter and a text translator through their interfaces; it never
imports an engine or a specific format (ADR-003). Formatting follows ADR-011: tagged translation,
then projection, then the per-span fallback.
"""

import contextlib
import logging
import os
import secrets
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from doctranslator_core.config import DocumentLimits
from doctranslator_core.detect import detect_source
from doctranslator_core.document import LayoutContainer, Paragraph
from doctranslator_core.fit.fitter import fit_container
from doctranslator_core.fit.fonts import FontLibrary
from doctranslator_core.fit.office import fit_office_container
from doctranslator_core.formats import DocumentAdapter, detect_format, open_adapter
from doctranslator_core.formats.base import LayoutRepairSupport, LayoutSupport, PlacementFit
from doctranslator_core.identity import STRATEGIES
from doctranslator_core.inline import (
    Encoded,
    Inline,
    Text,
    Wrap,
    decode,
    encode,
    join_segmented,
    normalize_tag_whitespace,
    project,
    segmented_pieces,
    span_texts,
    strip_paired_tags,
    validate,
)
from doctranslator_core.protect import passes_through, protect
from doctranslator_core.types import (
    DiagnosticSeverity,
    DocumentDetection,
    DocumentDiagnostic,
    DocumentFormat,
    DocumentLimitError,
    DocumentTranslationOptions,
    DocumentTranslationResult,
    EngineInfo,
    EngineResponseError,
    FitEntry,
    FitOptions,
    FitReport,
    FitStatus,
    FontManifest,
    InvalidDocumentError,
    Language,
    OutputPathError,
    ProgressPhase,
    SegmentCounts,
    TranslationProgress,
)

__all__ = ["PIPELINE_BATCH", "TextTranslator", "publish", "translate_document"]

logger = logging.getLogger(__name__)

PIPELINE_BATCH = 64
"""Unique engine inputs per translation step (one progress/cancellation point per step)."""
MAX_LOCATED_DIAGNOSTICS = 100

type ProgressCallback = Callable[[TranslationProgress], None]
type _Report = Callable[[ProgressPhase, int, int], None]
type _Translate = Callable[[list[str]], list[str]]


class TextTranslator(Protocol):
    @property
    def engine_info(self) -> EngineInfo: ...

    def translate_texts(
        self, texts: Sequence[str], *, source: Language | None, target: Language
    ) -> list[str]: ...


@dataclass
class _Occurrence:
    paragraph: Paragraph
    nodes: list[Inline]
    encoded: Encoded


@dataclass
class _Unit:
    """One unique engine input and every paragraph that produced it."""

    text: str
    occurrences: list[_Occurrence] = field(default_factory=list[_Occurrence])
    output: str = ""


def translate_document(
    translator: TextTranslator,
    input_path: Path,
    output_path: Path,
    *,
    options: DocumentTranslationOptions,
    fingerprint: str,
    limits: DocumentLimits,
    fonts: FontManifest | None = None,
    on_progress: ProgressCallback | None = None,
    font_library: FontLibrary | None = None,
    should_skip_fit: Callable[[], bool] | None = None,
    detection_metadata: DocumentDetection | None = None,
) -> DocumentTranslationResult:
    """Translate ``input_path`` into a new file at ``output_path`` (see the Document API).

    ``should_skip_fit`` is polled during fitting; once it returns true the remaining optional fit
    work stops (translation and adjustments already applied are kept) and the result records
    ``FitStatus.SKIPPED``.
    """
    _check_paths(input_path, output_path)
    started = time.perf_counter()
    report = _reporter(on_progress)
    report(ProgressPhase.EXTRACT, 0, 1)  # before parsing, so reading time is visible
    fmt = detect_format(input_path, limits)
    adapter = open_adapter(fmt, input_path, limits, options)
    try:
        paragraphs = adapter.paragraphs()
        if len(paragraphs) > limits.max_segments:
            raise DocumentLimitError(
                f"document has {len(paragraphs)} paragraphs (limit {limits.max_segments})"
            )
        protected = {
            p.id: protect(
                p.nodes,
                options.protected_terms,
                use_default_dictionary=options.use_default_dictionary,
            )
            for p in paragraphs
        }
        report(ProgressPhase.EXTRACT, 1, 1)
        extract_s = time.perf_counter() - started

        diagnostics: list[DocumentDiagnostic] = []
        source: Language | None
        if detection_metadata is not None:
            source = detection_metadata.source
            diagnostics.extend(detection_metadata.diagnostics)
        elif options.source == "auto":
            try:
                source, notes = detect_source(
                    _translatable_text(protected[p.id]) for p in paragraphs
                )
                diagnostics.extend(notes)
            except Exception:
                # Detection is display metadata only. An unavailable detector cannot stop inference.
                source = None
                diagnostics.append(
                    DocumentDiagnostic(
                        code="source_unknown",
                        severity=DiagnosticSeverity.INFO,
                        message="Source language is unknown; translation uses the selected target.",
                    )
                )
        else:
            source = options.source

        units: dict[str, _Unit] = {}
        passed = 0
        for paragraph in paragraphs:
            nodes = protected[paragraph.id]
            if passes_through(nodes):
                passed += 1
                continue
            encoded = encode(nodes)
            unit = units.setdefault(encoded.text, _Unit(encoded.text))
            unit.occurrences.append(_Occurrence(paragraph, nodes, encoded))

        empty_preserved = 0

        def translate(texts: list[str]) -> list[str]:
            nonlocal empty_preserved
            outputs = translator.translate_texts(texts, source=None, target=options.target)
            safe: list[str] = []
            for text, output in zip(texts, outputs, strict=True):
                if text.strip() and not output.strip():
                    # Keep the encoded source, including protected/formatting markers. A blank
                    # model answer must neither erase this text nor discard valid siblings.
                    empty_preserved += 1
                    safe.append(text)
                else:
                    safe.append(output)
            return safe

        results, fallbacks = _translate_units(
            list(units.values()), translate, options.target, report, diagnostics
        )
        if empty_preserved:
            diagnostics.append(
                DocumentDiagnostic(
                    code="empty_translation_preserved",
                    severity=DiagnosticSeverity.WARNING,
                    message=(
                        "Some text could not be translated and was kept in its original language."
                    ),
                    count=empty_preserved,
                )
            )
        translate_s = time.perf_counter() - started - extract_s
        originals = _containers(adapter)
        report(ProgressPhase.APPLY, 0, 1)
        for paragraph_id, nodes in results.items():
            adapter.apply(paragraph_id, nodes, options.target)
        report(ProgressPhase.APPLY, 1, 1)
        fit_started = time.perf_counter()
        fit_report = _fit(
            adapter, originals, options.fit, fonts, fmt, report, font_library, should_skip_fit
        )
        fit_s = time.perf_counter() - fit_started
        write_started = time.perf_counter()
        verified_report = _write_verify_publish(
            adapter,
            output_path,
            fmt,
            limits,
            options,
            report,
            fit_report=fit_report,
        )
        if verified_report is not None:
            fit_report = verified_report
        write_s = time.perf_counter() - write_started
        diagnostics.extend(adapter.diagnostics)
        logger.info(
            "translated %s: %d paragraphs, %d unique inputs, %d passed through, "
            "%d formatting fallbacks; extract %.2f s, translate %.2f s, fit %.2f s, "
            "write %.2f s, total %.2f s",
            fmt.value,
            len(paragraphs),
            len(units),
            passed,
            fallbacks,
            extract_s,
            translate_s,
            fit_s,
            write_s,
            time.perf_counter() - started,
        )
        counts = SegmentCounts(
            segments=len(paragraphs),
            passed_through=passed,
            unique_inputs=len(units),
            formatting_fallbacks=fallbacks,
        )
        return _result(
            output_path,
            fmt,
            options,
            source,
            translator,
            fingerprint,
            counts,
            diagnostics,
            fit_report,
            {"extract": extract_s, "translate": translate_s, "fit": fit_s, "write": write_s},
        )
    finally:
        adapter.close()


def _translatable_text(nodes: Sequence[Inline]) -> str:
    parts: list[str] = []
    for node in nodes:
        if isinstance(node, Text):
            parts.append(node.text)
        elif isinstance(node, Wrap):
            parts.append(_translatable_text(node.children))
    return "".join(parts)


def _reporter(on_progress: ProgressCallback | None) -> _Report:
    def report(phase: ProgressPhase, done: int, total: int) -> None:
        if on_progress is not None:
            on_progress(TranslationProgress(phase=phase, done=done, total=total))

    return report


def _translate_units(
    units: list[_Unit],
    translate: _Translate,
    target: Language,
    report: _Report,
    diagnostics: list[DocumentDiagnostic],
) -> tuple[dict[int, list[Inline]], int]:
    """Translate every unit; returns translated nodes per paragraph id and the fallback count."""
    total = len(units)
    report(ProgressPhase.TRANSLATE, 0, total)
    for start in range(0, total, PIPELINE_BATCH):
        batch = units[start : start + PIPELINE_BATCH]
        for unit, output in zip(batch, translate([u.text for u in batch]), strict=True):
            unit.output = output
        report(ProgressPhase.TRANSLATE, min(start + PIPELINE_BATCH, total), total)

    results: dict[int, list[Inline]] = {}
    failed: list[_Unit] = []
    for unit in units:
        representative = unit.occurrences[0].encoded
        if not representative.has_tags:
            if not unit.output.strip():
                raise EngineResponseError("the engine returned an empty translation")
            for occ in unit.occurrences:
                results[occ.paragraph.id] = decode(occ.encoded, unit.output)
            continue
        normalized = normalize_tag_whitespace(unit.output, unit.text)
        if validate(representative, normalized) is None:
            for occ in unit.occurrences:
                results[occ.paragraph.id] = decode(occ.encoded, normalized)
        else:
            failed.append(unit)
    if not failed:
        return results, 0
    remaining = _project(failed, translate, results, report, total)
    fallbacks = _segmented(remaining, translate, target, results, report, total, diagnostics)
    return results, fallbacks


def _project(
    failed: list[_Unit],
    translate: _Translate,
    results: dict[int, list[Inline]],
    report: _Report,
    total: int,
) -> list[_Unit]:
    """Projection for units whose tagged output failed validation; returns those still failing."""
    requests: list[str] = []
    for unit in failed:
        encoded = unit.occurrences[0].encoded
        requests.append(strip_paired_tags(encoded.text))
        requests.extend(span_texts(encoded).values())
    translated = _translate_unique(requests, translate, report, total)
    remaining: list[_Unit] = []
    for unit in failed:
        encoded = unit.occurrences[0].encoded
        spans = {ident: translated[text] for ident, text in span_texts(encoded).items()}
        projected = project(encoded, translated[strip_paired_tags(encoded.text)], spans)
        if projected is None:
            remaining.append(unit)
            continue
        normalized = normalize_tag_whitespace(projected, unit.text)
        for occ in unit.occurrences:
            results[occ.paragraph.id] = decode(occ.encoded, normalized)
    return remaining


def _segmented(
    units: list[_Unit],
    translate: _Translate,
    target: Language,
    results: dict[int, list[Inline]],
    report: _Report,
    total: int,
    diagnostics: list[DocumentDiagnostic],
) -> int:
    """Per-span fallback: every run translated separately, keeping its own formatting."""
    if not units:
        return 0
    requests = [piece for unit in units for piece in segmented_pieces(unit.occurrences[0].nodes)]
    translated = _translate_unique([p for p in requests if p.strip()], translate, report, total)
    locations: list[str] = []
    for unit in units:
        for occ in unit.occurrences:
            results[occ.paragraph.id] = join_segmented(occ.nodes, translated, target)
            locations.append(occ.paragraph.location)
    for location in locations[:MAX_LOCATED_DIAGNOSTICS]:
        diagnostics.append(
            DocumentDiagnostic(
                code="formatting_fallback",
                severity=DiagnosticSeverity.WARNING,
                location=location,
                message="The engine could not keep this paragraph's inline formatting; each "
                "formatted part was translated separately, which can read less naturally.",
            )
        )
    if len(locations) > MAX_LOCATED_DIAGNOSTICS:
        diagnostics.append(
            DocumentDiagnostic(
                code="formatting_fallback",
                severity=DiagnosticSeverity.WARNING,
                message="More paragraphs were translated part by part than are listed.",
                count=len(locations) - MAX_LOCATED_DIAGNOSTICS,
            )
        )
    return len(locations)


def _translate_unique(
    texts: list[str], translate: _Translate, report: _Report, total: int
) -> dict[str, str]:
    unique = list(dict.fromkeys(texts))
    translated: dict[str, str] = {}
    for start in range(0, len(unique), PIPELINE_BATCH):
        batch = unique[start : start + PIPELINE_BATCH]
        translated.update(zip(batch, translate(batch), strict=True))
        # Recovery runs after the main pass: progress stays at the total, but the callback still
        # runs between batches so cancellation is honoured.
        report(ProgressPhase.TRANSLATE, total, total)
    return translated


def _write_verify_publish(
    adapter: DocumentAdapter,
    output_path: Path,
    fmt: DocumentFormat,
    limits: DocumentLimits,
    options: DocumentTranslationOptions,
    report: _Report,
    *,
    fit_report: FitReport | None = None,
) -> FitReport | None:
    """Write to a temporary file, reopen it as the same format, then publish atomically."""
    temporary = _temporary_path(output_path)
    expected = _run_sizes(adapter)
    try:
        report(ProgressPhase.WRITE, 0, 1)
        adapter.save(temporary)
        _verify(adapter, temporary, fmt, limits, options, expected)
        report(ProgressPhase.WRITE, 1, 1)
        publish(temporary, output_path)
        return fit_report
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()


def _verify(
    adapter: DocumentAdapter,
    path: Path,
    fmt: DocumentFormat,
    limits: DocumentLimits,
    options: DocumentTranslationOptions,
    expected: dict[str, list[list[float]]] | None,
) -> None:
    """Reopen the written file as the same format, read its paragraphs again, check that every
    container's run sizes in the file are the sizes the fit check applied, then run the format's
    own output checks."""
    if detect_format(path, limits) is not fmt:
        raise InvalidDocumentError("the written output is not a valid document")
    reopened = open_adapter(fmt, path, limits, options)
    try:
        reopened.paragraphs()
        if expected is not None and _run_sizes(reopened) != expected:
            raise InvalidDocumentError("the written output does not contain the fitted font sizes")
        if (
            isinstance(adapter, LayoutRepairSupport)
            and isinstance(reopened, LayoutRepairSupport)
            and _effective_layout(adapter) != _effective_layout(reopened)
        ):
            raise InvalidDocumentError("the written output does not contain the fitted layout")
        adapter.verify_output(reopened)
    finally:
        reopened.close()


def _run_sizes(adapter: DocumentAdapter) -> dict[str, list[list[float]]] | None:
    """Effective run sizes per container, rounded to 0.01 pt, as the adapter reads them."""
    if not isinstance(adapter, LayoutSupport):
        return None
    return {
        c.id: [[round(r.size_pt, 2) for r in p.runs] for p in c.paragraphs]
        for c in adapter.layout_containers()
    }


def _effective_layout(adapter: LayoutRepairSupport) -> list[object]:
    """Serialized properties only: dynamic growth limits/revisions are not file contents."""
    return [
        (
            c.id,
            c.width_pt,
            c.height_pt,
            c.bounds_pt,
            c.content_bounds_pt,
            tuple(
                (
                    p.space_before_pt,
                    p.space_after_pt,
                    tuple(
                        (r.text, r.size_pt, r.latin_font, r.east_asian_font, r.bold, r.italic)
                        for r in p.runs
                    ),
                )
                for p in c.paragraphs
            ),
        )
        for c in adapter.layout_context()
    ]


def _check_paths(input_path: Path, output_path: Path) -> None:
    if not input_path.is_file():
        raise OutputPathError("input is not an existing regular file")
    if output_path.exists() or output_path.is_symlink():
        raise OutputPathError("output path already exists")
    if not output_path.parent.is_dir():
        raise OutputPathError("output directory does not exist")
    if output_path.resolve() == input_path.resolve():
        raise OutputPathError("output path is the input file")


def _temporary_path(output_path: Path) -> Path:
    """A hidden sibling that keeps the output's suffix, so it can be verified as that format."""
    token = secrets.token_hex(6)
    return output_path.with_name(f".{output_path.stem}.{token}.partial{output_path.suffix}")


def publish(temporary: Path, output_path: Path) -> None:
    """Move a finished temporary file to ``output_path`` atomically, never overwriting."""
    try:
        os.link(temporary, output_path)
    except FileExistsError as exc:
        raise OutputPathError("output path already exists") from exc
    except OSError:
        if os.name != "nt":
            raise
        try:
            temporary.rename(output_path)  # on Windows, rename fails if the target exists
        except FileExistsError as exc:
            raise OutputPathError("output path already exists") from exc
        return
    temporary.unlink()


def _containers(adapter: DocumentAdapter) -> list[LayoutContainer] | None:
    """The original fit baseline, described before any translation is applied."""
    if isinstance(adapter, LayoutRepairSupport):
        return adapter.layout_context()
    return adapter.layout_containers() if isinstance(adapter, LayoutSupport) else None


def _fit(
    adapter: DocumentAdapter,
    originals: list[LayoutContainer] | None,
    options: FitOptions,
    fonts: FontManifest | None,
    fmt: DocumentFormat,
    report: _Report,
    shared: FontLibrary | None = None,
    should_skip: Callable[[], bool] | None = None,
) -> FitReport:
    """Fit every container against its original and apply the chosen sizes (ADR-012)."""
    if isinstance(adapter, PlacementFit):
        outcomes, skipped = adapter.place(options, fonts, should_skip)
        return _placement_report(outcomes, fmt, options, fonts, report, skipped=skipped)
    if originals is None or not isinstance(adapter, LayoutSupport):
        if fmt is DocumentFormat.TXT:  # no fixed-size containers
            return FitReport(
                format=fmt,
                status=FitStatus.NOT_APPLICABLE,
                measurement="none",
                font_manifest=None,
                options=options,
            )
        # A required format without layout support is unresolved, never not applicable.
        missing = FitEntry(
            location="document",
            kind="document",
            status="unresolved",
            reason="fit_unsupported_for_format",
            original_sizes_pt=[],
            final_sizes_pt=[],
            allowed=None,
            original_extent=None,
            translated_extent=None,
            final_extent=None,
        )
        return FitReport(
            format=fmt,
            status=FitStatus.UNRESOLVED,
            measurement="unsupported",
            font_manifest=None,
            options=options,
            unresolved=1,
            entries=[missing],
        )
    translated = {c.id: c for c in adapter.layout_containers()}
    library = shared if shared is not None else (FontLibrary(fonts) if fonts is not None else None)
    try:
        entries: list[FitEntry] = []
        unchanged = adjusted = unresolved = inspected = 0
        skipped = False
        stop = should_skip or (lambda: False)
        report(ProgressPhase.FIT, 0, len(originals))
        for index, original in enumerate(originals):
            if stop():
                skipped = True
                break
            current = (
                next(c for c in adapter.layout_context() if c.id == original.id)
                if isinstance(adapter, LayoutRepairSupport)
                else translated[original.id]
            )
            if _same_text(original, current):
                unchanged += 1  # untranslated text cannot introduce new overflow
            else:
                if isinstance(adapter, LayoutRepairSupport):
                    outcome = fit_office_container(
                        original,
                        current,
                        options,
                        library,
                        adapter.apply_layout_patch,
                        adapter.layout_context,
                        stop,
                    )
                else:
                    outcome = fit_container(original, current, options, library, stop)
                if outcome.status == "skipped":
                    skipped = True
                    break
                if outcome.sizes is not None:
                    adapter.apply_run_sizes(original.id, outcome.sizes)
                if outcome.entry is not None:
                    entries.append(outcome.entry)
                if outcome.status == "unchanged":
                    unchanged += 1
                elif outcome.status == "adjusted":
                    adjusted += 1
                else:
                    unresolved += 1
            inspected += 1
            report(ProgressPhase.FIT, index + 1, len(originals))
    finally:
        if library is not None and library is not shared:
            library.close()
    if skipped:
        status = FitStatus.SKIPPED
    elif not originals:
        status = FitStatus.NOT_APPLICABLE
    elif unresolved:
        status = FitStatus.UNRESOLVED
    elif adjusted:
        status = FitStatus.ADJUSTED
    else:
        status = FitStatus.PASSED
    return FitReport(
        format=fmt,
        status=status,
        measurement=STRATEGIES["measure"],
        font_manifest=fonts.digest if fonts is not None else None,
        options=options,
        inspected=inspected,
        unchanged=unchanged,
        adjusted=adjusted,
        unresolved=unresolved,
        entries=entries,
    )


def _placement_report(
    outcomes: list[FitEntry | None],
    fmt: DocumentFormat,
    options: FitOptions,
    fonts: FontManifest | None,
    report: _Report,
    *,
    skipped: bool = False,
) -> FitReport:
    """The fit report for a format whose writer placed and fitted every changed unit."""
    report(ProgressPhase.FIT, len(outcomes), len(outcomes))
    entries = [e for e in outcomes if e is not None]
    adjusted = sum(1 for e in entries if e.status == "adjusted")
    unresolved = len(entries) - adjusted
    if skipped:
        status = FitStatus.SKIPPED
    elif not outcomes:
        status = FitStatus.NOT_APPLICABLE
    elif unresolved:
        status = FitStatus.UNRESOLVED
    elif adjusted:
        status = FitStatus.ADJUSTED
    else:
        status = FitStatus.PASSED
    return FitReport(
        format=fmt,
        status=status,
        measurement=STRATEGIES[fmt.value],
        font_manifest=fonts.digest if fonts is not None else None,
        options=options,
        inspected=len(outcomes),
        adjusted=adjusted,
        unresolved=unresolved,
        entries=entries,
    )


def _same_text(original: LayoutContainer, current: LayoutContainer) -> bool:
    def texts(container: LayoutContainer) -> list[str]:
        return ["".join(r.text for r in p.runs) for p in container.paragraphs]

    return texts(original) == texts(current)


def _result(
    output_path: Path,
    fmt: DocumentFormat,
    options: DocumentTranslationOptions,
    source: Language | None,
    translator: TextTranslator,
    fingerprint: str,
    counts: SegmentCounts,
    diagnostics: list[DocumentDiagnostic],
    fit_report: FitReport,
    timings: dict[str, float],
) -> DocumentTranslationResult:
    return DocumentTranslationResult(
        output_path=output_path,
        format=fmt,
        source_requested=options.source,
        source_resolved=source,
        target=options.target,
        engine=translator.engine_info,
        fingerprint=fingerprint,
        counts=counts,
        diagnostics=diagnostics,
        fit_report=fit_report,
        timings_s={k: round(v, 3) for k, v in timings.items()},
    )
