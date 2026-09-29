"""CLI environment settings reach the public core configuration unchanged."""

import os
from pathlib import Path

import keyring
import pytest
from pydantic import ValidationError

from doctranslator_cli.settings import SettingsError, load_settings
from doctranslator_core import LlmEngineConfig
from doctranslator_core.types import TranslationMode


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for name in os.environ:
        if name.startswith("DOCTRANSLATOR_"):
            monkeypatch.delenv(name)
    monkeypatch.chdir(tmp_path)

    def get_password(service: str, username: str) -> None:
        return None

    monkeypatch.setattr(keyring, "get_password", get_password)
    monkeypatch.setenv("DOCTRANSLATOR_LLM_BASE_URL", "http://127.0.0.1:8000/v1")
    monkeypatch.setenv("DOCTRANSLATOR_LLM_API_KEY", "local-placeholder")
    monkeypatch.setenv("DOCTRANSLATOR_LLM_MODEL", "served-model")


@pytest.mark.parametrize("profile", ["translategemma", "hy-mt2"])
def test_profile_settings_reach_core(monkeypatch: pytest.MonkeyPatch, profile: str) -> None:
    expected = {
        "translation_profile": profile,
        "server_backend": "llamacpp",
        "deployment_revision": "weights-template-build-v1",
        "max_concurrency": 2,
        "temperature": 0.7,
        "max_output_tokens": 4096,
        "top_p": 0.9,
        "top_k": 20,
        "repetition_penalty": 1.05,
        "seed": 42,
    }
    for name, value in expected.items():
        monkeypatch.setenv(f"DOCTRANSLATOR_LLM_{name.upper()}", str(value))
    config = load_settings(None).engine_config(TranslationMode.LLM)
    assert isinstance(config, LlmEngineConfig)
    assert config.model_dump(include=set(expected)) == expected


def test_default_profile_preserves_generic_defaults() -> None:
    config = load_settings(None).engine_config(TranslationMode.LLM)
    assert isinstance(config, LlmEngineConfig)
    assert config.translation_profile == "generic"
    assert config.server_backend == "openai"
    assert config.deployment_revision == ""
    assert config.batch_size == 16
    assert config.json_mode is True
    assert config.max_concurrency == 4
    assert config.temperature == 0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("TRANSLATION_PROFILE", "unsupported"),
        ("SERVER_BACKEND", "unsupported"),
        ("MAX_CONCURRENCY", "0"),
        ("MAX_OUTPUT_TOKENS", "0"),
        ("TEMPERATURE", "3"),
        ("TOP_P", "1.5"),
        ("TOP_K", "-1"),
        ("REPETITION_PENALTY", "0"),
        ("SEED", "invalid"),
    ],
)
def test_invalid_tuning_names_setting_without_value(
    monkeypatch: pytest.MonkeyPatch, field: str, value: str
) -> None:
    monkeypatch.setenv(f"DOCTRANSLATOR_LLM_{field}", value)
    with pytest.raises(SettingsError, match=f"invalid settings: llm_{field.lower()}"):
        load_settings(None)


def test_specialized_profile_requires_deployment_revision(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCTRANSLATOR_LLM_TRANSLATION_PROFILE", "hy-mt2")
    with pytest.raises(ValidationError, match="deployment_revision"):
        load_settings(None).engine_config(TranslationMode.LLM)
