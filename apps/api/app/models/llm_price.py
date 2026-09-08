from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text, UniqueConstraint, Uuid, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.clock import utc_now
from app.models.base import Base


class LlmPriceBook(Base):
    __tablename__ = "llm_price_books"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    effective_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    source_url: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        nullable=False,
    )

    rates: Mapped[list["LlmPriceRate"]] = relationship(back_populates="book")


class LlmPriceRate(Base):
    __tablename__ = "llm_price_rates"
    __table_args__ = (
        UniqueConstraint(
            "book_id",
            "provider",
            "model",
            "kind",
            name="uq_llm_price_rates_book_provider_model_kind",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    book_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("llm_price_books.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    usd_per_million: Mapped[Decimal] = mapped_column(Numeric(18, 10), nullable=False)
    extra_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb"), nullable=False
    )

    book: Mapped[LlmPriceBook] = relationship(back_populates="rates")
