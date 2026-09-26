# ADR-004: Job Storage

## Status

Accepted (2026-09-26)

## Context

The server runs translations as asynchronous jobs. Job state must survive dropped connections and process restarts ([ADR-001](ADR-001-mcp-server-deployment.md), rule 2), and lives in `doctranslator_server/db/` ([ADR-003](ADR-003-source-structure.md)). The core has no persistence.

Forces:

- **Hosting.** Initially one laptop runs one server process. Later it moves to a shared server, which should be a configuration change, not a redesign.
- **Volume.** Coworkers and agents submitting documents: low write volume, dominated by translation time, not database time.
- **Operations.** No one is available to run and maintain a database server on the laptop.
- **Documents are large binaries.** Uploaded and translated files are megabytes each.

## Options Considered

### Database: SQLite

Pros:
- A single file; nothing to install, run, or keep alive.
- More than enough for this volume on one host.
- Backups are file copies.

Cons:
- One writer at a time. Fine for a single server process; not for multiple server replicas.
- Moving to multiple hosts later requires a client-server database.

### Database: PostgreSQL

Pros:
- Handles concurrent writers and multiple server replicas.

Cons:
- A separate service to install, run, secure, and keep alive on the laptop, with no benefit at current scale.

### Access: SQLAlchemy vs. alternatives

SQLAlchemy 2.0 is the standard Python ORM, with typed models, and it keeps the database engine swappable. SQLModel adds Pydantic integration on top, but blurs the line between ORM classes and API schemas that ADR-003 deliberately keeps separate. Raw SQL gives up typed models and portability for no gain.

### Migrations: Alembic

The standard migration tool for SQLAlchemy, with autogeneration from models and support for SQLite's limited `ALTER TABLE` through batch mode.

## Decision

- **Database:** SQLite, as a single file in the server's configured data directory.
- **ORM:** SQLAlchemy 2.0, typed declarative models (`Mapped[...]`), synchronous sessions.
- **Migrations:** Alembic, in `apps/server/migrations/`.

Rules:

1. **Documents are files, not rows.** Uploaded inputs, translated outputs, rendered page images, and fit reports are stored on disk in the data directory. The database stores job metadata and paths relative to the data directory, never file contents.
2. **All schema changes go through Alembic migrations.** The server never calls `create_all()` outside tests. Migrations use Alembic batch mode so they work on SQLite.
3. **SQLite is configured on every connection:** WAL journal mode (readers don't block the writer) and `foreign_keys=ON`.
4. **No SQLite-specific SQL in application code.** Queries go through SQLAlchemy constructs in `db/repositories/`, so moving to PostgreSQL is a connection URL change plus a migration run.
5. **Synchronous sessions.** SQLite's Python driver is synchronous, and database time is negligible next to translation time; async SQLAlchemy would add complexity for no benefit. FastAPI routes that touch the database run in its thread pool.

## Consequences

- The server runs as a single process against one SQLite file. Running multiple server replicas requires moving to PostgreSQL first, which supersedes this ADR.
- Backing up the server means copying the data directory (database file and document files together) while the server is stopped, or using SQLite's online backup API.
- Stored documents grow without bound unless cleaned up. A retention policy for job files is needed before the server is shared with coworkers.
- Tests can run against a temporary SQLite file or in-memory database, with no external services.
