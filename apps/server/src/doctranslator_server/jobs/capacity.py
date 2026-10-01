"""Transactional global reservations and bounded shared-result eviction."""

import shutil
from datetime import timedelta

from sqlalchemy import delete, exists, func, select
from sqlalchemy.orm import Session

from doctranslator_server.db.models import (
    Blob,
    BlobPin,
    Job,
    JobResult,
    SharedSlot,
    StorageReservation,
    new_id,
    utcnow,
)
from doctranslator_server.jobs.errors import UnavailableError
from doctranslator_server.settings import ServerSettings


def reserve(session: Session, settings: ServerSettings, owner: str, purpose: str, size: int) -> str:
    now = utcnow()
    session.execute(
        delete(StorageReservation).where(
            StorageReservation.expires_at <= now,
            ~exists().where(
                Job.id == StorageReservation.owner_id, Job.status.in_(("queued", "running"))
            ),
        )
    )
    used = int(session.scalar(select(func.coalesce(func.sum(Blob.size), 0))) or 0)
    pending = int(
        session.scalar(
            select(func.coalesce(func.sum(StorageReservation.bytes), 0)).where(
                StorageReservation.purpose != "work"
            )
        )
        or 0
    )
    working = int(
        session.scalar(
            select(func.coalesce(func.sum(StorageReservation.bytes), 0)).where(
                StorageReservation.purpose == "work"
            )
        )
        or 0
    )
    disk = shutil.disk_usage(settings.data_dir)
    floor = max(5 << 30, disk.total // 10)
    exhausted = (
        working + size > settings.global_work_budget_bytes
        if purpose == "work"
        else used + pending + size > settings.global_blob_budget_bytes
    )
    if exhausted or disk.free - size - pending - working < floor:
        raise UnavailableError(
            "storage capacity is temporarily unavailable; retry later", code="storage_capacity"
        )
    identifier = new_id()
    session.add(
        StorageReservation(
            id=identifier,
            owner_id=owner,
            purpose=purpose,
            bytes=size,
            expires_at=now + timedelta(hours=24),
        )
    )
    return identifier


def release(session: Session, identifier: str) -> None:
    session.execute(delete(StorageReservation).where(StorageReservation.id == identifier))


def consume_output(session: Session, owner: str, size: int) -> None:
    reservation = session.scalar(
        select(StorageReservation).where(
            StorageReservation.owner_id == owner, StorageReservation.purpose == "output"
        )
    )
    if reservation is not None:
        reservation.bytes = max(0, reservation.bytes - size)
        session.flush()


def expire_slots(
    session: Session, settings: ServerSettings, *, protected_slot: str | None = None
) -> int:
    now = utcnow()
    used = int(session.scalar(select(func.coalesce(func.sum(Blob.size), 0))) or 0)
    pending = int(
        session.scalar(
            select(func.coalesce(func.sum(StorageReservation.bytes), 0)).where(
                StorageReservation.purpose != "work"
            )
        )
        or 0
    )
    pressure = used + pending >= settings.global_blob_budget_bytes * 0.9
    released = 0
    count = 0
    for slot in session.scalars(
        select(SharedSlot)
        .where(SharedSlot.current_result_id.is_not(None), SharedSlot.active_work_id.is_(None))
        .order_by(SharedSlot.last_used_at)
        .limit(500)
    ):
        if slot.id == protected_slot:
            # A verified upload may reuse this sole good copy if its upgrade cannot
            # reserve space. Do not finance that upgrade by evicting its fallback.
            continue
        expired = slot.last_used_at <= now - timedelta(days=30)
        if not expired and (
            not pressure or used + pending - released <= settings.global_blob_budget_bytes * 0.8
        ):
            continue
        result = session.get(JobResult, slot.current_result_id)
        if result is None:
            slot.current_result_id = None
            continue
        pinned = session.scalar(
            select(BlobPin.id)
            .where(
                BlobPin.hash.in_((result.output_blob, result.report_blob)), BlobPin.expires_at > now
            )
            .limit(1)
        )
        if pinned:
            continue
        for digest in (result.output_blob, result.report_blob):
            blob = session.get(Blob, digest)
            released += blob.size if blob else 0
        result.expires_at = now
        slot.current_result_id = None
        slot.generation += 1
        count += 1
    return count
