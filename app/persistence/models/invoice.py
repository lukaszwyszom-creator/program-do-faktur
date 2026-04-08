import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.persistence.base import Base


class InvoiceORM(Base):
    __tablename__ = "invoices"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    number_local: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    seller_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    status: Mapped[str] = mapped_column(String(64), index=True)
    payment_status: Mapped[str] = mapped_column(String(64), default="unpaid", nullable=False)
    seller_snapshot_json: Mapped[dict] = mapped_column(JSONB)
    buyer_snapshot_json: Mapped[dict] = mapped_column(JSONB)
    totals_json: Mapped[dict] = mapped_column(JSONB)
    ksef_payload_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    validation_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    issue_date: Mapped[date] = mapped_column(Date)
    sale_date: Mapped[date] = mapped_column(Date)
    delivery_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    ksef_reference_number: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    currency: Mapped[str] = mapped_column(String(8), default="PLN")
    invoice_type: Mapped[str] = mapped_column(String(32), default="VAT", nullable=False)
    correction_of_invoice_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    correction_of_ksef_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    correction_reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    correction_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Adnotacje FA(3)
    use_split_payment: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    self_billing: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    reverse_charge: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    reverse_charge_art: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    reverse_charge_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    cash_accounting_method: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    # Waluta obca
    exchange_rate: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    exchange_rate_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # ZAL/ROZ
    advance_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    # Kierunek dokumentu: 'sale' (domyślnie — faktury sprzedaży) | 'purchase'
    direction: Mapped[str] = mapped_column(String(8), nullable=False, server_default="sale", index=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    items = relationship("InvoiceItemORM", back_populates="invoice", cascade="all, delete-orphan")
    transmissions = relationship("TransmissionORM", back_populates="invoice", cascade="all, delete-orphan")
    created_by_user = relationship("UserORM", back_populates="created_invoices")
    payment_allocations = relationship("PaymentAllocationORM", back_populates="invoice", cascade="all, delete-orphan")
    advance_links = relationship(
        "InvoiceAdvanceLinkORM",
        foreign_keys="InvoiceAdvanceLinkORM.invoice_id",
        cascade="all, delete-orphan",
        lazy="select",
    )
