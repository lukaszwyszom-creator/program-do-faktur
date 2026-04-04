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

    def add(self, transmission: TransmissionORM) -> TransmissionORM:
        self.session.add(transmission)
        self.session.flush()
        return transmission
