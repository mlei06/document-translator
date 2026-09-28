# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportUnknownParameterType=false
# pyright: reportMissingTypeStubs=false, reportAttributeAccessIssue=false
"""Font provisioning: the font manifest and resolving document font names to files (P3, ADR-012).

The manifest lists every face in the configured font directories with its names (including
localized family names such as 微软雅黑), style and content hash. Resolution only ever uses fonts a
document names (plus metric-compatible aliases); an unavailable font is reported, never guessed.
"""

import hashlib
import io
import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

from fontTools.ttLib import TTCollection, TTFont, TTLibError

from doctranslator_core.types import FontFace, FontManifest

__all__ = [
    "METRIC_ALIASES",
    "FontLibrary",
    "LoadedFont",
    "build_font_manifest",
]

logger = logging.getLogger(__name__)

FONT_SUFFIXES = {".ttf", ".otf", ".ttc", ".otc"}
_NAME_IDS = (1, 4, 16)

METRIC_ALIASES: dict[str, tuple[str, ...]] = {
    "calibri": ("carlito",),
    "cambria": ("caladea",),
    "arial": ("liberation sans", "arimo"),
    "helvetica": ("arial", "liberation sans", "arimo"),
    "times new roman": ("liberation serif", "tinos"),
    "courier new": ("liberation mono", "cousine"),
}
"""Metric-compatible substitutes: same advance widths and vertical metrics by design."""


def build_font_manifest(
    directories: Sequence[Path], *, previous: FontManifest | None = None
) -> FontManifest:
    """Scan ``directories`` (recursively) for font files and describe every face.

    ``previous`` lets a caller skip re-reading files whose path, size and modification time are
    unchanged. Unreadable files are skipped with a warning; they are simply not available.
    """
    known: dict[tuple[str, int, int], list[FontFace]] = {}
    for face in previous.faces if previous is not None else ():
        known.setdefault((str(face.path), face.file_size, face.mtime_ns), []).append(face)
    faces: list[FontFace] = []
    for path in _font_files(directories):
        stat = path.stat()
        reused = known.get((str(path), stat.st_size, stat.st_mtime_ns))
        if reused:
            faces.extend(reused)
            continue
        try:
            faces.extend(_describe(path, stat.st_size, stat.st_mtime_ns))
        except (TTLibError, OSError, ValueError, KeyError, AssertionError) as exc:
            logger.warning("skipping unreadable font %s (%s)", path.name, type(exc).__name__)
    return FontManifest(faces=tuple(sorted(faces, key=lambda f: (str(f.path), f.index))))


def _font_files(directories: Sequence[Path]) -> Iterable[Path]:
    seen: set[Path] = set()
    for directory in directories:
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*")):
            if path.suffix.lower() in FONT_SUFFIXES and path.is_file() and path not in seen:
                seen.add(path)
                yield path


def _describe(path: Path, size: int, mtime_ns: int) -> list[FontFace]:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
    sha = digest.hexdigest()
    # Faces of a collection share one file handle: close it once, after reading every face.
    container = (
        TTCollection(str(path), lazy=True)
        if path.suffix.lower() in (".ttc", ".otc")
        else TTFont(str(path), lazy=True)
    )
    try:
        return _faces(container, path, sha, size, mtime_ns)
    finally:
        container.close()


def _faces(
    container: TTCollection | TTFont, path: Path, sha: str, size: int, mtime_ns: int
) -> list[FontFace]:
    fonts: list[TTFont] = (
        list(container.fonts) if isinstance(container, TTCollection) else [container]
    )
    faces: list[FontFace] = []
    for index, font in enumerate(fonts):
        names = _names(font, (1, 4))
        if not names:
            continue
        family = names[0]
        head = font["head"]
        os2 = font.get("OS/2")
        selection = int(os2.fsSelection) if os2 is not None else 0
        mac_style = int(head.macStyle)
        faces.append(
            FontFace(
                family=family,
                names=tuple(names),
                typographic_names=tuple(n for n in _names(font, (16,)) if n not in names),
                bold=bool(selection & 0x20 or mac_style & 0x1),
                italic=bool(selection & 0x1 or mac_style & 0x2),
                weight=int(os2.usWeightClass) if os2 is not None else 400,
                path=path,
                index=index,
                sha256=sha,
                file_size=size,
                mtime_ns=mtime_ns,
            )
        )
    return faces


def _names(font: TTFont, name_ids: tuple[int, ...]) -> list[str]:
    """Names with the given name IDs in that order, every language, without duplicates."""
    table = font["name"]
    ordered: list[str] = []
    for name_id in name_ids:
        for record in table.names:
            if record.nameID != name_id:
                continue
            try:
                value = record.toUnicode().strip()
            except UnicodeDecodeError:
                continue
            if value and value not in ordered:
                ordered.append(value)
    return ordered


@dataclass
class LoadedFont:
    """A face ready for shaping and metrics."""

    face: FontFace
    exact: bool
    """False when a metric-compatible alias stands in for the requested family."""

    @cached_property
    def _tables(self) -> TTFont:
        # Read from memory: no file handle stays open for the lifetime of the library.
        data = io.BytesIO(self.face.path.read_bytes())
        if self.face.path.suffix.lower() in (".ttc", ".otc"):
            return TTFont(data, fontNumber=self.face.index, lazy=True)
        return TTFont(data, lazy=True)

    @cached_property
    def units_per_em(self) -> int:
        return int(self._tables["head"].unitsPerEm)

    @cached_property
    def codepoints(self) -> frozenset[int]:
        cmap = self._tables.getBestCmap() or {}
        return frozenset(cmap)

    @cached_property
    def line_height_em(self) -> float:
        """Estimator for a font-metric single line height, in ems (ADR-012).

        Win ascent + descent plus any hhea line gap the win metrics do not already cover. This
        reproduced Word's line pitch for the Latin fonts compared (Calibri, Arial, Times New
        Roman); it is an estimate, not a claim about every font or application.
        """
        tables = self._tables
        hhea = tables["hhea"]
        hhea_sum = int(hhea.ascent) - int(hhea.descent)
        os2 = tables.get("OS/2")
        win_sum = int(os2.usWinAscent) + int(os2.usWinDescent) if os2 is not None else 0
        if win_sum <= 0:
            return (hhea_sum + int(hhea.lineGap)) / self.units_per_em
        extra = max(0, int(hhea.lineGap) - (win_sum - hhea_sum))
        return (win_sum + extra) / self.units_per_em

    @cached_property
    def blob(self) -> bytes:
        return self.face.path.read_bytes()

    def close(self) -> None:
        if "_tables" in self.__dict__:
            self._tables.close()
            del self.__dict__["_tables"]


@dataclass
class FontLibrary:
    """Resolves family names from documents to loaded faces in a manifest."""

    manifest: FontManifest
    _by_name: dict[str, list[FontFace]] = field(default_factory=dict[str, list[FontFace]])
    _by_typographic: dict[str, list[FontFace]] = field(default_factory=dict[str, list[FontFace]])
    _loaded: dict[tuple[str, int], LoadedFont] = field(
        default_factory=dict[tuple[str, int], LoadedFont]
    )

    def __post_init__(self) -> None:
        for face in self.manifest.faces:
            for name in face.names:
                self._by_name.setdefault(name.casefold(), []).append(face)
            for name in face.typographic_names:
                self._by_typographic.setdefault(name.casefold(), []).append(face)

    def close(self) -> None:
        """Release font files opened for metrics."""
        for font in self._loaded.values():
            font.close()

    def resolve(self, family: str, *, bold: bool, italic: bool) -> LoadedFont | None:
        """The face for ``family`` with the closest style, or ``None`` if it is not provisioned."""
        wanted = family.strip().casefold()
        for name, exact in ((wanted, True), *((a, False) for a in METRIC_ALIASES.get(wanted, ()))):
            # Office matches legacy family (ID 1) and full (ID 4) names; a typographic family
            # (ID 16) groups variants such as Display or Narrow and is only a last resort.
            candidates = self._by_name.get(name) or self._by_typographic.get(name)
            if not candidates:
                continue
            weight = 700 if bold else 400
            face = min(
                candidates,
                key=lambda f: ((f.bold != bold) + (f.italic != italic), abs(f.weight - weight)),
            )
            key = (str(face.path), face.index)
            loaded = self._loaded.get(key)
            if loaded is None:
                loaded = LoadedFont(face, exact)
                self._loaded[key] = loaded
            return loaded
        return None
