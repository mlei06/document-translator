"""The ``doctranslator`` command.

``translate`` runs the shared core locally and synchronously: no server, no persistent history and
no document cache (ADR-010). Service commands (``submit``, ``jobs``, ``batches``, ``download``) talk
to the shared service over its REST API.
"""

import json
import logging
import sys
from pathlib import Path
from typing import Annotated, Literal, NoReturn

import typer

from doctranslator_cli.console import ProgressPrinter
from doctranslator_cli.fonts import load_font_manifest
from doctranslator_cli.settings import SettingsError, load_settings
from doctranslator_core import Translator
from doctranslator_core.types import (
    DocumentError,
    DocumentTranslationOptions,
    DocumentTranslationResult,
    FitOptions,
    Language,
    OutputPathError,
    TranslationError,
    TranslationMode,
)

__all__ = ["app", "main"]

EXIT_OK = 0
EXIT_INVALID = 2
EXIT_ENGINE = 3
EXIT_OUTPUT = 4
EXIT_INTERRUPTED = 130

app = typer.Typer(
    name="doctranslator",
    help="Translate documents (TXT, PPTX, DOCX, XLSX) inside the company network.",
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_enable=False,
)


@app.callback()
def _root() -> None:
    """Document Translator."""


def _languages() -> str:
    return ", ".join(language.value for language in Language)


@app.command()
def translate(
    input_path: Annotated[Path, typer.Argument(metavar="INPUT", help="Document to translate.")],
    to: Annotated[Language, typer.Option("--to", help="Target language.")],
    source: Annotated[
        str, typer.Option("--from", help=f"Source language ({_languages()}) or auto.")
    ] = "auto",
    mode: Annotated[
        TranslationMode | None,
        typer.Option("--mode", help="llm or mt. Default: DOCTRANSLATOR_MODE, else mt."),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option("-o", "--output", help="Output file. Default: <name>.<target><suffix>."),
    ] = None,
    protect: Annotated[
        list[str] | None, typer.Option("--protect", help="Term never translated. Repeatable.")
    ] = None,
    txt_encoding: Annotated[
        str | None, typer.Option("--txt-encoding", help="TXT input encoding. Default UTF-8.")
    ] = None,
    min_scale: Annotated[
        float, typer.Option("--min-scale", help="Fit: smallest relative font size.")
    ] = 0.7,
    min_size: Annotated[
        float, typer.Option("--min-size", help="Fit: smallest font size in points.")
    ] = 8.0,
    report: Annotated[
        bool, typer.Option("--report/--no-report", help="Write <output>.report.json.")
    ] = True,
    as_json: Annotated[
        bool, typer.Option("--json", help="Print the result as JSON on stdout.")
    ] = False,
    env_file: Annotated[
        Path | None, typer.Option("--config", help="Settings file. Default: ./.env if present.")
    ] = None,
) -> None:
    """Translate one document locally. Nothing is stored on a server."""
    try:
        requested: Language | Literal["auto"] = "auto" if source == "auto" else Language(source)
    except ValueError:
        _fail(EXIT_INVALID, f"--from must be one of {_languages()} or auto")
    try:
        settings = load_settings(env_file)
        engine = settings.engine_config(mode or settings.mode)
        options = DocumentTranslationOptions(
            source=requested,
            target=to,
            protected_terms=tuple(protect or ()),
            txt_encoding=txt_encoding,
            fit=FitOptions(min_scale=min_scale, min_size_pt=min_size),
        )
    except (SettingsError, ValueError) as exc:
        _fail(EXIT_INVALID, str(exc).splitlines()[0])
    if requested == to:
        _fail(EXIT_INVALID, "--from and --to are the same language")
    target_path = output or input_path.with_name(f"{input_path.stem}.{to.value}{input_path.suffix}")
    printer = ProgressPrinter(sys.stderr)
    fonts = load_font_manifest(settings.font_directories())
    try:
        with Translator(engine, fonts=fonts) as translator:
            result = translator.translate_document(
                input_path, target_path, options=options, on_progress=printer
            )
    except KeyboardInterrupt:
        printer.finish()
        _fail(EXIT_INTERRUPTED, "interrupted; no output was written")
    except OutputPathError as exc:
        printer.finish()
        _fail(EXIT_OUTPUT, str(exc))
    except DocumentError as exc:
        printer.finish()
        _fail(EXIT_INVALID, str(exc))
    except OSError as exc:
        printer.finish()
        _fail(EXIT_OUTPUT, f"cannot write output: {exc.strerror or exc}")
    except TranslationError as exc:
        printer.finish()
        _fail(EXIT_ENGINE, f"translation failed: {exc}")
    printer.finish()
    report_path = target_path.with_name(target_path.name + ".report.json")
    if report:
        _write_report(result, report_path)
    _summarize(result, report_path if report else None)
    if as_json:
        payload = json.loads(result.model_dump_json())
        payload["report_path"] = str(report_path) if report else None
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        typer.echo(str(result.output_path))


def _write_report(result: DocumentTranslationResult, path: Path) -> None:
    """The result as JSON (diagnostics and fit report; never document text)."""
    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(result.model_dump_json(indent=2))
    except FileExistsError:
        typer.echo(f"warning: report not written, {path} exists", err=True)


def _summarize(result: DocumentTranslationResult, report_path: Path | None) -> None:
    counts = result.counts
    source = result.source_resolved.value if result.source_resolved else "none"
    typer.echo(
        f"{result.format.value}: {source} -> {result.target.value}, {counts.segments} paragraphs, "
        f"{counts.unique_inputs} translated, {counts.passed_through} unchanged; "
        f"fit {result.fit_status.value}",
        err=True,
    )
    for diagnostic in result.diagnostics:
        where = f" [{diagnostic.location}]" if diagnostic.location else ""
        count = f" (x{diagnostic.count})" if diagnostic.count > 1 else ""
        typer.echo(
            f"{diagnostic.severity.value}: {diagnostic.code}{where}{count}: {diagnostic.message}",
            err=True,
        )
    if report_path is not None:
        typer.echo(f"report: {report_path}", err=True)


def _fail(code: int, message: str) -> NoReturn:
    typer.echo(f"error: {message}", err=True)
    raise typer.Exit(code)


def main() -> None:
    """Entry point: UTF-8 console output, warnings to stderr, then the Typer app."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("fontTools").setLevel(logging.ERROR)  # noisy about font timestamps
    app()
