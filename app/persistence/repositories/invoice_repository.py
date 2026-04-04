from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.persistence.models.invoice import InvoiceORM


class InvoiceRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_id(self, invoice_id: UUID) -> InvoiceORM | None:
        return self.session.get(InvoiceORM, invoice_id)

    def add(self, invoice: InvoiceORM) -> InvoiceORM:
        self.session.add(invoice)
        self.session.flush()
        return invoice

    def list_by_status(self, status: str) -> list[InvoiceORM]:
        query = select(InvoiceORM).where(InvoiceORM.status == status).order_by(InvoiceORM.created_at.desc())
        return list(self.session.execute(query).scalars())
