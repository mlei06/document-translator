"""Real HTTP/worker HY-MT acceptance against an already running local llama-server.

Run with the repository Python environment. Creates an isolated service run directory,
never changes website settings, and stops only the service processes it starts.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import psutil
from profiling import ResourceProfiler

ROOT = Path(__file__).resolve().parents[3]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--llm-port", type=int, required=True)
    parser.add_argument("--llm-pid", type=int, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--timeout", type=float, default=300)
    args = parser.parse_args()
    if not 1 <= args.llm_port <= 65535 or args.timeout <= 0 or not args.revision.strip():
        parser.error("valid port, positive timeout and nonempty revision are required")
    external = psutil.Process(args.llm_pid)
    if "llama-server" not in external.name().lower():
        parser.error("--llm-pid must identify the existing llama-server")
    run_dir = ROOT / "data/experiments/laptop-mt/service" / uuid.uuid4().hex[:12]
    run_dir.mkdir(parents=True)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    translator = {
        "id": "hy-mt-local",
        "label": "Local HY-MT acceptance",
        "engine": {
            "mode": "llm",
            "protocol": "hy-mt",
            "execution_location": "server",
            "base_url": f"http://127.0.0.1:{args.llm_port}/v1/",
            "api_key": "local",
            "model": args.model,
            "deployment_revision": args.revision,
            "max_concurrency": 1,
            "max_output_tokens": 2048,
        },
    }
    values = {
        "DATA_DIR": (run_dir / "state").as_posix(),
        "SERVER_HOST": "127.0.0.1",
        "SERVER_PORT": str(port),
        "TRANSLATORS": json.dumps([translator]),
        "DEFAULT_TRANSLATOR_ID": "hy-mt-local",
        "PAGE_PREVIEWS": "off",
        "POLL_S": "0.25",
        "WORKERS": "1",
    }
    env_path = run_dir / "service.env"
    env_path.write_text(
        "\n".join(f"DOCTRANSLATOR_{key}={json.dumps(value)}" for key, value in values.items())
        + "\n",
        encoding="utf-8",
    )
    # Inherited project settings must not override this isolated acceptance service.
    # This operational client owns application configuration, not core behavior.
    env = {
        key: value
        for key, value in os.environ.items()  # noqa: TID251 - standalone operational script
        if not key.startswith("DOCTRANSLATOR_")
    }
    command = [sys.executable, "-m", "doctranslator_server.cli", "--env-file", str(env_path)]
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

    def admin(*arguments: str) -> str:
        result = subprocess.run(  # noqa: S603 - fixed local module, no shell
            [*command, *arguments],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=args.timeout,
            creationflags=flags,
        )
        if result.returncode:
            raise RuntimeError(f"service administration failed: {arguments[0]}")
        return result.stdout.strip()

    record: dict[str, Any] = {
        "started_utc": datetime.now(UTC).isoformat(),
        "model": args.model,
        "deployment_revision": args.revision,
        "status": "error",
    }
    process: subprocess.Popen[bytes] | None = None
    profile: ResourceProfiler | None = None
    stage = "migrate"
    try:
        admin("migrate")
        stage = "provision_user_and_key"
        user_id = admin("users", "create", "HY-MT acceptance", "--kind", "service")
        key = admin("keys", "create", user_id, "--label", "isolated-acceptance")
        stage = "start_service"
        with (run_dir / "service.log").open("wb") as log:
            process = subprocess.Popen(  # noqa: S603 - fixed local module, no shell
                [*command, "serve", "--workers", "1", "--no-retention"],
                cwd=ROOT,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=flags,
            )
            with httpx.Client(
                base_url=f"http://127.0.0.1:{port}",
                trust_env=False,
                headers={"Authorization": f"Bearer {key}"},
                timeout=30,
            ) as client:
                deadline = time.monotonic() + args.timeout
                while True:
                    if process.poll() is not None:
                        raise RuntimeError("acceptance service exited before readiness")
                    try:
                        ready = client.get("/v1/health").is_success
                    except httpx.TransportError:
                        ready = False
                    if ready:
                        break
                    if time.monotonic() >= deadline:
                        raise TimeoutError("acceptance service startup timed out")
                    time.sleep(0.25)
                stage = "check_capabilities"
                capabilities = client.get("/v1/capabilities")
                capabilities.raise_for_status()
                catalog = capabilities.json()
                entries = catalog["translators"]
                selected = next(item for item in entries if item["id"] == "hy-mt-local")
                if selected["location"] != "server":
                    raise AssertionError("configured local translator location was not exposed")
                record["translator"] = selected
                source = run_dir / "source.txt"
                original = "本季度营业收入增长了百分之十二。团队将继续提高产品质量。\n".encode()
                source.write_bytes(original)
                profile = ResourceProfiler(pids=[process.pid, args.llm_pid])
                began = time.monotonic()
                with profile:
                    stage = "submit_job"
                    response = client.post(
                        "/v1/jobs",
                        files={"file": (source.name, original, "text/plain")},
                        data={
                            "submission_id": str(uuid.uuid4()),
                            "options": json.dumps(
                                {
                                    "source": "zh",
                                    "target": "en",
                                    "translator_id": "hy-mt-local",
                                    "retention": "temporary",
                                }
                            ),
                        },
                    )
                    response.raise_for_status()
                    job = response.json()
                    stage = "poll_job"
                    deadline = time.monotonic() + args.timeout
                    while job["status"] in ("queued", "running"):
                        if time.monotonic() >= deadline:
                            raise TimeoutError("acceptance job timed out")
                        time.sleep(0.25)
                        response = client.get(f"/v1/jobs/{job['id']}")
                        response.raise_for_status()
                        job = response.json()
                    if job["status"] != "succeeded":
                        record["job_status"] = job["status"]
                        record["job_error_code"] = job.get("error_code")
                        raise RuntimeError(f"acceptance job failed: {job.get('error_code')}")
                    if job["translator_id"] != "hy-mt-local":
                        raise AssertionError("job did not retain the selected translator")
                    stage = "download_output"
                    output = client.get(f"/v1/jobs/{job['id']}/file")
                    output.raise_for_status()
                stage = "verify_output"
                text = output.content.decode("utf-8-sig")
                checks = {
                    "nonempty": bool(text.strip()),
                    "english_letters": bool(re.search(r"[A-Za-z]{3}", text)),
                    "no_chinese_text": not bool(re.search(r"[\u4e00-\u9fff]", text)),
                    "input_unchanged": source.read_bytes() == original,
                    "download_hash": hashlib.sha256(output.content).hexdigest()
                    == output.headers.get("x-content-sha256"),
                }
                (run_dir / "translated.en.txt").write_bytes(output.content)
                record.update(
                    {
                        "job_id": job["id"],
                        "wall_s": time.monotonic() - began,
                        "checks": checks,
                        "status": "ok" if all(checks.values()) else "error",
                    }
                )
    except Exception as exc:
        # Do not serialize request headers, admin output, or credentials.
        record["error_type"] = type(exc).__name__
        record["error_stage"] = stage
        if isinstance(exc, httpx.HTTPStatusError):
            record["http_status"] = exc.response.status_code
        elif isinstance(exc, (RuntimeError, TimeoutError, AssertionError)):
            # These exceptions are raised above with fixed, secret-free messages.
            record["error"] = str(exc)
    finally:
        if profile is not None:
            record["profile"] = profile.result()
        if process is not None and process.poll() is None:
            root = psutil.Process(process.pid)
            owned = root.children(recursive=True)
            root.terminate()
            for child in owned:
                with contextlib.suppress(psutil.NoSuchProcess):
                    child.terminate()
            _, alive = psutil.wait_procs([root, *owned], timeout=10)
            for child in alive:
                child.kill()
            psutil.wait_procs(alive, timeout=5)
        record["finished_utc"] = datetime.now(UTC).isoformat()
        report = run_dir / "acceptance.json"
        report.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"status": record["status"], "report": str(report)}))
    return 0 if record["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
