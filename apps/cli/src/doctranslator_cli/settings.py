"""CLI configuration: environment (``DOCTRANSLATOR_*``), then a ``.env`` file, then the OS vault.

Command-line options override all of these. The core never reads configuration itself (ADR-003).
"""

from pathlib import Path
from typing import Literal

import keyring
from keyring.errors import KeyringError
from pydantic import Field, HttpUrl, SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from doctranslator_core import EngineConfig, LlmEngineConfig, MtEngineConfig
from doctranslator_core.types import TranslationMode

__all__ = ["CliSettings", "SettingsError", "load_settings"]

KEYRING_SERVICE = "doctranslator"


class SettingsError(Exception):
    """Configuration is missing or invalid. The message names the settings, never their values."""


class CliSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="DOCTRANSLATOR_", env_ignore_empty=True, extra="ignore"
    )

    mode: TranslationMode = TranslationMode.MT
    """Default translation mode when ``--mode`` is not given."""
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
    mt_model_dir: Path | None = None
    mt_model_family: Literal["small100"] = "small100"
    mt_device: Literal["cpu", "cuda", "auto"] = "auto"
    mt_compute_type: str = "default"
    mt_beam_size: int = 4
    mt_cpu_threads: int = 0

    def secret(self, name: str, value: SecretStr | None) -> SecretStr | None:
        """``value`` from the environment/``.env``, else the OS vault entry ``name``."""
        if value is not None:
            return value
        try:
            stored = keyring.get_password(KEYRING_SERVICE, name)
        except KeyringError:
            return None
        return SecretStr(stored) if stored else None

    def engine_config(self, mode: TranslationMode) -> EngineConfig:
        match mode:
            case TranslationMode.LLM:
                api_key = self.secret("DOCTRANSLATOR_LLM_API_KEY", self.llm_api_key)
                missing = [
                    name
                    for name, value in (
                        ("DOCTRANSLATOR_LLM_BASE_URL", self.llm_base_url),
                        ("DOCTRANSLATOR_LLM_API_KEY", api_key),
                        ("DOCTRANSLATOR_LLM_MODEL", self.llm_model),
                    )
                    if value is None
                ]
                base_url, model = self.llm_base_url, self.llm_model
                if missing or api_key is None or base_url is None or model is None:
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
            case TranslationMode.MT:
                if self.mt_model_dir is None:
                    raise SettingsError("MT mode needs DOCTRANSLATOR_MT_MODEL_DIR")
                return MtEngineConfig(
                    model_dir=self.mt_model_dir,
                    model_family=self.mt_model_family,
                    device=self.mt_device,
                    compute_type=self.mt_compute_type,
                    beam_size=self.mt_beam_size,
                    cpu_threads=self.mt_cpu_threads,
                )


def load_settings(env_file: Path | None) -> CliSettings:
    """Settings from the environment and ``env_file`` (default: ``./.env`` when present)."""
    path = env_file if env_file is not None else Path(".env")
    if env_file is not None and not env_file.is_file():
        raise SettingsError(f"configuration file not found: {env_file}")
    try:
        env = path if path.is_file() else None
        return CliSettings(_env_file=env)  # pyright: ignore[reportCallIssue]
    except ValidationError as exc:
        fields = sorted({".".join(str(p) for p in error["loc"]) for error in exc.errors()})
        raise SettingsError(f"invalid settings: {', '.join(fields)}") from None
