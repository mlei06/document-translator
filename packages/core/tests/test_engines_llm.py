import json
import threading
from collections.abc import Callable

import httpx
import pytest

from doctranslator_core import LlmEngineConfig
from doctranslator_core.engines.llm import LlmEngine
from doctranslator_core.engines.llm_prompts import PROMPT_VERSION
from doctranslator_core.types import (
    EngineAuthenticationError,
    EngineResponseError,
    EngineUnavailableError,
    Language,
    TranslationError,
)

API_KEY = "sk-test-secret-value"

type Handler = Callable[[httpx.Request], httpx.Response]


def config(**overrides: object) -> LlmEngineConfig:
    values: dict[str, object] = {
        "base_url": "https://llm.example/v1",
        "api_key": API_KEY,
        "model": "gemma",
        "batch_size": 2,
        "max_concurrency": 3,
    }
    return LlmEngineConfig.model_validate(values | overrides)


def segments_of(request: httpx.Request) -> list[str]:
    body = json.loads(request.content)
    return json.loads(body["messages"][1]["content"])["segments"]


def completion(content: str) -> httpx.Response:
    body = {"choices": [{"message": {"role": "assistant", "content": content}}]}
    return httpx.Response(200, json=body)


def translations(texts: list[str]) -> httpx.Response:
    return completion(json.dumps({"translations": [f"T({t})" for t in texts]}))


class Recorder:
    """A mock transport that records requests and the engine's retry sleeps."""

    def __init__(self, handler: Handler) -> None:
        self.requests: list[httpx.Request] = []
        self.sleeps: list[float] = []
        self._handler = handler
        self._lock = threading.Lock()

    def engine(self, **overrides: object) -> LlmEngine:
        return LlmEngine(
            config(**overrides),
            transport=httpx.MockTransport(self._handle),
            sleep=self.sleeps.append,
        )

    def _handle(self, request: httpx.Request) -> httpx.Response:
        with self._lock:
            self.requests.append(request)
        return self._handler(request)


def translate(engine: LlmEngine, texts: list[str]) -> list[str]:
    return engine.translate_batch(texts, Language.ZH, Language.EN)


def test_batches_concurrently_and_preserves_order() -> None:
    recorder = Recorder(lambda request: translations(segments_of(request)))
    texts = [f"s{i}" for i in range(5)]
    assert translate(recorder.engine(), texts) == [f"T(s{i})" for i in range(5)]
    assert sorted(len(segments_of(r)) for r in recorder.requests) == [1, 2, 2]


def test_request_shape_and_auth_header() -> None:
    recorder = Recorder(lambda request: translations(segments_of(request)))
    translate(recorder.engine(), ["你好"])
    request = recorder.requests[0]
    assert request.url == "https://llm.example/v1/chat/completions"
    assert request.headers["Authorization"] == f"Bearer {API_KEY}"
    body = json.loads(request.content)
    assert body["model"] == "gemma"
    assert body["temperature"] == 0.0
    assert body["response_format"] == {"type": "json_object"}
    assert "Simplified Chinese to English" in body["messages"][0]["content"]
    assert json.loads(body["messages"][1]["content"]) == {"segments": ["你好"]}


def test_json_mode_off_omits_response_format() -> None:
    recorder = Recorder(lambda request: translations(segments_of(request)))
    translate(recorder.engine(json_mode=False), ["a"])
    assert "response_format" not in json.loads(recorder.requests[0].content)


def test_code_fenced_json_is_accepted() -> None:
    fenced = '```json\n{"translations": ["Hello"]}\n```'
    recorder = Recorder(lambda request: completion(fenced))
    assert translate(recorder.engine(), ["你好"]) == ["Hello"]


def test_count_mismatch_splits_and_succeeds() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        texts = segments_of(request)
        if len(texts) > 1:
            return completion(json.dumps({"translations": ["merged"]}))
        return translations(texts)

    recorder = Recorder(handler)
    assert translate(recorder.engine(batch_size=4), ["a", "b", "c"]) == ["T(a)", "T(b)", "T(c)"]


def test_persistent_garbage_for_one_segment_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        texts = segments_of(request)
        return completion("not json") if "bad" in texts else translations(texts)

    recorder = Recorder(handler)
    with pytest.raises(EngineResponseError, match="single segment"):
        translate(recorder.engine(batch_size=4), ["ok", "bad"])


def test_429_honors_retry_after_then_succeeds() -> None:
    responses = iter([httpx.Response(429, headers={"Retry-After": "3"})])

    def handler(request: httpx.Request) -> httpx.Response:
        return next(responses, None) or translations(segments_of(request))

    recorder = Recorder(handler)
    assert translate(recorder.engine(), ["a"]) == ["T(a)"]
    assert recorder.sleeps == [3.0]


def test_retry_after_is_capped() -> None:
    responses = iter([httpx.Response(503, headers={"Retry-After": "3600"})])

    def handler(request: httpx.Request) -> httpx.Response:
        return next(responses, None) or translations(segments_of(request))

    recorder = Recorder(handler)
    translate(recorder.engine(), ["a"])
    assert recorder.sleeps == [30.0]


def test_503_exhausts_retries_with_backoff() -> None:
    recorder = Recorder(lambda request: httpx.Response(503))
    with pytest.raises(EngineResponseError, match="503") as caught:
        translate(recorder.engine(max_retries=3), ["a"])
    assert len(recorder.requests) == 4
    assert len(recorder.sleeps) == 3
    for sleep, base in zip(recorder.sleeps, [1, 2, 4], strict=True):
        assert 0.75 * base <= sleep <= 1.25 * base
    assert API_KEY not in str(caught.value)


def test_connection_error_is_unavailable_after_retries() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    recorder = Recorder(handler)
    with pytest.raises(EngineUnavailableError) as caught:
        translate(recorder.engine(max_retries=2), ["a"])
    assert len(recorder.requests) == 3
    assert API_KEY not in str(caught.value)


@pytest.mark.parametrize("status", [401, 403])
def test_auth_failure_is_never_retried(status: int) -> None:
    recorder = Recorder(lambda request: httpx.Response(status, text=f"bad key {API_KEY}"))
    with pytest.raises(EngineAuthenticationError) as caught:
        translate(recorder.engine(), ["a"])
    assert len(recorder.requests) == 1
    assert recorder.sleeps == []
    assert API_KEY not in str(caught.value)


def test_other_client_error_is_not_retried() -> None:
    recorder = Recorder(lambda request: httpx.Response(400, text="bad request"))
    with pytest.raises(EngineResponseError, match="400"):
        translate(recorder.engine(), ["a"])
    assert len(recorder.requests) == 1


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="<html>proxy error</html>"),
        httpx.Response(200, json={"choices": []}),
        httpx.Response(200, json={"choices": [{"text": "x"}]}),
    ],
)
def test_malformed_envelope_raises(response: httpx.Response) -> None:
    recorder = Recorder(lambda request: response)
    with pytest.raises(EngineResponseError):
        translate(recorder.engine(), ["a"])


def test_failure_in_one_chunk_fails_the_batch() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        texts = segments_of(request)
        return httpx.Response(400) if "boom" in texts else translations(texts)

    recorder = Recorder(handler)
    with pytest.raises(TranslationError):
        translate(recorder.engine(batch_size=1), ["a", "boom", "c", "d"])


def test_info_identifies_prompt_and_model() -> None:
    engine = Recorder(lambda request: httpx.Response(500)).engine()
    assert engine.info.model == "gemma"
    assert engine.info.details["prompt_version"] == PROMPT_VERSION
    assert API_KEY not in engine.info.model_dump_json()
