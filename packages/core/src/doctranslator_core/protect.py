"""Protected spans and segment pass-through (ADR-011 section 3, strategy ``protect-v2``)."""

import hashlib
import re
import unicodedata
from collections.abc import Sequence
from functools import lru_cache
from importlib.resources import files

from doctranslator_core.inline import Inline, Keep, Text, Wrap, protect_tag_like
from doctranslator_core.types import Language

__all__ = [
    "get_default_protected_terms",
    "is_cjk_char",
    "passes_through",
    "protect",
    "script_letters",
]

_TRAILING = ".,;:!?)]}'\"。，、；：！？）】」』"  # noqa: RUF001 - CJK punctuation
_PATTERNS = [
    # Standalone environment assignments, including quoted values with spaces.
    r"(?P<assignment>(?m:^[ \t]*(?:export[ \t]+)?[A-Z_][A-Z0-9_]*="
    r'(?:"[^"\r\n]*"|\'[^\'\r\n]*\'|[^\s]+)[ \t]*$))',
    # Bare domains require a path: prose like "example.com" is intentionally conservative.
    r"(?<![\w@./-])(?:[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?\.)+[A-Za-z]{2,63}/"
    r"[^\s<>\"'　-〿＀-￯]*",
    r"(?<![\w])(?:[A-Z][A-Z0-9]*_)+[A-Z0-9]+(?![\w])",
    r"(?<![\w./])\.[A-Za-z][A-Za-z0-9_-]*(?:\.[A-Za-z0-9_-]+)*(?![\w])",
    # URLs (scheme or www.), emails, Windows drive and UNC paths, absolute Unix paths (2+ parts)
    r"(?:https?|ftp)://[^\s<>\"'　-〿＀-￯]+",
    r"\bwww\.[^\s<>\"'　-〿＀-￯]+",
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
    r"\b[A-Za-z]:\\[^\s<>\"|?*　-〿＀-￯]+",
    r"\\\\[^\s\\<>\"|?*]+\\[^\s<>\"|?*　-〿＀-￯]+",
    r"(?<![\w/.])/(?:[\w.-]+/)+[\w.-]*",
]
_PATTERN = re.compile("|".join(f"(?:{p})" for p in _PATTERNS))


@lru_cache(maxsize=1)
def get_default_protected_terms() -> tuple[str, ...]:
    """Exact, case-sensitive maintained names shipped with the core package."""
    content = (
        files("doctranslator_core").joinpath("protected_names.txt").read_text(encoding="utf-8")
    )
    return tuple(
        dict.fromkeys(
            line.strip()
            for line in content.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        )
    )


def default_dictionary_digest() -> str:
    """Hash effective dictionary entries so updates invalidate compatible output caches."""
    return hashlib.sha256("\n".join(get_default_protected_terms()).encode("utf-8")).hexdigest()


def _identifier_char(ch: str) -> bool:
    return ch == "_" or ch.isdigit() or _is_latin_letter(ch)


def _term_boundary(text: str, start: int, end: int, term: str) -> bool:
    return not (
        (start > 0 and _identifier_char(term[0]) and _identifier_char(text[start - 1]))
        or (end < len(text) and _identifier_char(term[-1]) and _identifier_char(text[end]))
    )


def _spans(text: str, terms: Sequence[str]) -> list[tuple[int, int]]:
    """Non-overlapping protected ranges; the earliest (then longest) match wins."""
    found: list[tuple[int, int]] = []
    for match in _PATTERN.finditer(text):
        start, end = match.start(), match.end()
        while match.lastgroup != "assignment" and end > start and text[end - 1] in _TRAILING:
            end -= 1
        if end > start:
            found.append((start, end))
    for term in sorted({t for t in terms if t}, key=len, reverse=True):
        for match in re.finditer(re.escape(term), text):
            if _term_boundary(text, match.start(), match.end(), term):
                found.append((match.start(), match.end()))
    found.sort(key=lambda r: (r[0], -(r[1] - r[0])))
    merged: list[tuple[int, int]] = []
    for start, end in found:
        if merged and start < merged[-1][1]:
            continue
        merged.append((start, end))
    return merged


def protect(
    nodes: Sequence[Inline], terms: Sequence[str] = (), *, use_default_dictionary: bool = True
) -> list[Inline]:
    """Protect syntax and exact names, including names split across adjacent styled runs."""
    effective = tuple(terms) + (get_default_protected_terms() if use_default_dictionary else ())
    return _protect_nodes(protect_tag_like(nodes), effective)


def _protect_nodes(nodes: Sequence[Inline], terms: Sequence[str]) -> list[Inline]:
    result: list[Inline] = []
    pending: list[Text] = []

    def flush() -> None:
        text = "".join(node.text for node in pending)
        spans = _spans(text, terms)
        offset = 0
        for node in pending:
            end = offset + len(node.text)
            cursor = offset
            for start, stop in spans:
                left, right = max(start, offset), min(stop, end)
                if left >= right:
                    continue
                if cursor < left:
                    result.append(Text(text[cursor:left], node.style))
                result.append(Keep(text[left:right], node.style))
                cursor = right
            if cursor < end:
                result.append(Text(text[cursor:end], node.style))
            offset = end
        pending.clear()

    for node in nodes:
        if isinstance(node, Text):
            pending.append(node)
            continue
        flush()
        if isinstance(node, Wrap):
            result.append(Wrap(node.key, tuple(_protect_nodes(node.children, terms))))
        else:
            result.append(node)
    flush()
    return result


def is_cjk_char(ch: str) -> bool:
    """Han or kana (the scripts of Chinese and Japanese source text)."""
    o = ord(ch)
    return (
        0x3040 <= o <= 0x30FF
        or 0x31F0 <= o <= 0x31FF
        or 0x3400 <= o <= 0x4DBF
        or 0x4E00 <= o <= 0x9FFF
        or 0xF900 <= o <= 0xFAFF
        or 0xFF66 <= o <= 0xFF9D
        or 0x20000 <= o <= 0x2FA1F
    )


def _is_latin_letter(ch: str) -> bool:
    return ch.isalpha() and "LATIN" in unicodedata.name(ch, "")


def script_letters(text: str, source: Language) -> int:
    """How many characters of ``text`` belong to the source language's script."""
    if source in (Language.ZH, Language.JA):
        return sum(1 for ch in text if is_cjk_char(ch))
    return sum(1 for ch in text if _is_latin_letter(ch))


def _translatable_text(nodes: Sequence[Inline]) -> str:
    parts: list[str] = []
    for node in nodes:
        match node:
            case Text(text=t):
                parts.append(t)
            case Wrap(children=children):
                parts.append(_translatable_text(children))
            case _:
                pass
    return "".join(parts)


def passes_through(nodes: Sequence[Inline], source: Language | None = None) -> bool:
    """True when the protected paragraph has nothing for the engine to translate.

    That is: no letters outside protected spans (numbers, symbols, URLs only), or no character of
    the source language's script (for example Latin product names inside a Chinese document).
    """
    text = _translatable_text(nodes)
    if not any(ch.isalpha() for ch in text):
        return True
    return source is not None and script_letters(text, source) == 0
