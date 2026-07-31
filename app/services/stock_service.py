from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.domain.exceptions import InvalidInvoiceError
from app.domain.models.stock import MovementType, Product, Stock, StockMovement
from app.persistence.repositories.stock_repository import StockRepository

logger = logging.getLogger(__name__)

DEFAULT_WAREHOUSE_ID = UUID("00000000-0000-0000-0000-000000000001")

# TRANSFER wycofany z API do czasu pełnej implementacji dwustronnej.
_DISABLED_MOVEMENT_TYPES = frozenset({MovementType.TRANSFER})


class StockError(InvalidInvoiceError):
    code = "stock_error"


class StockService:
    def __init__(self, session: Session, stock_repository: StockRepository) -> None:
        self.session = session
        self.repo = stock_repository

    # ── Products ──────────────────────────────────────────────────────────────

    def create_product(self, name: str, isbn: str | None, unit: str) -> Product:
        now = datetime.now(UTC)
        product = Product(
            id=uuid4(),
            name=name,
            isbn=isbn,
            unit=unit,
            created_at=now,
            updated_at=now,
        )
        return self.repo.add_product(product)

    def list_products(self) -> list[Product]:
        return self.repo.list_products()

    def get_product(self, product_id: UUID) -> Product:
        product = self.repo.get_product(product_id)
        if product is None:
            raise NotFoundError(f"Produkt {product_id} nie istnieje.")
        return product

    # ── Stock ─────────────────────────────────────────────────────────────────

    def list_stock(self, warehouse_id: UUID | None = None) -> list[Stock]:
        return self.repo.list_stock(warehouse_id=warehouse_id)

    # ── Movements ─────────────────────────────────────────────────────────────

    def create_movement(
        self,
        movement_type: MovementType,
        product_id: UUID,
        quantity: Decimal,
        warehouse_id: UUID | None = None,
        invoice_id: UUID | None = None,
        invoice_item_id: UUID | None = None,
        note: str | None = None,
        *,
        skip_if_duplicate: bool = False,
    ) -> StockMovement | None:
        if movement_type in _DISABLED_MOVEMENT_TYPES:
            raise StockError(
                "Typ ruchu TRANSFER jest tymczasowo niedostępny — "
                "użyj osobnych ruchów PURCHASE/SALE lub ADJUSTMENT."
            )

        if quantity <= Decimal("0"):
            raise StockError("Ilość ruchu magazynowego musi być większa od 0.")

        resolved_warehouse_id = warehouse_id or DEFAULT_WAREHOUSE_ID

        if self.repo.get_product(product_id) is None:
            raise NotFoundError(f"Produkt {product_id} nie istnieje.")
        if self.repo.get_warehouse(resolved_warehouse_id) is None:
            raise NotFoundError(f"Magazyn {resolved_warehouse_id} nie istnieje.")

        if invoice_item_id is not None:
            existing = self.repo.find_movement_by_invoice_item(
                invoice_item_id=invoice_item_id,
                movement_type=movement_type,
            )
            if existing is not None:
                if skip_if_duplicate:
                    logger.info(
                        "stock.movement skip duplicate item=%s type=%s",
                        invoice_item_id,
                        movement_type.value,
                    )
                    return existing
                raise StockError(
                    f"Ruch {movement_type.value} dla pozycji faktury "
                    f"{invoice_item_id} już istnieje."
                )

        stock_orm = self.repo.get_or_create_stock(product_id, resolved_warehouse_id)
        stock = self.repo.lock_stock_for_update(product_id, resolved_warehouse_id)
        if stock is None:
            stock = Stock(
                id=stock_orm.id,
                product_id=product_id,
                warehouse_id=resolved_warehouse_id,
                quantity=Decimal("0"),
            )

        movement = StockMovement(
            id=uuid4(),
            product_id=product_id,
            warehouse_id=resolved_warehouse_id,
            movement_type=movement_type,
            quantity=quantity,
            invoice_id=invoice_id,
            invoice_item_id=invoice_item_id,
            note=note,
            created_at=datetime.now(UTC),
        )

        try:
            stock.apply_movement(movement)
        except ValueError as exc:
            raise StockError(str(exc)) from exc

        self.repo.save_stock(stock)
        try:
            with self.session.begin_nested():
                self.repo.apply_movement(movement)
                self.session.flush()
        except IntegrityError:
            # Race: inny request wstawił ten sam (invoice_item_id, type) — bez rollback całej faktury
            if skip_if_duplicate and invoice_item_id is not None:
                existing = self.repo.find_movement_by_invoice_item(
                    invoice_item_id=invoice_item_id,
                    movement_type=movement_type,
                )
                if existing is not None:
                    return existing
            raise StockError(
                f"Konflikt idempotencji ruchu magazynowego "
                f"(item={invoice_item_id}, type={movement_type.value})."
            ) from None

        logger.info(
            "stock.movement type=%s product=%s qty=%s invoice=%s item=%s",
            movement_type.value,
            product_id,
            quantity,
            invoice_id,
            invoice_item_id,
        )
        return movement

    def list_movements(
        self,
        product_id: UUID | None = None,
        warehouse_id: UUID | None = None,
        invoice_id: UUID | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[StockMovement]:
        return self.repo.list_movements(
            product_id=product_id,
            warehouse_id=warehouse_id,
            invoice_id=invoice_id,
            limit=limit,
            offset=offset,
        )

    # ── Integracja z fakturami ────────────────────────────────────────────────

    def handle_invoice_created(
        self,
        invoice_id: UUID,
        direction: str,
        items: list[dict],
        warehouse_id: UUID | None = None,
    ) -> list[StockMovement]:
        """
        Generuje ruchy magazynowe na podstawie faktury.
        items: dict z kluczami product_id, quantity, invoice_item_id.
        Pozycje bez product_id są pomijane (usługowe).
        Idempotentne: ponowne wywołanie nie dubluje ruchów.
        """
        movement_type = (
            MovementType.SALE if direction == "sale" else MovementType.PURCHASE
        )
        created: list[StockMovement] = []
        for item in items:
            product_id = item.get("product_id")
            if not product_id:
                continue
            invoice_item_id = item.get("invoice_item_id")
            quantity = Decimal(str(item["quantity"]))
            movement = self.create_movement(
                movement_type=movement_type,
                product_id=product_id,
                quantity=quantity,
                warehouse_id=warehouse_id,
                invoice_id=invoice_id,
                invoice_item_id=invoice_item_id,
                note=f"Auto: faktura {invoice_id}",
                skip_if_duplicate=True,
            )
            if movement is not None:
                created.append(movement)
        return created

    def reverse_invoice_stock_movements(
        self,
        invoice_id: UUID,
        *,
        warehouse_id: UUID | None = None,
        note: str | None = None,
    ) -> list[StockMovement]:
        """
        Odwraca pierwotne ruchy faktury bez kasowania historii.
        SALE → PURCHASE (przywrócenie stanu), PURCHASE → SALE.
        Idempotentne względem (invoice_item_id, reverse_type).
        """
        original = self.repo.list_movements(invoice_id=invoice_id, limit=500, offset=0)
        # Tylko pierwotne kierunki księgowania (nie odwrócenia ADJUSTMENT)
        bookable = [
            m for m in original
            if m.movement_type in (MovementType.SALE, MovementType.PURCHASE)
            and m.invoice_item_id is not None
        ]
        # Unikaj ponownego odwracania: jeśli dla itemu istnieje już ruch odwrotny, skip
        reversed_movements: list[StockMovement] = []
        for movement in bookable:
            reverse_type = (
                MovementType.PURCHASE
                if movement.movement_type == MovementType.SALE
                else MovementType.SALE
            )
            # Nie odwracaj ruchów, które same są już odwróceniem
            # (jeśli mamy SALE i PURCHASE dla tego samego itemu — para zamknięta)
            pair = self.repo.find_movement_by_invoice_item(
                invoice_item_id=movement.invoice_item_id,
                movement_type=reverse_type,
            )
            if pair is not None:
                continue
            # Odwracamy tylko „pierwotny” kierunek faktury: jeśli istnieje tylko jeden typ
            result = self.create_movement(
                movement_type=reverse_type,
                product_id=movement.product_id,
                quantity=movement.quantity,
                warehouse_id=warehouse_id or movement.warehouse_id,
                invoice_id=invoice_id,
                invoice_item_id=movement.invoice_item_id,
                note=note or f"Odwrócenie: faktura {invoice_id}",
                skip_if_duplicate=True,
            )
            if result is not None:
                reversed_movements.append(result)
        return reversed_movements
