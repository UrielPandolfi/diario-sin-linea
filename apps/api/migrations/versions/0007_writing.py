"""Partial unique index for RUNNING writing.

Revision ID: 0007_writing
Revises: 0006_verification
Create Date: 2026-08-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "0007_writing"
down_revision: str | None = "0006_verification"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

WRITING_RUNNING_INDEX = "uq_pipeline_runs_event_writing_running"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    pipeline_indexes = {item["name"] for item in inspector.get_indexes("pipeline_runs")}
    if WRITING_RUNNING_INDEX not in pipeline_indexes:
        op.create_index(
            WRITING_RUNNING_INDEX,
            "pipeline_runs",
            ["event_id"],
            unique=True,
            postgresql_where=sa.text("stage = 'writing' AND status = 'RUNNING'"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    pipeline_indexes = {item["name"] for item in inspector.get_indexes("pipeline_runs")}
    if WRITING_RUNNING_INDEX in pipeline_indexes:
        op.drop_index(WRITING_RUNNING_INDEX, table_name="pipeline_runs")
