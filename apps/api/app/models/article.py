from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Computed, DateTime, Enum, ForeignKey, Index, Integer, String, Text, UniqueConstraint, Uuid, func
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.clock import utc_now
from app.domain.enums import ArticleStatus
from app.models.base import Base, TimestampMixin
from app.models.event import Event


class Article(TimestampMixin, Base):
    __tablename__ = "articles"
    __table_args__ = (
        UniqueConstraint("event_id", name="uq_articles_event_id"),
        UniqueConstraint("slug", name="uq_articles_slug"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    event_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("events.id", ondelete="CASCADE"), nullable=False
    )
    slug: Mapped[str] = mapped_column(String(255), nullable=False)
    headline: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[ArticleStatus] = mapped_column(
        Enum(ArticleStatus, native_enum=False, length=32),
        default=ArticleStatus.DRAFT,
        nullable=False,
        index=True,
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        server_default=func.now(),
        nullable=False,
    )
    current_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    published_version: Mapped[int | None] = mapped_column(Integer)
    hero_image_url: Mapped[str | None] = mapped_column(Text)

    event: Mapped[Event] = relationship(back_populates="articles")
    versions: Mapped[list["ArticleVersion"]] = relationship(back_populates="article")
    corrections: Mapped[list["Correction"]] = relationship(back_populates="article")


class ArticleVersion(TimestampMixin, Base):
    __tablename__ = "article_versions"
    __table_args__ = (
        UniqueConstraint("article_id", "version_number", name="uq_article_versions_article_id_version_number"),
        Index("ix_article_versions_search_tsv", "search_tsv", postgresql_using="gin"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    article_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("articles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    headline: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    change_reason: Mapped[str | None] = mapped_column(Text)
    search_tsv: Mapped[Any] = mapped_column(
        TSVECTOR,
        Computed(
            "to_tsvector('spanish', coalesce(headline, '') || ' ' || coalesce(summary, '') || ' ' || coalesce(body, ''))",
            persisted=True,
        ),
        nullable=True,
    )

    article: Mapped[Article] = relationship(back_populates="versions")


class Correction(TimestampMixin, Base):
    __tablename__ = "corrections"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    article_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("articles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    article_version_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("article_versions.id", ondelete="SET NULL")
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)

    article: Mapped[Article] = relationship(back_populates="corrections")
