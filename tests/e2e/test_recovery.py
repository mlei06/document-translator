"""Crash recovery across processes (R08): a service killed mid-translation loses nothing."""

import time
import uuid
from pathlib import Path
from typing import Any

import httpx
from support.service_process import provision, running_service

TXT = "这是一个用于测试的中文段落，内容足够长以便识别语言。\n".encode()


def _job(url: str, headers: dict[str, str], job_id: str) -> dict[str, Any]:
    return httpx.get(f"{url}/v1/jobs/{job_id}", headers=headers).json()


def test_killed_worker_job_is_recovered_by_a_restarted_service(tmp_path: Path) -> None:
    accounts = provision(tmp_path)
    headers = {"Authorization": f"Bearer {accounts.alice}"}
    lease = ("--lease", "3", "--heartbeat", "1")
    with running_service(accounts.data_dir, *lease, "--slow", "8") as url:
        response = httpx.post(
            url + "/v1/jobs",
            headers=headers,
            files={"file": ("notes.txt", TXT)},
            data={"options": '{"target": "en", "mode": "mt"}', "submission_id": str(uuid.uuid4())},
        )
        job_id = response.json()["id"]
        for _ in range(100):
            if _job(url, headers, job_id)["status"] == "running":
                break
            time.sleep(0.1)
        assert _job(url, headers, job_id)["status"] == "running"
    # The process was killed mid-translation. A new process on the same data recovers the job
    # once the dead attempt's lease expires, and translates it again.
    with running_service(accounts.data_dir, *lease) as url:
        deadline = time.monotonic() + 60
        job = _job(url, headers, job_id)
        while job["status"] not in ("succeeded", "failed", "cancelled"):
            assert time.monotonic() < deadline, job
            time.sleep(0.5)
            job = _job(url, headers, job_id)
        assert job["status"] == "succeeded"
        assert job["attempts"] == 2
        documents = httpx.get(f"{url}/v1/documents", headers=headers).json()["items"]
        assert len(documents) == 1
