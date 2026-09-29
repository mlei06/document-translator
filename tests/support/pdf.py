"""Synthetic PDFs for PDF adapter, pipeline and CLI tests, written with PyMuPDF's built-in fonts.

``china-s`` is PyMuPDF's built-in Simplified Chinese font (not embedded; viewers substitute a
system face) and ``helv`` is Helvetica. Every builder returns the path it wrote.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportMissingTypeStubs=false, reportAttributeAccessIssue=false

from pathlib import Path
from typing import Any, cast

import pymupdf

__all__ = [
    "LINK_URI",
    "drawings",
    "image_count",
    "links",
    "page_text",
    "text_blocks",
    "write_image_only",
    "write_mixed",
    "write_pdf",
]

LINK_URI = "https://intranet.example.com/q3"
CJK = "china-s"


def write_pdf(path: Path, build: Any, *, width: float = 595, height: float = 842) -> Path:
    """One page built by ``build(page)``."""
    doc = pymupdf.open()
    page = doc.new_page(width=width, height=height)
    build(page)
    doc.save(path)
    doc.close()
    return path


def _png(width: int, height: int) -> bytes:
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, width, height), False)
    pixmap.set_rect(pixmap.irect, (40, 120, 200))
    return cast(bytes, pixmap.tobytes("png"))


def write_mixed(path: Path) -> Path:
    """Heading, a two-line paragraph, a red span, a bulleted list, a two-cell table row inside
    filled cells, a centered label in a box, an underlined link, an image, a rule and a page
    number: the ordinary-text-and-artwork shapes the adapter must handle."""

    def build(page: pymupdf.Page) -> None:
        page.insert_text((72, 80), "季度业务回顾", fontname=CJK, fontsize=20)
        page.insert_text(
            (72, 120), "本季度销售额增长了百分之十二，主要原因是华东", fontname=CJK, fontsize=12
        )
        page.insert_text((72, 136), "地区的新客户数量显著增加。", fontname=CJK, fontsize=12)
        page.insert_text((72, 170), "成本控制", fontname=CJK, fontsize=12, color=(0.8, 0, 0))
        page.insert_text((120, 170), "措施取得了预期效果。", fontname=CJK, fontsize=12)
        for index, item in enumerate(("销售额增长", "利润率稳定", "客户数量增加")):
            page.insert_text((72, 210 + 18 * index), f"• {item}", fontname=CJK, fontsize=12)
        for x0, text in ((72, "华东地区"), (252, "华南地区")):
            page.draw_rect(
                pymupdf.Rect(x0, 280, x0 + 170, 310), color=(0, 0, 0), fill=(0.85, 0.9, 1)
            )
            page.insert_text((x0 + 6, 299), text, fontname=CJK, fontsize=12)
        page.draw_rect(pymupdf.Rect(72, 340, 232, 390), color=(0.1, 0.3, 0.5), fill=(0.1, 0.3, 0.5))
        page.insert_text((128, 370), "分析趋势", fontname=CJK, fontsize=12, color=(1, 1, 1))
        page.insert_text(
            (72, 430), "详情请见内部网站", fontname=CJK, fontsize=12, color=(0, 0, 0.8)
        )
        page.draw_line((72, 432), (168, 432), color=(0, 0, 0.8), width=0.8)
        page.insert_link(
            {"kind": pymupdf.LINK_URI, "from": pymupdf.Rect(72, 418, 168, 434), "uri": LINK_URI}
        )
        page.insert_image(pymupdf.Rect(360, 420, 520, 520), stream=_png(32, 20))
        page.draw_line((72, 560), (520, 560), color=(0.5, 0.5, 0.5), width=1)
        page.insert_text((290, 800), "3", fontname="helv", fontsize=10)

    return write_pdf(path, build)


def write_image_only(path: Path) -> Path:
    """A 'scanned' page: one image and no text layer."""

    def build(page: pymupdf.Page) -> None:
        page.insert_image(page.rect, stream=_png(60, 80))

    return write_pdf(path, build)


def page_text(path: Path, page: int = 0) -> str:
    with pymupdf.open(path) as doc:
        return cast(str, doc[page].get_text("text"))


def image_count(path: Path) -> int:
    with pymupdf.open(path) as doc:
        return sum(len(page.get_images()) for page in doc)


def drawings(path: Path, page: int = 0) -> list[tuple[float, float, float, float]]:
    with pymupdf.open(path) as doc:
        return [tuple(d["rect"]) for d in doc[page].get_drawings()]  # type: ignore[misc]


def links(path: Path, page: int = 0) -> list[str]:
    with pymupdf.open(path) as doc:
        return [str(link.get("uri")) for link in doc[page].get_links()]


def text_blocks(path: Path, page: int = 0) -> list[tuple[float, float, float, float]]:
    """The bounding boxes of a page's text blocks."""
    with pymupdf.open(path) as doc:
        layout = cast(dict[str, Any], doc[page].get_text("dict"))
    return [tuple(b["bbox"]) for b in layout["blocks"] if b["type"] == 0]
