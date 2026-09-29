"""Initial schema: users, keys, blobs, cache, batches, jobs, documents, audit, locks.

Revision ID: 0001
Revises:
Create Date: 2026-09-29 00:27:50.757072
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("at", sa.DateTime(), nullable=False),
        sa.Column("actor_user_id", sa.String(length=36), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=True),
        sa.Column("target_id", sa.String(length=64), nullable=True),
        sa.Column("outcome", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_events")),
    )
    with op.batch_alter_table("audit_events", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_audit_events_at"), ["at"], unique=False)

    op.create_table(
        "blobs",
        sa.Column("hash", sa.String(length=64), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("hash", name=op.f("pk_blobs")),
    )
    op.create_table(
        "locks",
        sa.Column("name", sa.String(length=32), nullable=False),
        sa.Column("holder", sa.String(length=64), nullable=False),
        sa.Column("until", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("name", name=op.f("pk_locks")),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("issuer", sa.String(length=300), nullable=True),
        sa.Column("subject", sa.String(length=300), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("disabled_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("issuer", "subject", name=op.f("uq_users_issuer")),
    )
    op.create_table(
        "api_keys",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("prefix", sa.String(length=16), nullable=False),
        sa.Column("digest", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_api_keys_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_api_keys")),
        sa.UniqueConstraint("prefix", name=op.f("uq_api_keys_prefix")),
    )
    with op.batch_alter_table("api_keys", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_api_keys_user_id"), ["user_id"], unique=False)

    op.create_table(
        "batches",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=36), nullable=False),
        sa.Column("idempotency_key", sa.String(length=36), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("next_ordinal", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("sealed_at", sa.DateTime(), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], name=op.f("fk_batches_owner_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_batches")),
        sa.UniqueConstraint("owner_id", "idempotency_key", name=op.f("uq_batches_owner_id")),
    )
    with op.batch_alter_table("batches", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_batches_owner_id"), ["owner_id"], unique=False)

    op.create_table(
        "blob_pins",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["hash"], ["blobs.hash"], name=op.f("fk_blob_pins_hash_blobs")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_blob_pins")),
    )
    with op.batch_alter_table("blob_pins", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_blob_pins_hash"), ["hash"], unique=False)

    op.create_table(
        "translation_results",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("output_blob", sa.String(length=64), nullable=False),
        sa.Column("report_blob", sa.String(length=64), nullable=False),
        sa.Column("source_resolved", sa.String(length=8), nullable=True),
        sa.Column("fit_status", sa.String(length=32), nullable=False),
        sa.Column("engine", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["output_blob"], ["blobs.hash"], name=op.f("fk_translation_results_output_blob_blobs")
        ),
        sa.ForeignKeyConstraint(
            ["report_blob"], ["blobs.hash"], name=op.f("fk_translation_results_report_blob_blobs")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_translation_results")),
        sa.UniqueConstraint(
            "input_hash", "fingerprint", name=op.f("uq_translation_results_input_hash")
        ),
    )
    with op.batch_alter_table("translation_results", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_translation_results_output_blob"), ["output_blob"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_translation_results_report_blob"), ["report_blob"], unique=False
        )

    op.create_table(
        "jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=36), nullable=False),
        sa.Column("batch_id", sa.String(length=36), nullable=True),
        sa.Column("submission_id", sa.String(length=36), nullable=True),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("original_name", sa.String(length=255), nullable=False),
        sa.Column("format", sa.String(length=8), nullable=False),
        sa.Column("input_blob", sa.String(length=64), nullable=False),
        sa.Column("input_size", sa.BigInteger(), nullable=False),
        sa.Column("options", sa.JSON(), nullable=False),
        sa.Column("mode", sa.String(length=8), nullable=False),
        sa.Column("source_requested", sa.String(length=8), nullable=False),
        sa.Column("source_resolved", sa.String(length=8), nullable=True),
        sa.Column("target", sa.String(length=8), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("force", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(), nullable=False),
        sa.Column("claim_token", sa.String(length=32), nullable=True),
        sa.Column("worker_id", sa.String(length=64), nullable=True),
        sa.Column("lease_until", sa.DateTime(), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(), nullable=True),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False),
        sa.Column("phase", sa.String(length=16), nullable=True),
        sa.Column("progress_done", sa.Integer(), nullable=False),
        sa.Column("progress_total", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("cache_hit", sa.Boolean(), nullable=False),
        sa.Column("result_id", sa.String(length=36), nullable=True),
        sa.Column("fit_status", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["batch_id"], ["batches.id"], name=op.f("fk_jobs_batch_id_batches")
        ),
        sa.ForeignKeyConstraint(
            ["input_blob"], ["blobs.hash"], name=op.f("fk_jobs_input_blob_blobs")
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], name=op.f("fk_jobs_owner_id_users")),
        sa.ForeignKeyConstraint(
            ["result_id"],
            ["translation_results.id"],
            name=op.f("fk_jobs_result_id_translation_results"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jobs")),
        sa.UniqueConstraint("owner_id", "submission_id", name=op.f("uq_jobs_owner_id")),
    )
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_jobs_batch_id"), ["batch_id"], unique=False)
        batch_op.create_index(
            "ix_jobs_claim", ["status", "available_at", "created_at"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_jobs_input_blob"), ["input_blob"], unique=False)
        batch_op.create_index(batch_op.f("ix_jobs_owner_id"), ["owner_id"], unique=False)

    op.create_table(
        "batch_items",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("batch_id", sa.String(length=36), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("client_item_id", sa.String(length=36), nullable=False),
        sa.Column("original_name", sa.String(length=255), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=True),
        sa.Column("rejection_code", sa.String(length=64), nullable=True),
        sa.Column("rejection_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["batch_id"], ["batches.id"], name=op.f("fk_batch_items_batch_id_batches")
        ),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], name=op.f("fk_batch_items_job_id_jobs")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_batch_items")),
        sa.UniqueConstraint("batch_id", "client_item_id", name=op.f("uq_batch_items_batch_id")),
        sa.UniqueConstraint("batch_id", "ordinal", name=op.f("uq_batch_items_batch_id")),
    )
    with op.batch_alter_table("batch_items", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_batch_items_batch_id"), ["batch_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_batch_items_job_id"), ["job_id"], unique=False)

    op.create_table(
        "documents",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("original_name", sa.String(length=255), nullable=False),
        sa.Column("format", sa.String(length=8), nullable=False),
        sa.Column("original_blob", sa.String(length=64), nullable=False),
        sa.Column("source_requested", sa.String(length=8), nullable=False),
        sa.Column("source_resolved", sa.String(length=8), nullable=True),
        sa.Column("target", sa.String(length=8), nullable=False),
        sa.Column("mode", sa.String(length=8), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("result_id", sa.String(length=36), nullable=True),
        sa.Column("fit_status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], name=op.f("fk_documents_job_id_jobs")),
        sa.ForeignKeyConstraint(
            ["original_blob"], ["blobs.hash"], name=op.f("fk_documents_original_blob_blobs")
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name=op.f("fk_documents_owner_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["result_id"],
            ["translation_results.id"],
            name=op.f("fk_documents_result_id_translation_results"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documents")),
        sa.UniqueConstraint("job_id", name=op.f("uq_documents_job_id")),
    )
    with op.batch_alter_table("documents", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_documents_original_blob"), ["original_blob"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_documents_owner_id"), ["owner_id"], unique=False)

    op.create_table(
        "document_versions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("output_blob", sa.String(length=64), nullable=False),
        sa.Column("report_blob", sa.String(length=64), nullable=False),
        sa.Column("parent_version_id", sa.String(length=36), nullable=True),
        sa.Column("created_by", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_document_versions_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["output_blob"], ["blobs.hash"], name=op.f("fk_document_versions_output_blob_blobs")
        ),
        sa.ForeignKeyConstraint(
            ["parent_version_id"],
            ["document_versions.id"],
            name=op.f("fk_document_versions_parent_version_id_document_versions"),
        ),
        sa.ForeignKeyConstraint(
            ["report_blob"], ["blobs.hash"], name=op.f("fk_document_versions_report_blob_blobs")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_versions")),
        sa.UniqueConstraint(
            "document_id", "version_no", name=op.f("uq_document_versions_document_id")
        ),
    )
    with op.batch_alter_table("document_versions", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_document_versions_output_blob"), ["output_blob"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_document_versions_report_blob"), ["report_blob"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("document_versions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_document_versions_report_blob"))
        batch_op.drop_index(batch_op.f("ix_document_versions_output_blob"))

    op.drop_table("document_versions")
    with op.batch_alter_table("documents", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_documents_owner_id"))
        batch_op.drop_index(batch_op.f("ix_documents_original_blob"))

    op.drop_table("documents")
    with op.batch_alter_table("batch_items", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_batch_items_job_id"))
        batch_op.drop_index(batch_op.f("ix_batch_items_batch_id"))

    op.drop_table("batch_items")
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_jobs_owner_id"))
        batch_op.drop_index(batch_op.f("ix_jobs_input_blob"))
        batch_op.drop_index("ix_jobs_claim")
        batch_op.drop_index(batch_op.f("ix_jobs_batch_id"))

    op.drop_table("jobs")
    with op.batch_alter_table("translation_results", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_translation_results_report_blob"))
        batch_op.drop_index(batch_op.f("ix_translation_results_output_blob"))

    op.drop_table("translation_results")
    with op.batch_alter_table("blob_pins", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_blob_pins_hash"))

    op.drop_table("blob_pins")
    with op.batch_alter_table("batches", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_batches_owner_id"))

    op.drop_table("batches")
    with op.batch_alter_table("api_keys", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_api_keys_user_id"))

    op.drop_table("api_keys")
    op.drop_table("users")
    op.drop_table("locks")
    op.drop_table("blobs")
    with op.batch_alter_table("audit_events", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_audit_events_at"))

    op.drop_table("audit_events")
    # ### end Alembic commands ###
