# /// script
# requires-python = ">=3.14"
# dependencies = ["pymupdf==1.28.2"]
# ///
"""P4.0 PDF strategy spike: targeted text replacement with PyMuPDF (redact text, keep artwork).

Run from the repository root after exporting the fixture deck to PDF (see README):

    uv run docs/experiments/pdf-strategy/spike.py

For each input PDF: read text blocks (``get_text("dict")``), "translate" each block with a
deterministic fake (Latin text 1.6x the source length, keeping span styles), remove only text inside
each block (redaction with images and vector graphics preserved), and place the translation with
``insert_htmlbox`` (bold/colour/size per span, provisioned fonts embedded, shrink-to-fit bounded by
the ADR-012 floor). Then verify: output reopens; no source CJK text remains extractable; images and
drawings count unchanged; pixels outside the replaced text rectangles unchanged; how many blocks fit.
Writes outputs and results.json under data/experiments/pdf-strategy/.
"""

import json
import os
import sys
from pathlib import Path

import pymupdf

OUT = Path("data/experiments/pdf-strategy")
CJK = range(0x4E00, 0xA000)
FONTS = Path(os.environ.get("WINDIR", "C:\\Windows")) / "Fonts"


def make_text_pdf(path: Path) -> None:
    """A synthetic 'ordinary text' PDF: heading, paragraphs, bold and coloured spans (Chinese)."""
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    archive = pymupdf.Archive(str(FONTS))
    css = '@font-face {font-family: yh; src: url(msyh.ttc);} * {font-family: yh;}'
    html = (
        "<h2>季度业务回顾</h2>"
        "<p>本季度销售额增长了<b>百分之十二</b>，主要原因是华东地区的新客户数量显著增加。</p>"
        "<p>利润率保持稳定，<span style='color:#c00000'>成本控制</span>措施取得了预期效果。"
        "管理层将在下个季度继续推进数字化转型项目。</p>"
        "<p>详情请访问 https://intranet.example.com/q3 或联系财务部门。</p>"
    )
    page.insert_htmlbox(pymupdf.Rect(60, 60, 535, 500), html, css=css, archive=archive)
    doc.save(path)


def fake_translate(text: str) -> str:
    words = ["revenue", "growth", "customers", "region", "stable", "quarter", "report", "costs"]
    count = max(1, int(len(text) * 1.6 / 7))
    return " ".join(words[i % len(words)] for i in range(count))


def process(source: Path) -> dict[str, object]:
    doc = pymupdf.open(source)
    output = OUT / f"{source.stem}.en.pdf"
    archive = pymupdf.Archive(str(FONTS))
    css = '@font-face {font-family: sans; src: url(arial.ttf);} ' \
          '@font-face {font-family: sans; src: url(arialbd.ttf); font-weight: bold;} * {font-family: sans;}'
    stats: dict[str, object] = {"blocks": 0, "fitted": 0, "shrunk": 0, "overflow": 0}
    before = {}
    for page in doc:
        before[page.number] = (len(page.get_images()), len(page.get_drawings()),
                               page.get_pixmap(dpi=72))
        blocks = [b for b in page.get_text("dict")["blocks"] if b["type"] == 0]
        placements = []
        for block in blocks:
            spans = [s for line in block["lines"] for s in line["spans"] if s["text"].strip()]
            if not spans or not any(ord(c) in CJK for s in spans for c in s["text"]):
                continue
            stats["blocks"] = int(stats["blocks"]) + 1  # type: ignore[call-overload]
            rect = pymupdf.Rect(block["bbox"])
            size = max(s["size"] for s in spans)
            html = "".join(
                f'<span style="font-size:{s["size"]:.1f}pt;color:#{s["color"]:06x};'
                f'font-weight:{"bold" if s["flags"] & 16 else "normal"}">{fake_translate(s["text"])} </span>'
                for s in spans
            )
            placements.append((rect, html, size))
            page.add_redact_annot(rect)
        page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE,
                              graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
                              text=pymupdf.PDF_REDACT_TEXT_REMOVE)
        for rect, html, size in placements:
            floor = min(1.0, max(0.7, 8.0 / size)) if size > 8 else 1.0
            spare, scale = page.insert_htmlbox(rect, html, css=css, archive=archive,
                                               scale_low=floor)
            if spare < 0:
                stats["overflow"] = int(stats["overflow"]) + 1  # type: ignore[call-overload]
            elif scale < 1:
                stats["shrunk"] = int(stats["shrunk"]) + 1  # type: ignore[call-overload]
            else:
                stats["fitted"] = int(stats["fitted"]) + 1  # type: ignore[call-overload]
    doc.save(output, garbage=3, deflate=True)
    reopened = pymupdf.open(output)
    cjk_left = sum(1 for page in reopened for c in page.get_text() if ord(c) in CJK)
    artwork_same = True
    pixel_diff_outside = 0
    for page in reopened:
        images, drawings, pix_before = before[page.number]
        if len(page.get_images()) != images or len(page.get_drawings()) < drawings:
            artwork_same = False
        pix_after = page.get_pixmap(dpi=72)
        text_rects = [pymupdf.Rect(b["bbox"]) for b in page.get_text("dict")["blocks"]]
        text_rects += [pymupdf.Rect(b["bbox"]) for b in pymupdf.open(source)[page.number].get_text("dict")["blocks"]]
        for y in range(0, pix_after.height, 4):
            for x in range(0, pix_after.width, 4):
                point = pymupdf.Point(x, y)
                if any(point in r for r in text_rects):
                    continue
                if pix_after.pixel(x, y) != pix_before.pixel(x, y):
                    pixel_diff_outside += 1
    stats |= {"output": str(output), "pages": len(reopened), "source_cjk_chars_left": cjk_left,
              "artwork_counts_preserved": artwork_same,
              "sampled_pixels_changed_outside_text": pixel_diff_outside,
              "size_bytes": output.stat().st_size}
    return stats


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # pyright: ignore[reportAttributeAccessIssue]
    OUT.mkdir(parents=True, exist_ok=True)
    text_pdf = OUT / "text-zh.pdf"
    make_text_pdf(text_pdf)
    sources = [text_pdf, Path("data/experiments/pdf/deck-zh.pptx.pdf")]
    results = {"pymupdf": pymupdf.__version__, "cases": {s.name: process(s) for s in sources}}
    (OUT / "results.json").write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
