"""Server configuration from the environment (``DOCTRANSLATOR_*``) and an optional ``.env`` file.

The core never reads configuration (ADR-003); this module builds the public core configuration
for each translation mode. Defaults are the ADR-016 operational defaults.
"""

import ipaddress
import os
from pathlib import Path
from typing import Literal

from pydantic import Field, HttpUrl, SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from doctranslator_core import EngineConfig, LlmEngineConfig, MtEngineConfig
from doctranslator_core.types import TranslationMode

__all__ = ["ServerSettings", "SettingsError", "load_settings"]


class SettingsError(Exception):
    """Configuration is missing or invalid. The message names settings, never their values."""


class ServerSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="DOCTRANSLATOR_", env_ignore_empty=True, extra="ignore"
    )

    data_dir: Path = Path("data/server")
    """Database, blobs, staging and the font-manifest cache."""
    database_url: str | None = None
    """SQLAlchemy URL; default ``sqlite:///<data_dir>/doctranslator.db``."""

    server_host: str = "127.0.0.1"
    server_port: int = Field(default=8765, ge=1, le=65535)
    server_tls_cert: Path | None = None
    server_tls_key: Path | None = None
    server_behind_proxy: bool = False
    """A trusted TLS-terminating reverse proxy is in front of a non-loopback bind (ADR-015)."""

    workers: int = Field(default=1, ge=0, le=32)
    poll_s: float = Field(default=1.0, gt=0)
    heartbeat_s: float = Field(default=20.0, gt=0)
    lease_s: float = Field(default=120.0, gt=0)
    max_attempts: int = Field(default=3, ge=1, le=10)
    retry_delays_s: tuple[float, ...] = (10.0, 30.0)

    max_upload_bytes: int = Field(default=100 << 20, ge=1)
    max_queued_jobs: int = Field(default=1000, ge=1)
    max_queued_jobs_per_user: int = Field(default=200, ge=1)

    cache_retention_days: int = Field(default=30, ge=1)
    document_retention_days: int = Field(default=90, ge=1)
    job_retention_days: int = Field(default=90, ge=1)
    staging_retention_hours: int = Field(default=24, ge=1)

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
    """Font directories for fit and PDF output, separated by the OS path separator."""

    @property
    def database(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{(self.data_dir / 'doctranslator.db').as_posix()}"

    @property
    def loopback(self) -> bool:
        if self.server_host == "localhost":
            return True
        try:
            return ipaddress.ip_address(self.server_host).is_loopback
        except ValueError:
            return False

    def check_network(self) -> None:
        """ADR-015: a non-loopback bind needs TLS here or a declared TLS-terminating proxy."""
        if self.loopback or self.server_behind_proxy:
            return
        if self.server_tls_cert is None or self.server_tls_key is None:
            raise SettingsError(
                "a non-loopback DOCTRANSLATOR_SERVER_HOST needs DOCTRANSLATOR_SERVER_TLS_CERT and "
                "DOCTRANSLATOR_SERVER_TLS_KEY (or DOCTRANSLATOR_SERVER_BEHIND_PROXY=true)"
            )

    def font_directories(self) -> list[Path]:
        if self.font_dirs:
            return [Path(p) for p in self.font_dirs.split(os.pathsep) if p]
        if os.name == "nt":
            windows = Path(os.environ.get("WINDIR", "C:\\Windows")) / "Fonts"
            local = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
            return [
                windows,
                local / "Microsoft" / "Windows" / "Fonts",
                local / "Microsoft" / "FontCache" / "4" / "CloudFonts",
            ]
        return [Path("/usr/share/fonts"), Path("/usr/local/share/fonts")]

    def available_modes(self) -> list[TranslationMode]:
        modes: list[TranslationMode] = []
        if self.mt_model_dir is not None:
            modes.append(TranslationMode.MT)
        if self.llm_base_url and self.llm_api_key and self.llm_model:
            modes.append(TranslationMode.LLM)
        return modes

    def engine_config(self, mode: TranslationMode) -> EngineConfig:
        match mode:
            case TranslationMode.LLM:
                if not (self.llm_base_url and self.llm_api_key and self.llm_model):
                    raise SettingsError(
                        "LLM mode needs DOCTRANSLATOR_LLM_BASE_URL, DOCTRANSLATOR_LLM_API_KEY "
                        "and DOCTRANSLATOR_LLM_MODEL"
                    )
                return LlmEngineConfig(
                    base_url=self.llm_base_url,
                    api_key=self.llm_api_key,
                    model=self.llm_model,
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


def load_settings(env_file: Path | None = None) -> ServerSettings:
    """Settings from the environment and ``env_file`` (default: ``./.env`` when present)."""
    path = env_file if env_file is not None else Path(".env")
    if env_file is not None and not env_file.is_file():
        raise SettingsError(f"configuration file not found: {env_file}")
    try:
        env = path if path.is_file() else None
        return ServerSettings(_env_file=env)  # pyright: ignore[reportCallIssue]
    except ValidationError as exc:
        fields = sorted({".".join(str(p) for p in error["loc"]) for error in exc.errors()})
        raise SettingsError(f"invalid settings: {', '.join(fields)}") from None
