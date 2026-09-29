"""Backup and restore of the database together with every blob it references (ADR-016)."""

import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from doctranslator_server.db import Database
from doctranslator_server.db.models import utcnow
from doctranslator_server.db.repositories import blobs as blob_repo
from doctranslator_server.db.repositories import users as locks
from doctranslator_server.jobs.storage import CHUNK, GC_LOCK, BlobStore

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
                referenced = blob_repo.referenced_hashes(session)
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
    blobs: dict[str, int] = manifest["blobs"]
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
