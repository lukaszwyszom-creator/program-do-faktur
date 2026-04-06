from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func as sa_func, select
from sqlalchemy.orm import Session, joinedload

from app.persistence.models.payment_allocation import PaymentAllocationORM


class PaymentAllocationRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def add(self, orm: PaymentAllocationORM) -> PaymentAllocationORM:
        self._session.add(orm)
        self._session.flush()
        return orm

    def reverse(self, allocation_id: UUID, reversed_by: str | UUID | None) -> PaymentAllocationORM:
        orm = self._get_orm(allocation_id)
        if orm is None:
            raise ValueError(f"Nie znaleziono alokacji {allocation_id}.")
        if orm.is_reversed:
            raise ValueError("Alokacja już została cofnięta.")
        orm.is_reversed = True
        orm.reversed_at = datetime.now(UTC)
        orm.reversed_by = uuid.UUID(reversed_by) if isinstance(reversed_by, str) else reversed_by
        self._session.flush()
        return orm

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_by_id(self, allocation_id: UUID) -> PaymentAllocationORM | None:
        return self._get_orm(allocation_id)

    def list_for_invoice(self, invoice_id: UUID) -> list[PaymentAllocationORM]:
        """Zwraca aktywne (niercofnięte) alokacje dla faktury wraz z transakcją."""
        stmt = (
            select(PaymentAllocationORM)
            .options(joinedload(PaymentAllocationORM.transaction))
            .where(
                PaymentAllocationORM.invoice_id == invoice_id,
                PaymentAllocationORM.is_reversed.is_(False),
            )
            .order_by(PaymentAllocationORM.created_at.desc())
        )
        return list(self._session.execute(stmt).unique().scalars().all())

    def list_for_invoice_all(self, invoice_id: UUID) -> list[PaymentAllocationORM]:
        """Zwraca wszystkie alokacje (łącznie z cofniętymi) — historia."""
        stmt = (
            select(PaymentAllocationORM)
            .options(joinedload(PaymentAllocationORM.transaction))
            .where(PaymentAllocationORM.invoice_id == invoice_id)
            .order_by(PaymentAllocationORM.created_at.desc())
        )
        return list(self._session.execute(stmt).unique().scalars().all())

    def list_active_for_transaction(self, transaction_id: UUID) -> list[PaymentAllocationORM]:
        stmt = (
            select(PaymentAllocationORM)
            .where(
                PaymentAllocationORM.transaction_id == transaction_id,
                PaymentAllocationORM.is_reversed.is_(False),
            )
        )
        return list(self._session.execute(stmt).scalars().all())

    def sum_allocated_for_invoice(self, invoice_id: UUID) -> Decimal:
        stmt = (
            select(sa_func.coalesce(sa_func.sum(PaymentAllocationORM.allocated_amount), 0))
            .where(
                PaymentAllocationORM.invoice_id == invoice_id,
                PaymentAllocationORM.is_reversed.is_(False),
            )
        )
        return Decimal(str(self._session.execute(stmt).scalar_one()))

    def sum_allocated_for_transaction(self, transaction_id: UUID) -> Decimal:
        stmt = (
            select(sa_func.coalesce(sa_func.sum(PaymentAllocationORM.allocated_amount), 0))
            .where(
                PaymentAllocationORM.transaction_id == transaction_id,
                PaymentAllocationORM.is_reversed.is_(False),
            )
        )
        return Decimal(str(self._session.execute(stmt).scalar_one()))

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _get_orm(self, allocation_id: UUID) -> PaymentAllocationORM | None:
        stmt = select(PaymentAllocationORM).where(PaymentAllocationORM.id == allocation_id)
        return self._session.execute(stmt).scalar_one_or_none()
