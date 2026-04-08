import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, LargeBinary, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.persistence.base import Base


class TransmissionORM(Base):
    __tablename__ = "transmissions"
    __table_args__ = (
        Index("ix_transmissions_invoice_status", "invoice_id", "status"),
        UniqueConstraint("idempotency_key", name="uq_transmissions_idempotency_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    invoice_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("invoices.id"), index=True)
    channel: Mapped[str] = mapped_column(String(64), default="ksef")
    operation_type: Mapped[str] = mapped_column(String(64), default="invoice_submit")
    status: Mapped[str] = mapped_column(String(64), index=True)
    attempt_no: Mapped[int] = mapped_column(Integer, default=1)
    idempotency_key: Mapped[str] = mapped_column(String(255), index=False)
    external_reference: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    ksef_reference_number: Mapped[str | None] = mapped_column(String(255), nullable=True)
    upo_xml: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    upo_status: Mapped[str | None] = mapped_column(String(32), nullable=True)  # pending | fetched | failed
    request_payload_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    response_payload_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    invoice = relationship("InvoiceORM", back_populates="transmissions")
