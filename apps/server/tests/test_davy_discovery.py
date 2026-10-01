"""Davy discovery only lists approved models; availability never changes pinned work."""

import io
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from support.server import add_user, server_settings

from doctranslator_core.types import DocumentTranslationOptions, FontManifest, Language
from doctranslator_server.app import build_services, create_app, migrate
from doctranslator_server.jobs.davy import DavyDiscovery, DavyState
from doctranslator_server.jobs.engines import EngineCatalog, resolve_translator
from doctranslator_server.jobs.errors import InvalidRequestError
from doctranslator_server.jobs.service import SubmitOptions
from doctranslator_server.settings import ServerSettings


def settings(tmp_path: Path) -> ServerSettings:
    return server_settings(
        tmp_path,
        davy_base_url="https://private.example/v1",
        davy_api_key="SECRET",
        davy_models=[
            {"id": "gemma", "label": "Gemma", "model": "gemma-upstream"},
            {"id": "other", "label": "Other", "model": "other-upstream"},
        ],
        default_translator_id="gemma",
    )


def test_discovery_get_only_singleflight_cache_and_forced_floor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = [100.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.method == "GET" and str(request.url) == "https://private.example/v1/models"
        assert request.headers["authorization"] == "Bearer SECRET"
        return httpx.Response(200, json={"data": [{"id": "gemma-upstream"}, {"id": "unapproved"}]})

    discovery = DavyDiscovery(settings(tmp_path), transport=httpx.MockTransport(handler))

    def snapshot(_: int) -> tuple[DavyState, frozenset[str]]:
        return discovery.snapshot()

    with ThreadPoolExecutor(max_workers=8) as pool:
        states = list(pool.map(snapshot, range(8)))
    assert all(state.status == "available" for state, _ in states)
    assert len(calls) == 1
    discovery.snapshot(force=True)
    assert len(calls) == 1
    clock[0] += 5
    discovery.snapshot(force=True)
    assert len(calls) == 2
    clock[0] += 59
    discovery.snapshot()
    assert len(calls) == 2
    clock[0] += 1
    discovery.snapshot()
    assert len(calls) == 3


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (httpx.Response(401), "authentication_failed"),
        (httpx.Response(403), "authentication_failed"),
        (httpx.Response(503), "unreachable"),
        (httpx.Response(302), "error"),
        (httpx.Response(200, json={"data": []}), "no_models"),
        (httpx.Response(200, json={"data": [{"id": "not-approved"}]}), "no_models"),
        (httpx.Response(200, json={"data": [{"id": 123}]}), "error"),
        (httpx.Response(200, json={"data": "wrong"}), "error"),
        (httpx.Response(200, text="SECRET private.example"), "error"),
    ],
)
def test_failure_states_are_safe(tmp_path: Path, response: httpx.Response, expected: str) -> None:
    discovery = DavyDiscovery(settings(tmp_path), transport=httpx.MockTransport(lambda _: response))
    state, models = discovery.snapshot()
    assert state.status == expected and not models
    assert "SECRET" not in str(state) and "private.example" not in str(state)
    assert state.checked_at is not None


def test_timeout_and_missing_credentials(tmp_path: Path) -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        assert request.extensions["timeout"]["read"] == 5.0
        raise httpx.ReadTimeout("SECRET private.example", request=request)

    transport = httpx.MockTransport(timeout)
    assert (
        DavyDiscovery(settings(tmp_path), transport=transport).snapshot()[0].status == "unreachable"
    )
    for changes in ({"davy_api_key": None}, {"davy_base_url": None}):
        config = settings(tmp_path).model_copy(update=changes)
        state, models = DavyDiscovery(config, transport=transport).snapshot()
        assert state.status == "not_configured" and state.checked_at is None and not models
        assert EngineCatalog(config, FontManifest(faces=())).default_translator_id == "gemma"


def test_catalog_filters_admission_but_keeps_pinned_identity_and_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = settings(tmp_path)
    catalog = EngineCatalog(config, FontManifest(faces=()))
    response = [
        httpx.Response(200, json={"data": [{"id": "gemma-upstream"}, {"id": "unapproved"}]})
    ]
    discovery = DavyDiscovery(config, transport=httpx.MockTransport(lambda _: response[0]))
    monkeypatch.setattr(catalog, "_davy", discovery)
    assert [entry.id for entry in catalog.translators] == ["gemma"]
    migrate(config)
    services = build_services(config, catalog=catalog)
    try:
        owner, headers = add_user(services)
        options = SubmitOptions(source="en", target="zh", retention="temporary")
        key = str(uuid.uuid4())
        content = b"This document has enough English text for translation."
        accepted = services.jobs.submit(
            owner, "test.txt", io.BytesIO(content), options, submission_id=key
        )
        response[0] = httpx.Response(503)
        monkeypatch.setattr(discovery, "_checked", float("-inf"))
        caps = services.jobs.capabilities()
        assert caps["translators"] == [] and caps["davy"]["status"] == "unreachable"
        assert caps["default_translator_id"] == "gemma"
        identity = catalog.fingerprint(
            "gemma", DocumentTranslationOptions(source=Language.EN, target=Language.ZH)
        )
        assert identity
        with pytest.raises(InvalidRequestError, match="unavailable"):
            services.jobs.submit(
                owner, "test.txt", io.BytesIO(content), options, submission_id=str(uuid.uuid4())
            )
        replay = services.jobs.submit(
            owner, "test.txt", io.BytesIO(content), options, submission_id=key
        )
        assert replay.replayed and replay.job and accepted.job and replay.job.id == accepted.job.id
        client = TestClient(create_app(services))
        assert client.post("/v1/translators/refresh").status_code == 401
        assert (
            client.post("/v1/translators/refresh", headers=headers).json()["davy"]["status"]
            == "unreachable"
        )
        login = client.post(
            "/v1/sessions", json={"key": headers["Authorization"].removeprefix("Bearer ")}
        )
        assert login.status_code == 201
        assert client.post("/v1/translators/refresh").status_code == 403
        assert (
            client.post(
                "/v1/translators/refresh", headers={"X-CSRF-Token": login.json()["csrf_token"]}
            ).status_code
            == 200
        )
    finally:
        services.close()


@pytest.mark.parametrize(
    "missing_file",
    ["model.bin", "sentencepiece.bpe.model", "config.json", "shared_vocabulary.json"],
)
def test_mt_installation_eligibility_and_unavailable_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, missing_file: str
) -> None:
    present = tmp_path / "present"
    present.mkdir()
    (present / "model.bin").write_bytes(b"weights")
    (present / "sentencepiece.bpe.model").write_bytes(b"tokenizer")
    (present / "config.json").write_text("{}")
    (present / "shared_vocabulary.json").write_text('["token"]')
    missing = tmp_path / "missing"
    partial = tmp_path / "partial"
    partial.mkdir()
    for filename in (
        "model.bin",
        "sentencepiece.bpe.model",
        "config.json",
        "shared_vocabulary.json",
    ):
        if filename != missing_file:
            (partial / filename).write_bytes(b"fixture")
    entries = [
        {
            "id": path.name,
            "label": path.name,
            "engine": {
                "mode": "mt",
                "model_dir": str(path),
                "model_family": "small100",
                "device": "cpu",
            },
        }
        for path in (present, missing, partial)
    ]
    config = settings(tmp_path).model_copy(update={"translators": []})
    config = ServerSettings.model_validate(config.model_dump() | {"translators": entries})
    catalog = EngineCatalog(config, FontManifest(faces=()))
    monkeypatch.setattr(
        catalog,
        "_davy",
        DavyDiscovery(config, transport=httpx.MockTransport(lambda _: httpx.Response(503))),
    )
    assert [entry.id for entry in catalog.translators] == ["present"]
    with pytest.raises(InvalidRequestError, match="unavailable"):
        resolve_translator(catalog.translators, "gemma", None, None)
    assert resolve_translator(catalog.translators, "gemma", "present", None).id == "present"
    with pytest.raises(InvalidRequestError):
        catalog.translator("missing")
    assert catalog.default_translator_id == "gemma"


def test_duplicate_ids_across_catalogs_rejected(tmp_path: Path) -> None:
    config = settings(tmp_path).model_dump()
    config["davy_models"] *= 2
    with pytest.raises(ValidationError):
        ServerSettings.model_validate(config)
