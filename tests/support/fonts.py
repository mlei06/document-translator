"""A deterministic synthetic font for fit tests (no dependence on installed fonts).

"Test Sans": every printable ASCII and Latin-1 character advances 500 units (0.5 em), space
included; CJK ideographs, kana and full-width punctuation advance 1000 units (1 em); units per em
1000; hhea and win ascent 800, descent 200, no line gap, so Word-style line height is 1.0 em.
"""

# pyright: reportUnknownMemberType=false, reportMissingTypeStubs=false
from pathlib import Path

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

from doctranslator_core.fit.fonts import build_font_manifest
from doctranslator_core.types import FontManifest

__all__ = ["TEST_FONT", "synthetic_font_manifest"]

TEST_FONT = "Test Sans"
_CJK_RANGES = [(0x3000, 0x303F), (0x3040, 0x30FF), (0x4E00, 0x9FFF), (0xFF00, 0xFFEF)]


def _box(width: int) -> object:
    pen = TTGlyphPen(None)
    pen.moveTo((50, 0))
    pen.lineTo((50, 700))
    pen.lineTo((width - 50, 700))
    pen.lineTo((width - 50, 0))
    pen.closePath()
    return pen.glyph()


def _write(path: Path) -> None:
    builder = FontBuilder(1000, isTTF=True)
    glyphs = [".notdef", "latin", "space", "cjk"]
    builder.setupGlyphOrder(glyphs)
    cmap: dict[int, str] = {0x20: "space"}
    cmap.update({code: "latin" for code in range(0x21, 0x7F)})
    cmap.update({code: "latin" for code in range(0xA0, 0x100)})
    for start, end in _CJK_RANGES:
        cmap.update({code: "cjk" for code in range(start, end + 1)})
    builder.setupCharacterMap(cmap)
    builder.setupGlyf({".notdef": _box(500), "latin": _box(500), "space": TTGlyphPen(None).glyph(),
                       "cjk": _box(1000)})
    builder.setupHorizontalMetrics({".notdef": (500, 50), "latin": (500, 50), "space": (500, 0),
                                    "cjk": (1000, 50)})
    builder.setupHorizontalHeader(ascent=800, descent=-200, lineGap=0)
    builder.setupNameTable({"familyName": TEST_FONT, "styleName": "Regular"})
    builder.setupOS2(sTypoAscender=800, sTypoDescender=-200, sTypoLineGap=0, usWinAscent=800,
                     usWinDescent=200, usWeightClass=400, fsSelection=0x40,
                     ulCodePageRange1=0x1)
    builder.setupPost()
    builder.save(str(path))


def synthetic_font_manifest(directory: Path) -> FontManifest:
    """Write the synthetic font into ``directory`` and return a manifest containing only it."""
    fonts = directory / "fonts"
    fonts.mkdir(exist_ok=True)
    _write(fonts / "TestSans.ttf")
    return build_font_manifest([fonts])
