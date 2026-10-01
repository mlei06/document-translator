"""Local source/export reconciliation metadata, never a translation queue or cache."""

import json
import logging
import os
import threading
from pathlib import Path
from typing import cast

from doctranslator_server.jobs.desktop_files import digest, export_file
from doctranslator_server.jobs.errors import NotFoundError
from doctranslator_server.jobs.service import JobService

logger = logging.getLogger(__name__)


class ExportJournal:
    def __init__(self, root: Path, jobs: JobService, owner: str) -> None:
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.jobs = jobs
        self.owner = owner
        self.lock = threading.RLock()

    def read(self, job_id: str) -> dict[str, str | None]:
        value: object = json.loads((self.root / f"{job_id}.json").read_text(encoding="utf-8"))
        if not isinstance(value, dict) or any(
            not isinstance(item, str) and item is not None
            for item in cast(dict[str, object], value).values()
        ):
            raise ValueError("Invalid export journal record")
        return cast(dict[str, str | None], value)

    def write(self, job_id: str, value: dict[str, str | None]) -> None:
        path = self.root / f"{job_id}.json"
        staged = path.with_suffix(".tmp")
        with staged.open("w", encoding="utf-8") as stream:
            stream.write(json.dumps(value))
            stream.flush()
            os.fsync(stream.fileno())
        staged.replace(path)

    def record(self, job_id: str, source: Path, destination: Path) -> None:
        with self.lock:
            if not (self.root / f"{job_id}.json").exists():
                self.write(
                    job_id,
                    {
                        "source": str(source),
                        "destination": str(destination),
                        "planned": None,
                        "output": None,
                    },
                )

    def export(self, job_id: str) -> Path:
        with self.lock:
            value = self.read(job_id)
            if value.get("output"):
                existing = Path(value["output"] or "")
                if existing.is_file() and digest(existing) == value.get("sha256"):
                    self.jobs.release_desktop_result(self.owner, job_id)
                    return existing
                raise FileNotFoundError("Export is missing or changed; retranslate the original")
            source = Path(value["source"] or "")
            job = self.jobs.get_job(self.owner, job_id)
            file = self.jobs.job_file(self.owner, job_id, "output")

            def planned(path: Path) -> None:
                value["planned"] = str(path)
                self.write(job_id, value)

            try:
                output = export_file(
                    file.path,
                    source,
                    Path(value["destination"]) if value["destination"] else source.parent,
                    job.target,
                    file.sha256,
                    planned=Path(value["planned"]) if value["planned"] else None,
                    before_publish=planned,
                )
            finally:
                if file.on_complete is not None:
                    file.on_complete()
            value["error"] = None
            value["output"] = str(output)
            # Exported activity needs only its filename and output location.
            # The original path is retained only until export for failed-job retry.
            value["source"] = None
            value["sha256"] = file.sha256
            self.write(job_id, value)
            self.jobs.release_desktop_result(self.owner, job_id)
            return output

    def publish_ready(self, stop: threading.Event) -> None:
        """Publish accepted work even when all application windows are closed."""
        while not stop.is_set():
            for path in self.root.glob("*.json"):
                if stop.is_set():
                    return
                try:
                    with self.lock:
                        value = self.read(path.stem)
                        job = self.jobs.get_job(self.owner, path.stem)
                        if value.get("output") or value.get("error"):
                            continue
                        if job.status == "succeeded":
                            self.export(path.stem)
                except NotFoundError:
                    try:
                        path.unlink(missing_ok=True)
                    except OSError:
                        logger.warning("Expired export metadata cleanup deferred")
                except OSError, ValueError:
                    try:
                        with self.lock:
                            value = self.read(path.stem)
                            value["error"] = (
                                "Output could not be saved; choose another output folder"
                            )
                            self.write(path.stem, value)
                    except OSError, ValueError:
                        logger.warning(
                            "An export journal record needs repair; continuing other exports"
                        )
            stop.wait(2)
