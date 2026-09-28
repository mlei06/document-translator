from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest

from doctranslator_core.types import EngineInfo, TranslationMode
from doctranslator_eval.datasets import DatasetInfo, Direction
from doctranslator_eval.hardware import HardwareInfo
from doctranslator_eval.runs import (
    CometInfo,
    DirectionScores,
    RunDir,
    RunManifest,
    RunStatus,
    TranslationRow,
)

HARDWARE = HardwareInfo(
    os="TestOS",
    os_version="1",
    cpu="Test CPU",
    logical_cores=8,
    physical_cores=4,
    ram_gb=16.0,
    device="cpu",
)


def make_manifest(run_id: str, directions: list[str], **overrides: object) -> RunManifest:
    values: dict[str, object] = {
        "run_id": run_id,
        "created_at": datetime(2026, 9, 27, tzinfo=UTC),
        "status": RunStatus.COMPLETE,
        "git_commit": "abc123",
        "git_dirty": False,
        "dataset": DatasetInfo(name="flores_plus", revision="rev"),
        "engine_info": EngineInfo(mode=TranslationMode.MT, model="small100", details={}),
        "engine_config": {"mode": "mt", "model_dir": "m"},
        "hardware": HARDWARE,
        "directions": directions,
        "limit": None,
        "comet": CometInfo(version="2.2.7", model="Unbabel/wmt22-comet-da", python="3.12"),
        "chrf_signature": "chrF2|test",
    }
    return RunManifest.model_validate(values | overrides)


def write_scored_run(
    root: Path,
    run_id: str,
    segment_comet: dict[str, dict[str, float]],
    *,
    chrf: float = 50.0,
    **manifest_overrides: object,
) -> RunDir:
    """A complete run with the given per-segment COMET scores and placeholder texts."""
    run = RunDir(root / run_id)
    run.write_manifest(make_manifest(run_id, list(segment_comet), **manifest_overrides))
    scores: dict[str, DirectionScores] = {}
    for name, segments in segment_comet.items():
        direction = Direction.parse(name)
        run.write_translations(
            direction,
            [
                TranslationRow(
                    id=key,
                    source=f"source text {name} {key}",
                    reference=f"reference text {name} {key}",
                    hypothesis=f"hypothesis text {name} {key}",
                )
                for key in segments
            ],
        )
        run.write_segment_scores(direction, segments)
        mean = sum(segments.values()) / len(segments)
        scores[name] = DirectionScores(n=len(segments), comet=mean, chrf=chrf)
    run.write_scores(scores)
    return run


type ScoredRunFactory = Callable[..., RunDir]


@pytest.fixture
def scored_run(tmp_path: Path) -> ScoredRunFactory:
    """``scored_run(run_id, segment_comet, *, chrf=..., **manifest_overrides) -> RunDir``."""

    def factory(
        run_id: str,
        segment_comet: dict[str, dict[str, float]],
        *,
        chrf: float = 50.0,
        **manifest_overrides: object,
    ) -> RunDir:
        return write_scored_run(
            tmp_path / "runs", run_id, segment_comet, chrf=chrf, **manifest_overrides
        )

    return factory
