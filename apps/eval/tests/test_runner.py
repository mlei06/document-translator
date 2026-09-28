import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import TracebackType
from typing import Self

import pytest

from doctranslator_core import EngineConfig, LlmEngineConfig
from doctranslator_core.types import EngineInfo, EngineUnavailableError, Language, TranslationMode
from doctranslator_eval import runner, scoring
from doctranslator_eval.datasets import FLORES_FILES, Dataset, Direction, flores_dir
from doctranslator_eval.runs import RunDir, RunStatus

API_KEY = "sk-test-secret-value"
ZH_EN = Direction(source=Language.ZH, target=Language.EN)
EN_JA = Direction(source=Language.EN, target=Language.JA)
TEXTS = {
    Language.ZH: {0: "你好", 1: "谢谢", 2: "再见"},
    Language.EN: {0: "hello", 1: "thanks", 2: "bye"},
    Language.JA: {0: "こんにちは", 1: "ありがとう", 2: "さようなら"},
}


class FakeTranslator:
    """Uppercases its input; optionally fails on a given target language."""

    fail_on: Language | None = None

    def __init__(self, config: EngineConfig) -> None:
        self.config = config

    @property
    def engine_info(self) -> EngineInfo:
        return EngineInfo(mode=TranslationMode.LLM, model="fake-model", details={})

    def translate_texts(
        self, texts: Sequence[str], *, source: Language, target: Language
    ) -> list[str]:
        if target == self.fail_on:
            raise EngineUnavailableError("server gone")
        return [text.upper() for text in texts]

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        pass


def fake_comet(
    sources: Sequence[str], references: Sequence[str], hypotheses: Mapping[str, Sequence[str]]
) -> dict[str, list[float]]:
    return {label: [0.5 + i / 100 for i in range(len(h))] for label, h in hypotheses.items()}


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for language, texts in TEXTS.items():
        path = flores_dir(tmp_path) / f"{FLORES_FILES[language]}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = (
            json.dumps({"id": key, "text": text}, ensure_ascii=False) for key, text in texts.items()
        )
        path.write_text("".join(f"{row}\n" for row in rows), encoding="utf-8")
    monkeypatch.setattr(runner, "Translator", FakeTranslator)
    monkeypatch.setattr(runner, "git_state", lambda: ("deadbeef", False))
    monkeypatch.setattr(scoring, "comet", fake_comet)
    FakeTranslator.fail_on = None
    return tmp_path


def llm_config() -> LlmEngineConfig:
    return LlmEngineConfig.model_validate(
        {"base_url": "https://llm.example/v1", "api_key": API_KEY, "model": "fake-model"}
    )


def run_files(run: RunDir) -> list[Path]:
    return sorted(p for p in run.path.rglob("*") if p.is_file())


def test_complete_run_writes_every_file(data_dir: Path) -> None:
    run = runner.run_benchmark(data_dir, llm_config(), Dataset("flores"), [ZH_EN, EN_JA], limit=2)

    names = [p.relative_to(run.path).as_posix() for p in run_files(run)]
    assert names == [
        "manifest.json",
        "scores.json",
        "segment_scores/en-ja.json",
        "segment_scores/zh-en.json",
        "timing.json",
        "translations/en-ja.jsonl",
        "translations/zh-en.jsonl",
    ]
    manifest = run.read_manifest()
    assert manifest.status is RunStatus.COMPLETE
    assert manifest.error is None
    assert manifest.run_id.endswith("-llm-fake-model")
    assert (manifest.git_commit, manifest.git_dirty) == ("deadbeef", False)
    assert manifest.directions == ["zh-en", "en-ja"]
    assert manifest.limit == 2
    assert manifest.hardware.device == "remote"
    assert manifest.engine_config["model"] == "fake-model"
    assert manifest.chrf_signature == scoring.CHRF_SIGNATURE

    rows = run.read_translations(ZH_EN)
    assert [(r.id, r.source, r.reference, r.hypothesis) for r in rows] == [
        ("0", "你好", "hello", "你好"),
        ("1", "谢谢", "thanks", "谢谢"),
    ]
    assert [r.hypothesis for r in run.read_translations(EN_JA)] == ["HELLO", "THANKS"]
    # One COMET call over all directions, split back in order.
    assert run.read_segment_scores("zh-en") == {"0": 0.5, "1": 0.51}
    assert run.read_segment_scores("en-ja") == {"0": 0.52, "1": 0.53}
    scores = run.read_scores()
    assert scores["zh-en"].n == 2
    assert scores["zh-en"].comet == pytest.approx(0.505)
    assert run.read_timings()["en-ja"].segments == 2
    assert "run:" in runner.format_summary(run)


def test_api_key_is_never_written(data_dir: Path) -> None:
    run = runner.run_benchmark(data_dir, llm_config(), Dataset("flores"), [ZH_EN])
    for path in run_files(run):
        assert API_KEY not in path.read_text(encoding="utf-8"), path


def test_translation_failure_marks_run_failed(data_dir: Path) -> None:
    FakeTranslator.fail_on = Language.JA
    with pytest.raises(EngineUnavailableError):
        runner.run_benchmark(data_dir, llm_config(), Dataset("flores"), [ZH_EN, EN_JA])
    [run_path] = list((data_dir / "eval" / "runs").iterdir())
    run = RunDir(run_path)
    manifest = run.read_manifest()
    assert manifest.status is RunStatus.FAILED
    assert manifest.error is not None
    assert "server gone" in manifest.error
    assert len(run.read_translations(ZH_EN)) == 3  # completed directions are kept


def test_scoring_failure_can_be_retried(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken_comet(*args: object, **kwargs: object) -> dict[str, list[float]]:
        raise scoring.ScoringError("no network")

    monkeypatch.setattr(scoring, "comet", broken_comet)
    with pytest.raises(scoring.ScoringError):
        runner.run_benchmark(data_dir, llm_config(), Dataset("flores"), [ZH_EN])
    [run_path] = list((data_dir / "eval" / "runs").iterdir())
    run = RunDir(run_path)
    assert run.read_manifest().status is RunStatus.TRANSLATED

    monkeypatch.setattr(scoring, "comet", fake_comet)
    runner.score_run(run)
    manifest = run.read_manifest()
    assert manifest.status is RunStatus.COMPLETE
    assert manifest.error is None
    assert run.read_scores()["zh-en"].n == 3


def test_failed_run_cannot_be_scored(data_dir: Path) -> None:
    FakeTranslator.fail_on = Language.EN
    with pytest.raises(EngineUnavailableError):
        runner.run_benchmark(data_dir, llm_config(), Dataset("flores"), [ZH_EN])
    [run_path] = list((data_dir / "eval" / "runs").iterdir())
    with pytest.raises(ValueError, match="nothing to score"):
        runner.score_run(RunDir(run_path))
