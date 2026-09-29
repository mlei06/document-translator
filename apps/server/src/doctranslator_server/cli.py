"""``doctranslator-server``: migrate, serve, worker, user/key administration and operations.

Builds settings and delegates to ``app``, ``auth`` and ``jobs``; it never imports ``db``
(ADR-008). Secrets are printed only once, when a key is created.
"""

import logging
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Annotated

import typer

from doctranslator_server import auth
from doctranslator_server.app import (
    Admin,
    Services,
    build_services,
    create_app,
    migrate,
    open_admin,
)
from doctranslator_server.jobs.backup import BackupError, backup, restore
from doctranslator_server.jobs.engines import EngineCatalog
from doctranslator_server.jobs.retention import run_retention
from doctranslator_server.jobs.service import cancel_user_jobs
from doctranslator_server.jobs.worker import Worker, worker_identity
from doctranslator_server.settings import ServerSettings, SettingsError, load_settings

__all__ = ["app", "main"]

logger = logging.getLogger("doctranslator_server")

app = typer.Typer(
    name="doctranslator-server",
    help="Document Translator service: REST API, workers and administration.",
    no_args_is_help=True,
    add_completion=False,
)
users_app = typer.Typer(help="Manage users (ADR-015).", no_args_is_help=True)
keys_app = typer.Typer(help="Manage API keys (ADR-015).", no_args_is_help=True)
retention_app = typer.Typer(help="Retention and storage cleanup (ADR-016).", no_args_is_help=True)
app.add_typer(users_app, name="users")
app.add_typer(keys_app, name="keys")
app.add_typer(retention_app, name="retention")

EnvFile = Annotated[
    Path | None, typer.Option("--env-file", help="Settings file (default: ./.env if present).")
]

_state: dict[str, Path | None] = {"env_file": None}


@app.callback()
def _root(env_file: EnvFile = None) -> None:
    _state["env_file"] = env_file


def _settings() -> ServerSettings:
    try:
        return load_settings(_state["env_file"])
    except SettingsError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from None


def _services(settings: ServerSettings) -> Services:
    try:
        return build_services(settings)
    except Exception as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from None


def _admin(settings: ServerSettings) -> Admin:
    try:
        return open_admin(settings)
    except Exception as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from None


def _logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    logging.getLogger("fontTools").setLevel(logging.ERROR)


@app.command(name="migrate")
def migrate_command() -> None:
    """Create or upgrade the database schema. Run before the first start and after upgrades."""
    revision = migrate(_settings())
    typer.echo(f"database at revision {revision}")


@app.command()
def serve(
    workers: Annotated[
        int | None, typer.Option(help="Worker processes to supervise (default: settings).")
    ] = None,
    retention: Annotated[
        bool, typer.Option("--retention/--no-retention", help="Run retention hourly.")
    ] = True,
) -> None:
    """Run the REST API and supervise worker processes (ADR-016)."""
    import uvicorn

    _logging()
    settings = _settings()
    try:
        settings.check_network()
    except SettingsError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from None
    services = _services(settings)
    stop = threading.Event()
    count = settings.workers if workers is None else workers
    supervisors = [
        threading.Thread(target=_supervise, args=(index, stop), daemon=True)
        for index in range(count)
    ]
    for thread in supervisors:
        thread.start()
    if retention:
        threading.Thread(
            target=_retention_loop, args=(services, stop), name="retention", daemon=True
        ).start()
    try:
        uvicorn.run(
            create_app(services),
            host=settings.server_host,
            port=settings.server_port,
            ssl_certfile=settings.server_tls_cert,
            ssl_keyfile=settings.server_tls_key,
            log_level="info",
            proxy_headers=settings.server_behind_proxy,
        )
    finally:
        stop.set()
        for thread in supervisors:
            thread.join(timeout=45)
        services.close()


def _supervise(index: int, stop: threading.Event) -> None:
    """Keep one worker subprocess running, restarting it after a crash with backoff."""
    backoff = 5.0
    command = [sys.executable, "-m", "doctranslator_server.cli"]
    if _state["env_file"] is not None:
        command += ["--env-file", str(_state["env_file"])]
    command.append("worker")
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    while not stop.is_set():
        started = time.monotonic()
        process = subprocess.Popen(command, creationflags=flags)  # noqa: S603 - our own module
        logger.info("worker %d started (pid %d)", index, process.pid)
        while process.poll() is None and not stop.is_set():
            stop.wait(1.0)
        if stop.is_set():
            _stop_process(process)
            return
        logger.warning(
            "worker %d exited with %s; restarting in %.0f s", index, process.returncode, backoff
        )
        if time.monotonic() - started > 300:
            backoff = 5.0
        stop.wait(backoff)
        backoff = min(backoff * 2, 60.0)


def _stop_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGTERM)
    try:
        process.wait(timeout=40)
    except subprocess.TimeoutExpired:
        process.kill()  # an abandoned job is recovered when its lease expires


def _retention_loop(services: Services, stop: threading.Event) -> None:
    holder = f"serve:{worker_identity()}"
    while not stop.wait(3600):
        try:
            run_retention(services.settings, services.db, services.store, holder=holder)
        except Exception:
            logger.exception("retention failed")


@app.command()
def worker() -> None:
    """Run one worker: claim and translate jobs until stopped (CTRL+C / CTRL+BREAK / SIGTERM)."""
    _logging()
    settings = _settings()
    services = _services(settings)
    stop = threading.Event()

    def request_stop(_signum: int, _frame: object) -> None:
        logger.info("stop requested; finishing the current job")
        stop.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    if os.name == "nt":
        signal.signal(signal.SIGBREAK, request_stop)
    try:
        catalog = services.catalog
        if not isinstance(catalog, EngineCatalog):  # pragma: no cover - production wiring
            raise TypeError("the worker needs the engine catalog")
        Worker.from_catalog(settings, services.db, services.store, services.queue(), catalog).run(
            stop
        )
    finally:
        services.close()


# Users and keys


@users_app.command("create")
def users_create(
    display_name: str,
    kind: Annotated[str, typer.Option(help="person or service")] = "person",
) -> None:
    """Create a user and print its ID."""
    services = _admin(_settings())
    try:
        user = auth.create_user(services.db, display_name, kind)
    finally:
        services.close()
    typer.echo(user.id)


@users_app.command("list")
def users_list() -> None:
    services = _admin(_settings())
    try:
        for user in auth.list_users(services.db):
            state = "active" if user.active else "disabled"
            typer.echo(f"{user.id}  {state:8}  {user.kind:7}  {user.display_name}")
    finally:
        services.close()


@users_app.command("disable")
def users_disable(user_id: str) -> None:
    """Block the user's keys at once and cancel their unfinished jobs."""
    services = _admin(_settings())
    try:
        auth.set_user_active(services.db, user_id, active=False)
        cancelled = cancel_user_jobs(services.db, user_id)
    except auth.UserNotFoundError:
        typer.echo("error: no such user", err=True)
        raise typer.Exit(2) from None
    finally:
        services.close()
    typer.echo(f"disabled; cancellation requested for {cancelled} jobs")


@users_app.command("enable")
def users_enable(user_id: str) -> None:
    services = _admin(_settings())
    try:
        auth.set_user_active(services.db, user_id, active=True)
    except auth.UserNotFoundError:
        typer.echo("error: no such user", err=True)
        raise typer.Exit(2) from None
    finally:
        services.close()
    typer.echo("enabled")


@keys_app.command("create")
def keys_create(
    user_id: str, label: Annotated[str, typer.Option(help="Where the key is used.")] = ""
) -> None:
    """Issue a key. The secret is printed once; deliver it privately and never commit it."""
    services = _admin(_settings())
    try:
        issued = auth.create_key(services.db, user_id, label)
    except auth.UserNotFoundError:
        typer.echo("error: no such user", err=True)
        raise typer.Exit(2) from None
    finally:
        services.close()
    typer.echo(f"key id: {issued.info.id}", err=True)
    typer.echo(issued.secret)


@keys_app.command("list")
def keys_list(user_id: str) -> None:
    services = _admin(_settings())
    try:
        for key in auth.list_keys(services.db, user_id):
            state = "revoked" if key.revoked_at else "active"
            used = key.last_used_at.isoformat() if key.last_used_at else "never"
            typer.echo(f"{key.id}  dt_{key.prefix}_...  {state:7}  last used {used}  {key.label}")
    finally:
        services.close()


@keys_app.command("revoke")
def keys_revoke(key_id: str) -> None:
    services = _admin(_settings())
    try:
        revoked = auth.revoke_key(services.db, key_id)
    finally:
        services.close()
    typer.echo("revoked" if revoked else "not found or already revoked")


# Operations


@retention_app.command("run")
def retention_run() -> None:
    """Expire documents, cache entries and old jobs, then delete unreferenced blobs."""
    _logging()
    services = _admin(_settings())
    try:
        report = run_retention(
            services.settings, services.db, services.store, holder=f"cli:{worker_identity()}"
        )
    finally:
        services.close()
    typer.echo(
        f"documents {report.documents}, cache entries {report.cache_entries}, jobs {report.jobs}, "
        f"batches {report.batches}, blobs {report.blobs}, staging files {report.staging_files}"
    )


@app.command(name="backup")
def backup_command(destination: Path) -> None:
    """Back up the database and every referenced blob into an empty directory."""
    services = _admin(_settings())
    try:
        summary = backup(
            services.db, services.store, destination, holder=f"backup:{worker_identity()}"
        )
    except BackupError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from None
    finally:
        services.close()
    typer.echo(
        f"backed up revision {summary.revision}: {summary.blobs} blobs, {summary.bytes} bytes"
    )


@app.command(name="restore")
def restore_command(source: Path) -> None:
    """Verify a backup and restore it into the configured (empty) data directory."""
    settings = _settings()
    if settings.database_url:
        typer.echo("error: restore supports the default SQLite database only", err=True)
        raise typer.Exit(2)
    try:
        summary = restore(source, settings.data_dir)
    except BackupError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from None
    typer.echo(f"restored revision {summary.revision}: {summary.blobs} blobs verified")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
