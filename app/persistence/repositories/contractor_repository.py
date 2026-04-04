from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.persistence.models.contractor import ContractorORM


class ContractorRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_id(self, contractor_id: UUID) -> ContractorORM | None:
        return self.session.get(ContractorORM, contractor_id)

    def get_by_nip(self, nip: str) -> ContractorORM | None:
        query = select(ContractorORM).where(ContractorORM.nip == nip)
        return self.session.execute(query).scalar_one_or_none()

    def add(self, contractor: ContractorORM) -> ContractorORM:
        self.session.add(contractor)
        self.session.flush()
        return contractor

    def save(self, contractor: ContractorORM) -> ContractorORM:
        self.session.add(contractor)
        self.session.flush()
        return contractor
