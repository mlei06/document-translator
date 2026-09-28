from pathlib import Path

import pytest
from pydantic import HttpUrl, SecretStr, TypeAdapter, ValidationError

from doctranslator_core import EngineConfig, LlmEngineConfig, MtEngineConfig
from doctranslator_core.types import LANGUAGE_NAMES, Language, TranslationMode

API_KEY = "sk-test-secret-value"


def llm_config(**overrides: object) -> LlmEngineConfig:
    values: dict[str, object] = {
        "base_url": "https://llm.example/v1",
        "api_key": API_KEY,
        "model": "gemma",
    }
    return LlmEngineConfig.model_validate(values | overrides)


def test_enum_values() -> None:
    assert [lang.value for lang in Language] == ["zh", "en", "ja", "es"]
    assert [mode.value for mode in TranslationMode] == ["llm", "mt"]
    assert set(LANGUAGE_NAMES) == set(Language)


def test_llm_defaults() -> None:
    config = LlmEngineConfig(
        base_url=HttpUrl("https://llm.example/v1"), api_key=SecretStr(API_KEY), model="gemma"
    )
    assert config.mode is TranslationMode.LLM
    assert (config.batch_size, config.max_concurrency, config.max_retries) == (16, 4, 3)
    assert config.temperature == 0.0
    assert config.json_mode is True


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("batch_size", 0),
        ("max_concurrency", 0),
        ("max_retries", -1),
        ("timeout_s", 0),
        ("temperature", -0.1),
        ("temperature", 2.1),
    ],
)
def test_llm_bounds(field: str, value: float) -> None:
    with pytest.raises(ValidationError):
        llm_config(**{field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    [("beam_size", 0), ("max_batch_size", 0), ("cpu_threads", -1)],
)
def test_mt_bounds(field: str, value: int) -> None:
    values: dict[str, object] = {"model_dir": "m", "model_family": "small100", field: value}
    with pytest.raises(ValidationError):
        MtEngineConfig.model_validate(values)


def test_unknown_fields_and_mutation_rejected() -> None:
    with pytest.raises(ValidationError):
        llm_config(unexpected=1)
    config = llm_config()
    with pytest.raises(ValidationError):
        config.model = "other"  # pyright: ignore[reportAttributeAccessIssue]


def test_discriminated_union_parses_both_modes() -> None:
    adapter: TypeAdapter[EngineConfig] = TypeAdapter(EngineConfig)
    llm = adapter.validate_python(
        {"mode": "llm", "base_url": "https://llm.example/v1", "api_key": API_KEY, "model": "g"}
    )
    mt = adapter.validate_python(
        {"mode": "mt", "model_dir": "models/x", "model_family": "small100"}
    )
    assert isinstance(llm, LlmEngineConfig)
    assert isinstance(mt, MtEngineConfig)
    assert mt.model_dir == Path("models/x")
    with pytest.raises(ValidationError):
        adapter.validate_python({"mode": "mt", "model_dir": "x", "model_family": "unknown"})


def test_api_key_never_shown() -> None:
    config = llm_config()
    assert API_KEY not in repr(config)
    assert API_KEY not in str(config)
    assert API_KEY not in config.model_dump_json()
    assert config.api_key.get_secret_value() == API_KEY
