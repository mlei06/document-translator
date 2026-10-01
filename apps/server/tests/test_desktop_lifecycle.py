"""Desktop capability changes and export cleanup through the shared job service."""

import io
import threading
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from typing import Any, NoReturn

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from support.server import FakeEngines, add_user, make_services, make_worker, server_settings

from doctranslator_core import AutomaticTranslationPolicy
from doctranslator_core.types import DocumentError
from doctranslator_server.app import Services
from doctranslator_server.db.models import Job, JobResult, StorageReservation, utcnow
from doctranslator_server.desktop_api import install as install_desktop
from doctranslator_server.jobs.desktop_journal import ExportJournal
from doctranslator_server.jobs.desktop_offline import OfflineSupport
from doctranslator_server.jobs.errors import ConflictError, InvalidRequestError
from doctranslator_server.jobs.retention import run_retention
from doctranslator_server.jobs.service import SubmitOptions
from doctranslator_server.jobs.views import JobView


@pytest.fixture
def desktop(tmp_path: Path) -> Iterator[tuple[Services, FakeEngines, str]]:
    settings = server_settings(
        tmp_path / "managed",
        translators=[
            dict(
                id="gemma",
                label="Gemma",
                engine=dict(
                    mode="llm",
                    model="gemma-4-31b-it",
                    api_key="synthetic-test-only",
                    base_url="https://approved.example/v1",
                ),
            )
        ],
        default_translator_id="gemma",
        web_translation_policy=AutomaticTranslationPolicy(local_translator_id=None).model_dump(),
    )
    engines = FakeEngines()
    services = make_services(settings, engines)
    owner, _ = add_user(services)
    try:
        yield services, engines, owner
    finally:
        services.close()


def submit(services: Services, owner: str) -> JobView:
    accepted = services.jobs.submit(
        owner,
        "original.txt",
        io.BytesIO(b"Original document remains user owned."),
        SubmitOptions(target="en", retention="temporary", selection_policy="desktop_auto"),
        submission_id=str(uuid.uuid4()),
    ).job
    assert accepted is not None
    return accepted


@pytest.mark.parametrize("terminal", ["succeeded", "cancelled"])
def test_offline_setup_ignores_completed_undismissed_activity(
    desktop: tuple[Services, FakeEngines, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    terminal: str,
) -> None:
    services, engines, owner = desktop
    offline = OfflineSupport(tmp_path / "models", tmp_path / "application")
    scheduled: list[bool] = []
    monkeypatch.setattr(offline, "manifest", lambda: None)
    monkeypatch.setattr(offline, "setup", lambda *, repair=False: scheduled.append(repair))
    app = FastAPI()
    install_desktop(app, services.jobs, owner, tmp_path / "metadata", offline)
    job = submit(services, owner)
    with TestClient(app) as client:
        assert client.post("/v1/desktop/offline/install").status_code == 409
        if terminal == "succeeded":
            make_worker(services, engines).run_once()
        else:
            services.jobs.cancel_job(owner, job.id)
        assert services.jobs.get_job(owner, job.id).status == terminal
        assert services.jobs.list_jobs(owner, None, 1, active=True).items
        response = client.post("/v1/desktop/offline/install")
        assert response.status_code == 200, response.text
        assert scheduled == [False]


def test_capability_change_requires_idle_and_keeps_accepted_identity(
    desktop: tuple[Services, FakeEngines, str], tmp_path: Path
) -> None:
    services, _, owner = desktop
    accepted = submit(services, owner)
    replacement = FakeEngines(version="next-capability")
    with pytest.raises(ConflictError, match="current translations"):
        services.jobs.reconfigure_desktop_catalog(services.settings, replacement)
    assert services.jobs.get_job(owner, accepted.id).fingerprint == accepted.fingerprint
    services.jobs.cancel_job(owner, accepted.id)
    services.jobs.reconfigure_desktop_catalog(services.settings, replacement)
    next_job = submit(services, owner)
    assert next_job.fingerprint != accepted.fingerprint
    assert services.jobs.get_job(owner, accepted.id).fingerprint == accepted.fingerprint
    with pytest.raises(InvalidRequestError, match="data directory"):
        services.jobs.reconfigure_desktop_catalog(
            services.settings.model_copy(update={"data_dir": tmp_path / "unrelated"}), replacement
        )


def test_export_replay_releases_managed_bytes_and_preserves_user_files(
    desktop: tuple[Services, FakeEngines, str], tmp_path: Path
) -> None:
    services, engines, owner = desktop
    source = tmp_path / "Original user file.txt"
    original = b"Original document remains user owned."
    source.write_bytes(original)
    job = submit(services, owner)
    with services.db.session() as session:
        row = session.get(Job, job.id)
        assert row is not None
        input_hash = row.input_blob
        assert len(list(session.scalars(select(StorageReservation)))) == 2
    make_worker(services, engines).run_once()
    assert not services.store.path(input_hash).exists()
    with services.db.session() as session:
        row = session.get(Job, job.id)
        assert row is not None and row.result_id is not None
        result = session.get(JobResult, row.result_id)
        assert result is not None
        output_hash, report_hash = result.output_blob, result.report_blob
        assert not list(session.scalars(select(StorageReservation)))
    journal = ExportJournal(tmp_path / "journal", services.jobs, owner)
    journal.record(job.id, source, source.parent)
    output = journal.export(job.id)
    assert output.is_file() and output != source
    assert source.read_bytes() == original
    assert not services.store.path(output_hash).exists()
    assert not services.store.path(report_hash).exists()
    assert journal.export(job.id) == output
    assert len(list(tmp_path.glob("Original user file.en*.txt"))) == 1
    assert services.jobs.get_job(owner, job.id).status == "succeeded"
    assert not services.jobs.get_job(owner, job.id).result_available
    output.write_text("User edited the exported document", encoding="utf-8")
    with pytest.raises(FileNotFoundError, match="missing or changed"):
        journal.export(job.id)
    assert output.read_text(encoding="utf-8") == "User edited the exported document"


def test_explicit_internal_temporary_retention_is_not_desktop_cleanup(
    desktop: tuple[Services, FakeEngines, str],
) -> None:
    services, engines, owner = desktop
    accepted = services.jobs.submit(
        owner,
        "internal.txt",
        io.BytesIO(b"Internal application document."),
        SubmitOptions(target="en", mode="mt", retention="temporary"),
        submission_id=str(uuid.uuid4()),
    ).job
    assert accepted is not None
    make_worker(services, engines).run_once()
    with services.db.session() as session:
        row = session.get(Job, accepted.id)
        assert row is not None
        row.policy = None
        input_hash = row.input_blob
    with pytest.raises(InvalidRequestError, match="not a desktop"):
        services.jobs.release_desktop_result(owner, accepted.id)
    services.store.sweep_capacity()
    assert services.store.path(input_hash).exists()
    assert services.jobs.get_job(owner, accepted.id).result_available


@pytest.mark.parametrize("terminal", ["cancelled", "failed"])
def test_terminal_desktop_work_releases_originals_and_reservations(
    desktop: tuple[Services, FakeEngines, str], monkeypatch: pytest.MonkeyPatch, terminal: str
) -> None:
    services, engines, owner = desktop
    job = submit(services, owner)
    with services.db.session() as session:
        row = session.get(Job, job.id)
        assert row is not None
        input_hash = row.input_blob
    if terminal == "cancelled":
        services.jobs.cancel_job(owner, job.id)
    else:

        def fail(*_args: object, **_kwargs: object) -> NoReturn:
            raise DocumentError("Document cannot be safely written")

        monkeypatch.setattr(engines, "translate", fail)
        make_worker(services, engines).run_once()
    assert services.jobs.get_job(owner, job.id).status == terminal
    assert not services.store.path(input_hash).exists()
    with services.db.session() as session:
        assert not list(session.scalars(select(StorageReservation)))


@pytest.mark.parametrize("queue_limit", [1, 1000])
def test_concurrent_desktop_submission_replays_before_capacity(
    desktop: tuple[Services, FakeEngines, str], monkeypatch: pytest.MonkeyPatch, queue_limit: int
) -> None:
    services, _, owner = desktop
    key = str(uuid.uuid4())
    barrier = threading.Barrier(2)
    original = services.jobs._replay  # pyright: ignore[reportPrivateUsage]

    def synchronized(*args: Any, **kwargs: Any) -> Any:
        result = original(*args, **kwargs)
        if result is None:
            barrier.wait(timeout=20)
        return result

    monkeypatch.setattr(services.jobs, "_replay", synchronized)
    services.settings.max_queued_jobs = queue_limit

    def send(_: int) -> Any:
        return services.jobs.submit(
            owner,
            "original.txt",
            io.BytesIO(b"Same verified bytes"),
            SubmitOptions(target="en", retention="temporary", selection_policy="desktop_auto"),
            submission_id=key,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(send, range(2)))
    assert results[0].job.id == results[1].job.id
    assert sorted(result.replayed for result in results) == [False, True]
    with services.db.session() as session:
        assert len(list(session.scalars(select(Job)))) == 1
        assert len(list(session.scalars(select(StorageReservation)))) == 2
    with pytest.raises(ConflictError) as mismatch:
        services.jobs.submit(
            owner,
            "different.txt",
            io.BytesIO(b"Different bytes"),
            SubmitOptions(target="en", retention="temporary", selection_policy="desktop_auto"),
            submission_id=key,
        )
    assert mismatch.value.code == "idempotency_mismatch"


def test_completed_journal_prunes_expired_job_but_preserves_user_export(
    desktop: tuple[Services, FakeEngines, str], tmp_path: Path
) -> None:
    services, engines, owner = desktop
    source = tmp_path / "User original.txt"
    source.write_bytes(b"Original document remains user owned.")
    job = submit(services, owner)
    assert make_worker(services, engines).run_once()
    journal = ExportJournal(tmp_path / "journal", services.jobs, owner)
    journal.record(job.id, source, source.parent)
    exported = journal.export(job.id)
    exported.write_bytes(b"User edited exported translation")
    with services.db.session() as session:
        row = session.get(Job, job.id)
        assert row is not None
        row.finished_at = utcnow() - timedelta(days=services.settings.job_retention_days + 1)
    run_retention(services.settings, services.db, services.store, holder="desktop-test")
    with services.db.session() as session:
        assert session.get(Job, job.id) is None

    class OneCycle(threading.Event):
        def wait(self, timeout: float | None = None) -> bool:
            self.set()
            return True

    journal.publish_ready(OneCycle())
    assert not (journal.root / f"{job.id}.json").exists()
    assert source.read_bytes() == b"Original document remains user owned."
    assert exported.read_bytes() == b"User edited exported translation"


@pytest.mark.parametrize("malformed", ["{invalid json", "[]", '{"output":42}'])
def test_corrupt_journal_record_does_not_block_independent_ready_export(
    desktop: tuple[Services, FakeEngines, str], tmp_path: Path, malformed: str
) -> None:
    services, engines, owner = desktop
    source = tmp_path / "original.txt"
    source.write_bytes(b"Original document remains user owned.")
    job = submit(services, owner)
    assert make_worker(services, engines).run_once()
    journal = ExportJournal(tmp_path / "journal", services.jobs, owner)
    broken = journal.root / "broken.json"
    broken.write_text(malformed)
    journal.record(job.id, source, source.parent)

    class OneCycle(threading.Event):
        def wait(self, timeout: float | None = None) -> bool:
            self.set()
            return True

    journal.publish_ready(OneCycle())
    result = journal.read(job.id)
    assert result["output"] is not None and Path(result["output"]).is_file()
    assert source.read_bytes() == b"Original document remains user owned."
    assert broken.read_text() == malformed


def test_desktop_exports_to_selected_folder_without_original_path(
    desktop: tuple[Services, FakeEngines, str], tmp_path: Path
) -> None:
    services, engines, owner = desktop
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    source = downloads / "original.txt"
    source.write_text("Document already in Downloads.", encoding="utf-8")
    app = FastAPI()
    journal = install_desktop(
        app,
        services.jobs,
        owner,
        tmp_path / "metadata",
        OfflineSupport(tmp_path / "models", tmp_path / "application"),
    )
    with TestClient(app) as client:
        discovery = client.post(
            "/v1/desktop/discover",
            json={
                "paths": [str(source)],
                "destination": str(downloads),
            },
        ).json()
        entry = client.get(f"/v1/desktop/discover/{discovery['cursor']}").json()
        assert entry["path"] == str(source)
        body = {"path": str(source), "target": "en", "submission_id": str(uuid.uuid4())}
        assert client.post("/v1/desktop/submit", json=body).status_code == 422
        response = client.post(
            "/v1/desktop/submit",
            json={
                **body,
                "destination": str(downloads),
                "relative": "source-folder/nested/original.txt",
            },
        )
        assert response.status_code == 200, response.text
        ident = response.json()["id"]
        # Accepted input is a snapshot. Export must not require the source to exist.
        source.unlink()
        make_worker(services, engines).run_once()
        response = client.post(f"/v1/desktop/jobs/{ident}/export", json={})
        assert response.status_code == 200, response.text
        output = Path(response.json()["path"])
        assert output.parent == downloads
        assert output.name == "original.en.txt"
        assert not (downloads / "source-folder").exists()
        assert journal.read(ident)["source"] is None
        assert client.get("/v1/desktop/recent").json()[0]["path"] is None
        assert client.post(f"/v1/desktop/jobs/{ident}/export", json={}).json()["path"] == str(
            output
        )
