"""Read models the job service returns to the REST adapter (never ORM objects or paths)."""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

__all__ = [
    "BatchView",
    "DocumentView",
    "FileView",
    "ItemView",
    "JobView",
    "Page",
    "SubmitResult",
]


@dataclass(frozen=True, slots=True)
class JobView:
    id: str
    batch_id: str | None
    status: str
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


@dataclass(frozen=True, slots=True)
class DocumentView:
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


@dataclass(frozen=True, slots=True)
class BatchView:
    id: str
    label: str
    state: str
    items: int
    counts: dict[str, int]
    created_at: datetime
    sealed_at: datetime | None


@dataclass(frozen=True, slots=True)
class ItemView:
    id: str
    ordinal: int
    client_item_id: str
    original_name: str
    rejection_code: str | None
    rejection_message: str | None
    job: JobView | None


@dataclass(frozen=True, slots=True)
class SubmitResult:
    job: JobView | None
    item: ItemView | None
    replayed: bool
    """True when this answers a repeated submission identity (idempotent replay)."""


@dataclass(frozen=True, slots=True)
class FileView:
    """A stored file to stream: never exposed as a path through the API."""

    path: Path
    filename: str
    media_type: str
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class Page[T]:
    items: list[T] = field(default_factory=list[T])
    next_cursor: str | None = None
