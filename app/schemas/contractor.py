from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class ContractorManualCreateRequest(BaseModel):
    nip: str
    name: str
    city: str
    postal_code: str
    street: str | None = None
    building_no: str | None = None
    apartment_no: str | None = None


class ContractorOverrideRequest(BaseModel):
    name: str | None = None
    legal_form: str | None = None
    street: str | None = None
    building_no: str | None = None
    apartment_no: str | None = None
    postal_code: str | None = None
    city: str | None = None
    county: str | None = None
    commune: str | None = None
    voivodeship: str | None = None
    override_reason: str | None = None


class ContractorResponse(BaseModel):
    id: UUID
    nip: str
    regon: str | None = None
    krs: str | None = None
    name: str
    legal_form: str | None = None
    street: str | None = None
    building_no: str | None = None
    apartment_no: str | None = None
    postal_code: str | None = None
    city: str | None = None
    voivodeship: str | None = None
    county: str | None = None
    commune: str | None = None
    country: str | None = None
    status: str | None = None
    source: str
    source_fetched_at: datetime | None = None
    cache_valid_until: datetime | None = None
    lookup_last_status: str | None = None
    lookup_last_error: str | None = None
    has_override: bool
