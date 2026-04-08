from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator
import re

_NIP_RE = re.compile(r"^\d{10}$")


class SettingsResponse(BaseModel):
    """Kontrakt odpowiedzi GET /api/v1/settings."""

    # Dane sprzedawcy (edytowalne przez PUT)
    seller_nip: str | None = None
    seller_name: str | None = None
    seller_street: str | None = None
    seller_building_no: str | None = None
    seller_apartment_no: str | None = None
    seller_postal_code: str | None = None
    seller_city: str | None = None
    seller_country: str | None = "PL"

    # Dane tylko do odczytu (środowisko aplikacji)
    ksef_environment: str = "test"
    app_env: str = "local"
    app_version: str = "0.1.0"


class SettingsUpdateRequest(BaseModel):
    """Ciało żądania PUT /api/v1/settings.

    Wszystkie pola opcjonalne — klient przesyła tylko te, które chce zmienić
    (partial update).
    """

    seller_nip: str | None = Field(default=None, max_length=10)
    seller_name: str | None = Field(default=None, max_length=256)
    seller_street: str | None = Field(default=None, max_length=256)
    seller_building_no: str | None = Field(default=None, max_length=32)
    seller_apartment_no: str | None = Field(default=None, max_length=32)
    seller_postal_code: str | None = Field(default=None, max_length=16)
    seller_city: str | None = Field(default=None, max_length=128)
    seller_country: str | None = Field(default=None, max_length=2)

    @field_validator("seller_nip")
    @classmethod
    def nip_must_be_10_digits(cls, v: str | None) -> str | None:
        if v is not None and not _NIP_RE.match(v):
            raise ValueError("seller_nip musi składać się dokładnie z 10 cyfr")
        return v
