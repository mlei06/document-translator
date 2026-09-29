# /// script
# requires-python = ">=3.14"
# dependencies = ["pypdfium2==5.13.0", "pillow==12.1.1"]
# ///
# pyright: reportMissingImports=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Check translated PDFs with an independent engine: PDFium (the PDF engine of Chrome and Edge).

For each ``source=output`` pair: both open, page counts and sizes match, the output's text layer
(extracted by PDFium, not PyMuPDF) contains no CJK characters from the source when the target is
Latin, and each output page is rendered to PNG for visual review. Prints one JSON line per pair.

    uv run scripts/pdf_independent_check.py SOURCE.pdf=OUTPUT.pdf [SOURCE.pdf=OUTPUT.pdf ...]

Writes OUTPUT-pdfium-p<N>.png next to each output.
"""

import json
import re
import sys
from pathlib import Path

import pypdfium2 as pdfium

CJK = re.compile(r"[぀-ヿ㐀-鿿豈-﫿]")


def check(source: Path, output: Path) -> dict[str, object]:
    src, out = pdfium.PdfDocument(source), pdfium.PdfDocument(output)
    try:
        sizes_match = len(src) == len(out) and all(
            src[i].get_size() == out[i].get_size() for i in range(len(src))
        )
        cjk_left = 0
        characters = 0
        for index in range(len(out)):
            page = out[index]
            text = page.get_textpage().get_text_range()
            characters += len(text.strip())
            cjk_left += len(CJK.findall(text))
            image = page.render(scale=1.0).to_pil()
            image.save(output.with_name(f"{output.stem}-pdfium-p{index + 1}.png"))
        return {
            "source": source.name,
            "output": output.name,
            "pdfium": pdfium.PDFIUM_INFO.version,
            "pages": len(out),
            "sizes_match": sizes_match,
            "output_characters": characters,
            "cjk_characters_left": cjk_left,
        }
    finally:
        src.close()
        out.close()


def main() -> None:
    for pair in sys.argv[1:]:
        source, output = pair.split("=", 1)
        print(json.dumps(check(Path(source), Path(output))))


if __name__ == "__main__":
    main()
