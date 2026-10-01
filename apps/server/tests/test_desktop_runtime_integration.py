"""Real HY-MT desktop lifecycle. Explicit installed assets required; never downloads."""

import hashlib
import os
from pathlib import Path

import httpx
import pytest

from doctranslator_core import LlmEngineConfig, Translator
from doctranslator_core.types import Language
from doctranslator_server.jobs.desktop_runtime import ManagedLlama


@pytest.mark.integration
def test_managed_hy_mt_real_translation() -> None:
    executable = os.environ.get("DOCTRANSLATOR_TEST_LLAMA_EXE")
    model = os.environ.get("DOCTRANSLATOR_TEST_GGUF")
    if not executable or not model:
        pytest.skip("Set DOCTRANSLATOR_TEST_LLAMA_EXE and DOCTRANSLATOR_TEST_GGUF")
    with Path(model).open("rb") as stream:
        revision = hashlib.file_digest(stream, "sha256").hexdigest()
    runtime = ManagedLlama(Path(executable), Path(model))
    config = LlmEngineConfig.model_validate(
        {
            "base_url": runtime.base_url,
            "api_key": runtime.token,
            "model": "hy-mt",
            "protocol": "hy-mt",
            "execution_location": "server",
            "deployment_revision": revision + ":vulkan-t4-tb4-slots4",
        }
    )
    try:
        with runtime.pin():
            with pytest.raises(RuntimeError, match="in use"):
                runtime.close()
            with httpx.Client(timeout=10, trust_env=False) as client:
                assert client.get(runtime.base_url + "/models").status_code == 401
            with Translator(config) as translator:
                translated = translator.translate_texts(["请保存文件。"], target=Language.EN)
            assert len(translated) == 1
            assert "save" in translated[0].lower()
            assert "file" in translated[0].lower()
    finally:
        runtime.close()
    with (
        httpx.Client(timeout=2, trust_env=False) as client,
        pytest.raises((httpx.ConnectError, httpx.ConnectTimeout)),
    ):
        client.get(runtime.base_url + "/models")
