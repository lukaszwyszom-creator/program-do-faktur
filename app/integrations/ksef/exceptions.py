"""
Hierarchia wyjątków integracji KSeF.

KSeFError
├── KSeFClientError      — błąd HTTP / sieciowy (w client.py, tu re-exportowany)
├── KSeFAuthError        — błąd autoryzacji (w auth.py, tu re-exportowany)
├── KSeFMappingError     — błąd budowania XML z modelu faktury (FA(3))
└── KSeFSessionError     — sesja KSeF brakująca lub wygasła
"""

from __future__ import annotations


class KSeFError(Exception):
    """Bazowy wyjątek dla wszystkich błędów integracji KSeF."""


class KSeFMappingError(KSeFError):
    """Nie można zmapować modelu faktury do XML FA(3) — błąd kontraktu adaptera."""


class KSeFSessionError(KSeFError):
    """Brak aktywnej sesji KSeF lub sesja wygasła."""


# Re-eksporty dla wygodnego importu z jednego miejsca
from app.integrations.ksef.client import KSeFClientError  # noqa: E402
from app.integrations.ksef.auth import KSeFAuthError  # noqa: E402

__all__ = [
    "KSeFError",
    "KSeFClientError",
    "KSeFAuthError",
    "KSeFMappingError",
    "KSeFSessionError",
]
