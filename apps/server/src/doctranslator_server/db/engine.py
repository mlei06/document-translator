"""Engine, sessions and migrations (ADR-004): WAL, foreign keys and a busy timeout on SQLite."""

import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

__all__ = [
    "BUSY_TIMEOUT_MS",
    "Database",
    "MigrationRequiredError",
]

BUSY_TIMEOUT_MS = 5000
MIGRATIONS = Path(__file__).resolve().parents[3] / "migrations"
"""``apps/server/migrations`` (ADR-004)."""


class MigrationRequiredError(Exception):
    """The database is not at the current schema revision; run ``doctranslator-server migrate``."""


def _sqlite_pragmas(dbapi_connection: Any, _record: Any) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    cursor.close()


def _sqlite_autocommit(dbapi_connection: Any, _record: Any) -> None:
    dbapi_connection.isolation_level = None


def _sqlite_begin(conn: Any) -> None:
    # pysqlite's implicit transactions are disabled below; every transaction takes the write
    # lock up front, so a read-then-write transaction never fails on lock upgrade.
    conn.exec_driver_sql("BEGIN IMMEDIATE")


class Database:
    """One engine and session factory per process."""

    def __init__(self, url: str) -> None:
        self.url = url
        if url.startswith("sqlite"):
            path = url.removeprefix("sqlite:///")
            if path and path != ":memory:":
                Path(path).parent.mkdir(parents=True, exist_ok=True)
            self.engine: Engine = create_engine(
                url,
                connect_args={"timeout": BUSY_TIMEOUT_MS / 1000, "check_same_thread": False},
            )
            event.listen(self.engine, "connect", _sqlite_pragmas)
            event.listen(self.engine, "connect", _sqlite_autocommit)
            event.listen(self.engine, "begin", _sqlite_begin)
        else:
            self.engine = create_engine(url)
        self._sessions = sessionmaker(self.engine, expire_on_commit=False)

    @contextmanager
    def session(self) -> Generator[Session]:
        """A session whose transaction commits on success and rolls back on error."""
        session = self._sessions()
        try:
            with session.begin():
                yield session
        finally:
            session.close()

    def dispose(self) -> None:
        self.engine.dispose()

    def snapshot(self, destination: Path) -> None:
        """A consistent copy of a SQLite database (online backup API), safe while in use."""
        if not self.url.startswith("sqlite"):
            raise NotImplementedError("snapshots are implemented for SQLite only")
        raw = self.engine.raw_connection()
        try:
            source = cast(sqlite3.Connection, raw.driver_connection)
            target = sqlite3.connect(destination)
            try:
                source.backup(target)
            finally:
                target.close()
        finally:
            raw.close()

    # Migrations

    def _alembic(self) -> Config:
        config = Config()
        config.set_main_option("script_location", str(MIGRATIONS))
        config.set_main_option("sqlalchemy.url", self.url)
        config.attributes["engine"] = self.engine
        return config

    def migrate(self, revision: str = "head") -> None:
        command.upgrade(self._alembic(), revision)

    def current_revision(self) -> str | None:
        with self.engine.connect() as conn:
            return MigrationContext.configure(conn).get_current_revision()

    def head_revision(self) -> str | None:
        return ScriptDirectory.from_config(self._alembic()).get_current_head()

    def require_current(self) -> None:
        if self.current_revision() != self.head_revision():
            raise MigrationRequiredError(
                "the database schema is not current; run `doctranslator-server migrate`"
            )
