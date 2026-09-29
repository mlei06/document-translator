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

from doctranslator_server.db import Database
from doctranslator_server.db.models import utcnow
from doctranslator_server.db.repositories import batches as batch_repo
from doctranslator_server.db.repositories import blobs as blob_repo
from doctranslator_server.db.repositories import jobs as job_repo
from doctranslator_server.db.repositories import results as result_repo
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
        cutoff = time.time() - grace.total_seconds()
        for path in work.iterdir():
            with contextlib.suppress(OSError):
                if path.stat().st_mtime < cutoff:
                    shutil.rmtree(path, ignore_errors=True)
    blobs = store.collect(holder=holder, pending_grace=grace, now=now)
    report = RetentionReport(results, jobs, batches, pins, staging, blobs)
    logger.info("retention: %s", report)
    return report
