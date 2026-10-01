"""Native-only file bridge. Queue, status, cancellation and inference remain shared."""

import threading
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Literal

from fastapi import BackgroundTasks, FastAPI, HTTPException
from pydantic import BaseModel

from doctranslator_server.api.schemas import JobOut
from doctranslator_server.jobs.desktop_files import DiscoveredFile, discover
from doctranslator_server.jobs.desktop_journal import ExportJournal
from doctranslator_server.jobs.desktop_offline import OfflineSupport
from doctranslator_server.jobs.errors import NotFoundError
from doctranslator_server.jobs.service import JobService, SubmitOptions


class DiscoverIn(BaseModel):
    paths: list[str]
    destination: str | None = None


class LocalSubmit(BaseModel):
    path: str
    target: Literal["en", "zh", "ja", "es"]
    submission_id: uuid.UUID
    destination: str


class ExportIn(BaseModel):
    destination: str | None = None


def install(
    app: FastAPI, jobs: JobService, owner: str, metadata: Path, offline: OfflineSupport
) -> ExportJournal:
    # Bounded, ephemeral discovery cursors are not a second job queue. Each admitted
    # file is sent immediately to the existing durable service queue by the shell.
    cursors: dict[str, Iterator[DiscoveredFile]] = {}
    lock = threading.Lock()
    journal = ExportJournal(metadata / "exports", jobs, owner)

    @app.get("/v1/desktop/offline")
    def offline_status() -> dict[str, str | int]:
        return offline.status()

    def idle_required() -> None:
        if jobs.has_pending_jobs(owner):
            raise HTTPException(409, "Wait for active translations before changing offline support")

    @app.post("/v1/desktop/offline/install")
    def add_offline(background: BackgroundTasks, repair: bool = False) -> dict[str, str]:
        with offline.lock:
            idle_required()
            if offline.installing:
                raise HTTPException(409, "Offline installation is already running")
            # Validate packaged approval before scheduling any network work.
            try:
                offline.manifest()
            except (ValueError, OSError) as exc:
                raise HTTPException(
                    409, "Approved offline bundle unavailable; repair application"
                ) from exc
            offline.cancelled.clear()
            offline.installing = True
            background.add_task(offline.setup, repair=repair)
        return {
            "state": "Installing",
            "detail": "Offline support will activate when installation completes",
        }

    @app.delete("/v1/desktop/offline")
    def remove_offline() -> dict[str, str]:
        try:
            with offline.lock:
                idle_required()
                offline.deactivate()
                offline.changed()
        except (OSError, ValueError, RuntimeError) as exc:
            raise HTTPException(409, "Offline support is in use or unavailable") from exc
        return {"state": "Not installed"}

    @app.post("/v1/desktop/offline/cancel")
    def cancel_offline() -> dict[str, str]:
        offline.cancelled.set()
        return {"state": "Cancelling"}

    @app.get("/v1/desktop/recent")
    def recent() -> list[dict[str, object]]:
        result: list[dict[str, object]] = []
        with journal.lock:
            for path in sorted(
                journal.root.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True
            )[:500]:
                value = journal.read(path.stem)
                try:
                    job = jobs.get_job(owner, path.stem)
                except NotFoundError:
                    path.unlink(missing_ok=True)
                    continue
                if job.dismissed_at is not None:
                    continue
                result.append(
                    {
                        **JobOut.of(job).model_dump(mode="json"),
                        "path": value["source"],
                        "destination": value["destination"],
                        "output": value["output"],
                        "name": job.original_name,
                        "error": value.get("error"),
                    }
                )
        return result

    @app.post("/v1/desktop/discover")
    def begin(body: DiscoverIn) -> dict[str, str]:
        with lock:
            if len(cursors) >= 8:
                raise HTTPException(429, "Finish or cancel an existing folder discovery")
            ident = str(uuid.uuid4())
            destination = Path(body.destination).resolve() if body.destination else None
            # Downloads can itself contain the selected inputs. Exclude an output
            # subtree only when it is strictly inside a selected source root.
            excluded = (
                [destination]
                if destination
                and any(
                    destination != Path(root).resolve()
                    and destination.is_relative_to(Path(root).resolve())
                    for root in body.paths
                )
                else []
            )
            with journal.lock:
                for record in journal.root.glob("*.json"):
                    value = journal.read(record.stem)
                    if value["output"]:
                        excluded.append(Path(value["output"]))
            cursors[ident] = discover(
                [Path(p) for p in body.paths],
                excluded=excluded,
            )
            return {"cursor": ident}

    @app.get("/v1/desktop/discover/{cursor}")
    def next_file(cursor: str) -> dict[str, str | bool | None]:
        with lock:
            iterator = cursors.get(cursor)
            if iterator is None:
                raise HTTPException(404, "Discovery ended")
            item = next(iterator, None)
            if item is None:
                del cursors[cursor]
                return {"done": True}
            return {
                "done": False,
                "path": str(item.path),
                "relative": str(item.relative),
                "error": item.error,
            }

    @app.delete("/v1/desktop/discover/{cursor}")
    def cancel_discovery(cursor: str) -> dict[str, bool]:
        with lock:
            cursors.pop(cursor, None)
        return {"cancelled": True}

    @app.post("/v1/desktop/submit", response_model=JobOut)
    def submit(body: LocalSubmit) -> JobOut:
        path = Path(body.path)
        if not path.is_absolute() or path.is_symlink() or path.is_junction():
            raise HTTPException(400, "Choose a regular local document")
        destination = Path(body.destination)
        if not destination.is_absolute():
            raise HTTPException(400, "Choose an absolute export folder")
        try:
            destination.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise HTTPException(409, "Choose another output folder") from exc
        try:
            with offline.lock, path.open("rb") as stream:
                if offline.installing:
                    raise HTTPException(409, "Wait for offline support installation to finish")
                result = jobs.submit(
                    owner,
                    path.name,
                    stream,
                    SubmitOptions(
                        target=body.target,
                        retention="temporary",
                        force_retranslate=True,
                        selection_policy="desktop_auto",
                    ),
                    submission_id=str(body.submission_id),
                )
        except OSError as exc:
            raise HTTPException(400, "Document cannot be opened") from exc
        if result.job is None:
            raise HTTPException(500, "Submission did not create a job")
        journal.record(result.job.id, path, destination)
        return JobOut.of(result.job)

    @app.post("/v1/desktop/jobs/{job_id}/export")
    def export(job_id: str, body: ExportIn) -> dict[str, str]:
        try:
            with journal.lock:
                value = journal.read(job_id)
                if body.destination is not None and not value["output"]:
                    value["destination"] = body.destination
                    value["planned"] = None
                    value["error"] = None
                    journal.write(job_id, value)
                path = journal.export(job_id)
        except OSError as exc:
            raise HTTPException(409, "Destination unavailable; choose another folder") from exc
        return {"path": str(path)}

    return journal
