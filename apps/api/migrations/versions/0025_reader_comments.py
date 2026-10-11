"""Reader username, profile avatars and article comments.

Revision ID: 0025_reader_comments
Revises: 0024_reader_email_verification
Create Date: 2026-10-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision: str = "0025_reader_comments"
down_revision: str | None = "0024_reader_email_verification"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    reader_columns = {column["name"] for column in inspector.get_columns("readers")}
    if "username" not in reader_columns:
        op.add_column("readers", sa.Column("username", sa.String(length=20), nullable=True))
        op.create_index("uq_readers_username", "readers", ["username"], unique=True)
    if "avatar_enqueued_at" not in reader_columns:
        op.add_column("readers", sa.Column("avatar_enqueued_at", sa.DateTime(timezone=True), nullable=True))
    tables = set(inspector.get_table_names())
    if "reader_avatars" not in tables:
        op.create_table(
            "reader_avatars",
            sa.Column("reader_id", PGUUID(), nullable=False),
            sa.Column("image_bytes", sa.LargeBinary(), nullable=False),
            sa.Column("fingerprint", sa.String(length=64), nullable=False),
            sa.Column("content_type", sa.String(length=64), nullable=False),
            sa.Column("width", sa.Integer(), nullable=False),
            sa.Column("height", sa.Integer(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(
                ["reader_id"],
                ["readers.id"],
                ondelete="CASCADE",
                name="fk_reader_avatars_reader_id_readers",
            ),
            sa.PrimaryKeyConstraint("reader_id", name="pk_reader_avatars"),
        )
    if "article_comments" not in tables:
        op.create_table(
            "article_comments",
            sa.Column("id", PGUUID(), nullable=False),
            sa.Column("article_id", PGUUID(), nullable=False),
            sa.Column("reader_id", PGUUID(), nullable=False),
            sa.Column("parent_id", PGUUID(), nullable=True),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column("anonymous", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(
                ["article_id"],
                ["articles.id"],
                ondelete="CASCADE",
                name="fk_article_comments_article_id_articles",
            ),
            sa.ForeignKeyConstraint(
                ["reader_id"],
                ["readers.id"],
                ondelete="CASCADE",
                name="fk_article_comments_reader_id_readers",
            ),
            sa.ForeignKeyConstraint(
                ["parent_id"],
                ["article_comments.id"],
                ondelete="CASCADE",
                name="fk_article_comments_parent_id_article_comments",
            ),
            sa.PrimaryKeyConstraint("id", name="pk_article_comments"),
        )
        op.create_index("ix_article_comments_article_id", "article_comments", ["article_id"])
        op.create_index("ix_article_comments_reader_id", "article_comments", ["reader_id"])
        op.create_index("ix_article_comments_parent_id", "article_comments", ["parent_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "article_comments" in inspector.get_table_names():
        op.drop_index("ix_article_comments_parent_id", table_name="article_comments")
        op.drop_index("ix_article_comments_reader_id", table_name="article_comments")
        op.drop_index("ix_article_comments_article_id", table_name="article_comments")
        op.drop_table("article_comments")
    if "reader_avatars" in inspector.get_table_names():
        op.drop_table("reader_avatars")
    reader_columns = {column["name"] for column in inspector.get_columns("readers")}
    if "avatar_enqueued_at" in reader_columns:
        op.drop_column("readers", "avatar_enqueued_at")
    if "username" in reader_columns:
        op.drop_index("uq_readers_username", table_name="readers")
        op.drop_column("readers", "username")
