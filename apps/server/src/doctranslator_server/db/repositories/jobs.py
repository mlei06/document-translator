"""Job rows and the attempt-fenced queue transitions of ADR-016.

Every transition after a claim is conditioned on ``status='running'`` and the attempt's
``claim_token``; heartbeat and success additionally require a live lease. A zero-row update means
the attempt no longer owns the job.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import and_, delete, exists, func, select, update
from sqlalchemy.orm import Session

from doctranslator_server.db.models import Job, JobResult, User
from doctranslator_server.db.repositories._rows import rowcount

__all__ = [
    "NONTERMINAL",
    "active_in_slot",
    "active_work_directories",
    "by_submission",
    "cancel_for_user",
    "claim",
    "count_nonterminal",
    "delete_finished",
    "expired_running",
    "fenced",
    "get",
    "get_owned",
    "heartbeat",
    "insert",
    "list_owned",
    "next_candidates",
    "recover",
    "request_cancel",
    "request_skip_fit",
]

NONTERMINAL = ("queued", "running")


def active_work_directories(session: Session) -> set[str]:
    """Names owned by current running attempts, including ones awaiting lease recovery.

    A lease expiring does not mean a native model call has stopped. Recovery changes the
    claim token before another worker creates its directory; tokens are never reused.
    """
    rows = session.execute(
        select(Job.id, Job.claim_token).where(Job.status == "running", Job.claim_token.is_not(None))
    )
    return {f"{job_id}-{token[:8]}" for job_id, token in rows if token is not None}


def insert(session: Session, **fields: Any) -> Job:
    job = Job(**fields)
    session.add(job)
    session.flush()
    return job


def get(session: Session, job_id: str) -> Job | None:
    return session.get(Job, job_id)


def get_owned(session: Session, owner_id: str, job_id: str) -> Job | None:
    return session.scalar(select(Job).where(Job.id == job_id, Job.owner_id == owner_id))


def by_submission(session: Session, owner_id: str, submission_id: str) -> Job | None:
    return session.scalar(
        select(Job).where(Job.owner_id == owner_id, Job.submission_id == submission_id)
    )


def list_owned(
    session: Session,
    owner_id: str,
    *,
    after: tuple[datetime, str] | None,
    limit: int,
    status: str | None = None,
    batch_id: str | None = None,
    search: str | None = None,
    active: bool = False,
    document_id: str | None = None,
    active_only: bool = False,
) -> list[Job]:
    """Newest first; ``after`` is the (created_at, id) of the last row of the previous page.

    ``search`` matches file names (case-insensitive); ``active`` keeps unfinished jobs and
    finished jobs the user has not dismissed; ``active_only`` keeps unfinished jobs only.
    """
    statement = select(Job).where(Job.owner_id == owner_id)
    if document_id is not None:
        statement = statement.where(Job.document_id == document_id)
    if active_only:
        statement = statement.where(Job.status.in_(NONTERMINAL))
    if search:
        escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        statement = statement.where(Job.original_name.ilike(f"%{escaped}%", escape="\\"))
    if active:
        statement = statement.where(Job.status.in_(NONTERMINAL) | Job.dismissed_at.is_(None))
    if status is not None:
        statement = statement.where(Job.status == status)
    if batch_id is not None:
        statement = statement.where(Job.batch_id == batch_id)
    if after is not None:
        created, ident = after
        statement = statement.where(
            (Job.created_at < created) | and_(Job.created_at == created, Job.id < ident)
        )
    return list(
        session.scalars(statement.order_by(Job.created_at.desc(), Job.id.desc()).limit(limit))
    )


def count_nonterminal(session: Session, owner_id: str | None = None) -> int:
    query = select(func.count()).select_from(Job).where(Job.status.in_(NONTERMINAL))
    if owner_id is not None:
        query = query.where(Job.owner_id == owner_id)
    return int(session.scalar(query) or 0)


def next_candidates(session: Session, now: datetime, limit: int = 8) -> list[str]:
    return list(
        session.scalars(
            select(Job.id)
            .where(
                Job.status == "queued",
                Job.kind != "waiter",
                Job.available_at <= now,
                ~Job.cancel_requested,
            )
            .order_by(Job.available_at, Job.created_at)
            .limit(limit)
        )
    )


def claim(
    session: Session, job_id: str, token: str, worker: str, now: datetime, lease_until: datetime
) -> bool:
    result = session.execute(
        update(Job)
        .where(
            Job.id == job_id,
            Job.status == "queued",
            Job.available_at <= now,
            ~Job.cancel_requested,
        )
        .values(
            status="running",
            attempts=Job.attempts + 1,
            claim_token=token,
            worker_id=worker,
            lease_until=lease_until,
            heartbeat_at=now,
            started_at=now,
            phase="prepare",
            progress_done=None,
            progress_total=None,
            progress_updated_at=now,
        )
    )
    return rowcount(result) == 1


def fenced(
    session: Session,
    job_id: str,
    token: str,
    values: dict[str, Any],
    *,
    now: datetime | None = None,
    success: bool = False,
) -> bool:
    """A transition of the running attempt ``token``; ``now`` also requires a live lease.

    ``success`` adds the publication predicates: no cancellation requested and the owner is
    still active (ADR-015/016).
    """
    conditions = [Job.id == job_id, Job.status == "running", Job.claim_token == token]
    if now is not None:
        conditions.append(Job.lease_until > now)
    if success:
        conditions.append(~Job.cancel_requested)
        conditions.append(exists().where(User.id == Job.owner_id, User.active))
    result = session.execute(
        update(Job).where(*conditions).values(**values).execution_options(synchronize_session=False)
    )
    return rowcount(result) == 1


def heartbeat(
    session: Session, job_id: str, token: str, now: datetime, lease_until: datetime
) -> tuple[bool, bool]:
    """Extend the lease; returns (still owned, cancellation requested)."""
    owned = fenced(
        session, job_id, token, {"lease_until": lease_until, "heartbeat_at": now}, now=now
    )
    if not owned:
        return False, False
    cancel = session.scalar(select(Job.cancel_requested).where(Job.id == job_id))
    return True, bool(cancel)


def expired_running(session: Session, now: datetime) -> list[Job]:
    return list(session.scalars(select(Job).where(Job.status == "running", Job.lease_until <= now)))


def recover(session: Session, job: Job, now: datetime, retry_at: datetime) -> str | None:
    """Requeue, fail or cancel an expired attempt, conditioned on its old token and lease."""
    if job.claim_token is None:
        return None
    if job.cancel_requested:
        values: dict[str, Any] = {
            "status": "cancelled",
            "finished_at": now,
            "active_slot": None,
        }
        outcome = "cancelled"
    elif job.attempts < job.max_attempts:
        values = {
            "status": "queued",
            "available_at": retry_at,
            "phase": None,
            "progress_done": None,
            "progress_total": None,
            "progress_updated_at": None,
        }
        outcome = "requeued"
    else:
        values = {
            "status": "failed",
            "finished_at": now,
            "active_slot": None,
            "error_code": "worker_lost",
            "error_message": "The worker processing this job stopped repeatedly.",
        }
        outcome = "failed"
    values |= {"claim_token": None, "worker_id": None, "lease_until": None}
    result = session.execute(
        update(Job)
        .where(
            Job.id == job.id,
            Job.status == "running",
            Job.claim_token == job.claim_token,
            Job.lease_until <= now,
        )
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    return outcome if rowcount(result) == 1 else None


def request_cancel(session: Session, job_id: str, now: datetime) -> None:
    """Queued jobs cancel at once; running jobs get the flag their worker observes."""
    session.execute(
        update(Job)
        .where(Job.id == job_id, Job.status == "queued")
        .values(status="cancelled", cancel_requested=True, finished_at=now, active_slot=None)
        .execution_options(synchronize_session=False)
    )
    session.execute(
        update(Job)
        .where(Job.id == job_id, Job.status == "running")
        .values(cancel_requested=True)
        .execution_options(synchronize_session=False)
    )


def delete_finished(session: Session, before: datetime) -> int:
    """Standalone terminal jobs that finished before ``before`` and whose own result is gone
    (a current translation's producing job is kept as its provenance, ADR-014)."""
    old = list(
        session.scalars(
            select(Job.id).where(
                Job.batch_id.is_(None),
                Job.status.not_in(NONTERMINAL),
                Job.finished_at < before,
                ~exists().where(JobResult.job_id == Job.id),
            )
        )
    )
    if old:
        session.execute(delete(Job).where(Job.id.in_(old)))
    return len(old)


def request_skip_fit(session: Session, job: Job) -> str:
    """Record a skip-fit request (ADR-012 amendment): ``set``, ``already`` or ``not_in_fit``."""
    if job.fit_skip_requested:
        return "already"
    result = session.execute(
        update(Job)
        .where(
            Job.id == job.id,
            Job.status == "running",
            Job.phase == "fit",
            ~Job.cancel_requested,
            ~Job.fit_skip_requested,
        )
        .values(fit_skip_requested=True)
        .execution_options(synchronize_session=False)
    )
    return "set" if rowcount(result) == 1 else "not_in_fit"


def active_in_slot(session: Session, slot: str) -> Job | None:
    return session.scalar(select(Job).where(Job.active_slot == slot))


def cancel_for_user(session: Session, owner_id: str, now: datetime) -> int:
    ids = list(
        session.scalars(select(Job.id).where(Job.owner_id == owner_id, Job.status.in_(NONTERMINAL)))
    )
    for job_id in ids:
        request_cancel(session, job_id, now)
    return len(ids)
