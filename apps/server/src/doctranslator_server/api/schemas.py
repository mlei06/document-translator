"""REST wire schemas (``/v1``). Distinct from ORM models and core types (ADR-003)."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from doctranslator_server.jobs.views import BatchView, DocumentView, ItemView, JobView

__all__ = [
    "BatchCreate",
    "BatchOut",
    "BatchPage",
    "Capabilities",
    "DocumentOut",
    "DocumentPage",
    "ErrorOut",
    "ItemOut",
    "ItemPage",
    "JobOut",
    "JobPage",
    "Me",
    "SubmitOptionsIn",
]


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ErrorOut(BaseModel):
    code: str
    message: str
    request_id: str
    retryable: bool = False
    details: dict[str, object] = Field(default_factory=dict)


class Me(BaseModel):
    id: str
    display_name: str
    kind: Literal["person", "service"]


class Capabilities(BaseModel):
    formats: list[str]
    modes: list[str]
    languages: list[str]
    fit_statuses: list[str]
    limits: dict[str, int]
    fit_defaults: dict[str, float]
    service_version: str
    core_version: str


class SubmitOptionsIn(BaseModel):
    """The ``options`` form field (JSON) of a submission."""

    model_config = ConfigDict(extra="forbid")

    target: str
    source: str = "auto"
    mode: str | None = None
    protected_terms: list[str] = Field(default_factory=list[str], max_length=500)
    txt_encoding: str | None = None
    min_scale: float | None = None
    min_size_pt: float | None = None
    force_retranslate: bool = False


class BatchCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: UUID
    label: str = Field(default="", max_length=200)


class JobOut(_Out):
    id: str
    batch_id: str | None
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"]
    original_name: str
    format: str
    mode: str
    source_requested: str
    source_resolved: str | None
    target: str
    fingerprint: str
    force: bool
    attempts: int
    phase: str | None
    progress_done: int
    progress_total: int
    cancel_requested: bool
    cache_hit: bool
    error_code: str | None
    error_message: str | None
    document_id: str | None
    fit_status: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None

    @classmethod
    def of(cls, view: JobView) -> JobOut:
        return cls.model_validate(view)


class ItemOut(_Out):
    id: str
    ordinal: int
    client_item_id: str
    original_name: str
    rejection_code: str | None
    rejection_message: str | None
    job: JobOut | None

    @classmethod
    def of(cls, view: ItemView) -> ItemOut:
        return cls(
            id=view.id,
            ordinal=view.ordinal,
            client_item_id=view.client_item_id,
            original_name=view.original_name,
            rejection_code=view.rejection_code,
            rejection_message=view.rejection_message,
            job=JobOut.of(view.job) if view.job else None,
        )


class BatchOut(_Out):
    id: str
    label: str
    state: Literal["open", "sealed", "cancelled"]
    items: int
    counts: dict[str, int]
    created_at: datetime
    sealed_at: datetime | None

    @classmethod
    def of(cls, view: BatchView) -> BatchOut:
        return cls.model_validate(view)


class DocumentOut(_Out):
    id: str
    job_id: str
    original_name: str
    format: str
    mode: str
    source_requested: str
    source_resolved: str | None
    target: str
    fit_status: str
    version: int
    output_size: int
    output_sha256: str
    created_at: datetime
    expires_at: datetime

    @classmethod
    def of(cls, view: DocumentView) -> DocumentOut:
        return cls.model_validate(view)


class JobPage(BaseModel):
    items: list[JobOut]
    next_cursor: str | None


class BatchPage(BaseModel):
    items: list[BatchOut]
    next_cursor: str | None


class ItemPage(BaseModel):
    items: list[ItemOut]
    next_cursor: str | None


class DocumentPage(BaseModel):
    items: list[DocumentOut]
    next_cursor: str | None
