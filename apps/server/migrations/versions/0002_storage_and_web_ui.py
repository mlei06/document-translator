"""ADR-014 storage and ADR-017 web UI: owned source documents, current translations, immutable
job results, retention modes, progress snapshots, fit skip, job dismissal and browser sessions.

Converts 0001 data without losing results: each old per-job document becomes (or joins) the
owner's source document for those bytes, each job's version 0 becomes its immutable job result,
and the newest result per document and language pair becomes current; older ones get the
superseded-result expiry. The global exact-byte cache is dropped (ADR-014: no cross-owner reuse).

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-29
"""

import json
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SUPERSEDED = timedelta(days=7)


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def upgrade() -> None:
    op.create_table(
        "sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("token_digest", sa.String(length=64), nullable=False),
        sa.Column("csrf_digest", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("api_key_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["api_key_id"], ["api_keys.id"], name=op.f("fk_sessions_api_key_id_api_keys")
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_sessions_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sessions")),
        sa.UniqueConstraint("token_digest", name=op.f("uq_sessions_token_digest")),
    )
    with op.batch_alter_table("sessions") as batch:
        batch.create_index(batch.f("ix_sessions_api_key_id"), ["api_key_id"], unique=False)
        batch.create_index(batch.f("ix_sessions_user_id"), ["user_id"], unique=False)

    op.execute("UPDATE users SET kind = 'human' WHERE kind = 'person'")
    op.execute("UPDATE jobs SET phase = NULL WHERE phase = 'done'")  # 0001 terminal marker

    op.rename_table("documents", "legacy_documents")
    with op.batch_alter_table("legacy_documents") as batch:
        batch.drop_index("ix_documents_original_blob")
        batch.drop_index("ix_documents_owner_id")

    op.create_table(
        "documents",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=36), nullable=False),
        sa.Column("source_blob", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("format", sa.String(length=8), nullable=False),
        sa.Column("detected_source", sa.String(length=8), nullable=True),
        sa.Column("detection", sa.String(length=16), nullable=False),
        sa.Column("external_ref", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name=op.f("fk_documents_owner_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["source_blob"], ["blobs.hash"], name=op.f("fk_documents_source_blob_blobs")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documents")),
    )
    with op.batch_alter_table("documents") as batch:
        batch.create_index(batch.f("ix_documents_owner_id"), ["owner_id"], unique=False)
        batch.create_index(batch.f("ix_documents_source_blob"), ["source_blob"], unique=False)
        batch.create_index("ix_documents_owner_source", ["owner_id", "source_blob"], unique=False)

    op.create_table(
        "job_results",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("output_blob", sa.String(length=64), nullable=False),
        sa.Column("report_blob", sa.String(length=64), nullable=False),
        sa.Column("preview_blob", sa.String(length=64), nullable=True),
        sa.Column("source_resolved", sa.String(length=8), nullable=True),
        sa.Column("fit_status", sa.String(length=32), nullable=False),
        sa.Column("engine", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], name=op.f("fk_job_results_job_id_jobs")),
        sa.ForeignKeyConstraint(
            ["output_blob"], ["blobs.hash"], name=op.f("fk_job_results_output_blob_blobs")
        ),
        sa.ForeignKeyConstraint(
            ["report_blob"], ["blobs.hash"], name=op.f("fk_job_results_report_blob_blobs")
        ),
        sa.ForeignKeyConstraint(
            ["preview_blob"], ["blobs.hash"], name=op.f("fk_job_results_preview_blob_blobs")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_job_results")),
        sa.UniqueConstraint("job_id", name=op.f("uq_job_results_job_id")),
    )
    with op.batch_alter_table("job_results") as batch:
        batch.create_index(batch.f("ix_job_results_output_blob"), ["output_blob"], unique=False)
        batch.create_index(batch.f("ix_job_results_report_blob"), ["report_blob"], unique=False)
        batch.create_index(batch.f("ix_job_results_preview_blob"), ["preview_blob"], unique=False)

    op.create_table(
        "document_translations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("source", sa.String(length=8), nullable=False),
        sa.Column("target", sa.String(length=8), nullable=False),
        sa.Column("current_result_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["current_result_id"],
            ["job_results.id"],
            name=op.f("fk_document_translations_current_result_id_job_results"),
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_document_translations_document_id_documents"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_translations")),
        sa.UniqueConstraint(
            "document_id", "source", "target", name=op.f("uq_document_translations_document_id")
        ),
    )
    with op.batch_alter_table("document_translations") as batch:
        batch.create_index(
            batch.f("ix_document_translations_document_id"), ["document_id"], unique=False
        )
        batch.create_index(
            batch.f("ix_document_translations_current_result_id"),
            ["current_result_id"],
            unique=False,
        )

    bind = op.get_bind()
    old_results = {
        row.id: row.result_id
        for row in bind.execute(
            sa.text("SELECT id, result_id FROM jobs WHERE result_id IS NOT NULL")
        )
    }
    op.execute("UPDATE jobs SET result_id = NULL")  # the column now points at job_results
    with op.batch_alter_table("jobs") as batch:
        batch.add_column(sa.Column("document_id", sa.String(length=36), nullable=True))
        batch.add_column(
            sa.Column("retention", sa.String(length=16), nullable=False, server_default="saved")
        )
        batch.add_column(sa.Column("active_slot", sa.String(length=64), nullable=True))
        batch.add_column(
            sa.Column("fit_skip_requested", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch.add_column(sa.Column("progress_updated_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("dismissed_at", sa.DateTime(), nullable=True))
        batch.alter_column("progress_done", existing_type=sa.Integer(), nullable=True)
        batch.alter_column("progress_total", existing_type=sa.Integer(), nullable=True)
        batch.drop_constraint("fk_jobs_result_id_translation_results", type_="foreignkey")
        batch.create_foreign_key(
            batch.f("fk_jobs_document_id_documents"), "documents", ["document_id"], ["id"]
        )
        batch.create_foreign_key(
            batch.f("fk_jobs_result_id_job_results"),
            "job_results",
            ["result_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_index(batch.f("ix_jobs_document_id"), ["document_id"], unique=False)
        batch.create_unique_constraint(batch.f("uq_jobs_active_slot"), ["active_slot"])

    _convert(old_results)

    with op.batch_alter_table("document_versions") as batch:
        batch.drop_index("ix_document_versions_output_blob")
        batch.drop_index("ix_document_versions_report_blob")
    op.drop_table("document_versions")
    op.drop_table("legacy_documents")
    with op.batch_alter_table("translation_results") as batch:
        batch.drop_index("ix_translation_results_output_blob")
        batch.drop_index("ix_translation_results_report_blob")
    op.drop_table("translation_results")


def _convert(old_results: dict[str, str]) -> None:
    """Move 0001 per-job documents into ADR-014 documents, results and current translations."""
    bind = op.get_bind()
    now = _now()
    engines = {
        row.id: row.engine
        for row in bind.execute(sa.text("SELECT id, engine FROM translation_results"))
    }
    olds = bind.execute(
        sa.text(
            "SELECT d.id, d.owner_id, d.job_id, d.original_name, d.format, d.original_blob, "
            "d.source_resolved, d.target, d.fit_status, d.created_at, j.fingerprint, "
            "b.size, v.output_blob, v.report_blob "
            "FROM legacy_documents d JOIN jobs j ON j.id = d.job_id "
            "JOIN blobs b ON b.hash = d.original_blob "
            "JOIN document_versions v ON v.document_id = d.id AND v.version_no = 0 "
            "ORDER BY d.created_at"
        )
    ).all()
    documents: dict[tuple[str, str], str] = {}
    slots: dict[tuple[str, str, str], list[tuple[datetime, str]]] = {}
    for old in olds:
        key = (old.owner_id, old.original_blob)
        document_id = documents.get(key)
        if document_id is None:
            document_id = str(uuid.uuid4())
            documents[key] = document_id
            bind.execute(
                sa.text(
                    "INSERT INTO documents (id, owner_id, source_blob, name, size, format, "
                    "detected_source, detection, created_at) VALUES (:id, :owner, :blob, :name, "
                    ":size, :format, :source, :detection, :created)"
                ),
                {
                    "id": document_id,
                    "owner": old.owner_id,
                    "blob": old.original_blob,
                    "name": old.original_name,
                    "size": old.size,
                    "format": old.format,
                    "source": old.source_resolved,
                    "detection": "detected" if old.source_resolved else "no_text",
                    "created": old.created_at,
                },
            )
        result_id = str(uuid.uuid4())
        engine = engines.get(old_results.get(old.job_id, "")) or "{}"
        bind.execute(
            sa.text(
                "INSERT INTO job_results (id, job_id, input_hash, fingerprint, output_blob, "
                "report_blob, source_resolved, fit_status, engine, created_at) VALUES (:id, :job, "
                ":input, :fp, :out, :report, :source, :fit, :engine, :created)"
            ),
            {
                "id": result_id,
                "job": old.job_id,
                "input": old.original_blob,
                "fp": old.fingerprint,
                "out": old.output_blob,
                "report": old.report_blob,
                "source": old.source_resolved,
                "fit": old.fit_status,
                "engine": engine if isinstance(engine, str) else json.dumps(engine),
                "created": old.created_at,
            },
        )
        bind.execute(
            sa.text("UPDATE jobs SET result_id = :result, document_id = :doc WHERE id = :job"),
            {"result": result_id, "doc": document_id, "job": old.job_id},
        )
        slot = (document_id, old.source_resolved or "", old.target)
        slots.setdefault(slot, []).append((old.created_at, result_id))
    for (document_id, source, target), results in slots.items():
        results.sort()
        *older, (created, current) = results
        bind.execute(
            sa.text(
                "INSERT INTO document_translations (id, document_id, source, target, "
                "current_result_id, created_at, updated_at) VALUES (:id, :doc, :source, :target, "
                ":current, :created, :created)"
            ),
            {
                "id": str(uuid.uuid4()),
                "doc": document_id,
                "source": source,
                "target": target,
                "current": current,
                "created": created,
            },
        )
        for _, result_id in older:
            bind.execute(
                sa.text("UPDATE job_results SET expires_at = :at WHERE id = :id"),
                {"at": (now + SUPERSEDED).strftime("%Y-%m-%d %H:%M:%S.%f"), "id": result_id},
            )


def downgrade() -> None:
    raise NotImplementedError("0002 converts storage (ADR-014); restore a backup to go back")
