"""Shared automatic work, private verified grants and bounded staging."""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("job_results") as batch:
        batch.drop_index("ix_job_results_preview_blob")
        batch.drop_index("ix_job_results_pages_blob")
        batch.drop_index("ix_job_results_pages_status")
        batch.drop_constraint("fk_job_results_preview_blob_blobs", type_="foreignkey")
        batch.drop_constraint("fk_job_results_pages_blob_blobs", type_="foreignkey")
        for column in (
            "preview_blob",
            "pages_status",
            "pages_blob",
            "pages_token",
            "pages_lease_until",
            "pages_attempts",
        ):
            batch.drop_column(column)
    with op.batch_alter_table("documents") as batch:
        batch.drop_constraint("fk_documents_source_blob_blobs", type_="foreignkey")
        batch.add_column(sa.Column("staging_expires_at", sa.DateTime(), nullable=True))
    with op.batch_alter_table("jobs") as batch:
        batch.drop_constraint("fk_jobs_input_blob_blobs", type_="foreignkey")
        batch.add_column(sa.Column("shared_work_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("history_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("policy", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("rung", sa.Integer(), nullable=False, server_default="0"))
        batch.create_index("ix_jobs_shared_work_id", ["shared_work_id"])
        batch.create_index("ix_jobs_history_id", ["history_id"])
    op.create_table(
        "shared_slots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("target", sa.String(8), nullable=False),
        sa.Column("current_result_id", sa.String(36)),
        sa.Column("active_work_id", sa.String(36)),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("profile", sa.String(64)),
        sa.Column("producer", sa.String(64)),
        sa.Column("producer_fingerprint", sa.String(64)),
        sa.Column("last_used_at", sa.DateTime(), nullable=False),
        sa.Column("cooldowns", sa.JSON(), nullable=False),
        sa.UniqueConstraint("source_hash", "target"),
    )
    op.create_table(
        "history_grants",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("slot_id", sa.String(36), sa.ForeignKey("shared_slots.id"), nullable=False),
        sa.Column("original_name", sa.String(255), nullable=False),
        sa.Column("format", sa.String(8), nullable=False),
        sa.Column("source", sa.String(8)),
        sa.Column("detection", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_at", sa.DateTime()),
        sa.UniqueConstraint("owner_id", "slot_id"),
    )
    op.create_index("ix_history_grants_owner_id", "history_grants", ["owner_id"])
    op.create_index("ix_history_grants_slot_id", "history_grants", ["slot_id"])
    op.create_table(
        "storage_reservations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(36), nullable=False),
        sa.Column("purpose", sa.String(16), nullable=False),
        sa.Column("bytes", sa.BigInteger(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_storage_reservations_owner_id", "storage_reservations", ["owner_id"])


def downgrade() -> None:
    raise RuntimeError("Clean-slate schema: initialize a new development database instead")
