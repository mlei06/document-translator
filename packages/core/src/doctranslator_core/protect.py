"""Protected spans and segment pass-through (ADR-011 section 3, strategy ``protect-v1``)."""

import re
import unicodedata
from collections.abc import Sequence

from doctranslator_core.inline import Inline, Keep, Obj, Text, Wrap, protect_tag_like
from doctranslator_core.types import Language

__all__ = ["is_cjk_char", "passes_through", "protect", "script_letters"]

_TRAILING = ".,;:!?)]}'\"。，、；：！？）】」』"  # noqa: RUF001 - CJK punctuation
_PATTERNS = [
    # URLs (scheme or www.), emails, Windows drive and UNC paths, absolute Unix paths (2+ parts)
    r"(?:https?|ftp)://[^\s<>\"'　-〿＀-￯]+",
    r"\bwww\.[^\s<>\"'　-〿＀-￯]+",
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
    r"\b[A-Za-z]:\\[^\s<>\"|?*　-〿＀-￯]+",
    r"\\\\[^\s\\<>\"|?*]+\\[^\s<>\"|?*　-〿＀-￯]+",
    r"(?<![\w/.])/(?:[\w.-]+/)+[\w.-]*",
]
_PATTERN = re.compile("|".join(f"(?:{p})" for p in _PATTERNS))


def _spans(text: str, terms: Sequence[str]) -> list[tuple[int, int]]:
    """Non-overlapping protected ranges; the earliest (then longest) match wins."""
    found: list[tuple[int, int]] = []
    for match in _PATTERN.finditer(text):
        start, end = match.start(), match.end()
        while end > start and text[end - 1] in _TRAILING:
            end -= 1
        if end > start:
            found.append((start, end))
    for term in sorted({t for t in terms if t}, key=len, reverse=True):
        for match in re.finditer(re.escape(term), text):
            found.append((match.start(), match.end()))
    found.sort(key=lambda r: (r[0], -(r[1] - r[0])))
    merged: list[tuple[int, int]] = []
    for start, end in found:
        if merged and start < merged[-1][1]:
            continue
        merged.append((start, end))
    return merged


def protect(nodes: Sequence[Inline], terms: Sequence[str] = ()) -> list[Inline]:
    """Split ``Text`` so URLs, emails, paths, protected terms and tag-like text become ``Keep``."""
    result: list[Inline] = []
    for node in protect_tag_like(nodes):
        match node:
            case Text(text=t, style=s):
                last = 0
                for start, end in _spans(t, terms):
                    if start > last:
                        result.append(Text(t[last:start], s))
                    result.append(Keep(t[start:end], s))
                    last = end
                if last < len(t):
                    result.append(Text(t[last:], s))
            case Wrap(key=k, children=children):
                result.append(Wrap(k, tuple(protect(children, terms))))
            case Keep() | Obj():
                result.append(node)
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


def passes_through(nodes: Sequence[Inline], source: Language) -> bool:
    """True when the protected paragraph has nothing for the engine to translate.

    That is: no letters outside protected spans (numbers, symbols, URLs only), or no character of
    the source language's script (for example Latin product names inside a Chinese document).
    """
    text = _translatable_text(nodes)
    if not any(ch.isalpha() for ch in text):
        return True
    return script_letters(text, source) == 0
