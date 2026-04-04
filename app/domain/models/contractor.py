from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.domain.enums import ContractorSource


@dataclass(slots=True)
class Contractor:
    id: UUID
    nip: str
    name: str
    source: ContractorSource
    source_fetched_at: datetime | None = None
