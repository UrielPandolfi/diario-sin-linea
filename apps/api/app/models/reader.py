from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Reader(TimestampMixin, Base):
    __tablename__ = "readers"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(254), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    interest_locality_id: Mapped[str | None] = mapped_column(
        String(32),
        ForeignKey("geo_localities.id", ondelete="SET NULL"),
        nullable=True,
    )
    locality_step: Mapped[str] = mapped_column(String(16), nullable=False, default="done", server_default="done")
