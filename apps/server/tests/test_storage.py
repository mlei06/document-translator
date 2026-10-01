"""Blob pins, reference-safe cleanup, retention and backup/restore (ADR-007, ADR-016)."""

import hashlib
import json
import os
import time
import uuid
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from support.server import FakeEngines, add_user, make_services, make_worker, server_settings

from doctranslator_server.app import Services, build_services, create_app
from doctranslator_server.db.models import Job, JobResult, utcnow
from doctranslator_server.jobs.backup import BackupError, backup, restore
from doctranslator_server.jobs.retention import run_retention

TXT = "这是一个用于测试的中文段落，内容足够长以便识别语言。\n".encode()


def test_unreadable_result_returns_unavailable_instead_of_server_error(
    services: Services, engines: FakeEngines
) -> None:
    _, headers = add_user(services)
    job_id = translated(services, engines, headers)
    client = TestClient(create_app(services))
    with patch.object(Path, "open", side_effect=PermissionError("file locked")):
        response = client.get(f"/v1/jobs/{job_id}/file", headers=headers)
    assert response.status_code == 410
    assert response.json()["code"] == "translation_unavailable"


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


def test_retention_keeps_live_work_until_translation_finishes(
    services: Services, engines: FakeEngines
) -> None:
    """A user translation must survive cleanup even after a long model call."""
    _, headers = add_user(services)
    stale = services.settings.data_dir / "work" / "abandoned-attempt"
    stale.mkdir(parents=True)
    (stale / "input.txt").write_text("abandoned", encoding="utf-8")
    old = time.time() - (services.settings.staging_retention_hours + 1) * 3600
    os.utime(stale, (old, old))

    def during_translation(_mode: object, source: Path) -> None:
        # Simulate a long-running worker while retaining its actual live DB claim.
        os.utime(source.parent, (old, old))
        run_retention(services.settings, services.db, services.store, holder="during-work")
        assert source.exists(), "retention removed input belonging to a running attempt"
        assert not stale.exists(), "abandoned working files still need cleanup"

    engines.before = during_translation
    job_id = translated(services, engines, headers)
    client = TestClient(create_app(services))
    assert client.get(f"/v1/jobs/{job_id}", headers=headers).json()["status"] == "succeeded"
    assert client.get(f"/v1/jobs/{job_id}/file", headers=headers).status_code == 200


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
    assert len(before) == 3  # retained legacy source, output and report; no preview
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
    assert summary.blobs == 3 and summary.revision == "0007"
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


def test_verified_reupload_repairs_corrupt_blob(services: Services) -> None:
    payload = b"verified original bytes"
    first = services.store.put(services.store.stage([payload], max_bytes=100))
    services.store.path(first.sha256).write_bytes(b"corrupted stored bytes")
    assert not services.store.verify(first.sha256)
    repaired = services.store.put(services.store.stage([payload], max_bytes=100))
    assert repaired.sha256 == first.sha256
    assert services.store.verify(repaired.sha256)
    assert services.store.path(repaired.sha256).read_bytes() == payload


def test_failed_blob_deletion_remains_charged_and_retries(
    services: Services, monkeypatch: pytest.MonkeyPatch
) -> None:
    from doctranslator_server.db.models import Blob

    stored = services.store.put(services.store.stage([b"unreferenced"], max_bytes=100))
    services.store.release_pins([stored.pin_id])
    victim = services.store.path(stored.sha256)
    unlink = Path.unlink

    def locked(path: Path, *args: object, **kwargs: object) -> None:
        if path == victim:
            raise PermissionError("file held by another process")
        unlink(path, *args, **kwargs)  # type: ignore[arg-type]

    with monkeypatch.context() as patch:
        patch.setattr(Path, "unlink", locked)
        assert services.store.collect(holder="locked", pending_grace=timedelta(0)) == 0
    with services.db.session() as session:
        blob = session.get(Blob, stored.sha256)
        assert blob is not None and blob.size == len(b"unreferenced")
    assert victim.exists()
    assert services.store.collect(holder="retry", pending_grace=timedelta(0)) == 1
    assert not victim.exists()


def test_failed_corrupt_blob_repair_does_not_report_success(
    services: Services, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b"original bytes"
    stored = services.store.put(services.store.stage([payload], max_bytes=100))
    services.store.path(stored.sha256).write_bytes(b"damaged")
    staged = services.store.stage([payload], max_bytes=100)
    replace = Path.replace

    def locked(path: Path, target: Path) -> Path:
        if path == staged.path:
            raise PermissionError("cannot replace locked corrupt file")
        return replace(path, target)

    monkeypatch.setattr(Path, "replace", locked)
    with pytest.raises(PermissionError):
        services.store.put(staged)
    assert not services.store.verify(stored.sha256)


def test_daily_backup_serializes_the_entire_workflow_and_releases_failed_lease(
    services: Services, monkeypatch: pytest.MonkeyPatch
) -> None:
    from doctranslator_server.jobs import backup as recovery

    original = recovery.backup
    calls = 0

    def simultaneous(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        # Simulate another supervisor entering after this run creates its pending tree.
        recovery.daily_backup(services.settings, services.db, services.store)
        assert calls == 1
        raise BackupError("simulated interrupted copy")

    with monkeypatch.context() as patch:
        patch.setattr(recovery, "backup", simultaneous)
        with pytest.raises(BackupError, match="interrupted"):
            recovery.daily_backup(services.settings, services.db, services.store)
    assert recovery.backup is original
    recovery.daily_backup(services.settings, services.db, services.store)
    points = list((services.settings.data_dir / "backups").glob("*/manifest.json"))
    assert len(points) == 1
