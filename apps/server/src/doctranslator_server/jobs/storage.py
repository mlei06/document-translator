"""Content-addressed blob storage with reference-safe cleanup (ADR-007, ADR-016).

Files are written to ``staging/`` while hashing and published into ``blobs/sha256/xx/<hash>``
with an atomic rename, so a file at a blob path is always complete. A pin protects a blob from
cleanup until the row that references it commits.
"""

import contextlib
import hashlib
import logging
import shutil
import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import BinaryIO

from doctranslator_server.db import Database
from doctranslator_server.db.models import new_id, utcnow
from doctranslator_server.db.repositories import blobs as repo
from doctranslator_server.db.repositories import users as locks
from doctranslator_server.jobs.errors import TooLargeError, UnavailableError

__all__ = ["GC_LOCK", "BlobStore", "Staged", "StoredBlob"]

logger = logging.getLogger(__name__)

CHUNK = 1 << 20
GC_LOCK = "gc"
_DELETING_RETRIES = 50


@dataclass(frozen=True, slots=True)
class Staged:
    """A fully written staging file with its digest."""

    path: Path
    sha256: str
    size: int


@dataclass(frozen=True, slots=True)
class StoredBlob:
    sha256: str
    size: int
    pin_id: str


class BlobStore:
    def __init__(self, root: Path, db: Database, *, pin_ttl: timedelta) -> None:
        self.root = root
        self.blobs = root / "blobs" / "sha256"
        self.staging = root / "staging"
        self.blobs.mkdir(parents=True, exist_ok=True)
        self.staging.mkdir(parents=True, exist_ok=True)
        self._db = db
        self._pin_ttl = pin_ttl

    def path(self, digest: str) -> Path:
        return self.blobs / digest[:2] / digest

    def staging_path(self, suffix: str = "") -> Path:
        return self.staging / f"{new_id()}{suffix}"

    def stage(self, chunks: Iterable[bytes], *, suffix: str = "", max_bytes: int) -> Staged:
        """Write ``chunks`` to a new staging file, hashing; ``TooLargeError`` past ``max_bytes``."""
        path = self.staging_path(suffix)
        digest = hashlib.sha256()
        size = 0
        try:
            with path.open("xb") as handle:
                for chunk in chunks:
                    size += len(chunk)
                    if size > max_bytes:
                        raise TooLargeError(f"the file is larger than {max_bytes} bytes")
                    digest.update(chunk)
                    handle.write(chunk)
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        return Staged(path, digest.hexdigest(), size)

    def stage_stream(self, stream: BinaryIO, *, suffix: str = "", max_bytes: int) -> Staged:
        return self.stage(iter(lambda: stream.read(CHUNK), b""), suffix=suffix, max_bytes=max_bytes)

    def stage_file(self, source: Path, *, suffix: str = "") -> Staged:
        with source.open("rb") as handle:
            return self.stage_stream(handle, suffix=suffix, max_bytes=1 << 62)

    def put(self, staged: Staged) -> StoredBlob:
        """Publish a staged file as a pinned blob; the staging file is consumed."""
        pin_id: str | None = None
        for _ in range(_DELETING_RETRIES):
            with self._db.session() as session:
                pin_id = repo.pin(session, staged.sha256, staged.size, utcnow() + self._pin_ttl)
            if pin_id is not None:
                break
            time.sleep(0.1)  # a cleanup is deleting this content right now; re-put afterwards
        if pin_id is None:
            staged.path.unlink(missing_ok=True)
            raise UnavailableError("storage is busy; retry the request")
        target = self.path(staged.sha256)
        if target.exists():
            staged.path.unlink(missing_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                staged.path.replace(target)
            except OSError:
                staged.path.unlink(missing_ok=True)
                if not target.exists():
                    raise
        with self._db.session() as session:
            repo.mark_available(session, staged.sha256)
        return StoredBlob(staged.sha256, staged.size, pin_id)

    def put_file(self, source: Path) -> StoredBlob:
        return self.put(self.stage_file(source))

    def release_pins(self, pin_ids: list[str]) -> None:
        with self._db.session() as session:
            repo.release_pins(session, pin_ids)

    def verify(self, digest: str) -> bool:
        """The stored file exists and still has its digest."""
        path = self.path(digest)
        if not path.is_file():
            return False
        hasher = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(CHUNK), b""):
                hasher.update(chunk)
        return hasher.hexdigest() == digest

    # Cleanup

    def collect(self, *, holder: str, pending_grace: timedelta, now: datetime | None = None) -> int:
        """Delete unreferenced, unpinned blobs (ADR-016 GC); returns how many were deleted.

        Runs only while holding the GC lock, which backups also take.
        """
        now = now or utcnow()
        with self._db.session() as session:
            if not locks.acquire_lock(session, GC_LOCK, holder, now + timedelta(minutes=10), now):
                return 0
        deleted = 0
        try:
            with self._db.session() as session:
                candidates = repo.unreferenced(session, now, now - pending_grace)
            for digest in candidates:
                with self._db.session() as session:
                    claimed = repo.mark_deleting(session, digest, now, now - pending_grace)
                if not claimed:
                    continue
                self.path(digest).unlink(missing_ok=True)
                with self._db.session() as session:
                    repo.delete_deleting(session, digest)
                deleted += 1
        finally:
            with self._db.session() as session:
                locks.release_lock(session, GC_LOCK, holder)
        return deleted

    def clean_staging(self, older_than: timedelta) -> int:
        """Remove abandoned staging files (uploads that never finished)."""
        cutoff = time.time() - older_than.total_seconds()
        removed = 0
        for path in self.staging.iterdir():
            with contextlib.suppress(OSError):
                if path.stat().st_mtime < cutoff:
                    if path.is_dir():
                        shutil.rmtree(path)
                    else:
                        path.unlink()
                    removed += 1
        return removed
