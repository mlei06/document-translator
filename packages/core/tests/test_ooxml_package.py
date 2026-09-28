"""Package safety: limits, hostile entries, protection and content/extension agreement."""

import zipfile
from pathlib import Path

import pytest
from support.fakes import copy_fixture
from support.ooxml import rewrite

from doctranslator_core import inspect_document
from doctranslator_core.config import DocumentLimits
from doctranslator_core.types import (
    DocumentFormat,
    DocumentLimitError,
    InvalidDocumentError,
    UnsupportedDocumentError,
)


def repack(source: Path, target: Path, extra: dict[str, bytes]) -> Path:
    """Copy a package and add entries with exactly the given (possibly hostile) names."""
    with zipfile.ZipFile(source) as src, zipfile.ZipFile(target, "w") as dst:
        for info in src.infolist():
            dst.writestr(info, src.read(info.filename))
        for name, data in extra.items():
            raw = zipfile.ZipInfo("placeholder")
            raw.filename = name  # ZipInfo() would normalize "/" prefixes and backslashes
            dst.writestr(raw, data)
    return target


def test_fixtures_are_identified(tmp_path: Path) -> None:
    for name, fmt in (
        ("pptx/deck.pptx", DocumentFormat.PPTX),
        ("docx/report.docx", DocumentFormat.DOCX),
        ("xlsx/labels.xlsx", DocumentFormat.XLSX),
    ):
        assert inspect_document(copy_fixture(name, tmp_path)) is fmt


def test_extension_must_match_content(tmp_path: Path) -> None:
    deck = copy_fixture("pptx/deck.pptx", tmp_path)
    renamed = deck.rename(tmp_path / "deck.docx")
    with pytest.raises(UnsupportedDocumentError, match="PPTX but the extension"):
        inspect_document(renamed)


def test_signed_macro_and_non_ooxml_zips_are_rejected(tmp_path: Path) -> None:
    source = copy_fixture("docx/report.docx", tmp_path)
    signed = repack(source, tmp_path / "signed.docx", {"_xmlsignatures/sig1.xml": b"<x/>"})
    with pytest.raises(UnsupportedDocumentError, match="signed"):
        inspect_document(signed)
    macro = rewrite(
        source,
        tmp_path / "macro.docx",
        "[Content_Types].xml",
        lambda d: d.replace(
            b"wordprocessingml.document.main+xml", b"ms-word.document.macroEnabled.main+xml"
        ),
    )
    with pytest.raises(UnsupportedDocumentError, match="macro"):
        inspect_document(macro)
    plain_zip = tmp_path / "archive.docx"
    with zipfile.ZipFile(plain_zip, "w") as z:
        z.writestr("readme.txt", "hello")
    with pytest.raises(UnsupportedDocumentError, match="not an Office Open XML"):
        inspect_document(plain_zip)


def test_unsafe_and_duplicate_entry_names(tmp_path: Path) -> None:
    source = copy_fixture("xlsx/labels.xlsx", tmp_path)
    # zipfile itself normalizes leading "/" and backslashes when reading, and packages are never
    # extracted to disk, so traversal is the hostile name that reaches the check unchanged.
    for index, name in enumerate(("../evil.xml", "xl/../../evil.xml")):
        bad = repack(source, tmp_path / f"bad{index}.xlsx", {name: b"<x/>"})
        with pytest.raises(InvalidDocumentError, match="unsafe"):
            inspect_document(bad)
    duplicate = tmp_path / "dup.xlsx"
    with zipfile.ZipFile(source) as src, zipfile.ZipFile(duplicate, "w") as dst:
        for info in src.infolist():
            dst.writestr(info, src.read(info.filename))
        dst.writestr("XL/workbook.xml", b"<x/>")  # differs only in case: Office names fold case
    with pytest.raises(InvalidDocumentError, match="duplicate"):
        inspect_document(duplicate)


def test_resource_limits(tmp_path: Path) -> None:
    source = copy_fixture("xlsx/labels.xlsx", tmp_path)
    with pytest.raises(DocumentLimitError):
        inspect_document(source, limits=DocumentLimits(max_entries=3))
    with pytest.raises(DocumentLimitError):
        inspect_document(source, limits=DocumentLimits(max_entry_bytes=100))
    bomb = tmp_path / "bomb.xlsx"
    with zipfile.ZipFile(source) as src, zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            dst.writestr(info, src.read(info.filename))
        dst.writestr("xl/media/zeros.bin", b"\0" * (20 << 20))
    with pytest.raises(DocumentLimitError, match="compression"):
        inspect_document(bomb)


def test_dtd_and_entities_are_refused(tmp_path: Path) -> None:
    from doctranslator_core.config import DocumentLimits as Limits
    from doctranslator_core.formats import open_adapter
    from doctranslator_core.types import DocumentTranslationOptions, Language

    source = copy_fixture("docx/report.docx", tmp_path)
    evil = rewrite(
        source,
        tmp_path / "evil.docx",
        "word/document.xml",
        lambda d: d.replace(b"?>", b'?><!DOCTYPE w [<!ENTITY x "boom">]>', 1),
    )
    with pytest.raises(InvalidDocumentError, match="DTD"):
        open_adapter(
            DocumentFormat.DOCX, evil, Limits(), DocumentTranslationOptions(target=Language.EN)
        )
