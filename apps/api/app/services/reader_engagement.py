"""Idempotent reads and likes for the authenticated reader. One row per reader and event."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.clock import utc_now
from app.models.reader_signal import ReaderEventLike, ReaderEventRead, ReaderEventSave


def like_event(session: Session, reader_id: UUID, event_id: UUID, *, now: datetime | None = None) -> None:
    moment = now or utc_now()
    stmt = insert(ReaderEventLike).values(reader_id=reader_id, event_id=event_id, created_at=moment)
    session.execute(stmt.on_conflict_do_nothing(constraint="pk_reader_event_likes"))
    session.flush()


def unlike_event(session: Session, reader_id: UUID, event_id: UUID) -> None:
    row = session.get(ReaderEventLike, (reader_id, event_id))
    if row is not None:
        session.delete(row)
        session.flush()


def event_is_liked(session: Session, reader_id: UUID, event_id: UUID) -> bool:
    return session.get(ReaderEventLike, (reader_id, event_id)) is not None


def save_event(session: Session, reader_id: UUID, event_id: UUID, *, now: datetime | None = None) -> None:
    moment = now or utc_now()
    stmt = insert(ReaderEventSave).values(reader_id=reader_id, event_id=event_id, saved_at=moment)
    session.execute(stmt.on_conflict_do_nothing(constraint="pk_reader_event_saves"))
    session.flush()


def unsave_event(session: Session, reader_id: UUID, event_id: UUID) -> None:
    row = session.get(ReaderEventSave, (reader_id, event_id))
    if row is not None:
        session.delete(row)
        session.flush()


def event_is_saved(session: Session, reader_id: UUID, event_id: UUID) -> bool:
    return session.get(ReaderEventSave, (reader_id, event_id)) is not None


def record_read(session: Session, reader_id: UUID, event_id: UUID, *, now: datetime | None = None) -> None:
    moment = now or utc_now()
    stmt = insert(ReaderEventRead).values(reader_id=reader_id, event_id=event_id, read_at=moment)
    session.execute(
        stmt.on_conflict_do_update(constraint="pk_reader_event_reads", set_={"read_at": moment})
    )
    session.flush()


def signal_ids(
    session: Session,
    reader_id: UUID,
    *,
    since: datetime,
) -> tuple[set[UUID], set[UUID]]:
    reads = set(
        session.scalars(
            select(ReaderEventRead.event_id).where(
                ReaderEventRead.reader_id == reader_id,
                ReaderEventRead.read_at >= since,
            )
        ).all()
    )
    likes = set(
        session.scalars(
            select(ReaderEventLike.event_id).where(
                ReaderEventLike.reader_id == reader_id,
                ReaderEventLike.created_at >= since,
            )
        ).all()
    )
    return reads, likes
