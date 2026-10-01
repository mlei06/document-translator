"""Shared slots and private waiters extending the existing database queue."""

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from doctranslator_server.db.models import (
    Document,
    HistoryGrant,
    Job,
    JobResult,
    SharedSlot,
    StorageReservation,
    User,
    new_id,
    utcnow,
)
from doctranslator_server.db.repositories import jobs as jobs_repo
from doctranslator_server.jobs import capacity
from doctranslator_server.jobs.errors import (
    AdmissionError,
    ConflictError,
    NotFoundError,
    UnavailableError,
)
from doctranslator_server.settings import ServerSettings

WORK_OWNER = "00000000-0000-0000-0000-000000000001"


def current(session: Session, grant: HistoryGrant) -> JobResult | None:
    if grant.deleted_at is not None or grant.updated_at <= utcnow() - timedelta(days=90):
        return None
    slot = session.get(SharedSlot, grant.slot_id)
    if slot is None or slot.current_result_id is None:
        return None
    return session.get(JobResult, slot.current_result_id)


def grant_for_job(session: Session, job: Job) -> HistoryGrant | None:
    grant = session.get(HistoryGrant, job.history_id) if job.history_id else None
    return grant if grant and grant.owner_id == job.owner_id and grant.deleted_at is None else None


def compatible(slot: SharedSlot, policy: dict[str, Any]) -> bool:
    return (
        slot.current_result_id is not None
        and slot.profile == policy["profile"]
        and any(
            candidate["id"] == slot.producer
            and candidate["fingerprint"] == slot.producer_fingerprint
            for candidate in policy["candidates"]
        )
    )


def accept(
    session: Session,
    document: Document,
    target: str,
    options: dict[str, Any],
    policy: dict[str, Any],
    request_hash: str,
    submission_id: str | None,
    batch_id: str | None,
    *,
    max_attempts: int,
    settings: ServerSettings,
) -> Job:
    """Caller verified the complete source bytes before this serialized transaction."""
    now = utcnow()
    slot = session.scalar(
        select(SharedSlot).where(
            SharedSlot.source_hash == document.source_blob,
            SharedSlot.target == target,
        )
    )
    if slot is None:
        slot = SharedSlot(
            id=new_id(),
            source_hash=document.source_blob,
            target=target,
            generation=0,
            cooldowns={},
            last_used_at=now,
        )
        session.add(slot)
        session.flush()
    grant = session.scalar(
        select(HistoryGrant).where(
            HistoryGrant.owner_id == document.owner_id,
            HistoryGrant.slot_id == slot.id,
        )
    )
    if grant is not None and (
        grant.deleted_at is not None or grant.updated_at <= now - timedelta(days=90)
    ):
        # A new verified submission grants new access; old job/history URLs stay revoked.
        # Jobs intentionally retain the obsolete grant ID as historical provenance.
        for waiter in session.scalars(select(Job).where(Job.history_id == grant.id)):
            detach(session, waiter, now)
        session.delete(grant)
        session.flush()
        grant = None
    if grant is None:
        grant = HistoryGrant(
            id=new_id(),
            owner_id=document.owner_id,
            slot_id=slot.id,
            original_name=document.name,
            format=document.format,
            source=document.detected_source,
            detection=document.detection,
            created_at=now,
            updated_at=now,
        )
        session.add(grant)
    else:
        grant.original_name = document.name
        grant.updated_at = now
        grant.source, grant.detection = document.detected_source, document.detection
    candidates = list(policy["candidates"])
    reuse = compatible(slot, policy)
    if reuse:
        candidates = candidates[
            : next(i for i, c in enumerate(candidates) if c["id"] == slot.producer)
        ]
    candidates = [
        c
        for c in candidates
        if float(slot.cooldowns.get(policy["profile"] + c["fingerprint"], 0)) <= now.timestamp()
    ]
    active = session.get(Job, slot.active_work_id) if slot.active_work_id else None
    if active is not None and active.status not in jobs_repo.NONTERMINAL:
        active = None
        slot.active_work_id = None
    if active is not None and (active.cancel_requested or not interested(session, active)):
        # A new verified upload must not join work whose final waiter already left.
        # Keep its reservation until the old worker acknowledges cancellation, but fence
        # publication now so an outstanding inference response cannot win the new slot.
        jobs_repo.request_cancel(session, active.id, now)
        session.refresh(active)
        if active.status == "cancelled":
            finish(session, active, None, now)
        slot.active_work_id = None
        slot.generation += 1
        active = None
    if (
        active is not None
        and active.policy is not None
        and active.policy["digest"] != policy["digest"]
    ):
        raise ConflictError(
            "a different pinned policy is already processing this document; retry later",
            code="policy_work_active",
        )
    cached = reuse and not candidates
    reserved_work_id = new_id()
    if (
        not cached
        and active is None
        and jobs_repo.count_nonterminal(session) >= settings.max_queued_jobs
    ):
        if not reuse:
            raise AdmissionError("the service queue is full; retry later")
        cached = True
    if not cached and active is None:
        try:
            with session.begin_nested():
                capacity.reserve(
                    session,
                    settings,
                    reserved_work_id,
                    "output",
                    settings.max_output_bytes + settings.max_report_bytes,
                )
                capacity.reserve(
                    session, settings, reserved_work_id, "work", settings.max_workspace_bytes
                )
        except UnavailableError:
            if not reuse:
                raise
            cached = True
    if not cached and active is None:
        if session.get(User, WORK_OWNER) is None:
            session.add(
                User(
                    id=WORK_OWNER,
                    display_name="Shared translation worker",
                    kind="service",
                    active=True,
                )
            )
            session.flush()
        work_policy = dict(
            policy,
            detection_metadata={
                "format": document.format,
                "source": document.detected_source,
                "status": document.detection,
            },
            candidates=candidates,
            slot_id=slot.id,
            generation=slot.generation,
            reuse=slot.current_result_id if reuse else None,
        )
        active = jobs_repo.insert(
            session,
            id=reserved_work_id,
            owner_id=WORK_OWNER,
            kind="shared_work",
            retention="cached",
            original_name=f"input.{document.format}",
            format=document.format,
            input_blob=document.source_blob,
            input_size=document.size,
            target=target,
            source_requested="auto",
            options=options,
            mode="llm",
            policy=work_policy,
            fingerprint=policy["digest"],
            request_hash=request_hash,
            max_attempts=max_attempts,
            available_at=now,
            created_at=now,
        )
        slot.active_work_id = active.id
    cached_result = (
        session.get(JobResult, slot.current_result_id)
        if cached and slot.current_result_id
        else None
    )
    waiter = jobs_repo.insert(
        session,
        owner_id=document.owner_id,
        kind="waiter",
        retention="cached",
        original_name=document.name,
        format=document.format,
        input_blob=document.source_blob,
        input_size=document.size,
        target=target,
        source_requested="auto",
        source_resolved=document.detected_source,
        options=options,
        mode="llm",
        fingerprint=policy["digest"],
        request_hash=request_hash,
        submission_id=submission_id,
        batch_id=batch_id,
        history_id=grant.id,
        document_id=document.id,
        shared_work_id=None if cached else active.id if active else None,
        status="succeeded" if cached else "queued",
        cache_hit=cached,
        translator_id=slot.producer if cached else None,
        fit_status=cached_result.fit_status if cached_result else None,
        finished_at=now if cached else None,
        created_at=now,
        available_at=now,
    )
    if cached:
        slot.last_used_at = now
    # The private record ceases to retain original bytes; shared work owns its snapshot.
    document.deleted_at = now
    return waiter


def sync_waiter(session: Session, waiter: Job) -> Job:
    if waiter.kind != "waiter" or waiter.status not in jobs_repo.NONTERMINAL:
        return waiter
    work = session.get(Job, waiter.shared_work_id) if waiter.shared_work_id else None
    if work is None:
        return waiter
    for field in (
        "status",
        "phase",
        "progress_done",
        "progress_total",
        "progress_updated_at",
        "started_at",
        "finished_at",
        "error_code",
        "error_message",
        "fit_status",
        "attempts",
        "translator_id",
        "rung",
        "fingerprint",
        "cache_hit",
    ):
        setattr(waiter, field, getattr(work, field))
    return waiter


def detach(session: Session, waiter: Job, now: datetime) -> None:
    if waiter.kind != "waiter" or waiter.status not in jobs_repo.NONTERMINAL:
        return
    waiter.status, waiter.finished_at, waiter.cancel_requested = "cancelled", now, True
    session.flush()
    work_id = waiter.shared_work_id
    others = session.scalar(
        select(Job.id)
        .join(User, User.id == Job.owner_id)
        .where(
            Job.shared_work_id == work_id,
            Job.status.in_(jobs_repo.NONTERMINAL),
            User.active,
        )
        .limit(1)
    )
    if others is None and work_id:
        jobs_repo.request_cancel(session, work_id, now)
        work = session.get(Job, work_id)
        if work:
            session.refresh(work)
            if work.status == "cancelled":
                finish(session, work, None, now)


def interested(session: Session, work: Job) -> bool:
    if work.kind != "shared_work":
        return True
    return (
        session.scalar(
            select(Job.id)
            .join(User, User.id == Job.owner_id)
            .join(HistoryGrant, HistoryGrant.id == Job.history_id)
            .where(
                Job.shared_work_id == work.id,
                Job.status.in_(jobs_repo.NONTERMINAL),
                ~Job.cancel_requested,
                User.active,
                HistoryGrant.deleted_at.is_(None),
            )
            .limit(1)
        )
        is not None
    )


def owned_grant(session: Session, owner_id: str, identifier: str) -> HistoryGrant:
    grant = session.scalar(
        select(HistoryGrant).where(
            HistoryGrant.id == identifier,
            HistoryGrant.owner_id == owner_id,
            HistoryGrant.deleted_at.is_(None),
            HistoryGrant.updated_at > utcnow() - timedelta(days=90),
        )
    )
    if grant is None:
        raise NotFoundError("history")
    return grant


def finish(session: Session, work: Job, result: JobResult | None, now: datetime) -> None:
    """Called inside the existing fenced publication/terminal transaction."""
    session.execute(delete(StorageReservation).where(StorageReservation.owner_id == work.id))
    if work.kind != "shared_work" or work.policy is None:
        return
    slot = session.get(SharedSlot, work.policy["slot_id"])
    owns_slot = slot is not None and slot.active_work_id == work.id
    if result is not None and owns_slot and slot is not None:
        if slot.generation != work.policy["generation"]:
            raise ConflictError("shared publication generation changed", code="publication_fenced")
        old = session.get(JobResult, slot.current_result_id) if slot.current_result_id else None
        if old is not None and old.id != result.id:
            old.expires_at = now
        slot.current_result_id = result.id
        slot.profile = work.policy["profile"]
        if old is None or old.id != result.id:
            slot.producer = work.translator_id
            slot.producer_fingerprint = result.fingerprint
        else:
            # Failed upgrade attempts are diagnostics, not the identity of reused bytes.
            work.translator_id = slot.producer
            work.fingerprint = result.fingerprint
        slot.generation += 1
        slot.last_used_at = now
        result.expires_at = None
    if owns_slot and slot is not None:
        slot.active_work_id = None
    # A work row is provenance, not a permanent output pin.
    work.result_id = None
    for waiter in session.scalars(select(Job).where(Job.shared_work_id == work.id)):
        sync_waiter(session, waiter)
