"""Private saved articles for each reader.

Revision ID: 0019_reader_saves
Revises: 0018_reader_signals
Create Date: 2026-09-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision: str = "0019_reader_saves"
down_revision: str | None = "0018_reader_signals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "reader_event_saves" in inspector.get_table_names():
        return
    op.create_table(
        "reader_event_saves",
        sa.Column("reader_id", PGUUID(), nullable=False),
        sa.Column("event_id", PGUUID(), nullable=False),
        sa.Column("saved_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["reader_id"], ["readers.id"], ondelete="CASCADE", name="fk_reader_event_saves_reader_id_readers"),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="CASCADE", name="fk_reader_event_saves_event_id_events"),
        sa.PrimaryKeyConstraint("reader_id", "event_id", name="pk_reader_event_saves"),
    )
    op.create_index("ix_reader_event_saves_reader_id_saved_at", "reader_event_saves", ["reader_id", "saved_at"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "reader_event_saves" in inspector.get_table_names():
        op.drop_table("reader_event_saves")
