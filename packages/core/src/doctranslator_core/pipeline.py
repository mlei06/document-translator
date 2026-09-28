"""Orchestrates one document translation: extract, translate, apply, fit, write, publish.

The pipeline composes a format adapter and a text translator through their interfaces; it never
imports an engine or a specific format (ADR-003). Formatting follows ADR-011: tagged translation,
then projection, then the per-span fallback.
"""

import contextlib
import logging
import os
import secrets
import shutil
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from doctranslator_core.config import DocumentLimits
from doctranslator_core.detect import detect_source
from doctranslator_core.document import Paragraph
from doctranslator_core.formats import DocumentAdapter, detect_format, open_adapter
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
    DocumentDiagnostic,
    DocumentFormat,
    DocumentLimitError,
    DocumentTranslationOptions,
    DocumentTranslationResult,
    EngineInfo,
    EngineResponseError,
    FitReport,
    FitStatus,
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
        self, texts: Sequence[str], *, source: Language, target: Language
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


_NO_TEXT = DocumentDiagnostic(
    code="no_translatable_text",
    severity=DiagnosticSeverity.INFO,
    message="The document has no translatable text; the output is an unchanged copy.",
)
_ALREADY_TARGET = DocumentDiagnostic(
    code="already_target_language",
    severity=DiagnosticSeverity.INFO,
    message="The document is already in the target language; the output is an unchanged copy.",
)


def translate_document(
    translator: TextTranslator,
    input_path: Path,
    output_path: Path,
    *,
    options: DocumentTranslationOptions,
    fingerprint: str,
    limits: DocumentLimits,
    on_progress: ProgressCallback | None = None,
) -> DocumentTranslationResult:
    """Translate ``input_path`` into a new file at ``output_path`` (see the Document API)."""
    if options.source != "auto" and options.source == options.target:
        raise ValueError(f"source and target language are both {options.target.value!r}")
    _check_paths(input_path, output_path)
    started = time.perf_counter()
    report = _reporter(on_progress)
    fmt = detect_format(input_path, limits)
    adapter = open_adapter(fmt, input_path, limits, options)
    try:
        report(ProgressPhase.EXTRACT, 0, 1)
        paragraphs = adapter.paragraphs()
        if len(paragraphs) > limits.max_segments:
            raise DocumentLimitError(
                f"document has {len(paragraphs)} paragraphs (limit {limits.max_segments})"
            )
        protected = {p.id: protect(p.nodes, options.protected_terms) for p in paragraphs}
        report(ProgressPhase.EXTRACT, 1, 1)
        extract_s = time.perf_counter() - started

        diagnostics: list[DocumentDiagnostic] = []
        source: Language | None
        if options.source == "auto":
            source, notes = detect_source(_translatable_text(protected[p.id]) for p in paragraphs)
            diagnostics.extend(notes)
        else:
            source = options.source
        if source is None or source == options.target:
            diagnostics.append(_NO_TEXT if source is None else _ALREADY_TARGET)
            report(ProgressPhase.WRITE, 0, 1)
            _publish_copy(input_path, output_path, report)
            counts = SegmentCounts(
                segments=len(paragraphs), passed_through=len(paragraphs), unique_inputs=0
            )
            return _result(
                output_path, fmt, options, source, translator, fingerprint, counts, diagnostics
            )

        units: dict[str, _Unit] = {}
        passed = 0
        for paragraph in paragraphs:
            nodes = protected[paragraph.id]
            if passes_through(nodes, source):
                passed += 1
                continue
            encoded = encode(nodes)
            unit = units.setdefault(encoded.text, _Unit(encoded.text))
            unit.occurrences.append(_Occurrence(paragraph, nodes, encoded))

        def translate(texts: list[str]) -> list[str]:
            return translator.translate_texts(texts, source=source, target=options.target)

        results, fallbacks = _translate_units(
            list(units.values()), translate, options.target, report, diagnostics
        )
        translate_s = time.perf_counter() - started - extract_s
        for paragraph_id, nodes in results.items():
            adapter.apply(paragraph_id, nodes, options.target)
        report(ProgressPhase.FIT, 0, 1)
        report(ProgressPhase.FIT, 1, 1)
        _write_verify_publish(adapter, output_path, fmt, limits, options, report)
        diagnostics.extend(adapter.diagnostics)
        logger.info(
            "translated %s: %d paragraphs, %d unique inputs, %d passed through, "
            "%d formatting fallbacks; extract %.2f s, translate %.2f s, total %.2f s",
            fmt.value,
            len(paragraphs),
            len(units),
            passed,
            fallbacks,
            extract_s,
            translate_s,
            time.perf_counter() - started,
        )
        counts = SegmentCounts(
            segments=len(paragraphs),
            passed_through=passed,
            unique_inputs=len(units),
            formatting_fallbacks=fallbacks,
        )
        return _result(
            output_path, fmt, options, source, translator, fingerprint, counts, diagnostics
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
        normalized = normalize_tag_whitespace(unit.output)
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
        normalized = normalize_tag_whitespace(projected)
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
) -> None:
    """Write to a temporary file, reopen it as the same format, then publish atomically."""
    temporary = _temporary_path(output_path)
    try:
        report(ProgressPhase.WRITE, 0, 1)
        adapter.save(temporary)
        _verify(temporary, fmt, limits, options)
        report(ProgressPhase.WRITE, 1, 1)
        publish(temporary, output_path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()


def _verify(
    path: Path, fmt: DocumentFormat, limits: DocumentLimits, options: DocumentTranslationOptions
) -> None:
    """Reopen the written file as the same format and read its paragraphs again."""
    if detect_format(path, limits) is not fmt:
        raise InvalidDocumentError("the written output is not a valid document")
    reopened = open_adapter(fmt, path, limits, options)
    try:
        reopened.paragraphs()
    finally:
        reopened.close()


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


def _publish_copy(input_path: Path, output_path: Path, report: _Report) -> None:
    temporary = _temporary_path(output_path)
    try:
        shutil.copyfile(input_path, temporary)
        report(ProgressPhase.WRITE, 1, 1)
        publish(temporary, output_path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()


def _result(
    output_path: Path,
    fmt: DocumentFormat,
    options: DocumentTranslationOptions,
    source: Language | None,
    translator: TextTranslator,
    fingerprint: str,
    counts: SegmentCounts,
    diagnostics: list[DocumentDiagnostic],
) -> DocumentTranslationResult:
    status = FitStatus.NOT_APPLICABLE if fmt is DocumentFormat.TXT else FitStatus.NOT_RUN
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
        fit_report=FitReport(
            format=fmt,
            status=status,
            measurement="none",
            font_manifest=None,
            options=options.fit,
        ),
    )
