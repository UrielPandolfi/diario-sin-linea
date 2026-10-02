"""Account security: session generation, password reset tokens, public update notices.

Revision ID: 0021_account_security
Revises: 0020_reader_locality
Create Date: 2026-10-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision: str = "0021_account_security"
down_revision: str | None = "0020_reader_locality"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    reader_columns = {column["name"] for column in inspector.get_columns("readers")}
    if "session_generation" not in reader_columns:
        op.add_column(
            "readers",
            sa.Column("session_generation", sa.Integer(), nullable=False, server_default="0"),
        )
    update_columns = {column["name"] for column in inspector.get_columns("event_updates")}
    if "public_notice" not in update_columns:
        op.add_column("event_updates", sa.Column("public_notice", sa.Text(), nullable=True))
    if "reader_password_resets" not in inspector.get_table_names():
        op.create_table(
            "reader_password_resets",
            sa.Column("id", PGUUID(), nullable=False),
            sa.Column("reader_id", PGUUID(), nullable=False),
            sa.Column("token_hash", sa.String(length=64), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(
                ["reader_id"],
                ["readers.id"],
                ondelete="CASCADE",
                name="fk_reader_password_resets_reader_id_readers",
            ),
            sa.PrimaryKeyConstraint("id", name="pk_reader_password_resets"),
            sa.UniqueConstraint("token_hash", name="uq_reader_password_resets_token_hash"),
        )
        op.create_index(
            "ix_reader_password_resets_reader_id",
            "reader_password_resets",
            ["reader_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "reader_password_resets" in inspector.get_table_names():
        op.drop_index("ix_reader_password_resets_reader_id", table_name="reader_password_resets")
        op.drop_table("reader_password_resets")
    update_columns = {column["name"] for column in inspector.get_columns("event_updates")}
    if "public_notice" in update_columns:
        op.drop_column("event_updates", "public_notice")
    reader_columns = {column["name"] for column in inspector.get_columns("readers")}
    if "session_generation" in reader_columns:
        op.drop_column("readers", "session_generation")
