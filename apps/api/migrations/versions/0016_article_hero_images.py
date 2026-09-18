"""Deterministic article hero images stored as PNG bytes.

Revision ID: 0016_article_hero_images
Revises: 0015_app_settings
Create Date: 2026-09-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision: str = "0016_article_hero_images"
down_revision: str | None = "0015_app_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "article_hero_images" in inspector.get_table_names():
        return
    op.create_table(
        "article_hero_images",
        sa.Column("article_id", PGUUID(), nullable=False),
        sa.Column("png_bytes", sa.LargeBinary(), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("content_type", sa.String(length=64), nullable=False, server_default="image/png"),
        sa.Column("width", sa.Integer(), nullable=False, server_default="1200"),
        sa.Column("height", sa.Integer(), nullable=False, server_default="630"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["article_id"],
            ["articles.id"],
            ondelete="CASCADE",
            name="fk_article_hero_images_article_id_articles",
        ),
        sa.PrimaryKeyConstraint("article_id", name="pk_article_hero_images"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "article_hero_images" in inspector.get_table_names():
        op.drop_table("article_hero_images")
