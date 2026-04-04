from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class TransmissionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    invoice_id: UUID
    status: str
    attempt_no: int
    created_at: datetime


class RetryTransmissionResponse(BaseModel):
    transmission_id: UUID
    status: str
