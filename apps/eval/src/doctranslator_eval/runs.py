"""The run directory: everything one benchmark run produces, under ``data/eval/runs/<run_id>/``.

| File | Content |
|------|---------|
| ``manifest.json`` | ``RunManifest`` |
| ``translations/<direction>.jsonl`` | one ``TranslationRow`` per segment |
| ``timing.json`` | ``{direction: DirectionTiming}`` |
| ``scores.json`` | ``{direction: DirectionScores}`` |
| ``segment_scores/<direction>.json`` | ``{segment id: COMET}`` |
"""

import re
import shutil
import subprocess
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, TypeAdapter

from doctranslator_core import EngineConfig
from doctranslator_core.types import EngineInfo
from doctranslator_eval.datasets import DatasetInfo, Direction
from doctranslator_eval.hardware import HardwareInfo


class RunStatus(StrEnum):
    RUNNING = "running"
    TRANSLATED = "translated"
    """All directions translated; scoring not done or failed (``score`` retries it)."""
    COMPLETE = "complete"
    FAILED = "failed"


class CometInfo(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str
    model: str
    python: str


class RunManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    created_at: datetime
    status: RunStatus
    error: str | None = None
    git_commit: str
    git_dirty: bool
    dataset: DatasetInfo
    engine_info: EngineInfo
    engine_config: dict[str, object]
    """The engine configuration as JSON, without the API key."""
    hardware: HardwareInfo
    directions: list[str]
    limit: int | None
    comet: CometInfo
    chrf_signature: str


class TranslationRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    source: str
    reference: str
    hypothesis: str


class DirectionTiming(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    seconds: float
    segments: int
    segments_per_second: float
    peak_rss_mb: float


class DirectionScores(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    n: int
    comet: float
    chrf: float


_TIMINGS = TypeAdapter(dict[str, DirectionTiming])
_SCORES = TypeAdapter(dict[str, DirectionScores])
_SEGMENT_SCORES = TypeAdapter(dict[str, float])


def runs_dir(data_dir: Path) -> Path:
    return data_dir / "eval" / "runs"


def new_run_id(mode: str, model: str, now: datetime | None = None) -> str:
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", model).strip("-") or "model"
    return f"{stamp}-{mode}-{slug}"


def engine_config_json(config: EngineConfig) -> dict[str, object]:
    """The configuration as JSON-compatible data, never including the API key."""
    return config.model_dump(mode="json", exclude={"api_key"})


def git_state() -> tuple[str, bool]:
    """``(HEAD commit, working tree dirty)``; ``("unknown", True)`` outside a git checkout."""
    git = shutil.which("git")
    if git is None:
        return "unknown", True
    try:
        commit = subprocess.run(  # noqa: S603 - fixed arguments
            [git, "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
        status = subprocess.run(  # noqa: S603 - fixed arguments
            [git, "status", "--porcelain"], capture_output=True, text=True, check=True
        ).stdout
    except subprocess.CalledProcessError:
        return "unknown", True
    return commit, bool(status.strip())


class RunDir:
    """Reads and writes one run directory."""

    def __init__(self, path: Path) -> None:
        self.path = path

    @property
    def run_id(self) -> str:
        return self.path.name

    def read_manifest(self) -> RunManifest:
        return RunManifest.model_validate_json(self._read("manifest.json"))

    def write_manifest(self, manifest: RunManifest) -> None:
        self._write("manifest.json", manifest.model_dump_json(indent=2))

    def write_translations(self, direction: Direction, rows: list[TranslationRow]) -> None:
        lines = [row.model_dump_json() for row in rows]
        self._write(f"translations/{direction}.jsonl", "".join(f"{line}\n" for line in lines))

    def read_translations(self, direction: Direction) -> list[TranslationRow]:
        text = self._read(f"translations/{direction}.jsonl")
        return [TranslationRow.model_validate_json(line) for line in text.splitlines() if line]

    def read_timings(self) -> dict[str, DirectionTiming]:
        if not (self.path / "timing.json").is_file():
            return {}
        return _TIMINGS.validate_json(self._read("timing.json"))

    def write_timings(self, timings: dict[str, DirectionTiming]) -> None:
        self._write("timing.json", _TIMINGS.dump_json(timings, indent=2).decode())

    def read_scores(self) -> dict[str, DirectionScores]:
        return _SCORES.validate_json(self._read("scores.json"))

    def write_scores(self, scores: dict[str, DirectionScores]) -> None:
        self._write("scores.json", _SCORES.dump_json(scores, indent=2).decode())

    def read_segment_scores(self, direction: str) -> dict[str, float]:
        return _SEGMENT_SCORES.validate_json(self._read(f"segment_scores/{direction}.json"))

    def write_segment_scores(self, direction: Direction, scores: dict[str, float]) -> None:
        text = _SEGMENT_SCORES.dump_json(scores, indent=2).decode()
        self._write(f"segment_scores/{direction}.json", text)

    def _read(self, name: str) -> str:
        return (self.path / name).read_text(encoding="utf-8")

    def _write(self, name: str, text: str) -> None:
        path = self.path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
