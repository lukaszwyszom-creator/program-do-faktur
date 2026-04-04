from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID

from app.domain.enums import InvoiceStatus


@dataclass(slots=True)
class Invoice:
    id: UUID
    status: InvoiceStatus
    issue_date: date
    sale_date: date
    created_at: datetime
