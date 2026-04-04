import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.persistence.base import Base


class ContractorOverrideORM(Base):
    __tablename__ = "contractor_overrides"
    __table_args__ = (
        Index(
            "uq_contractors_active_override",
            "contractor_id",
            unique=True,
            postgresql_where=text("is_active = true"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    contractor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("contractors.id"), index=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    legal_form: Mapped[str | None] = mapped_column(String(128), nullable=True)
    street: Mapped[str | None] = mapped_column(String(255), nullable=True)
    building_no: Mapped[str | None] = mapped_column(String(32), nullable=True)
    apartment_no: Mapped[str | None] = mapped_column(String(32), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    city: Mapped[str | None] = mapped_column(String(128), nullable=True)
    county: Mapped[str | None] = mapped_column(String(128), nullable=True)
    commune: Mapped[str | None] = mapped_column(String(128), nullable=True)
    voivodeship: Mapped[str | None] = mapped_column(String(128), nullable=True)
    override_reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    contractor = relationship("ContractorORM", back_populates="overrides")
    created_by_user = relationship("UserORM", back_populates="contractor_overrides")
