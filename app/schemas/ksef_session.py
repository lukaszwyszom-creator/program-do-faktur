"""Schematy request/response dla sesji KSeF."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class OpenSessionRequest(BaseModel):
    nip: str = Field(..., min_length=10, max_length=10, pattern=r"^\d{10}$")


class KSeFSessionResponse(BaseModel):
    id: UUID
    nip: str
    environment: str
    auth_method: str
    session_reference: str | None
    status: str
    expires_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CloseSessionResponse(BaseModel):
    id: UUID
    status: str
    session_reference: str | None

    model_config = {"from_attributes": True}
