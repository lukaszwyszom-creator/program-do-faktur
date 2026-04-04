from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.persistence.models.contractor_override import ContractorOverrideORM


class ContractorOverrideRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_active_by_contractor_id(self, contractor_id: UUID) -> ContractorOverrideORM | None:
        query = select(ContractorOverrideORM).where(
            ContractorOverrideORM.contractor_id == contractor_id,
            ContractorOverrideORM.is_active.is_(True),
        )
        return self.session.execute(query).scalar_one_or_none()

    def add(self, override: ContractorOverrideORM) -> ContractorOverrideORM:
        self.session.add(override)
        self.session.flush()
        return override

    def save(self, override: ContractorOverrideORM) -> ContractorOverrideORM:
        self.session.add(override)
        self.session.flush()
        return override
