"""Source-language detection (ADR-011 section 4, strategy ``detect-v1``).

Scripts decide Chinese vs Japanese (kana share) and CJK vs Latin; lingua-language-detector,
restricted to English and Spanish, decides between those two. Short or unclear samples raise
``SourceLanguageAmbiguousError`` instead of guessing.
"""

import unicodedata
from collections.abc import Iterable
from functools import cache

from doctranslator_core.types import (
    DiagnosticSeverity,
    DocumentDiagnostic,
    Language,
    SourceLanguageAmbiguousError,
)

__all__ = ["detect_source"]

MAX_SAMPLE_CHARS = 20_000
MIN_HAN = 10
MIN_LATIN = 20
KANA_SHARE = 0.10
MIN_CONFIDENCE = 0.70


def _is_kana(o: int) -> bool:
    return 0x3040 <= o <= 0x30FF or 0x31F0 <= o <= 0x31FF or 0xFF66 <= o <= 0xFF9D


def _is_han(o: int) -> bool:
    return (
        0x3400 <= o <= 0x4DBF
        or 0x4E00 <= o <= 0x9FFF
        or 0xF900 <= o <= 0xFAFF
        or 0x20000 <= o <= 0x2FA1F
    )


@cache
def _latin_detector():  # type: ignore[no-untyped-def]
    from lingua import Language as LinguaLanguage  # pyright: ignore[reportMissingTypeStubs]
    from lingua import LanguageDetectorBuilder  # pyright: ignore[reportMissingTypeStubs]

    detector = LanguageDetectorBuilder.from_languages(  # pyright: ignore[reportUnknownMemberType]
        LinguaLanguage.ENGLISH, LinguaLanguage.SPANISH
    ).build()
    return detector, LinguaLanguage.ENGLISH, LinguaLanguage.SPANISH


def detect_source(texts: Iterable[str]) -> tuple[Language | None, list[DocumentDiagnostic]]:
    """The document's source language from its translatable text.

    Returns ``(None, [])`` when the sample has no letters at all. Raises
    ``SourceLanguageAmbiguousError`` when the sample is too small or too unclear to decide.
    """
    parts: list[str] = []
    size = 0
    for text in texts:
        if size >= MAX_SAMPLE_CHARS:
            break
        chunk = text[: MAX_SAMPLE_CHARS - size]
        parts.append(chunk)
        size += len(chunk)
    sample = "\n".join(parts)
    kana = han = latin = 0
    for ch in sample:
        o = ord(ch)
        if _is_kana(o):
            kana += 1
        elif _is_han(o):
            han += 1
        elif ch.isalpha() and "LATIN" in unicodedata.name(ch, ""):
            latin += 1
    if kana + han + latin == 0:
        return None, []
    if kana + han >= 10 and latin >= 20 and min(kana + han, latin) / max(kana + han, latin) >= 0.35:
        return None, [
            DocumentDiagnostic(
                code="source_mixed",
                severity=DiagnosticSeverity.INFO,
                message="The document contains substantial text in multiple language scripts.",
            )
        ]
    if kana + han >= latin:
        if kana >= KANA_SHARE * (kana + han):
            return Language.JA, []
        if han >= MIN_HAN:
            note = DocumentDiagnostic(
                code="detected_without_kana",
                severity=DiagnosticSeverity.INFO,
                message="Detected Chinese: the text has Han characters and no Japanese kana.",
            )
            return Language.ZH, [note]
        raise SourceLanguageAmbiguousError(
            "too little Chinese/Japanese text to detect the source language confidently"
        )
    if latin < MIN_LATIN:
        raise SourceLanguageAmbiguousError(
            "too little text to detect the source language confidently"
        )
    detector, english, spanish = _latin_detector()  # pyright: ignore[reportUnknownVariableType]
    en = float(detector.compute_language_confidence(sample, english))  # pyright: ignore
    es = float(detector.compute_language_confidence(sample, spanish))  # pyright: ignore
    best, confidence = (Language.EN, en) if en >= es else (Language.ES, es)
    if confidence < MIN_CONFIDENCE:
        raise SourceLanguageAmbiguousError("cannot tell English from Spanish with confidence")
    return best, []
