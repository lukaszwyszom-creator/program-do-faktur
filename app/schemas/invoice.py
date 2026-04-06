from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.domain.models.invoice import Invoice, InvoiceItem


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
    delivery_date: date | None = None
    currency: str = "PLN"
    items: list[InvoiceItemInput]


class InvoiceItemResponse(BaseModel):
    id: UUID | None = None
    name: str
    quantity: Decimal
    unit: str
    unit_price_net: Decimal
    vat_rate: Decimal
    net_total: Decimal
    vat_total: Decimal
    gross_total: Decimal
    sort_order: int

    @classmethod
    def from_domain(cls, item: InvoiceItem) -> "InvoiceItemResponse":
        return cls(
            id=item.id,
            name=item.name,
            quantity=item.quantity,
            unit=item.unit,
            unit_price_net=item.unit_price_net,
            vat_rate=item.vat_rate,
            net_total=item.net_total,
            vat_total=item.vat_total,
            gross_total=item.gross_total,
            sort_order=item.sort_order,
        )


class InvoiceResponse(BaseModel):
    id: UUID
    status: str
    number_local: str | None = None
    issue_date: date
    sale_date: date
    delivery_date: date | None = None
    ksef_reference_number: str | None = None
    currency: str
    seller_snapshot: dict
    buyer_snapshot: dict
    items: list[InvoiceItemResponse]
    total_net: Decimal
    total_vat: Decimal
    total_gross: Decimal
    payment_status: str = "unpaid"
    created_by: UUID | None = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, invoice: Invoice) -> "InvoiceResponse":
        return cls(
            id=invoice.id,
            status=invoice.status.value,
            number_local=invoice.number_local,
            issue_date=invoice.issue_date,
            sale_date=invoice.sale_date,
            delivery_date=invoice.delivery_date,
            ksef_reference_number=invoice.ksef_reference_number,
            currency=invoice.currency,
            seller_snapshot=invoice.seller_snapshot,
            buyer_snapshot=invoice.buyer_snapshot,
            items=[InvoiceItemResponse.from_domain(i) for i in invoice.items],
            total_net=invoice.total_net,
            total_vat=invoice.total_vat,
            total_gross=invoice.total_gross,
            payment_status=invoice.payment_status,
            created_by=invoice.created_by,
            created_at=invoice.created_at,
            updated_at=invoice.updated_at,
        )


class InvoiceListResponse(BaseModel):
    items: list[InvoiceResponse]
    total: int
    page: int
    size: int


class SubmitInvoiceResponse(BaseModel):
    invoice_id: UUID
    transmission_id: UUID
    status: str
