"""Add body_blocks JSONB to articles and article_versions.

Revision ID: 0012_article_body_blocks
Revises: 0011_llm_usage_duration
Create Date: 2026-09-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0012_article_body_blocks"
down_revision: str | None = "0011_llm_usage_duration"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = inspector.get_table_names()
    if "articles" in tables:
        columns = {col["name"] for col in inspector.get_columns("articles")}
        if "body_blocks" not in columns:
            op.add_column("articles", sa.Column("body_blocks", JSONB(), nullable=True))
    if "article_versions" in tables:
        columns = {col["name"] for col in inspector.get_columns("article_versions")}
        if "body_blocks" not in columns:
            op.add_column("article_versions", sa.Column("body_blocks", JSONB(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = inspector.get_table_names()
    if "article_versions" in tables:
        columns = {col["name"] for col in inspector.get_columns("article_versions")}
        if "body_blocks" in columns:
            op.drop_column("article_versions", "body_blocks")
    if "articles" in tables:
        columns = {col["name"] for col in inspector.get_columns("articles")}
        if "body_blocks" in columns:
            op.drop_column("articles", "body_blocks")
