"""Native profile contracts, bounded scheduling and cache safety."""

import json
import threading
from concurrent.futures import ALL_COMPLETED, ThreadPoolExecutor, wait
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from doctranslator_core import LlmEngineConfig
from doctranslator_core.engines import llm
from doctranslator_core.engines.llm import LlmEngine, prepare_identity
from doctranslator_core.engines.llm_prompts import PROMPT_VERSION
from doctranslator_core.engines.translation_prompts import translategemma_prompt
from doctranslator_core.types import EngineResponseError, Language


def config(**overrides: object) -> LlmEngineConfig:
    return LlmEngineConfig.model_validate(
        {
            "base_url": "https://llm.example/v1",
            "api_key": "secret-token",
            "model": "native-model",
            "translation_profile": "hy-mt2",
            "deployment_revision": "weights-template-runtime-revision",
        }
        | overrides
    )


def completion(content: object = "Hello", **choice: object) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
                | choice
            ]
        },
    )


def test_native_request_contract() -> None:
    profile = "hy-mt2"
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return completion()

    engine = LlmEngine(config(translation_profile=profile), transport=httpx.MockTransport(handle))
    try:
        assert engine.translate_batch(["你好"], Language.ZH, Language.EN) == ["Hello"]
        body = json.loads(requests[0].content)
        assert body == {
            "model": "native-model",
            "temperature": 0.0,
            "max_tokens": 2048,
            "top_p": 1.0,
            "top_k": 0,
            "repetition_penalty": 1.0,
            "seed": 0,
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "Translate the following text into English. Note that you should only "
                        "output the translated result without any additional explanation:\n你好"
                    ),
                }
            ],
        }
        assert requests[0].headers["Authorization"] == "Bearer secret-token"
        assert engine.info.details["translation_profile"] == profile
        assert "secret-token" not in engine.info.model_dump_json()
        assert "secret-token" not in engine.identity.model_dump_json()
    finally:
        engine.close()


def test_translategemma_raw_prompt_and_retry_contract() -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"choices": [{"text": "Hello", "finish_reason": "stop"}]})

    engine = LlmEngine(
        config(translation_profile="translategemma"),
        transport=httpx.MockTransport(handle),
        sleep=lambda _: None,
    )
    try:
        assert engine.translate_batch([" 你好 \n"], Language.ZH, Language.EN) == ["Hello"]
        assert len(requests) == 2
        assert all(str(request.url) == "https://llm.example/v1/completions" for request in requests)
        body = json.loads(requests[-1].content)
        assert "messages" not in body
        assert "response_format" not in body
        assert body["stop"] == ["<end_of_turn>", "<eos>"]
        assert body["prompt"] == (
            "<bos><start_of_turn>user\nYou are a professional Chinese (zh) to English (en) "
            "translator. Your goal is to accurately convey the meaning and nuances of the "
            "original Chinese text while adhering to English grammar, vocabulary, and cultural "
            "sensitivities.\nProduce only the English translation, without any additional "
            "explanations or commentary. Please translate the following Chinese text into "
            "English:\n\n\n你好<end_of_turn>\n<start_of_turn>model\n"
        )
    finally:
        engine.close()


@pytest.mark.parametrize(
    "language,name",
    [
        (Language.ZH, "Chinese"),
        (Language.EN, "English"),
        (Language.JA, "Japanese"),
        (Language.ES, "Spanish"),
    ],
)
def test_translategemma_official_language_names(language: Language, name: str) -> None:
    assert f"{name} ({language.value}) to English (en)" in translategemma_prompt(
        "source", language, Language.EN
    )
    assert f"Chinese (zh) to {name} ({language.value})" in translategemma_prompt(
        "source", Language.ZH, language
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"choices": [{"text": "partial", "finish_reason": "length"}]},
        {"choices": [{"text": "partial"}]},
        {"choices": [{"text": "", "finish_reason": "stop"}]},
        {"choices": [{"text": ["x"], "finish_reason": "stop"}]},
        {"choices": [{"text": "no", "finish_reason": "stop", "refusal": "secret-token"}]},
        {"choices": [{"message": {"content": "wrong endpoint"}, "finish_reason": "stop"}]},
        {"choices": []},
        {"choices": [None]},
        None,
    ],
)
def test_raw_completion_rejects_partial_or_malformed_outputs(payload: object) -> None:
    engine = LlmEngine(
        config(translation_profile="translategemma"),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload)),
    )
    try:
        with pytest.raises(EngineResponseError) as caught:
            engine.translate_batch(["source"], Language.ZH, Language.EN)
        assert "secret-token" not in str(caught.value)
    finally:
        engine.close()


@pytest.mark.parametrize(
    "response",
    [
        completion("partial", finish_reason="length"),
        completion("partial", finish_reason=None),
        completion("", finish_reason="stop"),
        completion("  \n"),
        completion([{"type": "text", "text": "x"}]),
        completion(message={"content": "no", "refusal": "secret-token"}),
        completion(message={"content": "no", "tool_calls": [{"id": "x"}]}),
        httpx.Response(200, json={"choices": [{"message": {"content": "x"}}]}),
        httpx.Response(200, json={"choices": []}),
        httpx.Response(200, text="secret-token"),
    ],
)
def test_unusable_native_response_fails_without_leaking_content(response: httpx.Response) -> None:
    engine = LlmEngine(config(), transport=httpx.MockTransport(lambda request: response))
    try:
        with pytest.raises(EngineResponseError) as caught:
            engine.translate_batch(["secret source"], Language.ZH, Language.EN)
        assert "secret-token" not in str(caught.value)
        assert "secret source" not in str(caught.value)
    finally:
        engine.close()


def test_native_requests_reuse_retries() -> None:
    responses = iter([httpx.Response(429, headers={"Retry-After": "2"}), completion()])
    sleeps: list[float] = []
    engine = LlmEngine(
        config(),
        transport=httpx.MockTransport(lambda request: next(responses)),
        sleep=sleeps.append,
    )
    try:
        assert engine.translate_batch(["你好"], Language.ZH, Language.EN) == ["Hello"]
        assert sleeps == [2.0]
    finally:
        engine.close()


@pytest.mark.parametrize("profile", ["hy-mt2", "translategemma"])
@pytest.mark.parametrize("backend", ["openai", "llamacpp"])
def test_backend_decoding_wire_contract(profile: str, backend: str) -> None:
    bodies: list[dict[str, object]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return (
            completion()
            if profile == "hy-mt2"
            else httpx.Response(200, json={"choices": [{"text": "Hello", "finish_reason": "stop"}]})
        )

    engine = LlmEngine(
        config(translation_profile=profile, server_backend=backend, repetition_penalty=1.05),
        transport=httpx.MockTransport(handle),
    )
    try:
        assert engine.translate_batch(["你好"], Language.ZH, Language.EN) == ["Hello"]
        assert engine.identity.details["server_backend"] == backend
        if profile == "translategemma":
            expected_prompt = translategemma_prompt("你好", Language.ZH, Language.EN)
            if backend == "llamacpp":
                expected_prompt = expected_prompt.removeprefix("<bos>")
            assert bodies[0]["prompt"] == expected_prompt
        if backend == "llamacpp":
            assert bodies[0]["repeat_penalty"] == 1.05
            assert bodies[0]["min_p"] == 0.0
            assert "repetition_penalty" not in bodies[0]
            assert engine.identity.details["min_p"] == "0.0"
        else:
            assert bodies[0]["repetition_penalty"] == 1.05
            assert "repeat_penalty" not in bodies[0]
            assert "min_p" not in bodies[0]
            assert "min_p" not in engine.identity.details
    finally:
        engine.close()


def test_scheduling_bounds_submissions_and_preserves_order(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hold both first requests: no other document segments may be queued yet."""
    original_submit = ThreadPoolExecutor.submit
    submitted = 0
    two_started = threading.Barrier(3)
    release = threading.Event()

    def submit(self: ThreadPoolExecutor, *args: Any, **kwargs: Any) -> Any:
        nonlocal submitted
        submitted += 1
        return original_submit(self, *args, **kwargs)

    monkeypatch.setattr(ThreadPoolExecutor, "submit", submit)

    def handle(request: httpx.Request) -> httpx.Response:
        text = json.loads(request.content)["messages"][0]["content"].split("\n", 1)[1]
        if text in ("0", "1"):
            two_started.wait(timeout=5)
            assert release.wait(timeout=5)
        return completion(f"T{text}")

    engine = LlmEngine(config(max_concurrency=2), transport=httpx.MockTransport(handle))
    result: list[str] = []
    failures: list[Exception] = []

    def run() -> None:
        try:
            result.extend(
                engine.translate_batch([str(i) for i in range(50)], Language.ZH, Language.EN)
            )
        except Exception as exc:
            failures.append(exc)

    thread = threading.Thread(target=run)
    thread.start()
    try:
        two_started.wait(timeout=5)
        assert submitted == 2
    finally:
        release.set()
        thread.join(timeout=10)
        engine.close()
    assert not thread.is_alive()
    assert not failures
    assert result == [f"T{i}" for i in range(50)]


def test_failed_native_wave_prevents_replacements_and_returns_no_partial_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Force one successful and one failed request into the same completed wave.
    # Processing the success must not refill the queue before inspecting the failure.
    def complete_wave(futures: Any, *, return_when: str) -> Any:
        return wait(futures, return_when=ALL_COMPLETED)

    monkeypatch.setattr(llm, "wait", complete_wave)
    requests: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        text = json.loads(request.content)["messages"][0]["content"].split("\n", 1)[1]
        requests.append(text)
        return httpx.Response(400) if text == "bad" else completion("translated")

    engine = LlmEngine(config(max_concurrency=2), transport=httpx.MockTransport(handle))
    try:
        with pytest.raises(EngineResponseError, match="400"):
            engine.translate_batch(["ok", "bad", "never", "queued"], Language.ZH, Language.EN)
        assert sorted(requests) == ["bad", "ok"]
    finally:
        engine.close()


def test_native_identity_records_effective_behavior_and_decoding() -> None:
    base = config()
    identity = prepare_identity(base)
    assert identity.details["batch_size"] == "1"
    assert identity.details["json_mode"] == "false"
    assert prepare_identity(config(batch_size=99, json_mode=False)) == identity
    for field, value in {
        "translation_profile": "translategemma",
        "deployment_revision": "changed",
        "temperature": 0.7,
        "max_output_tokens": 1024,
        "top_p": 0.6,
        "top_k": 20,
        "repetition_penalty": 1.05,
        "seed": 7,
        "server_backend": "llamacpp",
        "max_concurrency": 8,
    }.items():
        assert prepare_identity(config(**{field: value})) != identity


def test_generic_identity_and_requests_remain_compatible() -> None:
    generic = config(translation_profile="generic", deployment_revision="")
    assert prepare_identity(generic).details == {
        "base_url": "https://llm.example/v1",
        "deployment_revision": "",
        "prompt_version": PROMPT_VERSION,
        "temperature": "0.0",
        "json_mode": "true",
        "batch_size": "16",
    }
    assert prepare_identity(generic) == prepare_identity(
        generic.model_copy(
            update={
                "max_output_tokens": 3,
                "top_k": 8,
                "top_p": 0.1,
                "seed": 3,
                "repetition_penalty": 1.2,
                "server_backend": "llamacpp",
                "max_concurrency": 8,
            }
        )
    )


@pytest.mark.parametrize("revision", ["", " \n"])
def test_native_profiles_require_revision(revision: str) -> None:
    with pytest.raises(ValidationError, match="require deployment_revision"):
        config(deployment_revision=revision)


@pytest.mark.parametrize(
    "overrides",
    [
        {"max_output_tokens": 0},
        {"top_p": 0},
        {"top_p": 1.1},
        {"top_k": -1},
        {"repetition_penalty": 0},
        {"seed": -1},
        {"translation_profile": "unknown"},
    ],
)
def test_profile_settings_are_validated(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        config(**overrides)
