"""Publication: published_version, FTS, shared write/audit/publish lock.

Revision ID: 0009_publishing
Revises: 0008_auditing
Create Date: 2026-08-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "0009_publishing"
down_revision: str | None = "0008_auditing"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

WRITING_RUNNING_INDEX = "uq_pipeline_runs_event_writing_running"
WRITE_AUDIT_RUNNING_INDEX = "uq_pipeline_runs_event_write_audit_running"
WRITE_AUDIT_PUBLISH_RUNNING_INDEX = "uq_pipeline_runs_event_write_audit_publish_running"
SEARCH_TSV_INDEX = "ix_article_versions_search_tsv"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    article_columns = {item["name"] for item in inspector.get_columns("articles")}
    if "published_version" not in article_columns:
        op.add_column("articles", sa.Column("published_version", sa.Integer(), nullable=True))

    version_columns = {item["name"] for item in inspector.get_columns("article_versions")}
    if "search_tsv" not in version_columns:
        op.execute(
            sa.text(
                "ALTER TABLE article_versions ADD COLUMN search_tsv tsvector "
                "GENERATED ALWAYS AS ("
                "to_tsvector('spanish', coalesce(headline, '') || ' ' || "
                "coalesce(summary, '') || ' ' || coalesce(body, ''))"
                ") STORED"
            )
        )

    version_indexes = {item["name"] for item in inspector.get_indexes("article_versions")}
    if SEARCH_TSV_INDEX not in version_indexes:
        op.create_index(
            SEARCH_TSV_INDEX,
            "article_versions",
            ["search_tsv"],
            postgresql_using="gin",
        )

    pipeline_indexes = {item["name"] for item in inspector.get_indexes("pipeline_runs")}
    for name in (WRITING_RUNNING_INDEX, WRITE_AUDIT_RUNNING_INDEX):
        if name in pipeline_indexes:
            op.drop_index(name, table_name="pipeline_runs")
    pipeline_indexes = {item["name"] for item in inspect(bind).get_indexes("pipeline_runs")}
    if WRITE_AUDIT_PUBLISH_RUNNING_INDEX not in pipeline_indexes:
        op.create_index(
            WRITE_AUDIT_PUBLISH_RUNNING_INDEX,
            "pipeline_runs",
            ["event_id"],
            unique=True,
            postgresql_where=sa.text(
                "status = 'RUNNING' AND stage IN ('writing', 'auditing', 'publishing')"
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    pipeline_indexes = {item["name"] for item in inspect(bind).get_indexes("pipeline_runs")}
    if WRITE_AUDIT_PUBLISH_RUNNING_INDEX in pipeline_indexes:
        op.drop_index(WRITE_AUDIT_PUBLISH_RUNNING_INDEX, table_name="pipeline_runs")
    pipeline_indexes = {item["name"] for item in inspect(bind).get_indexes("pipeline_runs")}
    if WRITE_AUDIT_RUNNING_INDEX not in pipeline_indexes:
        op.create_index(
            WRITE_AUDIT_RUNNING_INDEX,
            "pipeline_runs",
            ["event_id"],
            unique=True,
            postgresql_where=sa.text("status = 'RUNNING' AND stage IN ('writing', 'auditing')"),
        )
    pipeline_indexes = {item["name"] for item in inspect(bind).get_indexes("pipeline_runs")}
    if WRITING_RUNNING_INDEX not in pipeline_indexes:
        op.create_index(
            WRITING_RUNNING_INDEX,
            "pipeline_runs",
            ["event_id"],
            unique=True,
            postgresql_where=sa.text("stage = 'writing' AND status = 'RUNNING'"),
        )

    version_indexes = {item["name"] for item in inspect(bind).get_indexes("article_versions")}
    if SEARCH_TSV_INDEX in version_indexes:
        op.drop_index(SEARCH_TSV_INDEX, table_name="article_versions")
    version_columns = {item["name"] for item in inspect(bind).get_columns("article_versions")}
    if "search_tsv" in version_columns:
        op.drop_column("article_versions", "search_tsv")
    article_columns = {item["name"] for item in inspect(bind).get_columns("articles")}
    if "published_version" in article_columns:
        op.drop_column("articles", "published_version")
