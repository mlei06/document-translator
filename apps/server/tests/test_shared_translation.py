"""Independent REST client acceptance for automatic shared translations."""

import json
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from support.server import (
    FakeEngines,
    add_user,
    make_queue,
    make_services,
    make_worker,
    server_settings,
)

from doctranslator_core import AutomaticTranslationPolicy
from doctranslator_core.types import EnginePolicyDeniedError, EngineResponseError, Language
from doctranslator_server.app import create_app
from doctranslator_server.db.models import Blob, Job, SharedSlot, StorageReservation, utcnow
from doctranslator_server.jobs.queue import Output
from doctranslator_server.jobs.retention import run_retention


def automatic_settings(tmp_path: Path) -> Any:
    policy = AutomaticTranslationPolicy()
    translators = [
        dict(
            id=identifier,
            label=identifier,
            engine=dict(
                mode="llm",
                api_key="synthetic-test-only",
                base_url="https://approved.example/v1",
                model="gemma-4-31b-it" if identifier == "gemma" else identifier,
                deployment_revision="test-v1",
            ),
        )
        for identifier in policy.davy_order
    ]
    translators.append(
        dict(
            id="hy-mt-local",
            label="Local",
            engine=dict(
                mode="llm",
                api_key="synthetic-test-only",
                base_url="http://127.0.0.1:8999/v1",
                model="HY-MT",
                protocol="hy-mt",
                execution_location="server",
                deployment_revision="test-q8-v1",
            ),
        )
    )
    return server_settings(
        tmp_path,
        translators=translators,
        default_translator_id="gemma",
        web_translation_policy=policy.model_dump(mode="json"),
    )


def upload(
    client: TestClient,
    headers: dict[str, str],
    name: str = "notes.txt",
    content: bytes = b"Hello mixed language document.",
) -> str:
    response = client.post(
        "/v1/documents?staging=true", headers=headers, files={"file": (name, content)}
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def translate(
    client: TestClient, headers: dict[str, str], document: str, key: str | None = None
) -> dict[str, Any]:
    response = client.post(
        f"/v1/documents/{document}/translations",
        headers=headers,
        json=dict(
            target="en",
            selection_policy="website_auto",
            retention="cached",
            download_semantics="current_shared",
            submission_id=key or str(uuid.uuid4()),
        ),
    )
    assert response.status_code in (200, 201, 202), response.text
    return response.json()


def test_verified_cross_user_coalescing_current_download_and_revocation(tmp_path: Path) -> None:
    engines = FakeEngines()
    services = make_services(automatic_settings(tmp_path), engines)
    try:
        client = TestClient(create_app(services))
        _, alice = add_user(services, "Alice")
        _, bob = add_user(services, "Bob")
        da, db = upload(client, alice, "private-alice.txt"), upload(client, bob, "private-bob.txt")
        key = str(uuid.uuid4())
        a, b = translate(client, alice, da, key), translate(client, bob, db)
        assert translate(client, alice, da, key)["id"] == a["id"]
        with services.db.session() as session:
            assert len(list(session.scalars(select(Job).where(Job.kind == "shared_work")))) == 1
        assert make_worker(services, engines).run_once()
        assert engines.calls == 1
        ah = client.get("/v1/history", headers=alice).json()["items"]
        bh = client.get("/v1/history", headers=bob).json()["items"]
        assert len(ah) == len(bh) == 1
        assert ah[0]["original_name"] == "private-alice.txt"
        assert bh[0]["original_name"] == "private-bob.txt"
        assert ah[0]["available"] and bh[0]["available"]
        assert client.get(f"/v1/history/{ah[0]['id']}/file", headers=bob).status_code == 404
        for user, item in ((alice, a), (bob, b)):
            result = client.get(f"/v1/jobs/{item['id']}/file", headers=user)
            assert result.status_code == 200, result.text
            assert result.headers["cache-control"] == "private, no-store"
        assert client.delete(f"/v1/history/{ah[0]['id']}", headers=alice).status_code == 204
        assert client.get(f"/v1/jobs/{a['id']}/file", headers=alice).status_code == 404
        assert client.get(f"/v1/jobs/{b['id']}/file", headers=bob).status_code == 200
        c = translate(client, bob, upload(client, bob))
        assert c["status"] == "succeeded" and c["cache_hit"]
        assert c["fit_status"] == "not_applicable"  # plain text has no layout constraints
        assert engines.calls == 1
        with services.db.session() as session:
            digest = session.scalars(select(SharedSlot)).one().source_hash
            assert not services.store.path(digest).exists()
    finally:
        services.close()


def test_cancel_detaches_one_waiter_and_last_waiter_fences_work(tmp_path: Path) -> None:
    engines = FakeEngines()
    services = make_services(automatic_settings(tmp_path), engines)
    try:
        client = TestClient(create_app(services))
        _, alice = add_user(services)
        _, bob = add_user(services, "Bob")
        a = translate(client, alice, upload(client, alice))
        b = translate(client, bob, upload(client, bob))
        assert (
            client.post(f"/v1/jobs/{a['id']}/cancel", headers=alice).json()["status"] == "cancelled"
        )
        assert make_worker(services, engines).run_once()
        assert client.get(f"/v1/jobs/{b['id']}", headers=bob).json()["status"] == "succeeded"
        c = translate(client, alice, upload(client, alice, content=b"Another document"))
        client.post(f"/v1/jobs/{c['id']}/cancel", headers=alice)
        assert not make_worker(services, engines).run_once()
    finally:
        services.close()


def test_whole_document_fallback_and_higher_ranked_upgrade(tmp_path: Path) -> None:
    class Failing(FakeEngines):
        fail = True

        def translate(self, mode: str, *args: Any, **kwargs: Any) -> Any:
            if self.fail and mode != "hy-mt-local":
                raise EngineResponseError("test model response failed")
            return super().translate(mode, *args, **kwargs)

    engines = Failing()
    services = make_services(automatic_settings(tmp_path), engines)
    try:
        client = TestClient(create_app(services))
        _, alice = add_user(services)
        _, bob = add_user(services, "Bob")
        a = translate(client, alice, upload(client, alice))
        make_worker(services, engines).run_once()
        with services.db.session() as session:
            slot = session.scalars(select(SharedSlot)).one()
            assert slot.producer == "hy-mt-local"
        cooled = translate(client, bob, upload(client, bob))
        assert cooled["cache_hit"]
        assert engines.calls == 1
        with services.db.session() as session:
            slot = session.scalars(select(SharedSlot)).one()
            slot.cooldowns = {}  # simulate elapsed failed-upgrade cooldown
        engines.fail = False
        b = translate(client, bob, upload(client, bob))
        make_worker(services, engines).run_once()
        with services.db.session() as session:
            assert session.scalars(select(SharedSlot)).one().producer == "gemma"
        for owner, job in ((alice, a), (bob, b)):
            assert client.get(f"/v1/jobs/{job['id']}/file", headers=owner).status_code == 200
    finally:
        services.close()


def test_expiry_keeps_private_grant_and_recreation_restores_access(tmp_path: Path) -> None:
    engines = FakeEngines()
    services = make_services(automatic_settings(tmp_path), engines)
    try:
        client = TestClient(create_app(services))
        _, alice = add_user(services)
        _, bob = add_user(services, "Bob")
        a = translate(client, alice, upload(client, alice))
        make_worker(services, engines).run_once()
        with services.db.session() as session:
            slot = session.scalars(select(SharedSlot)).one()
            assert not services.store.path(slot.source_hash).exists()
            slot.last_used_at = utcnow() - timedelta(days=31)
            assert not list(session.scalars(select(StorageReservation)))
        run_retention(services.settings, services.db, services.store, holder="test")
        assert client.get(f"/v1/jobs/{a['id']}/file", headers=alice).status_code == 410
        history = client.get("/v1/history", headers=alice).json()["items"]
        assert len(history) == 1 and not history[0]["available"]
        translate(client, bob, upload(client, bob))
        make_worker(services, engines).run_once()
        assert client.get(f"/v1/jobs/{a['id']}/file", headers=alice).status_code == 200
    finally:
        services.close()


def test_policy_denial_does_not_consume_another_model(tmp_path: Path) -> None:
    class Denied(FakeEngines):
        def translate(self, mode: str, *args: Any, **kwargs: Any) -> Any:
            self.calls += 1
            raise EnginePolicyDeniedError("test explicit policy denial")

    engines = Denied()
    services = make_services(automatic_settings(tmp_path), engines)
    try:
        client = TestClient(create_app(services))
        _, owner = add_user(services)
        job = translate(client, owner, upload(client, owner))
        make_worker(services, engines).run_once()
        result = client.get(f"/v1/jobs/{job['id']}", headers=owner).json()
        assert result["status"] == "failed" and result["error_code"] == "engine_policy_denied"
        assert engines.calls == 1
    finally:
        services.close()


def test_capacity_rejects_cold_work_without_losing_upload(tmp_path: Path) -> None:
    engines = FakeEngines()
    services = make_services(automatic_settings(tmp_path), engines)
    try:
        client = TestClient(create_app(services))
        _, owner = add_user(services)
        document = upload(client, owner)
        services.settings.global_work_budget_bytes = 1
        response = client.post(
            f"/v1/documents/{document}/translations",
            headers=owner,
            json=dict(
                target="en",
                selection_policy="website_auto",
                retention="cached",
                download_semantics="current_shared",
                submission_id=str(uuid.uuid4()),
            ),
        )
        assert response.status_code == 503 and response.json()["code"] == "storage_capacity"
        assert client.get(f"/v1/documents/{document}", headers=owner).status_code == 200
        assert engines.calls == 0
    finally:
        services.close()


def test_new_upload_does_not_join_cancelling_work_and_old_publication_is_fenced(
    tmp_path: Path,
) -> None:
    engines = FakeEngines()
    services = make_services(automatic_settings(tmp_path), engines)
    try:
        client = TestClient(create_app(services))
        _, owner = add_user(services)
        first = translate(client, owner, upload(client, owner))
        queue = make_queue(services)
        old = queue.claim("old-worker")
        assert old is not None
        assert client.post(f"/v1/jobs/{first['id']}/cancel", headers=owner).status_code == 200
        second = translate(client, owner, upload(client, owner))
        with services.db.session() as session:
            replacement = session.get(Job, second["id"])
            assert replacement is not None and replacement.shared_work_id != old.job_id
            new_work_id = replacement.shared_work_id
            assert session.scalars(select(SharedSlot)).one().active_work_id == new_work_id
        assert not queue.publish(
            old, Output("0" * 64, "1" * 64, [], None, "passed", {}), reuse=None
        )
        assert queue.cancelled(old)
        with services.db.session() as session:
            assert not list(
                session.scalars(
                    select(StorageReservation).where(StorageReservation.owner_id == old.job_id)
                )
            )
            assert list(
                session.scalars(
                    select(StorageReservation).where(StorageReservation.owner_id == new_work_id)
                )
            )
        assert make_worker(services, engines).run_once()
        assert client.get(f"/v1/jobs/{second['id']}", headers=owner).json()["status"] == "succeeded"
    finally:
        services.close()


def test_generation_change_fences_publication_even_with_interested_waiter(tmp_path: Path) -> None:
    engines = FakeEngines()
    services = make_services(automatic_settings(tmp_path), engines)
    try:
        client = TestClient(create_app(services))
        _, owner = add_user(services)
        translate(client, owner, upload(client, owner))
        queue = make_queue(services)
        attempt = queue.claim("worker")
        assert attempt is not None
        with services.db.session() as session:
            session.scalars(select(SharedSlot)).one().generation += 1
        assert not queue.publish(
            attempt, Output("0" * 64, "1" * 64, [], None, "passed", {}), reuse=None
        )
        with services.db.session() as session:
            work = session.get(Job, attempt.job_id)
            assert work is not None and work.status == "running"
            assert session.scalars(select(SharedSlot)).one().current_result_id is None
    finally:
        services.close()


def test_failed_upgrade_reports_the_reused_producer(tmp_path: Path) -> None:
    class LocalOnly(FakeEngines):
        def translate(self, mode: str, *args: Any, **kwargs: Any) -> Any:
            if mode != "hy-mt-local":
                raise EngineResponseError("remote model unavailable")
            return super().translate(mode, *args, **kwargs)

    engines = LocalOnly()
    services = make_services(automatic_settings(tmp_path), engines)
    try:
        client = TestClient(create_app(services))
        _, owner = add_user(services)
        translate(client, owner, upload(client, owner))
        assert make_worker(services, engines).run_once()
        cached = translate(client, owner, upload(client, owner))
        assert cached["cache_hit"] and cached["translator_id"] == "hy-mt-local"
        with services.db.session() as session:
            session.scalars(select(SharedSlot)).one().cooldowns = {}
        upgrade = translate(client, owner, upload(client, owner))
        assert make_worker(services, engines).run_once()
        result = client.get(f"/v1/jobs/{upgrade['id']}", headers=owner).json()
        assert result["status"] == "succeeded" and result["translator_id"] == "hy-mt-local"
        assert result["cache_hit"] and result["error_code"] is None
        assert engines.calls == 1
    finally:
        services.close()


def test_worker_recovery_does_not_restart_exhausted_model_rungs(tmp_path: Path) -> None:
    engines = FakeEngines()
    services = make_services(automatic_settings(tmp_path), engines)
    try:
        client = TestClient(create_app(services))
        _, owner = add_user(services)
        submitted = translate(client, owner, upload(client, owner))
        queue = make_queue(services)
        old = queue.claim("crashed-worker")
        assert old is not None
        with services.db.session() as session:
            work = session.get(Job, old.job_id)
            assert work is not None and work.policy is not None
            exhausted = len(work.policy["candidates"])
        queue.advance_rung(old, exhausted, "response", "failed-candidate")
        with services.db.session() as session:
            work = session.get(Job, old.job_id)
            assert work is not None
            work.lease_until = utcnow() - timedelta(seconds=1)
        assert queue.recover() == [(old.job_id, "requeued")]
        assert make_worker(services, engines, queue).run_once()
        result = client.get(f"/v1/jobs/{submitted['id']}", headers=owner).json()
        assert result["status"] == "failed"
        assert result["error_code"] == "translation_services_exhausted"
        assert engines.calls == 0
        assert not make_worker(services, engines, queue).run_once()
    finally:
        services.close()


@pytest.mark.parametrize("detected", [None, Language.EN])
def test_detection_runs_once_at_ingestion_and_never_on_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    detected: Language | None,
) -> None:
    from support.fakes import FakeTranslator, fake_translation

    calls = 0

    def detect(_: object) -> tuple[Language | None, list[Any]]:
        nonlocal calls
        calls += 1
        return detected, []

    monkeypatch.setattr("doctranslator_core.analysis.detect_source", detect)
    monkeypatch.setattr("doctranslator_core.pipeline.detect_source", detect)

    class FirstFails(FakeEngines):
        def translate(self, mode: str, *args: Any, **kwargs: Any) -> Any:
            def inference(text: str, target: Language) -> str:
                if mode == "gemma":
                    raise EngineResponseError("first inference rung fails")
                return fake_translation(text, target)

            self.translator = FakeTranslator(transform=inference)
            return super().translate(mode, *args, **kwargs)

    engines = FirstFails()
    services = make_services(automatic_settings(tmp_path), engines)
    try:
        client = TestClient(create_app(services))
        _, owner = add_user(services)
        job = translate(client, owner, upload(client, owner))
        assert calls == 1
        assert make_worker(services, engines).run_once()
        result = client.get(f"/v1/jobs/{job['id']}", headers=owner).json()
        assert result["status"] == "succeeded"
        assert engines.calls == 2
        assert calls == 1
    finally:
        services.close()


def test_multipart_replay_consumes_identical_fresh_upload(tmp_path: Path) -> None:
    from doctranslator_server.db.models import Document

    engines = FakeEngines()
    services = make_services(automatic_settings(tmp_path), engines)
    try:
        client = TestClient(create_app(services))
        _, owner = add_user(services)
        key = str(uuid.uuid4())
        data = dict(
            submission_id=key,
            options=json.dumps(
                dict(
                    target="en",
                    selection_policy="website_auto",
                    retention="cached",
                    download_semantics="current_shared",
                )
            ),
        )
        first = client.post(
            "/v1/jobs", headers=owner, files={"file": ("one.txt", b"Identical original")}, data=data
        )
        second = client.post(
            "/v1/jobs", headers=owner, files={"file": ("two.txt", b"Identical original")}, data=data
        )
        assert first.status_code in (200, 201, 202), first.text
        assert second.status_code in (200, 201, 202), second.text
        assert first.json()["id"] == second.json()["id"]
        with services.db.session() as session:
            assert len(list(session.scalars(select(Job).where(Job.kind == "shared_work")))) == 1
            assert not list(session.scalars(select(Document).where(Document.deleted_at.is_(None))))
        assert make_worker(services, engines).run_once()
        assert engines.calls == 1
    finally:
        services.close()


def test_global_queue_limit_allows_join_but_rejects_new_execution(tmp_path: Path) -> None:
    engines = FakeEngines()
    services = make_services(automatic_settings(tmp_path), engines)
    try:
        client = TestClient(create_app(services))
        _, owner = add_user(services)
        translate(client, owner, upload(client, owner))
        services.settings.max_queued_jobs = 1
        translate(client, owner, upload(client, owner))
        document = upload(client, owner, content=b"Different original")
        rejected = client.post(
            f"/v1/documents/{document}/translations",
            headers=owner,
            json=dict(
                target="en",
                selection_policy="website_auto",
                retention="cached",
                download_semantics="current_shared",
                submission_id=str(uuid.uuid4()),
            ),
        )
        assert rejected.status_code == 429 and rejected.json()["code"] == "queue_full"
        assert client.get(f"/v1/documents/{document}", headers=owner).status_code == 200
        assert make_worker(services, engines).run_once()
        cached = translate(client, owner, upload(client, owner))
        assert cached["cache_hit"]
    finally:
        services.close()


@pytest.mark.parametrize("resource", ["queue", "storage", "blob_pressure"])
def test_optional_upgrade_capacity_reuses_current(tmp_path: Path, resource: str) -> None:
    class LocalOnly(FakeEngines):
        def translate(self, mode: str, *args: Any, **kwargs: Any) -> Any:
            if mode != "hy-mt-local":
                raise EngineResponseError("remote unavailable")
            return super().translate(mode, *args, **kwargs)

    engines = LocalOnly()
    services = make_services(automatic_settings(tmp_path), engines)
    try:
        client = TestClient(create_app(services))
        _, owner = add_user(services)
        first = translate(client, owner, upload(client, owner))
        assert make_worker(services, engines).run_once()
        translate(client, owner, upload(client, owner, content=b"Other queued document"))
        with services.db.session() as session:
            slot = session.scalar(
                select(SharedSlot).where(SharedSlot.current_result_id.is_not(None))
            )
            assert slot is not None
            slot.cooldowns = {}
        document = upload(client, owner)
        if resource == "queue":
            services.settings.max_queued_jobs = 1
        elif resource == "storage":
            services.settings.global_work_budget_bytes = 1
        else:
            with services.db.session() as session:
                used = session.scalar(select(func.sum(Blob.size))) or 0
                pending = (
                    session.scalar(
                        select(func.sum(StorageReservation.bytes)).where(
                            StorageReservation.purpose != "work"
                        )
                    )
                    or 0
                )
            services.settings.global_blob_budget_bytes = int(used + pending)
        reused = translate(client, owner, document)
        assert reused["status"] == "succeeded" and reused["cache_hit"]
        assert reused["translator_id"] == "hy-mt-local"
        assert client.get(f"/v1/jobs/{first['id']}/file", headers=owner).status_code == 200
        assert engines.calls == 1
    finally:
        services.close()


def test_active_reservations_survive_expiry_and_backup_omits_original(tmp_path: Path) -> None:
    from doctranslator_server.app import build_services
    from doctranslator_server.db.models import JobResult
    from doctranslator_server.jobs import capacity
    from doctranslator_server.jobs.backup import backup, restore

    engines = FakeEngines()
    services = make_services(automatic_settings(tmp_path), engines)
    try:
        client = TestClient(create_app(services))
        _, owner = add_user(services)
        completed = translate(client, owner, upload(client, owner))
        assert make_worker(services, engines).run_once()
        active = translate(client, owner, upload(client, owner, content=b"Outstanding input"))
        with services.db.session() as session:
            slot = session.scalars(
                select(SharedSlot).where(SharedSlot.active_work_id.is_not(None))
            ).one()
            digest = slot.source_hash
            output_digest = session.scalars(select(JobResult)).one().output_blob
            original_reservations = list(session.scalars(select(StorageReservation)))
            identifiers = {r.id for r in original_reservations}
            assert len(identifiers) == 2
            for reservation in original_reservations:
                reservation.expires_at = utcnow() - timedelta(hours=1)
        run_retention(services.settings, services.db, services.store, holder="long-work")
        with services.db.session() as session:
            capacity.reserve(session, services.settings, "other-staging", "upload", 1)
            assert identifiers <= {r.id for r in session.scalars(select(StorageReservation))}
        destination = tmp_path / "snapshot"
        backup(services.db, services.store, destination, holder="snapshot")
        manifest = json.loads((destination / "manifest.json").read_text())
        assert digest not in manifest["blobs"]
        assert output_digest in manifest["blobs"]
        assert services.store.verify(digest)
        restored_path = tmp_path / "restored"
        restore(destination, restored_path)
        restored_settings = automatic_settings(tmp_path).model_copy(
            update={"data_dir": restored_path}
        )
        restored = build_services(restored_settings, catalog=engines)
        try:
            restored_client = TestClient(create_app(restored))
            assert (
                restored_client.get(f"/v1/jobs/{completed['id']}/file", headers=owner).status_code
                == 200
            )
            restored_active = restored_client.get(f"/v1/jobs/{active['id']}", headers=owner).json()
            assert restored_active["status"] == "failed"
            assert restored_active["error_code"] == "recovery_requires_upload"
        finally:
            restored.close()
        assert make_worker(services, engines).run_once()
    finally:
        services.close()


def test_batch_cancel_detaches_final_waiter_immediately(tmp_path: Path) -> None:
    engines = FakeEngines()
    services = make_services(automatic_settings(tmp_path), engines)
    try:
        client = TestClient(create_app(services))
        _, owner = add_user(services)
        batch = client.post(
            "/v1/batches", headers=owner, json={"idempotency_key": str(uuid.uuid4())}
        ).json()
        document = upload(client, owner)
        response = client.post(
            f"/v1/documents/{document}/translations",
            headers=owner,
            json=dict(
                target="en",
                selection_policy="website_auto",
                retention="cached",
                download_semantics="current_shared",
                batch_id=batch["id"],
                client_item_id=str(uuid.uuid4()),
            ),
        )
        assert response.status_code in (200, 201, 202), response.text
        cancelled = client.post(f"/v1/batches/{batch['id']}/cancel", headers=owner)
        assert cancelled.status_code == 200, cancelled.text
        with services.db.session() as session:
            work = session.scalars(select(Job).where(Job.kind == "shared_work")).one()
            assert work.status == "cancelled"
            assert session.scalars(select(SharedSlot)).one().active_work_id is None
            assert not list(session.scalars(select(StorageReservation)))
        assert not make_worker(services, engines).run_once()
    finally:
        services.close()


def test_corrupt_current_output_is_unavailable_in_job_reads(tmp_path: Path) -> None:
    from doctranslator_server.db.models import JobResult

    engines = FakeEngines()
    services = make_services(automatic_settings(tmp_path), engines)
    try:
        client = TestClient(create_app(services))
        _, owner = add_user(services)
        job = translate(client, owner, upload(client, owner))
        assert make_worker(services, engines).run_once()
        with services.db.session() as session:
            result = session.scalars(select(JobResult)).one()
            services.store.path(result.output_blob).write_bytes(b"corrupted")
        assert not client.get(f"/v1/jobs/{job['id']}", headers=owner).json()["result_available"]
        jobs = client.get("/v1/jobs", headers=owner).json()["items"]
        assert not next(item for item in jobs if item["id"] == job["id"])["result_available"]
        assert client.get(f"/v1/jobs/{job['id']}/file", headers=owner).status_code == 410
    finally:
        services.close()


def test_verified_upload_repairs_active_original_before_joining(tmp_path: Path) -> None:
    engines = FakeEngines()
    services = make_services(automatic_settings(tmp_path), engines)
    try:
        client = TestClient(create_app(services))
        _, owner = add_user(services)
        first = translate(client, owner, upload(client, owner))
        with services.db.session() as session:
            digest = session.scalars(select(SharedSlot)).one().source_hash
        services.store.path(digest).write_bytes(b"damaged active input")
        second = translate(client, owner, upload(client, owner))
        assert services.store.verify(digest)
        assert make_worker(services, engines).run_once()
        assert engines.calls == 1
        for job in (first, second):
            assert client.get(f"/v1/jobs/{job['id']}/file", headers=owner).status_code == 200
    finally:
        services.close()


@pytest.mark.parametrize("malformed", ["model", "order"])
def test_invalid_approved_policy_is_a_configuration_error(tmp_path: Path, malformed: str) -> None:
    settings = automatic_settings(tmp_path)
    if malformed == "model":
        entry = settings.translators[1]
        settings.translators = [
            item.model_copy(
                update={
                    "engine": entry.engine.model_copy(update={"model": "unapproved-substitution"})
                }
            )
            if item.id == entry.id
            else item
            for item in settings.translators
        ]
    else:
        settings.web_translation_policy = dict(
            settings.web_translation_policy, davy_order=["gemma"]
        )
    engines = FakeEngines()
    services = make_services(settings, engines)
    try:
        client = TestClient(create_app(services))
        _, owner = add_user(services)
        document = upload(client, owner)
        response = client.post(
            f"/v1/documents/{document}/translations",
            headers=owner,
            json=dict(
                target="en",
                selection_policy="website_auto",
                retention="cached",
                download_semantics="current_shared",
                submission_id=str(uuid.uuid4()),
            ),
        )
        assert response.status_code == 422 and response.json()["code"] == "policy_configuration"
        assert engines.calls == 0
        assert client.get(f"/v1/documents/{document}", headers=owner).status_code == 200
    finally:
        services.close()


def test_policy_revision_and_order_are_pinned_in_digest(tmp_path: Path) -> None:
    from doctranslator_core.types import DocumentTranslationOptions
    from doctranslator_server.jobs.automatic import pinned_policy

    settings = automatic_settings(tmp_path)
    options = DocumentTranslationOptions(target=Language.EN)
    engines = FakeEngines()
    first = pinned_policy(settings, engines, options)
    policy = dict(settings.web_translation_policy)
    settings.web_translation_policy = dict(policy, revision="reviewed-order-v3")
    revised = pinned_policy(settings, engines, options)
    settings.web_translation_policy = dict(policy, davy_order=list(reversed(policy["davy_order"])))
    reordered = pinned_policy(settings, engines, options)
    assert len({first["digest"], revised["digest"], reordered["digest"]}) == 3
    assert first["candidates"][0]["id"] == "gemma"
    assert reordered["candidates"][0]["id"] == "laguna-s-2.1"


@pytest.mark.parametrize("available", [{"nemotron-3-ultra"}, set[str]()])
def test_custom_runner_discovery_skips_missing_models_without_inference(
    tmp_path: Path, available: set[str]
) -> None:
    engines = FakeEngines()
    engines.available_translators = available
    services = make_services(automatic_settings(tmp_path), engines)
    try:
        client = TestClient(create_app(services))
        _, owner = add_user(services)
        job = translate(client, owner, upload(client, owner))
        assert engines.discovery_calls == 0
        assert make_worker(services, engines).run_once()
        result = client.get(f"/v1/jobs/{job['id']}", headers=owner).json()
        assert engines.discovery_calls == 1
        if available:
            assert result["status"] == "succeeded"
            assert result["translator_id"] == "nemotron-3-ultra"
            assert engines.calls == 1
        else:
            assert result["status"] == "failed"
            assert result["error_code"] == "translation_services_exhausted"
            assert engines.calls == 0
    finally:
        services.close()


def test_cached_output_never_calls_runner_discovery(tmp_path: Path) -> None:
    engines = FakeEngines()
    engines.available_translators = {"gemma"}
    services = make_services(automatic_settings(tmp_path), engines)
    try:
        client = TestClient(create_app(services))
        _, owner = add_user(services)
        translate(client, owner, upload(client, owner))
        assert make_worker(services, engines).run_once()
        assert engines.discovery_calls == 1
        engines.available_translators = set()
        cached = translate(client, owner, upload(client, owner))
        assert cached["status"] == "succeeded" and cached["cache_hit"]
        assert not make_worker(services, engines).run_once()
        assert engines.discovery_calls == 1 and engines.calls == 1
    finally:
        services.close()


def test_desktop_runner_discovery_exhausts_absent_models_without_loading(tmp_path: Path) -> None:
    from doctranslator_server.jobs.desktop_runner import DesktopRunner
    from doctranslator_server.jobs.engines import EngineCatalog
    from doctranslator_server.jobs.worker import Worker

    engines = FakeEngines()
    services = make_services(automatic_settings(tmp_path), engines)
    try:
        client = TestClient(create_app(services))
        _, owner = add_user(services)
        job = translate(client, owner, upload(client, owner))
        # The discovery fixture advertises mt/llm, neither of the pinned automatic IDs.
        # It deliberately has no translator-loading method: none may be called here.
        runner = DesktopRunner(cast(EngineCatalog, engines), None)
        worker = Worker(
            services.settings, services.db, services.store, make_queue(services), runner
        )
        assert worker.run_once()
        result = client.get(f"/v1/jobs/{job['id']}", headers=owner).json()
        assert result["status"] == "failed"
        assert result["error_code"] == "translation_services_exhausted"
        assert engines.calls == 0
    finally:
        services.close()


@pytest.mark.parametrize("revocation", ["deleted", "expired"])
def test_fresh_upload_cannot_resurrect_revoked_history_or_job_urls(
    tmp_path: Path, revocation: str
) -> None:
    from doctranslator_server.db.models import HistoryGrant

    engines = FakeEngines()
    services = make_services(automatic_settings(tmp_path), engines)
    try:
        client = TestClient(create_app(services))
        _, owner = add_user(services)
        first = translate(client, owner, upload(client, owner))
        assert make_worker(services, engines).run_once()
        old_history = client.get("/v1/history", headers=owner).json()["items"][0]["id"]
        if revocation == "deleted":
            assert client.delete(f"/v1/history/{old_history}", headers=owner).status_code == 204
        else:
            with services.db.session() as session:
                grant = session.get(HistoryGrant, old_history)
                assert grant is not None
                grant.updated_at = utcnow() - timedelta(days=91)
        assert client.get(f"/v1/history/{old_history}/file", headers=owner).status_code == 404
        second = translate(client, owner, upload(client, owner))
        assert second["status"] == "succeeded" and second["cache_hit"]
        history = client.get("/v1/history", headers=owner).json()["items"]
        assert len(history) == 1 and history[0]["id"] != old_history
        assert client.get(f"/v1/history/{old_history}/file", headers=owner).status_code == 404
        assert client.get(f"/v1/jobs/{first['id']}/file", headers=owner).status_code == 404
        assert client.get(f"/v1/jobs/{second['id']}/file", headers=owner).status_code == 200
    finally:
        services.close()


@pytest.mark.parametrize("state", ["deleted", "expired", "retained", "recently_deleted"])
def test_retention_purges_only_old_revoked_grants_and_unowned_empty_slots(
    tmp_path: Path, state: str
) -> None:
    from doctranslator_server.db.models import HistoryGrant

    engines = FakeEngines()
    services = make_services(automatic_settings(tmp_path), engines)
    try:
        client = TestClient(create_app(services))
        _, owner = add_user(services)
        job = translate(client, owner, upload(client, owner))
        assert make_worker(services, engines).run_once()
        with services.db.session() as session:
            grant = session.scalars(select(HistoryGrant)).one()
            grant_id, slot_id = grant.id, grant.slot_id
            if state == "deleted":
                grant.deleted_at = utcnow() - timedelta(
                    days=services.settings.job_retention_days + 1
                )
            elif state == "recently_deleted":
                grant.deleted_at = utcnow()
            elif state == "expired":
                grant.updated_at = utcnow() - timedelta(
                    days=90 + services.settings.job_retention_days + 1
                )
            slot = session.get(SharedSlot, slot_id)
            assert slot is not None
            slot.last_used_at = utcnow() - timedelta(
                days=max(31, services.settings.job_retention_days + 1)
            )
        run_retention(services.settings, services.db, services.store, holder="metadata-cleanup")
        with services.db.session() as session:
            if state in ("retained", "recently_deleted"):
                assert session.get(HistoryGrant, grant_id) is not None
                slot = session.get(SharedSlot, slot_id)
                assert slot is not None and slot.current_result_id is None
            else:
                assert session.get(HistoryGrant, grant_id) is None
                assert session.get(SharedSlot, slot_id) is None
        file = client.get(f"/v1/jobs/{job['id']}/file", headers=owner)
        assert file.status_code == (410 if state == "retained" else 404)
    finally:
        services.close()


def test_replacing_expired_grant_detaches_its_pending_waiter(tmp_path: Path) -> None:
    from doctranslator_server.db.models import HistoryGrant

    engines = FakeEngines()
    services = make_services(automatic_settings(tmp_path), engines)
    try:
        client = TestClient(create_app(services))
        _, owner = add_user(services)
        first = translate(client, owner, upload(client, owner))
        with services.db.session() as session:
            session.scalars(select(HistoryGrant)).one().updated_at = utcnow() - timedelta(days=91)
        second = translate(client, owner, upload(client, owner))
        assert client.get(f"/v1/jobs/{first['id']}", headers=owner).json()["status"] == "cancelled"
        assert make_worker(services, engines).run_once()
        assert client.get(f"/v1/jobs/{first['id']}/file", headers=owner).status_code == 404
        assert client.get(f"/v1/jobs/{second['id']}/file", headers=owner).status_code == 200
        assert engines.calls == 1
    finally:
        services.close()
