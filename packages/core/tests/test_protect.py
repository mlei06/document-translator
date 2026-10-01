"""Literal guards preserve recognizable syntax and curated/user names before inference."""

from pathlib import Path
from unittest.mock import patch

import pytest
from support.fakes import FakeTranslator

from doctranslator_core import get_default_protected_terms, output_fingerprint
from doctranslator_core.config import DocumentLimits
from doctranslator_core.inline import Keep, Text, Wrap
from doctranslator_core.pipeline import translate_document
from doctranslator_core.protect import protect
from doctranslator_core.types import (
    DocumentTranslationOptions,
    Language,
    TranslationIdentity,
    TranslationMode,
)


@pytest.mark.parametrize(
    "literal",
    [
        "github.com/heygen-com/hyperframes",
        "ELEVENLABS_API_KEY=your_api_key",
        'API_TOKEN="value with spaces!"',
        "export API_TOKEN=abc:def!",
        "ELEVENLABS_API_KEY",
        ".env",
        ".env.local",
        "https://example.com/page",
        "person@example.com",
        r"C:\folder\file.txt",
        "/usr/local/bin",
    ],
)
def test_syntax_is_preserved(literal: str) -> None:
    assert protect([Text(literal, 0)], use_default_dictionary=False) == [Keep(literal, 0)]


def test_names_boundaries_longest_case_and_cjk() -> None:
    text = "Lenovo LenovoX MyLenovo lenovo Lenovo ThinkPad 联想提供支持 ThinkPad2"
    nodes = protect([Text(text, 0)], ("Lenovo ThinkPad",))
    assert [n.text for n in nodes if isinstance(n, Keep)] == [
        "Lenovo",
        "Lenovo ThinkPad",
        "联想",
    ]
    assert "".join(n.text for n in nodes if isinstance(n, (Keep, Text))) == text


def test_user_names_work_without_defaults() -> None:
    assert protect([Text("Lenovo Acme", 0)], ("Acme",), use_default_dictionary=False) == [
        Text("Lenovo ", 0),
        Keep("Acme", 0),
    ]


def test_adjacent_styles_keep_split_name_and_url() -> None:
    assert protect([Text("Try Eleven", 0), Text("Labs setup", 1)]) == [
        Text("Try ", 0),
        Keep("Eleven", 0),
        Keep("Labs", 1),
        Text(" setup", 1),
    ]
    assert protect([Text("github.com/", 0), Text("heygen-com/hyperframes", 1)]) == [
        Keep("github.com/", 0),
        Keep("heygen-com/hyperframes", 1),
    ]
    assert protect([Wrap(1, (Text("Eleven", 0), Text("Labs", 1)))]) == [
        Wrap(1, (Keep("Eleven", 0), Keep("Labs", 1))),
    ]


def test_prose_numbers_and_ambiguous_words_stay_translatable() -> None:
    text = "Use 123 units. Windows Excel Yoga Legion are words. example.com costs 4.50."
    assert protect([Text(text, 0)]) == [Text(text, 0)]


def test_literal_restoration_through_document_pipeline(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text(
        "Lenovo provides support.\nElevenLabs setup\n"
        "github.com/heygen-com/hyperframes\nELEVENLABS_API_KEY=your_api_key\n",
        encoding="utf-8",
    )
    engine = FakeTranslator(
        lambda text, target: text.replace("provides support.", "提供支持。").replace(
            "setup", "设置"
        )
    )
    destination = tmp_path / "result.txt"
    translate_document(
        engine,
        source,
        destination,
        options=DocumentTranslationOptions(source=Language.EN, target=Language.ZH),
        fingerprint="test",
        limits=DocumentLimits(),
    )
    assert engine.inputs == ["<x1/> provides support.", "<x1/> setup"]
    assert destination.read_text(encoding="utf-8") == (
        "Lenovo 提供支持。\nElevenLabs 设置\n"
        "github.com/heygen-com/hyperframes\nELEVENLABS_API_KEY=your_api_key\n"
    )


def test_dictionary_is_packaged_and_changes_fingerprint() -> None:
    assert "Lenovo" in get_default_protected_terms()
    identity = TranslationIdentity(mode=TranslationMode.LLM, model="test", details={})
    options = DocumentTranslationOptions(source=Language.EN, target=Language.ZH)
    base = output_fingerprint(identity, options)
    disabled = options.model_copy(update={"use_default_dictionary": False})
    without = output_fingerprint(identity, disabled)
    assert base != without
    with patch("doctranslator_core.protect.get_default_protected_terms", return_value=("Other",)):
        assert output_fingerprint(identity, options) != base
        assert output_fingerprint(identity, disabled) == without
