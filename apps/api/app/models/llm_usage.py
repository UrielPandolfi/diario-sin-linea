from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, Uuid, func
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
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        nullable=False,
        index=True,
    )
