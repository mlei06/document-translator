# /// script
# requires-python = ">=3.14"
# dependencies = ["pypdfium2==5.13.0", "pillow==12.1.1"]
# ///
"""Rasterize PDF pages to PNG for visual inspection of native-application exports.

Usage (from the repository root):

    uv run scripts/render_pdf_pages.py FILE.pdf [FILE.pdf ...] [--scale 1.5] [--pages 1,3]

Writes FILE.pdf.p<N>.png next to each PDF. Used with scripts/native_office_check.ps1, whose PDFs
come from Word/Excel/PowerPoint themselves, so the images show what the native application renders.
"""

import argparse
from pathlib import Path

import pypdfium2 as pdfium


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--scale", type=float, default=1.5)
    parser.add_argument("--pages", default="", help="comma-separated 1-based page numbers")
    args = parser.parse_args()
    wanted = {int(p) for p in args.pages.split(",") if p}
    for path in args.files:
        pdf = pdfium.PdfDocument(path)
        for index in range(len(pdf)):
            if wanted and index + 1 not in wanted:
                continue
            image = pdf[index].render(scale=args.scale).to_pil()
            target = path.with_name(f"{path.name}.p{index + 1}.png")
            image.save(target)
            print(target)
        pdf.close()


if __name__ == "__main__":
    main()
