import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.persistence.base import Base


class PaymentAllocationORM(Base):
    __tablename__ = "payment_allocations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bank_transactions.id"), nullable=False, index=True
    )
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("invoices.id"), nullable=False, index=True
    )
    allocated_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    # Metoda dopasowania: "auto" | "manual"
    match_method: Mapped[str] = mapped_column(String(16), nullable=False)
    # Wynik scoringu (0-100); NULL dla ręcznych
    match_score: Mapped[int | None] = mapped_column(Numeric(5, 2), nullable=True)
    # Lista powodów: ["number_match", "amount_match", ...]
    match_reasons_json: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # Cofnięcie przypisania
    is_reversed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reversed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    transaction = relationship("BankTransactionORM", back_populates="allocations")
    invoice = relationship("InvoiceORM", back_populates="payment_allocations")
