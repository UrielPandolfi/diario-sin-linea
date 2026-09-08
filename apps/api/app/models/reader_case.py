from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.enums import CaseActionType, CaseActor, CaseOutcome, CaseReason, CaseStatus
from app.models.article import Article, ArticleVersion, Correction
from app.models.base import Base, TimestampMixin


class ReaderCase(TimestampMixin, Base):
    __tablename__ = "reader_cases"
    __table_args__ = (
        Index("ix_reader_cases_status_created_at", "status", "created_at"),
        Index("ix_reader_cases_article_id", "article_id"),
        Index("ix_reader_cases_reason", "reason"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    public_code: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    access_token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    idempotency_key: Mapped[UUID] = mapped_column(Uuid, unique=True, nullable=False)
    article_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("articles.id", ondelete="SET NULL")
    )
    reported_version_number: Mapped[int | None] = mapped_column(Integer)
    reported_article_version_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("article_versions.id", ondelete="SET NULL")
    )
    reason: Mapped[CaseReason] = mapped_column(
        Enum(CaseReason, native_enum=False, length=32),
        nullable=False,
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    link_url: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(String(254))
    status: Mapped[CaseStatus] = mapped_column(
        Enum(CaseStatus, native_enum=False, length=32),
        default=CaseStatus.RECEIVED,
        nullable=False,
    )
    outcome: Mapped[CaseOutcome | None] = mapped_column(
        Enum(CaseOutcome, native_enum=False, length=32)
    )
    public_resolution: Mapped[str | None] = mapped_column(Text)
    reviewing_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    linked_correction_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("corrections.id", ondelete="SET NULL", use_alter=True)
    )
    ip_hash: Mapped[str | None] = mapped_column(String(64))

    article: Mapped[Article | None] = relationship(back_populates="reader_cases")
    reported_version: Mapped[ArticleVersion | None] = relationship(
        foreign_keys=[reported_article_version_id]
    )
    linked_correction: Mapped[Correction | None] = relationship(
        foreign_keys=[linked_correction_id]
    )
    authored_corrections: Mapped[list[Correction]] = relationship(
        back_populates="reader_case",
        foreign_keys="Correction.reader_case_id",
    )
    actions: Mapped[list["ReaderCaseAction"]] = relationship(back_populates="reader_case")


class ReaderCaseAction(TimestampMixin, Base):
    __tablename__ = "reader_case_actions"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    reader_case_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("reader_cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    action_type: Mapped[CaseActionType] = mapped_column(
        Enum(CaseActionType, native_enum=False, length=32),
        nullable=False,
    )
    actor: Mapped[CaseActor] = mapped_column(
        Enum(CaseActor, native_enum=False, length=32),
        nullable=False,
    )
    internal_note: Mapped[str | None] = mapped_column(Text)
    from_status: Mapped[str | None] = mapped_column(String(32))
    to_status: Mapped[str | None] = mapped_column(String(32))

    reader_case: Mapped[ReaderCase] = relationship(back_populates="actions")
