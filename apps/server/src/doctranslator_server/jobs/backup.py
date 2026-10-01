"""Backup and restore of the database together with every blob it references (ADR-016)."""

import hashlib
import json
import re
import shutil
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import delete, select

from doctranslator_server.db import Database
from doctranslator_server.db.models import (
    Blob,
    BlobPin,
    Document,
    Job,
    SharedSlot,
    StorageReservation,
    new_id,
    utcnow,
)
from doctranslator_server.db.repositories import blobs as blob_repo
from doctranslator_server.db.repositories import users as locks
from doctranslator_server.jobs.storage import CHUNK, GC_LOCK, BlobStore
from doctranslator_server.settings import ServerSettings

__all__ = ["BackupError", "BackupSummary", "backup", "restore"]

DATABASE = "doctranslator.db"
MANIFEST = "manifest.json"


class BackupError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class BackupSummary:
    blobs: int
    bytes: int
    database_sha256: str
    revision: str | None


def _sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _blob_path(root: Path, digest: str) -> Path:
    return root / "blobs" / "sha256" / digest[:2] / digest


def backup(db: Database, store: BlobStore, destination: Path, *, holder: str) -> BackupSummary:
    """Snapshot the database and copy every blob it references into ``destination``.

    The service may keep running: blobs are immutable, and the GC lock held here keeps cleanup
    from deleting a blob the snapshot references.
    """
    if destination.exists() and any(destination.iterdir()):
        raise BackupError("the backup destination must be empty")
    destination.mkdir(parents=True, exist_ok=True)
    now = utcnow()
    with db.session() as session:
        if not locks.acquire_lock(session, GC_LOCK, holder, now + timedelta(hours=6), now):
            raise BackupError("storage cleanup is running; retry the backup shortly")
    try:
        snapshot = destination / DATABASE
        db.snapshot(snapshot)
        copy = Database(f"sqlite:///{snapshot.as_posix()}")
        try:
            revision = copy.current_revision()
            with copy.session() as session:
                # Recovery snapshots deliberately exclude transient website originals.
                # Restored active requests need a new verified upload, never a missing source.
                for document in session.scalars(
                    select(Document).where(Document.staging_expires_at.is_not(None))
                ):
                    document.deleted_at = now
                for job in session.scalars(
                    select(Job).where(
                        Job.retention == "cached", Job.status.in_(("queued", "running"))
                    )
                ):
                    job.status = "failed"
                    job.error_code = "recovery_requires_upload"
                    job.error_message = "Upload the original to resume after recovery."
                    job.finished_at = now
                    job.claim_token = None
                    job.lease_until = None
                for slot in session.scalars(select(SharedSlot)):
                    slot.active_work_id = None
                session.execute(delete(StorageReservation))
                session.execute(delete(BlobPin))
                session.flush()
                referenced = blob_repo.referenced_hashes(session)
                session.execute(delete(Blob).where(Blob.hash.not_in(list(referenced))))
        finally:
            copy.dispose()
        total = 0
        for digest, size in sorted(referenced.items()):
            target = _blob_path(destination, digest)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(store.path(digest), target)
            if _sha256(target) != digest:
                raise BackupError(f"stored blob {digest[:12]} is damaged")
            total += size
        database_sha256 = _sha256(snapshot)
        manifest = {
            "format": 1,
            "created_at": now.isoformat(),
            "revision": revision,
            "database_sha256": database_sha256,
            "blobs": referenced,
        }
        (destination / MANIFEST).write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    finally:
        with db.session() as session:
            locks.release_lock(session, GC_LOCK, holder)
    return BackupSummary(len(referenced), total, database_sha256, revision)


def restore(source: Path, data_dir: Path) -> BackupSummary:
    """Verify a backup completely, then place it into an empty data directory."""
    manifest_path = source / MANIFEST
    if not manifest_path.is_file():
        raise BackupError("not a backup directory (manifest.json is missing)")
    if (data_dir / DATABASE).exists():
        raise BackupError("the data directory already has a database; restore into an empty one")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    snapshot = source / DATABASE
    if _sha256(snapshot) != manifest["database_sha256"]:
        raise BackupError("the backup database does not match its manifest")
    try:
        blobs = TypeAdapter(dict[str, int]).validate_python(manifest["blobs"], strict=True)
    except (KeyError, ValidationError) as exc:
        raise BackupError("backup contains invalid blob metadata") from exc
    if any(not re.fullmatch(r"[0-9a-f]{64}", digest) or size < 0 for digest, size in blobs.items()):
        raise BackupError("backup contains an invalid blob identity or size")
    for digest in blobs:
        path = _blob_path(source, digest)
        if not path.is_file() or _sha256(path) != digest:
            raise BackupError(f"backup blob {digest[:12]} is missing or damaged")
    copy = Database(f"sqlite:///{snapshot.as_posix()}")
    try:
        with copy.session() as session:
            referenced = blob_repo.referenced_hashes(session)
    finally:
        copy.dispose()
    missing = set(referenced) - set(blobs)
    if missing:
        raise BackupError(f"{len(missing)} referenced blobs are not in the backup")
    data_dir.mkdir(parents=True, exist_ok=True)
    total = 0
    for digest, size in blobs.items():
        target = _blob_path(data_dir, digest)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(_blob_path(source, digest), target)
        total += size
    shutil.copyfile(snapshot, data_dir / DATABASE)
    return BackupSummary(len(blobs), total, manifest["database_sha256"], manifest.get("revision"))


def daily_backup(settings: ServerSettings, db: Database, store: BlobStore) -> None:
    """Seven daily recovery points, with an independent physical-byte budget."""
    if not settings.daily_backups:
        return
    holder = f"daily-backup:{new_id()}"
    now = utcnow()
    with db.session() as session:
        if not locks.acquire_lock(session, "daily-backup", holder, now + timedelta(hours=6), now):
            return
    try:
        _daily_backup(settings, db, store, holder=holder)
    finally:
        with db.session() as session:
            locks.release_lock(session, "daily-backup", holder)


def _daily_backup(settings: ServerSettings, db: Database, store: BlobStore, *, holder: str) -> None:
    data_root = settings.data_dir.resolve()
    root = data_root / "backups"
    if root.is_symlink() or root.is_junction() or root.resolve().parent != data_root:
        raise BackupError("unsafe backup directory")
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    name = utcnow().strftime("%Y-%m-%d")
    destination = root / name
    if (destination / MANIFEST).is_file():
        return
    used = sum(path.stat().st_size for path in root.rglob("*") if path.is_file())
    with db.session() as session:
        required = sum(blob_repo.referenced_hashes(session).values())
    database_file = settings.data_dir / DATABASE
    required += database_file.stat().st_size if database_file.exists() else 0
    if used + required > settings.backup_budget_bytes:
        raise BackupError("daily backup budget has insufficient old-plus-new headroom")
    pending = root / f"{name}.pending"
    if pending.exists():
        if pending.is_symlink() or pending.resolve().parent != root:
            raise BackupError("unsafe pending backup path")
        shutil.rmtree(pending)
    backup(db, store, pending, holder=holder)
    pending.replace(destination)
    points = sorted(
        path
        for path in root.iterdir()
        if path.is_dir()
        and len(path.name) == 10
        and path.name[4] == "-"
        and path.name[7] == "-"
        and path.name.replace("-", "").isdigit()
        and (path / MANIFEST).is_file()
    )
    for old in points[:-7]:
        if old.is_symlink() or old.resolve().parent != root:
            raise BackupError("unsafe recovery point path")
        shutil.rmtree(old)
