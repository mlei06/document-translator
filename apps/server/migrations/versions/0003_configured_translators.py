"""Pin the selected configured translator on each job."""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("translator_id", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "translator_id")
