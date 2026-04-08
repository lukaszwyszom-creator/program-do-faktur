from __future__ import annotations

import uuid
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.models.stock import (
    MovementType,
    Product,
    Stock,
    StockMovement,
    Warehouse,
)
from app.persistence.models.stock import (
    ProductORM,
    StockMovementORM,
    StockORM,
    WarehouseORM,
)


class StockRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    # ── Warehouse ─────────────────────────────────────────────────────────────

    def get_default_warehouse(self) -> Warehouse | None:
        orm = self.session.execute(
            select(WarehouseORM).where(WarehouseORM.is_default.is_(True))
        ).scalar_one_or_none()
        return self._warehouse_to_domain(orm) if orm else None

    def get_warehouse(self, warehouse_id: UUID) -> Warehouse | None:
        orm = self.session.get(WarehouseORM, warehouse_id)
        return self._warehouse_to_domain(orm) if orm else None

    # ── Product ───────────────────────────────────────────────────────────────

    def get_product(self, product_id: UUID) -> Product | None:
        orm = self.session.get(ProductORM, product_id)
        return self._product_to_domain(orm) if orm else None

    def add_product(self, product: Product) -> Product:
        orm = ProductORM(
            id=product.id,
            name=product.name,
            isbn=product.isbn,
            unit=product.unit,
        )
        self.session.add(orm)
        self.session.flush()
        return self._product_to_domain(orm)

    def list_products(self) -> list[Product]:
        rows = self.session.execute(select(ProductORM)).scalars().all()
        return [self._product_to_domain(r) for r in rows]

    # ── Stock ─────────────────────────────────────────────────────────────────

    def get_stock(self, product_id: UUID, warehouse_id: UUID) -> Stock | None:
        orm = self.session.execute(
            select(StockORM)
            .where(StockORM.product_id == product_id)
            .where(StockORM.warehouse_id == warehouse_id)
        ).scalar_one_or_none()
        return self._stock_to_domain(orm) if orm else None

    def lock_stock_for_update(self, product_id: UUID, warehouse_id: UUID) -> Stock | None:
        """SELECT … FOR UPDATE (PostgreSQL). Fallback do zwykłego SELECT dla SQLite."""
        try:
            stmt = (
                select(StockORM)
                .where(StockORM.product_id == product_id)
                .where(StockORM.warehouse_id == warehouse_id)
                .with_for_update()
            )
            orm = self.session.execute(stmt).scalar_one_or_none()
        except Exception:
            orm = self.session.execute(
                select(StockORM)
                .where(StockORM.product_id == product_id)
                .where(StockORM.warehouse_id == warehouse_id)
            ).scalar_one_or_none()

        return self._stock_to_domain(orm) if orm else None

    def get_or_create_stock(self, product_id: UUID, warehouse_id: UUID) -> StockORM:
        """Zwraca istniejący ORM lub tworzy nowy z quantity=0."""
        orm = self.session.execute(
            select(StockORM)
            .where(StockORM.product_id == product_id)
            .where(StockORM.warehouse_id == warehouse_id)
        ).scalar_one_or_none()
        if orm is None:
            orm = StockORM(
                id=uuid4(),
                product_id=product_id,
                warehouse_id=warehouse_id,
                quantity=Decimal("0"),
            )
            self.session.add(orm)
            self.session.flush()
        return orm

    def save_stock(self, stock: Stock) -> Stock:
        orm = self.session.execute(
            select(StockORM)
            .where(StockORM.product_id == stock.product_id)
            .where(StockORM.warehouse_id == stock.warehouse_id)
        ).scalar_one_or_none()
        if orm is None:
            orm = StockORM(
                id=stock.id,
                product_id=stock.product_id,
                warehouse_id=stock.warehouse_id,
                quantity=stock.quantity,
            )
            self.session.add(orm)
        else:
            orm.quantity = stock.quantity
        self.session.flush()
        return self._stock_to_domain(orm)

    def list_stock(self, warehouse_id: UUID | None = None) -> list[Stock]:
        stmt = select(StockORM)
        if warehouse_id:
            stmt = stmt.where(StockORM.warehouse_id == warehouse_id)
        rows = self.session.execute(stmt).scalars().all()
        return [self._stock_to_domain(r) for r in rows]

    # ── StockMovement ─────────────────────────────────────────────────────────

    def apply_movement(self, movement: StockMovement) -> StockMovement:
        orm = StockMovementORM(
            id=movement.id,
            product_id=movement.product_id,
            warehouse_id=movement.warehouse_id,
            movement_type=movement.movement_type.value,
            quantity=movement.quantity,
            invoice_id=movement.invoice_id,
            note=movement.note,
        )
        self.session.add(orm)
        self.session.flush()
        return movement

    def list_movements(
        self,
        product_id: UUID | None = None,
        warehouse_id: UUID | None = None,
        invoice_id: UUID | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[StockMovement]:
        stmt = select(StockMovementORM).order_by(StockMovementORM.created_at.desc())
        if product_id:
            stmt = stmt.where(StockMovementORM.product_id == product_id)
        if warehouse_id:
            stmt = stmt.where(StockMovementORM.warehouse_id == warehouse_id)
        if invoice_id:
            stmt = stmt.where(StockMovementORM.invoice_id == invoice_id)
        stmt = stmt.limit(limit).offset(offset)
        rows = self.session.execute(stmt).scalars().all()
        return [self._movement_to_domain(r) for r in rows]

    # ── Mappers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _product_to_domain(orm: ProductORM) -> Product:
        return Product(
            id=orm.id,
            name=orm.name,
            isbn=orm.isbn,
            unit=orm.unit,
            created_at=orm.created_at,
            updated_at=orm.updated_at,
        )

    @staticmethod
    def _warehouse_to_domain(orm: WarehouseORM) -> Warehouse:
        return Warehouse(
            id=orm.id,
            name=orm.name,
            is_default=orm.is_default,
            created_at=orm.created_at,
        )

    @staticmethod
    def _stock_to_domain(orm: StockORM) -> Stock:
        return Stock(
            id=orm.id,
            product_id=orm.product_id,
            warehouse_id=orm.warehouse_id,
            quantity=Decimal(str(orm.quantity)),
        )

    @staticmethod
    def _movement_to_domain(orm: StockMovementORM) -> StockMovement:
        return StockMovement(
            id=orm.id,
            product_id=orm.product_id,
            warehouse_id=orm.warehouse_id,
            movement_type=MovementType(orm.movement_type),
            quantity=Decimal(str(orm.quantity)),
            invoice_id=orm.invoice_id,
            note=orm.note,
            created_at=orm.created_at,
        )
