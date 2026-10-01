"""Page rendering after publication (ADR-023): per-result render state and page images."""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("job_results") as batch:
        batch.add_column(sa.Column("pages_status", sa.String(length=16), nullable=True))
        batch.add_column(sa.Column("pages_blob", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("pages_token", sa.String(length=32), nullable=True))
        batch.add_column(sa.Column("pages_lease_until", sa.DateTime(), nullable=True))
        batch.add_column(
            sa.Column("pages_attempts", sa.Integer(), nullable=False, server_default="0")
        )
        batch.create_foreign_key(
            batch.f("fk_job_results_pages_blob_blobs"), "blobs", ["pages_blob"], ["hash"]
        )
        batch.create_index(batch.f("ix_job_results_pages_blob"), ["pages_blob"], unique=False)
        batch.create_index(batch.f("ix_job_results_pages_status"), ["pages_status"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("job_results") as batch:
        batch.drop_index(batch.f("ix_job_results_pages_status"))
        batch.drop_index(batch.f("ix_job_results_pages_blob"))
        batch.drop_constraint(batch.f("fk_job_results_pages_blob_blobs"), type_="foreignkey")
        batch.drop_column("pages_attempts")
        batch.drop_column("pages_lease_until")
        batch.drop_column("pages_token")
        batch.drop_column("pages_blob")
        batch.drop_column("pages_status")
