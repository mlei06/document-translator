"""PDF page images for previews (read-only; PyMuPDF stays inside ``formats.pdf``, ADR-018)."""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportMissingTypeStubs=false, reportAttributeAccessIssue=false

from pathlib import Path
from typing import cast

import pymupdf

from doctranslator_core.types import InvalidDocumentError

__all__ = ["render_pages"]


def render_pages(path: Path, *, max_pages: int, width_px: int, quality: int = 80) -> list[bytes]:
    """JPEG images of the first ``max_pages`` pages, each ``width_px`` wide (aspect kept)."""
    try:
        doc = pymupdf.open(path, filetype="pdf")
    except Exception as exc:
        raise InvalidDocumentError("the PDF cannot be read") from exc
    try:
        images: list[bytes] = []
        for number in range(min(doc.page_count, max_pages)):
            page = doc[number]
            zoom = width_px / max(page.rect.width, 1.0)
            pixmap = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
            images.append(cast(bytes, pixmap.tobytes("jpeg", jpg_quality=quality)))
        return images
    finally:
        doc.close()
