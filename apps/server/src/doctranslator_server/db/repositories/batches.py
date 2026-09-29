"""Batches and their members (P5): a grouping of independent outcomes, not a queue."""

from datetime import datetime
from typing import Any

from sqlalchemy import and_, delete, func, select, update
from sqlalchemy.orm import Session

from doctranslator_server.db.models import Batch, BatchItem, Document, Job

__all__ = [
    "add_item",
    "by_key",
    "counts",
    "create",
    "delete_old",
    "get_owned",
    "item_by_client_id",
    "items",
    "list_owned",
    "set_state",
]


def by_key(session: Session, owner_id: str, key: str) -> Batch | None:
    return session.scalar(
        select(Batch).where(Batch.owner_id == owner_id, Batch.idempotency_key == key)
    )


def create(session: Session, owner_id: str, key: str, label: str, now: datetime) -> Batch:
    batch = Batch(owner_id=owner_id, idempotency_key=key, label=label, created_at=now)
    session.add(batch)
    session.flush()
    return batch


def get_owned(session: Session, owner_id: str, batch_id: str) -> Batch | None:
    return session.scalar(select(Batch).where(Batch.id == batch_id, Batch.owner_id == owner_id))


def list_owned(
    session: Session, owner_id: str, *, after: tuple[datetime, str] | None, limit: int
) -> list[Batch]:
    query = select(Batch).where(Batch.owner_id == owner_id)
    if after is not None:
        created, ident = after
        query = query.where(
            (Batch.created_at < created) | and_(Batch.created_at == created, Batch.id < ident)
        )
    return list(
        session.scalars(query.order_by(Batch.created_at.desc(), Batch.id.desc()).limit(limit))
    )


def item_by_client_id(session: Session, batch_id: str, client_item_id: str) -> BatchItem | None:
    return session.scalar(
        select(BatchItem).where(
            BatchItem.batch_id == batch_id, BatchItem.client_item_id == client_item_id
        )
    )


def add_item(session: Session, batch: Batch, **fields: Any) -> BatchItem:
    ordinal = batch.next_ordinal
    batch.next_ordinal = ordinal + 1
    item = BatchItem(batch_id=batch.id, ordinal=ordinal, **fields)
    session.add(item)
    session.flush()
    return item


def items(
    session: Session, batch_id: str, *, after: int | None, limit: int, client_item_id: str | None
) -> list[tuple[BatchItem, Job | None, Document | None]]:
    query = (
        select(BatchItem, Job, Document)
        .outerjoin(Job, Job.id == BatchItem.job_id)
        .outerjoin(Document, Document.job_id == Job.id)
        .where(BatchItem.batch_id == batch_id)
    )
    if client_item_id is not None:
        query = query.where(BatchItem.client_item_id == client_item_id)
    if after is not None:
        query = query.where(BatchItem.ordinal > after)
    rows = session.execute(query.order_by(BatchItem.ordinal).limit(limit)).all()
    return [(row[0], row[1], row[2]) for row in rows]


def counts(session: Session, batch_id: str) -> dict[str, int]:
    """Members by outcome: ``rejected`` or the job status."""
    rejected = session.scalar(
        select(func.count())
        .select_from(BatchItem)
        .where(BatchItem.batch_id == batch_id, BatchItem.job_id.is_(None))
    )
    result = {"rejected": int(rejected or 0)}
    rows = session.execute(
        select(Job.status, func.count())
        .join(BatchItem, BatchItem.job_id == Job.id)
        .where(BatchItem.batch_id == batch_id)
        .group_by(Job.status)
    ).all()
    for status, count in rows:
        result[str(status)] = int(count)
    return result


def set_state(session: Session, batch_id: str, state: str, now: datetime) -> None:
    values: dict[str, Any] = {"state": state}
    if state in ("sealed", "cancelled"):
        values["sealed_at"] = now
    if state == "cancelled":
        values["cancelled_at"] = now
    session.execute(
        update(Batch)
        .where(Batch.id == batch_id, Batch.state != "cancelled")
        .values(**values)
        .execution_options(synchronize_session=False)
    )


def delete_old(session: Session, before: datetime) -> int:
    """Batches created before ``before`` whose jobs all finished before it and left no document,
    with their members and jobs (ADR-016 retention)."""
    unfinished = (
        select(Job.id)
        .where(
            Job.batch_id == Batch.id,
            Job.status.in_(("queued", "running")) | (Job.finished_at >= before),
        )
        .exists()
    )
    documented = (
        select(Document.id).join(Job, Job.id == Document.job_id).where(Job.batch_id == Batch.id)
    ).exists()
    old = list(
        session.scalars(select(Batch.id).where(Batch.created_at < before, ~unfinished, ~documented))
    )
    for batch_id in old:
        session.execute(delete(BatchItem).where(BatchItem.batch_id == batch_id))
        session.execute(delete(Job).where(Job.batch_id == batch_id))
        session.execute(delete(Batch).where(Batch.id == batch_id))
    return len(old)
