"""Preview packages (ADR-017): what the web UI shows before a user downloads a result.

A package is one ZIP blob: ``manifest.json`` plus, for PDF, JPEG images of the original and
translated pages. Text formats pair the original's and the output's text units by location;
PDF lists each page's units without pairing and relies on the rendered pages.
"""

import json
import logging
import zipfile
from pathlib import Path
from typing import Any

from doctranslator_core import document_text, render_pdf_pages
from doctranslator_core.types import DocumentFormat, TextUnit

__all__ = ["MAX_PAGES", "build_preview", "read_manifest", "read_member"]

logger = logging.getLogger(__name__)

MAX_PAGES = 30
PAGE_WIDTH = 1000
MAX_UNITS = 5000


def _grouped(units: list[TextUnit]) -> dict[str, list[TextUnit]]:
    groups: dict[str, list[TextUnit]] = {}
    for unit in units:
        groups.setdefault(unit.group, []).append(unit)
    return groups


def build_preview(fmt: str, source: Path, output: Path, destination: Path) -> Path | None:
    """Write the package to ``destination``; ``None`` (logged) if it cannot be built."""
    try:
        return _build(DocumentFormat(fmt), source, output, destination)
    except Exception:
        logger.warning("preview not built for %s", source.name, exc_info=True)
        return None


def _build(fmt: DocumentFormat, source: Path, output: Path, destination: Path) -> Path:
    original = document_text(source)
    translated = document_text(output)
    truncated = len(original) > MAX_UNITS
    manifest: dict[str, Any] = {"version": 1, "format": fmt.value, "pages": [], "groups": []}
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as package:
        if fmt is DocumentFormat.PDF:
            before = render_pdf_pages(source, max_pages=MAX_PAGES, width_px=PAGE_WIDTH)
            after = render_pdf_pages(output, max_pages=MAX_PAGES, width_px=PAGE_WIDTH)
            for number, (a, b) in enumerate(zip(before, after, strict=False), start=1):
                package.writestr(f"source-{number}.jpg", a, compress_type=zipfile.ZIP_STORED)
                package.writestr(f"target-{number}.jpg", b, compress_type=zipfile.ZIP_STORED)
                manifest["pages"].append(
                    {
                        "number": number,
                        "source": f"source-{number}.jpg",
                        "target": f"target-{number}.jpg",
                    }
                )
            truncated = truncated or len(before) >= MAX_PAGES
            source_groups, target_groups = _grouped(original), _grouped(translated)
            for name in dict.fromkeys([*source_groups, *target_groups]):
                manifest["groups"].append(
                    {
                        "name": name,
                        "paired": False,
                        "source": [u.text for u in source_groups.get(name, [])],
                        "target": [u.text for u in target_groups.get(name, [])],
                    }
                )
        else:
            by_location = {u.location: u.text for u in translated}
            for name, units in _grouped(original[:MAX_UNITS]).items():
                manifest["groups"].append(
                    {
                        "name": name,
                        "paired": True,
                        "units": [
                            {
                                "location": u.location,
                                "source": u.text,
                                "target": by_location.get(u.location, u.text),
                            }
                            for u in units
                        ],
                    }
                )
        manifest["truncated"] = truncated
        package.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
    return destination


def read_manifest(package: Path) -> dict[str, Any]:
    with zipfile.ZipFile(package) as archive:
        return json.loads(archive.read("manifest.json"))


def read_member(package: Path, name: str) -> bytes | None:
    """An image listed in the manifest; ``None`` for any other name."""
    with zipfile.ZipFile(package) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        allowed = {page[side] for page in manifest["pages"] for side in ("source", "target")}
        if name not in allowed:
            return None
        return archive.read(name)
