"""Partial unique index: one RUNNING writing or auditing per event.

Revision ID: 0008_auditing
Revises: 0007_writing
Create Date: 2026-08-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "0008_auditing"
down_revision: str | None = "0007_writing"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

WRITE_AUDIT_RUNNING_INDEX = "uq_pipeline_runs_event_write_audit_running"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    pipeline_indexes = {item["name"] for item in inspector.get_indexes("pipeline_runs")}
    if WRITE_AUDIT_RUNNING_INDEX not in pipeline_indexes:
        op.create_index(
            WRITE_AUDIT_RUNNING_INDEX,
            "pipeline_runs",
            ["event_id"],
            unique=True,
            postgresql_where=sa.text("status = 'RUNNING' AND stage IN ('writing', 'auditing')"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    pipeline_indexes = {item["name"] for item in inspector.get_indexes("pipeline_runs")}
    if WRITE_AUDIT_RUNNING_INDEX in pipeline_indexes:
        op.drop_index(WRITE_AUDIT_RUNNING_INDEX, table_name="pipeline_runs")
