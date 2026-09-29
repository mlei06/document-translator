"""The job service: submission, batches, owned history and downloads (P5, ADR-007/015/016).

Every method takes the authenticated owner ID from the caller and filters by it in the database;
absent and other-user resources both raise ``NotFoundError``.
"""

import base64
import hashlib
import json
import logging
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, BinaryIO

from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from doctranslator_core import DocumentLimits, inspect_document
from doctranslator_core.types import (
    DocumentError,
    DocumentTranslationOptions,
    FitOptions,
    Language,
    TranslationMode,
    UnsupportedDocumentError,
)
from doctranslator_server.db import Database
from doctranslator_server.db.models import Batch, BatchItem, Document, Job, utcnow
from doctranslator_server.db.repositories import batches as batch_repo
from doctranslator_server.db.repositories import blobs as blob_repo
from doctranslator_server.db.repositories import jobs as job_repo
from doctranslator_server.db.repositories import results as result_repo
from doctranslator_server.db.repositories import users as user_repo
from doctranslator_server.jobs.engines import EngineIdentities
from doctranslator_server.jobs.errors import (
    AdmissionError,
    ConflictError,
    DocumentRejectedError,
    InvalidRequestError,
    NotFoundError,
)
from doctranslator_server.jobs.storage import BlobStore
from doctranslator_server.jobs.views import (
    BatchView,
    DocumentView,
    FileView,
    ItemView,
    JobView,
    Page,
    SubmitResult,
)
from doctranslator_server.settings import ServerSettings

__all__ = ["MEDIA_TYPES", "JobService", "SubmitOptions", "cancel_user_jobs", "safe_filename"]

logger = logging.getLogger(__name__)

MEDIA_TYPES = {
    "txt": "text/plain",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
}
_UNSAFE = re.compile(r"[\x00-\x1f\x7f<>:\"|?*]")


def safe_filename(name: str) -> str:
    """The last path component, without control or reserved characters, at most 200 chars."""
    base = re.split(r"[\\/]", unicodedata.normalize("NFC", name or ""))[-1]
    base = _UNSAFE.sub("_", base).strip(" .")
    if len(base) > 200:
        stem, dot, suffix = base.rpartition(".")
        base = (
            f"{stem[: 200 - len(suffix) - 1]}.{suffix}" if dot and len(suffix) <= 10 else base[:200]
        )
    return base or "document"


@dataclass(frozen=True, slots=True)
class SubmitOptions:
    """What a caller chooses for one file (the REST ``options`` object)."""

    target: str
    source: str = "auto"
    mode: str | None = None
    protected_terms: tuple[str, ...] = ()
    txt_encoding: str | None = None
    min_scale: float | None = None
    min_size_pt: float | None = None
    force_retranslate: bool = False


def _cursor(created: datetime, ident: str) -> str:
    raw = f"{created.isoformat()}|{ident}".encode()
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _parse_cursor(cursor: str | None) -> tuple[datetime, str] | None:
    if not cursor:
        return None
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        created, ident = base64.urlsafe_b64decode(padded).decode().split("|", 1)
        return datetime.fromisoformat(created), ident
    except (ValueError, UnicodeDecodeError) as exc:
        raise InvalidRequestError("invalid cursor", code="invalid_cursor") from exc


def job_view(job: Job, document_id: str | None) -> JobView:
    return JobView(
        id=job.id,
        batch_id=job.batch_id,
        status=job.status,
        original_name=job.original_name,
        format=job.format,
        mode=job.mode,
        source_requested=job.source_requested,
        source_resolved=job.source_resolved,
        target=job.target,
        fingerprint=job.fingerprint,
        force=job.force,
        attempts=job.attempts,
        phase=job.phase,
        progress_done=job.progress_done,
        progress_total=job.progress_total,
        cancel_requested=job.cancel_requested,
        cache_hit=job.cache_hit,
        error_code=job.error_code,
        error_message=job.error_message,
        document_id=document_id,
        fit_status=job.fit_status,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


class JobService:
    def __init__(
        self,
        settings: ServerSettings,
        db: Database,
        store: BlobStore,
        catalog: EngineIdentities,
        limits: DocumentLimits | None = None,
    ) -> None:
        self._settings = settings
        self._db = db
        self._store = store
        self._catalog = catalog
        self._limits = limits or DocumentLimits()

    # Capabilities

    def capabilities(self) -> dict[str, Any]:
        return {
            "formats": sorted(MEDIA_TYPES),
            "modes": [m.value for m in self._catalog.modes],
            "languages": [lang.value for lang in Language],
            "fit_statuses": ["not_applicable", "passed", "adjusted", "unresolved"],
            "limits": {
                "max_upload_bytes": self._settings.max_upload_bytes,
                "max_queued_jobs_per_user": self._settings.max_queued_jobs_per_user,
                "document_retention_days": self._settings.document_retention_days,
                "page_size_default": 50,
                "page_size_max": 200,
            },
            "fit_defaults": FitOptions().model_dump(),
        }

    # Submission

    def _options(
        self, request: SubmitOptions
    ) -> tuple[TranslationMode, DocumentTranslationOptions]:
        modes = self._catalog.modes
        if not modes:
            raise InvalidRequestError("no translation engine is configured", code="no_engine")
        try:
            mode = TranslationMode(request.mode) if request.mode else modes[0]
        except ValueError as exc:
            raise InvalidRequestError("unknown mode", code="invalid_options") from exc
        if mode not in modes:
            raise InvalidRequestError(
                f"mode {mode.value} is not available", code="mode_unavailable"
            )
        fit: dict[str, float] = {}
        if request.min_scale is not None:
            fit["min_scale"] = request.min_scale
        if request.min_size_pt is not None:
            fit["min_size_pt"] = request.min_size_pt
        try:
            options = DocumentTranslationOptions.model_validate(
                {
                    "source": request.source,
                    "target": request.target,
                    "protected_terms": list(request.protected_terms),
                    "txt_encoding": request.txt_encoding,
                    "fit": fit,
                }
            )
        except ValidationError as exc:
            fields = sorted({".".join(str(p) for p in e["loc"]) for e in exc.errors()})
            raise InvalidRequestError(
                f"invalid options: {', '.join(fields)}", code="invalid_options", fields=fields
            ) from None
        if options.source != "auto" and options.source == options.target:
            raise InvalidRequestError(
                "source and target language are the same", code="invalid_options"
            )
        return mode, options

    @staticmethod
    def _request_hash(
        input_hash: str, mode: TranslationMode, options: DocumentTranslationOptions, force: bool
    ) -> str:
        canonical = json.dumps(
            {
                "input": input_hash,
                "mode": mode.value,
                "options": options.model_dump(mode="json"),
                "force": force,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode()).hexdigest()

    def submit(
        self,
        owner_id: str,
        filename: str,
        stream: BinaryIO,
        request: SubmitOptions,
        *,
        submission_id: str | None = None,
        batch_id: str | None = None,
        client_item_id: str | None = None,
    ) -> SubmitResult:
        """Accept one file: a cache hit completes at once, a miss queues a job (never waits)."""
        if (batch_id is None) == (submission_id is None):
            raise InvalidRequestError("give either a batch item or a submission ID")
        if batch_id is not None and client_item_id is None:
            raise InvalidRequestError("a batch item needs client_item_id")
        name = safe_filename(filename)
        mode, options = self._options(request)
        suffix = Path(name).suffix.lower()
        staged = self._store.stage_stream(
            stream, suffix=suffix, max_bytes=self._settings.max_upload_bytes
        )
        try:
            request_hash = self._request_hash(
                staged.sha256, mode, options, request.force_retranslate
            )
            replay = self._replay(owner_id, request_hash, submission_id, batch_id, client_item_id)
            if replay is not None:
                return replay
            try:
                fmt = inspect_document(staged.path, limits=self._limits)
            except DocumentError as exc:
                status = 415 if isinstance(exc, UnsupportedDocumentError) else 422
                return self._reject(
                    owner_id, name, request_hash, exc, status, batch_id, client_item_id
                )
            fingerprint = self._catalog.fingerprint(mode, options)
            stored = self._store.put(staged)
        finally:
            staged.path.unlink(missing_ok=True)
        try:
            return self._accept(
                owner_id,
                name,
                fmt.value,
                stored.sha256,
                stored.size,
                mode,
                options,
                fingerprint,
                request.force_retranslate,
                request_hash,
                submission_id,
                batch_id,
                client_item_id,
            )
        except IntegrityError:
            # A concurrent identical submission won the unique binding: answer with its outcome.
            replay = self._replay(owner_id, request_hash, submission_id, batch_id, client_item_id)
            if replay is None:
                raise
            return replay
        finally:
            self._store.release_pins([stored.pin_id])

    def _replay(
        self,
        owner_id: str,
        request_hash: str,
        submission_id: str | None,
        batch_id: str | None,
        client_item_id: str | None,
    ) -> SubmitResult | None:
        with self._db.session() as session:
            if submission_id is not None:
                job = job_repo.by_submission(session, owner_id, submission_id)
                if job is None:
                    return None
                if job.request_hash != request_hash:
                    raise ConflictError(
                        "this submission ID was used with a different file or options",
                        code="idempotency_mismatch",
                    )
                return SubmitResult(self._job_view(session, job), None, replayed=True)
            batch = self._open_batch(session, owner_id, batch_id or "", for_replay=True)
            item = batch_repo.item_by_client_id(session, batch.id, client_item_id or "")
            if item is None:
                return None
            if item.request_hash != request_hash:
                raise ConflictError(
                    "this client item ID was used with a different file or options",
                    code="idempotency_mismatch",
                )
            view = self._item_view(session, item)
            if item.job_id is None:
                raise DocumentRejectedError(
                    item.rejection_message or "rejected",
                    code=item.rejection_code or "invalid_document",
                    status=415 if item.rejection_code == "unsupported_document" else 422,
                    item_id=item.id,
                )
            return SubmitResult(view.job, view, replayed=True)

    def _open_batch(
        self, session: Session, owner_id: str, batch_id: str, *, for_replay: bool = False
    ) -> Batch:
        batch = batch_repo.get_owned(session, owner_id, batch_id)
        if batch is None:
            raise NotFoundError("batch")
        if batch.state != "open" and not for_replay:
            raise ConflictError(f"the batch is {batch.state}", code="batch_closed")
        return batch

    def _reject(
        self,
        owner_id: str,
        name: str,
        request_hash: str,
        exc: DocumentError,
        status: int,
        batch_id: str | None,
        client_item_id: str | None,
    ) -> SubmitResult:
        message = str(exc)
        if batch_id is None:
            raise DocumentRejectedError(message, code=exc.code, status=status)
        with self._db.session() as session:
            batch = self._open_batch(session, owner_id, batch_id)
            item = batch_repo.add_item(
                session,
                batch,
                client_item_id=client_item_id,
                original_name=name,
                request_hash=request_hash,
                rejection_code=exc.code,
                rejection_message=message,
            )
            user_repo.audit(
                session,
                "item_rejected",
                actor=owner_id,
                target_type="batch_item",
                target_id=item.id,
                outcome=exc.code,
            )
            item_id = item.id
        raise DocumentRejectedError(message, code=exc.code, status=status, item_id=item_id)

    def _accept(
        self,
        owner_id: str,
        name: str,
        fmt: str,
        input_hash: str,
        size: int,
        mode: TranslationMode,
        options: DocumentTranslationOptions,
        fingerprint: str,
        force: bool,
        request_hash: str,
        submission_id: str | None,
        batch_id: str | None,
        client_item_id: str | None,
    ) -> SubmitResult:
        now = utcnow()
        with self._db.session() as session:
            batch = self._open_batch(session, owner_id, batch_id) if batch_id else None
            if job_repo.count_nonterminal(session) >= self._settings.max_queued_jobs:
                raise AdmissionError("the service queue is full; retry later")
            if (
                job_repo.count_nonterminal(session, owner_id)
                >= self._settings.max_queued_jobs_per_user
            ):
                raise AdmissionError("you have too many unfinished jobs; retry later")
            job = job_repo.insert(
                session,
                owner_id=owner_id,
                batch_id=batch.id if batch else None,
                submission_id=submission_id,
                request_hash=request_hash,
                original_name=name,
                format=fmt,
                input_blob=input_hash,
                input_size=size,
                options=options.model_dump(mode="json"),
                mode=mode.value,
                source_requested=str(options.source),
                target=options.target.value,
                fingerprint=fingerprint,
                force=force,
                max_attempts=self._settings.max_attempts,
                available_at=now,
                created_at=now,
            )
            cached = None if force else result_repo.lookup(session, input_hash, fingerprint)
            if cached is not None:
                job.status = "succeeded"
                job.cache_hit = True
                job.finished_at = now
                job.result_id = cached.id
                job.fit_status = cached.fit_status
                job.source_resolved = cached.source_resolved
                result_repo.touch(session, cached.id, now)
                result_repo.add_document(
                    session,
                    job,
                    result_id=cached.id,
                    source_resolved=cached.source_resolved,
                    fit_status=cached.fit_status,
                    output_blob=cached.output_blob,
                    report_blob=cached.report_blob,
                    now=now,
                    expires_at=now + timedelta(days=self._settings.document_retention_days),
                )
            item = None
            if batch is not None:
                item = batch_repo.add_item(
                    session,
                    batch,
                    client_item_id=client_item_id,
                    original_name=name,
                    request_hash=request_hash,
                    job_id=job.id,
                )
            user_repo.audit(
                session,
                "job_submitted",
                actor=owner_id,
                target_type="job",
                target_id=job.id,
                outcome="cache_hit" if cached else "queued",
            )
            session.flush()
            view = self._job_view(session, job)
            item_view = self._item_view(session, item) if item is not None else None
        logger.info("job %s %s", view.id, "cache hit" if view.cache_hit else "queued")
        return SubmitResult(view, item_view, replayed=False)

    # Views

    def _job_view(self, session: Session, job: Job) -> JobView:
        document = result_repo.document_for_job(session, job.id)
        return job_view(job, document.id if document else None)

    def _item_view(self, session: Session, item: BatchItem) -> ItemView:
        job = job_repo.get(session, item.job_id) if item.job_id else None
        return ItemView(
            id=item.id,
            ordinal=item.ordinal,
            client_item_id=item.client_item_id,
            original_name=item.original_name,
            rejection_code=item.rejection_code,
            rejection_message=item.rejection_message,
            job=self._job_view(session, job) if job else None,
        )

    def _batch_view(self, session: Session, batch: Batch) -> BatchView:
        counts = batch_repo.counts(session, batch.id)
        return BatchView(
            id=batch.id,
            label=batch.label,
            state=batch.state,
            items=batch.next_ordinal,
            counts=counts,
            created_at=batch.created_at,
            sealed_at=batch.sealed_at,
        )

    def _document_view(self, session: Session, document: Document) -> DocumentView:
        version = result_repo.version(session, document.id, 0)
        if version is None:  # pragma: no cover - version 0 is created with the document
            raise NotFoundError("document")
        blob = blob_repo.get(session, version.output_blob)
        return DocumentView(
            id=document.id,
            job_id=document.job_id,
            original_name=document.original_name,
            format=document.format,
            mode=document.mode,
            source_requested=document.source_requested,
            source_resolved=document.source_resolved,
            target=document.target,
            fit_status=document.fit_status,
            version=0,
            output_size=blob.size if blob else 0,
            output_sha256=version.output_blob,
            created_at=document.created_at,
            expires_at=document.expires_at,
        )

    # Batches

    def create_batch(self, owner_id: str, key: str, label: str) -> tuple[BatchView, bool]:
        with self._db.session() as session:
            existing = batch_repo.by_key(session, owner_id, key)
            if existing is not None:
                return self._batch_view(session, existing), False
        try:
            with self._db.session() as session:
                batch = batch_repo.create(session, owner_id, key, label[:200], utcnow())
                user_repo.audit(
                    session,
                    "batch_created",
                    actor=owner_id,
                    target_type="batch",
                    target_id=batch.id,
                )
                return self._batch_view(session, batch), True
        except IntegrityError:
            with self._db.session() as session:
                existing = batch_repo.by_key(session, owner_id, key)
                if existing is None:
                    raise
                return self._batch_view(session, existing), False

    def get_batch(self, owner_id: str, batch_id: str) -> BatchView:
        with self._db.session() as session:
            batch = batch_repo.get_owned(session, owner_id, batch_id)
            if batch is None:
                raise NotFoundError("batch")
            return self._batch_view(session, batch)

    def list_batches(self, owner_id: str, cursor: str | None, limit: int) -> Page[BatchView]:
        with self._db.session() as session:
            rows = batch_repo.list_owned(
                session, owner_id, after=_parse_cursor(cursor), limit=limit + 1
            )
            views = [self._batch_view(session, b) for b in rows[:limit]]
            more = len(rows) > limit
            return Page(
                views, _cursor(rows[limit - 1].created_at, rows[limit - 1].id) if more else None
            )

    def list_items(
        self,
        owner_id: str,
        batch_id: str,
        cursor: str | None,
        limit: int,
        client_item_id: str | None = None,
    ) -> Page[ItemView]:
        try:
            after = int(cursor) if cursor else None
        except ValueError as exc:
            raise InvalidRequestError("invalid cursor", code="invalid_cursor") from exc
        with self._db.session() as session:
            if batch_repo.get_owned(session, owner_id, batch_id) is None:
                raise NotFoundError("batch")
            rows = batch_repo.items(
                session, batch_id, after=after, limit=limit + 1, client_item_id=client_item_id
            )
            views = [
                ItemView(
                    id=item.id,
                    ordinal=item.ordinal,
                    client_item_id=item.client_item_id,
                    original_name=item.original_name,
                    rejection_code=item.rejection_code,
                    rejection_message=item.rejection_message,
                    job=job_view(job, document.id if document else None) if job else None,
                )
                for item, job, document in rows[:limit]
            ]
            more = len(rows) > limit
            return Page(views, str(rows[limit - 1][0].ordinal) if more else None)

    def seal_batch(self, owner_id: str, batch_id: str) -> BatchView:
        with self._db.session() as session:
            batch = batch_repo.get_owned(session, owner_id, batch_id)
            if batch is None:
                raise NotFoundError("batch")
            if batch.state == "open":
                batch_repo.set_state(session, batch.id, "sealed", utcnow())
                session.refresh(batch)
            return self._batch_view(session, batch)

    def cancel_batch(self, owner_id: str, batch_id: str) -> BatchView:
        now = utcnow()
        with self._db.session() as session:
            batch = batch_repo.get_owned(session, owner_id, batch_id)
            if batch is None:
                raise NotFoundError("batch")
            if batch.state != "cancelled":
                batch_repo.set_state(session, batch.id, "cancelled", now)
                for job in job_repo.list_owned(
                    session, owner_id, after=None, limit=1_000_000, batch_id=batch.id
                ):
                    if job.status in job_repo.NONTERMINAL:
                        job_repo.request_cancel(session, job.id, now)
                user_repo.audit(
                    session,
                    "batch_cancelled",
                    actor=owner_id,
                    target_type="batch",
                    target_id=batch.id,
                )
                session.refresh(batch)
            return self._batch_view(session, batch)

    # Jobs

    def get_job(self, owner_id: str, job_id: str) -> JobView:
        with self._db.session() as session:
            job = job_repo.get_owned(session, owner_id, job_id)
            if job is None:
                raise NotFoundError("job")
            return self._job_view(session, job)

    def list_jobs(
        self, owner_id: str, cursor: str | None, limit: int, status: str | None = None
    ) -> Page[JobView]:
        with self._db.session() as session:
            rows = job_repo.list_owned(
                session, owner_id, after=_parse_cursor(cursor), limit=limit + 1, status=status
            )
            views = [self._job_view(session, j) for j in rows[:limit]]
            more = len(rows) > limit
            return Page(
                views, _cursor(rows[limit - 1].created_at, rows[limit - 1].id) if more else None
            )

    def cancel_job(self, owner_id: str, job_id: str) -> JobView:
        with self._db.session() as session:
            job = job_repo.get_owned(session, owner_id, job_id)
            if job is None:
                raise NotFoundError("job")
            if job.status in job_repo.NONTERMINAL:
                job_repo.request_cancel(session, job.id, utcnow())
                user_repo.audit(
                    session,
                    "job_cancel_requested",
                    actor=owner_id,
                    target_type="job",
                    target_id=job.id,
                )
                session.refresh(job)
            return self._job_view(session, job)

    # Documents

    def list_documents(self, owner_id: str, cursor: str | None, limit: int) -> Page[DocumentView]:
        with self._db.session() as session:
            rows = result_repo.list_documents(
                session, owner_id, after=_parse_cursor(cursor), limit=limit + 1
            )
            views = [self._document_view(session, d) for d in rows[:limit]]
            more = len(rows) > limit
            return Page(
                views, _cursor(rows[limit - 1].created_at, rows[limit - 1].id) if more else None
            )

    def get_document(self, owner_id: str, document_id: str) -> DocumentView:
        with self._db.session() as session:
            document = result_repo.get_document_owned(session, owner_id, document_id)
            if document is None:
                raise NotFoundError("document")
            return self._document_view(session, document)

    def document_file(self, owner_id: str, document_id: str, kind: str) -> FileView:
        """``kind`` is ``output``, ``report`` or ``original``."""
        with self._db.session() as session:
            document = result_repo.get_document_owned(session, owner_id, document_id)
            if document is None:
                raise NotFoundError("document")
            version = result_repo.version(session, document.id, 0)
            if version is None:  # pragma: no cover
                raise NotFoundError("document")
            stem = Path(document.original_name).stem or "document"
            if kind == "original":
                digest, filename = document.original_blob, document.original_name
                media = MEDIA_TYPES.get(document.format, "application/octet-stream")
            elif kind == "report":
                digest = version.report_blob
                filename = f"{stem}.{document.target}.{document.format}.report.json"
                media = "application/json"
            else:
                digest = version.output_blob
                filename = f"{stem}.{document.target}.{document.format}"
                media = MEDIA_TYPES.get(document.format, "application/octet-stream")
            blob = blob_repo.get(session, digest)
            size = blob.size if blob else 0
        return FileView(self._store.path(digest), filename, media, size, digest)

    def delete_document(self, owner_id: str, document_id: str) -> None:
        with self._db.session() as session:
            document = result_repo.get_document_owned(session, owner_id, document_id)
            if document is None:
                raise NotFoundError("document")
            result_repo.delete_document(session, document)
            user_repo.audit(
                session,
                "document_deleted",
                actor=owner_id,
                target_type="document",
                target_id=document_id,
            )


def cancel_user_jobs(db: Database, user_id: str) -> int:
    """Request cancellation of every unfinished job of a (disabled) user (ADR-015)."""
    with db.session() as session:
        return job_repo.cancel_for_user(session, user_id, utcnow())
