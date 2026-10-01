"""Configuration types and validation. Never reads the environment."""

import ipaddress
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, SecretStr, model_validator

from doctranslator_core.types import TranslationMode

__all__ = ["DocumentLimits", "EngineConfig", "LlmEngineConfig", "MtEngineConfig"]


class LlmEngineConfig(BaseModel):
    """The internal LLM server (OpenAI-compatible chat completions)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    mode: Literal[TranslationMode.LLM] = TranslationMode.LLM
    base_url: HttpUrl
    """OpenAI-compatible API root, e.g. ``https://host:port/v1``."""
    api_key: SecretStr
    model: str
    response_model_aliases: tuple[str, ...] = ()
    """Explicit approved provider names returned for this requested deployment."""
    timeout_s: float = Field(default=120.0, gt=0, allow_inf_nan=False)
    max_retries: int = Field(default=2, ge=0)
    batch_size: int = Field(default=16, ge=1)
    """Segments per request."""
    max_concurrency: int = Field(default=4, ge=1)
    """Concurrent requests per ``translate_texts`` call."""
    temperature: float = Field(default=0.0, ge=0, le=2)
    json_mode: bool = True
    """Send ``response_format: {"type": "json_object"}``. Disable for servers that reject it."""
    deployment_revision: str = ""
    """The operator's declared revision of the model served as ``model``. Part of the output
    identity (ADR-011); change it when the server's model changes under an unchanged name."""

    protocol: Literal["json-batch", "hy-mt"] = "json-batch"
    execution_location: Literal["server", "remote"] = "remote"
    """Location metadata. Server-local HTTP endpoints must use a loopback address."""
    managed_runtime_identity: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    """Verified weights/runtime/settings digest for a managed local HY-MT process.

    Its ephemeral loopback port is transport metadata, not part of the model identity.
    """
    max_output_tokens: int = Field(default=2048, ge=1, le=32768)
    """HY-MT output limit. A response hitting this limit is rejected, never published."""

    @model_validator(mode="after")
    def validate_protocol(self) -> LlmEngineConfig:
        if (
            len(self.response_model_aliases) > 8
            or len(set(self.response_model_aliases)) != len(self.response_model_aliases)
            or any(not alias.strip() or len(alias) > 256 for alias in self.response_model_aliases)
        ):
            raise ValueError("response model aliases must be distinct nonempty bounded names")
        if self.managed_runtime_identity is not None and (
            self.protocol != "hy-mt" or self.execution_location != "server"
        ):
            raise ValueError("managed runtime identity requires server-local HY-MT")
        if self.protocol == "hy-mt" and not self.deployment_revision.strip():
            raise ValueError("HY-MT requires deployment_revision for weights and runtime settings")
        if self.execution_location == "server":
            host = (self.base_url.host or "").strip("[]")
            if host != "localhost":
                try:
                    local = ipaddress.ip_address(host).is_loopback
                except ValueError:
                    local = False
                if not local:
                    raise ValueError("server execution_location requires a loopback endpoint")
        return self


class MtEngineConfig(BaseModel):
    """A local machine translation model, converted to CTranslate2."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    mode: Literal[TranslationMode.MT] = TranslationMode.MT
    model_dir: Path
    """Directory of a CTranslate2-converted model, including its tokenizer files."""
    model_family: Literal["small100"]
    """Selects tokenizer and language-token conventions."""
    device: Literal["cpu", "cuda", "auto"] = "auto"
    compute_type: str = "default"
    """CTranslate2 compute type (e.g. ``int8``); ``default`` keeps the converted precision."""
    beam_size: int = Field(default=4, ge=1)
    max_batch_size: int = Field(default=32, ge=1)
    """Segments per inference batch."""
    cpu_threads: int = Field(default=0, ge=0)
    """``0`` lets CTranslate2 decide."""


type EngineConfig = Annotated[LlmEngineConfig | MtEngineConfig, Field(discriminator="mode")]
"""Either engine's configuration, discriminated by ``mode``."""


class DocumentLimits(BaseModel):
    """Resource limits applied before any engine call (ADR-011 section 7). Nothing is truncated."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_package_bytes: int = Field(default=1 << 30, ge=1)
    """Total uncompressed size of an Office package."""
    max_entry_bytes: int = Field(default=128 << 20, ge=1)
    """Uncompressed size of one package entry."""
    max_entries: int = Field(default=20_000, ge=1)
    max_compression_ratio: float = Field(default=1000.0, gt=1)
    """Largest allowed uncompressed/compressed ratio of one entry."""
    max_text_bytes: int = Field(default=100 << 20, ge=1)
    """Size of a TXT or PDF input file."""
    max_segments: int = Field(default=200_000, ge=1)
    """Translatable paragraphs in one document."""
