"""Add human password accounts without manufacturing API keys."""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("email", sa.String(254), nullable=True))
    op.add_column("users", sa.Column("password_hash", sa.String(256), nullable=True))
    op.create_index("uq_users_email", "users", ["email"], unique=True)
    with op.batch_alter_table("sessions") as batch:
        batch.alter_column("api_key_id", existing_type=sa.String(36), nullable=True)


def downgrade() -> None:
    op.execute("DELETE FROM sessions WHERE api_key_id IS NULL")
    with op.batch_alter_table("sessions") as batch:
        batch.alter_column("api_key_id", existing_type=sa.String(36), nullable=False)
    op.drop_index("uq_users_email", table_name="users")
    op.drop_column("users", "password_hash")
    op.drop_column("users", "email")
