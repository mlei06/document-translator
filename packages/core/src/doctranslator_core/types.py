"""Public data types: languages, translation modes, options, results, fit report, errors."""

import hashlib
import json
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "LANGUAGE_NAMES",
    "DiagnosticSeverity",
    "DocumentDiagnostic",
    "DocumentError",
    "DocumentFormat",
    "DocumentLimitError",
    "DocumentTranslationOptions",
    "DocumentTranslationResult",
    "EngineAuthenticationError",
    "EngineInfo",
    "EngineResponseError",
    "EngineUnavailableError",
    "Extent",
    "FitEntry",
    "FitOptions",
    "FitReport",
    "FitStatus",
    "IdentityMismatchError",
    "InvalidDocumentError",
    "Language",
    "NoExtractableTextError",
    "OutputPathError",
    "ProgressPhase",
    "SegmentCounts",
    "SourceLanguageAmbiguousError",
    "TranslationError",
    "TranslationIdentity",
    "TranslationMode",
    "TranslationProgress",
    "UnsupportedDocumentError",
]


class Language(StrEnum):
    ZH = "zh"
    """Simplified Chinese."""
    EN = "en"
    JA = "ja"
    ES = "es"


LANGUAGE_NAMES: dict[Language, str] = {
    Language.ZH: "Simplified Chinese",
    Language.EN: "English",
    Language.JA: "Japanese",
    Language.ES: "Spanish",
}


class TranslationMode(StrEnum):
    LLM = "llm"
    MT = "mt"


class EngineInfo(BaseModel):
    """Identifies what produced a translation, for recording alongside results."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    mode: TranslationMode
    model: str
    details: dict[str, str]


class TranslationIdentity(BaseModel):
    """Everything about an engine configuration that can change its output (ADR-011).

    Prepared from configuration without loading a model (``prepare_identity``) and computed from a
    loaded engine (``Translator.identity``); the two are equal when a worker runs the configuration
    a job was fingerprinted with. Contains no credentials.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    mode: TranslationMode
    model: str
    details: dict[str, str]

    @property
    def digest(self) -> str:
        canonical = json.dumps(self.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class DocumentFormat(StrEnum):
    TXT = "txt"
    PPTX = "pptx"
    DOCX = "docx"
    XLSX = "xlsx"
    PDF = "pdf"


class FitOptions(BaseModel):
    """The shrink floor: a run never goes below ``max(min_size_pt, min_scale * original)``.

    A run that is already smaller than ``min_size_pt`` is never enlarged and never shrunk.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    min_scale: float = Field(default=0.7, ge=0.3, le=1.0)
    min_size_pt: float = Field(default=8.0, ge=1.0, le=72.0)


class DocumentTranslationOptions(BaseModel):
    """What the caller chooses for one document. Engine settings come from the ``Translator``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: Language | Literal["auto"] = "auto"
    target: Language
    protected_terms: tuple[str, ...] = ()
    """Terms that are never translated (exact, case-sensitive), e.g. product names."""
    txt_encoding: str | None = None
    """TXT only: the input's encoding. ``None`` means UTF-8, honouring a UTF-8/UTF-16 BOM."""
    fit: FitOptions = FitOptions()


class ProgressPhase(StrEnum):
    EXTRACT = "extract"
    TRANSLATE = "translate"
    FIT = "fit"
    WRITE = "write"


class TranslationProgress(BaseModel):
    """Reported between steps. ``done``/``total`` count unique engine inputs while translating."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    phase: ProgressPhase
    done: int
    total: int


class DiagnosticSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"


class DocumentDiagnostic(BaseModel):
    """Something the caller should know about a result. Never contains document text."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str
    severity: DiagnosticSeverity
    message: str
    location: str | None = None
    count: int = 1


class SegmentCounts(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    segments: int
    """Translatable paragraphs found in the document."""
    passed_through: int
    """Segments left unchanged without reaching the engine (no letters, protected, other script)."""
    unique_inputs: int
    """Distinct engine inputs after document-wide deduplication."""
    formatting_fallbacks: int = 0
    """Segments translated span by span because tagged output and projection both failed."""


class FitStatus(StrEnum):
    NOT_APPLICABLE = "not_applicable"
    """TXT, or a document with no fixed-size text containers."""
    PASSED = "passed"
    ADJUSTED = "adjusted"
    UNRESOLVED = "unresolved"


class Extent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    width_pt: float | None
    height_pt: float | None
    """``None`` for an unconstrained axis."""


class FitEntry(BaseModel):
    """One container that was adjusted or left unresolved. Never contains its text."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    location: str
    kind: str
    status: Literal["adjusted", "unresolved"]
    reason: str
    original_sizes_pt: list[float]
    final_sizes_pt: list[float]
    allowed: Extent | None
    original_extent: Extent | None
    translated_extent: Extent | None
    """At the original sizes, before any shrinking."""
    final_extent: Extent | None


class FitReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: int = 1
    format: DocumentFormat
    status: FitStatus
    measurement: str
    """Measurement strategy and version, e.g. ``harfbuzz-v1``; ``none`` when not applicable."""
    font_manifest: str | None
    """Digest of the provisioned font manifest used for measurement."""
    options: FitOptions
    inspected: int = 0
    unchanged: int = 0
    adjusted: int = 0
    unresolved: int = 0
    entries: list[FitEntry] = []


class DocumentTranslationResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    output_path: Path
    format: DocumentFormat
    source_requested: Language | Literal["auto"]
    source_resolved: Language | None
    """``None`` when the document has no translatable text."""
    target: Language
    engine: EngineInfo
    fingerprint: str
    counts: SegmentCounts
    diagnostics: list[DocumentDiagnostic]
    fit_report: FitReport

    @property
    def fit_status(self) -> FitStatus:
        return self.fit_report.status


class TranslationError(Exception):
    """Base exception for all translation failures."""


class EngineUnavailableError(TranslationError):
    """The engine cannot be reached or loaded."""


class EngineAuthenticationError(TranslationError):
    """The LLM server rejected the credentials. Never retried."""


class EngineResponseError(TranslationError):
    """The engine answered, but the answer is unusable."""


class IdentityMismatchError(TranslationError):
    """The loaded engine is not the identity a fingerprint was computed for."""


class DocumentError(TranslationError):
    """The document cannot be translated as requested. Messages contain no document text."""

    code = "document_error"


class UnsupportedDocumentError(DocumentError):
    """Not a supported format, or a supported format with unsupported protection or content."""

    code = "unsupported_document"


class InvalidDocumentError(DocumentError):
    """The file claims a supported format but is malformed."""

    code = "invalid_document"


class DocumentLimitError(DocumentError):
    """The document exceeds a configured resource limit. Nothing is truncated."""

    code = "document_limit"


class SourceLanguageAmbiguousError(DocumentError):
    """Automatic detection cannot decide the source language; pass it explicitly."""

    code = "source_ambiguous"


class NoExtractableTextError(DocumentError):
    """A PDF has no extractable text (for example a scan). OCR is out of scope."""

    code = "no_extractable_text"


class OutputPathError(DocumentError):
    """The output path is the input, already exists, or cannot be written."""

    code = "output_path"
