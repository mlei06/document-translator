"""TXT adapter: preserves encoding, BOM, line endings, blank lines and surrounding whitespace."""

import codecs
import re
from collections.abc import Sequence
from pathlib import Path

from doctranslator_core.document import Paragraph
from doctranslator_core.formats.base import DocumentAdapter
from doctranslator_core.inline import Inline, Text, plain_text
from doctranslator_core.types import DocumentFormat, InvalidDocumentError, Language

__all__ = ["TxtAdapter"]

_LINE = re.compile(r"(\r\n|\n|\r)")
_BOMS = (
    (codecs.BOM_UTF8, "utf-8"),
    (codecs.BOM_UTF16_LE, "utf-16-le"),
    (codecs.BOM_UTF16_BE, "utf-16-be"),
)


class TxtAdapter(DocumentAdapter):
    format = DocumentFormat.TXT

    def __init__(self, path: Path, encoding: str | None) -> None:
        super().__init__()
        data = path.read_bytes()
        self._bom = b""
        if encoding is None:
            encoding = "utf-8"
            for bom, name in _BOMS:
                if data.startswith(bom):
                    self._bom, encoding = bom, name
                    data = data[len(bom) :]
                    break
        else:
            try:
                codecs.lookup(encoding)
            except LookupError as exc:
                raise InvalidDocumentError(f"unknown text encoding {encoding!r}") from exc
        self._encoding = encoding
        try:
            text = data.decode(encoding)
        except UnicodeDecodeError as exc:
            raise InvalidDocumentError(
                f"the file is not valid {encoding}; pass its encoding explicitly"
            ) from exc
        pieces = _LINE.split(text)
        # pieces alternate line text and line ending; the last line may have no ending
        self._lines = pieces[0::2]
        self._endings = [*pieces[1::2], ""]

    def paragraphs(self) -> list[Paragraph]:
        return [
            Paragraph(index, f"line {index + 1}", (Text(line, 0),))
            for index, line in enumerate(self._lines)
            if line.strip()
        ]

    def apply(self, paragraph_id: int, nodes: Sequence[Inline], target: Language) -> None:
        # A translated line never gains line breaks: the file's line structure is preserved.
        self._lines[paragraph_id] = _LINE.sub(" ", plain_text(nodes))

    def save(self, path: Path) -> None:
        text = "".join(
            line + ending for line, ending in zip(self._lines, self._endings, strict=True)
        )
        try:
            data = self._bom + text.encode(self._encoding)
        except UnicodeEncodeError as exc:
            raise InvalidDocumentError(
                f"the translation cannot be represented in {self._encoding}"
            ) from exc
        with path.open("xb") as handle:
            handle.write(data)
