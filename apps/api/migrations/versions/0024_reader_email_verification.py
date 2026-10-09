"""Email confirmation for readers. Existing accounts stay confirmed.

Revision ID: 0024_reader_email_verification
Revises: 0023_search_single_flight
Create Date: 2026-10-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision: str = "0024_reader_email_verification"
down_revision: str | None = "0023_search_single_flight"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    reader_columns = {column["name"] for column in inspector.get_columns("readers")}
    if "email_verified_at" not in reader_columns:
        op.add_column("readers", sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True))
        op.execute(sa.text("UPDATE readers SET email_verified_at = created_at WHERE email_verified_at IS NULL"))
    if "reader_email_verifications" not in inspector.get_table_names():
        op.create_table(
            "reader_email_verifications",
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
                name="fk_reader_email_verifications_reader_id_readers",
            ),
            sa.PrimaryKeyConstraint("id", name="pk_reader_email_verifications"),
            sa.UniqueConstraint("token_hash", name="uq_reader_email_verifications_token_hash"),
        )
        op.create_index(
            "ix_reader_email_verifications_reader_id",
            "reader_email_verifications",
            ["reader_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "reader_email_verifications" in inspector.get_table_names():
        op.drop_index("ix_reader_email_verifications_reader_id", table_name="reader_email_verifications")
        op.drop_table("reader_email_verifications")
    reader_columns = {column["name"] for column in inspector.get_columns("readers")}
    if "email_verified_at" in reader_columns:
        op.drop_column("readers", "email_verified_at")
