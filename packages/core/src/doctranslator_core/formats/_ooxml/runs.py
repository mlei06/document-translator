"""Run-style tables and text sanitizing shared by the OOXML adapters."""

import copy
import re

from lxml import etree

from doctranslator_core.formats._ooxml import Element

__all__ = ["StyleTable", "clean_text", "xml_text_ok"]

# Characters XML 1.0 cannot contain, plus line breaks that would be meaningless inside a text node.
_ILLEGAL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")
_BREAKS = re.compile("\r\n|\r|\n|\u2028|\u2029")


def clean_text(text: str) -> str:
    """Make translated text safe for an OOXML text node: no control characters, no line breaks.

    Line structure in Office documents is carried by break objects, never by characters in a text
    node, so a newline an engine adds becomes a space.
    """
    return _ILLEGAL.sub("", _BREAKS.sub(" ", text))


def xml_text_ok(text: str) -> bool:
    return not _ILLEGAL.search(text)


class StyleTable:
    """Assigns a stable small integer to each distinct run-property element.

    Two property elements share an id when they are equal after removing the ignored attributes
    and child elements (language tags and proofing state, which do not change appearance and
    would otherwise split runs at every language boundary). The first element seen is the
    template used to write runs of that style.
    """

    def __init__(
        self, ignored_attributes: frozenset[str], ignored_children: frozenset[str]
    ) -> None:
        self._ignored_attributes = ignored_attributes
        self._ignored_children = ignored_children
        self._ids: dict[bytes, int] = {}
        self._templates: list[Element | None] = []

    def id_for(self, properties: Element | None) -> int:
        key = self._key(properties)
        found = self._ids.get(key)
        if found is None:
            found = len(self._templates)
            self._ids[key] = found
            self._templates.append(copy.deepcopy(properties) if properties is not None else None)
        return found

    def template(self, style: int) -> Element | None:
        """A fresh copy of the style's properties element (``None`` when runs had none)."""
        found = self._templates[style]
        return copy.deepcopy(found) if found is not None else None

    def _key(self, properties: Element | None) -> bytes:
        if properties is None:
            return b""
        clone = copy.deepcopy(properties)
        for name in list(clone.attrib):
            if _local(name) in self._ignored_attributes:
                del clone.attrib[name]
        for child in list(clone):
            if isinstance(child.tag, str) and _local(child.tag) in self._ignored_children:
                clone.remove(child)
        clone.tail = None
        return etree.tostring(clone, method="c14n")


def _local(name: str) -> str:
    return name.rsplit("}", 1)[-1]
