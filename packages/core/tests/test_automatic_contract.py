"""Automatic products use target-only inference and a pinned, bounded shared policy."""

import json
from pathlib import Path

import httpx
import pytest
from pydantic import HttpUrl, SecretStr, ValidationError
from support.fakes import FakeTranslator

import doctranslator_core
from doctranslator_core import DAVY_ORDER, AutomaticTranslationPolicy, LlmEngineConfig
from doctranslator_core.config import DocumentLimits
from doctranslator_core.engines.hy_mt import HyMtEngine
from doctranslator_core.engines.llm import LlmEngine
from doctranslator_core.pipeline import translate_document
from doctranslator_core.types import (
    DocumentDetection,
    DocumentTranslationOptions,
    EngineEndpointUnavailableError,
    EnginePolicyDeniedError,
    EngineResponseError,
    EngineUnavailableError,
    FitOptions,
    Language,
)


def test_default_policy_and_digest_pin_order_and_candidates() -> None:
    policy = AutomaticTranslationPolicy()
    assert policy.revision == "web-auto-v2"
    assert policy.candidates == (*DAVY_ORDER, "hy-mt-local")
    fingerprints = {candidate: f"immutable-{candidate}" for candidate in policy.candidates}
    original = policy.digest(fingerprints)
    assert policy.digest(dict(reversed(list(fingerprints.items())))) == original
    fingerprints["gemma"] = "new-deployment"
    assert policy.digest(fingerprints) != original
    reordered = AutomaticTranslationPolicy(davy_order=tuple(reversed(DAVY_ORDER)))
    assert reordered.digest(fingerprints) != policy.digest(fingerprints)


@pytest.mark.parametrize(
    "changes",
    [
        {"revision": " "},
        {"davy_order": ["gemma", "gemma"]},
        {"davy_order": [*DAVY_ORDER, "unapproved"]},
        {"local_translator_id": "small100"},
    ],
)
def test_policy_rejects_invalid_configuration(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        AutomaticTranslationPolicy.model_validate(changes)


@pytest.mark.parametrize("target", list(Language))
@pytest.mark.parametrize("protocol", ["hy-mt", "json-batch"])
def test_all_automatic_payloads_work_without_source(target: Language, protocol: str) -> None:
    requests: list[dict[str, object]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        content = "translated" if protocol == "hy-mt" else '{"translations":["translated"]}'
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": content},
                    }
                ]
            },
        )

    config = LlmEngineConfig.model_validate(
        {
            "base_url": "http://127.0.0.1:8099/v1/",
            "api_key": "secret",
            "model": "model",
            "protocol": protocol,
            "deployment_revision": "pinned",
        }
    )
    engine = (HyMtEngine if protocol == "hy-mt" else LlmEngine)(
        config,
        transport=httpx.MockTransport(respond),
    )
    try:
        assert engine.translate_batch(["mixed 你好"], target=target) == ["translated"]
        assert engine.translate_batch(["mixed 你好"], source=Language.ES, target=target) == [
            "translated"
        ]
        assert requests[0] == requests[1]
    finally:
        engine.close()


def test_transport_attempt_and_backoff_caps() -> None:
    attempts = 0
    delays: list[float] = []

    def overloaded(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(429, headers={"Retry-After": "999999"})

    engine = LlmEngine(
        LlmEngineConfig(
            base_url=HttpUrl("https://davy.example/v1"),
            api_key=SecretStr("key"),
            model="gemma",
            max_retries=99,
        ),
        transport=httpx.MockTransport(overloaded),
        sleep=delays.append,
    )
    try:
        with pytest.raises(EngineResponseError):
            engine.translate_batch(["text"], target=Language.EN)
    finally:
        engine.close()
    assert attempts == 3
    assert delays == [30, 30]


@pytest.mark.parametrize("kind", [httpx.ConnectError, httpx.ReadTimeout])
def test_endpoint_failure_is_distinct_from_model_timeout(kind: type[httpx.TransportError]) -> None:
    def unavailable(request: httpx.Request) -> httpx.Response:
        raise kind("unavailable", request=request)

    engine = LlmEngine(
        LlmEngineConfig.model_validate(
            {
                "base_url": "https://davy.example/v1",
                "api_key": "key",
                "model": "gemma",
                "max_retries": 0,
            }
        ),
        transport=httpx.MockTransport(unavailable),
    )
    try:
        with pytest.raises(EngineUnavailableError) as caught:
            engine.translate_batch(["text"], target=Language.EN)
        assert isinstance(caught.value, EngineEndpointUnavailableError) is (
            kind is httpx.ConnectError
        )
    finally:
        engine.close()


def test_hard_quota_denial_never_retries() -> None:
    delays: list[float] = []
    engine = LlmEngine(
        LlmEngineConfig(
            base_url=HttpUrl("https://davy.example/v1"), api_key=SecretStr("key"), model="gemma"
        ),
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                429,
                json={
                    "error": {
                        "code": "insufficient_quota",
                        "message": "sensitive upstream content",
                    },
                },
            )
        ),
        sleep=delays.append,
    )
    try:
        with pytest.raises(EnginePolicyDeniedError) as caught:
            engine.translate_batch(["text"], target=Language.EN)
    finally:
        engine.close()
    assert not delays
    assert "sensitive" not in str(caught.value)


@pytest.mark.parametrize(
    "reason,refusal", [("length", None), ("content_filter", None), ("stop", "no")]
)
def test_incomplete_or_refused_response_is_not_success(reason: str, refusal: str | None) -> None:
    engine = LlmEngine(
        LlmEngineConfig.model_validate(
            {
                "base_url": "https://davy.example/v1",
                "api_key": "key",
                "model": "gemma",
            }
        ),
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "finish_reason": reason,
                            "message": {"content": '{"translations":["text"]}', "refusal": refusal},
                        }
                    ]
                },
            )
        ),
    )
    try:
        with pytest.raises(EngineResponseError):
            engine.translate_batch(["text"], target=Language.EN)
    finally:
        engine.close()


def test_detector_failure_still_translates_all_scripts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable(_: object) -> object:
        raise RuntimeError("detector unavailable")

    monkeypatch.setattr("doctranslator_core.pipeline.detect_source", unavailable)
    source = tmp_path / "mixed.txt"
    source.write_text("English text\n中文文字\n日本語です", encoding="utf-8")
    translator = FakeTranslator()
    result = translate_document(
        translator,
        source,
        tmp_path / "out.txt",
        options=DocumentTranslationOptions(target=Language.EN),
        fingerprint="pinned",
        limits=DocumentLimits(),
    )
    assert len(translator.inputs) == 3
    assert result.source_resolved is None
    assert result.output_path.is_file()


def test_removed_rendering_has_no_public_entrypoints() -> None:
    assert not hasattr(doctranslator_core, "render_pages")
    assert not hasattr(doctranslator_core, "office_renderer")
    assert not hasattr(doctranslator_core, "RenderConfig")
    with pytest.raises(ValidationError):
        FitOptions.model_validate({"mode": "thorough"})


def test_mixed_and_unsupported_script_metadata(tmp_path: Path) -> None:
    from doctranslator_core import detect_document

    mixed = tmp_path / "mixed.txt"
    mixed.write_text(
        "中文内容需要翻译到目标语言这是完整的中文句子。\n"
        "The document contains English content too.",
        encoding="utf-8",
    )
    assert detect_document(mixed).status == "mixed"
    unknown = tmp_path / "unknown.txt"
    unknown.write_text("Привет мир", encoding="utf-8")
    assert detect_document(unknown).status == "unknown"


@pytest.mark.parametrize("source", [None, Language.EN])
def test_ingestion_metadata_prevents_redetection_without_controlling_inference(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source: Language | None,
) -> None:
    def forbidden(_: object) -> object:
        raise AssertionError("ingestion metadata must prevent another detector call")

    calls: list[object] = []

    def detect_again(value: object) -> object:
        calls.append(value)
        return forbidden(value)

    monkeypatch.setattr("doctranslator_core.pipeline.detect_source", detect_again)
    original = tmp_path / "source.txt"
    original.write_text("Already English\n中文也需要翻译", encoding="utf-8")
    translator = FakeTranslator()
    result = translate_document(
        translator,
        original,
        tmp_path / "translated.txt",
        options=DocumentTranslationOptions(target=Language.EN),
        fingerprint="pinned",
        limits=DocumentLimits(),
        detection_metadata=DocumentDetection.model_validate(
            {
                "format": "txt",
                "source": source,
                "status": "unknown" if source is None else "detected",
            }
        ),
    )
    assert not calls
    assert result.source_resolved == source
    assert len(translator.inputs) == 2
