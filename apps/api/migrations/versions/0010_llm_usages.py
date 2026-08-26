"""LLM usage telemetry for admin debug.

Revision ID: 0010_llm_usages
Revises: 0009_publishing
Create Date: 2026-08-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "0010_llm_usages"
down_revision: str | None = "0009_publishing"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    if "llm_usages" not in tables:
        op.create_table(
            "llm_usages",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("event_id", sa.Uuid(), nullable=True),
            sa.Column("source_item_id", sa.Uuid(), nullable=True),
            sa.Column("pipeline_run_id", sa.Uuid(), nullable=True),
            sa.Column("stage", sa.String(length=64), nullable=True),
            sa.Column("model_role", sa.String(length=64), nullable=True),
            sa.Column("provider", sa.String(length=64), nullable=True),
            sa.Column("model", sa.String(length=128), nullable=True),
            sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["pipeline_run_id"], ["pipeline_runs.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["source_item_id"], ["source_items.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id", name="pk_llm_usages"),
        )

    existing_indexes = {idx["name"] for idx in inspector.get_indexes("llm_usages")}
    for name, cols in (
        ("ix_llm_usages_event_id", ["event_id"]),
        ("ix_llm_usages_source_item_id", ["source_item_id"]),
        ("ix_llm_usages_pipeline_run_id", ["pipeline_run_id"]),
        ("ix_llm_usages_stage", ["stage"]),
        ("ix_llm_usages_model_role", ["model_role"]),
        ("ix_llm_usages_created_at", ["created_at"]),
    ):
        if name not in existing_indexes:
            op.create_index(name, "llm_usages", cols)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "llm_usages" not in inspector.get_table_names():
        return
    existing_indexes = {idx["name"] for idx in inspector.get_indexes("llm_usages")}
    for name in (
        "ix_llm_usages_created_at",
        "ix_llm_usages_model_role",
        "ix_llm_usages_stage",
        "ix_llm_usages_pipeline_run_id",
        "ix_llm_usages_source_item_id",
        "ix_llm_usages_event_id",
    ):
        if name in existing_indexes:
            op.drop_index(name, table_name="llm_usages")
    op.drop_table("llm_usages")
