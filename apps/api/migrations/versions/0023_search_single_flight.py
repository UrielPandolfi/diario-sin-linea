"""Índice único de búsquedas en vuelo, si 0022 se aplicó a medias.

Revision ID: 0023_search_single_flight
Revises: 0022_cost_measurement
Create Date: 2026-10-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "0023_search_single_flight"
down_revision: str | None = "0022_cost_measurement"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "provider_result_cache" not in set(inspector.get_table_names()):
        return
    names = {index["name"] for index in inspector.get_indexes("provider_result_cache")}
    if "uq_provider_cache_pending" in names:
        return
    op.create_index(
        "uq_provider_cache_pending",
        "provider_result_cache",
        ["kind", "provider", "request_hash"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "provider_result_cache" not in set(inspector.get_table_names()):
        return
    names = {index["name"] for index in inspector.get_indexes("provider_result_cache")}
    if "uq_provider_cache_pending" in names:
        op.drop_index("uq_provider_cache_pending", table_name="provider_result_cache")
