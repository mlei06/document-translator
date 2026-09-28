"""Shared low-level OOXML package access for PPTX, DOCX and XLSX (ADR-009, ADR-011).

``Package`` opens a ZIP under resource limits, parses XML parts securely, resolves relationships
and writes a copy in which only modified parts are re-serialized; every other entry's payload is
copied byte-for-byte. No translation or format policy lives here.
"""

import posixpath
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Self
from xml.sax.saxutils import escape

from lxml import etree

from doctranslator_core.config import DocumentLimits
from doctranslator_core.types import (
    DocumentLimitError,
    InvalidDocumentError,
    UnsupportedDocumentError,
)

__all__ = [
    "CONTENT_TYPES",
    "NS",
    "Element",
    "Package",
    "Relationship",
    "parse_xml",
    "qn",
]

type Element = etree._Element  # pyright: ignore[reportPrivateUsage]
"""An lxml element; lxml names its element class ``_Element``."""

NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "wps": "http://schemas.microsoft.com/office/word/2010/wordprocessingShape",
    "v": "urn:schemas-microsoft-com:vml",
    "c": "http://schemas.openxmlformats.org/drawingml/2006/chart",
    "dgm": "http://schemas.openxmlformats.org/drawingml/2006/diagram",
    "xdr": "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing",
    "m": "http://schemas.openxmlformats.org/officeDocument/2006/math",
    "pr": "http://schemas.openxmlformats.org/package/2006/relationships",
    "ct": "http://schemas.openxmlformats.org/package/2006/content-types",
}

REL_OFFICE_DOCUMENT = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
)
CONTENT_TYPES = {
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml",
}

_PARSER = etree.XMLParser(
    resolve_entities=False,
    no_network=True,
    load_dtd=False,
    dtd_validation=False,
    huge_tree=False,
    remove_blank_text=False,
)


def qn(tag: str) -> str:
    """Clark notation for a prefixed name: ``qn("w:t")`` -> ``{...main}t``."""
    prefix, local = tag.split(":")
    return f"{{{NS[prefix]}}}{local}"


def parse_xml(data: bytes, part: str) -> Element:
    """Parse a package part without entity expansion, DTDs or network access."""
    try:
        root = etree.fromstring(data, _PARSER)
    except etree.XMLSyntaxError as exc:
        raise InvalidDocumentError(f"malformed XML in package part {part}") from exc
    if root.getroottree().docinfo.doctype:
        raise InvalidDocumentError(f"package part {part} declares a DTD, which OOXML never does")
    return root


@dataclass(frozen=True, slots=True)
class Relationship:
    id: str
    type: str
    target: str
    """Resolved package part name (no leading slash), or the raw URI for external targets."""
    external: bool


class Package:
    """An OOXML package opened for targeted editing."""

    def __init__(self, path: Path, limits: DocumentLimits) -> None:
        self.path = path
        try:
            self._zip = zipfile.ZipFile(path)
        except (zipfile.BadZipFile, OSError) as exc:
            raise InvalidDocumentError("not a valid ZIP package") from exc
        try:
            self._infos = self._zip.infolist()
            _check_limits(self._infos, limits)
        except BaseException:
            self._zip.close()
            raise
        self._names = {info.filename for info in self._infos}
        self._xml: dict[str, Element] = {}
        self._modified: set[str] = set()
        self._content_types: tuple[dict[str, str], dict[str, str]] | None = None

    @classmethod
    def open(cls, path: Path, limits: DocumentLimits) -> Self:
        return cls(path, limits)

    def close(self) -> None:
        self._zip.close()

    @property
    def names(self) -> set[str]:
        return set(self._names)

    def has(self, name: str) -> bool:
        return name in self._names

    def read(self, name: str) -> bytes:
        if name not in self._names:
            raise InvalidDocumentError(f"package part {name} is missing")
        return self._zip.read(name)

    def xml(self, name: str) -> Element:
        """The parsed part, cached; edits to it are saved after ``mark_modified``."""
        if name not in self._xml:
            self._xml[name] = parse_xml(self.read(name), name)
        return self._xml[name]

    def mark_modified(self, name: str) -> None:
        self._modified.add(name)

    @property
    def modified(self) -> set[str]:
        return set(self._modified)

    def content_type(self, name: str) -> str | None:
        overrides, defaults = self._load_content_types()
        return overrides.get(name) or defaults.get(posixpath.splitext(name)[1].lstrip(".").lower())

    def _load_content_types(self) -> tuple[dict[str, str], dict[str, str]]:
        if self._content_types is None:
            root = self.xml("[Content_Types].xml")
            overrides = {
                str(e.get("PartName", "")).lstrip("/"): str(e.get("ContentType", ""))
                for e in root.iter(f"{{{NS['ct']}}}Override")
            }
            defaults = {
                str(e.get("Extension", "")).lower(): str(e.get("ContentType", ""))
                for e in root.iter(f"{{{NS['ct']}}}Default")
            }
            self._content_types = (overrides, defaults)
        return self._content_types

    def relationships(self, source: str) -> list[Relationship]:
        """Relationships of part ``source`` (``""`` for the package), targets resolved."""
        directory, filename = posixpath.split(source)
        rels_name = posixpath.join(directory, "_rels", f"{filename}.rels")
        if not self.has(rels_name):
            return []
        result: list[Relationship] = []
        for rel in self.xml(rels_name).iter(f"{{{NS['pr']}}}Relationship"):
            target = str(rel.get("Target", ""))
            external = rel.get("TargetMode") == "External"
            if not external:
                if target.startswith("/"):
                    target = target.lstrip("/")
                else:
                    target = posixpath.normpath(posixpath.join(directory, target))
            result.append(
                Relationship(str(rel.get("Id", "")), str(rel.get("Type", "")), target, external)
            )
        return result

    def related(self, source: str, rel_type_suffix: str) -> list[Relationship]:
        """Internal relationships of ``source`` whose type ends with ``/rel_type_suffix``."""
        return [
            r
            for r in self.relationships(source)
            if not r.external and r.type.endswith("/" + rel_type_suffix) and self.has(r.target)
        ]

    def main_part(self) -> str:
        for rel in self.relationships(""):
            if rel.type == REL_OFFICE_DOCUMENT and not rel.external:
                return rel.target
        raise InvalidDocumentError("package has no main document part")

    def save(self, path: Path) -> None:
        """Write a copy with modified parts re-serialized and every other entry copied as is."""
        with zipfile.ZipFile(path, "x") as out:
            for info in self._infos:
                if info.filename in self._modified:
                    data = etree.tostring(
                        self._xml[info.filename],
                        xml_declaration=True,
                        encoding="UTF-8",
                        standalone=True,
                    )
                else:
                    data = self._zip.read(info.filename)
                out.writestr(_copy_info(info), data)


def _copy_info(info: zipfile.ZipInfo) -> zipfile.ZipInfo:
    copy = zipfile.ZipInfo(info.filename, date_time=info.date_time)
    copy.compress_type = info.compress_type
    copy.external_attr = info.external_attr
    copy.create_system = info.create_system
    return copy


def _check_limits(infos: list[zipfile.ZipInfo], limits: DocumentLimits) -> None:
    if len(infos) > limits.max_entries:
        raise DocumentLimitError(f"package has {len(infos)} entries (limit {limits.max_entries})")
    seen: set[str] = set()
    total = 0
    for info in infos:
        name = info.filename
        folded = name.lower()
        if folded in seen:
            raise InvalidDocumentError(f"package has a duplicate entry: {escape(name)}")
        seen.add(folded)
        parts = name.split("/")
        if name.startswith("/") or "\\" in name or ".." in parts or ":" in name or "\0" in name:
            raise InvalidDocumentError(f"package has an unsafe entry name: {escape(name)}")
        if info.flag_bits & 0x1:
            raise UnsupportedDocumentError("package entries are encrypted")
        if info.file_size > limits.max_entry_bytes:
            raise DocumentLimitError(f"package entry {escape(name)} exceeds the per-entry limit")
        if (
            info.compress_size
            and info.file_size / info.compress_size > limits.max_compression_ratio
        ):
            raise DocumentLimitError(f"package entry {escape(name)} exceeds the compression limit")
        total += info.file_size
        if total > limits.max_package_bytes:
            raise DocumentLimitError("package exceeds the total uncompressed size limit")
        if name.startswith("_xmlsignatures/"):
            raise UnsupportedDocumentError("digitally signed packages are not supported")
