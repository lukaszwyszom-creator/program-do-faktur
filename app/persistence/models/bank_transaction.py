import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, Index, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.persistence.base import Base


class BankTransactionORM(Base):
    __tablename__ = "bank_transactions"
    __table_args__ = (
        Index("ix_bank_transactions_match_status", "match_status"),
        Index("ix_bank_transactions_transaction_date", "transaction_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Unikalny identyfikator z banku — służy deduplikacji przy reimporcie
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True, index=True)
    transaction_date: Mapped[date] = mapped_column(Date, nullable=False)
    value_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="PLN", nullable=False)
    counterparty_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    counterparty_account: Mapped[str | None] = mapped_column(String(128), nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Status dopasowania (aktualizowany przy każdej zmianie alokacji)
    match_status: Mapped[str] = mapped_column(String(32), default="unmatched", nullable=False)
    # Kwota jeszcze nieprzypisana do faktur
    remaining_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    source_file: Mapped[str | None] = mapped_column(String(512), nullable=True)
    raw_row_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    imported_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    allocations = relationship(
        "PaymentAllocationORM",
        back_populates="transaction",
        cascade="all, delete-orphan",
    )
