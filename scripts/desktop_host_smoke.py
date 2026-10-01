"""Exercise the actual desktop host without a browser or website dependency.

Run from repository root. Uses existing approved inference configuration; prints
only local protocol/status/result evidence, never upstream configuration/secrets.
"""

import argparse
import json
import secrets
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

import httpx


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("runtime", nargs="?")
    parser.add_argument("--install-offline", action="store_true")
    parser.add_argument("--long-path", action="store_true")
    args = parser.parse_args()
    token = secrets.token_hex(32)
    with tempfile.TemporaryDirectory(prefix="Lenny desktop 中文 ") as temporary:
        root = Path(temporary)
        if args.long_path:
            root = root.joinpath(*(f"nested-{index}-" + "a" * 48 for index in range(5)))
            root.mkdir(parents=True)
        source = root / "source report.txt"
        source.write_text("请保存文件。", encoding="utf-8")
        errors = (root / "runtime.stderr").open("w", encoding="utf-8")
        command = (
            [args.runtime, "desktop"]
            if args.runtime
            else [sys.executable, "-m", "doctranslator_server.cli", "desktop"]
        )
        process = subprocess.Popen(  # noqa: S603 - developer-supplied runtime under test
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=errors,
            text=True,
            encoding="utf-8",
        )
        try:
            if process.stdin is None or process.stdout is None:
                raise RuntimeError("Missing runtime pipes")
            process.stdin.write(json.dumps({"protocol": 1, "token": token}) + "\n")
            process.stdin.flush()
            line = process.stdout.readline(4097)
            if not line:
                raise RuntimeError("Desktop failed before readiness; inspect local stderr")
            ready = json.loads(line)
            with httpx.Client(base_url=ready["base_url"], timeout=120, trust_env=False) as client:
                if client.get("/v1/health").status_code != 401:
                    raise RuntimeError("Unauthenticated local health was not denied")
                client.headers["Authorization"] = "Bearer " + token
                client.get("/v1/health").raise_for_status()
                denied = client.get("/v1/health", headers={"Origin": "https://unrelated.invalid"})
                if denied.status_code != 403:
                    raise RuntimeError("Unrelated browser origin was not denied")
                response = client.post(
                    "/v1/desktop/submit",
                    json={
                        "path": str(source),
                        "destination": str(source.parent / "exports"),
                        "target": "en",
                        "submission_id": str(uuid.uuid4()),
                    },
                )
                response.raise_for_status()
                job = response.json()
                deadline = time.monotonic() + 300
                while job["status"] in {"queued", "running"} and time.monotonic() < deadline:
                    time.sleep(1)
                    status = client.get(f"/v1/jobs/{job['id']}")
                    status.raise_for_status()
                    job = status.json()
                if job["status"] != "succeeded":
                    raise RuntimeError(f"Desktop translation ended with {job['status']}")
                exported = client.post(f"/v1/desktop/jobs/{job['id']}/export", json={})
                exported.raise_for_status()
                output = Path(exported.json()["path"])
                again = client.post(f"/v1/desktop/jobs/{job['id']}/export", json={})
                again.raise_for_status()
                if again.json()["path"] != str(output):
                    raise RuntimeError("Export replay created a second file")
                if source.read_text(encoding="utf-8") != "请保存文件。":
                    raise RuntimeError("Source changed")
                offline_ready = False
                if args.install_offline:
                    # Completed, undismissed activity must not block capability changes.
                    client.post("/v1/desktop/offline/install").raise_for_status()
                    deadline = time.monotonic() + 600
                    capability = {"state": "Installing"}
                    while time.monotonic() < deadline:
                        response = client.get("/v1/desktop/offline")
                        response.raise_for_status()
                        capability = response.json()
                        if capability["state"] != "Installing":
                            break
                        time.sleep(1)
                    if capability["state"] != "Ready":
                        raise RuntimeError(f"Offline setup ended with {capability['state']}")
                    offline_ready = True
                print(
                    json.dumps(
                        {
                            "protocol": ready["protocol"],
                            "status": job["status"],
                            "mode": job.get("mode"),
                            "text": output.read_text(encoding="utf-8"),
                            "source_unchanged": True,
                            "source_path_length": len(str(source)),
                            "export_replay_same_path": True,
                            "offline_ready": offline_ready,
                        }
                    )
                )
                client.post("/v1/desktop/shutdown").raise_for_status()
            process.wait(timeout=30)
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=15)
            errors.close()


if __name__ == "__main__":
    main()
