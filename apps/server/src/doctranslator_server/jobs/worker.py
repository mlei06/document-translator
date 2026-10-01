"""The worker loop (ADR-008, ADR-016): claim, translate with the core, publish fenced.

A worker lazily loads configured translators with a bounded local runtime cache.
A separate heartbeat thread
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
from dataclasses import dataclass, field, replace
from datetime import timedelta
from pathlib import Path
from typing import Protocol

from doctranslator_core.types import (
    DocumentDetection,
    DocumentError,
    DocumentTranslationOptions,
    DocumentTranslationResult,
    EngineAuthenticationError,
    EngineEndpointUnavailableError,
    EnginePolicyDeniedError,
    EngineResponseError,
    EngineUnavailableError,
    IdentityMismatchError,
    TranslationProgress,
)
from doctranslator_server.db import Database
from doctranslator_server.jobs.engines import EngineCatalog
from doctranslator_server.jobs.errors import InvalidRequestError
from doctranslator_server.jobs.queue import Attempt, Output, Queue
from doctranslator_server.jobs.storage import BlobStore
from doctranslator_server.settings import ServerSettings

__all__ = ["DocumentRunner", "Worker", "worker_identity"]

logger = logging.getLogger(__name__)


class DocumentRunner(Protocol):
    """Runs one translation; the default uses the catalog's ``Translator`` for the mode."""

    def available(self) -> set[str] | None:
        """Execution-time discovered IDs; None leaves availability to inference."""
        ...

    def fingerprint(self, mode: str, options: DocumentTranslationOptions) -> str: ...

    def translate(
        self,
        mode: str,
        source: Path,
        output: Path,
        options: DocumentTranslationOptions,
        on_progress: Callable[[TranslationProgress], None],
        should_skip_fit: Callable[[], bool],
        *,
        detection_metadata: DocumentDetection | None = None,
    ) -> DocumentTranslationResult: ...


class _CatalogRunner:
    def __init__(self, catalog: EngineCatalog) -> None:
        self._catalog = catalog

    def available(self) -> set[str]:
        return {entry.id for entry in self._catalog.translators}

    def fingerprint(self, mode: str, options: DocumentTranslationOptions) -> str:
        try:
            return self._catalog.loaded_fingerprint(self._catalog.translator(mode), options)
        except InvalidRequestError as exc:
            raise _IdentityChangedError from exc

    def translate(
        self,
        mode: str,
        source: Path,
        output: Path,
        options: DocumentTranslationOptions,
        on_progress: Callable[[TranslationProgress], None],
        should_skip_fit: Callable[[], bool],
        *,
        detection_metadata: DocumentDetection | None = None,
    ) -> DocumentTranslationResult:
        return self._catalog.translator(mode).translate_document(
            source,
            output,
            options=options,
            on_progress=on_progress,
            should_skip_fit=should_skip_fit,
            detection_metadata=detection_metadata,
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
            if not self._store.verify(attempt.input_hash):
                raise DocumentError("the verified source bytes are missing or damaged")
            job = self._queue.job(attempt.job_id)
            if job is not None and job.policy is not None:
                self._automatic(attempt, heartbeat, work)
            else:
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
        except EnginePolicyDeniedError:
            self._queue.fail(
                attempt,
                "engine_policy_denied",
                "The translation service denied this request under its policy or quota.",
            )
        except EngineResponseError as exc:
            self._queue.fail(attempt, "engine_response", str(exc))
        except DocumentError as exc:
            self._queue.fail(attempt, exc.code, str(exc))
        except _IdentityChangedError, IdentityMismatchError:
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
            if (
                not work.is_symlink()
                and not work.is_junction()
                and work.resolve().parent == self._work.resolve()
            ):
                shutil.rmtree(work, ignore_errors=True)
            finished = self._queue.job(attempt.job_id)
            if (
                finished is not None
                and (
                    finished.retention == "cached"
                    or (finished.retention == "temporary" and finished.policy is not None)
                )
                and finished.status not in ("queued", "running")
            ):
                try:
                    self._store.collect(
                        holder=f"terminal:{attempt.job_id}", pending_grace=timedelta(hours=24)
                    )
                except Exception:
                    logger.warning("terminal cleanup deferred to retention sweep")

    def _automatic(self, attempt: Attempt, heartbeat: _Heartbeat, work: Path) -> None:
        job = self._queue.job(attempt.job_id)
        if job is None or job.policy is None:
            raise _IdentityChangedError
        candidates = job.policy["candidates"]
        available = self._runner.available()
        skip_remote = False
        for index in range(job.rung, len(candidates)):
            candidate = candidates[index]
            identifier = candidate["id"]
            if (skip_remote and identifier != "hy-mt-local") or (
                available is not None and identifier not in available
            ):
                self._queue.advance_rung(
                    attempt, index + 1, "unavailable", candidate["fingerprint"]
                )
                continue
            selected = replace(
                attempt, translator_id=identifier, fingerprint=candidate["fingerprint"]
            )
            if not self._queue.select_candidate(attempt, identifier, candidate["fingerprint"]):
                raise _StopError("lost")
            try:
                self._translate(selected, heartbeat, work / str(index))
                return
            except (EngineUnavailableError, EngineAuthenticationError, EngineResponseError) as exc:
                category = (
                    "authentication"
                    if isinstance(exc, EngineAuthenticationError)
                    else "unavailable"
                    if isinstance(exc, EngineUnavailableError)
                    else "response"
                )
                self._queue.advance_rung(attempt, index + 1, category, candidate["fingerprint"])
                if (
                    isinstance(exc, (EngineAuthenticationError, EngineEndpointUnavailableError))
                    and identifier != "hy-mt-local"
                ):
                    skip_remote = True
        reuse = job.policy.get("reuse")
        if reuse:
            if not self._queue.publish(attempt, None, reuse=reuse):
                self._after_refused(attempt)
            return
        self._queue.fail(
            attempt,
            "translation_services_exhausted",
            "Translation services are unavailable. Retry when a service is reachable "
            "or install offline support.",
        )

    def _translate(self, attempt: Attempt, heartbeat: _Heartbeat, work: Path) -> None:
        options = DocumentTranslationOptions.model_validate(attempt.options)
        mode = attempt.translator_id or attempt.mode
        if self._runner.fingerprint(mode, options) != attempt.fingerprint:
            raise _IdentityChangedError
        work.mkdir(parents=True, exist_ok=True)
        source = work / f"input.{attempt.format}"
        shutil.copyfile(self._store.path(attempt.input_hash), source)
        output = work / f"output.{attempt.format}"
        progress = _Progress(self._queue, attempt, heartbeat)
        job = self._queue.job(attempt.job_id)
        metadata = job.policy.get("detection_metadata") if job and job.policy else None
        result = self._runner.translate(
            mode,
            source,
            output,
            options,
            progress,
            progress.skip,
            detection_metadata=DocumentDetection.model_validate(metadata)
            if metadata is not None
            else None,
        )
        progress.check()
        report = work / "report.json"
        payload = result.model_dump(mode="json", exclude={"output_path", "timings_s"})
        report.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        if output.stat().st_size > self._settings.max_output_bytes:
            raise DocumentError("translated document exceeds the output size limit")
        if report.stat().st_size > self._settings.max_report_bytes:
            raise DocumentError("translation report exceeds the size limit")
        if (
            sum(path.stat().st_size for path in work.rglob("*") if path.is_file())
            > self._settings.max_workspace_bytes
        ):
            raise DocumentError("translation workspace exceeds its size limit")
        stored_output = self._store.put_file(output, reservation_owner=attempt.job_id)
        stored_report = self._store.put_file(report, reservation_owner=attempt.job_id)
        pins = [stored_output.pin_id, stored_report.pin_id]
        published = self._queue.publish(
            attempt,
            Output(
                output_blob=stored_output.sha256,
                report_blob=stored_report.sha256,
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
