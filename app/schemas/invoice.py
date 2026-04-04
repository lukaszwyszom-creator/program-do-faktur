from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class InvoiceItemInput(BaseModel):
    name: str
    quantity: Decimal
    unit: str
    unit_price_net: Decimal
    vat_rate: Decimal


class InvoiceCreateRequest(BaseModel):
    buyer_id: UUID | None = None
    issue_date: date
    sale_date: date
    currency: str = "PLN"
    items: list[InvoiceItemInput]


class InvoiceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    status: str
    issue_date: date
    sale_date: date
    created_at: datetime


class SubmitInvoiceResponse(BaseModel):
    invoice_id: UUID
    transmission_id: UUID
    status: str
