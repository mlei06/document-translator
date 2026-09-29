"""Alembic environment: migrations run through ``Database.migrate`` (ADR-004), in batch mode.

On SQLite, batch mode rebuilds tables, which foreign keys referencing them would block. Foreign
keys are switched off for the migration connection only, and ``foreign_key_check`` must report
no violations before the migration commits, so integrity is still proven.
"""

from alembic import context
from sqlalchemy import Engine, text

from doctranslator_server.db.models import Base

config = context.config
engine: Engine = config.attributes["engine"]

with engine.connect() as connection:
    sqlite = connection.dialect.name == "sqlite"
    if sqlite:
        # Before any transaction starts: the pragma is ignored inside one.
        connection.connection.driver_connection.execute("PRAGMA foreign_keys=OFF")  # type: ignore[union-attr]
    context.configure(
        connection=connection,
        target_metadata=Base.metadata,
        render_as_batch=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()
        if sqlite:
            violations = connection.execute(text("PRAGMA foreign_key_check")).all()
            if violations:
                raise RuntimeError(f"migration left {len(violations)} foreign key violations")
    connection.commit()
    if sqlite:
        connection.connection.driver_connection.execute("PRAGMA foreign_keys=ON")  # type: ignore[union-attr]
