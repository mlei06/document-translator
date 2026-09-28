from collections.abc import Callable
from pathlib import Path

import pytest

from doctranslator_eval.baselines import BaselineError, load_baseline, set_baseline
from doctranslator_eval.compare import Verdict, compare, load_score_set
from doctranslator_eval.datasets import Direction
from doctranslator_eval.runs import RunDir, RunStatus

type ScoredRunFactory = Callable[..., RunDir]

SEGMENTS = {"zh-en": {"0": 0.81, "1": 0.79, "2": 0.9}, "en-zh": {"0": 0.7, "1": 0.72}}


def test_baseline_contains_scores_but_no_text(scored_run: ScoredRunFactory, tmp_path: Path) -> None:
    run = scored_run("20260927T000000Z-mt-small100", SEGMENTS)
    path = set_baseline(run, tmp_path / "baselines")
    assert path.name == "mt.json"

    content = path.read_text(encoding="utf-8")
    for direction in SEGMENTS:
        for row in run.read_translations(Direction.parse(direction)):
            for text in (row.source, row.reference, row.hypothesis):
                assert text not in content
    baseline = load_baseline(path)
    assert baseline.run_id == run.run_id
    assert baseline.segment_comet == SEGMENTS
    assert baseline.directions["zh-en"].n == 3


def test_baseline_compared_with_itself_shows_no_difference(
    scored_run: ScoredRunFactory, tmp_path: Path
) -> None:
    run = scored_run("20260927T000000Z-mt-small100", SEGMENTS)
    path = set_baseline(run, tmp_path / "baselines")
    result = compare(load_score_set(path), load_score_set(run.path))
    assert all(d.verdict is Verdict.NO_DIFFERENCE for d in result.directions)
    assert not result.regression


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"git_dirty": True}, "dirty"),
        ({"limit": 100}, "limited"),
        ({"status": RunStatus.TRANSLATED}, "not complete"),
        ({"status": RunStatus.FAILED}, "not complete"),
    ],
)
def test_unsuitable_runs_are_refused(
    scored_run: ScoredRunFactory, tmp_path: Path, overrides: dict[str, object], reason: str
) -> None:
    run = scored_run("20260927T000000Z-mt-small100", SEGMENTS, **overrides)
    with pytest.raises(BaselineError, match=reason):
        set_baseline(run, tmp_path / "baselines")
    assert not (tmp_path / "baselines").exists()
