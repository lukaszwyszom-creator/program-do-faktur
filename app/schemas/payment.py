from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from app.persistence.models.payment_allocation import PaymentAllocationORM


# ---------------------------------------------------------------------------
# Bank transaction
# ---------------------------------------------------------------------------

class BankTransactionResponse(BaseModel):
    id: UUID
    transaction_date: date
    value_date: date | None = None
    amount: Decimal
    currency: str
    counterparty_name: str | None = None
    counterparty_account: str | None = None
    title: str | None = None
    match_status: str
    remaining_amount: Decimal
    external_id: str | None = None
    source_file: str | None = None
    imported_at: datetime

    model_config = {"from_attributes": True}


class TransactionListResponse(BaseModel):
    items: list[BankTransactionResponse]
    total: int
    page: int
    size: int


# ---------------------------------------------------------------------------
# Payment allocation
# ---------------------------------------------------------------------------

class PaymentAllocationResponse(BaseModel):
    id: UUID
    transaction_id: UUID
    invoice_id: UUID
    allocated_amount: Decimal
    match_method: str
    match_score: int | None = None
    match_reasons: list[str] = Field(default_factory=list)
    is_reversed: bool
    reversed_at: datetime | None = None
    reversed_by: UUID | None = None
    created_at: datetime
    created_by: UUID | None = None
    # Embedded transaction summary
    transaction_date: date | None = None
    counterparty_name: str | None = None

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_with_tx(cls, alloc: "PaymentAllocationORM") -> "PaymentAllocationResponse":
        tx = getattr(alloc, "transaction", None)
        return cls(
            id=alloc.id,
            transaction_id=alloc.transaction_id,
            invoice_id=alloc.invoice_id,
            allocated_amount=alloc.allocated_amount,
            match_method=alloc.match_method,
            match_score=alloc.match_score,
            match_reasons=alloc.match_reasons_json or [],
            is_reversed=alloc.is_reversed,
            reversed_at=alloc.reversed_at,
            reversed_by=alloc.reversed_by,
            created_at=alloc.created_at,
            created_by=alloc.created_by,
            transaction_date=tx.transaction_date if tx else None,
            counterparty_name=tx.counterparty_name if tx else None,
        )


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------

class ManualAllocateRequest(BaseModel):
    invoice_id: UUID
    amount: Decimal = Field(gt=0, description="Kwota do przypisania (>0)")


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

class ImportResultResponse(BaseModel):
    imported: int
    skipped: int
    auto_matched: int
    manual_review: int
