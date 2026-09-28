"""Compare two runs or baselines with a paired bootstrap on per-segment COMET (ADR-005)."""

import random
import statistics
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from doctranslator_eval.baselines import load_baseline
from doctranslator_eval.datasets import ALL_DIRECTIONS
from doctranslator_eval.runs import DirectionScores, RunDir, RunStatus

RESAMPLES = 1000
SEED = 0
CONFIDENCE = 0.95
DECIDING_DIRECTION = "zh-en"


class CompareError(Exception):
    """An input cannot be compared."""


class ScoreSet(BaseModel):
    """What ``compare`` needs from a run or a baseline."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    label: str
    directions: dict[str, DirectionScores]
    segment_comet: dict[str, dict[str, float]]


def load_score_set(path: Path) -> ScoreSet:
    """A run directory or a baseline file."""
    if path.is_dir():
        run = RunDir(path)
        status = run.read_manifest().status
        if status is not RunStatus.COMPLETE:
            raise CompareError(f"run {run.run_id} is {status.value}, not complete")
        scores = run.read_scores()
        return ScoreSet(
            label=run.run_id,
            directions=scores,
            segment_comet={d: run.read_segment_scores(d) for d in scores},
        )
    if path.is_file():
        baseline = load_baseline(path)
        return ScoreSet(
            label=f"baseline {path.name} ({baseline.run_id})",
            directions=baseline.directions,
            segment_comet=baseline.segment_comet,
        )
    raise CompareError(f"not a run directory or baseline file: {path}")


class Verdict(StrEnum):
    BETTER = "better"
    WORSE = "worse"
    NO_DIFFERENCE = "no significant difference"


class DirectionComparison(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    direction: str
    n: int
    """Segments present in both inputs."""
    only_in_a: int
    only_in_b: int
    comet_a: float
    comet_b: float
    delta_comet: float
    """``mean(b) - mean(a)`` over the shared segments."""
    ci_low: float
    ci_high: float
    verdict: Verdict
    delta_chrf: float
    """Corpus chrF difference, ``b - a``, without a significance test."""


class Comparison(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    a: str
    b: str
    directions: list[DirectionComparison]
    missing_directions: list[str]
    """Directions present in only one input; not compared."""

    @property
    def regression(self) -> bool:
        """``b`` is significantly worse than ``a`` on the deciding direction."""
        return any(
            d.direction == DECIDING_DIRECTION and d.verdict is Verdict.WORSE
            for d in self.directions
        )


def compare(a: ScoreSet, b: ScoreSet) -> Comparison:
    order = [str(d) for d in ALL_DIRECTIONS]
    shared = [d for d in order if d in a.directions and d in b.directions]
    return Comparison(
        a=a.label,
        b=b.label,
        directions=[_compare_direction(a, b, direction) for direction in shared],
        missing_directions=sorted(set(a.directions) ^ set(b.directions)),
    )


def _compare_direction(a: ScoreSet, b: ScoreSet, direction: str) -> DirectionComparison:
    segments_a, segments_b = a.segment_comet[direction], b.segment_comet[direction]
    ids = sorted(segments_a.keys() & segments_b.keys())
    if not ids:
        raise CompareError(f"{direction}: no segment ids in common")
    scores_a = [segments_a[i] for i in ids]
    scores_b = [segments_b[i] for i in ids]
    deltas = [y - x for x, y in zip(scores_a, scores_b, strict=True)]
    low, high = bootstrap_interval(deltas)
    if low > 0:
        verdict = Verdict.BETTER
    elif high < 0:
        verdict = Verdict.WORSE
    else:
        verdict = Verdict.NO_DIFFERENCE
    return DirectionComparison(
        direction=direction,
        n=len(ids),
        only_in_a=len(segments_a.keys() - segments_b.keys()),
        only_in_b=len(segments_b.keys() - segments_a.keys()),
        comet_a=statistics.fmean(scores_a),
        comet_b=statistics.fmean(scores_b),
        delta_comet=statistics.fmean(deltas),
        ci_low=low,
        ci_high=high,
        verdict=verdict,
        delta_chrf=b.directions[direction].chrf - a.directions[direction].chrf,
    )


def bootstrap_interval(
    deltas: list[float], resamples: int = RESAMPLES, seed: int = SEED
) -> tuple[float, float]:
    """Percentile interval of the mean paired delta, resampling segments with replacement."""
    rng = random.Random(seed)  # noqa: S311 - statistics, not security
    count = len(deltas)
    means = sorted(
        statistics.fmean(deltas[rng.randrange(count)] for _ in range(count))
        for _ in range(resamples)
    )
    tail = (1 - CONFIDENCE) / 2
    low_index = int(tail * resamples)
    high_index = min(int((1 - tail) * resamples), resamples - 1)
    return means[low_index], means[high_index]


def format_comparison(comparison: Comparison) -> str:
    lines = [
        f"a: {comparison.a}",
        f"b: {comparison.b}",
        "",
        f"{'direction':<9} {'n':>5} {'COMET a':>8} {'COMET b':>8} {'delta':>8} "
        f"{'95% interval':>19} {'chrF d':>7}  verdict",
    ]
    for d in comparison.directions:
        interval = f"[{d.ci_low:+.4f}, {d.ci_high:+.4f}]"
        lines.append(
            f"{d.direction:<9} {d.n:>5} {d.comet_a:>8.4f} {d.comet_b:>8.4f} "
            f"{d.delta_comet:>+8.4f} {interval:>19} {d.delta_chrf:>+7.2f}  {d.verdict.value}"
        )
        if d.only_in_a or d.only_in_b:
            lines.append(f"{'':<9} ids only in a: {d.only_in_a}, only in b: {d.only_in_b}")
    if comparison.missing_directions:
        lines.append(f"not compared: {', '.join(comparison.missing_directions)}")
    lines.append("")
    verdict = "REGRESSION" if comparison.regression else "no regression"
    lines.append(f"{DECIDING_DIRECTION}: {verdict}")
    return "\n".join(lines)
