"""Configuration types and validation. Never reads the environment."""

from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, SecretStr

from doctranslator_core.types import TranslationMode

__all__ = ["EngineConfig", "LlmEngineConfig", "MtEngineConfig"]


class LlmEngineConfig(BaseModel):
    """The internal LLM server (OpenAI-compatible chat completions)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    mode: Literal[TranslationMode.LLM] = TranslationMode.LLM
    base_url: HttpUrl
    """OpenAI-compatible API root, e.g. ``https://host:port/v1``."""
    api_key: SecretStr
    model: str
    timeout_s: float = Field(default=120.0, gt=0)
    max_retries: int = Field(default=3, ge=0)
    batch_size: int = Field(default=16, ge=1)
    """Segments per request."""
    max_concurrency: int = Field(default=4, ge=1)
    """Concurrent requests per ``translate_texts`` call."""
    temperature: float = Field(default=0.0, ge=0, le=2)
    json_mode: bool = True
    """Send ``response_format: {"type": "json_object"}``. Disable for servers that reject it."""


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
