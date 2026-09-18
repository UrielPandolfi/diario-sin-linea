"""App settings: toggle de polling automático (default activo).

Revision ID: 0015_app_settings
Revises: 0014_llm_costs
Create Date: 2026-09-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "0015_app_settings"
down_revision: str | None = "0014_llm_costs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "app_settings" in inspector.get_table_names():
        return
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("key", name="pk_app_settings"),
    )
    op.execute(
        "INSERT INTO app_settings (key, enabled) VALUES ('auto_poll_enabled', true)"
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "app_settings" in inspector.get_table_names():
        op.drop_table("app_settings")
