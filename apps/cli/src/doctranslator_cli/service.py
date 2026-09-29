"""HTTP client for the shared service's REST API (ADR-010). Never imports the server.

The credential comes from ``DOCTRANSLATOR_API_KEY`` or the OS vault, never from a command-line
argument, and is never printed. TLS is verified against the OS trust store (company CA).
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

import contextlib
import hashlib
import json
import os
import ssl
import time
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import truststore

__all__ = [
    "Download",
    "ServiceClient",
    "ServiceError",
    "ServiceUnavailableError",
]

CHUNK = 1 << 20


class ServiceError(Exception):
    """An error response from the service (with its stable ``code``)."""

    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        retry_after: float | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.retryable = retryable
        self.retry_after = retry_after
        self.details = details or {}


class ServiceUnavailableError(Exception):
    """The service could not be reached (network, TLS or timeout)."""


@dataclass(frozen=True, slots=True)
class Download:
    path: Path
    size: int
    sha256: str


def _error(response: httpx.Response) -> ServiceError:
    try:
        body = response.json()
    except ValueError:
        body = {}
    retry_after = response.headers.get("retry-after")
    return ServiceError(
        response.status_code,
        str(body.get("code", f"http_{response.status_code}")),
        str(body.get("message", response.reason_phrase)),
        retryable=bool(body.get("retryable", response.status_code >= 500)),
        retry_after=float(retry_after) if retry_after and retry_after.isdigit() else None,
        details=body.get("details") or {},
    )


class ServiceClient:
    def __init__(self, base_url: str, api_key: str, *, timeout: float = 900.0) -> None:
        context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        self._client = httpx.Client(
            base_url=base_url.rstrip("/") + "/v1",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=httpx.Timeout(timeout, connect=15.0),
            verify=context,
        )

    def close(self) -> None:
        self._client.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            response = self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise ServiceUnavailableError(f"{type(exc).__name__}: {exc}") from None
        if response.status_code >= 400:
            raise _error(response)
        return response

    def get(self, path: str, **params: Any) -> Any:
        clean = {k: v for k, v in params.items() if v is not None}
        return self._request("GET", path, params=clean).json()

    def post(self, path: str, body: dict[str, Any] | None = None) -> Any:
        return self._request("POST", path, json=body or {}).json()

    def pages(self, path: str, **params: Any) -> Iterator[dict[str, Any]]:
        """Every item of a cursor-paginated list."""
        cursor: str | None = None
        while True:
            page = self.get(path, cursor=cursor, limit=200, **params)
            yield from page["items"]
            cursor = page.get("next_cursor")
            if not cursor:
                return

    # Submission

    def create_batch(self, key: str, label: str) -> dict[str, Any]:
        return self.post("/batches", {"idempotency_key": key, "label": label})

    def submit_item(
        self, batch_id: str, path: Path, name: str, options: dict[str, Any], client_item_id: str
    ) -> tuple[int, dict[str, Any]]:
        """Upload one file (streamed from disk). Returns (status, item)."""
        with path.open("rb") as handle:
            response = self._request(
                "POST",
                f"/batches/{batch_id}/items",
                files={"file": (name, handle)},
                data={"options": json.dumps(options), "client_item_id": client_item_id},
            )
        return response.status_code, response.json()

    def find_item(self, batch_id: str, client_item_id: str) -> dict[str, Any] | None:
        items = self.get(f"/batches/{batch_id}/items", client_item_id=client_item_id)["items"]
        return items[0] if items else None

    # Downloads

    def download(self, path: str, destination: Path, *, overwrite: bool = False) -> Download:
        """Stream to a private temporary file, verify size and SHA-256, then publish atomically.

        An existing destination is refused unless ``overwrite``; an interrupted download leaves
        no partial file at the destination.
        """
        if destination.exists() and not overwrite:
            raise FileExistsError(str(destination))
        temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex[:8]}.part")
        hasher = hashlib.sha256()
        size = 0
        try:
            try:
                with self._client.stream("GET", path) as response:
                    if response.status_code >= 400:
                        response.read()
                        raise _error(response)
                    expected = response.headers.get("x-content-sha256")
                    length = response.headers.get("content-length")
                    with temporary.open("xb") as handle:
                        for chunk in response.iter_bytes(CHUNK):
                            hasher.update(chunk)
                            size += len(chunk)
                            handle.write(chunk)
            except httpx.HTTPError as exc:
                raise ServiceUnavailableError(f"{type(exc).__name__}: {exc}") from None
            digest = hasher.hexdigest()
            if (expected and digest != expected) or (length and int(length) != size):
                raise ServiceUnavailableError("the download was incomplete or damaged")
            if overwrite:
                temporary.replace(destination)
            else:
                _publish_new(temporary, destination)
            return Download(destination, size, digest)
        finally:
            with contextlib.suppress(OSError):
                temporary.unlink(missing_ok=True)


def _publish_new(temporary: Path, destination: Path) -> None:
    """Move ``temporary`` to ``destination`` atomically, never replacing an existing file."""
    try:
        os.link(temporary, destination)  # fails if the destination exists, on every platform
    except FileExistsError:
        raise FileExistsError(str(destination)) from None
    except OSError:
        if os.name != "nt":
            raise
        temporary.rename(destination)  # Windows rename also refuses an existing destination
        return
    temporary.unlink()


def with_retries[T](
    action: Callable[[], T],
    *,
    attempts: int = 5,
    sleep: Callable[[float], None] = time.sleep,
    on_wait: Callable[[str, float], None] | None = None,
) -> T:
    """Retry transient failures: 429/503 (honouring Retry-After) and unreachable service."""
    delay = 2.0
    for attempt in range(1, attempts + 1):
        try:
            return action()
        except ServiceError as exc:
            if not exc.retryable or attempt == attempts:
                raise
            wait = exc.retry_after if exc.retry_after is not None else delay
            reason = exc.code
        except ServiceUnavailableError as exc:
            if attempt == attempts:
                raise
            wait, reason = delay, str(exc)
        if on_wait is not None:
            on_wait(reason, wait)
        sleep(wait)
        delay = min(delay * 2, 30.0)
    raise AssertionError("unreachable")  # pragma: no cover
