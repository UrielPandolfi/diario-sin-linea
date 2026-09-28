"""Reader reads and likes for the authenticated home feed.

Revision ID: 0018_reader_signals
Revises: 0017_readers
Create Date: 2026-09-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision: str = "0018_reader_signals"
down_revision: str | None = "0017_readers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _create(name: str, *columns: sa.Column, indexes: list[tuple[str, list[str]]]) -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if name in inspector.get_table_names():
        return
    op.create_table(name, *columns)
    for index_name, cols in indexes:
        op.create_index(index_name, name, cols)


def upgrade() -> None:
    _create(
        "reader_event_likes",
        sa.Column("reader_id", PGUUID(), nullable=False),
        sa.Column("event_id", PGUUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["reader_id"], ["readers.id"], ondelete="CASCADE", name="fk_reader_event_likes_reader_id_readers"),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="CASCADE", name="fk_reader_event_likes_event_id_events"),
        sa.PrimaryKeyConstraint("reader_id", "event_id", name="pk_reader_event_likes"),
        indexes=[("ix_reader_event_likes_reader_id_created_at", ["reader_id", "created_at"])],
    )
    _create(
        "reader_event_reads",
        sa.Column("reader_id", PGUUID(), nullable=False),
        sa.Column("event_id", PGUUID(), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["reader_id"], ["readers.id"], ondelete="CASCADE", name="fk_reader_event_reads_reader_id_readers"),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="CASCADE", name="fk_reader_event_reads_event_id_events"),
        sa.PrimaryKeyConstraint("reader_id", "event_id", name="pk_reader_event_reads"),
        indexes=[("ix_reader_event_reads_reader_id_read_at", ["reader_id", "read_at"])],
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    names = set(inspector.get_table_names())
    if "reader_event_reads" in names:
        op.drop_table("reader_event_reads")
    if "reader_event_likes" in names:
        op.drop_table("reader_event_likes")
