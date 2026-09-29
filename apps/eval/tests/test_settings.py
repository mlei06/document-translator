import os
from pathlib import Path

import keyring
import pytest
from pydantic import ValidationError

from doctranslator_eval.settings import EvalSettings, SettingsError

VARIABLES = [
    "DOCTRANSLATOR_LLM_BASE_URL",
    "DOCTRANSLATOR_LLM_API_KEY",
    "DOCTRANSLATOR_LLM_MODEL",
    "DOCTRANSLATOR_DATA_DIR",
    "HF_TOKEN",
]


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[tuple[str, str]]:
    """No real environment, .env, or OS vault; records vault lookups."""
    for name in os.environ:
        if name.startswith("DOCTRANSLATOR_") or name in VARIABLES:
            monkeypatch.delenv(name)
    monkeypatch.chdir(tmp_path)
    lookups: list[tuple[str, str]] = []

    def get_password(service: str, username: str) -> str | None:
        lookups.append((service, username))
        return None

    monkeypatch.setattr(keyring, "get_password", get_password)
    return lookups


def test_reads_environment_and_dotenv(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(
        "DOCTRANSLATOR_LLM_BASE_URL=https://llm.example/v1\n"
        "DOCTRANSLATOR_LLM_MODEL=from-dotenv\n"
        "DOCTRANSLATOR_LLM_API_KEY=\n"
        "HF_TOKEN=hf_token_value\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("DOCTRANSLATOR_LLM_MODEL", "from-env")
    monkeypatch.setenv("DOCTRANSLATOR_DATA_DIR", "elsewhere")
    settings = EvalSettings()
    assert str(settings.llm_base_url) == "https://llm.example/v1"
    assert settings.llm_model == "from-env"
    assert settings.llm_api_key is None  # empty values count as unset
    assert settings.data_dir == Path("elsewhere")
    assert settings.hf_token is not None
    assert settings.hf_token.get_secret_value() == "hf_token_value"


def test_api_key_falls_back_to_vault(
    monkeypatch: pytest.MonkeyPatch, isolated: list[tuple[str, str]]
) -> None:
    def get_password(service: str, username: str) -> str | None:
        isolated.append((service, username))
        return "vault-key"

    monkeypatch.setattr(keyring, "get_password", get_password)
    monkeypatch.setenv("DOCTRANSLATOR_LLM_BASE_URL", "https://llm.example/v1")
    monkeypatch.setenv("DOCTRANSLATOR_LLM_MODEL", "gemma")
    config = EvalSettings().llm_engine_config()
    assert config.api_key.get_secret_value() == "vault-key"
    assert isolated == [("doctranslator", "DOCTRANSLATOR_LLM_API_KEY")]


def test_environment_key_wins_over_vault(
    monkeypatch: pytest.MonkeyPatch, isolated: list[tuple[str, str]]
) -> None:
    monkeypatch.setenv("DOCTRANSLATOR_LLM_API_KEY", "env-key")
    key = EvalSettings().resolved_llm_api_key()
    assert key is not None
    assert key.get_secret_value() == "env-key"
    assert isolated == []


def test_missing_llm_settings_are_named() -> None:
    with pytest.raises(SettingsError) as caught:
        EvalSettings().llm_engine_config()
    message = str(caught.value)
    for name in [
        "DOCTRANSLATOR_LLM_BASE_URL",
        "DOCTRANSLATOR_LLM_API_KEY",
        "DOCTRANSLATOR_LLM_MODEL",
    ]:
        assert name in message


@pytest.mark.parametrize("profile", ["translategemma", "hy-mt2"])
def test_profile_settings_reach_core(monkeypatch: pytest.MonkeyPatch, profile: str) -> None:
    monkeypatch.setenv("DOCTRANSLATOR_LLM_BASE_URL", "http://127.0.0.1:8000/v1")
    monkeypatch.setenv("DOCTRANSLATOR_LLM_API_KEY", "local-placeholder")
    monkeypatch.setenv("DOCTRANSLATOR_LLM_MODEL", "served-model")
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
    config = EvalSettings().llm_engine_config()
    assert config.model_dump(include=set(expected)) == expected


def test_default_profile_preserves_generic_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCTRANSLATOR_LLM_BASE_URL", "http://127.0.0.1:8000/v1")
    monkeypatch.setenv("DOCTRANSLATOR_LLM_API_KEY", "local-placeholder")
    monkeypatch.setenv("DOCTRANSLATOR_LLM_MODEL", "served-model")
    config = EvalSettings().llm_engine_config()
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
def test_invalid_tuning_is_rejected(
    monkeypatch: pytest.MonkeyPatch, field: str, value: str
) -> None:
    monkeypatch.setenv(f"DOCTRANSLATOR_LLM_{field}", value)
    with pytest.raises(ValidationError, match=f"llm_{field.lower()}"):
        EvalSettings()


def test_specialized_profile_requires_deployment_revision(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCTRANSLATOR_LLM_BASE_URL", "http://127.0.0.1:8000/v1")
    monkeypatch.setenv("DOCTRANSLATOR_LLM_API_KEY", "local-placeholder")
    monkeypatch.setenv("DOCTRANSLATOR_LLM_MODEL", "served-model")
    monkeypatch.setenv("DOCTRANSLATOR_LLM_TRANSLATION_PROFILE", "hy-mt2")
    with pytest.raises(ValidationError, match="deployment_revision"):
        EvalSettings().llm_engine_config()
