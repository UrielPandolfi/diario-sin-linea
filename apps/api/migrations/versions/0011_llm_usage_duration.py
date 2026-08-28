"""Add duration_ms to llm_usages.

Revision ID: 0011_llm_usage_duration
Revises: 0010_llm_usages
Create Date: 2026-08-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "0011_llm_usage_duration"
down_revision: str | None = "0010_llm_usages"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "llm_usages" not in inspector.get_table_names():
        return
    columns = {col["name"] for col in inspector.get_columns("llm_usages")}
    if "duration_ms" not in columns:
        op.add_column("llm_usages", sa.Column("duration_ms", sa.Integer(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "llm_usages" not in inspector.get_table_names():
        return
    columns = {col["name"] for col in inspector.get_columns("llm_usages")}
    if "duration_ms" in columns:
        op.drop_column("llm_usages", "duration_ms")
