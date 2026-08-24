"""Identify publications by canonical_url/external_id, not content_hash.

Revision ID: 0003_source_item_identity
Revises: 0002_event_embeddings
Create Date: 2026-08-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "0003_source_item_identity"
down_revision: str | None = "0002_event_embeddings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    unique_names = {item["name"] for item in inspector.get_unique_constraints("source_items")}
    index_names = {item["name"] for item in inspector.get_indexes("source_items")}
    if "uq_source_items_source_id_content_hash" in unique_names:
        op.drop_constraint("uq_source_items_source_id_content_hash", "source_items", type_="unique")
    if "uq_source_items_source_id_content_hash" in index_names:
        op.drop_index("uq_source_items_source_id_content_hash", table_name="source_items")
    if "uq_source_items_source_id_canonical_url" not in index_names:
        op.create_index(
            "uq_source_items_source_id_canonical_url",
            "source_items",
            ["source_id", "canonical_url"],
            unique=True,
            postgresql_where=sa.text("canonical_url IS NOT NULL"),
        )
    if "uq_source_items_source_id_external_id" not in index_names:
        op.create_index(
            "uq_source_items_source_id_external_id",
            "source_items",
            ["source_id", "external_id"],
            unique=True,
            postgresql_where=sa.text("external_id IS NOT NULL"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    index_names = {item["name"] for item in inspector.get_indexes("source_items")}
    unique_names = {item["name"] for item in inspector.get_unique_constraints("source_items")}
    if "uq_source_items_source_id_canonical_url" in index_names:
        op.drop_index("uq_source_items_source_id_canonical_url", table_name="source_items")
    if "uq_source_items_source_id_content_hash" not in unique_names:
        op.create_unique_constraint(
            "uq_source_items_source_id_content_hash",
            "source_items",
            ["source_id", "content_hash"],
        )
