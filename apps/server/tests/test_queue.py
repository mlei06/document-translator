"""Attempt-fenced queue (ADR-016): claims, leases, stale attempts, cancellation and retries."""

import json
import uuid
from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from support.fakes import FIXTURES
from support.fonts import TEST_FONT, synthetic_font_manifest
from support.ooxml import rewrite
from support.server import (
    FakeEngines,
    add_user,
    make_queue,
    make_services,
    make_worker,
    server_settings,
)

from doctranslator_core.types import EngineUnavailableError, InvalidDocumentError, TranslationMode
from doctranslator_server import auth
from doctranslator_server.app import Services, create_app
from doctranslator_server.db.models import Job as JobRow
from doctranslator_server.db.models import utcnow
from doctranslator_server.jobs.queue import Output, Queue

TXT = "这是一个用于测试的中文段落，内容足够长以便识别语言。\n".encode()


class Clock:
    def __init__(self) -> None:
        self.now = utcnow() + timedelta(seconds=5)  # after the fixtures' submissions

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


@pytest.fixture
def engines() -> FakeEngines:
    return FakeEngines()


@pytest.fixture
def services(tmp_path: Path, engines: FakeEngines) -> Iterator[Services]:
    services = make_services(server_settings(tmp_path, lease_s=60.0), engines)
    yield services
    services.close()


@pytest.fixture
def clock() -> Clock:
    return Clock()


def submit(
    services: Services,
    headers: dict[str, str],
    content: bytes = TXT,
    retention: str = "saved",
) -> str:
    client = TestClient(create_app(services))
    options = json.dumps({"target": "en", "mode": "mt", "retention": retention})
    response = client.post(
        "/v1/jobs",
        headers=headers,
        files={"file": ("notes.txt", content)},
        data={"options": options, "submission_id": str(uuid.uuid4())},
    )
    assert response.status_code == 202, response.text
    return str(response.json()["id"])


def job(services: Services, job_id: str) -> tuple[str, int, str | None, bool]:
    row = make_queue(services).job(job_id)
    assert row is not None
    return row.status, row.attempts, row.error_code, row.cancel_requested


def translations(services: Services, headers: dict[str, str]) -> int:
    """Current translations in the owner's library (published results)."""
    client = TestClient(create_app(services))
    items = client.get("/v1/documents", headers=headers).json()["items"]
    return sum(len(d["translations"]) for d in items)


def test_a_job_is_claimed_once(services: Services, clock: Clock) -> None:
    _, headers = add_user(services)
    submit(services, headers)
    queue = make_queue(services, clock)
    first = queue.claim("w1")
    assert first is not None
    assert queue.claim("w2") is None
    assert first.attempts == 1


def test_stale_attempt_cannot_publish_after_reclaim(
    services: Services, engines: FakeEngines, clock: Clock
) -> None:
    _, headers = add_user(services)
    job_id = submit(services, headers)
    queue = make_queue(services, clock)
    old = queue.claim("w1")
    assert old is not None
    clock.advance(61)  # the lease expires without heartbeats
    assert queue.recover() == [(job_id, "requeued")]
    new = queue.claim("w1")  # the same worker ID reclaims: a new token fences the old attempt
    assert new is not None and new.token != old.token and new.attempts == 2
    assert queue.heartbeat(old) == (False, False)
    assert queue.progress(old, "translate", 1, 2).owned is False
    output = Output("0" * 64, "1" * 64, None, [], "zh", "passed", {})
    assert queue.publish(old, output, reuse=None) is False
    assert queue.fail(old, "x", "y") is False
    assert queue.cancelled(old) is False
    assert job(services, job_id)[0] == "running"
    worker = make_worker(services, engines, queue)
    worker.process(new)
    assert job(services, job_id)[0] == "succeeded"
    assert translations(services, headers) == 1


def test_expired_lease_cannot_publish_even_without_reclaim(
    services: Services, clock: Clock
) -> None:
    _, headers = add_user(services)
    submit(services, headers)
    queue = make_queue(services, clock)
    attempt = queue.claim("w1")
    assert attempt is not None
    clock.advance(61)
    output = Output("0" * 64, "1" * 64, None, [], "zh", "passed", {})
    assert queue.publish(attempt, output, reuse=None) is False
    assert queue.heartbeat(attempt)[0] is False


def test_recovery_budget_then_worker_lost(services: Services, clock: Clock) -> None:
    _, headers = add_user(services)
    job_id = submit(services, headers)
    queue = make_queue(services, clock)
    for expected in ("requeued", "requeued", "failed"):
        assert queue.claim("w") is not None
        clock.advance(61)
        assert queue.recover() == [(job_id, expected)]
    status, attempts, code, _ = job(services, job_id)
    assert (status, attempts, code) == ("failed", 3, "worker_lost")


def test_cancelling_a_queued_job_is_immediate(services: Services, engines: FakeEngines) -> None:
    _, headers = add_user(services)
    job_id = submit(services, headers)
    client = TestClient(create_app(services))
    cancelled = client.post(f"/v1/jobs/{job_id}/cancel", headers=headers).json()
    assert cancelled["status"] == "cancelled"
    assert make_worker(services, engines).run_once() is False
    assert engines.calls == 0


def test_cancel_during_translation_publishes_nothing(
    services: Services, engines: FakeEngines
) -> None:
    _, headers = add_user(services)
    job_id = submit(services, headers)
    client = TestClient(create_app(services))

    def cancel_now(_mode: TranslationMode, _source: Path) -> None:
        client.post(f"/v1/jobs/{job_id}/cancel", headers=headers)

    engines.before = cancel_now
    make_worker(services, engines).run_once()
    assert job(services, job_id)[0] == "cancelled"
    assert translations(services, headers) == 0


def test_cancel_after_success_keeps_the_success(services: Services, engines: FakeEngines) -> None:
    _, headers = add_user(services)
    job_id = submit(services, headers)
    make_worker(services, engines).run_once()
    client = TestClient(create_app(services))
    after = client.post(f"/v1/jobs/{job_id}/cancel", headers=headers).json()
    assert after["status"] == "succeeded" and after["document_id"]


def test_disabled_owner_cannot_publish(services: Services, engines: FakeEngines) -> None:
    user_id, headers = add_user(services)
    job_id = submit(services, headers)

    def disable(_mode: TranslationMode, _source: Path) -> None:
        auth.set_user_active(services.db, user_id, active=False)

    engines.before = disable
    make_worker(services, engines).run_once()
    assert job(services, job_id)[0] != "succeeded"
    client = TestClient(create_app(services))
    assert client.get("/v1/me", headers=headers).status_code == 401
    auth.set_user_active(services.db, user_id, active=True)
    assert translations(services, headers) == 0


def test_transient_engine_errors_retry_then_fail(services: Services, engines: FakeEngines) -> None:
    _, headers = add_user(services)
    job_id = submit(services, headers)

    def unavailable(_mode: TranslationMode, _source: Path) -> None:
        raise EngineUnavailableError("the engine is down")

    engines.before = unavailable
    worker = make_worker(services, engines)
    while worker.run_once():
        pass
    status, attempts, code, _ = job(services, job_id)
    assert (status, attempts, code) == ("failed", 3, "engine_unavailable")
    assert engines.calls == 3


def test_permanent_errors_fail_without_retry(services: Services, engines: FakeEngines) -> None:
    _, headers = add_user(services)
    job_id = submit(services, headers)

    def invalid(_mode: TranslationMode, _source: Path) -> None:
        raise InvalidDocumentError("the document is damaged")

    engines.before = invalid
    worker = make_worker(services, engines)
    while worker.run_once():
        pass
    status, attempts, code, _ = job(services, job_id)
    assert (status, attempts, code) == ("failed", 1, "invalid_document")
    row = make_queue(services).job(job_id)
    assert row is not None and row.error_message == "the document is damaged"


def test_identical_saved_submissions_are_serialized_per_target(
    services: Services, engines: FakeEngines
) -> None:
    _, headers = add_user(services)
    first = submit(services, headers)
    client = TestClient(create_app(services))
    busy = client.post(
        "/v1/jobs",
        headers=headers,
        files={"file": ("again.txt", TXT)},
        data={"options": '{"target": "en", "mode": "mt"}', "submission_id": str(uuid.uuid4())},
    )
    assert busy.status_code == 409 and busy.json()["details"]["job_id"] == first
    make_worker(services, engines).run_once()
    assert engines.calls == 1 and translations(services, headers) == 1


def test_temporary_jobs_never_reuse_even_at_the_worker(
    services: Services, engines: FakeEngines
) -> None:
    _, headers = add_user(services)
    saved = submit(services, headers)
    worker = make_worker(services, engines)
    worker.run_once()
    temporary = submit(services, headers, retention="temporary")
    worker.run_once()
    assert engines.calls == 2
    assert job(services, saved)[0] == job(services, temporary)[0] == "succeeded"
    assert translations(services, headers) == 1  # temporary results never enter the library


def test_two_owners_translate_the_same_bytes_independently(
    services: Services, engines: FakeEngines, clock: Clock
) -> None:
    _, alice = add_user(services, "Alice")
    _, bob = add_user(services, "Bob")
    a = submit(services, alice)
    b = submit(services, bob)
    queue: Queue = make_queue(services)
    attempt_a, attempt_b = queue.claim("w1"), queue.claim("w2")
    assert attempt_a is not None and attempt_b is not None
    worker = make_worker(services, engines, queue)
    worker.process(attempt_a)
    engines_b = FakeEngines()
    make_worker(services, engines_b, queue, "w2").process(attempt_b)
    assert job(services, a)[0] == job(services, b)[0] == "succeeded"
    assert translations(services, alice) == translations(services, bob) == 1


def test_skip_fit_is_accepted_only_during_the_fit_stage(services: Services, clock: Clock) -> None:
    _, headers = add_user(services)
    job_id = submit(services, headers)
    queue = make_queue(services, clock)
    attempt = queue.claim("w1")
    assert attempt is not None
    client = TestClient(create_app(services))
    assert client.post(f"/v1/jobs/{job_id}/skip-fit", headers=headers).status_code == 409
    queue.progress(attempt, "fit", None, None)
    first = client.post(f"/v1/jobs/{job_id}/skip-fit", headers=headers)
    assert first.status_code == 202 and first.json()["fit_skip_requested"] is True
    assert first.json()["progress"] == {
        "phase": "fit",
        "done": None,
        "total": None,
        "updated_at": first.json()["progress"]["updated_at"],
    }
    assert client.post(f"/v1/jobs/{job_id}/skip-fit", headers=headers).status_code == 200
    assert queue.control(attempt).skip_fit is True


def test_skipped_fit_is_saved_but_never_reused(
    services: Services, engines: FakeEngines, tmp_path: Path
) -> None:
    engines.fonts = synthetic_font_manifest(tmp_path)
    workbook = rewrite(
        FIXTURES / "xlsx" / "labels.xlsx",
        tmp_path / "labels.xlsx",
        "xl/styles.xml",
        lambda d: d.replace(b'<name val="Aptos Narrow"/>', f'<name val="{TEST_FONT}"/>'.encode()),
    ).read_bytes()
    _, headers = add_user(services)
    job_id = submit_file(services, headers, workbook, "labels.xlsx")

    def request_skip(_mode: TranslationMode, _source: Path) -> None:
        with services.db.session() as session:
            row = session.get(JobRow, job_id)
            assert row is not None
            row.fit_skip_requested = True  # as accepted by the endpoint once fit starts

    engines.before = request_skip
    make_worker(services, engines).run_once()
    client = TestClient(create_app(services))
    done = client.get(f"/v1/jobs/{job_id}", headers=headers).json()
    assert done["status"] == "succeeded" and done["fit_status"] == "skipped"
    assert client.get(f"/v1/jobs/{job_id}/file", headers=headers).status_code == 200
    assert translations(services, headers) == 1  # the skipped result is current
    engines.before = None
    again = submit_file(services, headers, workbook, "labels.xlsx")
    assert job(services, again)[0] == "queued"  # a normal request does not reuse a skipped fit


def submit_file(services: Services, headers: dict[str, str], content: bytes, name: str) -> str:
    client = TestClient(create_app(services))
    response = client.post(
        "/v1/jobs",
        headers=headers,
        files={"file": (name, content)},
        data={
            "options": '{"target": "en", "mode": "mt", "source": "zh"}',
            "submission_id": str(uuid.uuid4()),
        },
    )
    assert response.status_code == 202, response.text
    return str(response.json()["id"])
