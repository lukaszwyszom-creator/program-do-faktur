import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.persistence.base import Base


class ContractorORM(Base):
    __tablename__ = "contractors"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    nip: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    regon: Mapped[str | None] = mapped_column(String(32), nullable=True)
    krs: Mapped[str | None] = mapped_column(String(32), nullable=True)
    name: Mapped[str] = mapped_column(String(255))
    legal_form: Mapped[str | None] = mapped_column(String(128), nullable=True)
    street: Mapped[str | None] = mapped_column(String(255), nullable=True)
    building_no: Mapped[str | None] = mapped_column(String(32), nullable=True)
    apartment_no: Mapped[str | None] = mapped_column(String(32), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    city: Mapped[str | None] = mapped_column(String(128), nullable=True)
    voivodeship: Mapped[str | None] = mapped_column(String(128), nullable=True)
    county: Mapped[str | None] = mapped_column(String(128), nullable=True)
    commune: Mapped[str | None] = mapped_column(String(128), nullable=True)
    country: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source: Mapped[str] = mapped_column(String(64))
    source_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cache_valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lookup_last_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lookup_last_error: Mapped[str | None] = mapped_column(String(512), nullable=True)
    raw_payload_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    overrides = relationship("ContractorOverrideORM", back_populates="contractor", cascade="all, delete-orphan")
