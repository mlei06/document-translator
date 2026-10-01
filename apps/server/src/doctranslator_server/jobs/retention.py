"""Retention (ADR-014, ADR-016): expire rows transactionally, then delete unreferenced blobs.

Saved documents and their current translations never expire (they count against the owner's
quota). Temporary results and superseded translations stop being downloadable at their advertised
``expires_at``; terminal job and batch metadata without a live result is kept for
``job_retention_days``.
"""

import contextlib
import logging
import shutil
import time
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import delete, exists, select

from doctranslator_server.db import Database
from doctranslator_server.db.models import (
    Document,
    HistoryGrant,
    Job,
    SharedSlot,
    StorageReservation,
    utcnow,
)
from doctranslator_server.db.repositories import batches as batch_repo
from doctranslator_server.db.repositories import blobs as blob_repo
from doctranslator_server.db.repositories import jobs as job_repo
from doctranslator_server.db.repositories import results as result_repo
from doctranslator_server.jobs import capacity, shared
from doctranslator_server.jobs.storage import BlobStore
from doctranslator_server.settings import ServerSettings

__all__ = ["RetentionReport", "run_retention"]

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RetentionReport:
    results: int
    jobs: int
    batches: int
    pins: int
    staging_files: int
    blobs: int


def run_retention(
    settings: ServerSettings, db: Database, store: BlobStore, *, holder: str
) -> RetentionReport:
    now = utcnow()
    with db.session() as session:
        capacity.expire_slots(session, settings)
        for document in session.scalars(
            select(Document)
            .where(Document.staging_expires_at <= now, Document.deleted_at.is_(None))
            .limit(500)
        ):
            document.deleted_at = now
        for grant in session.scalars(
            select(HistoryGrant)
            .where(
                HistoryGrant.updated_at <= now - timedelta(days=90),
                HistoryGrant.deleted_at.is_(None),
            )
            .limit(500)
        ):
            grant.deleted_at = grant.updated_at + timedelta(days=90)
            for waiter in session.scalars(select(Job).where(Job.history_id == grant.id)):
                shared.detach(session, waiter, now)
        # Revocation is permanent for these IDs. Keep a bounded metadata grace period,
        # then remove tombstones and empty slots without touching retained live grants.
        metadata_cutoff = now - timedelta(days=settings.job_retention_days)
        expired_grants = (
            select(HistoryGrant.id).where(HistoryGrant.deleted_at <= metadata_cutoff).limit(500)
        )
        session.execute(delete(HistoryGrant).where(HistoryGrant.id.in_(expired_grants)))
        empty_slots = (
            select(SharedSlot.id)
            .where(
                SharedSlot.current_result_id.is_(None),
                SharedSlot.active_work_id.is_(None),
                SharedSlot.last_used_at <= metadata_cutoff,
                ~exists().where(HistoryGrant.slot_id == SharedSlot.id),
            )
            .limit(500)
        )
        session.execute(delete(SharedSlot).where(SharedSlot.id.in_(empty_slots)))
        session.execute(
            delete(StorageReservation).where(
                StorageReservation.expires_at <= now,
                ~exists().where(
                    Job.id == StorageReservation.owner_id, Job.status.in_(("queued", "running"))
                ),
            )
        )
    with db.session() as session:
        results = result_repo.delete_expired_results(session, now)
    job_cutoff = now - timedelta(days=settings.job_retention_days)
    with db.session() as session:
        batches = batch_repo.delete_old(session, job_cutoff)
    with db.session() as session:
        jobs = job_repo.delete_finished(session, job_cutoff)
    with db.session() as session:
        result_repo.purge_deleted_documents(session)
    with db.session() as session:
        pins = blob_repo.delete_expired_pins(session, now)
    grace = timedelta(hours=settings.staging_retention_hours)
    staging = store.clean_staging(grace)
    work = settings.data_dir / "work"
    if work.is_dir():
        with db.session() as session:
            active_work = job_repo.active_work_directories(session)
        cutoff = time.time() - grace.total_seconds()
        for path in work.iterdir():
            with contextlib.suppress(OSError):
                if (
                    path.name not in active_work
                    and not path.is_symlink()
                    and not path.is_junction()
                    and path.resolve().parent == work.resolve()
                    and path.stat().st_mtime < cutoff
                ):
                    shutil.rmtree(path, ignore_errors=True)
    blobs = store.collect(holder=holder, pending_grace=grace, now=now)
    report = RetentionReport(results, jobs, batches, pins, staging, blobs)
    logger.info("retention: %s", report)
    return report
