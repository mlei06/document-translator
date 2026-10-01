import pytest

from doctranslator_cli.settings import CliSettings
from doctranslator_core import LlmEngineConfig
from doctranslator_core.types import TranslationMode


def test_hy_mt_environment_reaches_core(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in {
        "LLM_BASE_URL": "http://127.0.0.1:8099/v1/",
        "LLM_API_KEY": "local",
        "LLM_MODEL": "hy-mt",
        "LLM_PROTOCOL": "hy-mt",
        "LLM_EXECUTION_LOCATION": "server",
        "LLM_DEPLOYMENT_REVISION": "pinned-gguf-and-runtime",
        "LLM_MAX_OUTPUT_TOKENS": "1024",
        "LLM_MAX_CONCURRENCY": "1",
    }.items():
        monkeypatch.setenv(f"DOCTRANSLATOR_{name}", value)
    config = CliSettings().engine_config(TranslationMode.LLM)
    assert isinstance(config, LlmEngineConfig)
    assert config.protocol == "hy-mt"
    assert config.execution_location == "server"
    assert config.max_output_tokens == 1024
    assert config.max_concurrency == 1
    assert config.deployment_revision == "pinned-gguf-and-runtime"
