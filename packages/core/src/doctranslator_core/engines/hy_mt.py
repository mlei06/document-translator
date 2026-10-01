"""HY-MT plain-text protocol over an administrator-managed chat completion endpoint.

The endpoint owns model loading, threads and GPU offload. This adapter only owns translation.
Prompt templates: https://github.com/Tencent-Hunyuan/HY-MT#prompts
"""

import json
import re
from collections.abc import Sequence
from concurrent.futures import FIRST_EXCEPTION, ThreadPoolExecutor, wait
from typing import cast

from doctranslator_core.config import LlmEngineConfig
from doctranslator_core.engines.llm import LlmEngine
from doctranslator_core.types import (
    LANGUAGE_NAMES,
    EngineInfo,
    EngineResponseError,
    Language,
    TranslationIdentity,
    TranslationMode,
)

PROMPT_VERSION = "hy-mt-target-only-v3"
_SAMPLING = {"top_k": 20, "top_p": 0.6, "repeat_penalty": 1.05, "seed": 42}
_MARKER = re.compile(r"</?g\d+>|<x\d+\s*/>|</?ph\d+\s*/?>")


def user_prompt(text: str, target: Language) -> str:
    instruction = (
        f"Translate the following text into {LANGUAGE_NAMES[target]}. "
        "Note that you should only output the translated result without any additional explanation:"
    )
    if _MARKER.search(text):
        instruction = (
            "Preserve every formatting tag and placeholder from the source exactly. "
            "Do not change, remove or add tags. Translate the text inside tags.\n" + instruction
        )
    return f"{instruction}\n\n{text}"


class HyMtEngine(LlmEngine):
    """Reuse authenticated transport/retries, with HY-MT-specific requests and validation."""

    @property
    def info(self) -> EngineInfo:
        identity = self.identity
        return EngineInfo(mode=identity.mode, model=identity.model, details=identity.details)

    @property
    def identity(self) -> TranslationIdentity:
        return prepare_identity(self._config)

    def translate_batch(
        self, texts: Sequence[str], source: Language | None = None, target: Language | None = None
    ) -> list[str]:
        if target is None:
            raise ValueError("target language is required")
        if not texts:
            return []
        if self._config.max_concurrency == 1 or len(texts) == 1:
            return [self._translate_one(text, source, target) for text in texts]
        with ThreadPoolExecutor(max_workers=min(self._config.max_concurrency, len(texts))) as pool:
            futures = [pool.submit(self._translate_one, text, source, target) for text in texts]
            _, pending = wait(futures, return_when=FIRST_EXCEPTION)
            for future in pending:
                future.cancel()
            return [future.result() for future in futures]

    def _translate_one(self, text: str, source: Language | None, target: Language) -> str:
        response = self._post_with_retries(
            {
                "model": self._config.model,
                "temperature": self._config.temperature,
                "max_tokens": self._config.max_output_tokens,
                **_SAMPLING,
                "cache_prompt": False,
                "messages": [{"role": "user", "content": user_prompt(text, target)}],
            },
            1,
        )
        try:
            payload: object = response.json()
            if not isinstance(payload, dict):
                raise ValueError
            choices = cast(dict[str, object], payload).get("choices")
            if not isinstance(choices, list):
                raise ValueError
            items = cast(list[object], choices)
            if len(items) != 1 or not isinstance(items[0], dict):
                raise ValueError
            choice = cast(dict[str, object], items[0])
            reason = choice.get("finish_reason")
            if reason == "length":
                raise EngineResponseError("HY-MT translation exceeded the output token limit")
            if reason != "stop":
                raise ValueError
            message = choice.get("message")
            if not isinstance(message, dict):
                raise ValueError
            content = cast(dict[str, object], message).get("content")
            if not isinstance(content, str) or not content.strip():
                raise ValueError
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise EngineResponseError(
                "HY-MT returned an incomplete or malformed translation"
            ) from exc
        return content


def prepare_identity(config: LlmEngineConfig) -> TranslationIdentity:
    return TranslationIdentity(
        mode=TranslationMode.LLM,
        model=config.model,
        details={
            **(
                {"managed_runtime_identity": config.managed_runtime_identity}
                if config.managed_runtime_identity is not None
                else {"base_url": str(config.base_url).rstrip("/")}
            ),
            "deployment_revision": config.deployment_revision,
            "protocol": "hy-mt",
            "response_model_aliases": json.dumps(sorted(config.response_model_aliases)),
            "prompt_version": PROMPT_VERSION,
            "temperature": repr(config.temperature),
            "max_output_tokens": str(config.max_output_tokens),
            **{key: str(value) for key, value in _SAMPLING.items()},
        },
    )
