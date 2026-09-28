from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utc_now
from app.models.base import Base


class ReaderEventLike(Base):
    __tablename__ = "reader_event_likes"
    __table_args__ = (
        Index("ix_reader_event_likes_reader_id_created_at", "reader_id", "created_at"),
    )

    reader_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("readers.id", ondelete="CASCADE"), primary_key=True
    )
    event_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("events.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        nullable=False,
    )


class ReaderEventRead(Base):
    __tablename__ = "reader_event_reads"
    __table_args__ = (
        Index("ix_reader_event_reads_reader_id_read_at", "reader_id", "read_at"),
    )

    reader_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("readers.id", ondelete="CASCADE"), primary_key=True
    )
    event_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("events.id", ondelete="CASCADE"), primary_key=True
    )
    read_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        nullable=False,
    )
