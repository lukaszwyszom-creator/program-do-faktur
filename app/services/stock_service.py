from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.domain.exceptions import InvalidInvoiceError
from app.domain.models.stock import MovementType, Product, Stock, StockMovement
from app.persistence.repositories.stock_repository import StockRepository

logger = logging.getLogger(__name__)

DEFAULT_WAREHOUSE_ID = UUID("00000000-0000-0000-0000-000000000001")


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
        note: str | None = None,
    ) -> StockMovement:
        if quantity <= Decimal("0"):
            raise StockError("Ilość ruchu magazynowego musi być większa od 0.")

        resolved_warehouse_id = warehouse_id or DEFAULT_WAREHOUSE_ID

        # Weryfikacja że produkt i magazyn istnieją
        if self.repo.get_product(product_id) is None:
            raise NotFoundError(f"Produkt {product_id} nie istnieje.")
        if self.repo.get_warehouse(resolved_warehouse_id) is None:
            raise NotFoundError(f"Magazyn {resolved_warehouse_id} nie istnieje.")

        # SELECT FOR UPDATE — blokada wiersza stanu
        stock_orm = self.repo.get_or_create_stock(product_id, resolved_warehouse_id)
        stock = self.repo.lock_stock_for_update(product_id, resolved_warehouse_id)
        if stock is None:
            # Właśnie utworzony przez get_or_create_stock
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
            note=note,
            created_at=datetime.now(UTC),
        )

        # Walidacja (rzuca ValueError przy ujemnym stanie)
        try:
            stock.apply_movement(movement)
        except ValueError as exc:
            raise StockError(str(exc)) from exc

        # Persist: zaktualizuj stan i dołącz log
        self.repo.save_stock(stock)
        self.repo.apply_movement(movement)
        self.session.flush()

        logger.info(
            "stock.movement type=%s product=%s qty=%s invoice=%s",
            movement_type.value,
            product_id,
            quantity,
            invoice_id,
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
    ) -> None:
        """
        Generuje ruchy magazynowe na podstawie faktury.
        items: lista słowników z kluczami 'product_id' i 'quantity'.
        Produkty bez product_id są pomijane (pozycje usługowe).
        """
        movement_type = (
            MovementType.SALE if direction == "sale" else MovementType.PURCHASE
        )
        for item in items:
            product_id = item.get("product_id")
            if not product_id:
                continue
            try:
                self.create_movement(
                    movement_type=movement_type,
                    product_id=product_id,
                    quantity=item["quantity"],
                    warehouse_id=warehouse_id,
                    invoice_id=invoice_id,
                    note=f"Auto: faktura {invoice_id}",
                )
            except NotFoundError:
                # Produkt nie istnieje w magazynie — pomijamy (brak obowiązku śledzenia)
                logger.debug("stock: produkt %s nie istnieje w magazynie, pomijam.", product_id)
