"""Committed baselines: aggregate and per-segment scores of a reference run, never any text.

A baseline lives at ``apps/eval/baselines/<mode>.json``. A new run is a regression when
``compare(baseline, run).regression`` (ADR-005).
"""

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from doctranslator_core.types import EngineInfo
from doctranslator_eval.datasets import DatasetInfo
from doctranslator_eval.hardware import HardwareInfo
from doctranslator_eval.runs import CometInfo, DirectionScores, RunDir, RunStatus

DEFAULT_BASELINES_DIR = Path("apps/eval/baselines")


class BaselineError(Exception):
    """A run cannot become a baseline."""


class Baseline(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str
    created_at: datetime
    dataset: DatasetInfo
    engine_info: EngineInfo
    engine_config: dict[str, object]
    hardware: HardwareInfo
    comet: CometInfo
    chrf_signature: str
    directions: dict[str, DirectionScores]
    segment_comet: dict[str, dict[str, float]]
    """``{direction: {segment id: COMET}}``: ids and numbers only."""


def baseline_from_run(run: RunDir) -> Baseline:
    manifest = run.read_manifest()
    if manifest.status is not RunStatus.COMPLETE:
        raise BaselineError(f"run {run.run_id} is {manifest.status.value}, not complete")
    if manifest.git_dirty:
        raise BaselineError(f"run {run.run_id} was made from a dirty working tree")
    if manifest.limit is not None:
        raise BaselineError(f"run {run.run_id} was limited to {manifest.limit} segments")
    scores = run.read_scores()
    return Baseline(
        run_id=manifest.run_id,
        created_at=manifest.created_at,
        dataset=manifest.dataset,
        engine_info=manifest.engine_info,
        engine_config=manifest.engine_config,
        hardware=manifest.hardware,
        comet=manifest.comet,
        chrf_signature=manifest.chrf_signature,
        directions=scores,
        segment_comet={direction: run.read_segment_scores(direction) for direction in scores},
    )


def set_baseline(run: RunDir, baselines_dir: Path = DEFAULT_BASELINES_DIR) -> Path:
    """Write the run's baseline to ``<baselines_dir>/<mode>.json``, replacing any previous one."""
    baseline = baseline_from_run(run)
    path = baselines_dir / f"{baseline.engine_info.mode.value}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(baseline.model_dump_json(indent=2) + "\n", encoding="utf-8", newline="\n")
    return path


def load_baseline(path: Path) -> Baseline:
    return Baseline.model_validate_json(path.read_text(encoding="utf-8"))
