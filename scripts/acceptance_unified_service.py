"""Real loopback API proof driven by the separate HTTP-only acceptance client."""

import json
import os
import socket
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import httpx
import uvicorn

from doctranslator_core import AutomaticTranslationPolicy
from doctranslator_server import auth
from doctranslator_server.app import build_services, create_app, migrate
from doctranslator_server.jobs.engines import EngineCatalog
from doctranslator_server.jobs.worker import Worker
from doctranslator_server.settings import ServerSettings, load_settings


def main() -> None:
    configured = load_settings()
    policy = AutomaticTranslationPolicy()
    root = Path("data/experiments/unified-api") / uuid.uuid4().hex
    root.mkdir(parents=True)
    endpoint = configured.davy_base_url or configured.llm_base_url
    credential = configured.davy_api_key or configured.llm_api_key
    models = [
        dict(
            id=name,
            label=name,
            model="gemma-4-31b-it" if name == "gemma" else name,
            deployment_revision="acceptance-2026-09-30",
        )
        for name in policy.davy_order
    ]
    settings = ServerSettings(
        _env_file=None,  # pyright: ignore[reportCallIssue]
        data_dir=root / "service",
        workers=0,
        translators=[
            dict(
                id="hy-mt-local",
                label="Local",
                engine=dict(
                    mode="llm",
                    base_url="http://127.0.0.1:8099/v1",
                    api_key="local-acceptance",
                    model="hy-mt",
                    protocol="hy-mt",
                    execution_location="server",
                    deployment_revision="acceptance-q8",
                ),
            )
        ],
        davy_base_url=endpoint,
        davy_api_key=credential,
        davy_models=models,
        default_translator_id="gemma",
        web_translation_policy=policy.model_dump(mode="json"),
        daily_backups=False,
    )
    migrate(settings)
    services = build_services(settings)
    if not isinstance(services.catalog, EngineCatalog):
        raise RuntimeError("acceptance requires the real engine catalog")
    user = auth.create_user(services.db, "Synthetic API acceptance")
    key = auth.create_key(services.db, user.id).secret
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(create_app(services), log_level="error"))
    host_thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    host_thread.start()
    stop = threading.Event()
    worker = Worker.from_catalog(
        settings, services.db, services.store, services.queue(), services.catalog
    )
    worker_thread = threading.Thread(target=worker.run, args=(stop,), daemon=True)
    try:
        deadline = time.monotonic() + 60
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.1)
        if not server.started:
            raise RuntimeError("acceptance API startup timed out")
        url = f"http://127.0.0.1:{port}"
        with httpx.Client(base_url=url, headers={"Authorization": f"Bearer {key}"}) as client:
            options = dict(
                target="en",
                selection_policy="website_auto",
                retention="cached",
                download_semantics="current_shared",
            )
            submitted = client.post(
                "/v1/jobs",
                files={"file": ("cancel.txt", b"Please cancel this test.")},
                data={"options": json.dumps(options), "submission_id": str(uuid.uuid4())},
            )
            submitted.raise_for_status()
            cancelled = client.post(f"/v1/jobs/{submitted.json()['id']}/cancel")
            if cancelled.json()["status"] != "cancelled":
                raise RuntimeError("queued cancellation failed")
        worker_thread.start()
        fixture_root = Path("data/experiments/unified-runtime")
        latest = max(
            (path for path in fixture_root.iterdir() if path.is_dir()), key=lambda path: path.name
        )
        sources = [
            latest / "source.txt",
            Path("tests/fixtures/docx/report.docx"),
            Path("tests/fixtures/pptx/deck.pptx"),
            Path("tests/fixtures/xlsx/features-shared.xlsx"),
            latest / "source.pdf",
        ]
        environment = dict(os.environ, DOCTRANSLATOR_API_KEY=key)
        for phase in ("cold", "warm"):
            command = [
                sys.executable,
                "scripts/acceptance_http_client.py",
                "--server",
                url,
                "--to",
                "en",
                "--automatic",
                "--out",
                str(root / phase),
                *map(str, sources),
            ]
            result = subprocess.run(  # noqa: S603 - fixed repository HTTP client, no shell
                command,
                env=environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=900,
            )
            (root / f"{phase}.jsonl").write_text(result.stdout, encoding="utf-8")
            print(result.stdout, end="", flush=True)
            if result.returncode:
                raise RuntimeError(f"independent {phase} client failed (exit {result.returncode})")
        print(json.dumps({"cancel": "passed", "evidence": str(root)}))
    finally:
        stop.set()
        server.should_exit = True
        host_thread.join(30)
        if worker_thread.ident is not None:
            worker_thread.join(120)
        sock.close()
        services.close()


if __name__ == "__main__":
    main()
