"""Eval configuration: environment first (``DOCTRANSLATOR_*``, ``.env``), then the OS vault."""

from pathlib import Path
from typing import Literal

import keyring
from keyring.errors import KeyringError
from pydantic import Field, HttpUrl, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from doctranslator_core import LlmEngineConfig

KEYRING_SERVICE = "doctranslator"
KEYRING_USERNAME = "DOCTRANSLATOR_LLM_API_KEY"


class SettingsError(Exception):
    """Required configuration is missing."""


class EvalSettings(BaseSettings):
    """Read from the environment and ``.env`` in the current directory (the repository root)."""

    model_config = SettingsConfigDict(
        env_prefix="DOCTRANSLATOR_", env_file=".env", env_ignore_empty=True, extra="ignore"
    )

    llm_base_url: HttpUrl | None = None
    llm_api_key: SecretStr | None = None
    llm_model: str | None = None
    llm_deployment_revision: str = ""
    llm_translation_profile: Literal["generic", "translategemma", "hy-mt2"] = "generic"
    llm_server_backend: Literal["openai", "llamacpp"] = "openai"
    llm_max_concurrency: int = Field(default=4, ge=1)
    llm_temperature: float = Field(default=0.0, ge=0, le=2)
    llm_max_output_tokens: int = Field(default=2048, ge=1)
    llm_top_p: float = Field(default=1.0, gt=0, le=1)
    llm_top_k: int = Field(default=0, ge=0)
    llm_repetition_penalty: float = Field(default=1.0, gt=0)
    llm_seed: int = Field(default=0, ge=0)
    data_dir: Path = Path("data")
    hf_token: SecretStr | None = Field(default=None, validation_alias="HF_TOKEN")

    def resolved_llm_api_key(self) -> SecretStr | None:
        """The API key from the environment, else from the OS vault, else ``None``."""
        if self.llm_api_key is not None:
            return self.llm_api_key
        try:
            stored = keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME)
        except KeyringError:
            return None
        return SecretStr(stored) if stored else None

    def llm_engine_config(self) -> LlmEngineConfig:
        base_url, api_key, model = self.llm_base_url, self.resolved_llm_api_key(), self.llm_model
        if base_url is None or api_key is None or model is None:
            missing = [
                name
                for name, value in (
                    ("DOCTRANSLATOR_LLM_BASE_URL", base_url),
                    ("DOCTRANSLATOR_LLM_API_KEY", api_key),
                    ("DOCTRANSLATOR_LLM_MODEL", model),
                )
                if value is None
            ]
            raise SettingsError(f"LLM mode needs these settings: {', '.join(missing)}")
        return LlmEngineConfig(
            base_url=base_url,
            api_key=api_key,
            model=model,
            deployment_revision=self.llm_deployment_revision,
            translation_profile=self.llm_translation_profile,
            server_backend=self.llm_server_backend,
            max_concurrency=self.llm_max_concurrency,
            temperature=self.llm_temperature,
            max_output_tokens=self.llm_max_output_tokens,
            top_p=self.llm_top_p,
            top_k=self.llm_top_k,
            repetition_penalty=self.llm_repetition_penalty,
            seed=self.llm_seed,
        )
