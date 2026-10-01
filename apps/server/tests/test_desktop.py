import hashlib
import io
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from doctranslator_server.auth.desktop import DesktopAuthenticator
from doctranslator_server.auth.desktop_credentials import protect_secret, unprotect_secret
from doctranslator_server.db import Database
from doctranslator_server.desktop import read_bootstrap, secure_app, windows_identity
from doctranslator_server.jobs.desktop_assets import Asset, install
from doctranslator_server.jobs.desktop_files import digest, discover, export_file


def test_bootstrap_never_accepts_short_or_unbounded_secrets() -> None:
    token = "a1" * 32
    assert read_bootstrap(io.StringIO(json.dumps({"protocol": 1, "token": token}) + "\n")) == token
    for raw in ('{"protocol":2}\n', '{"protocol":1,"token":"short"}\n', "x" * 4097):
        with pytest.raises(ValueError):
            read_bootstrap(io.StringIO(raw))


def test_loopback_every_route_requires_token_and_native_origin(tmp_path: Path) -> None:
    db = Database(f"sqlite:///{tmp_path / 'host.db'}")
    db.migrate()
    auth = DesktopAuthenticator(db, "S-1-5-21-123", "a" * 64)
    app = FastAPI()
    secure_app(app, auth, 12345)

    @app.get("/health")
    def health() -> dict[str, bool]:
        return {"ready": True}

    with TestClient(app, base_url="http://127.0.0.1:12345") as client:
        headers = {"authorization": "Bearer " + "a" * 64}
        assert client.get("/health").status_code == 401
        assert client.get("/health", headers=headers).status_code == 200
        assert (
            client.get("/health", headers={**headers, "origin": "http://evil"}).status_code == 403
        )
        assert client.get("/health", headers={**headers, "host": "evil"}).status_code == 403
        assert client.get("/openapi.json").status_code == 401
        again = DesktopAuthenticator(db, "S-1-5-21-123", "b" * 64)
        assert again.authenticate("Bearer " + "b" * 64) == auth.authenticate(
            headers["authorization"]
        )
    db.dispose()


def test_discovery_dedupe_exclusion_cancel_and_unsupported(tmp_path: Path) -> None:
    (tmp_path / "one.txt").write_text("one")
    (tmp_path / "bad.exe").write_text("bad")
    excluded = tmp_path / "exports"
    excluded.mkdir()
    (excluded / "result.txt").write_text("result")
    rows = list(discover([tmp_path, tmp_path / "one.txt"], excluded=[excluded]))
    assert len(rows) == 2
    assert len([r for r in rows if r.error]) == 1
    assert list(discover([tmp_path], cancelled=lambda: True)) == []


def test_parallel_exports_never_overwrite_and_verify_bytes(tmp_path: Path) -> None:
    source = tmp_path / "report.txt"
    source.write_text("original")
    output = tmp_path / "output.txt"
    output.write_text("translated")
    checksum = digest(output)

    def publish(_index: int) -> Path:
        return export_file(output, source, tmp_path, "en", checksum)

    with ThreadPoolExecutor(max_workers=8) as pool:
        paths = list(pool.map(publish, range(20)))
    assert len(set(paths)) == 20
    assert all(p.read_text() == "translated" for p in paths)
    assert source.read_text() == "original"
    with pytest.raises(ValueError, match="integrity"):
        export_file(output, source, tmp_path, "en", "bad")
    assert not list(tmp_path.glob(".lenny-export-*"))


def test_offline_assets_corruption_and_load_failure_never_activate(tmp_path: Path) -> None:
    media = tmp_path / "media"
    media.mkdir()
    (media / "model.gguf").write_bytes(b"test model")
    asset = Asset(
        "model.gguf", "https://assets.example/model", 10, hashlib.sha256(b"test model").hexdigest()
    )
    root = tmp_path / "models"
    installed = install(root, "revision-1", (asset,), lambda _: None, offline=media)
    assert (installed / "model.gguf").read_bytes() == b"test model"
    (media / "model.gguf").write_bytes(b"corruption")
    with pytest.raises(ValueError):
        install(root, "revision-2", (asset,), lambda _: None, offline=media)
    assert not (root / "revision-2").exists()
    for name in ("../model.gguf", "C:/model.gguf", "script.exe", "model:stream.gguf"):
        with pytest.raises(ValueError):
            Asset(name, asset.url, asset.size, asset.sha256).validate()


def test_export_reconciles_crash_after_publication(tmp_path: Path) -> None:
    source = tmp_path / "original.txt"
    source.write_text("original")
    output = tmp_path / "translated.txt"
    output.write_text("translated")
    checksum = digest(output)
    planned: list[Path] = []
    published = export_file(output, source, tmp_path, "en", checksum, before_publish=planned.append)
    assert planned == [published]
    recovered = export_file(output, source, tmp_path, "en", checksum, planned=planned[0])
    assert recovered == published
    assert len(list(tmp_path.glob("original.en*.txt"))) == 1
    published.write_text("user changed this file")
    with pytest.raises(FileExistsError):
        export_file(output, source, tmp_path, "en", checksum, planned=published)
    assert published.read_text() == "user changed this file"


@pytest.mark.skipif(__import__("sys").platform != "win32", reason="Windows identity")
def test_real_windows_identity_uses_known_folder() -> None:
    sid, root = windows_identity()
    assert sid.startswith("S-1-")
    assert root.is_absolute()
    assert root.name == "Translator"


@pytest.mark.skipif(__import__("sys").platform != "win32", reason="Windows credential protection")
def test_real_windows_credential_protection() -> None:
    payload = b'{"example":"test shared credential"}'
    protected = protect_secret(payload)
    assert payload not in protected
    assert unprotect_secret(protected) == payload
    with pytest.raises(OSError, match="credential protection"):
        unprotect_secret(protected[:-8])


def test_offline_cancel_before_background_start_is_not_lost(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from doctranslator_server.jobs.desktop_offline import OfflineSupport

    support = OfflineSupport(tmp_path / "models", tmp_path / "application")
    support.installing = True
    support.cancelled.set()
    observed: list[bool] = []

    def interrupted(*, offline: Path | None = None) -> None:
        observed.append(support.cancelled.is_set())
        raise RuntimeError("Installation cancelled")

    monkeypatch.setattr(support, "add", interrupted)
    support.setup()
    assert observed == [True]
    assert not support.installing
    assert support.error == "Installation cancelled"
