import re
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator

from app.domain.models.stock import MovementType, Product, Stock, StockMovement, Warehouse

_ISBN_RE = re.compile(r'^\d{3}-\d{2}-\d{6}-\d-\d$')


class ProductCreateRequest(BaseModel):
    name: str
    isbn: str | None = None
    unit: str = "szt"

    @field_validator("isbn")
    @classmethod
    def validate_isbn(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not _ISBN_RE.match(v):
            raise ValueError("ISBN musi mieć format xxx-xx-xxxxxx-x-x (np. 978-83-123456-7-8)")
        return v


class ProductResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    isbn: str | None
    unit: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, p: Product) -> "ProductResponse":
        return cls(
            id=p.id,
            name=p.name,
            isbn=p.isbn,
            unit=p.unit,
            created_at=p.created_at,
            updated_at=p.updated_at,
        )


class WarehouseResponse(BaseModel):
    id: UUID
    name: str
    is_default: bool
    created_at: datetime

    @classmethod
    def from_domain(cls, w: Warehouse) -> "WarehouseResponse":
        return cls(id=w.id, name=w.name, is_default=w.is_default, created_at=w.created_at)


class StockResponse(BaseModel):
    id: UUID
    product_id: UUID
    warehouse_id: UUID
    quantity: Decimal

    @classmethod
    def from_domain(cls, s: Stock) -> "StockResponse":
        return cls(
            id=s.id,
            product_id=s.product_id,
            warehouse_id=s.warehouse_id,
            quantity=s.quantity,
        )


class StockListResponse(BaseModel):
    items: list[StockResponse]
    total: int


class StockMovementCreateRequest(BaseModel):
    product_id: UUID
    warehouse_id: UUID | None = None  # None → domyślny magazyn
    movement_type: MovementType
    quantity: Decimal
    note: str | None = None

    @field_validator("quantity")
    @classmethod
    def quantity_positive(cls, v: Decimal) -> Decimal:
        if v <= Decimal("0"):
            raise ValueError("Ilość musi być większa od 0.")
        return v


class StockMovementResponse(BaseModel):
    id: UUID
    product_id: UUID
    warehouse_id: UUID
    movement_type: MovementType
    quantity: Decimal
    invoice_id: UUID | None
    note: str | None
    created_at: datetime

    @classmethod
    def from_domain(cls, m: StockMovement) -> "StockMovementResponse":
        return cls(
            id=m.id,
            product_id=m.product_id,
            warehouse_id=m.warehouse_id,
            movement_type=m.movement_type,
            quantity=m.quantity,
            invoice_id=m.invoice_id,
            note=m.note,
            created_at=m.created_at,
        )


class StockMovementListResponse(BaseModel):
    items: list[StockMovementResponse]
    total: int
