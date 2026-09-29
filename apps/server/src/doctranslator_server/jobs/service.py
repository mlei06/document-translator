"""The job service: saved documents, submission, batches, owned history and downloads.

Storage follows ADR-014: an owner's saved source documents each keep one current translation per
language pair; reuse only considers that document's current compatible result; temporary jobs
never create library entries or reuse anything; every job keeps its exact immutable result until
the result's advertised expiry. Every method takes the authenticated owner ID and filters by it
in the database; absent and other-owner resources both raise ``NotFoundError``.
"""

import base64
import hashlib
import json
import logging
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, BinaryIO, Literal

from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from doctranslator_core import DocumentLimits, detect_document
from doctranslator_core.types import (
    DocumentError,
    DocumentTranslationOptions,
    FitOptions,
    Language,
    TranslationMode,
    UnsupportedDocumentError,
)
from doctranslator_server.db import Database
from doctranslator_server.db.models import (
    Batch,
    BatchItem,
    Document,
    DocumentTranslation,
    Job,
    JobResult,
    utcnow,
)
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
    TooLargeError,
)
from doctranslator_server.jobs.preview import read_manifest, read_member
from doctranslator_server.jobs.storage import BlobStore, Staged
from doctranslator_server.jobs.views import (
    BatchView,
    DocumentView,
    FileView,
    ItemView,
    JobView,
    Page,
    ProgressView,
    SubmitResult,
    TranslationView,
)
from doctranslator_server.settings import ServerSettings

__all__ = [
    "MEDIA_TYPES",
    "JobService",
    "SubmitOptions",
    "cancel_user_jobs",
    "safe_filename",
]

logger = logging.getLogger(__name__)

MEDIA_TYPES = {
    "txt": "text/plain",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
}
_UNSAFE = re.compile(r"[\x00-\x1f\x7f<>:\"|?*]")
type Retention = Literal["saved", "temporary"]
type FileKind = Literal["output", "report"]


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
    """What a caller chooses for one translation (the REST ``options`` object)."""

    target: str
    source: str = "auto"
    mode: str | None = None
    protected_terms: tuple[str, ...] = ()
    txt_encoding: str | None = None
    min_scale: float | None = None
    min_size_pt: float | None = None
    force_retranslate: bool = False
    retention: Retention = "saved"


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


_PHASES = frozenset({"prepare", "extract", "translate", "apply", "fit", "write"})


def _progress(job: Job) -> ProgressView | None:
    if job.phase not in _PHASES:
        return None
    counted = (
        job.phase == "translate"
        and job.progress_total is not None
        and job.progress_done is not None
        and 0 <= job.progress_done <= job.progress_total
    )
    return ProgressView(
        phase=job.phase,
        done=job.progress_done if counted else None,
        total=job.progress_total if counted else None,
        updated_at=job.progress_updated_at,
    )


def _available(
    result: JobResult | None, document: Document | None, job: Job, now: datetime
) -> bool:
    if job.status != "succeeded" or result is None:
        return False
    if job.document_id is not None and (document is None or document.deleted_at is not None):
        return False
    return result.expires_at is None or result.expires_at > now


def job_view(session: Session, job: Job) -> JobView:
    result = result_repo.get_result(session, job.result_id) if job.result_id else None
    document = session.get(Document, job.document_id) if job.document_id else None
    available = _available(result, document, job, utcnow())
    return JobView(
        id=job.id,
        batch_id=job.batch_id,
        document_id=job.document_id,
        retention=job.retention,
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
        progress=_progress(job),
        cancel_requested=job.cancel_requested,
        fit_skip_requested=job.fit_skip_requested,
        cache_hit=job.cache_hit,
        error_code=job.error_code,
        error_message=job.error_message,
        fit_status=job.fit_status,
        result_available=available,
        result_expires_at=result.expires_at if result is not None and available else None,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        dismissed_at=job.dismissed_at,
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
            "fit_statuses": ["not_applicable", "passed", "adjusted", "unresolved", "skipped"],
            "retention": ["saved", "temporary"],
            "limits": {
                "max_upload_bytes": self._settings.max_upload_bytes,
                "max_queued_jobs_per_user": self._settings.max_queued_jobs_per_user,
                "owner_quota_bytes": self._settings.owner_quota_bytes,
                "temporary_retention_hours": self._settings.temporary_retention_hours,
                "superseded_retention_days": self._settings.superseded_retention_days,
                "page_size_default": 50,
                "page_size_max": 200,
            },
            "fit_defaults": FitOptions().model_dump(),
        }

    def storage(self, owner_id: str) -> dict[str, int]:
        with self._db.session() as session:
            used = result_repo.storage_used(session, owner_id)
        return {"used_bytes": used, "quota_bytes": self._settings.owner_quota_bytes}

    # Options and identity

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
        if request.retention not in ("saved", "temporary"):
            raise InvalidRequestError(
                "retention must be saved or temporary", code="invalid_options"
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
        input_hash: str,
        mode: TranslationMode,
        options: DocumentTranslationOptions,
        request: SubmitOptions,
        document_id: str | None,
    ) -> str:
        canonical = json.dumps(
            {
                "input": input_hash,
                "document": document_id,
                "mode": mode.value,
                "options": options.model_dump(mode="json"),
                "force": request.force_retranslate,
                "retention": request.retention,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode()).hexdigest()

    # Saved documents (ADR-014)

    def _detect(self, staged: Staged) -> tuple[str, str | None, str]:
        try:
            detection = detect_document(staged.path, limits=self._limits)
        except DocumentError as exc:
            status = 415 if isinstance(exc, UnsupportedDocumentError) else 422
            raise DocumentRejectedError(str(exc), code=exc.code, status=status) from None
        source = detection.source.value if detection.source else None
        return detection.format.value, source, detection.status

    def create_document(
        self,
        owner_id: str,
        filename: str,
        stream: BinaryIO,
        *,
        new_document: bool = False,
        external_ref: str | None = None,
    ) -> tuple[DocumentView, bool]:
        """Store, validate and detect a source document; returns (document, created).

        Identical bytes resolve to the owner's existing document unless ``new_document`` (an
        application's distinct attachment); another owner's identical bytes are only shared as
        physical storage, never as a record.
        """
        name = safe_filename(filename)
        staged = self._store.stage_stream(
            stream, suffix=Path(name).suffix.lower(), max_bytes=self._settings.max_upload_bytes
        )
        try:
            if not new_document:
                with self._db.session() as session:
                    existing = result_repo.document_by_blob(session, owner_id, staged.sha256)
                    if existing is not None:
                        return self._document_view(session, existing), False
            fmt, source, status = self._detect(staged)
            stored = self._store.put(staged)
        finally:
            staged.path.unlink(missing_ok=True)
        try:
            with self._db.session() as session:
                used = result_repo.storage_used(session, owner_id)
                if used + stored.size > self._settings.owner_quota_bytes:
                    raise TooLargeError(
                        "your saved documents would exceed your storage quota",
                        code="quota_exceeded",
                    )
                document = result_repo.add_document(
                    session,
                    owner_id=owner_id,
                    source_blob=stored.sha256,
                    name=name,
                    size=stored.size,
                    format=fmt,
                    detected_source=source,
                    detection=status,
                    external_ref=(external_ref or None) and external_ref[:200],
                    created_at=utcnow(),
                )
                user_repo.audit(
                    session,
                    "document_created",
                    actor=owner_id,
                    target_type="document",
                    target_id=document.id,
                )
                return self._document_view(session, document), True
        finally:
            self._store.release_pins([stored.pin_id])

    def _document_view(self, session: Session, document: Document) -> DocumentView:
        translations: list[TranslationView] = []
        for slot in result_repo.slots_of(session, document.id):
            result = result_repo.get_result(session, slot.current_result_id)
            if result is None:  # pragma: no cover - slots always reference a result
                continue
            blob = blob_repo.get(session, result.output_blob)
            translations.append(
                TranslationView(
                    id=slot.id,
                    source=slot.source or None,
                    target=slot.target,
                    fit_status=result.fit_status,
                    job_id=result.job_id,
                    output_size=blob.size if blob else 0,
                    output_sha256=result.output_blob,
                    updated_at=slot.updated_at,
                )
            )
        active = {
            job.target: job.id
            for job in job_repo.list_owned(
                session,
                document.owner_id,
                after=None,
                limit=100,
                document_id=document.id,
                active_only=True,
            )
        }
        return DocumentView(
            id=document.id,
            name=document.name,
            format=document.format,
            size=document.size,
            sha256=document.source_blob,
            detected_source=document.detected_source,
            detection=document.detection,
            external_ref=document.external_ref,
            created_at=document.created_at,
            translations=translations,
            active_jobs=active,
        )

    def _owned_document(self, session: Session, owner_id: str, document_id: str) -> Document:
        document = result_repo.get_document_owned(session, owner_id, document_id)
        if document is None:
            raise NotFoundError("document")
        return document

    def get_document(self, owner_id: str, document_id: str) -> DocumentView:
        with self._db.session() as session:
            return self._document_view(
                session, self._owned_document(session, owner_id, document_id)
            )

    def list_documents(
        self, owner_id: str, cursor: str | None, limit: int, query: str | None = None
    ) -> Page[DocumentView]:
        with self._db.session() as session:
            rows = result_repo.list_documents(
                session, owner_id, after=_parse_cursor(cursor), limit=limit + 1, query=query
            )
            views = [self._document_view(session, d) for d in rows[:limit]]
            more = len(rows) > limit
            last = rows[limit - 1] if more else None
            return Page(views, _cursor(last.created_at, last.id) if last else None)

    def delete_document(self, owner_id: str, document_id: str) -> None:
        """Delete the source and all its translations; cancel its unfinished jobs; job downloads
        of it stop at once (ADR-014)."""
        now = utcnow()
        with self._db.session() as session:
            document = self._owned_document(session, owner_id, document_id)
            for job in job_repo.list_owned(
                session,
                owner_id,
                after=None,
                limit=1000,
                document_id=document.id,
                active_only=True,
            ):
                job_repo.request_cancel(session, job.id, now)
            result_repo.mark_document_deleted(session, document, now)
            user_repo.audit(
                session,
                "document_deleted",
                actor=owner_id,
                target_type="document",
                target_id=document_id,
            )

    def delete_translation(self, owner_id: str, document_id: str, translation_id: str) -> None:
        now = utcnow()
        with self._db.session() as session:
            slot = result_repo.slot_owned(session, owner_id, document_id, translation_id)
            if slot is None:
                raise NotFoundError("translation")
            active = job_repo.active_in_slot(session, f"{document_id}:{slot.target}")
            if active is not None:
                job_repo.request_cancel(session, active.id, now)
            result_repo.delete_slot(session, slot, now)
            user_repo.audit(
                session,
                "translation_deleted",
                actor=owner_id,
                target_type="translation",
                target_id=translation_id,
            )

    def _slot(
        self, session: Session, owner_id: str, document_id: str, translation_id: str
    ) -> tuple[Document, DocumentTranslation, JobResult]:
        document = self._owned_document(session, owner_id, document_id)
        slot = result_repo.slot_owned(session, owner_id, document_id, translation_id)
        if slot is None:
            raise NotFoundError("translation")
        result = result_repo.get_result(session, slot.current_result_id)
        if result is None:  # pragma: no cover
            raise NotFoundError("translation")
        return document, slot, result

    def translation_file(
        self, owner_id: str, document_id: str, translation_id: str, kind: FileKind
    ) -> FileView:
        with self._db.session() as session:
            document, slot, result = self._slot(session, owner_id, document_id, translation_id)
            return self._result_file(
                session, document.name, document.format, slot.target, result, kind
            )

    def translation_preview(
        self, owner_id: str, document_id: str, translation_id: str, name: str | None
    ) -> dict[str, Any] | tuple[bytes, str]:
        with self._db.session() as session:
            _, _, result = self._slot(session, owner_id, document_id, translation_id)
            preview = result.preview_blob
        return self._preview(preview, name)

    def document_original(self, owner_id: str, document_id: str) -> FileView:
        with self._db.session() as session:
            document = self._owned_document(session, owner_id, document_id)
            return FileView(
                self._store.path(document.source_blob),
                document.name,
                MEDIA_TYPES.get(document.format, "application/octet-stream"),
                document.size,
                document.source_blob,
            )

    # Submission

    def translate_document(
        self,
        owner_id: str,
        document_id: str,
        request: SubmitOptions,
        *,
        submission_id: str | None = None,
        batch_id: str | None = None,
        client_item_id: str | None = None,
    ) -> SubmitResult:
        """Translate a saved document without re-uploading it (ADR-014)."""
        self._identity(submission_id, batch_id, client_item_id)
        if request.retention != "saved":
            raise InvalidRequestError(
                "saved documents translate with retention=saved", code="invalid_options"
            )
        mode, options = self._options(request)
        with self._db.session() as session:
            document = self._owned_document(session, owner_id, document_id)
            name, fmt, digest, size = (
                document.name,
                document.format,
                document.source_blob,
                document.size,
            )
        request_hash = self._request_hash(digest, mode, options, request, document_id)
        replay = self._replay(owner_id, request_hash, submission_id, batch_id, client_item_id)
        if replay is not None:
            return replay
        return self._accept_with_retry(
            owner_id,
            name,
            fmt,
            digest,
            size,
            mode,
            options,
            request,
            document_id,
            request_hash,
            submission_id,
            batch_id,
            client_item_id,
        )

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
        """Accept one uploaded file: saved mode files it in the owner's library first; a
        compatible current result completes at once, otherwise a job is queued (never waits)."""
        self._identity(submission_id, batch_id, client_item_id)
        name = safe_filename(filename)
        mode, options = self._options(request)
        staged = self._store.stage_stream(
            stream, suffix=Path(name).suffix.lower(), max_bytes=self._settings.max_upload_bytes
        )
        try:
            if request.retention == "saved":
                with self._db.session() as session:
                    existing = result_repo.document_by_blob(session, owner_id, staged.sha256)
                    document_id = existing.id if existing else None
            else:
                document_id = None
            if document_id is not None or request.retention == "temporary":
                request_hash = self._request_hash(
                    staged.sha256, mode, options, request, document_id
                )
                replay = self._replay(
                    owner_id, request_hash, submission_id, batch_id, client_item_id
                )
                if replay is not None:
                    return replay
            try:
                fmt, source, status = self._detect(staged)
            except DocumentRejectedError as exc:
                hash_for_rejection = self._request_hash(staged.sha256, mode, options, request, None)
                return self._reject(
                    owner_id, name, hash_for_rejection, exc, batch_id, client_item_id
                )
            stored = self._store.put(staged)
        finally:
            staged.path.unlink(missing_ok=True)
        try:
            if request.retention == "saved" and document_id is None:
                document_id = self._file_document(
                    owner_id, name, fmt, stored.sha256, stored.size, source, status
                )
            request_hash = self._request_hash(stored.sha256, mode, options, request, document_id)
            replay = self._replay(owner_id, request_hash, submission_id, batch_id, client_item_id)
            if replay is not None:
                return replay
            return self._accept_with_retry(
                owner_id,
                name,
                fmt,
                stored.sha256,
                stored.size,
                mode,
                options,
                request,
                document_id,
                request_hash,
                submission_id,
                batch_id,
                client_item_id,
            )
        finally:
            self._store.release_pins([stored.pin_id])

    def _file_document(
        self,
        owner_id: str,
        name: str,
        fmt: str,
        digest: str,
        size: int,
        source: str | None,
        status: str,
    ) -> str:
        with self._db.session() as session:
            existing = result_repo.document_by_blob(session, owner_id, digest)
            if existing is not None:
                return existing.id
            if (
                result_repo.storage_used(session, owner_id) + size
                > self._settings.owner_quota_bytes
            ):
                raise TooLargeError(
                    "your saved documents would exceed your storage quota", code="quota_exceeded"
                )
            document = result_repo.add_document(
                session,
                owner_id=owner_id,
                source_blob=digest,
                name=name,
                size=size,
                format=fmt,
                detected_source=source,
                detection=status,
                created_at=utcnow(),
            )
            return document.id

    @staticmethod
    def _identity(
        submission_id: str | None, batch_id: str | None, client_item_id: str | None
    ) -> None:
        if (batch_id is None) == (submission_id is None):
            raise InvalidRequestError("give either a batch item or a submission ID")
        if batch_id is not None and client_item_id is None:
            raise InvalidRequestError("a batch item needs client_item_id")

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
                return SubmitResult(job_view(session, job), None, replayed=True)
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
        exc: DocumentRejectedError,
        batch_id: str | None,
        client_item_id: str | None,
    ) -> SubmitResult:
        if batch_id is None:
            raise exc
        with self._db.session() as session:
            batch = self._open_batch(session, owner_id, batch_id)
            item = batch_repo.add_item(
                session,
                batch,
                client_item_id=client_item_id,
                original_name=name,
                request_hash=request_hash,
                rejection_code=exc.code,
                rejection_message=exc.message,
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
        raise DocumentRejectedError(exc.message, code=exc.code, status=exc.status, item_id=item_id)

    def _accept_with_retry(
        self,
        owner_id: str,
        name: str,
        fmt: str,
        input_hash: str,
        size: int,
        mode: TranslationMode,
        options: DocumentTranslationOptions,
        request: SubmitOptions,
        document_id: str | None,
        request_hash: str,
        submission_id: str | None,
        batch_id: str | None,
        client_item_id: str | None,
    ) -> SubmitResult:
        fingerprint = self._catalog.fingerprint(mode, options)
        try:
            return self._accept(
                owner_id,
                name,
                fmt,
                input_hash,
                size,
                mode,
                options,
                request,
                document_id,
                fingerprint,
                request_hash,
                submission_id,
                batch_id,
                client_item_id,
            )
        except IntegrityError:
            # A concurrent request won a unique binding or the target slot: answer truthfully.
            replay = self._replay(owner_id, request_hash, submission_id, batch_id, client_item_id)
            if replay is not None:
                return replay
            if document_id is not None:
                with self._db.session() as session:
                    active = job_repo.active_in_slot(
                        session, f"{document_id}:{options.target.value}"
                    )
                    if active is not None:
                        raise self._active_conflict(active.id) from None
            raise

    @staticmethod
    def _active_conflict(job_id: str) -> ConflictError:
        return ConflictError(
            "this document is already being translated into that language",
            code="translation_active",
            job_id=job_id,
        )

    def _accept(
        self,
        owner_id: str,
        name: str,
        fmt: str,
        input_hash: str,
        size: int,
        mode: TranslationMode,
        options: DocumentTranslationOptions,
        request: SubmitOptions,
        document_id: str | None,
        fingerprint: str,
        request_hash: str,
        submission_id: str | None,
        batch_id: str | None,
        client_item_id: str | None,
    ) -> SubmitResult:
        now = utcnow()
        target = options.target.value
        slot = f"{document_id}:{target}" if document_id else None
        with self._db.session() as session:
            batch = self._open_batch(session, owner_id, batch_id) if batch_id else None
            if document_id is not None:
                document = session.get(Document, document_id)
                if document is None or document.deleted_at is not None:
                    raise NotFoundError("document")
                active = job_repo.active_in_slot(session, slot or "")
                if active is not None:
                    raise self._active_conflict(active.id)
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
                document_id=document_id,
                retention=request.retention,
                active_slot=slot,
                submission_id=submission_id,
                request_hash=request_hash,
                original_name=name,
                format=fmt,
                input_blob=input_hash,
                input_size=size,
                options=options.model_dump(mode="json"),
                mode=mode.value,
                source_requested=str(options.source),
                target=target,
                fingerprint=fingerprint,
                force=request.force_retranslate,
                max_attempts=self._settings.max_attempts,
                available_at=now,
                created_at=now,
            )
            reused = (
                result_repo.reusable_result(session, document_id, target, fingerprint)
                if document_id is not None and not request.force_retranslate
                else None
            )
            if reused is not None:
                job.status = "succeeded"
                job.cache_hit = True
                job.finished_at = now
                job.result_id = reused.id
                job.fit_status = reused.fit_status
                job.source_resolved = reused.source_resolved
                job.active_slot = None
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
                outcome="reused" if reused else "queued",
            )
            session.flush()
            view = job_view(session, job)
            item_view = self._item_view(session, item) if item is not None else None
        logger.info("job %s %s", view.id, "reused current result" if view.cache_hit else "queued")
        return SubmitResult(view, item_view, replayed=False)

    # Views

    def _item_view(self, session: Session, item: BatchItem) -> ItemView:
        job = job_repo.get(session, item.job_id) if item.job_id else None
        return ItemView(
            id=item.id,
            ordinal=item.ordinal,
            client_item_id=item.client_item_id,
            original_name=item.original_name,
            rejection_code=item.rejection_code,
            rejection_message=item.rejection_message,
            job=job_view(session, job) if job else None,
        )

    def _batch_view(self, session: Session, batch: Batch) -> BatchView:
        return BatchView(
            id=batch.id,
            label=batch.label,
            state=batch.state,
            items=batch.next_ordinal,
            counts=batch_repo.counts(session, batch.id),
            created_at=batch.created_at,
            sealed_at=batch.sealed_at,
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
            last = rows[limit - 1] if len(rows) > limit else None
            return Page(views, _cursor(last.created_at, last.id) if last else None)

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
                    job=job_view(session, job) if job else None,
                )
                for item, job in rows[:limit]
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

    def _owned_job(self, session: Session, owner_id: str, job_id: str) -> Job:
        job = job_repo.get_owned(session, owner_id, job_id)
        if job is None:
            raise NotFoundError("job")
        return job

    def get_job(self, owner_id: str, job_id: str) -> JobView:
        with self._db.session() as session:
            return job_view(session, self._owned_job(session, owner_id, job_id))

    def list_jobs(
        self,
        owner_id: str,
        cursor: str | None,
        limit: int,
        status: str | None = None,
        *,
        query: str | None = None,
        active: bool = False,
    ) -> Page[JobView]:
        with self._db.session() as session:
            rows = job_repo.list_owned(
                session,
                owner_id,
                after=_parse_cursor(cursor),
                limit=limit + 1,
                status=status,
                search=query,
                active=active,
            )
            views = [job_view(session, j) for j in rows[:limit]]
            last = rows[limit - 1] if len(rows) > limit else None
            return Page(views, _cursor(last.created_at, last.id) if last else None)

    def cancel_job(self, owner_id: str, job_id: str) -> JobView:
        with self._db.session() as session:
            job = self._owned_job(session, owner_id, job_id)
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
            return job_view(session, job)

    def skip_fit(self, owner_id: str, job_id: str) -> tuple[JobView, bool]:
        """Ask the worker to stop the remaining optional fit (ADR-012 amendment).

        Returns (job, newly requested). Raises ``ConflictError`` outside the fit stage.
        """
        with self._db.session() as session:
            job = self._owned_job(session, owner_id, job_id)
            outcome = job_repo.request_skip_fit(session, job)
            if outcome == "not_in_fit":
                raise ConflictError(
                    "the layout check is not running", code="not_in_fit", phase=job.phase or ""
                )
            session.refresh(job)
            return job_view(session, job), outcome == "set"

    def set_dismissed(self, owner_id: str, job_id: str, dismissed: bool) -> JobView:
        """Move a job off (or back onto) the user's active view (ADR-017)."""
        with self._db.session() as session:
            job = self._owned_job(session, owner_id, job_id)
            job.dismissed_at = utcnow() if dismissed else None
            session.flush()
            return job_view(session, job)

    def _job_result(self, session: Session, owner_id: str, job_id: str) -> tuple[Job, JobResult]:
        job = self._owned_job(session, owner_id, job_id)
        result = result_repo.get_result(session, job.result_id) if job.result_id else None
        document = session.get(Document, job.document_id) if job.document_id else None
        if result is None or not _available(result, document, job, utcnow()):
            raise NotFoundError("job result")
        return job, result

    def job_file(self, owner_id: str, job_id: str, kind: FileKind) -> FileView:
        """The job's exact output or report, until the result expires (ADR-014)."""
        with self._db.session() as session:
            job, result = self._job_result(session, owner_id, job_id)
            return self._result_file(
                session, job.original_name, job.format, job.target, result, kind
            )

    def job_preview(
        self, owner_id: str, job_id: str, name: str | None
    ) -> dict[str, Any] | tuple[bytes, str]:
        with self._db.session() as session:
            _, result = self._job_result(session, owner_id, job_id)
            preview = result.preview_blob
        return self._preview(preview, name)

    def _result_file(
        self,
        session: Session,
        original_name: str,
        fmt: str,
        target: str,
        result: JobResult,
        kind: FileKind,
    ) -> FileView:
        stem = Path(original_name).stem or "document"
        if kind == "report":
            digest = result.report_blob
            filename = f"{stem}.{target}.{fmt}.report.json"
            media = "application/json"
        else:
            digest = result.output_blob
            filename = f"{stem}.{target}.{fmt}"
            media = MEDIA_TYPES.get(fmt, "application/octet-stream")
        blob = blob_repo.get(session, digest)
        return FileView(self._store.path(digest), filename, media, blob.size if blob else 0, digest)

    def _preview(self, blob: str | None, name: str | None) -> dict[str, Any] | tuple[bytes, str]:
        if blob is None:
            raise NotFoundError("preview")
        package = self._store.path(blob)
        if name is None:
            return read_manifest(package)
        data = read_member(package, name)
        if data is None:
            raise NotFoundError("preview page")
        return data, "image/jpeg"


def cancel_user_jobs(db: Database, user_id: str) -> int:
    """Request cancellation of every unfinished job of a (disabled) user (ADR-015)."""
    with db.session() as session:
        return job_repo.cancel_for_user(session, user_id, utcnow())
