"""Blob pins, reference-safe cleanup, retention and backup/restore (ADR-007, ADR-016)."""

import hashlib
import uuid
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from support.server import FakeEngines, add_user, make_services, make_worker, server_settings

from doctranslator_server.app import Services, build_services, create_app
from doctranslator_server.db.models import utcnow
from doctranslator_server.jobs.backup import BackupError, backup, restore
from doctranslator_server.jobs.retention import run_retention

TXT = "这是一个用于测试的中文段落，内容足够长以便识别语言。\n".encode()


@pytest.fixture
def engines() -> FakeEngines:
    return FakeEngines()


@pytest.fixture
def services(tmp_path: Path, engines: FakeEngines) -> Iterator[Services]:
    services = make_services(server_settings(tmp_path), engines)
    yield services
    services.close()


def translated(services: Services, engines: FakeEngines, headers: dict[str, str]) -> str:
    client = TestClient(create_app(services))
    job = client.post(
        "/v1/jobs",
        headers=headers,
        files={"file": ("notes.txt", TXT)},
        data={"options": '{"target": "en", "mode": "mt"}', "submission_id": str(uuid.uuid4())},
    ).json()
    make_worker(services, engines).run_once()
    return str(client.get(f"/v1/jobs/{job['id']}", headers=headers).json()["document_id"])


def blob_files(services: Services) -> set[str]:
    return {p.name for p in (services.settings.data_dir / "blobs").rglob("*") if p.is_file()}


def test_a_pinned_blob_survives_cleanup_until_it_is_referenced(services: Services) -> None:
    staged = services.store.stage([b"payload"], max_bytes=100)
    stored = services.store.put(staged)
    assert services.store.collect(holder="t", pending_grace=timedelta(0)) == 0
    assert stored.sha256 in blob_files(services)
    services.store.release_pins([stored.pin_id])
    assert services.store.collect(holder="t", pending_grace=timedelta(0)) == 1
    assert stored.sha256 not in blob_files(services)
    # Re-putting deleted content works and is complete.
    again = services.store.put(services.store.stage([b"payload"], max_bytes=100))
    assert services.store.verify(again.sha256)


def test_cleanup_keeps_everything_a_document_references(
    services: Services, engines: FakeEngines
) -> None:
    _, headers = add_user(services)
    translated(services, engines, headers)
    before = blob_files(services)
    assert len(before) == 3  # original, output, report
    assert services.store.collect(holder="t", pending_grace=timedelta(0)) == 0
    assert blob_files(services) == before


def test_cache_expiry_never_removes_a_users_result(tmp_path: Path, engines: FakeEngines) -> None:
    settings = server_settings(tmp_path, cache_retention_days=1)
    services = make_services(settings, engines)
    try:
        _, headers = add_user(services)
        document = translated(services, engines, headers)
        with services.db.session() as session:
            from doctranslator_server.db.models import TranslationResult

            for row in session.query(TranslationResult):
                row.last_used_at = utcnow() - timedelta(days=5)
        report = run_retention(settings, services.db, services.store, holder="t")
        assert report.cache_entries == 1 and report.blobs == 0
        client = TestClient(create_app(services))
        file = client.get(f"/v1/documents/{document}/versions/0/file", headers=headers)
        assert file.status_code == 200
        assert hashlib.sha256(file.content).hexdigest() == file.headers["x-content-sha256"]
    finally:
        services.close()


def test_deleted_and_expired_documents_free_their_blobs(
    services: Services, engines: FakeEngines
) -> None:
    _, headers = add_user(services)
    document = translated(services, engines, headers)
    client = TestClient(create_app(services))
    assert client.delete(f"/v1/documents/{document}", headers=headers).status_code == 204
    report = run_retention(services.settings, services.db, services.store, holder="t")
    # The cache row still references output and report; the job references the original.
    assert report.blobs == 0 and len(blob_files(services)) == 3
    with services.db.session() as session:
        from doctranslator_server.db.models import Job, TranslationResult

        for row in session.query(TranslationResult):
            row.last_used_at = utcnow() - timedelta(days=365)
        for job in session.query(Job):
            job.finished_at = utcnow() - timedelta(days=365)
    report = run_retention(services.settings, services.db, services.store, holder="t")
    assert (report.cache_entries, report.jobs, report.blobs) == (1, 1, 3)
    assert blob_files(services) == set()


def test_gc_lock_blocks_cleanup_during_backup(services: Services, tmp_path: Path) -> None:
    from doctranslator_server.db.repositories import users as locks

    with services.db.session() as session:
        assert locks.acquire_lock(
            session, "gc", "backup", utcnow() + timedelta(minutes=5), utcnow()
        )
    stored = services.store.put(services.store.stage([b"x"], max_bytes=10))
    services.store.release_pins([stored.pin_id])
    assert services.store.collect(holder="retention", pending_grace=timedelta(0)) == 0
    assert stored.sha256 in blob_files(services)


def test_backup_and_restore_round_trip(
    services: Services, engines: FakeEngines, tmp_path: Path
) -> None:
    _, headers = add_user(services)
    document = translated(services, engines, headers)
    client = TestClient(create_app(services))
    original = client.get(f"/v1/documents/{document}/versions/0/file", headers=headers).content
    destination = tmp_path / "backup"
    summary = backup(services.db, services.store, destination, holder="b")
    assert summary.blobs == 3 and summary.revision == "0001"
    with pytest.raises(BackupError, match="empty"):
        backup(services.db, services.store, destination, holder="b")

    restored_dir = tmp_path / "restored"
    restored = restore(destination, restored_dir)
    assert restored.blobs == 3
    with pytest.raises(BackupError, match="already has a database"):
        restore(destination, restored_dir)
    settings = server_settings(tmp_path, data_dir=restored_dir)
    again = build_services(settings, catalog=engines)
    try:
        client = TestClient(create_app(again))
        file = client.get(f"/v1/documents/{document}/versions/0/file", headers=headers)
        assert file.status_code == 200 and file.content == original
    finally:
        again.close()


def test_restore_rejects_a_damaged_backup(
    services: Services, engines: FakeEngines, tmp_path: Path
) -> None:
    _, headers = add_user(services)
    translated(services, engines, headers)
    destination = tmp_path / "backup"
    backup(services.db, services.store, destination, holder="b")
    victim = next(p for p in (destination / "blobs").rglob("*") if p.is_file())
    victim.write_bytes(b"tampered")
    with pytest.raises(BackupError, match="damaged"):
        restore(destination, tmp_path / "restored")
    assert not (tmp_path / "restored" / "doctranslator.db").exists()
