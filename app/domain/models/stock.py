from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID


class MovementType(str, Enum):
    PURCHASE = "PURCHASE"
    SALE = "SALE"
    ADJUSTMENT = "ADJUSTMENT"
    TRANSFER = "TRANSFER"


@dataclass(slots=True)
class Product:
    id: UUID
    name: str
    isbn: str | None
    unit: str
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True)
class Warehouse:
    id: UUID
    name: str
    is_default: bool
    created_at: datetime


@dataclass(slots=True)
class Stock:
    id: UUID
    product_id: UUID
    warehouse_id: UUID
    quantity: Decimal

    def validate_stock_not_negative(self) -> None:
        if self.quantity < Decimal("0"):
            raise ValueError(
                f"Stan magazynowy produktu {self.product_id} "
                f"nie może być ujemny (aktualnie: {self.quantity})."
            )

    def apply_movement(self, movement: StockMovement) -> None:
        if movement.movement_type in (MovementType.PURCHASE, MovementType.ADJUSTMENT):
            self.quantity += movement.quantity
        elif movement.movement_type == MovementType.SALE:
            self.quantity -= movement.quantity
            self.validate_stock_not_negative()
        elif movement.movement_type == MovementType.TRANSFER:
            # TRANSFER: ujemna ilość oznacza rozchód (magazyn źródłowy)
            self.quantity += movement.quantity
            self.validate_stock_not_negative()


@dataclass(slots=True)
class StockMovement:
    id: UUID
    product_id: UUID
    warehouse_id: UUID
    movement_type: MovementType
    quantity: Decimal
    invoice_id: UUID | None
    note: str | None
    created_at: datetime
