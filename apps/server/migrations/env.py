"""Alembic environment: migrations run through ``Database.migrate`` (ADR-004), in batch mode."""

from alembic import context
from sqlalchemy import Engine

from doctranslator_server.db.models import Base

config = context.config
engine: Engine = config.attributes["engine"]

with engine.connect() as connection:
    context.configure(
        connection=connection,
        target_metadata=Base.metadata,
        render_as_batch=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()
    connection.commit()
