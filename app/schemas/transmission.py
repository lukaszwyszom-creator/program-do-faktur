from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class TransmissionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    invoice_id: UUID
    channel: str
    operation_type: str
    status: str
    attempt_no: int
    idempotency_key: str | None = None
    external_reference: str | None = None
    ksef_reference_number: str | None = None
    upo_status: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime


class KSeFStatusResponse(BaseModel):
    """Zwięzły widok wyniku integracji KSeF dla danej transmisji.

    Semantyka pól:
    - ksef_reference_number: finalny numer KSeF (non-null tylko gdy status='success')
    - upo_status:  'fetched' | 'failed' | None
    - is_final:    True gdy status jest terminalny (success / failed_permanent)
    """
    transmission_id: UUID
    invoice_id: UUID
    status: str
    ksef_reference_number: str | None
    upo_status: str | None
    is_final: bool


class TransmissionListResponse(BaseModel):
    items: list[TransmissionResponse]
    invoice_id: UUID


class TransmissionPageResponse(BaseModel):
    items: list[TransmissionResponse]
    total: int
    page: int
    size: int


class RetryTransmissionResponse(BaseModel):
    transmission_id: UUID
    attempt_no: int
    status: str


class SubmitInvoiceResponse(BaseModel):
    transmission_id: UUID
    invoice_id: UUID
    status: str
