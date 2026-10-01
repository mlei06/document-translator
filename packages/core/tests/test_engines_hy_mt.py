import json
import threading
from typing import cast
from unittest.mock import patch

import httpx
import pytest
from pydantic import ValidationError

from doctranslator_core import LlmEngineConfig
from doctranslator_core.engines import create_engine, prepare_identity
from doctranslator_core.engines.hy_mt import HyMtEngine, user_prompt
from doctranslator_core.types import EngineAuthenticationError, EngineResponseError, Language


def config(**changes: object) -> LlmEngineConfig:
    return LlmEngineConfig.model_validate(
        {
            "base_url": "http://127.0.0.1:8099/v1/",
            "api_key": "test-key",
            "model": "hy-mt",
            "protocol": "hy-mt",
            "execution_location": "server",
            "deployment_revision": "gguf-sha256:runtime-and-settings-v1",
            "max_concurrency": 2,
        }
        | changes
    )


def test_plain_requests_are_concurrent_and_keep_order() -> None:
    barrier = threading.Barrier(2)
    bodies: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        bodies.append(body)
        barrier.wait(timeout=5)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": body["messages"][0]["content"].split("\n\n")[-1]},
                    }
                ]
            },
        )

    engine = HyMtEngine(config(), transport=httpx.MockTransport(handler))
    try:
        assert engine.translate_batch(["first", "second"], Language.EN, Language.ES) == [
            "first",
            "second",
        ]
    finally:
        engine.close()
    assert len(bodies) == 2
    for body in bodies:
        assert body["max_tokens"] == 2048
        assert "response_format" not in body
        messages = body["messages"]
        assert isinstance(messages, list)
        assert [message["role"] for message in cast(list[dict[str, object]], messages)] == ["user"]


@pytest.mark.parametrize("reason", ["length", "content_filter", None, "tool_calls"])
def test_rejects_incomplete_output(reason: str | None) -> None:
    engine = HyMtEngine(
        config(),
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={"choices": [{"finish_reason": reason, "message": {"content": "partial"}}]},
            )
        ),
    )
    try:
        with pytest.raises(EngineResponseError):
            engine.translate_batch(["source"], Language.EN, Language.ZH)
    finally:
        engine.close()


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"choices": []},
        {"choices": [None]},
        {"choices": [{"finish_reason": "stop", "message": {"content": " "}}]},
    ],
)
def test_rejects_malformed_output(payload: object) -> None:
    engine = HyMtEngine(
        config(), transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    )
    try:
        with pytest.raises(EngineResponseError):
            engine.translate_batch(["source"], Language.EN, Language.ZH)
    finally:
        engine.close()


def test_authentication_error_does_not_expose_upstream_body() -> None:
    engine = HyMtEngine(
        config(),
        transport=httpx.MockTransport(
            lambda _: httpx.Response(401, text="private upstream details")
        ),
    )
    try:
        with pytest.raises(EngineAuthenticationError, match="HTTP 401") as caught:
            engine.translate_batch(["source"], Language.EN, Language.ZH)
        assert "private" not in str(caught.value)
    finally:
        engine.close()


def test_prompt_language_and_markers() -> None:
    assert user_prompt("text", Language.ZH).startswith(
        "Translate the following text into Simplified Chinese."
    )
    assert user_prompt("text", Language.EN).startswith("Translate the following text into English.")
    assert user_prompt("text", Language.ES).startswith("Translate the following")
    assert "Preserve every" not in user_prompt("plain", Language.ES)
    assert "Preserve every" in user_prompt("<g1>text</g1><x2/>", Language.ES)


@pytest.mark.parametrize("source,target", [(Language.ZH, Language.EN), (Language.EN, Language.ES)])
def test_tagged_prompt_keeps_instructions_outside_translation_source(
    source: Language, target: Language
) -> None:
    text = "<g1>content</g1><x2/>\n\nsecond paragraph"
    prompt = user_prompt(text, target)
    instructions, submitted_source = prompt.split("\n\n", 1)
    assert submitted_source == text
    # The official translation delimiter must immediately precede the source, so
    # preserving tags cannot itself become part of the material to translate.
    plain_instruction = user_prompt("unused", target).split("\n\n", 1)[0]
    assert instructions.endswith(plain_instruction)
    assert instructions != plain_instruction
    assert "<g0>" not in instructions and "<x0/>" not in instructions


def test_configuration_factory_and_identity() -> None:
    original = config()
    assert LlmEngineConfig.model_validate(original.model_dump()) == original
    assert LlmEngineConfig.model_validate_json(original.model_dump_json()).protocol == "hy-mt"
    engine = create_engine(original)
    try:
        assert isinstance(engine, HyMtEngine)
        assert engine.identity == prepare_identity(original)
    finally:
        engine.close()
    for change in (
        {"max_output_tokens": 4096},
        {"temperature": 0.7},
        {"deployment_revision": "different-weights"},
        {"protocol": "json-batch"},
    ):
        assert prepare_identity(config(**change)) != prepare_identity(original)


@pytest.mark.parametrize(
    "changes",
    [
        {"deployment_revision": " "},
        {"base_url": "https://example.org/v1/"},
        {"max_output_tokens": 0},
        {"max_output_tokens": 32769},
    ],
)
def test_invalid_configuration(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        config(**changes)


@pytest.mark.parametrize("location", ["server", "remote"])
def test_local_endpoint_ignores_environment_proxies(location: str) -> None:
    with patch("doctranslator_core.engines.llm.httpx.Client") as client:
        engine = HyMtEngine(config(execution_location=location))
        try:
            assert client.call_args.kwargs["trust_env"] is (location != "server")
        finally:
            engine.close()


def test_managed_runtime_identity_is_stable_across_ephemeral_ports() -> None:
    pinned = config(managed_runtime_identity="a" * 64)
    relocated = pinned.model_copy(
        update={"base_url": config(base_url="http://127.0.0.1:55555/v1/").base_url}
    )
    assert prepare_identity(pinned) == prepare_identity(relocated)
    assert prepare_identity(pinned) != prepare_identity(config(managed_runtime_identity="b" * 64))
    assert prepare_identity(config()) != prepare_identity(
        config(base_url="http://127.0.0.1:55555/v1/")
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"managed_runtime_identity": "not-a-digest"},
        {"managed_runtime_identity": "a" * 64, "protocol": "json-batch"},
        {"managed_runtime_identity": "a" * 64, "execution_location": "remote"},
    ],
)
def test_managed_identity_is_restricted_to_verified_local_hy_mt(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        config(**changes)
