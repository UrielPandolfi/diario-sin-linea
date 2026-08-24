"""Add event_embeddings if the table is missing.

Revision ID: 0002_event_embeddings
Revises: 0001_foundation
Create Date: 2026-08-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "0002_event_embeddings"
down_revision: str | None = "0001_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "event_embeddings" not in inspector.get_table_names():
        op.execute(
            sa.text(
                """
                -- 1024 is the schema contract, not EMBEDDING_DIMENSIONS from the environment.
                -- No HNSW/IVF: the MVP volume does not need an ANN index.
                CREATE TABLE event_embeddings (
                    id UUID PRIMARY KEY,
                    event_id UUID NOT NULL UNIQUE REFERENCES events(id) ON DELETE CASCADE,
                    embedding vector(1024) NOT NULL,
                    model VARCHAR(128) NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
        )
        op.create_index("ix_event_embeddings_event_id", "event_embeddings", ["event_id"], unique=True)

    # Drop ANN indexes if a previous revision created them. Linear scan is enough.
    ann_indexes = bind.execute(
        sa.text(
            """
            SELECT indexname
            FROM pg_indexes
            WHERE tablename = 'event_embeddings'
              AND (indexdef ILIKE '%hnsw%' OR indexdef ILIKE '%ivfflat%')
            """
        )
    ).fetchall()
    for row in ann_indexes:
        op.drop_index(row[0], table_name="event_embeddings")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "event_embeddings" not in inspector.get_table_names():
        return
    op.drop_index("ix_event_embeddings_event_id", table_name="event_embeddings")
    op.drop_table("event_embeddings")
