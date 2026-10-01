"""Verified HTTP asset recovery, with no model/runtime quality claims."""

import hashlib
import os
import subprocess
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from doctranslator_server.jobs import desktop_assets as assets

BLOCK = 1024 * 1024
PAYLOAD = b"a" * BLOCK + b"second block"


class InterruptedStream(httpx.SyncByteStream):
    def __iter__(self) -> Iterator[bytes]:
        yield PAYLOAD[:BLOCK]
        raise httpx.ReadError("interrupted connection")


def asset(payload: bytes = PAYLOAD) -> assets.Asset:
    return assets.Asset(
        "model.gguf",
        "https://approved.example/model",
        len(payload),
        hashlib.sha256(payload).hexdigest(),
    )


def transport(
    monkeypatch: pytest.MonkeyPatch, handler: Callable[[httpx.Request], httpx.Response]
) -> None:
    client = httpx.Client

    def factory(**kwargs: Any) -> httpx.Client:
        return client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(httpx, "Client", factory)


@pytest.mark.parametrize("mismatch", [None, "validator", "range"])
@pytest.mark.parametrize("redirect", [False, True])
def test_interrupted_download_resumes_only_matching_validator_and_range(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mismatch: str | None, redirect: bool
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if redirect and request.url.host == "approved.example":
            return httpx.Response(302, headers={"location": "https://cdn.example/asset"})
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(200, headers={"etag": '"version1"'}, stream=InterruptedStream())
        if len(requests) == 2:
            assert request.headers["range"] == f"bytes={BLOCK}-"
            assert request.headers["if-range"] == '"version1"'
            start = BLOCK if mismatch != "range" else 0
            return httpx.Response(
                206,
                headers={
                    "etag": '"other"' if mismatch == "validator" else '"version1"',
                    "content-range": f"bytes {start}-{len(PAYLOAD) - 1}/{len(PAYLOAD)}",
                },
                content=PAYLOAD[BLOCK:],
            )
        assert "range" not in request.headers
        return httpx.Response(200, headers={"etag": '"version1"'}, content=PAYLOAD)

    transport(monkeypatch, handler)
    root = tmp_path / "models"
    with pytest.raises(httpx.ReadError):
        assets.install(root, "v1", (asset(),), lambda _: None)
    assert not (root / "v1").exists()
    assert (root / ".staging/v1/model.gguf.part").stat().st_size == BLOCK
    loaded: list[Path] = []
    installed = assets.install(root, "v1", (asset(),), loaded.append)
    assert (installed / "model.gguf").read_bytes() == PAYLOAD
    assert len(loaded) == 1
    assert len(requests) == (2 if mismatch is None else 3)


@pytest.mark.parametrize("payload", [b"bad", b"too long"])
def test_invalid_bytes_never_activate_or_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, payload: bytes
) -> None:
    transport(monkeypatch, lambda _: httpx.Response(200, content=payload))
    loaded: list[Path] = []
    with pytest.raises(ValueError):
        assets.install(tmp_path / "models", "v1", (asset(b"yes"),), loaded.append)
    assert loaded == []
    assert not (tmp_path / "models/v1").exists()


def test_cancelled_transfer_retains_verified_resume_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        if "range" in request.headers:
            return httpx.Response(
                206,
                headers={
                    "etag": '"v1"',
                    "content-range": f"bytes {BLOCK}-{len(PAYLOAD) - 1}/{len(PAYLOAD)}",
                },
                content=PAYLOAD[BLOCK:],
            )
        return httpx.Response(200, headers={"etag": '"v1"'}, content=PAYLOAD)

    def cancelled() -> bool:
        nonlocal calls
        calls += 1
        return calls > 1

    transport(monkeypatch, handler)
    root = tmp_path / "models"
    with pytest.raises(InterruptedError):
        assets.install(root, "v1", (asset(),), lambda _: None, cancelled=cancelled)
    assert (root / ".staging/v1/model.gguf.part").stat().st_size == BLOCK
    installed = assets.install(root, "v1", (asset(),), lambda _: None)
    assert (installed / "model.gguf").read_bytes() == PAYLOAD


@pytest.mark.parametrize(
    "name", ["../model.gguf", "C:/model.gguf", "model:alternate.gguf", "model.exe"]
)
def test_manifest_cannot_escape_or_install_executables(name: str) -> None:
    with pytest.raises(ValueError):
        assets.Asset(name, "https://approved.example/model", 3, asset(b"yes").sha256).validate()


def test_stage_redirect_cannot_write_user_files(tmp_path: Path) -> None:
    root = tmp_path / "models"
    root.mkdir()
    outside = tmp_path / "user-owned"
    outside.mkdir()
    sentinel = outside / "keep.txt"
    sentinel.write_text("preserve me")
    redirect = root / ".staging"
    try:
        redirect.symlink_to(outside, target_is_directory=True)
    except OSError:
        if os.name != "nt":
            raise
        # Fixed Windows builtin and pytest-owned absolute paths; no user-provided command.
        subprocess.run(  # noqa: S603
            [os.environ["COMSPEC"], "/d", "/c", "mklink", "/J", str(redirect), str(outside)],
            check=True,
            capture_output=True,
        )
    with pytest.raises(ValueError, match="redirect"):
        assets.install(root, "v1", (asset(),), lambda _: None)
    assert sentinel.read_text() == "preserve me"
    assert list(outside.iterdir()) == [sentinel]


def test_failed_load_keeps_verified_assets_without_activating(tmp_path: Path) -> None:
    media = tmp_path / "media"
    media.mkdir()
    (media / "model.gguf").write_bytes(b"approved")
    root = tmp_path / "models"

    def fail(_: Path) -> None:
        raise RuntimeError("runtime cannot load this approved model")

    with pytest.raises(RuntimeError, match="cannot load"):
        assets.install(root, "v1", (asset(b"approved"),), fail, offline=media)
    assert not (root / "v1").exists()
    assert (root / ".staging/v1/model.gguf").read_bytes() == b"approved"
    (media / "model.gguf").unlink()
    installed = assets.install(root, "v1", (asset(b"approved"),), lambda _: None, offline=media)
    assert (installed / "model.gguf").read_bytes() == b"approved"


@pytest.mark.parametrize(
    "location",
    [
        "https://cdn.example/asset",
        "http://cdn.example/asset",
        "https://user:secret@cdn.example/asset",
    ],
)
def test_download_redirects_are_bounded_https_without_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, location: str
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert "authorization" not in request.headers and "cookie" not in request.headers
        if len(requests) == 1:
            return httpx.Response(
                302, headers={"location": location, "set-cookie": "private=value; Domain=example"}
            )
        return httpx.Response(200, content=b"yes")

    transport(monkeypatch, handler)
    if location == "https://cdn.example/asset":
        result = assets.install(tmp_path / "models", "v1", (asset(b"yes"),), lambda _: None)
        assert (result / "model.gguf").read_bytes() == b"yes"
        assert len(requests) == 2
    else:
        with pytest.raises(ValueError, match="HTTPS"):
            assets.install(tmp_path / "models", "v1", (asset(b"yes"),), lambda _: None)
        assert len(requests) == 1


def test_redirect_loop_is_bounded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    requests = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(302, headers={"location": "/again"})

    transport(monkeypatch, handler)
    with pytest.raises(ValueError, match="redirect limit"):
        assets.install(tmp_path / "models", "v1", (asset(b"yes"),), lambda _: None)
    assert requests == 6
