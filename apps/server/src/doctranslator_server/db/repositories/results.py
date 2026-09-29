"""Owned source documents, their current translations and immutable job results (ADR-014)."""

from datetime import datetime
from typing import Any

from sqlalchemy import and_, delete, exists, func, select, update
from sqlalchemy.orm import Session

from doctranslator_server.db.models import (
    Blob,
    Document,
    DocumentTranslation,
    Job,
    JobResult,
)
from doctranslator_server.db.repositories._rows import rowcount

__all__ = [
    "add_document",
    "add_result",
    "delete_expired_results",
    "delete_slot",
    "document_by_blob",
    "get_document_owned",
    "get_result",
    "list_documents",
    "mark_document_deleted",
    "purge_deleted_documents",
    "reusable_result",
    "set_current",
    "slot_owned",
    "slots_of",
    "storage_used",
]


# Documents


def add_document(session: Session, **fields: Any) -> Document:
    document = Document(**fields)
    session.add(document)
    session.flush()
    return document


def document_by_blob(session: Session, owner_id: str, blob: str) -> Document | None:
    """The owner's existing (not deleted) document for these bytes, newest first."""
    return session.scalar(
        select(Document)
        .where(
            Document.owner_id == owner_id,
            Document.source_blob == blob,
            Document.deleted_at.is_(None),
        )
        .order_by(Document.created_at.desc())
        .limit(1)
    )


def get_document_owned(session: Session, owner_id: str, document_id: str) -> Document | None:
    return session.scalar(
        select(Document).where(
            Document.id == document_id,
            Document.owner_id == owner_id,
            Document.deleted_at.is_(None),
        )
    )


def list_documents(
    session: Session,
    owner_id: str,
    *,
    after: tuple[datetime, str] | None,
    limit: int,
    query: str | None = None,
) -> list[Document]:
    """Newest first; ``query`` matches names case-insensitively."""
    statement = select(Document).where(Document.owner_id == owner_id, Document.deleted_at.is_(None))
    if query:
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        statement = statement.where(Document.name.ilike(f"%{escaped}%", escape="\\"))
    if after is not None:
        created, ident = after
        statement = statement.where(
            (Document.created_at < created)
            | and_(Document.created_at == created, Document.id < ident)
        )
    return list(
        session.scalars(
            statement.order_by(Document.created_at.desc(), Document.id.desc()).limit(limit)
        )
    )


def mark_document_deleted(session: Session, document: Document, now: datetime) -> None:
    """Delete the source and all its translations from the owner's library.

    Job downloads of this document stop at once because they check the document (ADR-014).
    """
    for slot in slots_of(session, document.id):
        delete_slot(session, slot, now)
    document.deleted_at = now


def storage_used(session: Session, owner_id: str) -> int:
    """Bytes the owner's saved library holds: sources plus current translation outputs."""
    sources = session.scalar(
        select(func.coalesce(func.sum(Document.size), 0)).where(
            Document.owner_id == owner_id, Document.deleted_at.is_(None)
        )
    )
    outputs = session.scalar(
        select(func.coalesce(func.sum(Blob.size), 0))
        .select_from(DocumentTranslation)
        .join(Document, Document.id == DocumentTranslation.document_id)
        .join(JobResult, JobResult.id == DocumentTranslation.current_result_id)
        .join(Blob, Blob.hash == JobResult.output_blob)
        .where(Document.owner_id == owner_id, Document.deleted_at.is_(None))
    )
    return int(sources or 0) + int(outputs or 0)


# Results and current translations


def add_result(session: Session, **fields: Any) -> JobResult:
    result = JobResult(**fields)
    session.add(result)
    session.flush()
    return result


def get_result(session: Session, result_id: str) -> JobResult | None:
    return session.get(JobResult, result_id)


def reusable_result(
    session: Session, document_id: str, target: str, fingerprint: str
) -> JobResult | None:
    """The document's current translation to ``target`` if it was produced with exactly this
    fingerprint and completed its fit (a skipped fit is never reused)."""
    return session.scalar(
        select(JobResult)
        .join(DocumentTranslation, DocumentTranslation.current_result_id == JobResult.id)
        .where(
            DocumentTranslation.document_id == document_id,
            DocumentTranslation.target == target,
            JobResult.fingerprint == fingerprint,
            JobResult.fit_status != "skipped",
        )
        .limit(1)
    )


def slots_of(session: Session, document_id: str) -> list[DocumentTranslation]:
    return list(
        session.scalars(
            select(DocumentTranslation)
            .where(DocumentTranslation.document_id == document_id)
            .order_by(DocumentTranslation.target, DocumentTranslation.source)
        )
    )


def slot_owned(
    session: Session, owner_id: str, document_id: str, slot_id: str
) -> DocumentTranslation | None:
    return session.scalar(
        select(DocumentTranslation)
        .join(Document, Document.id == DocumentTranslation.document_id)
        .where(
            DocumentTranslation.id == slot_id,
            DocumentTranslation.document_id == document_id,
            Document.owner_id == owner_id,
            Document.deleted_at.is_(None),
        )
    )


def set_current(
    session: Session,
    document_id: str,
    source: str,
    target: str,
    result: JobResult,
    now: datetime,
    superseded_until: datetime,
) -> None:
    """Make ``result`` the current translation; the previous one keeps serving its jobs until
    ``superseded_until``."""
    slot = session.scalar(
        select(DocumentTranslation).where(
            DocumentTranslation.document_id == document_id,
            DocumentTranslation.source == source,
            DocumentTranslation.target == target,
        )
    )
    result.expires_at = None
    if slot is None:
        session.add(
            DocumentTranslation(
                document_id=document_id,
                source=source,
                target=target,
                current_result_id=result.id,
                created_at=now,
                updated_at=now,
            )
        )
        return
    if slot.current_result_id != result.id:
        session.execute(
            update(JobResult)
            .where(JobResult.id == slot.current_result_id)
            .values(expires_at=superseded_until)
        )
        slot.current_result_id = result.id
        slot.updated_at = now


def delete_slot(session: Session, slot: DocumentTranslation, now: datetime) -> None:
    """Remove one language's current translation; job downloads of it end now."""
    session.execute(
        update(JobResult).where(JobResult.id == slot.current_result_id).values(expires_at=now)
    )
    session.execute(delete(DocumentTranslation).where(DocumentTranslation.id == slot.id))


def delete_expired_results(session: Session, now: datetime) -> int:
    """Results past their expiry that are nobody's current translation."""
    current = exists().where(DocumentTranslation.current_result_id == JobResult.id)
    expired = list(
        session.scalars(
            select(JobResult.id).where(
                JobResult.expires_at.is_not(None), JobResult.expires_at <= now, ~current
            )
        )
    )
    if not expired:
        return 0
    session.execute(update(Job).where(Job.result_id.in_(expired)).values(result_id=None))
    return rowcount(session.execute(delete(JobResult).where(JobResult.id.in_(expired))))


def purge_deleted_documents(session: Session) -> int:
    """Remove deleted documents once no job refers to them (their bytes can then be freed)."""
    referenced = exists().where(Job.document_id == Document.id)
    gone = list(
        session.scalars(select(Document.id).where(Document.deleted_at.is_not(None), ~referenced))
    )
    if not gone:
        return 0
    return rowcount(session.execute(delete(Document).where(Document.id.in_(gone))))
