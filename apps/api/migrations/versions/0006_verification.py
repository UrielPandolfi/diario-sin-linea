"""Partial unique index for RUNNING verification.

Revision ID: 0006_verification
Revises: 0005_claim_resolution
Create Date: 2026-08-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "0006_verification"
down_revision: str | None = "0005_claim_resolution"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

VERIFICATION_RUNNING_INDEX = "uq_pipeline_runs_event_verification_running"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    pipeline_indexes = {item["name"] for item in inspector.get_indexes("pipeline_runs")}
    if VERIFICATION_RUNNING_INDEX not in pipeline_indexes:
        op.create_index(
            VERIFICATION_RUNNING_INDEX,
            "pipeline_runs",
            ["event_id"],
            unique=True,
            postgresql_where=sa.text("stage = 'verification' AND status = 'RUNNING'"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    pipeline_indexes = {item["name"] for item in inspector.get_indexes("pipeline_runs")}
    if VERIFICATION_RUNNING_INDEX in pipeline_indexes:
        op.drop_index(VERIFICATION_RUNNING_INDEX, table_name="pipeline_runs")
