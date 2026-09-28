from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class GeoLocality(Base):
    """Official Argentine locality. Ids stay text so leading zeros survive."""

    __tablename__ = "geo_localities"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    name_folded: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    province_id: Mapped[str] = mapped_column(String(16), nullable=False)
    province_name: Mapped[str] = mapped_column(String(80), nullable=False)
    department_id: Mapped[str] = mapped_column(String(16), nullable=False)
    department_name: Mapped[str] = mapped_column(String(120), nullable=False)
    country_code: Mapped[str] = mapped_column(String(2), nullable=False, default="AR")
