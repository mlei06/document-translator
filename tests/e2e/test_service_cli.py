"""Service CLI end to end: ``doctranslator`` subprocesses against the real HTTP service running
in another process with the deterministic fake engine (R03, R04, R07, R10, R13 behaviours)."""

import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import pytest
from support.fakes import FIXTURES
from support.pdf import write_mixed
from support.service_process import provision, running_service

CLI = [sys.executable, "-c", "from doctranslator_cli.main import main; main()"]
TXT = "这是一个用于测试的中文段落，内容足够长以便识别语言。\n".encode()


@dataclass
class Service:
    url: str
    alice: str
    bob: str


@contextmanager
def started(tmp_path: Path, *options: str) -> Generator[Service]:
    accounts = provision(tmp_path)
    with running_service(accounts.data_dir, *options) as url:
        yield Service(url, accounts.alice, accounts.bob)


@pytest.fixture
def service(tmp_path: Path) -> Iterator[Service]:
    with started(tmp_path) as service:
        yield service


def run(
    args: list[str], cwd: Path, service: Service, key: str | None = None
) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("DOCTRANSLATOR_")}
    env |= {
        "DOCTRANSLATOR_SERVER_URL": service.url,
        "DOCTRANSLATOR_API_KEY": key or service.alice,
        "DOCTRANSLATOR_MODE": "mt",
        "PYTHONIOENCODING": "utf-8",
    }
    return subprocess.run(  # noqa: S603 - the test's own interpreter
        [*CLI, *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
        check=False,
    )


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def lines(output: str) -> list[dict[str, object]]:
    return [json.loads(line) for line in output.splitlines() if line.strip()]


def test_mixed_batch_with_failures_downloads_every_success(
    tmp_path: Path, service: Service
) -> None:
    inputs = tmp_path / "in"
    (inputs / "a").mkdir(parents=True)
    (inputs / "b").mkdir()
    (inputs / "a" / "notes.txt").write_bytes(TXT)
    (inputs / "b" / "notes.txt").write_bytes(TXT)  # same bytes and basename, other folder
    for fixture in ("pptx/deck.pptx", "docx/report.docx", "xlsx/features-shared.xlsx"):
        (inputs / Path(fixture).name).write_bytes((FIXTURES / fixture).read_bytes())
    write_mixed(inputs / "mixed.pdf")
    (inputs / "photo.png").write_bytes(b"\x89PNG not a document")
    (inputs / "broken.docx").write_bytes(b"PK\x03\x04broken")
    files = sorted(p for p in inputs.rglob("*") if p.is_file())
    before = {p: digest(p) for p in files}

    result = run(
        ["submit", *map(str, files), "--to", "en", "--download-dir", "out", "--json"],
        tmp_path,
        service,
    )
    assert result.returncode == 1, result.stderr  # rejected items make the run exit 1
    records = lines(result.stdout)
    assert len(records) == len(files)
    by_name: dict[str, list[dict[str, object]]] = {}
    for record in records:
        by_name.setdefault(str(record["name"]), []).append(record)
    assert [r["status"] for r in by_name["notes.txt"]] == ["succeeded", "succeeded"]
    for name in ("deck.pptx", "report.docx", "features-shared.xlsx", "mixed.pdf"):
        assert by_name[name][0]["status"] == "succeeded", by_name[name]
    assert by_name["photo.png"][0]["error"] == "unsupported_document"
    assert by_name["broken.docx"][0]["status"] == "rejected"
    outputs = [Path(str(r["output"])) for r in records if r["output"]]
    assert len(outputs) == 6 and len(set(outputs)) == 6  # distinct destinations
    for output in outputs:
        assert output.is_file()
        assert (output.parent / (output.name + ".report.json")).is_file()
    assert not list((tmp_path / "out").glob(".*.part"))
    assert {p: digest(p) for p in files} == before  # inputs unchanged
    assert "rejected 2" in result.stderr and "succeeded 6" in result.stderr


def test_resume_reuses_identities_and_creates_no_duplicates(
    tmp_path: Path, service: Service
) -> None:
    for index in range(3):
        (tmp_path / f"f{index}.txt").write_bytes(TXT + str(index).encode())
    args = ["submit", "f0.txt", "f1.txt", "f2.txt", "--to", "en", "--resume-state", "run.jsonl"]
    first = run(args, tmp_path, service)
    assert first.returncode == 0, first.stderr
    batch = first.stdout.strip()
    second = run(args, tmp_path, service)  # e.g. after losing the first run's responses
    assert second.returncode == 0, second.stderr
    assert second.stdout.strip() == batch
    jobs = run(["jobs", "list", "--json"], tmp_path, service)
    assert len(lines(jobs.stdout)) == 3
    (tmp_path / "f1.txt").write_bytes(b"changed")
    changed = run(args, tmp_path, service)
    assert changed.returncode == 1
    assert "changed since the previous run" in changed.stderr


def test_a_long_manifest_drains_through_admission_backpressure(tmp_path: Path) -> None:
    with started(tmp_path, "--max-per-user", "2", "--slow", "0.2") as service:
        manifest = tmp_path / "files.jsonl"
        with manifest.open("w", encoding="utf-8") as handle:
            for index in range(8):
                (tmp_path / f"doc{index}.txt").write_bytes(TXT + str(index).encode())
                target = "ja" if index == 3 else None
                record = {"path": f"doc{index}.txt"} | ({"target": target} if target else {})
                handle.write(json.dumps(record) + "\n")
        result = run(
            ["submit", "--manifest", str(manifest), "--to", "en", "--wait", "--json"],
            tmp_path,
            service,
        )
        assert result.returncode == 0, result.stderr
        records = lines(result.stdout)
        assert len(records) == 8
        assert all(r["status"] == "succeeded" for r in records)
        assert "queue_full" in result.stderr  # the CLI backed off and retried


def test_download_never_overwrites_without_consent(tmp_path: Path, service: Service) -> None:
    (tmp_path / "a.txt").write_bytes(TXT)
    submitted = run(["submit", "a.txt", "--to", "en", "--wait", "--json"], tmp_path, service)
    document = str(lines(submitted.stdout)[0]["document_id"])
    first = run(["download", "--document", document, "--output-dir", "out"], tmp_path, service)
    assert first.returncode == 0, first.stderr
    output = Path(first.stdout.strip())
    output.write_text("my edits", encoding="utf-8")
    again = run(["download", "--document", document, "--output-dir", "out"], tmp_path, service)
    assert again.returncode == 1
    assert output.read_text(encoding="utf-8") == "my edits"
    forced = run(
        ["download", "--document", document, "--output-dir", "out", "--overwrite"],
        tmp_path,
        service,
    )
    assert forced.returncode == 0
    assert output.read_text(encoding="utf-8").startswith("EN:")


def test_authentication_and_ownership(tmp_path: Path, service: Service) -> None:
    whoami = run(["whoami"], tmp_path, service)
    assert whoami.returncode == 0 and "Alice" in whoami.stdout
    bad = run(["whoami"], tmp_path, service, key="dt_aaaaaaaaaaaa_" + "A" * 43)
    assert bad.returncode == 2 and "rejected the API key" in bad.stderr
    assert "dt_aaaa" not in bad.stderr + bad.stdout
    (tmp_path / "a.txt").write_bytes(TXT)
    batch = run(["submit", "a.txt", "--to", "en"], tmp_path, service).stdout.strip()
    other = run(["batches", "status", batch], tmp_path, service, key=service.bob)
    assert other.returncode == 2 and "not found" in other.stderr
    mine = run(["batches", "status", batch], tmp_path, service)
    assert mine.returncode == 0 and "a.txt" in mine.stdout
