import json
from pathlib import Path

import pytest

from doctranslator_eval import scoring


def test_chrf() -> None:
    assert scoring.chrf(["the cat sat"], ["the cat sat"]) == pytest.approx(100.0)
    assert scoring.chrf(["xyz"], ["the cat sat"]) < 10
    assert scoring.CHRF_SIGNATURE.startswith("nrefs:1|")


class FakeCometScore:
    """Stands in for the ``comet-score`` command: records inputs, writes its JSON shape."""

    def __init__(self, drop_last: bool = False) -> None:
        self.command: list[str] = []
        self.inputs: dict[str, list[str]] = {}
        self._drop_last = drop_last

    def __call__(self, command: list[str], cwd: Path) -> None:
        self.command = command
        for path in cwd.glob("*.txt"):
            self.inputs[path.name] = path.read_text(encoding="utf-8").splitlines()
        hyp_files = command[command.index("-t") + 1 : command.index("--model")]
        output: dict[str, list[dict[str, object]]] = {}
        for index, name in enumerate(hyp_files):
            lines = self.inputs[name][:-1] if self._drop_last else self.inputs[name]
            output[name] = [
                {"src": "s", "mt": line, "ref": "r", "COMET": index + row / 10}
                for row, line in enumerate(lines)
            ]
        target = cwd / command[command.index("--to_json") + 1]
        target.write_text(json.dumps(output), encoding="utf-8")


def test_comet_maps_labels_and_sanitizes_newlines() -> None:
    fake = FakeCometScore()
    result = scoring.comet(
        ["line one\nline two", "b"],
        ["ref\r\none", "ref b"],
        {"base": ["h1", "h2"], "new": ["n1\nmore", "n2"]},
        run_command=fake,
    )
    assert result == {"base": [0.0, 0.1], "new": [1.0, 1.1]}
    assert fake.inputs["src.txt"] == ["line one line two", "b"]
    assert fake.inputs["ref.txt"] == ["ref  one", "ref b"]
    assert fake.inputs["hyp_1.txt"] == ["n1 more", "n2"]
    assert fake.command[1:10] == [
        "tool",
        "run",
        "--python",
        scoring.COMET_PYTHON,
        "--from",
        f"unbabel-comet=={scoring.COMET_VERSION}",
        "--with",
        "setuptools<81",
        "comet-score",
    ]
    assert scoring.COMET_MODEL in fake.command


def test_comet_count_mismatch_fails_loudly() -> None:
    with pytest.raises(scoring.ScoringError, match="expected 2"):
        scoring.comet(["a", "b"], ["x", "y"], {"run": ["1", "2"]}, run_command=FakeCometScore(True))


def test_comet_rejects_unequal_inputs() -> None:
    with pytest.raises(scoring.ScoringError, match="same length"):
        scoring.comet(["a"], ["x", "y"], {"run": ["1"]}, run_command=FakeCometScore())


def test_comet_command_failure_is_a_scoring_error() -> None:
    def failing(command: list[str], cwd: Path) -> None:
        raise OSError("disk full")

    with pytest.raises(scoring.ScoringError, match="disk full"):
        scoring.comet(["a"], ["x"], {"run": ["1"]}, run_command=failing)
