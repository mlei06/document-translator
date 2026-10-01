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
    "DocumentDetection",
    "DocumentDiagnostic",
    "DocumentError",
    "DocumentFormat",
    "DocumentLimitError",
    "DocumentTranslationOptions",
    "DocumentTranslationResult",
    "EngineAuthenticationError",
    "EngineEndpointUnavailableError",
    "EngineInfo",
    "EnginePolicyDeniedError",
    "EngineResponseError",
    "EngineUnavailableError",
    "Extent",
    "FitEntry",
    "FitOptions",
    "FitReport",
    "FitStatus",
    "FontFace",
    "FontManifest",
    "IdentityMismatchError",
    "InvalidDocumentError",
    "Language",
    "LayoutUnresolvableError",
    "NoExtractableTextError",
    "OutputPathError",
    "ProgressPhase",
    "SegmentCounts",
    "SourceLanguageAmbiguousError",
    "TextUnit",
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


class FontFace(BaseModel):
    """One provisioned font face: a file (and face index for collections) with its names."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    family: str
    """Family name as documents reference it (name ID 1, or 16 when present)."""
    names: tuple[str, ...]
    """Family (name ID 1) and full (ID 4) names in every language, e.g. 微软雅黑."""
    typographic_names: tuple[str, ...] = ()
    """Typographic family names (ID 16) not already in ``names``; matched only as a fallback."""
    bold: bool
    italic: bool
    weight: int = 400
    """OS/2 weight class; picks Regular over Light/Medium faces of one typographic family."""
    path: Path
    index: int = 0
    sha256: str
    file_size: int = 0
    mtime_ns: int = 0
    """Size and modification time let a rebuild skip unchanged files; not part of the digest."""


class FontManifest(BaseModel):
    """The fonts available for fit measurement and PDF output. ``digest`` ignores file paths."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    faces: tuple[FontFace, ...]

    @property
    def digest(self) -> str:
        entries = sorted(
            (
                f.family,
                f.bold,
                f.italic,
                f.weight,
                f.index,
                f.sha256,
                sorted(f.names),
                sorted(f.typographic_names),
            )
            for f in self.faces
        )
        canonical = json.dumps(entries, ensure_ascii=False)
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

    mode: Literal["standard"] = "standard"
    min_scale: float = Field(default=0.7, ge=0.3, le=1.0)
    min_size_pt: float = Field(default=8.0, ge=1.0, le=72.0)


class DocumentTranslationOptions(BaseModel):
    """What the caller chooses for one document. Engine settings come from the ``Translator``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: Language | Literal["auto"] = "auto"
    target: Language
    protected_terms: tuple[str, ...] = ()
    """Terms that are never translated (exact, case-sensitive), e.g. product names."""
    use_default_dictionary: bool = True
    """Protect the maintained product/company names in addition to caller terms."""
    txt_encoding: str | None = None
    """TXT only: the input's encoding. ``None`` means UTF-8, honouring a UTF-8/UTF-16 BOM."""
    fit: FitOptions = FitOptions()


class ProgressPhase(StrEnum):
    EXTRACT = "extract"
    TRANSLATE = "translate"
    APPLY = "apply"
    """Translations (including formatting fallbacks) are being placed into the document."""
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
    SKIPPED = "skipped"
    """The caller stopped the remaining optional fit work (ADR-012 owner amendment): translation
    and adjustments already applied are kept; unvisited containers are not reported."""


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
    operations: tuple[str, ...] = ()
    original_bounds_pt: tuple[float, float, float, float] | None = None
    final_bounds_pt: tuple[float, float, float, float] | None = None
    original_fonts: tuple[tuple[str | None, str | None], ...] = ()
    final_fonts: tuple[tuple[str | None, str | None], ...] = ()
    original_spacing_pt: tuple[tuple[float, float], ...] = ()
    final_spacing_pt: tuple[tuple[float, float], ...] = ()
    timings_s: dict[str, float] = Field(default_factory=dict[str, float])


class FitReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: Literal[1, 2] = 2
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
    """Optional display metadata; unknown or mixed content still translates."""
    target: Language
    engine: EngineInfo
    fingerprint: str
    counts: SegmentCounts
    diagnostics: list[DocumentDiagnostic]
    fit_report: FitReport
    timings_s: dict[str, float] = {}
    """Seconds per phase (extract, translate, fit, write); not part of the cached report."""

    @property
    def fit_status(self) -> FitStatus:
        return self.fit_report.status


class DocumentDetection(BaseModel):
    """What a document is before translation: its verified format and detected source language.

    Language is optional display metadata. Unknown, mixed and ambiguous documents translate
    without a source selection or a different inference profile.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    format: DocumentFormat
    source: Language | None
    status: Literal["detected", "ambiguous", "unknown", "mixed", "no_text"]
    confidence: float | None = Field(default=None, ge=0, le=1)
    segments: int | None = None
    diagnostics: list[DocumentDiagnostic] = Field(default_factory=list[DocumentDiagnostic])


class TextUnit(BaseModel):
    """One translatable paragraph's text with its stable location, for previews.

    ``group`` is the page-like part it belongs to: a slide, sheet, document part, PDF page or a
    run of TXT lines.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    location: str
    group: str
    text: str


class TranslationError(Exception):
    """Base exception for all translation failures."""


class EngineUnavailableError(TranslationError):
    """The engine cannot be reached or loaded."""


class EngineEndpointUnavailableError(EngineUnavailableError):
    """Shared endpoint connectivity failed, rather than one model request timing out."""


class EngineAuthenticationError(TranslationError):
    """The LLM server rejected the credentials. Never retried."""


class EnginePolicyDeniedError(TranslationError):
    """The endpoint explicitly denied policy or hard quota. Never retried or rerouted."""


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


class LayoutUnresolvableError(DocumentError):
    """Complete translated text cannot be placed within legal regions and font floors."""

    code = "layout_unresolvable"


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
