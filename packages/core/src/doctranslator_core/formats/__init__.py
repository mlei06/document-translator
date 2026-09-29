"""Format registry: identify a file's format from its content and open its adapter."""

from pathlib import Path

from doctranslator_core.config import DocumentLimits
from doctranslator_core.formats._ooxml import CONTENT_TYPES, Package
from doctranslator_core.formats.base import DocumentAdapter
from doctranslator_core.types import (
    DocumentFormat,
    DocumentLimitError,
    DocumentTranslationOptions,
    InvalidDocumentError,
    UnsupportedDocumentError,
)

__all__ = ["DocumentAdapter", "detect_format", "open_adapter"]

_EXTENSIONS = {f".{fmt.value}": fmt for fmt in DocumentFormat}
_OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_MACRO_TYPES = ("macroEnabled", "template", "slideshow")


def detect_format(path: Path, limits: DocumentLimits) -> DocumentFormat:
    """The format of ``path`` from its content; the extension must agree.

    Raises ``UnsupportedDocumentError`` for other formats, legacy/encrypted Office files, macro,
    template and slideshow variants, signed packages and mismatched extensions;
    ``InvalidDocumentError`` for malformed files; ``DocumentLimitError`` for oversized ones.
    """
    if not path.is_file():
        raise InvalidDocumentError("input is not a regular file")
    claimed = _EXTENSIONS.get(path.suffix.lower())
    if claimed is None:
        raise UnsupportedDocumentError(
            f"unsupported file extension {path.suffix!r}; supported: .txt .pptx .docx .xlsx .pdf"
        )
    with path.open("rb") as handle:
        head = handle.read(8)
    if head.startswith(_OLE):
        raise UnsupportedDocumentError(
            "legacy binary or password-protected Office files are not supported"
        )
    if head.startswith(b"PK\x03\x04") or head.startswith(b"PK\x05\x06"):
        actual = _ooxml_format(path, limits)
    elif head.startswith(b"%PDF-"):
        actual = DocumentFormat.PDF
    elif claimed is DocumentFormat.TXT:
        actual = DocumentFormat.TXT
    else:
        raise InvalidDocumentError(f"the file content is not a {claimed.value.upper()} document")
    if actual is not claimed:
        raise UnsupportedDocumentError(
            f"the file content is {actual.value.upper()} but the extension is {path.suffix!r}"
        )
    if actual in (DocumentFormat.TXT, DocumentFormat.PDF):
        size = path.stat().st_size
        if size > limits.max_text_bytes:
            raise DocumentLimitError(f"file is {size} bytes (limit {limits.max_text_bytes})")
    return actual


def _ooxml_format(path: Path, limits: DocumentLimits) -> DocumentFormat:
    package = Package.open(path, limits)
    try:
        if not package.has("[Content_Types].xml"):
            raise UnsupportedDocumentError("ZIP file is not an Office Open XML package")
        main_type = package.content_type(package.main_part()) or ""
    finally:
        package.close()
    for fmt, content_type in CONTENT_TYPES.items():
        if main_type == content_type:
            return DocumentFormat(fmt)
    if any(marker in main_type for marker in _MACRO_TYPES):
        raise UnsupportedDocumentError(
            "macro-enabled, template and slideshow Office files are not supported"
        )
    raise UnsupportedDocumentError("unsupported Office package type")


def open_adapter(
    fmt: DocumentFormat,
    path: Path,
    limits: DocumentLimits,
    options: DocumentTranslationOptions,
) -> DocumentAdapter:
    """Open ``path`` with the adapter for ``fmt`` (already verified by ``detect_format``)."""
    match fmt:
        case DocumentFormat.TXT:
            from doctranslator_core.formats.txt import TxtAdapter

            return TxtAdapter(path, options.txt_encoding)
        case DocumentFormat.PPTX:
            from doctranslator_core.formats.pptx import PptxAdapter

            return PptxAdapter(path, limits)
        case DocumentFormat.DOCX:
            from doctranslator_core.formats.docx import DocxAdapter

            return DocxAdapter(path, limits)
        case DocumentFormat.XLSX:
            from doctranslator_core.formats.xlsx import XlsxAdapter

            return XlsxAdapter(path, limits)
        case DocumentFormat.PDF:
            from doctranslator_core.formats.pdf import PdfAdapter

            return PdfAdapter(path, limits)
