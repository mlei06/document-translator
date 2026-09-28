from collections.abc import Callable
from pathlib import Path

import pytest
from typer.testing import CliRunner

from doctranslator_eval.cli import USER_ERROR_EXIT_CODE, app
from doctranslator_eval.runs import RunDir

type ScoredRunFactory = Callable[..., RunDir]

cli = CliRunner()


def test_compare_exit_code_reflects_regression(scored_run: ScoredRunFactory) -> None:
    good = scored_run("a", {"zh-en": {str(i): 0.8 + (i % 3) / 100 for i in range(100)}})
    bad = scored_run("b", {"zh-en": {str(i): 0.7 + (i % 3) / 100 for i in range(100)}})

    same = cli.invoke(app, ["compare", str(good.path), str(good.path)])
    assert same.exit_code == 0, same.output
    assert "no regression" in same.output

    worse = cli.invoke(app, ["compare", str(good.path), str(bad.path)])
    assert worse.exit_code == 1, worse.output
    assert "REGRESSION" in worse.output


def test_baseline_set_writes_file(scored_run: ScoredRunFactory, tmp_path: Path) -> None:
    run = scored_run("r", {"zh-en": {"0": 0.8}})
    result = cli.invoke(
        app, ["baseline", "set", str(run.path), "--baselines-dir", str(tmp_path / "b")]
    )
    assert result.exit_code == 0, result.output
    assert (tmp_path / "b" / "mt.json").is_file()


def test_user_errors_are_one_line(scored_run: ScoredRunFactory, tmp_path: Path) -> None:
    run = scored_run("r", {"zh-en": {"0": 0.8}}, git_dirty=True)
    result = cli.invoke(
        app, ["baseline", "set", str(run.path), "--baselines-dir", str(tmp_path / "b")]
    )
    assert result.exit_code == USER_ERROR_EXIT_CODE
    assert "error:" in result.output
    assert "Traceback" not in result.output


@pytest.mark.parametrize(
    "args",
    [
        ["run", "--mode", "mt"],
        ["run", "--mode", "llm", "--directions", "zh-fr"],
    ],
)
def test_run_rejects_bad_arguments(args: list[str]) -> None:
    result = cli.invoke(app, args)
    assert result.exit_code == USER_ERROR_EXIT_CODE, result.output
