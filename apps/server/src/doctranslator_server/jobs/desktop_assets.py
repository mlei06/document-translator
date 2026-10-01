"""Verified immutable model installation and validator-bound interrupted downloads."""

import hashlib
import json
import os
import re
import shutil
from collections.abc import Callable, Generator, Iterable
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import cast

import httpx


@dataclass(frozen=True)
class Asset:
    path: str
    url: str
    size: int
    sha256: str

    def validate(self) -> None:
        path = PurePosixPath(self.path)
        url = httpx.URL(self.url)
        if (
            not self.path
            or path.is_absolute()
            or ".." in path.parts
            or "\\" in self.path
            or ":" in self.path
            or path.suffix.lower() not in {".gguf", ".json", ".txt", ".model"}
            or url.scheme != "https"
            or not url.host
            or url.username
            or url.password
            or self.size <= 0
            or re.fullmatch("[0-9a-f]{64}", self.sha256) is None
        ):
            raise ValueError("Invalid approved model asset")


def _valid(path: Path, asset: Asset) -> bool:
    if not path.is_file() or path.stat().st_size != asset.size:
        return False
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest() == asset.sha256


def _managed_path(root: Path, relative: str) -> Path:
    """Refuse existing filesystem redirects before touching managed installation files."""
    if root.is_symlink() or root.is_junction():
        raise ValueError("Managed model directory cannot redirect outside its root")
    current = root
    for part in PurePosixPath(relative).parts:
        current = current / part
        if current.is_symlink() or current.is_junction():
            raise ValueError("Managed model path contains a filesystem redirect")
    if not current.resolve().is_relative_to(root.resolve()):
        raise ValueError("Managed model path escapes its root")
    return current


def _write(
    parts: Iterable[bytes], path: Path, asset: Asset, cancelled: Callable[[], bool], *, append: bool
) -> None:
    size = path.stat().st_size if append else 0
    with path.open("ab" if append else "wb") as sink:
        for block in parts:
            if cancelled():
                raise InterruptedError("Offline installation cancelled")
            size += len(block)
            if size > asset.size:
                raise ValueError("Model asset exceeds approved size")
            sink.write(block)
            sink.flush()
        os.fsync(sink.fileno())


@contextmanager
def _asset_response(
    client: httpx.Client, url: str, headers: dict[str, str]
) -> Generator[httpx.Response]:
    destination = httpx.URL(url)
    for redirects in range(6):
        if (
            destination.scheme != "https"
            or not destination.host
            or destination.username
            or destination.password
        ):
            raise ValueError("Model redirects require HTTPS without credentials")
        # Build each request explicitly so client cookies and authorization cannot cross hosts.
        request = httpx.Request("GET", destination, headers=headers)
        response = client.send(request, stream=True, follow_redirects=False, auth=None)
        try:
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("location")
                if not location or redirects == 5:
                    raise ValueError("Model redirect limit or missing destination")
                destination = destination.join(location)
                continue
            yield response
            return
        finally:
            response.close()


def _download(
    client: httpx.Client, asset: Asset, partial: Path, cancelled: Callable[[], bool]
) -> None:
    metadata = partial.with_suffix(partial.suffix + ".json")
    saved: dict[str, object] = {}
    if metadata.exists():
        try:
            raw: object = json.loads(metadata.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                saved = cast(dict[str, object], raw)
        except ValueError, OSError:
            pass
    validator = saved.get("validator")
    validator_header = saved.get("header")
    offset = partial.stat().st_size if partial.exists() else 0
    resume = (
        0 < offset < asset.size
        and saved.get("asset") == asdict(asset)
        and isinstance(validator, str)
        and bool(validator)
        and validator_header in {"etag", "last-modified"}
    )
    for attempt in range(2):
        headers = {"Accept-Encoding": "identity"}
        if resume:
            headers.update({"Range": f"bytes={offset}-", "If-Range": str(validator)})
        with _asset_response(client, asset.url, headers) as response:
            response.raise_for_status()
            append = False
            if response.status_code == 206:
                expected = f"bytes {offset}-{asset.size - 1}/{asset.size}"
                append = (
                    resume
                    and response.headers.get("content-range") == expected
                    and response.headers.get(str(validator_header)) == validator
                )
                if not append:
                    if attempt == 0:
                        resume = False
                        continue
                    raise ValueError("Model server returned an inconsistent byte range")
            elif response.status_code != 200:
                raise ValueError("Model server did not return a complete asset")
            etag = response.headers.get("etag", "")
            modified = response.headers.get("last-modified", "")
            if etag and not etag.startswith("W/"):
                current_header, current_validator = "etag", etag
            else:
                current_header, current_validator = "last-modified", modified
            if len(current_validator) > 1024:
                current_validator = ""
            metadata.write_text(
                json.dumps(
                    {
                        "asset": asdict(asset),
                        "header": current_header,
                        "validator": current_validator,
                    }
                ),
                encoding="utf-8",
            )
            _write(response.iter_bytes(1024 * 1024), partial, asset, cancelled, append=append)
            return


def install(
    root: Path,
    revision: str,
    assets: tuple[Asset, ...],
    load_test: Callable[[Path], None],
    *,
    offline: Path | None = None,
    cancelled: Callable[[], bool] = lambda: False,
) -> Path:
    """Resume only with matching validators, verify all bytes, load-test, activate atomically.

    Verified and partial files survive interruption under the approved revision. Partial
    size is capped to its manifest size. No executable model payloads are accepted.
    Existing immutable versions are never overwritten while jobs may hold them.
    """
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,100}", revision) is None:
        raise ValueError("Invalid immutable model revision")
    if not assets or len({PurePosixPath(a.path).as_posix().casefold() for a in assets}) != len(
        assets
    ):
        raise ValueError("Manifest requires unique files")
    for asset in assets:
        asset.validate()
    stage = _managed_path(root, f".staging/{revision}")
    stage.mkdir(parents=True, exist_ok=True)
    for asset in assets:
        for suffix in ("", ".part", ".part.json"):
            _managed_path(stage, asset.path + suffix)
    remaining = sum(
        asset.size - min(asset.size, (stage / (asset.path + ".part")).stat().st_size)
        if (stage / (asset.path + ".part")).is_file()
        else asset.size
        for asset in assets
    )
    if shutil.disk_usage(root).free < remaining + (256 << 20):
        raise OSError("Insufficient disk space for offline support")
    final = _managed_path(root, revision)
    if final.exists():
        raise FileExistsError("Immutable model revision already exists")
    with httpx.Client(follow_redirects=False, timeout=60) as client:
        for asset in assets:
            output = stage / asset.path
            output.parent.mkdir(parents=True, exist_ok=True)
            if _valid(output, asset):
                continue
            partial = output.with_name(output.name + ".part")
            if offline is not None:
                candidate = offline / asset.path
                if not candidate.resolve().is_relative_to(offline.resolve()):
                    raise ValueError("Offline asset escapes bundle")
                with candidate.open("rb") as source:
                    _write(
                        iter(lambda: source.read(1024 * 1024), b""),
                        partial,
                        asset,
                        cancelled,
                        append=False,
                    )
            elif not _valid(partial, asset):
                _download(client, asset, partial, cancelled)
            if not _valid(partial, asset):
                if partial.stat().st_size == asset.size:
                    partial.unlink()
                raise ValueError("Offline model integrity verification failed")
            partial.replace(output)
            partial.with_suffix(partial.suffix + ".json").unlink(missing_ok=True)
    if cancelled():
        raise InterruptedError("Offline installation cancelled")
    load_test(stage)
    if cancelled():
        raise InterruptedError("Offline installation cancelled")
    stage.rename(final)
    return final
