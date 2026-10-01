"""Authenticated Windows local host using the existing API, queue and worker.

The native launcher writes one bootstrap line to inherited stdin. stdout is reserved
for readiness; documents and credentials never travel through process arguments.
"""

import csv
import ctypes
import json
import logging
import os
import re
import socket
import subprocess
import sys
import threading
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TextIO, cast

import uvicorn
from fastapi import FastAPI, Request
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

from doctranslator_server.app import build_services, create_app, migrate
from doctranslator_server.auth import AuthenticationError
from doctranslator_server.auth.desktop import DesktopAuthenticator
from doctranslator_server.auth.desktop_credentials import load_provisioned
from doctranslator_server.desktop_api import install as install_desktop
from doctranslator_server.jobs.desktop_config import configure
from doctranslator_server.jobs.desktop_offline import OfflineSupport
from doctranslator_server.jobs.desktop_runner import DesktopRunner
from doctranslator_server.jobs.engines import EngineCatalog
from doctranslator_server.jobs.retention import run_retention
from doctranslator_server.jobs.worker import Worker
from doctranslator_server.settings import ServerSettings

PROTOCOL = 1


def read_bootstrap(stream: TextIO) -> str:
    line = stream.readline(4097)
    if len(line) > 4096 or not line.endswith("\n"):
        raise ValueError("Invalid desktop bootstrap")
    raw: object = json.loads(line)
    if not isinstance(raw, dict):
        raise ValueError("Invalid desktop bootstrap")
    value = cast(dict[str, object], raw)
    if value.get("protocol") != PROTOCOL:
        raise ValueError("Unsupported desktop bootstrap protocol")
    token = value.get("token")
    if not isinstance(token, str) or re.fullmatch(r"[0-9a-f]{64}", token) is None:
        raise ValueError("Desktop session requires a 256-bit credential")
    return token


def windows_identity() -> tuple[str, Path]:
    if sys.platform != "win32":
        raise RuntimeError("Desktop runtime requires Windows x64")
    # CSIDL_LOCAL_APPDATA resolves the actual per-user known folder, not an env override.
    folder = ctypes.create_unicode_buffer(32768)
    if ctypes.windll.shell32.SHGetFolderPathW(None, 0x001C, None, 0, folder) != 0:
        raise OSError("Cannot resolve Local AppData")
    system = ctypes.create_unicode_buffer(32768)
    if not ctypes.windll.kernel32.GetSystemDirectoryW(system, len(system)):
        raise OSError("Cannot resolve Windows system directory")
    result = subprocess.run(  # noqa: S603
        [str(Path(system.value) / "whoami.exe"), "/user", "/fo", "csv", "/nh"],
        capture_output=True,
        text=True,
        check=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    sid = next(csv.reader([result.stdout.strip()]))[-1]
    if re.fullmatch(r"S-1-\d+(?:-\d+)+", sid) is None:
        raise RuntimeError("Windows did not return a valid user SID")
    return sid, Path(folder.value) / "Lenny" / "Translator"


def restrict_data_root(root: Path, sid: str) -> None:
    """New per-user runtime files inherit access only for the owning Windows SID."""
    system = ctypes.create_unicode_buffer(32768)
    if not ctypes.windll.kernel32.GetSystemDirectoryW(system, len(system)):
        raise OSError("Cannot resolve Windows system directory")
    subprocess.run(  # noqa: S603 - OS executable and argument vector, never a shell
        [
            str(Path(system.value) / "icacls.exe"),
            str(root),
            "/inheritance:r",
            "/grant:r",
            f"*{sid}:(OI)(CI)F",
        ],
        check=True,
        capture_output=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


def secure_app(app: FastAPI, auth: DesktopAuthenticator, port: int) -> None:
    @app.middleware("http")
    async def guard(request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Native IPC client does not send Origin. No browser origin is trusted.
        if request.headers.get("host") != f"127.0.0.1:{port}" or "origin" in request.headers:
            return JSONResponse({"detail": "Local application access required"}, status_code=403)
        try:
            auth.authenticate(request.headers.get("authorization"))
        except AuthenticationError:
            return JSONResponse({"detail": "Authentication required"}, status_code=401)
        return await call_next(request)


def run(settings: ServerSettings) -> None:
    """Start on a kernel-assigned loopback port. Caller owns the Windows Job Object."""
    token = read_bootstrap(sys.stdin)
    sid, root = windows_identity()
    root.mkdir(parents=True, exist_ok=True)
    restrict_data_root(root, sid)
    settings = settings.model_copy(
        update={
            "data_dir": root / "work",
            "database_url": None,
            "web_dir": None,
            "registration_enabled": False,
            "daily_backups": False,
            "job_retention_days": 30,
            "server_host": "127.0.0.1",
        }
    )
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    settings = load_provisioned(settings, Path(sys.executable).parent, root / "metadata")
    offline = OfflineSupport(root / "models", Path(sys.executable).parent)
    base_settings = settings
    settings = configure(base_settings, offline)
    migrate(settings)
    services = build_services(settings)
    services.auth = DesktopAuthenticator(services.db, sid, token)
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    port = listener.getsockname()[1]
    stop = threading.Event()
    if not isinstance(services.catalog, EngineCatalog):
        raise TypeError("Desktop requires the shared engine catalog")
    runner = DesktopRunner(services.catalog, offline.runtime)
    worker = Worker(
        settings,
        services.db,
        services.store,
        services.queue(),
        runner,
    )

    def refresh_catalog() -> None:
        with offline.lock:
            refreshed = configure(base_settings, offline)
            catalog = EngineCatalog(refreshed, runner.catalog.fonts)
            previous = runner.catalog
            try:
                services.jobs.reconfigure_desktop_catalog(refreshed, catalog)
            except Exception:
                catalog.close()
                raise
            services.catalog = catalog
            runner.catalog = catalog
            runner.runtime = offline.runtime
            previous.close()

    offline.changed = refresh_catalog
    thread = threading.Thread(target=worker.run, args=(stop,), daemon=True, name="desktop-worker")
    app = create_app(services)
    secure_app(app, services.auth, port)
    journal = install_desktop(
        app,
        services.jobs,
        services.auth.authenticate("Bearer " + token).user_id,
        root / "metadata",
        offline,
    )
    publisher = threading.Thread(
        target=journal.publish_ready, args=(stop,), daemon=True, name="desktop-exporter"
    )

    def maintain() -> None:
        while not stop.is_set():
            try:
                run_retention(settings, services.db, services.store, holder="desktop-retention")
            except Exception:
                logging.getLogger(__name__).exception("Desktop retention failed")
            stop.wait(300)

    maintenance = threading.Thread(target=maintain, daemon=True, name="desktop-retention")
    server = uvicorn.Server(uvicorn.Config(app, access_log=False, log_level="warning"))

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
        thread.start()
        publisher.start()
        maintenance.start()
        print(
            json.dumps(
                {
                    "event": "ready",
                    "protocol": PROTOCOL,
                    "api": "v1",
                    "pid": os.getpid(),
                    "base_url": f"http://127.0.0.1:{port}",
                }
            ),
            flush=True,
        )
        try:
            yield
        finally:
            stop.set()
            publisher.join(timeout=15)
            maintenance.join(timeout=15)
            thread.join(timeout=15)

    app.router.lifespan_context = lifespan

    @app.post("/v1/desktop/shutdown")
    def shutdown() -> dict[str, bool]:
        server.should_exit = True
        return {"stopping": True}

    try:
        server.run(sockets=[listener])
    finally:
        listener.close()
        if not thread.is_alive():
            services.close()
