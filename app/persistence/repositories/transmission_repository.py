from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.persistence.models.transmission import TransmissionORM


class TransmissionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_id(self, transmission_id: UUID) -> TransmissionORM | None:
        return self.session.get(TransmissionORM, transmission_id)

    def lock_for_update(self, transmission_id: UUID) -> TransmissionORM | None:
        """Pobiera transmisję z blokadą FOR UPDATE (tylko PostgreSQL).
        W SQLite działa bez blokady (fallback do zwykłego get).
        """
        try:
            stmt = (
                select(TransmissionORM)
                .where(TransmissionORM.id == transmission_id)
                .with_for_update()
            )
            return self.session.execute(stmt).scalar_one_or_none()
        except Exception:
            return self.session.get(TransmissionORM, transmission_id)

    def list_for_invoice(self, invoice_id: UUID) -> list[TransmissionORM]:
        query = (
            select(TransmissionORM)
            .where(TransmissionORM.invoice_id == invoice_id)
            .order_by(TransmissionORM.created_at.desc(), TransmissionORM.attempt_no.desc())
        )
        return list(self.session.execute(query).scalars())

    def get_active_for_invoice(self, invoice_id: UUID, active_statuses: Sequence[str]) -> TransmissionORM | None:
        query = (
            select(TransmissionORM)
            .where(TransmissionORM.invoice_id == invoice_id, TransmissionORM.status.in_(active_statuses))
            .order_by(TransmissionORM.created_at.desc(), TransmissionORM.attempt_no.desc())
        )
        return self.session.execute(query).scalar_one_or_none()

    def list_all_paginated(self, page: int, size: int) -> tuple[list[TransmissionORM], int]:
        from sqlalchemy import func

        offset = (page - 1) * size
        total_stmt = select(func.count()).select_from(TransmissionORM)
        total: int = self.session.execute(total_stmt).scalar_one()
        items_stmt = (
            select(TransmissionORM)
            .order_by(TransmissionORM.created_at.desc())
            .offset(offset)
            .limit(size)
        )
        items = list(self.session.execute(items_stmt).scalars())
        return items, total

    def add(self, transmission: TransmissionORM) -> TransmissionORM:
        self.session.add(transmission)
        self.session.flush()
        return transmission
