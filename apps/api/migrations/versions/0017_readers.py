"""Reader accounts for the home feed and personal areas.

Revision ID: 0017_readers
Revises: 0016_article_hero_images
Create Date: 2026-09-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision: str = "0017_readers"
down_revision: str | None = "0016_article_hero_images"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "readers" in inspector.get_table_names():
        return
    op.create_table(
        "readers",
        sa.Column("id", PGUUID(), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_readers"),
        sa.UniqueConstraint("email", name="uq_readers_email"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "readers" in inspector.get_table_names():
        op.drop_table("readers")
