from __future__ import annotations

from datetime import date
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.models.invoice import Invoice
from app.persistence.mappers.invoice_mapper import InvoiceMapper
from app.persistence.models.invoice import InvoiceORM


class InvoiceRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_id(self, invoice_id: UUID) -> Invoice | None:
        orm = self.session.get(InvoiceORM, invoice_id)
        if orm is None:
            return None
        return InvoiceMapper.to_domain(orm)

    def lock_for_update(self, invoice_id: UUID) -> Invoice | None:
        """Pobiera fakturę z blokadą FOR UPDATE (tylko PostgreSQL).
        W SQLite działa bez blokady.
        """
        try:
            stmt = (
                select(InvoiceORM)
                .where(InvoiceORM.id == invoice_id)
                .with_for_update()
            )
            orm = self.session.execute(stmt).scalar_one_or_none()
        except Exception:
            # SQLite nie obsługuje FOR UPDATE — fallback
            orm = self.session.get(InvoiceORM, invoice_id)

        if orm is None:
            return None
        return InvoiceMapper.to_domain(orm)

    def add(self, invoice: Invoice) -> Invoice:
        orm = InvoiceMapper.to_orm(invoice)
        self.session.add(orm)
        self.session.flush()
        return InvoiceMapper.to_domain(orm)

    def update(self, invoice_id: UUID, invoice: Invoice) -> Invoice:
        orm = self.session.get(InvoiceORM, invoice_id)
        if orm is None:
            from app.core.exceptions import NotFoundError
            raise NotFoundError(f"Nie znaleziono faktury {invoice_id}.")
        InvoiceMapper.update_orm(orm, invoice)
        self.session.flush()
        return InvoiceMapper.to_domain(orm)

    def list_paginated(
        self,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
        issue_date_from: date | None = None,
        issue_date_to: date | None = None,
        number_filter: str | None = None,
    ) -> tuple[list[Invoice], int]:
        base_stmt = select(InvoiceORM)

        if status is not None:
            base_stmt = base_stmt.where(InvoiceORM.status == status)
        if issue_date_from is not None:
            base_stmt = base_stmt.where(InvoiceORM.issue_date >= issue_date_from)
        if issue_date_to is not None:
            base_stmt = base_stmt.where(InvoiceORM.issue_date <= issue_date_to)
        if number_filter is not None:
            base_stmt = base_stmt.where(
                InvoiceORM.number_local.ilike(f"%{number_filter}%")
            )

        count_stmt = select(func.count()).select_from(base_stmt.subquery())
        total = self.session.execute(count_stmt).scalar_one()

        data_stmt = (
            base_stmt
            .order_by(InvoiceORM.created_at.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
        rows = list(self.session.execute(data_stmt).scalars())
        return [InvoiceMapper.to_domain(orm) for orm in rows], total

    def exists_by_number(self, number_local: str) -> bool:
        stmt = select(
            select(InvoiceORM).where(InvoiceORM.number_local == number_local).exists()
        )
        return bool(self.session.execute(stmt).scalar())

    def get_next_sequence_number(self, year: int, month: int) -> int:
        """Zlicza faktury w danym miesiącu i zwraca następny numer sekwencyjny."""
        from datetime import date as _date
        month_start = _date(year, month, 1)
        if month == 12:
            month_end = _date(year + 1, 1, 1)
        else:
            month_end = _date(year, month + 1, 1)

        stmt = select(func.count(InvoiceORM.id)).where(
            InvoiceORM.issue_date >= month_start,
            InvoiceORM.issue_date < month_end,
            InvoiceORM.number_local.isnot(None),
        )
        count = self.session.execute(stmt).scalar_one()
        return count + 1

    def list_all(self) -> list:
        """Zwraca wszystkie faktury jako obiekty ORM (do matchingu płatności)."""
        stmt = select(InvoiceORM).order_by(InvoiceORM.issue_date.desc())
        return list(self.session.execute(stmt).scalars())
