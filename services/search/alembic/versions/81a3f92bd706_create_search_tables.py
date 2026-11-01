"""Create Search service tables.

Revision ID: 81a3f92bd706
Revises:
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "81a3f92bd706"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "search_document",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("doc_type", sa.String(20), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("thread_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("author_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("author_username", sa.String(30), nullable=False),
        sa.Column("thread_title", sa.String(200), nullable=False),
        sa.Column("title", sa.String(200), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("tags", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("doc_type", "source_id", name="uq_search_document_type_source"),
        sa.CheckConstraint("doc_type IN ('thread', 'comment')", name="ck_search_document_type"),
    )
    op.create_table(
        "processed_event",
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("consumer", sa.String(100), nullable=False),
        sa.PrimaryKeyConstraint("event_id", "consumer"),
    )


def downgrade() -> None:
    op.drop_table("processed_event")
    op.drop_table("search_document")
