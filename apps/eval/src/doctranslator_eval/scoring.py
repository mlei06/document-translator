"""chrF (in-process) and COMET (isolated in its own ``uv tool`` environment, ADR-005)."""

import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import cast

from sacrebleu.metrics.chrf import CHRF

from doctranslator_eval.runs import CometInfo

COMET_VERSION = "2.2.7"
COMET_PYTHON = "3.11"
"""COMET 2.2.7 pins jsonargparse 3.13.1, which calls a private argparse method whose signature
changed in recent CPython 3.12 patch releases; on 3.11 it still matches."""
COMET_MODEL = "Unbabel/wmt22-comet-da"
COMET_EXTRA_REQUIREMENTS = ["setuptools<81"]
"""COMET 2.2.7's torchmetrics imports ``pkg_resources``, which setuptools 81 removed."""
COMET_INFO = CometInfo(version=COMET_VERSION, model=COMET_MODEL, python=COMET_PYTHON)


class ScoringError(Exception):
    """A metric could not be computed."""


def chrf(hypotheses: Sequence[str], references: Sequence[str]) -> float:
    """Corpus-level chrF with sacrebleu defaults (char n-gram 6, word n-gram 0, beta 2)."""
    return float(CHRF().corpus_score(list(hypotheses), [list(references)]).score)


def _chrf_signature() -> str:
    # sacrebleu completes the signature (e.g. the reference count) only after a first score.
    metric = CHRF()
    metric.corpus_score(["signature"], [["signature"]])
    return str(metric.get_signature())


CHRF_SIGNATURE = _chrf_signature()


type CommandRunner = Callable[[list[str], Path], None]
"""Runs a command in a working directory, raising on failure. Replaced in tests."""


def _run_command(command: list[str], cwd: Path) -> None:
    subprocess.run(command, cwd=cwd, check=True, env=os.environ.copy())  # noqa: S603


def comet(
    sources: Sequence[str],
    references: Sequence[str],
    hypotheses: Mapping[str, Sequence[str]],
    *,
    run_command: CommandRunner = _run_command,
) -> dict[str, list[float]]:
    """Per-segment COMET for each labelled hypothesis list, in input order.

    All hypothesis lists share ``sources`` and ``references`` and are scored in one call, so the
    COMET model loads once. The first call downloads PyTorch for Python 3.11 and the COMET model
    (about 2.5 GB) into the uv and Hugging Face caches.
    """
    count = len(sources)
    if len(references) != count or any(len(h) != count for h in hypotheses.values()):
        raise ScoringError("sources, references, and hypotheses must have the same length")
    if not hypotheses:
        return {}
    uv = shutil.which("uv")
    if uv is None:
        raise ScoringError("COMET needs 'uv' on PATH (https://docs.astral.sh/uv/)")

    with tempfile.TemporaryDirectory(prefix="doctranslator-comet-") as tmp:
        workdir = Path(tmp)
        _write_lines(workdir / "src.txt", sources)
        _write_lines(workdir / "ref.txt", references)
        files = {label: f"hyp_{index}.txt" for index, label in enumerate(hypotheses)}
        for label, name in files.items():
            _write_lines(workdir / name, hypotheses[label])
        command = [
            uv,
            "tool",
            "run",
            "--python",
            COMET_PYTHON,
            "--from",
            f"unbabel-comet=={COMET_VERSION}",
            *(arg for requirement in COMET_EXTRA_REQUIREMENTS for arg in ("--with", requirement)),
            "comet-score",
            "-s",
            "src.txt",
            "-r",
            "ref.txt",
            "-t",
            *files.values(),
            "--model",
            COMET_MODEL,
            "--gpus",
            "0",
            "--quiet",
            "--only_system",
            "--to_json",
            "scores.json",
        ]
        try:
            run_command(command, workdir)
        except (subprocess.CalledProcessError, OSError) as exc:
            raise ScoringError(f"comet-score failed: {exc}") from exc
        output = _read_output(workdir / "scores.json")

    scores: dict[str, list[float]] = {}
    for label, name in files.items():
        segment_scores = output.get(name)
        if segment_scores is None or len(segment_scores) != count:
            found = "none" if segment_scores is None else str(len(segment_scores))
            raise ScoringError(f"COMET returned {found} scores for {name}, expected {count}")
        scores[label] = segment_scores
    return scores


def _write_lines(path: Path, texts: Sequence[str]) -> None:
    """One segment per line. Line breaks inside a segment would misalign every later segment."""
    lines = (text.replace("\r", " ").replace("\n", " ") for text in texts)
    path.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8", newline="\n")


def _read_output(path: Path) -> dict[str, list[float]]:
    """Parse ``{<hypothesis file>: [{"src", "mt", "ref", "COMET"}, ...]}``."""
    try:
        payload: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ScoringError(f"COMET output unreadable: {path.name}") from exc
    if not isinstance(payload, dict):
        raise ScoringError("COMET output is not an object")
    result: dict[str, list[float]] = {}
    for key, rows in cast(dict[str, object], payload).items():
        if not isinstance(rows, list):
            raise ScoringError(f"COMET output for {key} is not a list")
        values: list[float] = []
        for row in cast(list[object], rows):
            value = cast(dict[str, object], row).get("COMET") if isinstance(row, dict) else None
            if not isinstance(value, int | float):
                raise ScoringError(f"COMET output for {key} has a row without a score")
            values.append(float(value))
        result[Path(key).name] = values
    return result
