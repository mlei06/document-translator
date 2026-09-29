"""CLI configuration: environment (``DOCTRANSLATOR_*``), then a ``.env`` file, then the OS vault.

Command-line options override all of these. The core never reads configuration itself (ADR-003).
"""

import os
from pathlib import Path
from typing import Literal

from pydantic import HttpUrl, SecretStr, ValidationError
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
    mt_model_dir: Path | None = None
    mt_model_family: Literal["small100"] = "small100"
    mt_device: Literal["cpu", "cuda", "auto"] = "auto"
    mt_compute_type: str = "default"
    mt_beam_size: int = 4
    mt_cpu_threads: int = 0
    font_dirs: str | None = None
    """Font directories for fit measurement, separated by the OS path separator."""

    def font_directories(self) -> list[Path]:
        from doctranslator_cli.fonts import default_font_directories

        if not self.font_dirs:
            return default_font_directories()
        return [Path(p) for p in self.font_dirs.split(os.pathsep) if p]

    def secret(self, name: str, value: SecretStr | None) -> SecretStr | None:
        """``value`` from the environment/``.env``, else the OS vault entry ``name``."""
        if value is not None:
            return value
        # Imported only when needed: keyring pulls in jaraco.context, which calls into
        # platform/WMI at import and can take many seconds on some Windows machines.
        import keyring
        from keyring.errors import KeyringError

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
