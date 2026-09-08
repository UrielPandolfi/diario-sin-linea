"""Reader cases, editorial hold, version published_at, correction kinds.

Revision ID: 0013_reader_cases
Revises: 0012_article_body_blocks
Create Date: 2026-09-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision: str = "0013_reader_cases"
down_revision: str | None = "0012_article_body_blocks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = inspector.get_table_names()

    if "articles" in tables:
        columns = {col["name"] for col in inspector.get_columns("articles")}
        if "editorial_hold" not in columns:
            op.add_column(
                "articles",
                sa.Column("editorial_hold", sa.Boolean(), nullable=False, server_default=sa.false()),
            )
            op.alter_column("articles", "editorial_hold", server_default=None)

    if "article_versions" in tables:
        columns = {col["name"] for col in inspector.get_columns("article_versions")}
        if "published_at" not in columns:
            op.add_column(
                "article_versions",
                sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
            )
        op.execute(
            """
            UPDATE article_versions AS v
            SET published_at = a.published_at
            FROM articles AS a
            WHERE v.article_id = a.id
              AND a.published_version IS NOT NULL
              AND v.version_number = a.published_version
              AND v.published_at IS NULL
              AND a.published_at IS NOT NULL
            """
        )

    if "reader_cases" not in tables:
        op.create_table(
            "reader_cases",
            sa.Column("id", PGUUID(), nullable=False),
            sa.Column("public_code", sa.String(length=16), nullable=False),
            sa.Column("access_token", sa.String(length=64), nullable=False),
            sa.Column("idempotency_key", PGUUID(), nullable=False),
            sa.Column("article_id", PGUUID(), nullable=True),
            sa.Column("reported_version_number", sa.Integer(), nullable=True),
            sa.Column("reported_article_version_id", PGUUID(), nullable=True),
            sa.Column("reason", sa.String(length=32), nullable=False),
            sa.Column("message", sa.Text(), nullable=False),
            sa.Column("link_url", sa.Text(), nullable=True),
            sa.Column("email", sa.String(length=254), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("outcome", sa.String(length=32), nullable=True),
            sa.Column("public_resolution", sa.Text(), nullable=True),
            sa.Column("reviewing_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("linked_correction_id", PGUUID(), nullable=True),
            sa.Column("ip_hash", sa.String(length=64), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.PrimaryKeyConstraint("id", name="pk_reader_cases"),
            sa.UniqueConstraint("public_code", name="uq_reader_cases_public_code"),
            sa.UniqueConstraint("access_token", name="uq_reader_cases_access_token"),
            sa.UniqueConstraint("idempotency_key", name="uq_reader_cases_idempotency_key"),
            sa.ForeignKeyConstraint(["article_id"], ["articles.id"], name="fk_reader_cases_article_id_articles", ondelete="SET NULL"),
            sa.ForeignKeyConstraint(
                ["reported_article_version_id"],
                ["article_versions.id"],
                name="fk_reader_cases_reported_article_version_id_article_versions",
                ondelete="SET NULL",
            ),
            sa.ForeignKeyConstraint(
                ["linked_correction_id"],
                ["corrections.id"],
                name="fk_reader_cases_linked_correction_id_corrections",
                ondelete="SET NULL",
            ),
        )
        op.create_index("ix_reader_cases_status_created_at", "reader_cases", ["status", "created_at"])
        op.create_index("ix_reader_cases_article_id", "reader_cases", ["article_id"])
        op.create_index("ix_reader_cases_reason", "reader_cases", ["reason"])

    if "corrections" in tables:
        columns = {col["name"] for col in inspector.get_columns("corrections")}
        if "kind" not in columns:
            op.add_column(
                "corrections",
                sa.Column("kind", sa.String(length=32), nullable=False, server_default="CORRECTION"),
            )
            op.alter_column("corrections", "kind", server_default=None)
            op.create_index("ix_corrections_kind", "corrections", ["kind"])
        if "show_near_title" not in columns:
            op.add_column(
                "corrections",
                sa.Column("show_near_title", sa.Boolean(), nullable=False, server_default=sa.false()),
            )
            op.alter_column("corrections", "show_near_title", server_default=None)
        if "is_public" not in columns:
            op.add_column(
                "corrections",
                sa.Column("is_public", sa.Boolean(), nullable=False, server_default=sa.true()),
            )
            op.alter_column("corrections", "is_public", server_default=None)
        if "reader_case_id" not in columns:
            op.add_column("corrections", sa.Column("reader_case_id", PGUUID(), nullable=True))
            op.create_index("ix_corrections_reader_case_id", "corrections", ["reader_case_id"])
            op.create_foreign_key(
                "fk_corrections_reader_case_id_reader_cases",
                "corrections",
                "reader_cases",
                ["reader_case_id"],
                ["id"],
                ondelete="SET NULL",
            )

    if "reader_case_actions" not in tables:
        op.create_table(
            "reader_case_actions",
            sa.Column("id", PGUUID(), nullable=False),
            sa.Column("reader_case_id", PGUUID(), nullable=False),
            sa.Column("action_type", sa.String(length=32), nullable=False),
            sa.Column("actor", sa.String(length=32), nullable=False),
            sa.Column("internal_note", sa.Text(), nullable=True),
            sa.Column("from_status", sa.String(length=32), nullable=True),
            sa.Column("to_status", sa.String(length=32), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.PrimaryKeyConstraint("id", name="pk_reader_case_actions"),
            sa.ForeignKeyConstraint(
                ["reader_case_id"],
                ["reader_cases.id"],
                name="fk_reader_case_actions_reader_case_id_reader_cases",
                ondelete="CASCADE",
            ),
        )
        op.create_index("ix_reader_case_actions_reader_case_id", "reader_case_actions", ["reader_case_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = inspector.get_table_names()

    if "reader_case_actions" in tables:
        op.drop_table("reader_case_actions")

    if "corrections" in tables:
        columns = {col["name"] for col in inspector.get_columns("corrections")}
        if "reader_case_id" in columns:
            op.drop_constraint("fk_corrections_reader_case_id_reader_cases", "corrections", type_="foreignkey")
            op.drop_index("ix_corrections_reader_case_id", table_name="corrections")
            op.drop_column("corrections", "reader_case_id")
        if "is_public" in columns:
            op.drop_column("corrections", "is_public")
        if "show_near_title" in columns:
            op.drop_column("corrections", "show_near_title")
        if "kind" in columns:
            op.drop_index("ix_corrections_kind", table_name="corrections")
            op.drop_column("corrections", "kind")

    if "reader_cases" in tables:
        op.drop_table("reader_cases")

    if "article_versions" in tables:
        columns = {col["name"] for col in inspector.get_columns("article_versions")}
        if "published_at" in columns:
            op.drop_column("article_versions", "published_at")

    if "articles" in tables:
        columns = {col["name"] for col in inspector.get_columns("articles")}
        if "editorial_hold" in columns:
            op.drop_column("articles", "editorial_hold")
