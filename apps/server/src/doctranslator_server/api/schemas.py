"""REST wire schemas (``/v1``). Distinct from ORM models and core types (ADR-003)."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from doctranslator_server.jobs.views import (
    BatchView,
    DocumentView,
    ItemView,
    JobView,
)

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
    "ProgressOut",
    "SessionCreate",
    "SessionOut",
    "SubmitOptionsIn",
    "TranslateIn",
    "TranslationOut",
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
    kind: Literal["human", "service"]
    storage_used_bytes: int
    storage_quota_bytes: int


class SessionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=200)
    """A provisioned API key; exchanged once for a session and never stored by the browser."""


class SessionOut(BaseModel):
    user: Me
    csrf_token: str
    """Send as ``X-CSRF-Token`` on every state-changing request made with the session cookie."""
    expires_at: datetime


class Capabilities(BaseModel):
    formats: list[str]
    modes: list[str]
    languages: list[str]
    fit_statuses: list[str]
    retention: list[str]
    limits: dict[str, int]
    fit_defaults: dict[str, float]
    service_version: str
    core_version: str


class SubmitOptionsIn(BaseModel):
    """Translation options (the ``options`` form field of uploads, or the JSON body fields)."""

    model_config = ConfigDict(extra="forbid")

    target: str
    source: str = "auto"
    mode: str | None = None
    protected_terms: list[str] = Field(default_factory=list[str], max_length=500)
    txt_encoding: str | None = None
    min_scale: float | None = None
    min_size_pt: float | None = None
    force_retranslate: bool = False
    """Translate again even when the document's current translation is compatible."""
    retention: Literal["saved", "temporary"] = "saved"


class TranslateIn(SubmitOptionsIn):
    """Translate a saved document: options plus exactly one submission identity."""

    submission_id: UUID | None = None
    batch_id: str | None = None
    client_item_id: UUID | None = None


class BatchCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: UUID
    label: str = Field(default="", max_length=200)


class ProgressOut(_Out):
    phase: Literal["prepare", "extract", "translate", "apply", "fit", "write"]
    done: int | None
    total: int | None
    updated_at: datetime | None


class JobOut(_Out):
    id: str
    batch_id: str | None
    document_id: str | None
    retention: Literal["saved", "temporary"]
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
    progress: ProgressOut | None
    cancel_requested: bool
    fit_skip_requested: bool
    cache_hit: bool
    error_code: str | None
    error_message: str | None
    fit_status: str | None
    result_available: bool
    result_expires_at: datetime | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    dismissed_at: datetime | None

    @classmethod
    def of(cls, view: JobView) -> JobOut:
        return cls.model_validate(view)


class TranslationOut(_Out):
    id: str
    source: str | None
    target: str
    fit_status: str
    job_id: str
    output_size: int
    output_sha256: str
    updated_at: datetime


class DocumentOut(_Out):
    id: str
    name: str
    format: str
    size: int
    sha256: str
    detected_source: str | None
    detection: Literal["detected", "ambiguous", "no_text"]
    external_ref: str | None
    created_at: datetime
    translations: list[TranslationOut]
    active_jobs: dict[str, str]

    @classmethod
    def of(cls, view: DocumentView) -> DocumentOut:
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
        return cls.model_validate(view)


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
