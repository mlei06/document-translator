"""Blob pins, reference-safe cleanup, retention and backup/restore (ADR-007, ADR-016)."""

import hashlib
import json
import uuid
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from support.server import FakeEngines, add_user, make_services, make_worker, server_settings

from doctranslator_server.app import Services, build_services, create_app
from doctranslator_server.db.models import Job, JobResult, utcnow
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


def translated(
    services: Services, engines: FakeEngines, headers: dict[str, str], force: bool = False
) -> str:
    """Translate TXT into the owner's library; returns the job ID."""
    client = TestClient(create_app(services))
    job = client.post(
        "/v1/jobs",
        headers=headers,
        files={"file": ("notes.txt", TXT)},
        data={
            "options": json.dumps({"target": "en", "mode": "mt", "force_retranslate": force}),
            "submission_id": str(uuid.uuid4()),
        },
    ).json()
    make_worker(services, engines).run_once()
    return str(job["id"])


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
    assert len(before) == 4  # original, output, report, preview
    assert services.store.collect(holder="t", pending_grace=timedelta(0)) == 0
    assert blob_files(services) == before


def test_superseded_results_serve_their_jobs_until_they_expire(
    services: Services, engines: FakeEngines
) -> None:
    _, headers = add_user(services)
    first = translated(services, engines, headers)
    second = translated(services, engines, headers, force=True)
    client = TestClient(create_app(services))
    old = client.get(f"/v1/jobs/{first}/file", headers=headers)
    assert old.status_code == 200
    assert run_retention(services.settings, services.db, services.store, holder="t").results == 0
    with services.db.session() as session:
        for row in session.query(JobResult).filter(JobResult.expires_at.is_not(None)):
            row.expires_at = utcnow() - timedelta(seconds=1)
    report = run_retention(services.settings, services.db, services.store, holder="t")
    assert report.results == 1
    assert client.get(f"/v1/jobs/{first}/file", headers=headers).status_code == 404
    current = client.get(f"/v1/jobs/{second}/file", headers=headers)
    assert current.status_code == 200
    assert hashlib.sha256(current.content).hexdigest() == current.headers["x-content-sha256"]


def test_deleted_documents_free_their_blobs_after_metadata_retention(
    services: Services, engines: FakeEngines
) -> None:
    _, headers = add_user(services)
    job_id = translated(services, engines, headers)
    client = TestClient(create_app(services))
    document = client.get(f"/v1/jobs/{job_id}", headers=headers).json()["document_id"]
    assert client.delete(f"/v1/documents/{document}", headers=headers).status_code == 204
    report = run_retention(services.settings, services.db, services.store, holder="t")
    # The result is gone at once; the job (30-day metadata) still names the original bytes.
    assert report.results == 1 and len(blob_files(services)) == 1
    with services.db.session() as session:
        for job in session.query(Job):
            job.finished_at = utcnow() - timedelta(days=365)
    report = run_retention(services.settings, services.db, services.store, holder="t")
    assert report.jobs == 1 and blob_files(services) == set()


def test_saved_documents_never_expire(services: Services, engines: FakeEngines) -> None:
    _, headers = add_user(services)
    job_id = translated(services, engines, headers)
    with services.db.session() as session:
        for job in session.query(Job):
            job.finished_at = utcnow() - timedelta(days=3650)
    run_retention(services.settings, services.db, services.store, holder="t")
    client = TestClient(create_app(services))
    assert client.get(f"/v1/jobs/{job_id}/file", headers=headers).status_code == 200


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
    job_id = translated(services, engines, headers)
    client = TestClient(create_app(services))
    original = client.get(f"/v1/jobs/{job_id}/file", headers=headers).content
    destination = tmp_path / "backup"
    summary = backup(services.db, services.store, destination, holder="b")
    assert summary.blobs == 4 and summary.revision == "0002"
    with pytest.raises(BackupError, match="empty"):
        backup(services.db, services.store, destination, holder="b")

    restored_dir = tmp_path / "restored"
    restored = restore(destination, restored_dir)
    assert restored.blobs == 4
    with pytest.raises(BackupError, match="already has a database"):
        restore(destination, restored_dir)
    settings = server_settings(tmp_path, data_dir=restored_dir)
    again = build_services(settings, catalog=engines)
    try:
        client = TestClient(create_app(again))
        file = client.get(f"/v1/jobs/{job_id}/file", headers=headers)
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
