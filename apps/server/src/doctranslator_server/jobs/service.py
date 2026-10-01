"""Submission, batches, private History and authorized downloads.

Website jobs join shared execution and resolve current results through private grants. Explicit
internal-app saved/temporary jobs retain exact-result contracts; desktop automatic jobs create
fresh local exports. Every public operation filters by authenticated owner identity.
"""

import base64
import hashlib
import json
import logging
import re
import unicodedata
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, BinaryIO, Literal

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from doctranslator_core import DocumentLimits, detect_document, get_default_protected_terms
from doctranslator_core.types import (
    DocumentError,
    DocumentTranslationOptions,
    FitOptions,
    Language,
    UnsupportedDocumentError,
)
from doctranslator_server.db import Database
from doctranslator_server.db.models import (
    Batch,
    BatchItem,
    Document,
    DocumentTranslation,
    HistoryGrant,
    Job,
    JobResult,
    SharedSlot,
    User,
    utcnow,
)
from doctranslator_server.db.repositories import batches as batch_repo
from doctranslator_server.db.repositories import blobs as blob_repo
from doctranslator_server.db.repositories import jobs as job_repo
from doctranslator_server.db.repositories import results as result_repo
from doctranslator_server.db.repositories import users as user_repo
from doctranslator_server.jobs import capacity, shared
from doctranslator_server.jobs.automatic import pinned_policy
from doctranslator_server.jobs.engines import EngineIdentities, resolve_translator
from doctranslator_server.jobs.errors import (
    AdmissionError,
    ConflictError,
    DocumentRejectedError,
    InvalidRequestError,
    NotFoundError,
    TooLargeError,
    TranslationUnavailableError,
)
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
type Retention = Literal["saved", "temporary", "cached"]
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
    translator_id: str | None = None
    protected_terms: tuple[str, ...] = ()
    use_default_dictionary: bool | None = None
    txt_encoding: str | None = None
    min_scale: float | None = None
    min_size_pt: float | None = None
    fit: dict[str, object] | None = None
    force_retranslate: bool = False
    retention: Retention = "saved"
    selection_policy: str | None = None
    download_semantics: str | None = None


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
    shared.sync_waiter(session, job)
    result = result_repo.get_result(session, job.result_id) if job.result_id else None
    document = session.get(Document, job.document_id) if job.document_id else None
    available = _available(result, document, job, utcnow())
    if job.kind == "waiter":
        grant = shared.grant_for_job(session, job)
        result = shared.current(session, grant) if grant else None
        available = result is not None
    return JobView(
        id=job.id,
        batch_id=job.batch_id,
        document_id=job.document_id,
        retention=job.retention,
        status=job.status,
        original_name=job.original_name,
        format=job.format,
        mode=job.mode,
        translator_id=job.translator_id,
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
        fallback=(
            "Continuing on this device"
            if job.kind == "translate" and job.translator_id == "hy-mt-local"
            else "Trying another translation service"
        )
        if job.rung > 0 and job.status == "running"
        else None,
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

    def reserve_upload(self, owner_id: str, size: int) -> str:
        self._store.sweep_capacity()
        with self._db.session() as session:
            return capacity.reserve(session, self._settings, owner_id, "incoming", size)

    def release_upload(self, identifier: str) -> None:
        with self._db.session() as session:
            capacity.release(session, identifier)

    def _accept_cached(
        self,
        owner_id: str,
        document_id: str,
        request: SubmitOptions,
        submission_id: str | None,
        batch_id: str | None,
        client_item_id: str | None,
    ) -> SubmitResult:
        accepted = self._accept_cached_transaction(
            owner_id, document_id, request, submission_id, batch_id, client_item_id
        )
        if accepted.job is not None and accepted.job.status not in job_repo.NONTERMINAL:
            try:
                self._store.collect(
                    holder=f"cached-input:{accepted.job.id}", pending_grace=timedelta(hours=24)
                )
            except Exception:
                logger.warning("cached input cleanup deferred to retention sweep")
        return accepted

    def _accept_cached_transaction(
        self,
        owner_id: str,
        document_id: str,
        request: SubmitOptions,
        submission_id: str | None,
        batch_id: str | None,
        client_item_id: str | None,
    ) -> SubmitResult:
        if (
            request.retention != "cached"
            or request.download_semantics != "current_shared"
            or request.source != "auto"
            or request.mode is not None
            or request.translator_id is not None
            or request.protected_terms
            or request.txt_encoding is not None
            or request.use_default_dictionary is not None
            or request.force_retranslate
            or request.min_scale is not None
            or request.min_size_pt is not None
            or request.fit not in (None, {}, FitOptions().model_dump())
        ):
            raise InvalidRequestError(
                "website automatic requests accept only the target language", code="invalid_options"
            )
        _, options = self._options(request)
        policy = pinned_policy(self._settings, self._catalog, options)
        with self._db.session() as session:
            protected_slot = session.scalar(
                select(SharedSlot.id)
                .join(Document, Document.source_blob == SharedSlot.source_hash)
                .where(
                    Document.id == document_id,
                    Document.owner_id == owner_id,
                    SharedSlot.target == request.target,
                )
            )
        self._store.sweep_capacity(protected_slot=protected_slot)
        with self._db.session() as session:
            # Idempotency is checked before the consumed staging record is consulted.
            replay = (
                job_repo.by_submission(session, owner_id, submission_id) if submission_id else None
            )
            if batch_id and client_item_id:
                self._open_batch(session, owner_id, batch_id, for_replay=True)
                old_item = batch_repo.item_by_client_id(session, batch_id, client_item_id)
                if old_item is not None:
                    replay = session.get(Job, old_item.job_id)
            if replay is not None:
                replay_upload = session.get(Document, document_id)
                if replay_upload is None or replay_upload.owner_id != owner_id:
                    raise NotFoundError("upload")
                if (
                    replay.target != request.target
                    or replay.input_blob != replay_upload.source_blob
                ):
                    raise ConflictError(
                        "submission file and target cannot change", code="idempotency_conflict"
                    )
                if replay_upload.staging_expires_at is not None:
                    replay_upload.deleted_at = utcnow()
                replay_item = (
                    batch_repo.item_by_client_id(session, batch_id, client_item_id)
                    if batch_id and client_item_id
                    else None
                )
                return SubmitResult(
                    job_view(session, replay),
                    self._item_view(session, replay_item) if replay_item else None,
                    replayed=True,
                )
            document = self._owned_document(session, owner_id, document_id)
            if document.staging_expires_at is not None and document.staging_expires_at <= utcnow():
                raise NotFoundError("upload")
            if not self._store.verify(document.source_blob):
                raise InvalidRequestError(
                    "uploaded source is unavailable; upload it again", code="source_unavailable"
                )
            slot = session.scalar(
                select(SharedSlot).where(
                    SharedSlot.source_hash == document.source_blob,
                    SharedSlot.target == request.target,
                )
            )
            if slot and slot.current_result_id:
                current_result = session.get(JobResult, slot.current_result_id)
                if (
                    current_result is None
                    or not self._store.verify(current_result.output_blob)
                    or not self._store.verify(current_result.report_blob)
                ):
                    logger.error(
                        "shared slot %s has an unreadable result; admission will repair it", slot.id
                    )
                    if current_result:
                        current_result.expires_at = utcnow()
                    slot.current_result_id = None
                    slot.generation += 1
            if (
                job_repo.count_nonterminal(session, owner_id)
                >= self._settings.max_queued_jobs_per_user
            ):
                raise AdmissionError("you have too many unfinished jobs; retry later")
            batch = self._open_batch(session, owner_id, batch_id) if batch_id else None
            request_hash = self._request_hash(
                document.source_blob, "", options, request, document_id
            )
            job = shared.accept(
                session,
                document,
                request.target,
                options.model_dump(mode="json"),
                policy,
                request_hash,
                submission_id,
                batch_id,
                max_attempts=self._settings.max_attempts,
                settings=self._settings,
            )
            item = (
                batch_repo.add_item(
                    session,
                    batch,
                    client_item_id=client_item_id,
                    original_name=document.name,
                    request_hash=request_hash,
                    job_id=job.id,
                )
                if batch
                else None
            )
            session.flush()
            return SubmitResult(
                job_view(session, job),
                self._item_view(session, item) if item else None,
                replayed=False,
            )

    def list_history(self, owner_id: str, cursor: str | None, limit: int) -> dict[str, Any]:
        with self._db.session() as session:
            query = select(HistoryGrant).where(
                HistoryGrant.owner_id == owner_id,
                HistoryGrant.deleted_at.is_(None),
                HistoryGrant.updated_at > utcnow() - timedelta(days=90),
            )
            after = _parse_cursor(cursor)
            if after:
                updated, identifier = after
                query = query.where(
                    (HistoryGrant.updated_at < updated)
                    | ((HistoryGrant.updated_at == updated) & (HistoryGrant.id < identifier))
                )
            rows = list(
                session.scalars(
                    query.order_by(HistoryGrant.updated_at.desc(), HistoryGrant.id.desc()).limit(
                        limit + 1
                    )
                )
            )
            items: list[dict[str, Any]] = []
            for grant in rows[:limit]:
                slot = session.get(SharedSlot, grant.slot_id)
                result = shared.current(session, grant)
                available = result is not None and self._store.verify(result.output_blob)
                latest = session.scalar(
                    select(Job)
                    .where(Job.history_id == grant.id)
                    .order_by(Job.created_at.desc())
                    .limit(1)
                )
                if latest:
                    shared.sync_waiter(session, latest)
                items.append(
                    dict(
                        id=grant.id,
                        original_name=grant.original_name,
                        source=grant.source,
                        detection=grant.detection,
                        target=slot.target if slot else "",
                        format=grant.format,
                        created_at=grant.created_at,
                        updated_at=grant.updated_at,
                        available=available,
                        status=latest.status if latest else "unavailable",
                        error_code=latest.error_code if latest else None,
                        error_message=latest.error_message if latest else None,
                        download_url=f"/v1/history/{grant.id}/file" if available else None,
                    )
                )
            return {
                "items": items,
                "next_cursor": _cursor(rows[limit - 1].updated_at, rows[limit - 1].id)
                if len(rows) > limit
                else None,
            }

    def history_file(self, owner_id: str, identifier: str) -> FileView:
        with self._db.session() as session:
            grant = shared.owned_grant(session, owner_id, identifier)
            result = shared.current(session, grant)
            slot = session.get(SharedSlot, grant.slot_id)
            if result is None or slot is None or not self._store.verify(result.output_blob):
                raise TranslationUnavailableError()
            return self._result_file(
                session, grant.original_name, grant.format, slot.target, result, "output"
            )

    def delete_history(self, owner_id: str, identifier: str) -> None:
        with self._db.session() as session:
            grant = shared.owned_grant(session, owner_id, identifier)
            grant.deleted_at = utcnow()
            for waiter in session.scalars(select(Job).where(Job.history_id == grant.id)):
                shared.detach(session, waiter, utcnow())

    # Capabilities

    def capabilities(self, *, refresh: bool = False) -> dict[str, Any]:
        davy = self._catalog.discovery(force=refresh)
        translators = self._catalog.translators
        return {
            "davy": asdict(davy),
            "formats": sorted(MEDIA_TYPES),
            "modes": list(dict.fromkeys(entry.mode.value for entry in translators)),
            "translators": [asdict(entry) for entry in translators],
            "default_translator_id": self._catalog.default_translator_id,
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

    @staticmethod
    def _terms(terms: tuple[str, ...]) -> list[str]:
        if len(terms) > 500:
            raise InvalidRequestError(
                "at most 500 protected terms are allowed", code="invalid_options"
            )
        for term in terms:
            if (
                not term.strip()
                or len(term) > 200
                or any(
                    unicodedata.category(char).startswith("C") or char in "\u2028\u2029"
                    for char in term
                )
            ):
                raise InvalidRequestError(
                    "protected terms must contain 1-200 characters without controls or line breaks",
                    code="invalid_options",
                )
        return sorted({term.strip() for term in terms})

    def translation_settings(self, owner_id: str) -> dict[str, Any]:
        with self._db.session() as session:
            user = session.get(User, owner_id)
            if user is None:
                raise NotFoundError("user")
            prefs = user.translation_settings
            return {
                "protected_terms": list(prefs.get("protected_terms", [])),
                "use_default_dictionary": prefs.get("use_default_dictionary", True),
                "default_protected_terms": list(get_default_protected_terms()),
            }

    def update_translation_settings(
        self, owner_id: str, terms: tuple[str, ...], use_default_dictionary: bool
    ) -> dict[str, Any]:
        canonical = self._terms(terms)
        with self._db.session() as session:
            user = session.get(User, owner_id)
            if user is None:
                raise NotFoundError("user")
            user.translation_settings = {
                "protected_terms": canonical,
                "use_default_dictionary": use_default_dictionary,
            }
        return self.translation_settings(owner_id)

    def _effective_options(
        self, owner_id: str, options: DocumentTranslationOptions, request: SubmitOptions
    ) -> DocumentTranslationOptions:
        prefs = self.translation_settings(owner_id)
        values = options.model_dump()
        # Each source is bounded at 500; the exact union (at most 1,000) is persisted.
        values["protected_terms"] = sorted(
            set(prefs["protected_terms"]) | set(options.protected_terms)
        )
        values["use_default_dictionary"] = (
            prefs["use_default_dictionary"]
            if request.use_default_dictionary is None
            else request.use_default_dictionary
        )
        return DocumentTranslationOptions.model_validate(values)

    # Options and identity

    def _options(self, request: SubmitOptions) -> tuple[str, DocumentTranslationOptions]:
        mode = request.translator_id or request.mode or ""
        if request.retention not in ("saved", "temporary", "cached"):
            raise InvalidRequestError(
                "retention must be saved or temporary", code="invalid_options"
            )
        fit: dict[str, object] = dict(request.fit or {})
        if request.min_scale is not None:
            fit["min_scale"] = request.min_scale
        if request.min_size_pt is not None:
            fit["min_size_pt"] = request.min_size_pt
        try:
            options = DocumentTranslationOptions.model_validate(
                {
                    "source": request.source,
                    "target": request.target,
                    "protected_terms": self._terms(request.protected_terms),
                    "use_default_dictionary": request.use_default_dictionary
                    if request.use_default_dictionary is not None
                    else True,
                    "txt_encoding": request.txt_encoding,
                    "fit": fit,
                }
            )
        except ValidationError as exc:
            fields = sorted({".".join(str(p) for p in e["loc"]) for e in exc.errors()})
            raise InvalidRequestError(
                f"invalid options: {', '.join(fields)}", code="invalid_options", fields=fields
            ) from None
        return mode, options

    @staticmethod
    def _request_hash(
        input_hash: str,
        mode: str,
        options: DocumentTranslationOptions,
        request: SubmitOptions,
        document_id: str | None,
        *,
        legacy: bool = False,
    ) -> str:
        selection = (
            {"mode": mode}
            if legacy
            else {"translator_id": request.translator_id, "mode": request.mode}
        )
        request_options = options.model_dump(mode="json", exclude={"use_default_dictionary"})
        if request.use_default_dictionary is not None:
            request_options["use_default_dictionary"] = request.use_default_dictionary
        canonical = json.dumps(
            {
                "input": input_hash,
                "document": document_id,
                **selection,
                "options": request_options,
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
        staging: bool = False,
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
            if not new_document and not staging:
                with self._db.session() as session:
                    existing = result_repo.document_by_blob(session, owner_id, staged.sha256)
                    if existing is not None:
                        return self._document_view(session, existing), False
            fmt, source, status = self._detect(staged)
            stored = self._store.put(staged)
        finally:
            self._store.discard(staged)
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
                    staging_expires_at=utcnow()
                    + timedelta(hours=self._settings.staging_retention_hours)
                    if staging
                    else None,
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
        if request.selection_policy == "website_auto":
            return self._accept_cached(
                owner_id, document_id, request, submission_id, batch_id, client_item_id
            )
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
        replay = self._replay(
            owner_id,
            request_hash,
            submission_id,
            batch_id,
            client_item_id,
            legacy_context=(digest, options, request, document_id),
        )
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
        if request.selection_policy == "website_auto":
            document, _ = self.create_document(owner_id, filename, stream, staging=True)
            return self._accept_cached(
                owner_id, document.id, request, submission_id, batch_id, client_item_id
            )
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
                    owner_id,
                    request_hash,
                    submission_id,
                    batch_id,
                    client_item_id,
                    legacy_context=(staged.sha256, options, request, document_id),
                )
                if replay is not None:
                    return replay
            try:
                fmt, source, status = self._detect(staged)
            except DocumentRejectedError as exc:
                hash_for_rejection = self._request_hash(staged.sha256, mode, options, request, None)
                self._replay(
                    owner_id,
                    hash_for_rejection,
                    submission_id,
                    batch_id,
                    client_item_id,
                    legacy_context=(staged.sha256, options, request, None),
                )
                return self._reject(
                    owner_id, name, hash_for_rejection, exc, batch_id, client_item_id
                )
            stored = self._store.put(staged)
        finally:
            self._store.discard(staged)
        try:
            if request.retention == "saved" and document_id is None:
                document_id = self._file_document(
                    owner_id, name, fmt, stored.sha256, stored.size, source, status
                )
            request_hash = self._request_hash(stored.sha256, mode, options, request, document_id)
            replay = self._replay(
                owner_id,
                request_hash,
                submission_id,
                batch_id,
                client_item_id,
                legacy_context=(stored.sha256, options, request, document_id),
            )
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
                detection_metadata={"format": fmt, "source": source, "status": status},
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

    def _matches_request(
        self,
        saved_hash: str,
        request_hash: str,
        job: Job | None,
        context: tuple[str, DocumentTranslationOptions, SubmitOptions, str | None] | None,
    ) -> bool:
        if saved_hash == request_hash:
            return True
        if job is None or job.translator_id is not None or context is None:
            return False
        digest, options, request, document_id = context
        if request.translator_id is not None or (
            request.mode is not None and request.mode != job.mode
        ):
            return False
        return saved_hash == self._request_hash(
            digest, job.mode, options, request, document_id, legacy=True
        )

    def _replay(
        self,
        owner_id: str,
        request_hash: str,
        submission_id: str | None,
        batch_id: str | None,
        client_item_id: str | None,
        *,
        legacy_context: tuple[str, DocumentTranslationOptions, SubmitOptions, str | None]
        | None = None,
    ) -> SubmitResult | None:
        with self._db.session() as session:
            if submission_id is not None:
                job = job_repo.by_submission(session, owner_id, submission_id)
                if job is None:
                    return None
                if not self._matches_request(job.request_hash, request_hash, job, legacy_context):
                    raise ConflictError(
                        "this submission ID was used with a different file or options",
                        code="idempotency_mismatch",
                    )
                return SubmitResult(job_view(session, job), None, replayed=True)
            batch = self._open_batch(session, owner_id, batch_id or "", for_replay=True)
            item = batch_repo.item_by_client_id(session, batch.id, client_item_id or "")
            if item is None:
                return None
            legacy_job = job_repo.get(session, item.job_id) if item.job_id else None
            if not self._matches_request(
                item.request_hash, request_hash, legacy_job, legacy_context
            ):
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
        try:
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
        except IntegrityError:
            self._replay(owner_id, request_hash, None, batch_id, client_item_id)
            raise
        raise DocumentRejectedError(exc.message, code=exc.code, status=exc.status, item_id=item_id)

    def _accept_with_retry(
        self,
        owner_id: str,
        name: str,
        fmt: str,
        input_hash: str,
        size: int,
        mode: str,
        options: DocumentTranslationOptions,
        request: SubmitOptions,
        document_id: str | None,
        request_hash: str,
        submission_id: str | None,
        batch_id: str | None,
        client_item_id: str | None,
        *,
        detection_metadata: dict[str, Any] | None = None,
    ) -> SubmitResult:
        if request.selection_policy == "desktop_auto":
            if (
                request.retention != "temporary"
                or request.mode
                or request.translator_id
                or request.source != "auto"
            ):
                raise InvalidRequestError(
                    "desktop automatic translation requires target-only temporary work",
                    code="invalid_options",
                )
            policy = pinned_policy(self._settings, self._catalog, options, desktop=True)
            if detection_metadata is not None:
                policy["detection_metadata"] = detection_metadata
            self._store.sweep_capacity()
            with self._db.session() as session:
                existing = (
                    job_repo.by_submission(session, owner_id, submission_id)
                    if submission_id
                    else None
                )
                if existing is not None:
                    if existing.request_hash != request_hash:
                        raise ConflictError(
                            "this submission ID was used with a different file or options",
                            code="idempotency_mismatch",
                        )
                    return SubmitResult(job_view(session, existing), None, replayed=True)
                if (
                    job_repo.count_nonterminal(session) >= self._settings.max_queued_jobs
                    or job_repo.count_nonterminal(session, owner_id)
                    >= self._settings.max_queued_jobs_per_user
                ):
                    raise AdmissionError("the translation queue is full; retry later")
                job = job_repo.insert(
                    session,
                    owner_id=owner_id,
                    retention="temporary",
                    kind="translate",
                    original_name=name,
                    format=fmt,
                    input_blob=input_hash,
                    input_size=size,
                    options=options.model_dump(mode="json"),
                    mode="llm",
                    source_requested="auto",
                    target=options.target.value,
                    fingerprint=policy["digest"],
                    policy=policy,
                    submission_id=submission_id,
                    batch_id=batch_id,
                    request_hash=request_hash,
                    max_attempts=self._settings.max_attempts,
                )
                capacity.reserve(
                    session,
                    self._settings,
                    job.id,
                    "output",
                    self._settings.max_output_bytes + self._settings.max_report_bytes,
                )
                capacity.reserve(
                    session, self._settings, job.id, "work", self._settings.max_workspace_bytes
                )
                return SubmitResult(job_view(session, job), None, replayed=False)
        if request.retention == "cached":
            raise InvalidRequestError(
                "cached retention requires website_auto", code="invalid_options"
            )
        mode = resolve_translator(
            self._catalog.translators,
            self._catalog.default_translator_id,
            request.translator_id,
            request.mode,
        ).id
        options = self._effective_options(owner_id, options, request)
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
            replay = self._replay(
                owner_id,
                request_hash,
                submission_id,
                batch_id,
                client_item_id,
                legacy_context=(input_hash, options, request, document_id),
            )
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
        mode: str,
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
                mode=resolve_translator(
                    self._catalog.translators, self._catalog.default_translator_id, mode, None
                ).mode.value,
                translator_id=mode,
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
            job=self._readable_job_view(session, job) if job else None,
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
                    job=self._readable_job_view(session, job) if job else None,
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
                        if job.kind == "waiter":
                            shared.detach(session, job, now)
                        else:
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

    def has_pending_jobs(self, owner_id: str) -> bool:
        """Whether the owner has unfinished work, independent of workspace dismissal."""
        with self._db.session() as session:
            return job_repo.count_nonterminal(session, owner_id) > 0

    def reconfigure_desktop_catalog(
        self, settings: ServerSettings, catalog: EngineIdentities
    ) -> None:
        """Replace desktop capability configuration while admission is locked and idle.

        The desktop composition root holds its admission lock across this call and
        the matching runner swap. Existing jobs are never retargeted by installation.
        """
        if settings.data_dir.resolve() != self._settings.data_dir.resolve():
            raise InvalidRequestError("desktop reconfiguration cannot change the data directory")
        with self._db.session() as session:
            if job_repo.count_nonterminal(session):
                raise ConflictError("wait for current translations before changing offline support")
        self._settings = settings
        self._catalog = catalog

    def release_desktop_result(self, owner_id: str, job_id: str) -> None:
        """Release managed bytes after a durable local export; keep recent job metadata.

        Only automatic temporary jobs belong to the desktop export contract. Explicit
        internal-app temporary jobs retain their advertised exact-result lifetime.
        """
        with self._db.session() as session:
            job = self._owned_job(session, owner_id, job_id)
            if job.retention != "temporary" or job.policy is None:
                raise InvalidRequestError("this job is not a desktop export")
            if job.status in job_repo.NONTERMINAL:
                raise ConflictError("the desktop job is still running")
            result = session.get(JobResult, job.result_id) if job.result_id else None
            job.result_id = None
            session.flush()
            if result is not None:
                session.delete(result)
        self._store.collect(holder=f"desktop-export:{job_id}", pending_grace=timedelta(hours=24))

    def _owned_job(self, session: Session, owner_id: str, job_id: str) -> Job:
        job = job_repo.get_owned(session, owner_id, job_id)
        if job is None:
            raise NotFoundError("job")
        return job

    def get_job(self, owner_id: str, job_id: str) -> JobView:
        with self._db.session() as session:
            job = self._owned_job(session, owner_id, job_id)
            return self._readable_job_view(session, job)

    def _readable_job_view(self, session: Session, job: Job) -> JobView:
        view = job_view(session, job)
        if job.kind == "waiter" and view.result_available:
            grant = shared.grant_for_job(session, job)
            result = shared.current(session, grant) if grant else None
            if result is None or not self._store.verify(result.output_blob):
                return replace(view, result_available=False)
        return view

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
            views = [self._readable_job_view(session, j) for j in rows[:limit]]
            last = rows[limit - 1] if len(rows) > limit else None
            return Page(views, _cursor(last.created_at, last.id) if last else None)

    def cancel_job(self, owner_id: str, job_id: str) -> JobView:
        with self._db.session() as session:
            job = self._owned_job(session, owner_id, job_id)
            if job.kind == "waiter":
                shared.detach(session, job, utcnow())
            elif job.status in job_repo.NONTERMINAL:
                job_repo.request_cancel(session, job.id, utcnow())
                user_repo.audit(
                    session,
                    "job_cancel_requested",
                    actor=owner_id,
                    target_type="job",
                    target_id=job.id,
                )
                session.refresh(job)
                if job.status not in job_repo.NONTERMINAL:
                    shared.finish(session, job, None, utcnow())
            view = job_view(session, job)
        if view.status not in job_repo.NONTERMINAL:
            try:
                self._store.collect(
                    holder=f"cancel-input:{job_id}", pending_grace=timedelta(hours=24)
                )
            except Exception:
                logger.warning("cancelled input cleanup deferred to retention sweep")
        return view

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
        if job.kind == "waiter":
            grant = shared.grant_for_job(session, job)
            if grant is None:
                raise NotFoundError("history")
            result = shared.current(session, grant)
            if result is None:
                raise TranslationUnavailableError()
            return job, result
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
        if blob is None or blob.state != "available" or not self._store.verify(digest):
            logger.error("result %s failed download integrity/readability verification", result.id)
            raise TranslationUnavailableError()
        pin = blob_repo.pin(session, digest, blob.size, utcnow() + timedelta(hours=1))
        if pin is None:
            raise TranslationUnavailableError()
        slot_id = session.scalar(
            select(SharedSlot.id).where(SharedSlot.current_result_id == result.id)
        )
        result_id = result.id

        def completed() -> None:
            with self._db.session() as finish_session:
                blob_repo.release_pins(finish_session, [pin])
                slot = finish_session.get(SharedSlot, slot_id) if slot_id else None
                if slot and slot.current_result_id == result_id:
                    slot.last_used_at = utcnow()

        return FileView(
            self._store.path(digest),
            filename,
            media,
            blob.size,
            digest,
            completed,
        )


def cancel_user_jobs(db: Database, user_id: str) -> int:
    """Request cancellation of every unfinished job of a (disabled) user (ADR-015)."""
    with db.session() as session:
        return job_repo.cancel_for_user(session, user_id, utcnow())
