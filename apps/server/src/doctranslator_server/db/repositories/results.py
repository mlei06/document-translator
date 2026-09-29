"""The shared exact-byte cache (ADR-007 layer 2) and user documents with their versions."""

from datetime import datetime
from typing import Any

from sqlalchemy import and_, delete, select, update
from sqlalchemy.orm import Session

from doctranslator_server.db.models import (
    Document,
    DocumentVersion,
    Job,
    TranslationResult,
)
from doctranslator_server.db.repositories._rows import rowcount

__all__ = [
    "add_document",
    "delete_document",
    "delete_expired_documents",
    "delete_stale_results",
    "document_for_job",
    "get_document_owned",
    "list_documents",
    "lookup",
    "store_result",
    "touch",
    "version",
]


def lookup(session: Session, input_hash: str, fingerprint: str) -> TranslationResult | None:
    return session.scalar(
        select(TranslationResult).where(
            TranslationResult.input_hash == input_hash,
            TranslationResult.fingerprint == fingerprint,
        )
    )


def touch(session: Session, result_id: str, now: datetime) -> None:
    session.execute(
        update(TranslationResult).where(TranslationResult.id == result_id).values(last_used_at=now)
    )


def store_result(
    session: Session,
    *,
    input_hash: str,
    fingerprint: str,
    output_blob: str,
    report_blob: str,
    source_resolved: str | None,
    fit_status: str,
    engine: dict[str, Any],
    force: bool,
    now: datetime,
) -> TranslationResult:
    """Cache a successful output: the first ordinary winner stays; a forced run replaces it."""
    existing = lookup(session, input_hash, fingerprint)
    if existing is not None and not force:
        existing.last_used_at = now
        return existing
    if existing is not None:
        existing.output_blob = output_blob
        existing.report_blob = report_blob
        existing.source_resolved = source_resolved
        existing.fit_status = fit_status
        existing.engine = engine
        existing.created_at = now
        existing.last_used_at = now
        return existing
    result = TranslationResult(
        input_hash=input_hash,
        fingerprint=fingerprint,
        output_blob=output_blob,
        report_blob=report_blob,
        source_resolved=source_resolved,
        fit_status=fit_status,
        engine=engine,
        created_at=now,
        last_used_at=now,
    )
    session.add(result)
    session.flush()
    return result


def delete_stale_results(session: Session, unused_before: datetime) -> int:
    return rowcount(
        session.execute(
            delete(TranslationResult).where(TranslationResult.last_used_at < unused_before)
        )
    )


def add_document(
    session: Session,
    job: Job,
    *,
    result_id: str | None,
    source_resolved: str | None,
    fit_status: str,
    output_blob: str,
    report_blob: str,
    now: datetime,
    expires_at: datetime,
) -> Document:
    document = Document(
        owner_id=job.owner_id,
        job_id=job.id,
        original_name=job.original_name,
        format=job.format,
        original_blob=job.input_blob,
        source_requested=job.source_requested,
        source_resolved=source_resolved,
        target=job.target,
        mode=job.mode,
        fingerprint=job.fingerprint,
        result_id=result_id,
        fit_status=fit_status,
        created_at=now,
        expires_at=expires_at,
    )
    session.add(document)
    session.flush()
    session.add(
        DocumentVersion(
            document_id=document.id,
            version_no=0,
            output_blob=output_blob,
            report_blob=report_blob,
            created_by="translation",
            created_at=now,
        )
    )
    return document


def get_document_owned(session: Session, owner_id: str, document_id: str) -> Document | None:
    return session.scalar(
        select(Document).where(Document.id == document_id, Document.owner_id == owner_id)
    )


def document_for_job(session: Session, job_id: str) -> Document | None:
    return session.scalar(select(Document).where(Document.job_id == job_id))


def version(session: Session, document_id: str, version_no: int) -> DocumentVersion | None:
    return session.scalar(
        select(DocumentVersion).where(
            DocumentVersion.document_id == document_id, DocumentVersion.version_no == version_no
        )
    )


def list_documents(
    session: Session, owner_id: str, *, after: tuple[datetime, str] | None, limit: int
) -> list[Document]:
    query = select(Document).where(Document.owner_id == owner_id)
    if after is not None:
        created, ident = after
        query = query.where(
            (Document.created_at < created)
            | and_(Document.created_at == created, Document.id < ident)
        )
    return list(
        session.scalars(query.order_by(Document.created_at.desc(), Document.id.desc()).limit(limit))
    )


def delete_document(session: Session, document: Document) -> None:
    session.execute(delete(DocumentVersion).where(DocumentVersion.document_id == document.id))
    session.execute(delete(Document).where(Document.id == document.id))


def delete_expired_documents(session: Session, now: datetime) -> int:
    expired = list(session.scalars(select(Document).where(Document.expires_at <= now)))
    for document in expired:
        delete_document(session, document)
    return len(expired)
