"""Font provisioning for the local CLI: configured directories and a cached manifest (ADR-012)."""

import contextlib
import logging
import os
from pathlib import Path

from pydantic import ValidationError

from doctranslator_core import build_font_manifest
from doctranslator_core.types import FontManifest

__all__ = ["default_font_directories", "load_font_manifest"]

logger = logging.getLogger(__name__)


def default_font_directories() -> list[Path]:
    """Platform font directories; on Windows including Office's cloud-font cache."""
    if os.name == "nt":
        windows = Path(os.environ.get("WINDIR", "C:\\Windows")) / "Fonts"
        local = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
        return [
            windows,
            local / "Microsoft" / "Windows" / "Fonts",
            local / "Microsoft" / "FontCache" / "4" / "CloudFonts",
        ]
    return [Path("/usr/share/fonts"), Path("/usr/local/share/fonts"), Path.home() / ".fonts"]


def _cache_path() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache")))
    return base / "doctranslator" / "font-manifest.json"


def load_font_manifest(directories: list[Path]) -> FontManifest:
    """Build the manifest, reusing the cached entries of unchanged font files."""
    cache = _cache_path()
    previous: FontManifest | None = None
    with contextlib.suppress(OSError, ValidationError, ValueError):
        previous = FontManifest.model_validate_json(cache.read_text(encoding="utf-8"))
    manifest = build_font_manifest(directories, previous=previous)
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(manifest.model_dump_json(), encoding="utf-8")
    except OSError as exc:
        logger.warning("font manifest cache not written: %s", exc.strerror)
    return manifest
