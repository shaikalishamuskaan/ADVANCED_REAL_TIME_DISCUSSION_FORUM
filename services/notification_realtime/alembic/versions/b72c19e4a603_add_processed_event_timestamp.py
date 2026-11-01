"""Add a timestamp for processed-event retention.

Revision ID: b72c19e4a603
Revises: 3406b4793c5c
"""

from alembic import op
import sqlalchemy as sa

revision = "b72c19e4a603"
down_revision = "3406b4793c5c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # PostgreSQL fills legacy rows with the migration's transaction timestamp.
    # Their original processing time is unknown, so retain them for 14 more days.
    op.add_column(
        "processed_event",
        sa.Column(
            "processed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("processed_event", "processed_at")
