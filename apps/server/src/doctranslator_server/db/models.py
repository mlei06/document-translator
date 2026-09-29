"""ORM models (ADR-004, ADR-007, ADR-015, ADR-016). Schema changes go through Alembic migrations."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
)
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

__all__ = [
    "ApiKey",
    "AuditEvent",
    "Base",
    "Batch",
    "BatchItem",
    "Blob",
    "BlobPin",
    "Document",
    "DocumentVersion",
    "Job",
    "Lock",
    "TranslationResult",
    "User",
    "new_id",
    "utcnow",
]


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return str(uuid.uuid4())


class UtcDateTime(TypeDecorator[datetime]):
    """Timezone-aware UTC in Python; naive UTC in the database (portable to SQLite)."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        return None if value is None else value.replace(tzinfo=UTC)


NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

type Json = dict[str, Any]


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)
    type_annotation_map = {datetime: UtcDateTime, Json: JSON}  # noqa: RUF012


def _id() -> Mapped[str]:
    return mapped_column(String(36), primary_key=True, default=new_id)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("issuer", "subject"),)

    id: Mapped[str] = _id()
    display_name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(16), default="person")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    issuer: Mapped[str | None] = mapped_column(String(300))
    subject: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    disabled_at: Mapped[datetime | None]


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[str] = _id()
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    prefix: Mapped[str] = mapped_column(String(16), unique=True)
    digest: Mapped[str] = mapped_column(String(64))
    label: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    last_used_at: Mapped[datetime | None]
    revoked_at: Mapped[datetime | None]


class Blob(Base):
    """An immutable content-addressed file (ADR-007); ``state`` guards cleanup (ADR-016)."""

    __tablename__ = "blobs"

    hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    size: Mapped[int] = mapped_column(BigInteger)
    state: Mapped[str] = mapped_column(String(16), default="pending")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class BlobPin(Base):
    """Protects a blob between writing it and committing its first reference."""

    __tablename__ = "blob_pins"

    id: Mapped[str] = _id()
    hash: Mapped[str] = mapped_column(ForeignKey("blobs.hash"), index=True)
    expires_at: Mapped[datetime]


class TranslationResult(Base):
    """The shared exact-byte cache (ADR-007 layer 2). Never exposed through the API."""

    __tablename__ = "translation_results"
    __table_args__ = (UniqueConstraint("input_hash", "fingerprint"),)

    id: Mapped[str] = _id()
    input_hash: Mapped[str] = mapped_column(String(64))
    fingerprint: Mapped[str] = mapped_column(String(64))
    output_blob: Mapped[str] = mapped_column(ForeignKey("blobs.hash"), index=True)
    report_blob: Mapped[str] = mapped_column(ForeignKey("blobs.hash"), index=True)
    source_resolved: Mapped[str | None] = mapped_column(String(8))
    fit_status: Mapped[str] = mapped_column(String(32))
    engine: Mapped[Json]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    last_used_at: Mapped[datetime] = mapped_column(default=utcnow)


class Batch(Base):
    __tablename__ = "batches"
    __table_args__ = (UniqueConstraint("owner_id", "idempotency_key"),)

    id: Mapped[str] = _id()
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(36))
    label: Mapped[str] = mapped_column(String(200), default="")
    state: Mapped[str] = mapped_column(String(16), default="open")
    next_ordinal: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    sealed_at: Mapped[datetime | None]
    cancelled_at: Mapped[datetime | None]


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("owner_id", "submission_id"),
        Index("ix_jobs_claim", "status", "available_at", "created_at"),
    )

    id: Mapped[str] = _id()
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    batch_id: Mapped[str | None] = mapped_column(ForeignKey("batches.id"), index=True)
    submission_id: Mapped[str | None] = mapped_column(String(36))
    request_hash: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(16), default="translate")
    original_name: Mapped[str] = mapped_column(String(255))
    format: Mapped[str] = mapped_column(String(8))
    input_blob: Mapped[str] = mapped_column(ForeignKey("blobs.hash"), index=True)
    input_size: Mapped[int] = mapped_column(BigInteger)
    options: Mapped[Json]
    """Canonical ``DocumentTranslationOptions`` JSON."""
    mode: Mapped[str] = mapped_column(String(8))
    source_requested: Mapped[str] = mapped_column(String(8))
    source_resolved: Mapped[str | None] = mapped_column(String(8))
    target: Mapped[str] = mapped_column(String(8))
    fingerprint: Mapped[str] = mapped_column(String(64))
    force: Mapped[bool] = mapped_column(Boolean, default=False)

    status: Mapped[str] = mapped_column(String(16), default="queued")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    available_at: Mapped[datetime] = mapped_column(default=utcnow)
    claim_token: Mapped[str | None] = mapped_column(String(32))
    worker_id: Mapped[str | None] = mapped_column(String(64))
    lease_until: Mapped[datetime | None]
    heartbeat_at: Mapped[datetime | None]
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    phase: Mapped[str | None] = mapped_column(String(16))
    progress_done: Mapped[int] = mapped_column(Integer, default=0)
    progress_total: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    cache_hit: Mapped[bool] = mapped_column(Boolean, default=False)
    result_id: Mapped[str | None] = mapped_column(
        ForeignKey("translation_results.id", ondelete="SET NULL")
    )
    fit_status: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]


class BatchItem(Base):
    """A batch member: an accepted job or a recorded rejection."""

    __tablename__ = "batch_items"
    __table_args__ = (
        UniqueConstraint("batch_id", "client_item_id"),
        UniqueConstraint("batch_id", "ordinal"),
    )

    id: Mapped[str] = _id()
    batch_id: Mapped[str] = mapped_column(ForeignKey("batches.id"), index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    client_item_id: Mapped[str] = mapped_column(String(36))
    original_name: Mapped[str] = mapped_column(String(255))
    request_hash: Mapped[str] = mapped_column(String(64))
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id"), index=True)
    rejection_code: Mapped[str | None] = mapped_column(String(64))
    rejection_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = _id()
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), unique=True)
    original_name: Mapped[str] = mapped_column(String(255))
    format: Mapped[str] = mapped_column(String(8))
    original_blob: Mapped[str] = mapped_column(ForeignKey("blobs.hash"), index=True)
    source_requested: Mapped[str] = mapped_column(String(8))
    source_resolved: Mapped[str | None] = mapped_column(String(8))
    target: Mapped[str] = mapped_column(String(8))
    mode: Mapped[str] = mapped_column(String(8))
    fingerprint: Mapped[str] = mapped_column(String(64))
    result_id: Mapped[str | None] = mapped_column(
        ForeignKey("translation_results.id", ondelete="SET NULL")
    )
    fit_status: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    expires_at: Mapped[datetime]


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    __table_args__ = (UniqueConstraint("document_id", "version_no"),)

    id: Mapped[str] = _id()
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    version_no: Mapped[int] = mapped_column(Integer)
    output_blob: Mapped[str] = mapped_column(ForeignKey("blobs.hash"), index=True)
    report_blob: Mapped[str] = mapped_column(ForeignKey("blobs.hash"), index=True)
    parent_version_id: Mapped[str | None] = mapped_column(ForeignKey("document_versions.id"))
    created_by: Mapped[str] = mapped_column(String(16), default="translation")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    actor_user_id: Mapped[str | None] = mapped_column(String(36))
    action: Mapped[str] = mapped_column(String(64))
    target_type: Mapped[str | None] = mapped_column(String(32))
    target_id: Mapped[str | None] = mapped_column(String(64))
    outcome: Mapped[str] = mapped_column(String(64), default="ok")


class Lock(Base):
    """A named lease (the GC/backup exclusion of ADR-016)."""

    __tablename__ = "locks"

    name: Mapped[str] = mapped_column(String(32), primary_key=True)
    holder: Mapped[str] = mapped_column(String(64))
    until: Mapped[datetime]
