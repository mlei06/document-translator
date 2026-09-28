"""LLM mode: the internal OpenAI-compatible chat completions server."""

import json
import logging
import random
import ssl
import time
from collections.abc import Callable, Sequence
from concurrent.futures import FIRST_EXCEPTION, ThreadPoolExecutor, wait
from typing import cast

import httpx
import truststore

from doctranslator_core.config import LlmEngineConfig
from doctranslator_core.engines.base import TranslationEngine
from doctranslator_core.engines.llm_prompts import PROMPT_VERSION, system_prompt, user_message
from doctranslator_core.types import (
    EngineAuthenticationError,
    EngineInfo,
    EngineResponseError,
    EngineUnavailableError,
    Language,
    TranslationError,
    TranslationIdentity,
    TranslationMode,
)

__all__ = ["LlmEngine", "prepare_identity"]

logger = logging.getLogger(__name__)

_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
_AUTH_STATUS = frozenset({401, 403})
_MAX_RETRY_AFTER_S = 30.0


class LlmEngine(TranslationEngine):
    def __init__(
        self,
        config: LlmEngineConfig,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """``transport`` and ``sleep`` exist for tests; production passes neither."""
        self._config = config
        self._sleep = sleep
        self._client = httpx.Client(
            base_url=str(config.base_url),
            headers={"Authorization": f"Bearer {config.api_key.get_secret_value()}"},
            timeout=config.timeout_s,
            verify=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT),
            transport=transport,
        )

    @property
    def info(self) -> EngineInfo:
        return EngineInfo(
            mode=TranslationMode.LLM,
            model=self._config.model,
            details={
                "prompt_version": PROMPT_VERSION,
                "temperature": str(self._config.temperature),
            },
        )

    @property
    def identity(self) -> TranslationIdentity:
        return prepare_identity(self._config)

    def translate_batch(
        self, texts: Sequence[str], source: Language, target: Language
    ) -> list[str]:
        system = system_prompt(source, target)
        size = self._config.batch_size
        chunks = [texts[i : i + size] for i in range(0, len(texts), size)]
        if len(chunks) <= 1:
            return [t for chunk in chunks for t in self._translate_chunk(chunk, system)]

        workers = min(self._config.max_concurrency, len(chunks))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(self._translate_chunk, chunk, system) for chunk in chunks]
            _, pending = wait(futures, return_when=FIRST_EXCEPTION)
            for future in pending:
                future.cancel()
            # Raises the first failure in chunk order; cancelled chunks never ran.
            return [t for future in futures for t in future.result()]

    def close(self) -> None:
        self._client.close()

    def _translate_chunk(self, chunk: Sequence[str], system: str) -> list[str]:
        translations = _parse_translations(self._complete(chunk, system), len(chunk))
        if translations is not None:
            return translations
        if len(chunk) == 1:
            raise EngineResponseError("unusable response for a single segment")
        logger.warning("unusable response for %d segments; splitting and retrying", len(chunk))
        middle = len(chunk) // 2
        return self._translate_chunk(chunk[:middle], system) + self._translate_chunk(
            chunk[middle:], system
        )

    def _complete(self, chunk: Sequence[str], system: str) -> str | None:
        """Send one chat completion and return the message content, if any."""
        body: dict[str, object] = {
            "model": self._config.model,
            "temperature": self._config.temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_message(chunk)},
            ],
        }
        if self._config.json_mode:
            body["response_format"] = {"type": "json_object"}
        return _message_content(self._post_with_retries(body, len(chunk)))

    def _post_with_retries(self, body: dict[str, object], segments: int) -> httpx.Response:
        max_retries = self._config.max_retries
        for attempt in range(max_retries + 1):
            started = time.perf_counter()
            retry_after: float | None = None
            try:
                response = self._client.post("chat/completions", json=body)
            except httpx.TransportError as exc:
                failure: TranslationError = EngineUnavailableError(
                    f"LLM server unreachable ({type(exc).__name__})"
                )
                failure.__cause__ = exc
            else:
                status = response.status_code
                logger.debug(
                    "request with %d segments: HTTP %d in %.2f s (attempt %d)",
                    segments,
                    status,
                    time.perf_counter() - started,
                    attempt + 1,
                )
                if response.is_success:
                    return response
                if status in _AUTH_STATUS:
                    raise EngineAuthenticationError(
                        f"LLM server rejected the credentials (HTTP {status})"
                    )
                failure = EngineResponseError(f"LLM server returned HTTP {status}")
                if status not in _RETRYABLE_STATUS:
                    raise failure
                retry_after = _retry_after_seconds(response)

            if attempt == max_retries:
                raise failure
            delay = retry_after if retry_after is not None else _backoff_seconds(attempt)
            logger.warning("%s; retry %d of %d in %.1f s", failure, attempt + 1, max_retries, delay)
            self._sleep(delay)
        raise AssertionError("unreachable")


def prepare_identity(config: LlmEngineConfig) -> TranslationIdentity:
    """The LLM engine's output identity from configuration alone (no network)."""
    return TranslationIdentity(
        mode=TranslationMode.LLM,
        model=config.model,
        details={
            "base_url": str(config.base_url).rstrip("/"),
            "deployment_revision": config.deployment_revision,
            "prompt_version": PROMPT_VERSION,
            "temperature": repr(config.temperature),
            "json_mode": str(config.json_mode).lower(),
            "batch_size": str(config.batch_size),
        },
    )


def _backoff_seconds(attempt: int) -> float:
    return min(2**attempt, 8) * random.uniform(0.75, 1.25)  # noqa: S311 - jitter, not security


def _retry_after_seconds(response: httpx.Response) -> float | None:
    """The ``Retry-After`` header in its seconds form, capped; the date form is ignored."""
    value = response.headers.get("Retry-After")
    if value is None:
        return None
    try:
        seconds = float(value)
    except ValueError:
        return None
    return min(max(seconds, 0.0), _MAX_RETRY_AFTER_S)


def _message_content(response: httpx.Response) -> str | None:
    """Extract ``choices[0].message.content``. A malformed envelope is a server error."""
    try:
        payload: object = response.json()
    except ValueError as exc:
        raise EngineResponseError("LLM server returned a response that is not JSON") from exc
    choices = cast(dict[str, object], payload).get("choices") if isinstance(payload, dict) else None
    if not isinstance(choices, list) or not choices:
        raise EngineResponseError("LLM server response has no choices")
    first: object = cast(list[object], choices)[0]
    message = cast(dict[str, object], first).get("message") if isinstance(first, dict) else None
    if not isinstance(message, dict):
        raise EngineResponseError("LLM server response has no message")
    content = cast(dict[str, object], message).get("content")
    return content if isinstance(content, str) else None


def _parse_translations(content: str | None, expected: int) -> list[str] | None:
    """The model's ``{"translations": [...]}`` answer, or ``None`` if it is unusable."""
    if content is None:
        return None
    text = _strip_code_fence(content.strip())
    try:
        parsed: object = json.loads(text)
    except ValueError:
        return None
    if not isinstance(parsed, dict):
        return None
    translations = cast(dict[str, object], parsed).get("translations")
    if not isinstance(translations, list):
        return None
    items = cast(list[object], translations)
    if len(items) != expected or not all(isinstance(item, str) for item in items):
        return None
    return cast(list[str], items)


def _strip_code_fence(text: str) -> str:
    """Remove a surrounding Markdown code fence (with an optional language tag), if present."""
    if not text.startswith("```"):
        return text
    lines = text.splitlines()[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines)
