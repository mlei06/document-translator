"""Read models the job service returns to the REST adapter (never ORM objects or paths)."""

from collections.abc import Callable
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
    "ProgressView",
    "SubmitResult",
    "TranslationView",
]


@dataclass(frozen=True, slots=True)
class ProgressView:
    """The latest stored progress snapshot (P5-P6 progress plan). Counts are only reported for
    the translate phase; other phases are indeterminate."""

    phase: str
    done: int | None
    total: int | None
    updated_at: datetime | None


@dataclass(frozen=True, slots=True)
class JobView:
    """Historical request progress/provenance, with live authorized download availability.

    A cached website job's file may later be upgraded independently of this request's
    translator and fit diagnostics. History/download resolution follows the current slot.
    """

    id: str
    batch_id: str | None
    document_id: str | None
    retention: str
    status: str
    original_name: str
    format: str
    mode: str
    translator_id: str | None
    source_requested: str
    source_resolved: str | None
    target: str
    fingerprint: str
    force: bool
    attempts: int
    progress: ProgressView | None
    cancel_requested: bool
    fit_skip_requested: bool
    cache_hit: bool
    error_code: str | None
    error_message: str | None
    fit_status: str | None
    result_available: bool
    """The authorized output is available (current shared output for website waiters)."""
    result_expires_at: datetime | None
    """When the job's output stops being downloadable (``None``: while it is current)."""
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    dismissed_at: datetime | None
    fallback: str | None = None


@dataclass(frozen=True, slots=True)
class TranslationView:
    """A saved document's current translation for one language pair (ADR-014)."""

    id: str
    source: str | None
    target: str
    fit_status: str
    job_id: str
    """The job that produced the current result."""
    output_size: int
    output_sha256: str
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class DocumentView:
    """An owned source document in the library, with its current translations."""

    id: str
    name: str
    format: str
    size: int
    sha256: str
    detected_source: str | None
    detection: str
    external_ref: str | None
    created_at: datetime
    translations: list[TranslationView]
    active_jobs: dict[str, str]
    """Unfinished job per target language (at most one each, ADR-014)."""


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
    on_complete: Callable[[], None] | None = None


@dataclass(frozen=True, slots=True)
class Page[T]:
    items: list[T] = field(default_factory=list[T])
    next_cursor: str | None = None
