"""Translation quality benchmark (ADR-005). Run from the repository root."""

import logging
import sys
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Literal

import typer

from doctranslator_core import EngineConfig, MtEngineConfig
from doctranslator_core.types import TranslationError, TranslationMode
from doctranslator_eval import baselines, compare, datasets, runner, scoring
from doctranslator_eval.runs import RunDir
from doctranslator_eval.settings import EvalSettings, SettingsError

app = typer.Typer(no_args_is_help=True, add_completion=False, help=__doc__)
baseline_app = typer.Typer(no_args_is_help=True, help="Manage committed baselines.")
app.add_typer(baseline_app, name="baseline")

_USER_ERRORS = (
    SettingsError,
    datasets.DatasetError,
    scoring.ScoringError,
    baselines.BaselineError,
    compare.CompareError,
    TranslationError,
    ValueError,
)
USER_ERROR_EXIT_CODE = 2
"""Exit code for bad input or configuration. ``compare`` uses 1 for a regression."""


@contextmanager
def _reported_errors() -> Generator[None]:
    """Report expected failures as one line on stderr instead of a traceback."""
    try:
        yield
    except _USER_ERRORS as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=USER_ERROR_EXIT_CODE) from exc


def main() -> None:
    """Console entry point: set up the console and logging, then run the app."""
    # The default Windows console code page cannot print Chinese or Japanese.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")
    logging.basicConfig(
        level=logging.INFO, stream=sys.stderr, format="%(asctime)s %(levelname)s %(message)s"
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per HTTP request otherwise
    app()


@app.command("download-flores")
def download_flores() -> None:
    """Download FLORES+ devtest at the pinned revision."""
    with _reported_errors():
        settings = EvalSettings()
        token = settings.hf_token.get_secret_value() if settings.hf_token else None
        paths = datasets.download_flores(settings.data_dir, token)
    for path in paths:
        typer.echo(path)


@app.command()
def run(
    mode: Annotated[TranslationMode, typer.Option(help="Translation mode.")],
    dataset: Annotated[str, typer.Option(help="'flores' or 'domain:<path>'.")] = "flores",
    directions: Annotated[str, typer.Option(help="'all' or e.g. 'zh-en,en-zh'.")] = "all",
    limit: Annotated[int | None, typer.Option(min=1, help="First N segments only.")] = None,
    mt_model_dir: Annotated[Path | None, typer.Option(help="Converted MT model.")] = None,
    mt_family: Annotated[Literal["small100"], typer.Option()] = "small100",
    device: Annotated[Literal["cpu", "cuda", "auto"], typer.Option()] = "auto",
    compute_type: Annotated[str, typer.Option()] = "default",
    beam_size: Annotated[int, typer.Option(min=1)] = 4,
    cpu_threads: Annotated[int, typer.Option(min=0)] = 0,
) -> None:
    """Run a benchmark, then print the run directory and a summary."""
    selected = _parse_directions(directions)
    if mode is TranslationMode.MT and mt_model_dir is None:
        raise typer.BadParameter("MT mode needs --mt-model-dir", param_hint="--mt-model-dir")
    with _reported_errors():
        settings = EvalSettings()
        engine_config: EngineConfig
        if mt_model_dir is None:
            engine_config = settings.llm_engine_config()
        else:
            engine_config = MtEngineConfig(
                model_dir=mt_model_dir,
                model_family=mt_family,
                device=device,
                compute_type=compute_type,
                beam_size=beam_size,
                cpu_threads=cpu_threads,
            )
        result = runner.run_benchmark(
            settings.data_dir, engine_config, datasets.Dataset(dataset), selected, limit
        )
        summary = runner.format_summary(result)
    typer.echo(summary)


@app.command()
def score(run_dir: Annotated[Path, typer.Argument(exists=True, file_okay=False)]) -> None:
    """(Re)score an existing run, e.g. after a COMET failure."""
    run = RunDir(run_dir)
    with _reported_errors():
        runner.score_run(run)
        summary = runner.format_summary(run)
    typer.echo(summary)


@app.command("compare")
def compare_command(
    a: Annotated[Path, typer.Argument(exists=True, help="Run directory or baseline file.")],
    b: Annotated[Path, typer.Argument(exists=True, help="Run directory or baseline file.")],
) -> None:
    """Compare b against a. Exits with code 1 on a zh-en regression."""
    with _reported_errors():
        comparison = compare.compare(compare.load_score_set(a), compare.load_score_set(b))
    typer.echo(compare.format_comparison(comparison))
    if comparison.regression:
        raise typer.Exit(code=1)


@baseline_app.command("set")
def baseline_set(
    run_dir: Annotated[Path, typer.Argument(exists=True, file_okay=False)],
    baselines_dir: Annotated[Path, typer.Option()] = baselines.DEFAULT_BASELINES_DIR,
) -> None:
    """Write apps/eval/baselines/<mode>.json from a complete, scored, clean, unlimited run."""
    with _reported_errors():
        path = baselines.set_baseline(RunDir(run_dir), baselines_dir)
    typer.echo(path)


def _parse_directions(text: str) -> list[datasets.Direction]:
    if text.strip() == "all":
        return list(datasets.ALL_DIRECTIONS)
    try:
        return [datasets.Direction.parse(part) for part in text.split(",") if part.strip()]
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="--directions") from exc
