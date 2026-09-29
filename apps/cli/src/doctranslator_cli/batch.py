"""Service batch runs: submit many files, optionally wait and download (P5 service CLI).

Files come from arguments or a JSON Lines manifest and are processed incrementally with bounded
upload concurrency; nothing holds all files or all results in memory. Every item's identity
(``client_item_id``) is written to the resume state before its upload starts, so a retry after an
uncertain response or an interrupted run reuses it and never creates a second job.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

import functools
import hashlib
import json
import os
import threading
import time
import uuid
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TextIO

from doctranslator_cli.service import (
    ServiceClient,
    ServiceError,
    ServiceUnavailableError,
    with_retries,
)

__all__ = [
    "Entry",
    "ManifestError",
    "ResumeState",
    "RunSummary",
    "download_items",
    "entries_from_manifest",
    "entries_from_paths",
    "output_name",
    "submit_all",
    "wait_for",
]

CHUNK = 1 << 20
TERMINAL = ("succeeded", "failed", "cancelled")


class ManifestError(Exception):
    pass


@dataclass
class Entry:
    """One local file and its options."""

    path: Path
    options: dict[str, Any]
    line: int | None = None

    @property
    def key(self) -> str:
        return json.dumps({"path": str(self.path), "options": self.options}, sort_keys=True)


def entries_from_paths(paths: Iterable[Path], defaults: dict[str, Any]) -> Iterator[Entry]:
    for path in paths:
        yield Entry(path.resolve(), dict(defaults))


def entries_from_manifest(manifest: Path, defaults: dict[str, Any]) -> Iterator[Entry]:
    """UTF-8 JSON Lines, one ``{path, source?, target?, mode?}`` per line; paths resolve relative
    to the manifest; per-item values override the submission defaults."""
    base = manifest.resolve().parent
    with manifest.open(encoding="utf-8") as handle:
        for number, raw in enumerate(handle, start=1):
            if not raw.strip():
                continue
            try:
                record = json.loads(raw)
            except ValueError as exc:
                raise ManifestError(f"manifest line {number} is not JSON") from exc
            if not isinstance(record, dict) or not isinstance(record.get("path"), str):
                raise ManifestError(f"manifest line {number} needs a string 'path'")
            options = dict(defaults)
            for name in ("source", "target", "mode"):
                value = record.get(name)
                if value is not None:
                    options[name] = value
            yield Entry((base / record["path"]).resolve(), options, number)


@dataclass
class ItemState:
    key: str
    path: str
    client_item_id: str
    sha256: str
    size: int
    status: str = "planned"
    """planned (identity reserved, upload not confirmed), accepted, rejected or unsubmitted."""
    item_id: str | None = None
    job_id: str | None = None
    error: str | None = None


class ResumeState:
    """The private run record (JSON Lines). Never contains credentials or file contents."""

    def __init__(self, path: Path | None) -> None:
        self.path = path
        self.run: dict[str, Any] = {}
        self.items: dict[str, ItemState] = {}
        self._lock = threading.Lock()
        self._handle: TextIO | None = None
        if path is not None and path.exists():
            with path.open(encoding="utf-8") as handle:
                for raw in handle:
                    if not raw.strip():
                        continue
                    record = json.loads(raw)
                    if record.get("type") == "run":
                        self.run = record
                    elif record.get("type") == "item":
                        record.pop("type")
                        self.items[record["key"]] = ItemState(**record)

    def _write(self, record: dict[str, Any]) -> None:
        if self.path is None:
            return
        if self._handle is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._handle = self.path.open("a", encoding="utf-8")
        self._handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._handle.flush()
        os.fsync(self._handle.fileno())

    def start(self, **run: Any) -> None:
        with self._lock:
            self.run = {"type": "run", **run}
            self._write(self.run)

    def record(self, state: ItemState) -> None:
        with self._lock:
            self.items[state.key] = state
            self._write({"type": "item", **state.__dict__})

    def close(self) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None


@dataclass
class RunSummary:
    accepted: int = 0
    rejected: int = 0
    unsubmitted: int = 0
    succeeded: int = 0
    failed: int = 0
    cancelled: int = 0
    unresolved: int = 0
    downloaded: int = 0
    download_failed: int = 0
    items: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])


def _digest(path: Path) -> tuple[str, int]:
    hasher = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK), b""):
            hasher.update(chunk)
            size += len(chunk)
    return hasher.hexdigest(), size


type Notify = Callable[[str], None]


def _submit_one(
    client: ServiceClient, batch_id: str, entry: Entry, state: ResumeState, notify: Notify
) -> ItemState:
    try:
        sha256, size = _digest(entry.path)
    except OSError as exc:
        item = ItemState(entry.key, str(entry.path), "", "", 0, "unsubmitted")
        item.error = f"cannot read the file: {exc.strerror or exc}"
        return item
    prior = state.items.get(entry.key)
    if prior is not None and prior.sha256 != sha256:
        item = ItemState(entry.key, str(entry.path), prior.client_item_id, sha256, size)
        item.status, item.error = "unsubmitted", "the file changed since the previous run"
        return item
    if prior is not None and prior.status in ("accepted", "rejected"):
        return prior
    item = prior or ItemState(entry.key, str(entry.path), str(uuid.uuid4()), sha256, size)
    if prior is None:
        state.record(item)  # the identity is durable before any network I/O
    name = entry.path.name

    def upload() -> tuple[int, dict[str, Any]]:
        return with_retries(
            lambda: client.submit_item(
                batch_id, entry.path, name, entry.options, item.client_item_id
            ),
            on_wait=lambda reason, seconds: notify(
                f"{name}: {reason}; retrying in {seconds:.0f} s"
            ),
        )

    try:
        try:
            _, body = upload()
        except ServiceError as exc:
            if exc.code != "translation_active" or not exc.details.get("job_id"):
                raise
            # The same saved document is already being translated into this language (for
            # example an identical file earlier in the batch): wait for it, then submit again
            # with the same identity, which reuses the new current translation (ADR-014).
            notify(f"{name}: waiting for the identical document already being translated")
            _wait_for_job(client, str(exc.details["job_id"]))
            _, body = upload()
        item.status, item.item_id = "accepted", body["id"]
        item.job_id = (body.get("job") or {}).get("id")
    except ServiceError as exc:
        if exc.status == 401:
            raise
        if exc.status in (415, 422) and exc.details.get("item_id"):
            item.status, item.item_id = "rejected", str(exc.details["item_id"])
        else:
            item.status = "unsubmitted"
        item.error = f"{exc.code}: {exc.message}"
    except ServiceUnavailableError as exc:
        found = _recover(client, batch_id, item.client_item_id)
        if found is None:
            item.status, item.error = "unsubmitted", f"service unavailable: {exc}"
        else:
            item.status, item.item_id = "accepted", found["id"]
            item.job_id = (found.get("job") or {}).get("id")
            if found.get("rejection_code"):
                item.status, item.error = "rejected", found["rejection_code"]
    state.record(item)
    return item


def _wait_for_job(
    client: ServiceClient, job_id: str, *, sleep: Callable[[float], None] = time.sleep
) -> None:
    interval = 1.0
    while True:
        job = with_retries(lambda: client.get(f"/jobs/{job_id}"), attempts=10)
        if job["status"] in TERMINAL:
            return
        sleep(interval)
        interval = min(interval * 1.5, 10.0)


def _recover(client: ServiceClient, batch_id: str, client_item_id: str) -> dict[str, Any] | None:
    """After an uncertain upload, ask whether the service accepted this identity."""
    try:
        return with_retries(lambda: client.find_item(batch_id, client_item_id), attempts=3)
    except ServiceError, ServiceUnavailableError:
        return None


def submit_all(
    client: ServiceClient,
    batch_id: str,
    entries: Iterable[Entry],
    state: ResumeState,
    *,
    concurrency: int,
    notify: Notify,
    on_item: Callable[[Entry, ItemState], None],
) -> None:
    """Upload every entry with at most ``concurrency`` requests in flight (a bounded window)."""
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        pending: dict[Future[ItemState], Entry] = {}
        for entry in entries:
            while len(pending) >= concurrency:
                done, _ = wait(pending, return_when=FIRST_COMPLETED)
                for future in done:
                    on_item(pending.pop(future), future.result())
            pending[pool.submit(_submit_one, client, batch_id, entry, state, notify)] = entry
        for future in list(pending):
            on_item(pending.pop(future), future.result())


def wait_for(
    client: ServiceClient,
    batch_id: str,
    notify: Notify,
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> list[dict[str, Any]]:
    """Poll the batch's items until every accepted job is terminal; returns the items."""
    interval = 2.0
    last = ""
    while True:
        items = list(
            with_retries(lambda: list(client.pages(f"/batches/{batch_id}/items")), attempts=10)
        )
        jobs = [i["job"] for i in items if i.get("job")]
        done = sum(1 for j in jobs if j["status"] in TERMINAL)
        running = [j for j in jobs if j["status"] == "running"]
        line = f"{done}/{len(jobs)} finished, {len(running)} running"
        if line != last:
            notify(line)
            last = line
        if done == len(jobs):
            return items
        sleep(interval)
        interval = min(interval * 1.5, 10.0)


def output_name(original_name: str, target: str, job_id: str) -> str:
    """``<stem>.<target>.<job id prefix><suffix>``: distinct for same-named inputs."""
    base = original_name.replace("\\", "/").rsplit("/", 1)[-1] or "document"
    stem, dot, suffix = base.rpartition(".")
    if not dot:
        stem, suffix = base, ""
    stem = "".join(ch if ch.isprintable() and ch not in '<>:"|?*' else "_" for ch in stem)
    return f"{stem or 'document'}.{target}.{job_id[:8]}{'.' + suffix if suffix else ''}"


def download_items(
    client: ServiceClient,
    items: Iterable[dict[str, Any]],
    directory: Path,
    *,
    report: bool,
    overwrite: bool,
    notify: Notify,
) -> Iterator[tuple[dict[str, Any], Path | None, str | None]]:
    """Download each succeeded item's exact job result (ADR-014); yields (item, path or None,
    error or None)."""
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    for item in items:
        job = item.get("job") or {}
        job_id = job.get("id")
        if job.get("status") != "succeeded" or not job_id or not job.get("result_available", True):
            continue
        name = output_name(item["original_name"], job["target"], job_id)
        destination = directory / name
        file_path = f"/jobs/{job_id}/file"
        report_path = f"/jobs/{job_id}/fit-report"
        try:
            with_retries(
                functools.partial(client.download, file_path, destination, overwrite=overwrite),
                attempts=4,
            )
            if report:
                report_destination = destination.with_name(name + ".report.json")
                with_retries(
                    functools.partial(
                        client.download, report_path, report_destination, overwrite=overwrite
                    ),
                    attempts=4,
                )
        except FileExistsError:
            notify(f"{name}: exists; not overwritten (use --overwrite)")
            yield item, None, "destination exists"
            continue
        except (ServiceError, ServiceUnavailableError) as exc:
            notify(f"{name}: download failed: {exc}")
            yield item, None, str(exc)
            continue
        yield item, destination, None
