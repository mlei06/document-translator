"""Engines against real backends. Deselected by default; run with ``pytest -m integration``.

LLM: needs the company VPN and ``DOCTRANSLATOR_LLM_BASE_URL``, ``DOCTRANSLATOR_LLM_API_KEY``, and
``DOCTRANSLATOR_LLM_MODEL`` in the environment. MT: needs ``DOCTRANSLATOR_TEST_MT_MODEL_DIR``
pointing at a converted small100 model.
"""

import os
import re
from pathlib import Path

import pytest

from doctranslator_core import LlmEngineConfig, MtEngineConfig, Translator
from doctranslator_core.config import EngineConfig
from doctranslator_core.types import Language

pytestmark = pytest.mark.integration

SOURCES = ["你好，世界", "谢谢"]
_CJK = re.compile(r"[一-鿿]")  # U+4E00 to U+9FFF, CJK Unified Ideographs


def _assert_english(translations: list[str]) -> None:
    assert len(translations) == len(SOURCES)
    for text in translations:
        assert text.strip()
        assert not _CJK.search(text), text


def _translate(config: EngineConfig) -> list[str]:
    with Translator(config) as translator:
        return translator.translate_texts(SOURCES, source=Language.ZH, target=Language.EN)


def test_llm_translates_zh_to_en() -> None:
    names = ["DOCTRANSLATOR_LLM_BASE_URL", "DOCTRANSLATOR_LLM_API_KEY", "DOCTRANSLATOR_LLM_MODEL"]
    missing = [name for name in names if not os.environ.get(name)]
    if missing:
        pytest.skip(f"not set: {', '.join(missing)}")
    config = LlmEngineConfig.model_validate(
        {
            "base_url": os.environ["DOCTRANSLATOR_LLM_BASE_URL"],
            "api_key": os.environ["DOCTRANSLATOR_LLM_API_KEY"],
            "model": os.environ["DOCTRANSLATOR_LLM_MODEL"],
        }
    )
    _assert_english(_translate(config))


def test_mt_translates_zh_to_en() -> None:
    model_dir = os.environ.get("DOCTRANSLATOR_TEST_MT_MODEL_DIR")
    if not model_dir:
        pytest.skip("DOCTRANSLATOR_TEST_MT_MODEL_DIR not set")
    config = MtEngineConfig(model_dir=Path(model_dir), model_family="small100")
    _assert_english(_translate(config))
