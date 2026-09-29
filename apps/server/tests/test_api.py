"""REST contract (/v1): authentication, submission, idempotency, cache, ownership, batches."""

import hashlib
import json
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from support.fakes import FIXTURES
from support.server import FakeEngines, add_user, make_services, make_worker, server_settings

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


def test_every_route_requires_a_valid_key(client: TestClient, services: Services) -> None:
    assert client.get("/v1/health").status_code == 200
    for headers in ({}, {"Authorization": "Bearer nope"}, {"Authorization": "Basic x"}):
        response = client.get("/v1/me", headers=headers)
        assert response.status_code == 401
        assert response.json()["code"] == "unauthenticated"
        assert response.headers["www-authenticate"] == "Bearer"
    user_id, headers = add_user(services)
    me = client.get("/v1/me", headers=headers).json()
    assert me == {"id": user_id, "display_name": "Alice", "kind": "person"}
    wrong = headers["Authorization"][:-4] + "AAAA"
    assert client.get("/v1/me", headers={"Authorization": wrong}).status_code == 401


def test_capabilities_list_formats_modes_and_limits(client: TestClient, services: Services) -> None:
    _, headers = add_user(services)
    caps = client.get("/v1/capabilities", headers=headers).json()
    assert caps["formats"] == ["docx", "pdf", "pptx", "txt", "xlsx"]
    assert caps["modes"] == ["mt", "llm"]
    assert caps["limits"]["max_upload_bytes"] == 100 << 20
    assert "path" not in json.dumps(caps)


def test_submit_translate_download_and_report(
    client: TestClient, services: Services, engines: FakeEngines
) -> None:
    _, headers = add_user(services)
    response = submit(client, headers)
    assert response.status_code == 202
    job = response.json()
    assert job["status"] == "queued" and job["document_id"] is None
    run_all(services, engines)
    job = client.get(f"/v1/jobs/{job['id']}", headers=headers).json()
    assert job["status"] == "succeeded"
    assert job["source_resolved"] == "zh" and job["fit_status"] == "not_applicable"
    document = client.get(f"/v1/documents/{job['document_id']}", headers=headers).json()
    assert document["original_name"] == "notes.txt" and document["version"] == 0
    file = client.get(f"/v1/documents/{document['id']}/versions/0/file", headers=headers)
    assert file.status_code == 200
    assert file.content.decode("utf-8").startswith("EN:")
    assert hashlib.sha256(file.content).hexdigest() == file.headers["x-content-sha256"]
    assert 'filename="notes.en.txt"' in file.headers["content-disposition"]
    report = client.get(
        f"/v1/documents/{document['id']}/versions/0/fit-report", headers=headers
    ).json()
    assert report["fit_report"]["status"] == "not_applicable"
    assert "output_path" not in report
    original = client.get(f"/v1/documents/{document['id']}/original", headers=headers)
    assert original.content == TXT


def test_idempotent_replay_and_mismatch(client: TestClient, services: Services) -> None:
    _, headers = add_user(services)
    submission = str(uuid.uuid4())
    first = submit(client, headers, submission_id=submission)
    replay = submit(client, headers, submission_id=submission)
    assert replay.status_code == 200
    assert replay.json()["id"] == first.json()["id"]
    changed = submit(client, headers, content=TXT + b"x", submission_id=submission)
    assert changed.status_code == 409
    assert changed.json()["code"] == "idempotency_mismatch"
    other_options = submit(client, headers, submission_id=submission, target="ja")
    assert other_options.status_code == 409


def test_cache_hit_skips_the_engine_and_force_bypasses_it(
    client: TestClient, services: Services, engines: FakeEngines
) -> None:
    _, headers = add_user(services)
    submit(client, headers)
    run_all(services, engines)
    assert engines.calls == 1
    hit = submit(client, headers, name="renamed.txt")
    assert hit.status_code == 201
    assert hit.json()["cache_hit"] is True and hit.json()["status"] == "succeeded"
    run_all(services, engines)
    assert engines.calls == 1
    changes: list[dict[str, Any]] = [{"target": "ja"}, {"mode": "llm"}, {"min_scale": 0.8}]
    for changed in changes:
        miss = submit(client, headers, **changed)
        assert miss.status_code == 202, changed
    forced = submit(client, headers, force_retranslate=True)
    assert forced.status_code == 202 and forced.json()["force"] is True
    run_all(services, engines)
    assert engines.calls == 5
    engines.version = "fake-2"  # a new engine identity misses the cache too
    assert submit(client, headers).status_code == 202


def test_identity_change_between_submission_and_worker_fails_the_job(
    client: TestClient, services: Services, engines: FakeEngines
) -> None:
    _, headers = add_user(services)
    job = submit(client, headers).json()
    engines.loaded_version = "fake-2"
    run_all(services, engines)
    job = client.get(f"/v1/jobs/{job['id']}", headers=headers).json()
    assert job["status"] == "failed" and job["error_code"] == "identity_mismatch"
    assert engines.calls == 0


def test_users_cannot_see_each_others_records(
    client: TestClient, services: Services, engines: FakeEngines
) -> None:
    _, alice = add_user(services, "Alice")
    _, bob = add_user(services, "Bob")
    job = submit(client, alice).json()
    run_all(services, engines)
    job = client.get(f"/v1/jobs/{job['id']}", headers=alice).json()
    doc = job["document_id"]
    for path in (
        f"/v1/jobs/{job['id']}",
        f"/v1/documents/{doc}",
        f"/v1/documents/{doc}/versions/0/file",
        f"/v1/documents/{doc}/versions/0/fit-report",
        f"/v1/documents/{doc}/original",
    ):
        response = client.get(path, headers=bob)
        assert response.status_code == 404, path
        assert response.json()["code"] == "not_found"
    assert client.post(f"/v1/jobs/{job['id']}/cancel", headers=bob).status_code == 404
    assert client.delete(f"/v1/documents/{doc}", headers=bob).status_code == 404
    assert client.get("/v1/jobs", headers=bob).json()["items"] == []
    assert client.get("/v1/documents", headers=bob).json()["items"] == []
    # Bob's identical upload is a cache hit that creates Bob's own records only.
    hit = submit(client, bob).json()
    assert hit["cache_hit"] is True
    assert hit["id"] != job["id"] and hit["document_id"] != doc
    assert client.get(f"/v1/documents/{doc}", headers=alice).status_code == 200


def test_deleting_a_document_removes_access_but_not_the_job(
    client: TestClient, services: Services, engines: FakeEngines
) -> None:
    _, headers = add_user(services)
    job = submit(client, headers).json()
    run_all(services, engines)
    doc = client.get(f"/v1/jobs/{job['id']}", headers=headers).json()["document_id"]
    assert client.delete(f"/v1/documents/{doc}", headers=headers).status_code == 204
    assert client.get(f"/v1/documents/{doc}/versions/0/file", headers=headers).status_code == 404
    assert client.get(f"/v1/jobs/{job['id']}", headers=headers).json()["document_id"] is None


def test_rejections_are_typed(client: TestClient, services: Services) -> None:
    _, headers = add_user(services)
    unsupported = submit(client, headers, content=b"abc", name="scan.png")
    assert unsupported.status_code == 415
    assert unsupported.json()["code"] == "unsupported_document"
    broken = submit(client, headers, content=b"PK\x03\x04garbage", name="deck.pptx")
    assert broken.status_code == 422
    same = submit(client, headers, target="zh", source="zh")
    assert same.status_code == 422 and same.json()["code"] == "invalid_options"
    bad_json = client.post(
        "/v1/jobs",
        headers=headers,
        files={"file": ("a.txt", TXT)},
        data={"options": "{", "submission_id": str(uuid.uuid4())},
    )
    assert bad_json.status_code == 422
    assert "traceback" not in bad_json.text.lower()


def test_admission_limit_returns_429_with_retry_after(tmp_path: Path, engines: FakeEngines) -> None:
    services = make_services(server_settings(tmp_path, max_queued_jobs_per_user=1), engines)
    try:
        client = TestClient(create_app(services))
        _, headers = add_user(services)
        assert submit(client, headers).status_code == 202
        full = submit(client, headers, content=TXT + b"2")
        assert full.status_code == 429
        assert full.headers["retry-after"] == "5"
        assert full.json()["retryable"] is True
    finally:
        services.close()


def test_upload_size_limit(tmp_path: Path, engines: FakeEngines) -> None:
    services = make_services(server_settings(tmp_path, max_upload_bytes=1000), engines)
    try:
        client = TestClient(create_app(services))
        _, headers = add_user(services)
        big = submit(client, headers, content=b"x" * 70_000)
        assert big.status_code == 413
        just_over = submit(client, headers, content=b"x" * 1001)
        assert just_over.status_code == 413
        assert not any((services.settings.data_dir / "staging").iterdir())
    finally:
        services.close()


def test_batch_lifecycle_with_mixed_items(
    client: TestClient, services: Services, engines: FakeEngines
) -> None:
    _, headers = add_user(services)
    key = str(uuid.uuid4())
    created = client.post("/v1/batches", headers=headers, json={"idempotency_key": key})
    assert created.status_code == 201
    again = client.post("/v1/batches", headers=headers, json={"idempotency_key": key})
    assert again.status_code == 200 and again.json()["id"] == created.json()["id"]
    batch = created.json()["id"]

    def item(name: str, content: bytes, client_id: str | None = None) -> Any:
        return client.post(
            f"/v1/batches/{batch}/items",
            headers=headers,
            files={"file": (name, content)},
            data={"options": options(), "client_item_id": client_id or str(uuid.uuid4())},
        )

    deck = (FIXTURES / "pptx" / "deck.pptx").read_bytes()
    first_id = str(uuid.uuid4())
    assert item("a/notes.txt", TXT, first_id).status_code == 202
    assert item("b/notes.txt", TXT).status_code == 202  # same basename and bytes, other folder
    assert item("deck.pptx", deck).status_code == 202
    rejected = item("photo.png", b"not a document")
    assert rejected.status_code == 415
    assert rejected.json()["details"]["item_id"]
    malformed = item("broken.docx", b"PK\x03\x04broken")
    assert malformed.status_code == 422
    replay = item("a/notes.txt", TXT, first_id)
    assert replay.status_code == 200
    run_all(services, engines)
    items = client.get(f"/v1/batches/{batch}/items", headers=headers).json()["items"]
    assert [i["ordinal"] for i in items] == [0, 1, 2, 3, 4]
    assert [i["original_name"] for i in items] == [
        "notes.txt",
        "notes.txt",
        "deck.pptx",
        "photo.png",
        "broken.docx",
    ]
    assert [i["job"]["status"] if i["job"] else i["rejection_code"] for i in items] == [
        "succeeded",
        "succeeded",
        "succeeded",
        "unsupported_document",
        "invalid_document",
    ]
    documents = {i["job"]["document_id"] for i in items if i["job"]}
    assert len(documents) == 3  # every accepted item has its own document
    by_client = client.get(
        f"/v1/batches/{batch}/items", headers=headers, params={"client_item_id": first_id}
    ).json()["items"]
    assert len(by_client) == 1 and by_client[0]["ordinal"] == 0
    page = client.get(f"/v1/batches/{batch}/items", headers=headers, params={"limit": 2}).json()
    assert len(page["items"]) == 2 and page["next_cursor"] == "1"
    sealed = client.post(f"/v1/batches/{batch}/seal", headers=headers).json()
    assert sealed["state"] == "sealed"
    assert sealed["counts"] == {"rejected": 2, "succeeded": 3}
    assert item("late.txt", TXT + b"late").status_code == 409


def test_batch_cancel_stops_outstanding_jobs(
    client: TestClient, services: Services, engines: FakeEngines
) -> None:
    _, headers = add_user(services)
    batch = client.post(
        "/v1/batches", headers=headers, json={"idempotency_key": str(uuid.uuid4())}
    ).json()["id"]
    for index in range(3):
        client.post(
            f"/v1/batches/{batch}/items",
            headers=headers,
            files={"file": (f"f{index}.txt", TXT + str(index).encode())},
            data={"options": options(), "client_item_id": str(uuid.uuid4())},
        )
    cancelled = client.post(f"/v1/batches/{batch}/cancel", headers=headers).json()
    assert cancelled["state"] == "cancelled"
    assert cancelled["counts"] == {"rejected": 0, "cancelled": 3}
    run_all(services, engines)
    assert engines.calls == 0


def test_lists_paginate_newest_first(client: TestClient, services: Services) -> None:
    _, headers = add_user(services)
    ids = [submit(client, headers, content=TXT + str(i).encode()).json()["id"] for i in range(5)]
    first = client.get("/v1/jobs", headers=headers, params={"limit": 2}).json()
    second = client.get(
        "/v1/jobs", headers=headers, params={"limit": 2, "cursor": first["next_cursor"]}
    ).json()
    third = client.get(
        "/v1/jobs", headers=headers, params={"limit": 2, "cursor": second["next_cursor"]}
    ).json()
    listed = [j["id"] for page in (first, second, third) for j in page["items"]]
    assert sorted(listed) == sorted(ids) and len(set(listed)) == 5
    assert third["next_cursor"] is None


def test_openapi_documents_the_contract(client: TestClient) -> None:
    schema = client.get("/v1/openapi.json").json()
    paths = set(schema["paths"])
    assert {
        "/v1/me",
        "/v1/capabilities",
        "/v1/batches",
        "/v1/batches/{batch_id}/items",
        "/v1/batches/{batch_id}/seal",
        "/v1/batches/{batch_id}/cancel",
        "/v1/jobs",
        "/v1/jobs/{job_id}/cancel",
        "/v1/documents/{document_id}/versions/0/file",
        "/v1/documents/{document_id}/versions/0/fit-report",
        "/v1/documents/{document_id}/original",
    } <= paths
