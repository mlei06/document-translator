"""Configured selection, safe discovery and pinned identity without model downloads."""

import hashlib
import io
import json
import uuid
from pathlib import Path
from unittest.mock import Mock

import pytest
from pydantic import ValidationError
from support.server import add_user, server_settings

from doctranslator_core.types import (
    DocumentTranslationOptions,
    FontManifest,
    Language,
    TranslationIdentity,
    TranslationMode,
)
from doctranslator_server.app import build_services, migrate
from doctranslator_server.db.models import Job
from doctranslator_server.jobs.engines import EngineCatalog, resolve_translator
from doctranslator_server.jobs.errors import InvalidRequestError
from doctranslator_server.jobs.service import SubmitOptions
from doctranslator_server.settings import ServerSettings


def test_local_hy_mt_is_independent_of_davy(tmp_path: Path) -> None:
    settings = server_settings(
        tmp_path,
        translators=[
            {
                "id": "hy-local",
                "label": "HY-MT on this server",
                "engine": {
                    "mode": "llm",
                    "base_url": "http://127.0.0.1:8099/v1/",
                    "api_key": "PRIVATE",
                    "model": "hy-mt",
                    "protocol": "hy-mt",
                    "execution_location": "server",
                    "deployment_revision": "pinned-gguf",
                },
            }
        ],
        default_translator_id="hy-local",
    )
    catalog = EngineCatalog(settings, FontManifest(faces=()))
    try:
        entries = catalog.translators
        assert len(entries) == 1
        assert entries[0].id == "hy-local"
        assert entries[0].location == "server"
        assert entries[0].mode == TranslationMode.LLM
        assert "PRIVATE" not in repr(entries)
        assert "127.0.0.1" not in repr(entries)
        # Verify the internal MT cache stays empty for an HTTP-backed local engine.
        assert not catalog._local_groups  # pyright: ignore[reportPrivateUsage]
    finally:
        catalog.close()


def configuration(tmp_path: Path) -> ServerSettings:
    return server_settings(
        tmp_path,
        translators=[
            {
                "id": "first",
                "label": "First",
                "engine": {
                    "mode": "llm",
                    "base_url": "https://private.example/v1",
                    "api_key": "SECRET",
                    "model": "a",
                },
            },
            {
                "id": "second",
                "label": "Second",
                "engine": {
                    "mode": "llm",
                    "base_url": "https://private.example/v1",
                    "api_key": "SECRET",
                    "model": "b",
                },
            },
            {
                "id": "disabled",
                "label": "Disabled",
                "enabled": False,
                "engine": {
                    "mode": "llm",
                    "base_url": "https://private.example/v1",
                    "api_key": "SECRET",
                    "model": "c",
                },
            },
        ],
        default_translator_id="second",
    )


def test_selection_and_safe_discovery(tmp_path: Path) -> None:
    settings = configuration(tmp_path)
    migrate(settings)
    services = build_services(settings)
    try:
        owner, _ = add_user(services)
        key = str(uuid.uuid4())
        request = SubmitOptions(target="zh", source="en", retention="temporary")
        result = services.jobs.submit(
            owner,
            "notes.txt",
            io.BytesIO(b"This document has enough English text for translation."),
            request,
            submission_id=key,
        )
        assert result.job is not None and result.job.translator_id == "second"
        changed = settings.model_copy(update={"translators": [], "default_translator_id": None})
        restarted = build_services(changed)
        try:
            replay = restarted.jobs.submit(
                owner,
                "notes.txt",
                io.BytesIO(b"This document has enough English text for translation."),
                request,
                submission_id=key,
            )
            assert replay.replayed and replay.job is not None and replay.job.id == result.job.id
        finally:
            restarted.close()
        # A pre-0003 accepted request hashes resolved mode, without a translator ID.
        payload = {
            "input": hashlib.sha256(
                b"This document has enough English text for translation."
            ).hexdigest(),
            "document": None,
            "mode": "llm",
            "options": DocumentTranslationOptions(
                target=Language.ZH, source=Language.EN
            ).model_dump(mode="json", exclude={"use_default_dictionary"}),
            "force": False,
            "retention": "temporary",
        }
        with services.db.session() as session:
            old_job = session.get(Job, result.job.id)
            assert old_job is not None
            old_job.translator_id = None
            old_job.request_hash = hashlib.sha256(
                json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
        legacy = services.jobs.submit(
            owner,
            "notes.txt",
            io.BytesIO(b"This document has enough English text for translation."),
            request,
            submission_id=key,
        )
        assert legacy.replayed and legacy.job is not None and legacy.job.id == result.job.id
        capabilities = services.jobs.capabilities()
        assert capabilities["default_translator_id"] == "second"
        assert [item["id"] for item in capabilities["translators"]] == ["first", "second"]
        assert "SECRET" not in str(capabilities) and "private.example" not in str(capabilities)
        options = DocumentTranslationOptions(target=Language.ZH, source=Language.EN)
        catalog = EngineCatalog(settings, FontManifest(faces=()))
        assert catalog.fingerprint("first", options) != catalog.fingerprint("second", options)
        assert resolve_translator(catalog.translators, "second", None, "llm").id == "second"
        for identifier, mode in [("disabled", None), ("unknown", None), ("first", "mt")]:
            with pytest.raises(InvalidRequestError):
                resolve_translator(catalog.translators, "second", identifier, mode)
    finally:
        services.close()


def test_invalid_defaults_and_duplicate_ids(tmp_path: Path) -> None:
    settings = configuration(tmp_path)
    values = settings.model_dump()
    for default in [None, "disabled", "missing"]:
        with pytest.raises(ValidationError):
            ServerSettings.model_validate(values | {"default_translator_id": default})
    with pytest.raises(ValidationError):
        ServerSettings.model_validate(values | {"translators": [values["translators"][0]] * 2})


def test_local_runtime_eviction(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from doctranslator_server.jobs import engines

    settings = server_settings(
        tmp_path,
        translators=[
            {
                "id": key,
                "label": key,
                "engine": {
                    "mode": "mt",
                    "model_dir": str(tmp_path / key),
                    "model_family": "small100",
                },
            }
            for key in ["one", "two"]
        ],
        default_translator_id="one",
    )
    monkeypatch.setattr(
        engines,
        "prepare_identity",
        Mock(
            return_value=TranslationIdentity(
                mode=TranslationMode.MT,
                model="fake",
                details={"artifact_sha256": "fake", "device": "cpu"},
            )
        ),
    )
    runtimes = [Mock(), Mock(), Mock()]
    create = Mock(side_effect=runtimes)
    monkeypatch.setattr(engines, "Translator", create)
    catalog = EngineCatalog(settings, FontManifest(faces=()))
    assert create.call_count == 0
    first = catalog.translator("one")
    assert catalog.translator("one") is first
    catalog.translator("two")
    runtimes[0].close.assert_called_once()
    catalog.translator("one")
    assert create.call_count == 3
    catalog.close()


def test_rejected_saved_batch_item_replays(tmp_path: Path) -> None:
    from doctranslator_server.jobs.errors import DocumentRejectedError

    settings = configuration(tmp_path)
    migrate(settings)
    services = build_services(settings)
    try:
        owner, _ = add_user(services)
        batch, _ = services.jobs.create_batch(owner, str(uuid.uuid4()), "Malformed input")
        item_id = str(uuid.uuid4())
        errors: list[str] = []
        for _ in range(2):
            with pytest.raises(DocumentRejectedError) as caught:
                services.jobs.submit(
                    owner,
                    "broken.pptx",
                    io.BytesIO(b"not an office package"),
                    SubmitOptions(target="zh", source="en"),
                    batch_id=batch.id,
                    client_item_id=item_id,
                )
            errors.append(caught.value.code)
        assert errors[0] == errors[1]
        assert services.jobs.get_batch(owner, batch.id).items == 1
    finally:
        services.close()
