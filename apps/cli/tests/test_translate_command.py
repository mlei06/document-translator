"""``doctranslator translate`` end to end: a subprocess against a local fake LLM server."""

import json
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from support.fake_llm import FakeLlm, fake_llm_server
from support.fakes import copy_fixture

CLI = [sys.executable, "-c", "from doctranslator_cli.main import main; main()"]


@pytest.fixture
def llm() -> Iterator[FakeLlm]:
    with fake_llm_server() as server:
        yield server


def run(args: list[str], cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    clean = {k: v for k, v in os.environ.items() if not k.startswith("DOCTRANSLATOR_")}
    return subprocess.run(  # noqa: S603 - the test's own interpreter and arguments
        [*CLI, *args],
        cwd=cwd,
        env=clean | env | {"PYTHONIOENCODING": "utf-8"},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )


def llm_env(llm: FakeLlm) -> dict[str, str]:
    return {
        "DOCTRANSLATOR_LLM_BASE_URL": llm.base_url,
        "DOCTRANSLATOR_LLM_API_KEY": "test-key",
        "DOCTRANSLATOR_LLM_MODEL": "fake-model",
        "DOCTRANSLATOR_MODE": "llm",
    }


@pytest.mark.parametrize(
    "fixture", ["pptx/deck.pptx", "docx/report.docx", "xlsx/features-shared.xlsx"]
)
def test_translates_each_office_format(tmp_path: Path, llm: FakeLlm, fixture: str) -> None:
    source = copy_fixture(fixture, tmp_path)
    result = run(["translate", source.name, "--to", "en", "--from", "zh"], tmp_path, llm_env(llm))
    assert result.returncode == 0, result.stderr
    output = tmp_path / f"{source.stem}.en{source.suffix}"
    assert result.stdout.strip() == output.name
    assert output.is_file()
    report = json.loads((tmp_path / f"{output.name}.report.json").read_text(encoding="utf-8"))
    assert report["format"] == source.suffix[1:]
    assert report["counts"]["unique_inputs"] > 0
    assert llm.requests
    assert "test-key" not in result.stderr + result.stdout


def test_txt_with_json_output_and_auto_detection(tmp_path: Path, llm: FakeLlm) -> None:
    source = tmp_path / "notes.txt"
    source.write_text("这是第一段足够长的中文文字。\n第二行。\n", encoding="utf-8")
    result = run(
        ["translate", "notes.txt", "--to", "ja", "--json", "-o", "out.txt"], tmp_path, llm_env(llm)
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["source_resolved"] == "zh"
    assert payload["target"] == "ja"
    assert payload["fit_report"]["status"] == "not_applicable"
    assert (tmp_path / "out.txt").read_text(encoding="utf-8").startswith("JA:")


def test_usage_and_configuration_errors_exit_2(tmp_path: Path, llm: FakeLlm) -> None:
    source = copy_fixture("pptx/deck.pptx", tmp_path)
    missing = run(["translate", source.name, "--to", "en", "--mode", "llm"], tmp_path, {})
    assert missing.returncode == 2
    assert "DOCTRANSLATOR_LLM_BASE_URL" in missing.stderr
    same = run(["translate", source.name, "--to", "zh", "--from", "zh"], tmp_path, llm_env(llm))
    assert same.returncode == 2
    (tmp_path / "data.csv").write_text("a,b", encoding="utf-8")
    unsupported = run(["translate", "data.csv", "--to", "en"], tmp_path, llm_env(llm))
    assert unsupported.returncode == 2
    assert "unsupported file extension" in unsupported.stderr
    assert llm.requests == []


def test_existing_output_exits_4_and_is_untouched(tmp_path: Path, llm: FakeLlm) -> None:
    source = copy_fixture("pptx/deck.pptx", tmp_path)
    (tmp_path / "deck.en.pptx").write_bytes(b"keep me")
    result = run(["translate", source.name, "--to", "en", "--from", "zh"], tmp_path, llm_env(llm))
    assert result.returncode == 4
    assert (tmp_path / "deck.en.pptx").read_bytes() == b"keep me"


def test_engine_rejection_exits_3_without_output(tmp_path: Path, llm: FakeLlm) -> None:
    llm.status = 401
    source = copy_fixture("docx/report.docx", tmp_path)
    result = run(["translate", source.name, "--to", "en", "--from", "zh"], tmp_path, llm_env(llm))
    assert result.returncode == 3
    assert "rejected the credentials" in result.stderr
    assert sorted(p.name for p in tmp_path.iterdir()) == ["report.docx"]


def test_help_needs_no_settings_or_models(tmp_path: Path) -> None:
    result = run(["translate", "--help"], tmp_path, {"DOCTRANSLATOR_MT_MODEL_DIR": "missing"})
    assert result.returncode == 0
    assert "--to" in result.stdout
