from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector

from app.core.clock import utc_now
from app.domain.enums import EventSourceRelation, EventStatus, EventUpdateType, LocationPrecision
from app.models.base import Base, TimestampMixin
from app.models.source import SourceItem

EMBEDDING_DIMENSIONS = 1024


class Event(TimestampMixin, Base):
    __tablename__ = "events"
    __table_args__ = (
        CheckConstraint(
            "relevance_score >= 0 AND relevance_score <= 100",
            name="relevance_score_range",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    public_id: Mapped[UUID] = mapped_column(Uuid, default=uuid4, unique=True, nullable=False)
    slug: Mapped[str | None] = mapped_column(String(255), unique=True)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False, default="unknown")
    title_internal: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[EventStatus] = mapped_column(
        Enum(EventStatus, native_enum=False, length=32),
        default=EventStatus.DETECTED,
        nullable=False,
        index=True,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        nullable=False,
        index=True,
    )
    last_material_update_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    country_code: Mapped[str | None] = mapped_column(String(8), default="AR")
    province: Mapped[str | None] = mapped_column(String(128))
    locality: Mapped[str | None] = mapped_column(String(128), index=True)
    neighborhood: Mapped[str | None] = mapped_column(String(128))
    address_text: Mapped[str | None] = mapped_column(Text)
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    location_precision: Mapped[LocationPrecision | None] = mapped_column(
        Enum(LocationPrecision, native_enum=False, length=32)
    )
    relevance_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    short_summary: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        server_default=func.now(),
        nullable=False,
    )

    event_sources: Mapped[list["EventSource"]] = relationship(back_populates="event")
    event_entities: Mapped[list["EventEntity"]] = relationship(back_populates="event")
    claims: Mapped[list["Claim"]] = relationship(back_populates="event")
    updates: Mapped[list["EventUpdate"]] = relationship(back_populates="event")
    articles: Mapped[list["Article"]] = relationship(back_populates="event")
    embedding: Mapped["EventEmbedding | None"] = relationship(back_populates="event")


class EventSource(Base):
    __tablename__ = "event_sources"
    __table_args__ = (
        UniqueConstraint("event_id", "source_item_id", name="uq_event_sources_event_id_source_item_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    event_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_item_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("source_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    relation_type: Mapped[EventSourceRelation] = mapped_column(
        Enum(EventSourceRelation, native_enum=False, length=32),
        default=EventSourceRelation.INITIAL,
        nullable=False,
    )
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )

    event: Mapped[Event] = relationship(back_populates="event_sources")
    source_item: Mapped[SourceItem] = relationship()


class EventUpdate(TimestampMixin, Base):
    __tablename__ = "event_updates"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    event_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    update_type: Mapped[EventUpdateType] = mapped_column(
        Enum(EventUpdateType, native_enum=False, length=32),
        nullable=False,
    )
    headline: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    is_material: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )

    event: Mapped[Event] = relationship(back_populates="updates")


class EventEntity(Base):
    __tablename__ = "event_entities"
    __table_args__ = (
        UniqueConstraint("event_id", "entity_id", "role", name="uq_event_entities_event_entity_role"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    event_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("events.id", ondelete="CASCADE"), nullable=False
    )
    entity_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("entities.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(64), nullable=False)

    event: Mapped[Event] = relationship(back_populates="event_entities")


class EventEmbedding(TimestampMixin, Base):
    __tablename__ = "event_embeddings"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    event_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("events.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)

    event: Mapped[Event] = relationship(back_populates="embedding")
