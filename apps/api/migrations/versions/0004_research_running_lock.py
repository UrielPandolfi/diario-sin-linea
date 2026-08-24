"""Partial unique index: one RUNNING research per event.

Revision ID: 0004_research_running_lock
Revises: 0003_source_item_identity
Create Date: 2026-08-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_research_running_lock"
down_revision: str | None = "0003_source_item_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "uq_pipeline_runs_event_research_running",
        "pipeline_runs",
        ["event_id"],
        unique=True,
        postgresql_where=sa.text("stage = 'research' AND status = 'RUNNING'"),
    )


def downgrade() -> None:
    op.drop_index("uq_pipeline_runs_event_research_running", table_name="pipeline_runs")
