from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utc_now
from app.models.base import Base


class LlmUsage(Base):
    __tablename__ = "llm_usages"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    event_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("events.id", ondelete="SET NULL"), index=True
    )
    source_item_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("source_items.id", ondelete="SET NULL"), index=True
    )
    pipeline_run_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("pipeline_runs.id", ondelete="SET NULL"), index=True
    )
    stage: Mapped[str | None] = mapped_column(String(64), index=True)
    model_role: Mapped[str | None] = mapped_column(String(64), index=True)
    provider: Mapped[str | None] = mapped_column(String(64))
    model: Mapped[str | None] = mapped_column(String(128))
    model_requested: Mapped[str | None] = mapped_column(String(128))
    model_reported: Mapped[str | None] = mapped_column(String(128))
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cache_write_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    usage_reported: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    attribution_kind: Mapped[str] = mapped_column(
        String(32), default="unattributed", nullable=False, index=True
    )
    cost_status: Mapped[str] = mapped_column(String(16), default="unknown", nullable=False, index=True)
    estimated_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(18, 10), nullable=True)
    price_book_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("llm_price_books.id", ondelete="SET NULL"), index=True
    )
    rate_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        nullable=False,
        index=True,
    )
