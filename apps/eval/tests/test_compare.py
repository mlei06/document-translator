import random
from pathlib import Path

import pytest

from doctranslator_eval.compare import (
    CompareError,
    ScoreSet,
    Verdict,
    bootstrap_interval,
    compare,
    format_comparison,
    load_score_set,
)
from doctranslator_eval.runs import DirectionScores


def score_set(label: str, segment_comet: dict[str, dict[str, float]], chrf: float = 50) -> ScoreSet:
    return ScoreSet(
        label=label,
        directions={
            d: DirectionScores(n=len(s), comet=sum(s.values()) / len(s), chrf=chrf)
            for d, s in segment_comet.items()
        },
        segment_comet=segment_comet,
    )


def noisy(n: int, mean: float, seed: int) -> dict[str, float]:
    rng = random.Random(seed)
    return {str(i): mean + rng.uniform(-0.05, 0.05) for i in range(n)}


def test_identical_inputs_show_no_difference() -> None:
    scores = {"zh-en": noisy(200, 0.8, 1), "en-zh": noisy(200, 0.7, 2)}
    result = compare(score_set("a", scores), score_set("b", scores))
    assert [d.verdict for d in result.directions] == [Verdict.NO_DIFFERENCE] * 2
    assert all(d.delta_comet == 0 for d in result.directions)
    assert not result.regression


def test_clear_differences_get_verdicts_and_regression_uses_zh_en_only() -> None:
    a = score_set("a", {"zh-en": noisy(200, 0.80, 1), "en-zh": noisy(200, 0.80, 2)}, chrf=50)
    b = score_set("b", {"zh-en": noisy(200, 0.75, 3), "en-zh": noisy(200, 0.85, 4)}, chrf=48)
    result = compare(a, b)
    verdicts = {d.direction: d.verdict for d in result.directions}
    assert verdicts == {"zh-en": Verdict.WORSE, "en-zh": Verdict.BETTER}
    assert result.regression
    assert result.directions[0].delta_chrf == pytest.approx(-2)
    assert "REGRESSION" in format_comparison(result)

    only_en_zh_worse = compare(b, a)
    assert {d.direction: d.verdict for d in only_en_zh_worse.directions}["en-zh"] is Verdict.WORSE
    assert not only_en_zh_worse.regression


def test_directions_follow_standard_order() -> None:
    scores = {"en-zh": noisy(10, 0.7, 1), "zh-en": noisy(10, 0.8, 2)}
    result = compare(score_set("a", scores), score_set("b", scores))
    assert [d.direction for d in result.directions] == ["zh-en", "en-zh"]


def test_bootstrap_is_deterministic() -> None:
    deltas = [random.Random(5).uniform(-1, 1) for _ in range(50)]
    assert bootstrap_interval(deltas) == bootstrap_interval(deltas)
    low, high = bootstrap_interval(deltas)
    assert low <= sum(deltas) / len(deltas) <= high


def test_mismatched_ids_and_directions_are_reported() -> None:
    a = score_set("a", {"zh-en": {"1": 0.8, "2": 0.8, "3": 0.8}, "ja-es": {"1": 0.5}})
    b = score_set("b", {"zh-en": {"2": 0.8, "3": 0.8, "4": 0.8}})
    result = compare(a, b)
    [zh_en] = result.directions
    assert (zh_en.n, zh_en.only_in_a, zh_en.only_in_b) == (2, 1, 1)
    assert result.missing_directions == ["ja-es"]
    with pytest.raises(CompareError, match="no segment ids"):
        compare(score_set("a", {"zh-en": {"1": 0.8}}), score_set("b", {"zh-en": {"2": 0.8}}))


def test_load_score_set_rejects_unknown_paths(tmp_path: Path) -> None:
    with pytest.raises(CompareError, match="not a run directory"):
        load_score_set(tmp_path / "missing")
