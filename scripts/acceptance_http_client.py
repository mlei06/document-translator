# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx>=0.27", "truststore>=0.9"]
# ///
"""Independent REST client for release evidence: uses only HTTP, no project code.

    uv run scripts/acceptance_http_client.py --server URL --to en --mode mt [--force] \
        --out DIR FILE [FILE ...]

The API key is read from DOCTRANSLATOR_API_KEY. For each file: submit a standalone job,
poll until it finishes, download the output and fit report, check the SHA-256 the service
declares, and confirm the input file is unchanged. Prints one JSON line per file.
"""

import argparse
import hashlib
import json
import os
import ssl
import sys
import time
import uuid
from pathlib import Path

import httpx
import truststore


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", required=True)
    parser.add_argument("--to", required=True)
    parser.add_argument("--mode", required=True)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("files", type=Path, nargs="+")
    args = parser.parse_args()
    key = os.environ.get("DOCTRANSLATOR_API_KEY")
    if not key:
        print("DOCTRANSLATOR_API_KEY is not set", file=sys.stderr)
        return 2
    client = httpx.Client(
        base_url=args.server.rstrip("/") + "/v1",
        headers={"Authorization": f"Bearer {key}"},
        timeout=600,
        verify=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT),
    )
    args.out.mkdir(parents=True, exist_ok=True)
    options = json.dumps({"target": args.to, "mode": args.mode, "force_retranslate": args.force})
    failures = 0
    for path in args.files:
        before = sha256(path.read_bytes())
        started = time.monotonic()
        with path.open("rb") as handle:
            response = client.post(
                "/jobs",
                files={"file": (path.name, handle)},
                data={"options": options, "submission_id": str(uuid.uuid4())},
            )
        if response.status_code not in (201, 202):
            print(
                json.dumps(
                    {"file": path.name, "http": response.status_code, "error": response.json()}
                )
            )
            failures += 1
            continue
        job = response.json()
        while job["status"] in ("queued", "running"):
            time.sleep(1)
            job = client.get(f"/jobs/{job['id']}").json()
        record: dict[str, object] = {
            "file": path.name,
            "status": job["status"],
            "cache_hit": job["cache_hit"],
            "fit_status": job["fit_status"],
            "source_resolved": job["source_resolved"],
            "error": job["error_code"],
            "seconds": round(time.monotonic() - started, 1),
        }
        if job["status"] == "succeeded":
            document = job["document_id"]
            output = client.get(f"/documents/{document}/versions/0/file")
            report = client.get(f"/documents/{document}/versions/0/fit-report")
            name = f"{path.stem}.{args.to}.{document[:8]}{path.suffix}"
            (args.out / name).write_bytes(output.content)
            (args.out / f"{name}.report.json").write_bytes(report.content)
            record |= {
                "output": name,
                "bytes": len(output.content),
                "sha256_ok": sha256(output.content) == output.headers["x-content-sha256"],
                "report_fit": report.json()["fit_report"]["status"],
            }
        else:
            failures += 1
        record["input_unchanged"] = sha256(path.read_bytes()) == before
        print(json.dumps(record))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
