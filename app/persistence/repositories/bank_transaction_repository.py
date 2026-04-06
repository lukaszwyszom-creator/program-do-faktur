from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.enums import PaymentMatchStatus
from app.domain.models.payment import BankTransaction
from app.persistence.models.bank_transaction import BankTransactionORM


class BankTransactionRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def add(self, orm: BankTransactionORM) -> BankTransactionORM:
        self._session.add(orm)
        self._session.flush()
        return orm

    def add_all(self, orms: list[BankTransactionORM]) -> list[BankTransactionORM]:
        for orm in orms:
            self._session.add(orm)
        self._session.flush()
        return orms

    def update_match_status(
        self,
        transaction_id: UUID,
        match_status: PaymentMatchStatus,
        remaining_amount: Decimal,
    ) -> None:
        orm = self._get_orm(transaction_id)
        if orm is None:
            raise ValueError(f"Nie znaleziono transakcji {transaction_id}.")
        orm.match_status = match_status.value
        orm.remaining_amount = remaining_amount
        self._session.flush()

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_by_id(self, transaction_id: UUID) -> BankTransactionORM | None:
        return self._get_orm(transaction_id)

    def get_by_external_id(self, external_id: str) -> BankTransactionORM | None:
        stmt = select(BankTransactionORM).where(BankTransactionORM.external_id == external_id)
        return self._session.execute(stmt).scalar_one_or_none()

    def list_unmatched_paginated(
        self,
        page: int,
        size: int,
        match_status: str | None = None,
    ) -> tuple[list[BankTransactionORM], int]:
        base_filter = (
            BankTransactionORM.match_status == match_status
            if match_status
            else BankTransactionORM.match_status.in_(
                [PaymentMatchStatus.UNMATCHED.value, PaymentMatchStatus.PARTIAL.value,
                 PaymentMatchStatus.MANUAL_REVIEW.value]
            )
        )
        count_stmt = select(func.count()).select_from(BankTransactionORM).where(base_filter)
        data_stmt = (
            select(BankTransactionORM)
            .where(base_filter)
            .order_by(BankTransactionORM.transaction_date.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
        total: int = self._session.execute(count_stmt).scalar_one()
        rows = self._session.execute(data_stmt).scalars().all()
        return list(rows), total

    def list_all_paginated(self, page: int, size: int) -> tuple[list[BankTransactionORM], int]:
        count_stmt = select(func.count()).select_from(BankTransactionORM)
        data_stmt = (
            select(BankTransactionORM)
            .order_by(BankTransactionORM.transaction_date.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
        total: int = self._session.execute(count_stmt).scalar_one()
        rows = self._session.execute(data_stmt).scalars().all()
        return list(rows), total

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _get_orm(self, transaction_id: UUID) -> BankTransactionORM | None:
        stmt = select(BankTransactionORM).where(BankTransactionORM.id == transaction_id)
        return self._session.execute(stmt).scalar_one_or_none()
