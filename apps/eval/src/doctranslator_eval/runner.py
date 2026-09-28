"""Run a benchmark: translate every direction with one ``Translator``, then score the run."""

import logging
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from doctranslator_core import EngineConfig, Translator
from doctranslator_eval import scoring
from doctranslator_eval.datasets import Dataset, Direction, Segment
from doctranslator_eval.hardware import PeakMemory, collect_hardware
from doctranslator_eval.runs import (
    DirectionScores,
    DirectionTiming,
    RunDir,
    RunManifest,
    RunStatus,
    TranslationRow,
    engine_config_json,
    git_state,
    new_run_id,
    runs_dir,
)

logger = logging.getLogger(__name__)


def run_benchmark(
    data_dir: Path,
    engine_config: EngineConfig,
    dataset: Dataset,
    directions: Sequence[Direction],
    limit: int | None = None,
) -> RunDir:
    """Translate and score; returns the run directory.

    A translation failure marks the run ``failed``. A scoring failure leaves it ``translated``,
    and ``score_run`` can be retried without translating again. Both re-raise.
    """
    segments = {d: dataset.load(data_dir, d)[:limit] for d in directions}
    with Translator(engine_config) as translator:
        info = translator.engine_info
        commit, dirty = git_state()
        created_at = datetime.now(UTC)
        run = RunDir(runs_dir(data_dir) / new_run_id(info.mode.value, info.model, created_at))
        manifest = RunManifest(
            run_id=run.run_id,
            created_at=created_at,
            status=RunStatus.RUNNING,
            git_commit=commit,
            git_dirty=dirty,
            dataset=dataset.info,
            engine_info=info,
            engine_config=engine_config_json(engine_config),
            hardware=collect_hardware(info.details.get("device", "remote")),
            directions=[str(d) for d in directions],
            limit=limit,
            comet=scoring.COMET_INFO,
            chrf_signature=scoring.CHRF_SIGNATURE,
        )
        run.write_manifest(manifest)
        logger.info("run %s: %d directions", run.run_id, len(directions))

        try:
            timings: dict[str, DirectionTiming] = {}
            for direction in directions:
                timings[str(direction)] = _translate_direction(
                    translator, run, direction, segments[direction]
                )
                run.write_timings(timings)
        except Exception as exc:
            manifest.status, manifest.error = RunStatus.FAILED, f"{type(exc).__name__}: {exc}"
            run.write_manifest(manifest)
            raise

    manifest.status = RunStatus.TRANSLATED
    run.write_manifest(manifest)
    score_run(run)
    return run


def _translate_direction(
    translator: Translator, run: RunDir, direction: Direction, segments: list[Segment]
) -> DirectionTiming:
    started = time.perf_counter()
    with PeakMemory() as memory:
        hypotheses = translator.translate_texts(
            [s.source for s in segments], source=direction.source, target=direction.target
        )
    seconds = time.perf_counter() - started
    run.write_translations(
        direction,
        [
            TranslationRow(id=s.id, source=s.source, reference=s.reference, hypothesis=h)
            for s, h in zip(segments, hypotheses, strict=True)
        ],
    )
    logger.info("%s: %d segments in %.1f s", direction, len(segments), seconds)
    return DirectionTiming(
        seconds=round(seconds, 3),
        segments=len(segments),
        segments_per_second=round(len(segments) / seconds, 3) if seconds > 0 else 0.0,
        peak_rss_mb=memory.peak_mb,
    )


def score_run(run: RunDir) -> dict[str, DirectionScores]:
    """Score every direction of a translated run with COMET (one call) and chrF."""
    manifest = run.read_manifest()
    if manifest.status not in (RunStatus.TRANSLATED, RunStatus.COMPLETE):
        raise ValueError(f"run {run.run_id} is {manifest.status.value}; nothing to score")
    rows = {d: run.read_translations(Direction.parse(d)) for d in manifest.directions}
    all_rows = [row for direction_rows in rows.values() for row in direction_rows]

    try:
        segment_comet = scoring.comet(
            [r.source for r in all_rows],
            [r.reference for r in all_rows],
            {"run": [r.hypothesis for r in all_rows]},
        )["run"]
    except scoring.ScoringError as exc:
        manifest.error = f"scoring failed: {exc}"
        run.write_manifest(manifest)
        raise

    scores: dict[str, DirectionScores] = {}
    offset = 0
    for direction, direction_rows in rows.items():
        values = segment_comet[offset : offset + len(direction_rows)]
        offset += len(direction_rows)
        run.write_segment_scores(
            Direction.parse(direction),
            {row.id: value for row, value in zip(direction_rows, values, strict=True)},
        )
        scores[direction] = DirectionScores(
            n=len(direction_rows),
            comet=round(sum(values) / len(values), 6) if values else 0.0,
            chrf=round(
                scoring.chrf(
                    [r.hypothesis for r in direction_rows], [r.reference for r in direction_rows]
                ),
                4,
            ),
        )
    run.write_scores(scores)
    manifest.status, manifest.error = RunStatus.COMPLETE, None
    run.write_manifest(manifest)
    return scores


def format_summary(run: RunDir) -> str:
    scores = run.read_scores()
    timings = run.read_timings()
    lines = [
        f"run: {run.path}",
        f"{'direction':<9} {'n':>5} {'COMET':>7} {'chrF':>6} {'seg/s':>7} {'peak MB':>8}",
    ]
    for direction, score in scores.items():
        timing = timings.get(direction)
        speed = f"{timing.segments_per_second:>7.2f}" if timing else f"{'-':>7}"
        memory = f"{timing.peak_rss_mb:>8.0f}" if timing else f"{'-':>8}"
        lines.append(
            f"{direction:<9} {score.n:>5} {score.comet:>7.4f} {score.chrf:>6.2f} {speed} {memory}"
        )
    return "\n".join(lines)
