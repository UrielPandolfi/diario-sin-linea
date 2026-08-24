"""Enable pgvector and create core domain tables.

Revision ID: 0001_foundation
Revises:
Create Date: 2026-08-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

from app.models import Base

revision: str = "0001_foundation"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)
    inspector = inspect(bind)
    source_item_indexes = {item["name"] for item in inspector.get_indexes("source_items")}
    source_indexes = {item["name"] for item in inspector.get_indexes("sources")}
    if "uq_source_items_source_id_external_id" not in source_item_indexes:
        op.create_index(
            "uq_source_items_source_id_external_id",
            "source_items",
            ["source_id", "external_id"],
            unique=True,
            postgresql_where=sa.text("external_id IS NOT NULL"),
        )
    if "ix_sources_pollable" not in source_indexes:
        op.create_index(
            "ix_sources_pollable",
            "sources",
            ["is_monitored", "is_enabled"],
        )


def downgrade() -> None:
    op.drop_index("ix_sources_pollable", table_name="sources")
    op.drop_index("uq_source_items_source_id_external_id", table_name="source_items")
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
    op.execute(sa.text("DROP EXTENSION IF EXISTS vector"))
