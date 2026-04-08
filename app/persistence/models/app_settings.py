import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.persistence.base import Base


class AppSettingsORM(Base):
    """Singleton — zawsze dokładnie jeden wiersz (id = 1).

    Przechowuje konfigurowalne parametry sprzedawcy, które frontend może
    odczytać przez GET /api/v1/settings zamiast polegać wyłącznie na
    zmiennych środowiskowych lub localStorage.
    """

    __tablename__ = "app_settings"
    __table_args__ = (CheckConstraint("id = 1", name="ck_app_settings_singleton"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    seller_nip: Mapped[str | None] = mapped_column(String(10), nullable=True)
    seller_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    seller_street: Mapped[str | None] = mapped_column(String(256), nullable=True)
    seller_building_no: Mapped[str | None] = mapped_column(String(32), nullable=True)
    seller_apartment_no: Mapped[str | None] = mapped_column(String(32), nullable=True)
    seller_postal_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    seller_city: Mapped[str | None] = mapped_column(String(128), nullable=True)
    seller_country: Mapped[str | None] = mapped_column(String(2), nullable=True, server_default="PL")
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
