"""Service commands: ``whoami``, ``submit``, ``batches``, ``jobs`` and ``download`` (ADR-010).

They talk to the shared service over REST and never translate locally or fall back to local
translation. Exit codes: 0 success; 1 a completed run or download has failed, rejected,
cancelled, unsubmitted (or, with ``--fail-on-unresolved``, unresolved-fit) items; 2 invalid
configuration, authentication or usage; 3 the service could not be reached; 130 interrupted.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

import json
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Any, NoReturn

import typer

from doctranslator_cli.batch import (
    Entry,
    ItemState,
    ManifestError,
    ResumeState,
    RunSummary,
    download_items,
    entries_from_manifest,
    entries_from_paths,
    submit_all,
    wait_for,
)
from doctranslator_cli.service import (
    ServiceClient,
    ServiceError,
    ServiceUnavailableError,
    with_retries,
)
from doctranslator_cli.settings import CliSettings, SettingsError, load_settings

__all__ = ["register"]

EXIT_OK = 0
EXIT_ITEMS = 1
EXIT_INVALID = 2
EXIT_SERVICE = 3
EXIT_INTERRUPTED = 130

Server = Annotated[
    str | None,
    typer.Option("--server", help="Service URL. Default: DOCTRANSLATOR_SERVER_URL."),
]
Config = Annotated[
    Path | None, typer.Option("--config", help="Settings file. Default: ./.env if present.")
]
AsJson = Annotated[bool, typer.Option("--json", help="Machine-readable JSON on stdout.")]


def _fail(code: int, message: str) -> NoReturn:
    typer.echo(f"error: {message}", err=True)
    raise typer.Exit(code)


def _note(message: str) -> None:
    typer.echo(message, err=True)


@contextmanager
def _client(
    server: str | None, config: Path | None
) -> Generator[tuple[ServiceClient, CliSettings, str]]:
    try:
        settings = load_settings(config)
        url, key = settings.service(server)
    except SettingsError as exc:
        _fail(EXIT_INVALID, str(exc))
    client = ServiceClient(url, key.get_secret_value())
    try:
        yield client, settings, url
    except ServiceError as exc:
        if exc.status == 401:
            _fail(EXIT_INVALID, "the service rejected the API key (missing, revoked or disabled)")
        if exc.status == 404:
            _fail(EXIT_INVALID, exc.message)
        _fail(EXIT_SERVICE, f"{exc.code}: {exc.message}")
    except ServiceUnavailableError as exc:
        _fail(EXIT_SERVICE, f"the service is unreachable: {exc}")
    finally:
        client.close()


def _emit(payload: dict[str, Any]) -> None:
    typer.echo(json.dumps(payload, ensure_ascii=False))


def register(app: typer.Typer) -> None:
    jobs = typer.Typer(help="Your jobs on the shared service.", no_args_is_help=True)
    batches = typer.Typer(help="Your batches on the shared service.", no_args_is_help=True)
    app.add_typer(jobs, name="jobs")
    app.add_typer(batches, name="batches")

    @app.command()
    def whoami(server: Server = None, config: Config = None, as_json: AsJson = False) -> None:  # pyright: ignore[reportUnusedFunction]
        """Show the authenticated user and what the service supports."""
        with _client(server, config) as (client, _, url):
            me = client.get("/me")
            caps = client.get("/capabilities")
        if as_json:
            _emit({"server": url, "user": me, "capabilities": caps})
            return
        typer.echo(f"{me['display_name']} ({me['id']}) on {url}")
        typer.echo(
            f"modes: {', '.join(caps['modes'])}; formats: {', '.join(caps['formats'])}; "
            f"max upload {caps['limits']['max_upload_bytes']} bytes"
        )

    @app.command()
    def submit(  # pyright: ignore[reportUnusedFunction]
        files: Annotated[
            list[Path] | None, typer.Argument(help="Files to translate (or use --manifest).")
        ] = None,
        to: Annotated[str | None, typer.Option("--to", help="Target language.")] = None,
        source: Annotated[str, typer.Option("--from", help="Source language or auto.")] = "auto",
        mode: Annotated[str | None, typer.Option("--mode", help="mt or llm.")] = None,
        manifest: Annotated[
            Path | None, typer.Option(help="JSON Lines: {path, source?, target?, mode?} per line.")
        ] = None,
        resume_state: Annotated[
            Path | None,
            typer.Option(help="Run record to resume an interrupted submission (JSON Lines)."),
        ] = None,
        wait: Annotated[
            bool, typer.Option("--wait", help="Wait until every job finishes.")
        ] = False,
        download_dir: Annotated[
            Path | None, typer.Option(help="Download successful outputs here (implies --wait).")
        ] = None,
        report: Annotated[
            bool, typer.Option("--report/--no-report", help="Also download fit reports.")
        ] = True,
        overwrite: Annotated[bool, typer.Option(help="Replace existing downloads.")] = False,
        concurrency: Annotated[int, typer.Option(min=1, max=8, help="Uploads in flight.")] = 2,
        label: Annotated[str, typer.Option(help="Batch label.")] = "",
        force: Annotated[bool, typer.Option("--force", help="Bypass the service cache.")] = False,
        protect: Annotated[
            list[str] | None, typer.Option("--protect", help="Term never translated.")
        ] = None,
        fail_on_unresolved: Annotated[
            bool, typer.Option(help="Exit 1 when any output has unresolved fit.")
        ] = False,
        server: Server = None,
        config: Config = None,
        as_json: AsJson = False,
    ) -> None:
        """Submit files to the shared service as one batch.

        Without --wait this returns once files are accepted: accepted is not yet translated.
        CTRL+C stops submitting and waiting but does not cancel accepted jobs.
        """
        if bool(files) == bool(manifest):
            _fail(EXIT_INVALID, "give FILES or --manifest (not both)")
        with _client(server, config) as (client, settings, url):
            me = client.get("/me")
            caps = client.get("/capabilities")
            chosen_mode = mode or settings.mode.value
            if chosen_mode not in caps["modes"]:
                _fail(EXIT_INVALID, f"mode {chosen_mode} is not available on this service")
            defaults: dict[str, Any] = {"source": source, "mode": chosen_mode}
            if to:
                defaults["target"] = to
            if force:
                defaults["force_retranslate"] = True
            if protect:
                defaults["protected_terms"] = list(protect)
            state = ResumeState(resume_state)
            if state.run:
                if state.run.get("server") != url or state.run.get("user_id") != me["id"]:
                    _fail(EXIT_INVALID, "the resume state belongs to another service or user")
                batch_key = str(state.run["batch_key"])
            else:
                batch_key = str(uuid.uuid4())
                state.start(server=url, user_id=me["id"], batch_key=batch_key, label=label)
            batch = with_retries(lambda: client.create_batch(batch_key, label))
            _note(f"batch {batch['id']}")
            entries = (
                entries_from_manifest(manifest, defaults)
                if manifest
                else entries_from_paths(files or [], defaults)
            )
            summary = RunSummary()

            def on_item(entry: Entry, item: ItemState) -> None:
                if item.status == "accepted":
                    summary.accepted += 1
                elif item.status == "rejected":
                    summary.rejected += 1
                else:
                    summary.unsubmitted += 1
                detail = f" ({item.error})" if item.error else ""
                _note(f"{item.status}: {entry.path.name}{detail}")
                if as_json and not (wait or download_dir):
                    _emit(
                        {
                            "path": str(entry.path),
                            "client_item_id": item.client_item_id,
                            "status": item.status,
                            "item_id": item.item_id,
                            "job_id": item.job_id,
                            "error": item.error,
                        }
                    )

            def checked() -> Generator[Entry]:
                for entry in entries:
                    if "target" not in entry.options:
                        _fail(EXIT_INVALID, f"{entry.path}: no target language (--to)")
                    yield entry

            try:
                submit_all(
                    client,
                    batch["id"],
                    checked(),
                    state,
                    concurrency=concurrency,
                    notify=_note,
                    on_item=on_item,
                )
            except KeyboardInterrupt:
                state.close()
                _note(
                    f"interrupted; accepted jobs continue. Resume with the same --resume-state "
                    f"or check: doctranslator batches status {batch['id']}"
                )
                raise typer.Exit(EXIT_INTERRUPTED) from None
            except ManifestError as exc:
                state.close()
                _fail(EXIT_INVALID, str(exc))
            state.close()
            if summary.unsubmitted == 0:
                client.post(f"/batches/{batch['id']}/seal")
            else:
                _note(
                    f"{summary.unsubmitted} files were not submitted; the batch stays open. "
                    "Rerun with the same --resume-state to retry them."
                )
            _note(
                f"accepted {summary.accepted}, rejected {summary.rejected}, "
                f"unsubmitted {summary.unsubmitted}"
            )
            if not (wait or download_dir):
                if not as_json:
                    typer.echo(batch["id"])
                _note("accepted files are queued; use --wait or `batches status` to follow them")
                raise typer.Exit(EXIT_ITEMS if summary.rejected or summary.unsubmitted else EXIT_OK)
            try:
                items = wait_for(client, batch["id"], _note)
            except KeyboardInterrupt:
                _note(
                    "stopped waiting; jobs continue. Check: doctranslator batches status "
                    f"{batch['id']}"
                )
                raise typer.Exit(EXIT_INTERRUPTED) from None
            outputs: dict[str, str] = {}
            if download_dir is not None:
                for item, path, error in download_items(
                    client, items, download_dir, report=report, overwrite=overwrite, notify=_note
                ):
                    if error is None and path is not None:
                        summary.downloaded += 1
                        outputs[item["id"]] = str(path)
                    else:
                        summary.download_failed += 1
            _finish(summary, items, outputs, as_json, fail_on_unresolved)

    def _finish(
        summary: RunSummary,
        items: list[dict[str, Any]],
        outputs: dict[str, str],
        as_json: bool,
        fail_on_unresolved: bool,
    ) -> NoReturn:
        for item in items:
            job = item.get("job") or {}
            status = job.get("status") or "rejected"
            if status == "succeeded":
                summary.succeeded += 1
                if job.get("fit_status") == "unresolved":
                    summary.unresolved += 1
            elif status == "failed":
                summary.failed += 1
            elif status == "cancelled":
                summary.cancelled += 1
            if as_json:
                _emit(
                    {
                        "item_id": item["id"],
                        "client_item_id": item["client_item_id"],
                        "name": item["original_name"],
                        "status": status,
                        "job_id": job.get("id"),
                        "document_id": job.get("document_id"),
                        "fit_status": job.get("fit_status"),
                        "error": job.get("error_code") or item.get("rejection_code"),
                        "output": outputs.get(item["id"]),
                    }
                )
            elif item["id"] in outputs:
                typer.echo(outputs[item["id"]])
        _note(
            f"succeeded {summary.succeeded} (unresolved fit {summary.unresolved}), failed "
            f"{summary.failed}, cancelled {summary.cancelled}, rejected {summary.rejected}, "
            f"unsubmitted {summary.unsubmitted}, downloaded {summary.downloaded}, "
            f"download failed {summary.download_failed}"
        )
        bad = (
            summary.failed
            + summary.cancelled
            + summary.rejected
            + summary.unsubmitted
            + summary.download_failed
        )
        if bad or (fail_on_unresolved and summary.unresolved):
            raise typer.Exit(EXIT_ITEMS)
        raise typer.Exit(EXIT_OK)

    @batches.command("list")
    def batches_list(server: Server = None, config: Config = None, as_json: AsJson = False) -> None:  # pyright: ignore[reportUnusedFunction]
        with _client(server, config) as (client, _, _url):
            for batch in client.pages("/batches"):
                if as_json:
                    _emit(batch)
                else:
                    typer.echo(
                        f"{batch['id']}  {batch['state']:9}  {batch['items']:5} items  "
                        f"{batch['label']}"
                    )

    @batches.command("status")
    def batches_status(  # pyright: ignore[reportUnusedFunction]
        batch_id: str, server: Server = None, config: Config = None, as_json: AsJson = False
    ) -> None:
        """Per-file outcomes of a batch."""
        with _client(server, config) as (client, _, _url):
            batch = client.get(f"/batches/{batch_id}")
            items = list(client.pages(f"/batches/{batch_id}/items"))
        if as_json:
            _emit({"batch": batch, "items": items})
            return
        typer.echo(f"batch {batch['id']} ({batch['state']}): {json.dumps(batch['counts'])}")
        for item in items:
            job = item.get("job") or {}
            status = job.get("status") or f"rejected ({item['rejection_code']})"
            fit = f" fit {job['fit_status']}" if job.get("fit_status") else ""
            error = f" {job['error_code']}" if job.get("error_code") else ""
            typer.echo(f"{item['ordinal']:5}  {status:10}{fit}{error}  {item['original_name']}")

    @batches.command("cancel")
    def batches_cancel(batch_id: str, server: Server = None, config: Config = None) -> None:  # pyright: ignore[reportUnusedFunction]
        """Seal the batch and cancel its unfinished jobs (finished outputs remain)."""
        with _client(server, config) as (client, _, _url):
            batch = client.post(f"/batches/{batch_id}/cancel")
        typer.echo(f"batch {batch['id']} {batch['state']}: {json.dumps(batch['counts'])}")

    @jobs.command("list")
    def jobs_list(  # pyright: ignore[reportUnusedFunction]
        status: Annotated[str | None, typer.Option(help="Only jobs in this status.")] = None,
        server: Server = None,
        config: Config = None,
        as_json: AsJson = False,
    ) -> None:
        with _client(server, config) as (client, _, _url):
            for job in client.pages("/jobs", status=status):
                if as_json:
                    _emit(job)
                else:
                    typer.echo(
                        f"{job['id']}  {job['status']:9}  {job['target']}  {job['original_name']}"
                    )

    @jobs.command("status")
    def jobs_status(  # pyright: ignore[reportUnusedFunction]
        job_id: str, server: Server = None, config: Config = None, as_json: AsJson = False
    ) -> None:
        with _client(server, config) as (client, _, _url):
            job = client.get(f"/jobs/{job_id}")
        if as_json:
            _emit(job)
            return
        progress = (
            f" {job['phase']} {job['progress_done']}/{job['progress_total']}"
            if job["phase"]
            else ""
        )
        typer.echo(f"{job['id']} {job['status']}{progress} {job['original_name']}")
        if job["error_code"]:
            typer.echo(f"error {job['error_code']}: {job['error_message']}")
        if job["document_id"]:
            typer.echo(f"document {job['document_id']} (fit {job['fit_status']})")

    @jobs.command("cancel")
    def jobs_cancel(job_id: str, server: Server = None, config: Config = None) -> None:  # pyright: ignore[reportUnusedFunction]
        with _client(server, config) as (client, _, _url):
            job = client.post(f"/jobs/{job_id}/cancel")
        typer.echo(f"{job['id']} {job['status']}")

    @app.command()
    def download(  # pyright: ignore[reportUnusedFunction]
        output_dir: Annotated[Path, typer.Option("--output-dir", help="Where to save files.")],
        batch: Annotated[
            str | None, typer.Option("--batch", help="All successes of a batch.")
        ] = None,
        document: Annotated[str | None, typer.Option("--document", help="One document.")] = None,
        report: Annotated[bool, typer.Option("--report/--no-report")] = True,
        overwrite: Annotated[bool, typer.Option(help="Replace existing files.")] = False,
        server: Server = None,
        config: Config = None,
    ) -> None:
        """Download translated files (and fit reports) you own."""
        if bool(batch) == bool(document):
            _fail(EXIT_INVALID, "give --batch or --document")
        failures = 0
        with _client(server, config) as (client, _, _url):
            if document:
                doc = client.get(f"/documents/{document}")
                items = [
                    {
                        "id": doc["id"],
                        "original_name": doc["original_name"],
                        "job": {
                            "status": "succeeded",
                            "document_id": doc["id"],
                            "target": doc["target"],
                        },
                    }
                ]
            else:
                items = list(client.pages(f"/batches/{batch}/items"))
            for _, path, error in download_items(
                client, items, output_dir, report=report, overwrite=overwrite, notify=_note
            ):
                if path is not None:
                    typer.echo(str(path))
                if error is not None:
                    failures += 1
        raise typer.Exit(EXIT_ITEMS if failures else EXIT_OK)
