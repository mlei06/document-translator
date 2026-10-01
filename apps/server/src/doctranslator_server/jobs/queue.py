"""Queue transitions as short transactions (ADR-008 as amended by ADR-016, storage per ADR-014).

Each method is one database transaction. Everything after a claim is fenced by the attempt's
claim token. ``publish`` is the only way a job becomes ``succeeded`` from a worker: it records the
job's immutable result and, for a saved document, swaps that document's current translation for
the language pair, together or not at all. Every terminal transition releases the saved
document's active target slot.
"""

import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import exists, select

from doctranslator_server.db import Database
from doctranslator_server.db.models import Document, Job, SharedSlot, utcnow
from doctranslator_server.db.repositories import blobs as blob_repo
from doctranslator_server.db.repositories import jobs as job_repo
from doctranslator_server.db.repositories import results as result_repo
from doctranslator_server.db.repositories import users as user_repo
from doctranslator_server.jobs import shared

__all__ = ["Attempt", "Output", "Queue"]

type Clock = Callable[[], datetime]

_RELEASE: dict[str, Any] = {"claim_token": None, "lease_until": None, "active_slot": None}


class _NotPublishedError(Exception):
    """The fenced publication found the attempt no longer entitled to publish."""


@dataclass(frozen=True, slots=True)
class Attempt:
    """A claimed job attempt: the job's fields at claim time and the attempt's fence token."""

    job_id: str
    token: str
    owner_id: str
    document_id: str | None
    retention: str
    target: str
    mode: str
    translator_id: str | None
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


@dataclass(frozen=True, slots=True)
class Control:
    """What the running attempt should do: still owned, cancellation or fit skip requested."""

    owned: bool
    cancel: bool
    skip_fit: bool


class Queue:
    def __init__(
        self,
        db: Database,
        *,
        lease: timedelta,
        retry_delays: tuple[float, ...],
        temporary_retention: timedelta,
        superseded_retention: timedelta,
        clock: Clock = utcnow,
    ) -> None:
        self._db = db
        self._lease = lease
        self._retry_delays = retry_delays
        self._temporary = temporary_retention
        self._superseded = superseded_retention
        self.now = clock

    def _retry_at(self, now: datetime, attempts: int) -> datetime:
        delays = self._retry_delays or (0.0,)
        delay = delays[min(max(attempts - 1, 0), len(delays) - 1)]
        return now + timedelta(seconds=delay)

    def select_candidate(self, attempt: Attempt, identifier: str, fingerprint: str) -> bool:
        with self._db.session() as session:
            return job_repo.fenced(
                session,
                attempt.job_id,
                attempt.token,
                {"translator_id": identifier, "fingerprint": fingerprint},
                now=self.now(),
                success=True,
            )

    def advance_rung(self, attempt: Attempt, rung: int, category: str, fingerprint: str) -> None:
        with self._db.session() as session:
            if not job_repo.fenced(
                session,
                attempt.job_id,
                attempt.token,
                {"rung": rung, "error_code": category},
                now=self.now(),
                success=True,
            ):
                return
            work = session.get(Job, attempt.job_id)
            if work and work.kind == "shared_work" and work.policy:
                slot = session.get(SharedSlot, work.policy["slot_id"])
                if slot:
                    slot.cooldowns = dict(
                        slot.cooldowns,
                        **{
                            work.policy["profile"] + fingerprint: (
                                self.now() + timedelta(minutes=15)
                            ).timestamp()
                        },
                    )

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
                    recovered = session.get(Job, job.id)
                    if recovered and outcome in ("failed", "cancelled"):
                        session.refresh(recovered)
                        shared.finish(session, recovered, None, now)
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
                    document_id=job.document_id,
                    retention=job.retention,
                    target=job.target,
                    mode=job.mode,
                    translator_id=job.translator_id,
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

    def control(self, attempt: Attempt) -> Control:
        """The attempt's current control flags (read-only)."""
        with self._db.session() as session:
            job = job_repo.get(session, attempt.job_id)
            owned = job is not None and job.status == "running" and job.claim_token == attempt.token
            if not owned or job is None:
                return Control(False, False, False)
            return Control(
                True,
                job.cancel_requested or not shared.interested(session, job),
                job.fit_skip_requested,
            )

    def progress(
        self, attempt: Attempt, phase: str, done: int | None, total: int | None
    ) -> Control:
        """Store the latest progress snapshot (fenced) and return the control flags."""
        with self._db.session() as session:
            owned = job_repo.fenced(
                session,
                attempt.job_id,
                attempt.token,
                {
                    "phase": phase,
                    "progress_done": done,
                    "progress_total": total,
                    "progress_updated_at": self.now(),
                },
            )
            if not owned:
                return Control(False, False, False)
            job = job_repo.get(session, attempt.job_id)
            if job is None:  # pragma: no cover
                return Control(False, False, False)
            return Control(True, job.cancel_requested, job.fit_skip_requested)

    def reusable(self, attempt: Attempt) -> str | None:
        """The saved document's compatible current result (worker re-check, ADR-014); temporary
        and forced jobs never reuse."""
        if attempt.force or attempt.document_id is None:
            return None
        with self._db.session() as session:
            result = result_repo.reusable_result(
                session, attempt.document_id, attempt.target, attempt.fingerprint
            )
            return result.id if result else None

    def publish(self, attempt: Attempt, output: Output | None, *, reuse: str | None) -> bool:
        """Fenced success. ``output`` is a fresh translation; ``reuse`` completes the job with the
        document's existing current result. Returns ``False`` (nothing published) if the attempt
        lost its claim or lease, the job was cancelled, its owner was disabled or its saved
        document was deleted."""
        now = self.now()
        try:
            self._publish(attempt, output, reuse, now)
        except _NotPublishedError:
            return False
        return True

    def _publish(
        self, attempt: Attempt, output: Output | None, reuse: str | None, now: datetime
    ) -> None:
        with self._db.session() as session:
            live_work = session.get(Job, attempt.job_id)
            if live_work is None or not shared.interested(session, live_work):
                raise _NotPublishedError
            if live_work.kind == "shared_work":
                policy = live_work.policy
                slot = session.get(SharedSlot, policy["slot_id"]) if policy else None
                if (
                    slot is None
                    or slot.active_work_id != live_work.id
                    or policy is None
                    or slot.generation != policy["generation"]
                ):
                    raise _NotPublishedError
            if attempt.document_id is not None:
                live = session.scalar(
                    select(
                        exists().where(
                            Document.id == attempt.document_id, Document.deleted_at.is_(None)
                        )
                    )
                )
                if not live:
                    raise _NotPublishedError
            if reuse is not None:
                result = result_repo.get_result(session, reuse)
                if result is None:
                    raise _NotPublishedError
                source_resolved, fit_status = result.source_resolved, result.fit_status
            elif output is not None:
                result = None
                source_resolved, fit_status = output.source_resolved, output.fit_status
            else:  # pragma: no cover - callers pass one or the other
                raise ValueError("publish needs an output or a result to reuse")
            owned = job_repo.fenced(
                session,
                attempt.job_id,
                attempt.token,
                {
                    "status": "succeeded",
                    "finished_at": now,
                    "phase": None,
                    "progress_done": None,
                    "progress_total": None,
                    "progress_updated_at": now,
                    "source_resolved": source_resolved,
                    "fit_status": fit_status,
                    "cache_hit": reuse is not None,
                    "error_code": None,
                    "error_message": None,
                }
                | _RELEASE,
                now=now,
                success=True,
            )
            if not owned:
                raise _NotPublishedError  # rolls the transaction back: nothing is published
            if result is None and output is not None:
                saved = attempt.document_id is not None
                result = result_repo.add_result(
                    session,
                    job_id=attempt.job_id,
                    input_hash=attempt.input_hash,
                    fingerprint=attempt.fingerprint,
                    output_blob=output.output_blob,
                    report_blob=output.report_blob,
                    source_resolved=output.source_resolved,
                    fit_status=output.fit_status,
                    engine=output.engine,
                    created_at=now,
                    expires_at=None if saved else now + self._temporary,
                )
                if saved and attempt.document_id is not None:
                    result_repo.set_current(
                        session,
                        attempt.document_id,
                        output.source_resolved or "",
                        attempt.target,
                        result,
                        now,
                        now + self._superseded,
                    )
                blob_repo.release_pins(session, output.pins)
            job = job_repo.get(session, attempt.job_id)
            if job is None or result is None:  # pragma: no cover
                raise _NotPublishedError
            job.result_id = result.id
            session.refresh(job)
            job.result_id = result.id
            shared.finish(session, job, result, now)
            user_repo.audit(
                session,
                "job_succeeded",
                actor=None,
                target_type="job",
                target_id=attempt.job_id,
                outcome="reused" if reuse else "translated",
            )

    def cancelled(self, attempt: Attempt) -> bool:
        now = self.now()
        with self._db.session() as session:
            done = job_repo.fenced(
                session,
                attempt.job_id,
                attempt.token,
                {"status": "cancelled", "finished_at": now} | _RELEASE,
            )
            if done:
                job = session.get(Job, attempt.job_id)
                if job:
                    session.refresh(job)
                    shared.finish(session, job, None, now)
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
                }
                | _RELEASE,
            )
            if done:
                job = session.get(Job, attempt.job_id)
                if job:
                    session.refresh(job)
                    shared.finish(session, job, None, now)
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
                    "phase": None,
                    "progress_done": None,
                    "progress_total": None,
                    "progress_updated_at": None,
                },
            )
            return "requeued" if done else None

    def job(self, job_id: str) -> Job | None:
        with self._db.session() as session:
            return job_repo.get(session, job_id)
