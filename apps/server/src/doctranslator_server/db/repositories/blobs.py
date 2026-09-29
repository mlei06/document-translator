"""Blob rows, pins and the reference-safe cleanup predicates (ADR-016)."""

from datetime import datetime

from sqlalchemy import ColumnElement, delete, exists, or_, select, update
from sqlalchemy.orm import InstrumentedAttribute, Session

from doctranslator_server.db.models import (
    Blob,
    BlobPin,
    Document,
    Job,
    JobResult,
    new_id,
)
from doctranslator_server.db.repositories._rows import rowcount

__all__ = [
    "delete_deleting",
    "delete_expired_pins",
    "get",
    "mark_available",
    "mark_deleting",
    "pin",
    "referenced_hashes",
    "release_pins",
    "unreferenced",
]


def get(session: Session, digest: str) -> Blob | None:
    return session.get(Blob, digest)


def pin(session: Session, digest: str, size: int, expires_at: datetime) -> str | None:
    """Register ``digest`` (pending if new) and pin it; ``None`` while it is being deleted."""
    blob = session.get(Blob, digest)
    if blob is None:
        session.add(Blob(hash=digest, size=size, state="pending"))
        session.flush()
    elif blob.state == "deleting":
        return None
    pin_id = new_id()
    session.add(BlobPin(id=pin_id, hash=digest, expires_at=expires_at))
    return pin_id


def mark_available(session: Session, digest: str) -> None:
    session.execute(
        update(Blob).where(Blob.hash == digest, Blob.state == "pending").values(state="available")
    )


def release_pins(session: Session, pin_ids: list[str]) -> None:
    if pin_ids:
        session.execute(delete(BlobPin).where(BlobPin.id.in_(pin_ids)))


def _referenced(digest: InstrumentedAttribute[str]) -> ColumnElement[bool]:
    return or_(
        exists().where(Job.input_blob == digest),
        exists().where(Document.source_blob == digest),
        exists().where(JobResult.output_blob == digest),
        exists().where(JobResult.report_blob == digest),
        exists().where(JobResult.preview_blob == digest),
    )


def _collectable(now: datetime, pending_before: datetime) -> ColumnElement[bool]:
    return (
        or_(
            Blob.state == "available",
            (Blob.state == "pending") & (Blob.created_at < pending_before),
        )
        & ~_referenced(Blob.hash)
        & ~exists().where(BlobPin.hash == Blob.hash, BlobPin.expires_at > now)
    )


def unreferenced(session: Session, now: datetime, pending_before: datetime) -> list[str]:
    """Candidates for deletion (re-checked by ``mark_deleting``)."""
    return list(session.scalars(select(Blob.hash).where(_collectable(now, pending_before))))


def mark_deleting(session: Session, digest: str, now: datetime, pending_before: datetime) -> bool:
    """Atomically prove the blob unreferenced and unpinned, and claim it for deletion."""
    result = session.execute(
        update(Blob)
        .where(Blob.hash == digest, _collectable(now, pending_before))
        .values(state="deleting")
        .execution_options(synchronize_session=False)
    )
    return rowcount(result) == 1


def delete_deleting(session: Session, digest: str) -> None:
    session.execute(delete(BlobPin).where(BlobPin.hash == digest))
    session.execute(delete(Blob).where(Blob.hash == digest, Blob.state == "deleting"))


def delete_expired_pins(session: Session, now: datetime) -> int:
    return rowcount(session.execute(delete(BlobPin).where(BlobPin.expires_at <= now)))


def referenced_hashes(session: Session) -> dict[str, int]:
    """Every blob some row references, with its size (for backups)."""
    return {
        blob.hash: blob.size for blob in session.scalars(select(Blob).where(_referenced(Blob.hash)))
    }
