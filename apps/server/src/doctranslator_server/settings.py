"""Server configuration from the environment (``DOCTRANSLATOR_*``) and an optional ``.env`` file.

The core never reads configuration (ADR-003); this module builds the public core configuration
for each translation mode. Defaults are the ADR-016 operational defaults.
"""

import ipaddress
import os
from pathlib import Path
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    SecretStr,
    ValidationError,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

from doctranslator_core import EngineConfig, LlmEngineConfig, MtEngineConfig
from doctranslator_core.types import TranslationMode

__all__ = ["ServerSettings", "SettingsError", "load_settings"]


class SettingsError(Exception):
    """Configuration is missing or invalid. The message names settings, never their values."""


class ConfiguredTranslator(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}$")
    label: str = Field(min_length=1, max_length=100)
    enabled: bool = True
    engine: EngineConfig


class DavyModel(BaseModel):
    """An administrator-approved translation model on the shared Davy endpoint."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}$")
    label: str = Field(min_length=1, max_length=100)
    model: str = Field(min_length=1)
    response_model_aliases: tuple[str, ...] = ()
    enabled: bool = True
    deployment_revision: str = ""
    json_mode: bool = True
    batch_size: int = Field(default=16, ge=1)
    max_concurrency: int = Field(default=4, ge=1)


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

    web_dir: Path | None = None
    """The built web UI (``apps/web/dist``); served at ``/`` when set (ADR-017)."""

    registration_enabled: bool = False

    workers: int = Field(default=1, ge=0, le=32)
    poll_s: float = Field(default=1.0, gt=0)
    heartbeat_s: float = Field(default=20.0, gt=0)
    lease_s: float = Field(default=120.0, gt=0)
    max_attempts: int = Field(default=3, ge=1, le=10)
    retry_delays_s: tuple[float, ...] = (10.0, 30.0)

    max_upload_bytes: int = Field(default=100 << 20, ge=1)
    max_queued_jobs: int = Field(default=1000, ge=1)
    max_queued_jobs_per_user: int = Field(default=200, ge=1)
    web_translation_policy: dict[str, object] | None = None
    global_blob_budget_bytes: int = Field(default=100 << 30, ge=1)
    global_work_budget_bytes: int = Field(default=8 << 30, ge=1)
    max_output_bytes: int = Field(default=200 << 20, ge=1)
    max_report_bytes: int = Field(default=16 << 20, ge=1)
    max_workspace_bytes: int = Field(default=1 << 30, ge=1)
    backup_budget_bytes: int = Field(default=100 << 30, ge=1)
    daily_backups: bool = True

    temporary_retention_hours: int = Field(default=24, ge=1)
    """Temporary job results (``retention=temporary``) are downloadable this long (ADR-014)."""
    superseded_retention_days: int = Field(default=7, ge=0)
    """A replaced current translation stays downloadable through its jobs this long."""
    job_retention_days: int = Field(default=30, ge=1)
    """Terminal job and batch metadata (without a live result) is kept this long."""
    staging_retention_hours: int = Field(default=24, ge=1)
    owner_quota_bytes: int = Field(default=20 << 30, ge=1)
    """Saved library limit per owner: sources plus current translations (no automatic expiry)."""

    translators: list[ConfiguredTranslator] | None = None
    davy_base_url: HttpUrl | None = None
    davy_api_key: SecretStr | None = None
    davy_models: list[DavyModel] = Field(default_factory=list[DavyModel])
    default_translator_id: str | None = None
    max_loaded_local_models: int = Field(default=1, ge=1, le=32)

    @model_validator(mode="after")
    def validate_translators(self) -> ServerSettings:
        entries = self.translators or []
        ids = [entry.id for entry in entries] + [entry.id for entry in self.davy_models]
        if self.translators is None:
            ids += [mode.value for mode in self._legacy_modes()]
        if len(ids) != len(set(ids)):
            raise ValueError("translator IDs must be unique")
        enabled = [entry.id for entry in entries if entry.enabled]
        enabled += [entry.id for entry in self.davy_models if entry.enabled]
        if self.translators is None:
            enabled += [mode.value for mode in self._legacy_modes()]
        if self.translators is not None or self.davy_models:
            if enabled and self.default_translator_id not in enabled:
                raise ValueError("default_translator_id must identify an enabled translator")
            if not enabled and self.default_translator_id is not None:
                raise ValueError("default_translator_id requires an enabled translator")
        elif self.default_translator_id is not None and self.default_translator_id not in enabled:
            raise ValueError("default_translator_id must identify an available translator")
        return self

    llm_base_url: HttpUrl | None = None
    llm_api_key: SecretStr | None = None
    llm_model: str | None = None
    llm_deployment_revision: str = ""
    llm_protocol: Literal["json-batch", "hy-mt"] = "json-batch"
    llm_execution_location: Literal["server", "remote"] = "remote"
    llm_max_output_tokens: int = 2048
    llm_max_concurrency: int = 4
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

    def configured_translators(self) -> list[ConfiguredTranslator]:
        entries = (
            [entry for entry in self.translators if entry.enabled]
            if self.translators is not None
            else [
                ConfiguredTranslator(
                    id=mode.value, label=mode.value.upper(), engine=self.engine_config(mode)
                )
                for mode in self._legacy_modes()
            ]
        )
        if (
            self.davy_base_url
            and self.davy_api_key
            and self.davy_api_key.get_secret_value().strip()
        ):
            entries.extend(
                ConfiguredTranslator(
                    id=model.id,
                    label=model.label,
                    engine=LlmEngineConfig(
                        base_url=self.davy_base_url,
                        api_key=self.davy_api_key,
                        response_model_aliases=model.response_model_aliases
                        or (("gpt-oss-120b",) if model.model == "gpt-oss-120b-thinking" else ()),
                        **model.model_dump(
                            exclude={"id", "label", "enabled", "response_model_aliases"}
                        ),
                    ),
                )
                for model in self.davy_models
                if model.enabled
            )
        return entries

    def available_modes(self) -> list[TranslationMode]:
        return list(dict.fromkeys(entry.engine.mode for entry in self.configured_translators()))

    def _legacy_modes(self) -> list[TranslationMode]:
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
                    protocol=self.llm_protocol,
                    execution_location=self.llm_execution_location,
                    max_output_tokens=self.llm_max_output_tokens,
                    max_concurrency=self.llm_max_concurrency,
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
