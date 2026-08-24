"""Partial unique index for RUNNING claim_resolution and unique claim evidence.

Revision ID: 0005_claim_resolution
Revises: 0004_research_running_lock
Create Date: 2026-08-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "0005_claim_resolution"
down_revision: str | None = "0004_research_running_lock"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CLAIM_RUNNING_INDEX = "uq_pipeline_runs_event_claim_resolution_running"
EVIDENCE_UNIQUE = "uq_claim_evidence_claim_id_source_item_id"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    pipeline_indexes = {item["name"] for item in inspector.get_indexes("pipeline_runs")}
    if CLAIM_RUNNING_INDEX not in pipeline_indexes:
        op.create_index(
            CLAIM_RUNNING_INDEX,
            "pipeline_runs",
            ["event_id"],
            unique=True,
            postgresql_where=sa.text("stage = 'claim_resolution' AND status = 'RUNNING'"),
        )

    evidence_uniques = {item["name"] for item in inspector.get_unique_constraints("claim_evidence")}
    evidence_indexes = {item["name"] for item in inspector.get_indexes("claim_evidence")}
    if EVIDENCE_UNIQUE not in evidence_uniques and EVIDENCE_UNIQUE not in evidence_indexes:
        op.create_unique_constraint(
            EVIDENCE_UNIQUE,
            "claim_evidence",
            ["claim_id", "source_item_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    evidence_uniques = {item["name"] for item in inspector.get_unique_constraints("claim_evidence")}
    evidence_indexes = {item["name"] for item in inspector.get_indexes("claim_evidence")}
    if EVIDENCE_UNIQUE in evidence_uniques:
        op.drop_constraint(EVIDENCE_UNIQUE, "claim_evidence", type_="unique")
    elif EVIDENCE_UNIQUE in evidence_indexes:
        op.drop_index(EVIDENCE_UNIQUE, table_name="claim_evidence")

    pipeline_indexes = {item["name"] for item in inspector.get_indexes("pipeline_runs")}
    if CLAIM_RUNNING_INDEX in pipeline_indexes:
        op.drop_index(CLAIM_RUNNING_INDEX, table_name="pipeline_runs")
