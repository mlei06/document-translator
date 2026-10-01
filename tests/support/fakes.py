"""Deterministic fake translators for pipeline, CLI and server tests."""

import re
import shutil
from collections.abc import Callable, Sequence
from pathlib import Path

from doctranslator_core.types import EngineInfo, Language, TranslationMode

__all__ = ["FIXTURES", "FakeTranslator", "copy_fixture", "fake_translation"]

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
_TAG = re.compile(r"</?g\d+>|<x\d+/>")
_CJK = re.compile(r"[぀-ヿ㐀-䶿一-鿿＀-￯　-〿]")


def fake_translation(text: str, target: Language) -> str:
    """Replace every CJK character with a Latin marker, keep tags, prefix the target code.

    The result has no CJK characters (so "translated to English" is checkable) and every tag of
    the input in the same place (so formatting correspondence is checkable).
    """
    parts = _TAG.split(text)
    tags = _TAG.findall(text)
    out = [_CJK.sub("x", part) for part in parts]
    joined = out[0]
    for tag, part in zip(tags, out[1:], strict=True):
        joined += tag + part
    return f"{target.value.upper()}:{joined}" if joined.strip() else joined


class FakeTranslator:
    """Records every batch. ``transform`` overrides the translation of individual texts."""

    def __init__(
        self,
        transform: Callable[[str, Language], str] | None = None,
        *,
        on_batch: Callable[[list[str]], None] | None = None,
    ) -> None:
        self.batches: list[list[str]] = []
        self._transform = transform or fake_translation
        self._on_batch = on_batch

    @property
    def engine_info(self) -> EngineInfo:
        return EngineInfo(mode=TranslationMode.MT, model="fake", details={})

    def translate_texts(
        self, texts: Sequence[str], *, source: Language | None, target: Language
    ) -> list[str]:
        batch = list(texts)
        self.batches.append(batch)
        if self._on_batch is not None:
            self._on_batch(batch)
        return [self._keep_whitespace(text, target) for text in batch]

    def _keep_whitespace(self, text: str, target: Language) -> str:
        """Like ``Translator.translate_texts``: outer whitespace is kept around the translation."""
        core = text.strip()
        if not core:
            return text
        start = len(text) - len(text.lstrip())
        return text[:start] + self._transform(core, target) + text[start + len(core) :]

    @property
    def inputs(self) -> list[str]:
        return [text for batch in self.batches for text in batch]


def copy_fixture(name: str, directory: Path) -> Path:
    """Copy ``tests/fixtures/<name>`` into ``directory`` and return the copy's path."""
    source = FIXTURES / name
    target = directory / source.name
    shutil.copyfile(source, target)
    return target
