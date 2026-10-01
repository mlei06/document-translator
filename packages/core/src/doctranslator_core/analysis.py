"""Read-only document analysis for surfaces: detection before translation and preview text.

Nothing here translates or writes documents. Both functions open the same format adapters the
pipeline uses, so what they report is exactly what translation would see.
"""

import re
from pathlib import Path

from doctranslator_core.config import DocumentLimits
from doctranslator_core.detect import detect_source
from doctranslator_core.formats import detect_format, open_adapter
from doctranslator_core.inline import Inline, Text, Wrap, plain_text
from doctranslator_core.protect import protect
from doctranslator_core.types import (
    DiagnosticSeverity,
    DocumentDetection,
    DocumentDiagnostic,
    DocumentFormat,
    DocumentTranslationOptions,
    Language,
    SourceLanguageAmbiguousError,
    TextUnit,
)

__all__ = ["TXT_LINES_PER_GROUP", "detect_document", "document_text", "group_of"]

TXT_LINES_PER_GROUP = 40
_OPTIONS = DocumentTranslationOptions(target=Language.EN)
"""Adapters need options only for TXT encoding; the default (UTF-8 with BOM detection) applies."""
_LINE = re.compile(r"^line (\d+)$")


def _translatable(nodes: tuple[Inline, ...] | list[Inline]) -> str:
    parts: list[str] = []
    for node in nodes:
        if isinstance(node, Text):
            parts.append(node.text)
        elif isinstance(node, Wrap):
            parts.append(_translatable(list(node.children)))
    return "".join(parts)


def detect_document(path: Path, *, limits: DocumentLimits | None = None) -> DocumentDetection:
    """The document's format and source language, as translation would detect them.

    Raises the same ``DocumentError`` subclasses as translation for unsupported, invalid,
    oversized or text-less (``NoExtractableTextError``) documents.
    """
    limits = limits or DocumentLimits()
    fmt = detect_format(path, limits)
    adapter = open_adapter(fmt, path, limits, _OPTIONS)
    try:
        paragraphs = adapter.paragraphs()
        texts = [_translatable(protect(p.nodes, ())) for p in paragraphs]
    finally:
        adapter.close()
    try:
        source, notes = detect_source(texts)
    except SourceLanguageAmbiguousError as exc:
        note = DocumentDiagnostic(code=exc.code, severity=DiagnosticSeverity.INFO, message=str(exc))
        return DocumentDetection(
            format=fmt,
            source=None,
            status="ambiguous",
            segments=len(paragraphs),
            diagnostics=[note],
        )
    except Exception:
        return DocumentDetection(
            format=fmt,
            source=None,
            status="unknown",
            segments=len(paragraphs),
            diagnostics=[
                DocumentDiagnostic(
                    code="source_unknown",
                    severity=DiagnosticSeverity.INFO,
                    message="Source language is unknown; translation uses the selected target.",
                )
            ],
        )
    status = (
        "mixed"
        if any(note.code == "source_mixed" for note in notes)
        else "detected"
        if source is not None
        else "unknown"
        if any(ch.isalpha() for text in texts for ch in text)
        else "no_text"
    )
    return DocumentDetection(
        format=fmt, source=source, status=status, segments=len(paragraphs), diagnostics=notes
    )


def group_of(fmt: DocumentFormat, location: str) -> str:
    """The page-like part a location belongs to (slide, sheet, document part, page, lines)."""
    match fmt:
        case DocumentFormat.PPTX:
            head = location.split(" / ", 1)[0]
            return head.removesuffix(" notes")
        case DocumentFormat.DOCX | DocumentFormat.XLSX:
            return location.split(" / ", 1)[0]
        case DocumentFormat.PDF:
            return location.split(", ", 1)[0]
        case DocumentFormat.TXT:
            found = _LINE.match(location)
            if found is None:
                return "text"
            index = (int(found.group(1)) - 1) // TXT_LINES_PER_GROUP
            first = index * TXT_LINES_PER_GROUP + 1
            return f"lines {first}-{first + TXT_LINES_PER_GROUP - 1}"


def document_text(path: Path, *, limits: DocumentLimits | None = None) -> list[TextUnit]:
    """Every translatable paragraph's plain text with its location and group, in order."""
    limits = limits or DocumentLimits()
    fmt = detect_format(path, limits)
    adapter = open_adapter(fmt, path, limits, _OPTIONS)
    try:
        return [
            TextUnit(location=p.location, group=group_of(fmt, p.location), text=plain_text(p.nodes))
            for p in adapter.paragraphs()
        ]
    finally:
        adapter.close()
