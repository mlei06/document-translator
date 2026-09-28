"""Formatting recovery through the real pipeline: projection, then the per-span fallback."""

import re
from pathlib import Path

from support.fakes import FakeTranslator, copy_fixture, fake_translation
from support.ooxml import NS, xml

from doctranslator_core.config import DocumentLimits
from doctranslator_core.pipeline import translate_document
from doctranslator_core.types import DocumentTranslationOptions, Language

OPTIONS = DocumentTranslationOptions(source=Language.ZH, target=Language.EN)
A = f"{{{NS['a']}}}"
TAGS = re.compile(r"</?g\d+>")
TRANSLATIONS = {
    "销售额": "Revenue",
    "增长了百分之十二": "grew twelve percent",
    "销售额增长了百分之十二": "Revenue grew twelve percent",
}


def bold_texts(path: Path) -> list[str]:
    body = xml(path, "ppt/slides/slide2.xml")
    return [
        r.findtext(f"{A}t") or ""
        for r in body.iter(f"{A}r")
        if (rpr := r.find(f"{A}rPr")) is not None and rpr.get("b") == "1"
    ]


def test_projection_recovers_lost_tags(tmp_path: Path) -> None:
    def engine(text: str, target: Language) -> str:
        if text == "<g1>销售额</g1>增长了百分之十二":
            return "Revenue grew twelve percent"  # tags lost
        return TRANSLATIONS.get(text, fake_translation(text, target))

    source = copy_fixture("pptx/deck.pptx", tmp_path)
    result = translate_document(
        FakeTranslator(engine),
        source,
        tmp_path / "out.pptx",
        options=OPTIONS,
        fingerprint="f",
        limits=DocumentLimits(),
    )
    assert result.counts.formatting_fallbacks == 0
    assert bold_texts(tmp_path / "out.pptx") == ["Revenue"]
    assert not any(d.code == "formatting_fallback" for d in result.diagnostics)


def test_per_span_fallback_keeps_formatting_and_is_reported(tmp_path: Path) -> None:
    def engine(text: str, target: Language) -> str:
        if TAGS.search(text):
            return "garbled output"
        if text == "销售额增长了百分之十二":
            return "Sales rose by twelve percent"  # projection cannot find "Revenue"
        return TRANSLATIONS.get(text, fake_translation(text, target))

    source = copy_fixture("pptx/deck.pptx", tmp_path)
    result = translate_document(
        FakeTranslator(engine),
        source,
        tmp_path / "out.pptx",
        options=OPTIONS,
        fingerprint="f",
        limits=DocumentLimits(),
    )
    assert result.counts.formatting_fallbacks >= 1
    assert bold_texts(tmp_path / "out.pptx") == ["Revenue"]  # the joining space is not bold
    fallback = [d for d in result.diagnostics if d.code == "formatting_fallback"]
    assert fallback and fallback[0].location is not None
    assert fallback[0].location.startswith("slide 2 / shape")
