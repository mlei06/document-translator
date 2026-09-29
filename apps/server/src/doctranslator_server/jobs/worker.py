"""The worker loop (ADR-008, ADR-016): claim, translate with the core, publish fenced.

A worker process keeps one ``Translator`` per mode between jobs. A separate heartbeat thread
extends the lease and watches for cancellation; the pipeline's progress callback raises to stop
between batches. A lost claim or lease stops the attempt without publishing anything.
"""

import json
import logging
import os
import shutil
import socket
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from doctranslator_core.types import (
    DocumentError,
    DocumentTranslationOptions,
    DocumentTranslationResult,
    EngineAuthenticationError,
    EngineResponseError,
    EngineUnavailableError,
    TranslationMode,
    TranslationProgress,
)
from doctranslator_server.db import Database
from doctranslator_server.jobs.engines import EngineCatalog
from doctranslator_server.jobs.preview import build_preview
from doctranslator_server.jobs.queue import Attempt, Output, Queue
from doctranslator_server.jobs.storage import BlobStore
from doctranslator_server.settings import ServerSettings

__all__ = ["DocumentRunner", "Worker", "worker_identity"]

logger = logging.getLogger(__name__)


class DocumentRunner(Protocol):
    """Runs one translation; the default uses the catalog's ``Translator`` for the mode."""

    def fingerprint(self, mode: TranslationMode, options: DocumentTranslationOptions) -> str: ...

    def translate(
        self,
        mode: TranslationMode,
        source: Path,
        output: Path,
        options: DocumentTranslationOptions,
        on_progress: Callable[[TranslationProgress], None],
        should_skip_fit: Callable[[], bool],
    ) -> DocumentTranslationResult: ...


class _CatalogRunner:
    def __init__(self, catalog: EngineCatalog) -> None:
        self._catalog = catalog

    def fingerprint(self, mode: TranslationMode, options: DocumentTranslationOptions) -> str:
        return self._catalog.loaded_fingerprint(self._catalog.translator(mode), options)

    def translate(
        self,
        mode: TranslationMode,
        source: Path,
        output: Path,
        options: DocumentTranslationOptions,
        on_progress: Callable[[TranslationProgress], None],
        should_skip_fit: Callable[[], bool],
    ) -> DocumentTranslationResult:
        return self._catalog.translator(mode).translate_document(
            source,
            output,
            options=options,
            on_progress=on_progress,
            should_skip_fit=should_skip_fit,
        )


class _StopError(Exception):
    """Raised from the progress callback to stop the pipeline between batches."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def worker_identity() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


@dataclass
class _Heartbeat:
    queue: Queue
    attempt: Attempt
    interval: float
    lost: threading.Event = field(default_factory=threading.Event)
    cancel: threading.Event = field(default_factory=threading.Event)
    _stop: threading.Event = field(default_factory=threading.Event)
    _thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="heartbeat", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                owned, cancel = self.queue.heartbeat(self.attempt)
            except Exception:  # a database hiccup: try again next beat; the lease has headroom
                logger.warning("heartbeat failed for job %s", self.attempt.job_id, exc_info=True)
                continue
            if not owned:
                self.lost.set()
                return
            if cancel:
                self.cancel.set()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=10)


class Worker:
    def __init__(
        self,
        settings: ServerSettings,
        db: Database,
        store: BlobStore,
        queue: Queue,
        runner: DocumentRunner,
        *,
        worker_id: str | None = None,
    ) -> None:
        self._settings = settings
        self._db = db
        self._store = store
        self._queue = queue
        self._runner = runner
        self.worker_id = worker_id or worker_identity()
        self._work = settings.data_dir / "work"

    @classmethod
    def from_catalog(
        cls,
        settings: ServerSettings,
        db: Database,
        store: BlobStore,
        queue: Queue,
        catalog: EngineCatalog,
    ) -> Worker:
        return cls(settings, db, store, queue, _CatalogRunner(catalog))

    def run(self, stop: threading.Event) -> None:
        """Claim and run jobs until ``stop`` is set (finishing the current job first)."""
        logger.info("worker %s started", self.worker_id)
        while not stop.is_set():
            if not self.run_once():
                stop.wait(self._settings.poll_s)
        logger.info("worker %s stopped", self.worker_id)

    def run_once(self) -> bool:
        """Recover expired attempts, then claim and run one job; ``False`` when idle."""
        self._queue.recover()
        attempt = self._queue.claim(self.worker_id)
        if attempt is None:
            return False
        self.process(attempt)
        return True

    def process(self, attempt: Attempt) -> None:
        reusable = self._queue.reusable(attempt)
        if reusable is not None:
            published = self._queue.publish(attempt, None, reuse=reusable)
            logger.info(
                "job %s reused the current result (published=%s)", attempt.job_id, published
            )
            if not published:
                self._after_refused(attempt)
            return
        heartbeat = _Heartbeat(self._queue, attempt, self._settings.heartbeat_s)
        heartbeat.start()
        work = self._work / f"{attempt.job_id}-{attempt.token[:8]}"
        try:
            self._translate(attempt, heartbeat, work)
        except _StopError as stop:
            if stop.reason == "cancelled":
                self._queue.cancelled(attempt)
                logger.info("job %s cancelled", attempt.job_id)
            else:
                logger.warning("job %s: attempt lost its claim; nothing published", attempt.job_id)
        except EngineUnavailableError as exc:
            outcome = self._queue.retry(attempt, "engine_unavailable", str(exc))
            logger.warning("job %s: engine unavailable (%s)", attempt.job_id, outcome)
        except EngineAuthenticationError:
            self._queue.fail(
                attempt, "engine_authentication", "The translation engine rejected the service."
            )
        except EngineResponseError as exc:
            self._queue.fail(attempt, "engine_response", str(exc))
        except DocumentError as exc:
            self._queue.fail(attempt, exc.code, str(exc))
        except _IdentityChangedError:
            self._queue.fail(
                attempt,
                "identity_mismatch",
                "The service's engine or fonts changed since submission; submit the file again.",
            )
        except Exception:
            logger.exception("job %s failed unexpectedly", attempt.job_id)
            self._queue.fail(attempt, "internal_error", "The translation failed unexpectedly.")
        finally:
            heartbeat.stop()
            shutil.rmtree(work, ignore_errors=True)

    def _translate(self, attempt: Attempt, heartbeat: _Heartbeat, work: Path) -> None:
        options = DocumentTranslationOptions.model_validate(attempt.options)
        mode = TranslationMode(attempt.mode)
        if self._runner.fingerprint(mode, options) != attempt.fingerprint:
            raise _IdentityChangedError
        work.mkdir(parents=True, exist_ok=True)
        source = work / f"input.{attempt.format}"
        shutil.copyfile(self._store.path(attempt.input_hash), source)
        output = work / f"output.{attempt.format}"
        progress = _Progress(self._queue, attempt, heartbeat)
        result = self._runner.translate(mode, source, output, options, progress, progress.skip)
        progress.check()
        report = work / "report.json"
        payload = result.model_dump(mode="json", exclude={"output_path", "timings_s"})
        report.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        package = build_preview(attempt.format, source, output, work / "preview.zip")
        stored_output = self._store.put_file(output)
        stored_report = self._store.put_file(report)
        stored_preview = self._store.put_file(package) if package is not None else None
        pins = [stored_output.pin_id, stored_report.pin_id]
        if stored_preview is not None:
            pins.append(stored_preview.pin_id)
        published = self._queue.publish(
            attempt,
            Output(
                output_blob=stored_output.sha256,
                report_blob=stored_report.sha256,
                preview_blob=stored_preview.sha256 if stored_preview else None,
                pins=pins,
                source_resolved=result.source_resolved.value if result.source_resolved else None,
                fit_status=result.fit_status.value,
                engine=result.engine.model_dump(mode="json"),
            ),
            reuse=None,
        )
        if published:
            logger.info(
                "job %s succeeded (fit %s, %d segments)",
                attempt.job_id,
                result.fit_status.value,
                result.counts.segments,
            )
            return
        self._store.release_pins(pins)
        self._after_refused(attempt)

    def _after_refused(self, attempt: Attempt) -> None:
        """Publication was refused: record cancellation if that was the reason."""
        job = self._queue.job(attempt.job_id)
        if job is not None and job.status == "running" and job.cancel_requested:
            self._queue.cancelled(attempt)


class _IdentityChangedError(Exception):
    pass


class _Progress:
    """The pipeline's progress callback and fit-skip control: fenced, throttled snapshots
    (P5-P6 progress plan) and cooperative stopping."""

    MIN_INTERVAL = 1.0

    def __init__(self, queue: Queue, attempt: Attempt, heartbeat: _Heartbeat) -> None:
        self._queue = queue
        self._attempt = attempt
        self._heartbeat = heartbeat
        self._last = 0.0
        self._phase: str = ""
        self._skip = False
        self._checked = 0.0

    def skip(self) -> bool:
        """``should_skip_fit``: reads the durable request at most once per second."""
        if self._skip:
            return True
        now = time.monotonic()
        if now - self._checked >= self.MIN_INTERVAL:
            self._checked = now
            control = self._queue.control(self._attempt)
            if not control.owned:
                raise _StopError("lost")
            if control.cancel:
                raise _StopError("cancelled")
            self._skip = control.skip_fit
        return self._skip

    def check(self) -> None:
        if self._heartbeat.lost.is_set():
            raise _StopError("lost")
        if self._heartbeat.cancel.is_set():
            raise _StopError("cancelled")

    def __call__(self, progress: TranslationProgress) -> None:
        self.check()
        now = time.monotonic()
        phase = str(progress.phase)
        if phase == self._phase and now - self._last < self.MIN_INTERVAL:
            return
        self._phase, self._last = phase, now
        control = self._queue.progress(self._attempt, phase, progress.done, progress.total)
        if not control.owned:
            raise _StopError("lost")
        if control.cancel:
            raise _StopError("cancelled")
        self._skip = self._skip or control.skip_fit
