"""Profile real HTTP upload, production worker, fit v2, publication and page previews.

One fresh process per model/fit-mode case. The first document is cold-model, later
documents reuse that model and the production LibreOffice renderer profile.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import shutil
import socket
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from zipfile import ZipFile

import httpx
import pymupdf
import uvicorn
from bench import ROOT, HyRuntime, baseline_module, request
from lifecycle_trace import Trace
from profiling import ResourceProfiler
from pydantic import HttpUrl, SecretStr

from doctranslator_core import LlmEngineConfig, MtEngineConfig, document_text, office_renderer
from doctranslator_server import auth
from doctranslator_server.app import Services, build_services, create_app, migrate
from doctranslator_server.jobs.engines import EngineCatalog
from doctranslator_server.jobs.pages import PageRenderer
from doctranslator_server.jobs.worker import Worker
from doctranslator_server.settings import ConfiguredTranslator, ServerSettings


def sha(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--model", choices=["small100", "hy"], required=True)
    parser.add_argument("--fit-mode", choices=["standard", "thorough"], default="standard")
    parser.add_argument("--reps", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=1800)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.reps < 1:
        parser.error("reps must be positive")
    os.chdir(ROOT)
    source = args.input.resolve()
    destination = args.out.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    state = destination / "state"
    if state.exists():
        parser.error("out/state already exists; choose a fresh case directory")
    state.mkdir()
    trace = Trace()
    report: dict[str, Any] = {
        "started_utc": datetime.now(UTC).isoformat(),
        "model": args.model,
        "fit_mode": args.fit_mode,
        "input": str(source),
        "input_sha256": sha(source),
        "input_bytes": source.stat().st_size,
        "runs": [],
        "status": "running",
        "notes": [
            "Real loopback HTTP app and real production worker/renderer in separate threads.",
            "Fresh model; OS cache retained. Later runs reuse model and LO profile.",
            "Nested events overlap; exclusive wall excludes same-thread direct children only.",
            "Thread CPU excludes native helpers. Process CPU includes concurrent threads.",
            "Resource slices estimate interval overlap, not isolated stage hardware usage.",
            "Existing idle website and HY server are outside this benchmark process tree.",
            "HY loads at startup; CT2 loads in first job. Compare startup plus first run.",
        ],
    }
    with ZipFile(source) as archive:
        report["source_slides"] = len(
            [
                name
                for name in archive.namelist()
                if name.startswith("ppt/slides/slide") and name.endswith(".xml")
            ]
        )
    report["source_units"] = len(document_text(source))
    manifest = ROOT / "data/experiments/openvino-small100/font-manifest.json"
    shutil.copyfile(manifest, state / "font-manifest.json")
    report["seed_font_manifest_sha256"] = sha(manifest)
    if os.name == "nt":
        baseline_module().no_power_throttling()
    stop = threading.Event()
    threads: list[threading.Thread] = []
    server: uvicorn.Server | None = None
    services: Services | None = None
    hy: HyRuntime | None = None
    profiler = ResourceProfiler(interval_s=1.0)

    def save() -> None:
        report["events"] = trace.snapshot()
        (destination / "report.json").write_text(
            json.dumps(report, indent=2, default=str), encoding="utf-8"
        )

    try:
        with contextlib.ExitStack() as patches, profiler:
            trace.install(patches)
            with trace.span("startup"):
                engine: LlmEngineConfig | MtEngineConfig
                if args.model == "hy":
                    hy_args = argparse.Namespace(
                        runtime="hy-vulkan",
                        threads=4,
                        threads_batch=4,
                        concurrency=4,
                        model=ROOT / "data/models/gguf/HY-MT1.5-1.8B-Q8_0.gguf",
                        out=destination / "llama.json",
                    )
                    with trace.span("hy_model_server_load"):
                        hy = HyRuntime(hy_args)
                        hy.start()
                    model_id = request(hy.port, "/v1/models")["data"][0]["id"]
                    report["runtime"] = hy.props
                    engine = LlmEngineConfig(
                        base_url=HttpUrl(f"http://127.0.0.1:{hy.port}/v1"),
                        api_key=SecretStr("local"),
                        model=model_id,
                        protocol="hy-mt",
                        execution_location="server",
                        json_mode=False,
                        max_concurrency=4,
                        batch_size=1,
                        max_retries=0,
                        max_output_tokens=2048,
                        timeout_s=180,
                        deployment_revision="HY-MT1.5-1.8B-Q8_0-vulkan-t4-slots4",
                    )
                else:
                    engine = MtEngineConfig(
                        model_dir=ROOT / "data/models/alirezamsh--small100-ct2-int8",
                        model_family="small100",
                        device="cpu",
                        compute_type="int8",
                        cpu_threads=4,
                        beam_size=4,
                        max_batch_size=32,
                    )
                # model_validate constructs explicit settings without reading project env vars.
                inherited = {
                    name: value
                    for name, value in os.environ.items()  # noqa: TID251 - operational settings
                    if name.startswith("DOCTRANSLATOR_")
                }
                for name in inherited:
                    del os.environ[name]  # noqa: TID251 - isolate this experiment process
                settings = ServerSettings.model_validate(
                    {
                        "data_dir": state,
                        "translators": [
                            ConfiguredTranslator(id="bench", label=args.model, engine=engine)
                        ],
                        "default_translator_id": "bench",
                        "page_previews": "eager",
                        "poll_s": 0.2,
                        "max_attempts": 1,
                        "workers": 1,
                    }
                )
                os.environ.update(inherited)  # noqa: TID251 - restore inherited process settings
                report["renderer"] = str(office_renderer(settings.render_config()))
                with trace.span("database_migrate"):
                    migrate(settings)
                with trace.span("service_font_catalog_startup"):
                    services = build_services(settings)
                report["font_manifest_sha256"] = sha(state / "font-manifest.json")
                user = auth.create_user(services.db, "Lifecycle benchmark", kind="service")
                key = auth.create_key(services.db, user.id, "lifecycle").secret
                with socket.socket() as sock:
                    sock.bind(("127.0.0.1", 0))
                    port = sock.getsockname()[1]
                server = uvicorn.Server(
                    uvicorn.Config(
                        create_app(services),
                        host="127.0.0.1",
                        port=port,
                        log_level="warning",
                        access_log=False,
                    )
                )
                worker = Worker.from_catalog(
                    settings,
                    services.db,
                    services.store,
                    services.queue(),
                    cast(EngineCatalog, services.catalog),
                )
                renderer = PageRenderer(settings, services.db, services.store)
                for name, target in [
                    ("http", server.run),
                    ("worker", lambda: worker.run(stop)),
                    ("pages", lambda: renderer.run(stop)),
                ]:
                    thread = threading.Thread(name=name, target=target, daemon=True)
                    thread.start()
                    threads.append(thread)
                deadline = time.monotonic() + 60
                while not server.started:
                    if time.monotonic() > deadline:
                        raise TimeoutError("HTTP startup timed out")
                    time.sleep(0.1)
            save()
            with httpx.Client(
                base_url=f"http://127.0.0.1:{port}",
                trust_env=False,
                headers={"Authorization": f"Bearer {key}"},
                timeout=180,
            ) as client:
                for rep in range(1, args.reps + 1):
                    trace.rep = rep
                    run: dict[str, Any] = {
                        "rep": rep,
                        "first_rep_no_inference_warmup": rep == 1,
                        "started": time.perf_counter(),
                    }
                    report["runs"].append(run)
                    print(f"lifecycle {args.model}/{args.fit_mode} repetition {rep}", flush=True)
                    with trace.span("upload_and_queue"):
                        with source.open("rb") as stream:
                            response = client.post(
                                "/v1/jobs",
                                files={
                                    "file": (
                                        source.name,
                                        stream,
                                        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                                    )
                                },
                                data={
                                    "submission_id": str(uuid.uuid4()),
                                    "options": json.dumps(
                                        {
                                            "source": "zh",
                                            "target": "en",
                                            "translator_id": "bench",
                                            "retention": "temporary",
                                            "fit": {"mode": args.fit_mode},
                                        }
                                    ),
                                },
                            )
                        response.raise_for_status()
                        job = response.json()
                    run["job_id"] = job["id"]
                    deadline = time.monotonic() + args.timeout
                    with trace.span("wait_for_publication"):
                        while job["status"] in ("queued", "running"):
                            if time.monotonic() > deadline:
                                raise TimeoutError("Document publication timed out")
                            time.sleep(0.2)
                            response = client.get(f"/v1/jobs/{job['id']}")
                            response.raise_for_status()
                            job = response.json()
                    run["job"] = job
                    run["publication_latency_s"] = time.perf_counter() - run["started"]
                    if job["status"] != "succeeded":
                        raise RuntimeError(f"Translation failed: {job.get('error_code')}")
                    with trace.span("output_download"):
                        response = client.get(f"/v1/jobs/{job['id']}/file")
                        response.raise_for_status()
                        output = destination / f"rep-{rep}.en.pptx"
                        output.write_bytes(response.content)
                        run["output_sha256"] = hashlib.sha256(response.content).hexdigest()
                        if run["output_sha256"] != response.headers.get("x-content-sha256"):
                            raise RuntimeError("Downloaded output hash mismatch")
                    run["download_latency_s"] = time.perf_counter() - run["started"]
                    response = client.get(f"/v1/jobs/{job['id']}/preview")
                    response.raise_for_status()
                    run["pages_status_at_download"] = response.json()["pages_status"]
                    response = client.get(f"/v1/jobs/{job['id']}/fit-report")
                    response.raise_for_status()
                    run["fit_report"] = response.json()
                    save()
                    with trace.span("wait_for_pages"):
                        while True:
                            response = client.get(f"/v1/jobs/{job['id']}/preview")
                            response.raise_for_status()
                            preview = response.json()
                            if preview["pages_status"] not in ("queued", "running"):
                                break
                            if time.monotonic() > deadline:
                                raise TimeoutError("Page rendering timed out")
                            time.sleep(0.3)
                    run["preview"] = preview
                    run["pages_ready_latency_s"] = time.perf_counter() - run["started"]
                    if preview["pages_status"] != "ready" or preview.get("truncated"):
                        raise RuntimeError("All-pages preview unavailable or truncated")
                    if [page["number"] for page in preview["pages"]] != list(
                        range(1, report["source_slides"] + 1)
                    ):
                        raise RuntimeError("Preview page numbering/count mismatch")
                    downloads: list[dict[str, Any]] = []
                    run["page_downloads"] = downloads
                    page_dir = destination / f"rep-{rep}-pages"
                    page_dir.mkdir()
                    with trace.span("all_pages_download"):
                        for page in preview["pages"]:
                            for side in ("source", "target"):
                                name = page.get(side)
                                if name:
                                    response = client.get(f"/v1/jobs/{job['id']}/preview/{name}")
                                    response.raise_for_status()
                                    if (
                                        response.headers.get("content-type", "").split(";")[0]
                                        != "image/jpeg"
                                    ):
                                        raise RuntimeError("Preview image content type mismatch")
                                    image = cast(Any, pymupdf).Pixmap(response.content)
                                    if [image.width, image.height] != page[f"{side}_size"]:
                                        raise RuntimeError("Preview image dimensions mismatch")
                                    (page_dir / name).write_bytes(response.content)
                                    downloads.append(
                                        {
                                            "name": name,
                                            "bytes": len(response.content),
                                            "sha256": hashlib.sha256(response.content).hexdigest(),
                                        }
                                    )
                    if len(run["page_downloads"]) != report["source_slides"] * 2:
                        raise RuntimeError("Unexpected source/target page count")
                    run["all_pages_download_latency_s"] = time.perf_counter() - run["started"]
                    save()
            report["status"] = "ok"
    except Exception as exc:
        report["status"] = "error"
        report["error_type"] = type(exc).__name__
        # HTTP exception strings can expose request URLs, but never include secrets here.
        report["error"] = (
            str(exc) if not isinstance(exc, httpx.HTTPError) else "HTTP request failed"
        )
        if isinstance(exc, httpx.HTTPStatusError):
            report["http_status"] = exc.response.status_code
    finally:
        stop.set()
        if server:
            server.should_exit = True
        for thread in threads:
            thread.join(timeout=30)
        if services:
            services.close()
        if hy:
            hy.close()
        trace.finish()
        trace.resources(profiler._start, profiler.samples)  # pyright: ignore[reportPrivateUsage]
        report["profile"] = profiler.result()
        report["input_unchanged"] = sha(source) == report["input_sha256"]
        report["finished_utc"] = datetime.now(UTC).isoformat()
        save()
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
