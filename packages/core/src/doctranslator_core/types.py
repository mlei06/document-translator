"""Public data types: languages, translation modes, options, results, fit report, errors."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

__all__ = [
    "LANGUAGE_NAMES",
    "EngineAuthenticationError",
    "EngineInfo",
    "EngineResponseError",
    "EngineUnavailableError",
    "Language",
    "TranslationError",
    "TranslationMode",
]


class Language(StrEnum):
    ZH = "zh"
    """Simplified Chinese."""
    EN = "en"
    JA = "ja"
    ES = "es"


LANGUAGE_NAMES: dict[Language, str] = {
    Language.ZH: "Simplified Chinese",
    Language.EN: "English",
    Language.JA: "Japanese",
    Language.ES: "Spanish",
}


class TranslationMode(StrEnum):
    LLM = "llm"
    MT = "mt"


class EngineInfo(BaseModel):
    """Identifies what produced a translation, for recording alongside results."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    mode: TranslationMode
    model: str
    details: dict[str, str]


class TranslationError(Exception):
    """Base exception for all translation failures."""


class EngineUnavailableError(TranslationError):
    """The engine cannot be reached or loaded."""


class EngineAuthenticationError(TranslationError):
    """The LLM server rejected the credentials. Never retried."""


class EngineResponseError(TranslationError):
    """The engine answered, but the answer is unusable."""
