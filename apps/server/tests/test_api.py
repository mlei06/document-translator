"""REST contract (/v1) under ADR-014/ADR-017: authentication, saved documents and reuse,
temporary jobs, ownership, batches, sessions, previews and the job controls."""

import hashlib
import json
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from support.fakes import FIXTURES
from support.pdf import write_mixed
from support.server import FakeEngines, add_user, make_services, make_worker, server_settings

from doctranslator_server import auth
from doctranslator_server.app import Services, create_app

TXT = "这是一个用于测试的中文段落，内容足够长以便识别语言。\n".encode()


@pytest.fixture
def engines() -> FakeEngines:
    return FakeEngines()


@pytest.fixture
def services(tmp_path: Path, engines: FakeEngines) -> Iterator[Services]:
    services = make_services(server_settings(tmp_path), engines)
    yield services
    services.close()


@pytest.fixture
def client(services: Services) -> TestClient:
    return TestClient(create_app(services))


def options(**values: Any) -> str:
    return json.dumps({"target": "en", "mode": "mt"} | values)


def submit(
    client: TestClient,
    headers: dict[str, str],
    content: bytes = TXT,
    name: str = "notes.txt",
    submission_id: str | None = None,
    **opts: Any,
) -> Any:
    return client.post(
        "/v1/jobs",
        headers=headers,
        files={"file": (name, content)},
        data={"options": options(**opts), "submission_id": submission_id or str(uuid.uuid4())},
    )


def run_all(services: Services, engines: FakeEngines) -> None:
    worker = make_worker(services, engines)
    while worker.run_once():
        pass


def job(client: TestClient, headers: dict[str, str], job_id: str) -> dict[str, Any]:
    return client.get(f"/v1/jobs/{job_id}", headers=headers).json()


def test_every_route_requires_a_valid_key(client: TestClient, services: Services) -> None:
    assert client.get("/v1/health").status_code == 200
    for headers in ({}, {"Authorization": "Bearer nope"}, {"Authorization": "Basic x"}):
        response = client.get("/v1/me", headers=headers)
        assert response.status_code == 401
        assert response.json()["code"] == "unauthenticated"
    user_id, headers = add_user(services)
    me = client.get("/v1/me", headers=headers).json()
    assert me["id"] == user_id and me["kind"] == "human"
    assert me["storage_used_bytes"] == 0 and me["storage_quota_bytes"] == 20 << 30


def test_capabilities_list_formats_modes_retention_and_limits(
    client: TestClient, services: Services
) -> None:
    _, headers = add_user(services)
    caps = client.get("/v1/capabilities", headers=headers).json()
    assert caps["formats"] == ["docx", "pdf", "pptx", "txt", "xlsx"]
    assert caps["modes"] == ["mt", "llm"]
    assert caps["retention"] == ["saved", "temporary"]
    assert "skipped" in caps["fit_statuses"]
    assert caps["limits"]["temporary_retention_hours"] == 24


def test_saved_submit_translate_and_download(
    client: TestClient, services: Services, engines: FakeEngines
) -> None:
    _, headers = add_user(services)
    response = submit(client, headers)
    assert response.status_code == 202
    queued = response.json()
    assert queued["status"] == "queued" and queued["retention"] == "saved"
    assert queued["document_id"] and queued["result_available"] is False
    run_all(services, engines)
    done = job(client, headers, queued["id"])
    assert done["status"] == "succeeded" and done["result_available"] is True
    assert done["source_resolved"] == "zh" and done["fit_status"] == "not_applicable"
    assert done["result_expires_at"] is None  # current translation: no expiry
    file = client.get(f"/v1/jobs/{done['id']}/file", headers=headers)
    assert file.status_code == 200 and file.content.decode("utf-8").startswith("EN:")
    assert hashlib.sha256(file.content).hexdigest() == file.headers["x-content-sha256"]
    assert 'filename="notes.en.txt"' in file.headers["content-disposition"]
    report = client.get(f"/v1/jobs/{done['id']}/fit-report", headers=headers).json()
    assert report["fit_report"]["status"] == "not_applicable"
    document = client.get(f"/v1/documents/{done['document_id']}", headers=headers).json()
    assert document["detected_source"] == "zh" and document["format"] == "txt"
    [translation] = document["translations"]
    assert (translation["source"], translation["target"]) == ("zh", "en")
    assert translation["job_id"] == done["id"]
    current = client.get(
        f"/v1/documents/{document['id']}/translations/{translation['id']}/file", headers=headers
    )
    assert current.content == file.content
    original = client.get(f"/v1/documents/{document['id']}/original", headers=headers)
    assert original.content == TXT


def test_documents_are_owner_scoped_and_deduplicated(
    client: TestClient, services: Services
) -> None:
    _, alice = add_user(services, "Alice")
    _, bob = add_user(services, "Bob")

    def upload(headers: dict[str, str], **form: Any) -> Any:
        return client.post(
            "/v1/documents", headers=headers, files={"file": ("a.txt", TXT)}, data=form
        )

    first = upload(alice)
    assert first.status_code == 201
    doc = first.json()
    assert doc["detection"] == "detected" and doc["detected_source"] == "zh"
    again = upload(alice)
    assert again.status_code == 200 and again.json()["id"] == doc["id"]
    attachment = upload(alice, new_document="true", external_ref="case-17")
    assert attachment.status_code == 201 and attachment.json()["id"] != doc["id"]
    assert attachment.json()["external_ref"] == "case-17"
    bobs = upload(bob)
    assert bobs.status_code == 201 and bobs.json()["id"] != doc["id"]
    assert client.get(f"/v1/documents/{doc['id']}", headers=bob).status_code == 404
    listed = client.get("/v1/documents", headers=alice, params={"q": "A.TX"}).json()["items"]
    assert len(listed) == 2
    scan = client.post("/v1/documents", headers=alice, files={"file": ("scan.png", b"\x89PNG")})
    assert scan.status_code == 415


def test_reuse_is_owner_scoped_and_force_replaces_the_current_result(
    client: TestClient, services: Services, engines: FakeEngines
) -> None:
    _, alice = add_user(services, "Alice")
    _, bob = add_user(services, "Bob")
    first = submit(client, alice).json()
    run_all(services, engines)
    assert engines.calls == 1
    hit = submit(client, alice, name="renamed.txt")
    assert hit.status_code == 201
    assert hit.json()["cache_hit"] is True and hit.json()["document_id"] == first["document_id"]
    bobs = submit(client, bob)  # the same bytes in another owner's library are not reused
    assert bobs.status_code == 202 and bobs.json()["document_id"] != first["document_id"]
    run_all(services, engines)
    assert engines.calls == 2
    changes: list[dict[str, Any]] = [{"target": "ja"}, {"mode": "llm"}, {"min_scale": 0.8}]
    for changed in changes:
        assert submit(client, alice, **changed).status_code == 202, changed
        run_all(services, engines)
    forced = submit(client, alice, force_retranslate=True).json()
    run_all(services, engines)
    assert engines.calls == 6
    old = job(client, alice, first["id"])
    assert old["result_available"] is True and old["result_expires_at"] is not None
    new = job(client, alice, forced["id"])
    assert new["result_expires_at"] is None
    document = client.get(f"/v1/documents/{first['document_id']}", headers=alice).json()
    en = [t for t in document["translations"] if t["target"] == "en"]
    assert len(en) == 1 and en[0]["job_id"] == forced["id"]


def test_temporary_jobs_never_reuse_and_expire(
    client: TestClient, services: Services, engines: FakeEngines
) -> None:
    _, headers = add_user(services)
    first = submit(client, headers, retention="temporary").json()
    assert first["document_id"] is None and first["retention"] == "temporary"
    run_all(services, engines)
    second = submit(client, headers, retention="temporary")
    assert second.status_code == 202  # temporary requests always run
    run_all(services, engines)
    assert engines.calls == 2
    done = job(client, headers, first["id"])
    assert done["result_available"] and done["result_expires_at"] is not None
    assert client.get("/v1/documents", headers=headers).json()["items"] == []


def test_one_active_job_per_document_and_target(
    client: TestClient, services: Services, engines: FakeEngines
) -> None:
    _, headers = add_user(services)
    first = submit(client, headers).json()
    conflict = submit(client, headers, force_retranslate=True)
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "translation_active"
    assert conflict.json()["details"]["job_id"] == first["id"]
    other_target = submit(client, headers, target="ja")
    assert other_target.status_code == 202
    run_all(services, engines)
    assert submit(client, headers, force_retranslate=True).status_code == 202


def test_translate_saved_document_without_reupload(
    client: TestClient, services: Services, engines: FakeEngines
) -> None:
    _, headers = add_user(services)
    doc = client.post("/v1/documents", headers=headers, files={"file": ("a.txt", TXT)}).json()
    body = {"target": "en", "mode": "mt", "submission_id": str(uuid.uuid4())}
    response = client.post(f"/v1/documents/{doc['id']}/translations", headers=headers, json=body)
    assert response.status_code == 202
    replay = client.post(f"/v1/documents/{doc['id']}/translations", headers=headers, json=body)
    assert replay.status_code == 200 and replay.json()["id"] == response.json()["id"]
    run_all(services, engines)
    again = client.post(
        f"/v1/documents/{doc['id']}/translations",
        headers=headers,
        json=body | {"submission_id": str(uuid.uuid4())},
    )
    assert again.status_code == 201 and again.json()["cache_hit"] is True


def test_idempotent_replay_and_mismatch(client: TestClient, services: Services) -> None:
    _, headers = add_user(services)
    submission = str(uuid.uuid4())
    first = submit(client, headers, submission_id=submission)
    replay = submit(client, headers, submission_id=submission)
    assert replay.status_code == 200 and replay.json()["id"] == first.json()["id"]
    changed = submit(client, headers, content=TXT + b"x", submission_id=submission)
    assert changed.status_code == 409 and changed.json()["code"] == "idempotency_mismatch"


def test_identity_change_between_submission_and_worker_fails_the_job(
    client: TestClient, services: Services, engines: FakeEngines
) -> None:
    _, headers = add_user(services)
    queued = submit(client, headers).json()
    engines.loaded_version = "fake-2"
    run_all(services, engines)
    failed = job(client, headers, queued["id"])
    assert failed["status"] == "failed" and failed["error_code"] == "identity_mismatch"
    assert engines.calls == 0


def test_users_cannot_see_each_others_records(
    client: TestClient, services: Services, engines: FakeEngines
) -> None:
    _, alice = add_user(services, "Alice")
    _, bob = add_user(services, "Bob")
    done = submit(client, alice).json()
    run_all(services, engines)
    doc = done["document_id"]
    for path in (
        f"/v1/jobs/{done['id']}",
        f"/v1/jobs/{done['id']}/file",
        f"/v1/jobs/{done['id']}/fit-report",
        f"/v1/jobs/{done['id']}/preview",
        f"/v1/documents/{doc}",
        f"/v1/documents/{doc}/original",
    ):
        response = client.get(path, headers=bob)
        assert response.status_code == 404, path
    for path in (f"/v1/jobs/{done['id']}/cancel", f"/v1/jobs/{done['id']}/dismiss"):
        assert client.post(path, headers=bob).status_code == 404
    assert client.delete(f"/v1/documents/{doc}", headers=bob).status_code == 404
    assert client.get("/v1/jobs", headers=bob).json()["items"] == []
    assert client.get("/v1/documents", headers=bob).json()["items"] == []


def test_deleting_a_document_revokes_its_job_downloads(
    client: TestClient, services: Services, engines: FakeEngines
) -> None:
    _, headers = add_user(services)
    done = submit(client, headers).json()
    run_all(services, engines)
    assert client.get(f"/v1/jobs/{done['id']}/file", headers=headers).status_code == 200
    assert client.delete(f"/v1/documents/{done['document_id']}", headers=headers).status_code == 204
    assert client.get(f"/v1/jobs/{done['id']}/file", headers=headers).status_code == 404
    assert job(client, headers, done["id"])["result_available"] is False
    # A new upload of the same bytes starts a fresh document and translates again.
    fresh = submit(client, headers).json()
    assert fresh["document_id"] != done["document_id"] and fresh["status"] == "queued"


def test_deleting_a_translation_keeps_the_source(
    client: TestClient, services: Services, engines: FakeEngines
) -> None:
    _, headers = add_user(services)
    done = submit(client, headers).json()
    run_all(services, engines)
    document = client.get(f"/v1/documents/{done['document_id']}", headers=headers).json()
    [translation] = document["translations"]
    url = f"/v1/documents/{document['id']}/translations/{translation['id']}"
    assert client.delete(url, headers=headers).status_code == 204
    after = client.get(f"/v1/documents/{document['id']}", headers=headers).json()
    assert after["translations"] == []
    assert client.get(f"/v1/jobs/{done['id']}/file", headers=headers).status_code == 404
    assert submit(client, headers).status_code == 202  # nothing to reuse any more


def test_rejections_are_typed(client: TestClient, services: Services) -> None:
    _, headers = add_user(services)
    assert submit(client, headers, content=b"abc", name="scan.png").status_code == 415
    assert (
        submit(client, headers, content=b"PK\x03\x04garbage", name="deck.pptx").status_code == 422
    )
    same = submit(client, headers, target="zh", source="zh")
    assert same.status_code == 422 and same.json()["code"] == "invalid_options"


def test_admission_and_quota_limits(tmp_path: Path, engines: FakeEngines) -> None:
    services = make_services(
        server_settings(tmp_path, max_queued_jobs_per_user=1, owner_quota_bytes=len(TXT) + 10),
        engines,
    )
    try:
        client = TestClient(create_app(services))
        _, headers = add_user(services)
        assert submit(client, headers).status_code == 202
        full = submit(client, headers, retention="temporary")
        assert full.status_code == 429 and full.headers["retry-after"] == "5"
        over = client.post(
            "/v1/documents", headers=headers, files={"file": ("b.txt", TXT + b"more")}
        )
        assert over.status_code == 413 and over.json()["code"] == "quota_exceeded"
    finally:
        services.close()


def test_batch_lifecycle_with_mixed_items(
    client: TestClient, services: Services, engines: FakeEngines
) -> None:
    _, headers = add_user(services)
    key = str(uuid.uuid4())
    batch = client.post("/v1/batches", headers=headers, json={"idempotency_key": key}).json()["id"]

    def item(name: str, content: bytes, **opts: Any) -> Any:
        return client.post(
            f"/v1/batches/{batch}/items",
            headers=headers,
            files={"file": (name, content)},
            data={"options": options(**opts), "client_item_id": str(uuid.uuid4())},
        )

    deck = (FIXTURES / "pptx" / "deck.pptx").read_bytes()
    assert item("a/notes.txt", TXT).status_code == 202
    assert item("b/notes.txt", TXT, retention="temporary").status_code == 202
    assert item("deck.pptx", deck).status_code == 202
    assert item("photo.png", b"not a document").status_code == 415
    assert item("broken.docx", b"PK\x03\x04broken").status_code == 422
    run_all(services, engines)
    items = client.get(f"/v1/batches/{batch}/items", headers=headers).json()["items"]
    assert [i["job"]["status"] if i["job"] else i["rejection_code"] for i in items] == [
        "succeeded",
        "succeeded",
        "succeeded",
        "unsupported_document",
        "invalid_document",
    ]
    sealed = client.post(f"/v1/batches/{batch}/seal", headers=headers).json()
    assert sealed["counts"] == {"rejected": 2, "succeeded": 3}
    assert item("late.txt", TXT + b"late").status_code == 409


def test_sessions_with_csrf(client: TestClient, services: Services, engines: FakeEngines) -> None:
    user = auth.create_user(services.db, "Mei")
    key = auth.create_key(services.db, user.id).secret
    signed = client.post("/v1/sessions", json={"key": key})
    assert signed.status_code == 201
    body = signed.json()
    assert body["user"]["id"] == user.id and body["csrf_token"]
    assert "dt_session" in signed.cookies
    assert client.get("/v1/me").json()["id"] == user.id  # the cookie authenticates
    no_csrf = submit(client, {})
    assert no_csrf.status_code == 403 and no_csrf.json()["code"] == "csrf_failed"
    csrf = {"X-CSRF-Token": body["csrf_token"]}
    assert submit(client, csrf).status_code == 202
    cross = submit(client, csrf | {"Origin": "https://evil.example"})
    assert cross.status_code == 403
    assert client.delete("/v1/sessions/current", headers=csrf).status_code == 204
    assert client.get("/v1/me").status_code == 401
    # A revoked key ends its sessions.
    again = client.post("/v1/sessions", json={"key": key})
    assert client.get("/v1/me").status_code == 200
    auth.revoke_key(services.db, auth.list_keys(services.db, user.id)[0].id)
    assert client.get("/v1/me").status_code == 401
    assert again.status_code == 201


def test_sign_in_failures_are_rate_limited(client: TestClient, services: Services) -> None:
    for _ in range(10):
        assert client.post("/v1/sessions", json={"key": "dt_wrong"}).status_code == 401
    assert client.post("/v1/sessions", json={"key": "dt_wrong"}).status_code == 429


def test_conflicting_credentials_are_rejected(client: TestClient, services: Services) -> None:
    alice = auth.create_user(services.db, "Alice")
    key = auth.create_key(services.db, alice.id).secret
    client.post("/v1/sessions", json={"key": key})
    _, bob = add_user(services, "Bob")
    assert client.get("/v1/me", headers=bob).status_code == 401


def test_dismiss_restore_and_active_list(
    client: TestClient, services: Services, engines: FakeEngines
) -> None:
    _, headers = add_user(services)
    done = submit(client, headers).json()
    run_all(services, engines)
    active = client.get("/v1/jobs", headers=headers, params={"active": "true"}).json()["items"]
    assert [j["id"] for j in active] == [done["id"]]
    client.post(f"/v1/jobs/{done['id']}/dismiss", headers=headers)
    assert client.get("/v1/jobs", headers=headers, params={"active": "true"}).json()["items"] == []
    restored = client.post(f"/v1/jobs/{done['id']}/restore", headers=headers).json()
    assert restored["dismissed_at"] is None


def test_skip_fit_outside_the_fit_stage_is_a_conflict(
    client: TestClient, services: Services
) -> None:
    _, headers = add_user(services)
    queued = submit(client, headers).json()
    response = client.post(f"/v1/jobs/{queued['id']}/skip-fit", headers=headers)
    assert response.status_code == 409 and response.json()["code"] == "not_in_fit"


def test_previews_for_text_and_pdf(
    client: TestClient, services: Services, engines: FakeEngines, tmp_path: Path
) -> None:
    _, headers = add_user(services)
    text = submit(client, headers).json()
    pdf = submit(
        client, headers, content=write_mixed(tmp_path / "m.pdf").read_bytes(), name="m.pdf"
    ).json()
    run_all(services, engines)
    manifest = client.get(f"/v1/jobs/{text['id']}/preview", headers=headers).json()
    [group] = manifest["groups"]
    assert group["paired"] is True
    assert group["units"][0]["source"].startswith("这是")
    assert group["units"][0]["target"].startswith("EN:")
    pages = client.get(f"/v1/jobs/{pdf['id']}/preview", headers=headers).json()
    assert pages["format"] == "pdf" and len(pages["pages"]) == 1
    image = client.get(
        f"/v1/jobs/{pdf['id']}/preview/{pages['pages'][0]['target']}", headers=headers
    )
    assert image.status_code == 200 and image.headers["content-type"] == "image/jpeg"
    assert (
        client.get(f"/v1/jobs/{pdf['id']}/preview/manifest.json", headers=headers).status_code
        == 404
    )


def test_openapi_documents_the_contract(client: TestClient) -> None:
    paths = set(client.get("/v1/openapi.json").json()["paths"])
    assert {
        "/v1/sessions",
        "/v1/sessions/current",
        "/v1/documents",
        "/v1/documents/{document_id}/translations",
        "/v1/documents/{document_id}/translations/{translation_id}/file",
        "/v1/jobs/{job_id}/file",
        "/v1/jobs/{job_id}/skip-fit",
        "/v1/jobs/{job_id}/dismiss",
        "/v1/jobs/{job_id}/preview",
        "/v1/batches/{batch_id}/items",
    } <= paths
