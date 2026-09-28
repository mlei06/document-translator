"""Reading and rewriting OOXML packages in tests (independent of the production adapters)."""

import re
import zipfile
from collections.abc import Callable
from pathlib import Path

from lxml import etree

__all__ = ["CJK", "NS", "entries", "rewrite", "texts", "xml"]

NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}
CJK = re.compile(r"[぀-ヿ㐀-䶿一-鿿]")


def entries(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as package:
        return {name: package.read(name) for name in package.namelist()}


def xml(path: Path, part: str) -> etree._Element:  # pyright: ignore[reportPrivateUsage]
    return etree.fromstring(entries(path)[part])


def texts(path: Path, part: str, tag: str) -> list[str]:
    """Text of every ``tag`` element (e.g. ``a:t``) in a part."""
    prefix, local = tag.split(":")
    return [e.text or "" for e in xml(path, part).iter(f"{{{NS[prefix]}}}{local}")]


def rewrite(source: Path, target: Path, part: str, edit: Callable[[bytes], bytes]) -> Path:
    """Copy a package, replacing one part's bytes through ``edit``."""
    with zipfile.ZipFile(source) as src, zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            data = src.read(info.filename)
            dst.writestr(info, edit(data) if info.filename == part else data)
    return target
