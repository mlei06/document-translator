"""Output identity and the cache fingerprint (ADR-007 layer 2, ADR-011 section 6)."""

import hashlib
import json
from importlib.metadata import PackageNotFoundError, version

from doctranslator_core.config import EngineConfig
from doctranslator_core.engines import prepare_identity as _prepare_engine_identity
from doctranslator_core.protect import default_dictionary_digest
from doctranslator_core.types import (
    DocumentTranslationOptions,
    FontManifest,
    TranslationIdentity,
)

__all__ = ["STRATEGIES", "core_version", "output_fingerprint", "prepare_identity"]

FINGERPRINT_SCHEMA = 2

STRATEGIES: dict[str, str] = {
    "pipeline": "pipeline-v3-target-only-standard",
    "inline": "inline-v1",
    "protect": "protect-v2",
    "detect": "detect-v1-lingua-2.2.0",
    "txt": "txt-v1",
    "pptx": "pptx-v2-offline-fit",
    "docx": "docx-v2-offline-fit",
    "xlsx": "xlsx-v1",
    "pdf": "pdf-v2-pymupdf-1.28.2",
    "fit": "fit-v2",
    "measure": "harfbuzz-v1",
}
"""Version of every output-affecting strategy. Bump the entry when its behavior changes."""


def core_version() -> str:
    try:
        return version("doctranslator-core")
    except PackageNotFoundError:  # pragma: no cover - only when running from a bare source tree
        return "0+unknown"


def prepare_identity(config: EngineConfig) -> TranslationIdentity:
    """The output identity for ``config`` without loading a model or contacting a server."""
    return _prepare_engine_identity(config)


def output_fingerprint(
    identity: TranslationIdentity,
    options: DocumentTranslationOptions,
    fonts: FontManifest | None = None,
) -> str:
    """Deterministic SHA-256 of everything that determines a translated document's bytes."""
    payload = {
        "schema": FINGERPRINT_SCHEMA,
        "core_version": core_version(),
        "strategies": {k: v for k, v in STRATEGIES.items() if k != "detect"},
        "identity": identity.model_dump(mode="json"),
        "options": options.model_dump(mode="json", exclude={"source"}),
        "font_manifest": fonts.digest if fonts is not None else None,
        "default_dictionary": default_dictionary_digest()
        if options.use_default_dictionary
        else None,
    }
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
