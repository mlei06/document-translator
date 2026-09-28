"""Document Translator core: the public API.

Apps import only from this module and ``doctranslator_core.types`` (ADR-003).
"""

from pathlib import Path

from doctranslator_core.config import DocumentLimits, EngineConfig, LlmEngineConfig, MtEngineConfig
from doctranslator_core.formats import detect_format as _detect_format
from doctranslator_core.identity import output_fingerprint, prepare_identity
from doctranslator_core.translator import Translator
from doctranslator_core.types import DocumentFormat

__all__ = [
    "DocumentLimits",
    "EngineConfig",
    "LlmEngineConfig",
    "MtEngineConfig",
    "Translator",
    "inspect_document",
    "output_fingerprint",
    "prepare_identity",
]


def inspect_document(path: Path, *, limits: DocumentLimits | None = None) -> DocumentFormat:
    """Identify and validate a document's format without translating it (Document API)."""
    return _detect_format(path, limits or DocumentLimits())
