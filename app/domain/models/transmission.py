from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.domain.enums import TransmissionStatus


@dataclass(slots=True)
class Transmission:
    id: UUID
    invoice_id: UUID
    status: TransmissionStatus
    attempt_no: int
    created_at: datetime
