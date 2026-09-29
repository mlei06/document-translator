"""Queue transitions as short transactions (ADR-008 as amended by ADR-016).

Each method is one database transaction. Everything after a claim is fenced by the attempt's
claim token; ``publish`` is the only way a job becomes ``succeeded`` from a worker, and it
publishes the cache row, the owner's document and version 0 together or not at all.
"""

import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from doctranslator_server.db import Database
from doctranslator_server.db.models import Job, TranslationResult, utcnow
from doctranslator_server.db.repositories import blobs as blob_repo
from doctranslator_server.db.repositories import jobs as job_repo
from doctranslator_server.db.repositories import results as result_repo
from doctranslator_server.db.repositories import users as user_repo

__all__ = ["Attempt", "Output", "Queue"]

type Clock = Callable[[], datetime]


class _NotPublishedError(Exception):
    """The fenced publication found the attempt no longer entitled to publish."""


@dataclass(frozen=True, slots=True)
class Attempt:
    """A claimed job attempt: the job's fields at claim time and the attempt's fence token."""

    job_id: str
    token: str
    owner_id: str
    mode: str
    options: dict[str, Any]
    fingerprint: str
    input_hash: str
    format: str
    force: bool
    attempts: int
    max_attempts: int


@dataclass(frozen=True, slots=True)
class Output:
    """A finished translation's stored blobs and summary."""

    output_blob: str
    report_blob: str
    pins: list[str]
    source_resolved: str | None
    fit_status: str
    engine: dict[str, Any]


class Queue:
    def __init__(
        self,
        db: Database,
        *,
        lease: timedelta,
        retry_delays: tuple[float, ...],
        document_retention: timedelta,
        clock: Clock = utcnow,
    ) -> None:
        self._db = db
        self._lease = lease
        self._retry_delays = retry_delays
        self._document_retention = document_retention
        self.now = clock

    def _retry_at(self, now: datetime, attempts: int) -> datetime:
        delays = self._retry_delays or (0.0,)
        delay = delays[min(max(attempts - 1, 0), len(delays) - 1)]
        return now + timedelta(seconds=delay)

    def recover(self) -> list[tuple[str, str]]:
        """Requeue, fail or cancel attempts whose lease expired; returns (job, outcome)."""
        now = self.now()
        outcomes: list[tuple[str, str]] = []
        with self._db.session() as session:
            expired = job_repo.expired_running(session, now)
        for job in expired:
            with self._db.session() as session:
                outcome = job_repo.recover(session, job, now, self._retry_at(now, job.attempts))
                if outcome is not None:
                    user_repo.audit(
                        session,
                        f"job_{outcome}",
                        actor=None,
                        target_type="job",
                        target_id=job.id,
                        outcome="lease_expired",
                    )
                    outcomes.append((job.id, outcome))
        return outcomes

    def claim(self, worker_id: str) -> Attempt | None:
        now = self.now()
        with self._db.session() as session:
            candidates = job_repo.next_candidates(session, now)
        for job_id in candidates:
            token = secrets.token_hex(16)
            with self._db.session() as session:
                if not job_repo.claim(session, job_id, token, worker_id, now, now + self._lease):
                    continue
                job = job_repo.get(session, job_id)
                if job is None:  # pragma: no cover - the claim just updated this row
                    continue
                session.refresh(job)
                return Attempt(
                    job_id=job.id,
                    token=token,
                    owner_id=job.owner_id,
                    mode=job.mode,
                    options=dict(job.options),
                    fingerprint=job.fingerprint,
                    input_hash=job.input_blob,
                    format=job.format,
                    force=job.force,
                    attempts=job.attempts,
                    max_attempts=job.max_attempts,
                )
        return None

    def heartbeat(self, attempt: Attempt) -> tuple[bool, bool]:
        """(still owned, cancellation requested)."""
        now = self.now()
        with self._db.session() as session:
            return job_repo.heartbeat(
                session, attempt.job_id, attempt.token, now, now + self._lease
            )

    def progress(self, attempt: Attempt, phase: str, done: int, total: int) -> tuple[bool, bool]:
        with self._db.session() as session:
            owned = job_repo.fenced(
                session,
                attempt.job_id,
                attempt.token,
                {"phase": phase, "progress_done": done, "progress_total": total},
            )
            if not owned:
                return False, False
            job = job_repo.get(session, attempt.job_id)
            return True, bool(job and job.cancel_requested)

    def cached(self, attempt: Attempt) -> str | None:
        """The cache row for this attempt's input and fingerprint, if any (re-check, ADR-008)."""
        if attempt.force:
            return None
        with self._db.session() as session:
            result = result_repo.lookup(session, attempt.input_hash, attempt.fingerprint)
            return result.id if result else None

    def publish(self, attempt: Attempt, output: Output | None, *, cache_result: str | None) -> bool:
        """Fenced success: job, cache row, document and version 0 in one transaction.

        ``output`` is a fresh translation; ``cache_result`` completes from an existing cache row.
        Returns ``False`` (nothing published) if the attempt lost its claim or lease, the job was
        cancelled, or its owner was disabled.
        """
        now = self.now()
        try:
            self._publish(attempt, output, cache_result, now)
        except _NotPublishedError:
            return False
        return True

    def _publish(
        self, attempt: Attempt, output: Output | None, cache_result: str | None, now: datetime
    ) -> None:
        with self._db.session() as session:
            if cache_result is not None:
                cached = session.get(TranslationResult, cache_result)
                if cached is None:
                    raise _NotPublishedError
                result_id = cached.id
                output_blob, report_blob = cached.output_blob, cached.report_blob
                source_resolved, fit_status = cached.source_resolved, cached.fit_status
                result_repo.touch(session, cached.id, now)
            else:
                if output is None:  # pragma: no cover - callers pass one or the other
                    raise ValueError("publish needs an output or a cache result")
                output_blob, report_blob = output.output_blob, output.report_blob
                source_resolved, fit_status = output.source_resolved, output.fit_status
                result_id = None
            owned = job_repo.fenced(
                session,
                attempt.job_id,
                attempt.token,
                {
                    "status": "succeeded",
                    "finished_at": now,
                    "phase": "done",
                    "source_resolved": source_resolved,
                    "fit_status": fit_status,
                    "cache_hit": cache_result is not None,
                    "claim_token": None,
                    "lease_until": None,
                },
                now=now,
                success=True,
            )
            if not owned:
                raise _NotPublishedError  # rolls the transaction back: nothing is published
            if output is not None:
                result = result_repo.store_result(
                    session,
                    input_hash=attempt.input_hash,
                    fingerprint=attempt.fingerprint,
                    output_blob=output.output_blob,
                    report_blob=output.report_blob,
                    source_resolved=output.source_resolved,
                    fit_status=output.fit_status,
                    engine=output.engine,
                    force=attempt.force,
                    now=now,
                )
                result_id = result.id
                blob_repo.release_pins(session, output.pins)
            job = job_repo.get(session, attempt.job_id)
            if job is None:  # pragma: no cover - the fenced update just changed this row
                raise _NotPublishedError
            session.refresh(job)
            job.result_id = result_id
            result_repo.add_document(
                session,
                job,
                result_id=result_id,
                source_resolved=source_resolved,
                fit_status=fit_status,
                output_blob=output_blob,
                report_blob=report_blob,
                now=now,
                expires_at=now + self._document_retention,
            )
            user_repo.audit(
                session,
                "job_succeeded",
                actor=None,
                target_type="job",
                target_id=attempt.job_id,
                outcome="cache_hit" if cache_result else "translated",
            )

    def cancelled(self, attempt: Attempt) -> bool:
        now = self.now()
        with self._db.session() as session:
            done = job_repo.fenced(
                session,
                attempt.job_id,
                attempt.token,
                {
                    "status": "cancelled",
                    "finished_at": now,
                    "claim_token": None,
                    "lease_until": None,
                },
            )
            if done:
                user_repo.audit(
                    session,
                    "job_cancelled",
                    actor=None,
                    target_type="job",
                    target_id=attempt.job_id,
                )
            return done

    def fail(self, attempt: Attempt, code: str, message: str) -> bool:
        now = self.now()
        with self._db.session() as session:
            done = job_repo.fenced(
                session,
                attempt.job_id,
                attempt.token,
                {
                    "status": "failed",
                    "finished_at": now,
                    "error_code": code,
                    "error_message": message[:2000],
                    "claim_token": None,
                    "lease_until": None,
                },
            )
            if done:
                user_repo.audit(
                    session,
                    "job_failed",
                    actor=None,
                    target_type="job",
                    target_id=attempt.job_id,
                    outcome=code,
                )
            return done

    def retry(self, attempt: Attempt, code: str, message: str) -> str | None:
        """Requeue a transient failure within the attempt budget, else fail it."""
        if attempt.attempts >= attempt.max_attempts:
            return "failed" if self.fail(attempt, code, message) else None
        now = self.now()
        with self._db.session() as session:
            done = job_repo.fenced(
                session,
                attempt.job_id,
                attempt.token,
                {
                    "status": "queued",
                    "available_at": self._retry_at(now, attempt.attempts),
                    "error_code": code,
                    "error_message": message[:2000],
                    "claim_token": None,
                    "worker_id": None,
                    "lease_until": None,
                },
            )
            return "requeued" if done else None

    def job(self, job_id: str) -> Job | None:
        with self._db.session() as session:
            return job_repo.get(session, job_id)
