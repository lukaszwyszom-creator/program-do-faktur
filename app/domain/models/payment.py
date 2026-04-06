from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from app.domain.enums import InvoicePaymentStatus, PaymentMatchMethod, PaymentMatchStatus


@dataclass(slots=True)
class BankTransaction:
    id: UUID
    transaction_date: date
    amount: Decimal
    currency: str
    match_status: PaymentMatchStatus
    remaining_amount: Decimal
    imported_at: datetime
    value_date: date | None = None
    counterparty_name: str | None = None
    counterparty_account: str | None = None
    title: str | None = None
    external_id: str | None = None
    source_file: str | None = None
    raw_row: dict | None = None
    imported_by: UUID | None = None


@dataclass(slots=True)
class PaymentAllocation:
    id: UUID
    transaction_id: UUID
    invoice_id: UUID
    allocated_amount: Decimal
    match_method: PaymentMatchMethod
    created_at: datetime
    match_score: int | None = None
    match_reasons: list[str] = field(default_factory=list)
    is_reversed: bool = False
    reversed_at: datetime | None = None
    reversed_by: UUID | None = None
    created_by: UUID | None = None
