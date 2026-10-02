from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class ReaderPasswordReset(TimestampMixin, Base):
    __tablename__ = "reader_password_resets"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    reader_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("readers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
