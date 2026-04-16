"""KSeF 2.0 — uwierzytelnienie tokenem KSeF z szyfrowaniem RSA-OAEP.

Przepływ uwierzytelnienia:
  1. POST /auth/challenge          → {challenge, timestampMs, ...}
  2. Szyfrowanie tokena:           KSEF_TOKEN|timestampMs → RSA-OAEP(SHA-256)
  3. POST /auth/ksef-token         → {referenceNumber, authenticationToken}
  4. POST /auth/token/redeem       → {accessToken, refreshToken}
  5. POST /sessions/online         → w KSeFClient (wymagany accessToken)
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from datetime import datetime

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.x509 import load_der_x509_certificate

logger = logging.getLogger(__name__)

_KSEF_URLS = {
    "test": "https://api-test.ksef.mf.gov.pl/v2",
    "production": "https://api.ksef.mf.gov.pl/v2",
}

_USAGE_TOKEN_ENCRYPTION = "KsefTokenEncryption"


class KSeFAuthError(Exception):
    """Błąd uwierzytelnienia w KSeF."""


@dataclass
class KSeFSession:
    """Tokeny dostępowe zwrócone po pomyślnym uwierzytelnieniu."""

    access_token: str
    refresh_token: str
    access_valid_until: datetime | None
    refresh_valid_until: datetime | None


class KSeFAuthProvider:
    def __init__(self, environment: str, timeout_seconds: int = 30) -> None:
        self.environment = environment
        self._base_url = _KSEF_URLS.get(environment, _KSEF_URLS["test"])
        self._timeout = timeout_seconds

    # -------------------------------------------------------------------------
    # PUBLIC API
    # -------------------------------------------------------------------------

    def get_tokens(self, nip: str, ksef_auth_token: str) -> KSeFSession:
        """Pełny przepływ uwierzytelnienia — zwraca parę access/refresh tokenów."""
        challenge_data = self._get_challenge()
        encrypted = self._encrypt_token(ksef_auth_token, challenge_data["timestampMs"])
        auth_init = self._init_token_auth(nip, challenge_data["challenge"], encrypted)
        return self._redeem_tokens(auth_init["authenticationToken"]["token"])

    def refresh_access_token(self, refresh_token: str) -> KSeFSession:
        """Odświeżenie access tokena przy użyciu refresh tokena."""
        url = f"{self._base_url}/auth/token/refresh"
        try:
            resp = httpx.post(
                url,
                headers={"Authorization": f"Bearer {refresh_token}"},
                timeout=self._timeout,
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as exc:
            raise KSeFAuthError(
                f"KSeF token refresh error ({exc.response.status_code}): "
                f"{exc.response.text[:300]}"
            ) from exc
        except httpx.RequestError as exc:
            raise KSeFAuthError(f"KSeF connection error: {exc}") from exc

        return KSeFSession(
            access_token=data["accessToken"]["token"],
            refresh_token=refresh_token,
            access_valid_until=_parse_dt(data["accessToken"].get("validUntil")),
            refresh_valid_until=None,
        )

    # -------------------------------------------------------------------------
    # INTERNAL HELPERS
    # -------------------------------------------------------------------------

    def _get_challenge(self) -> dict:
        """POST /auth/challenge — brak ciała żądania."""
        url = f"{self._base_url}/auth/challenge"
        try:
            resp = httpx.post(url, timeout=self._timeout)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as exc:
            raise KSeFAuthError(
                f"KSeF challenge error ({exc.response.status_code}): "
                f"{exc.response.text[:300]}"
            ) from exc
        except httpx.RequestError as exc:
            raise KSeFAuthError(f"KSeF connection error: {exc}") from exc

    def _fetch_token_encryption_key(self) -> bytes:
        """Pobiera klucz publiczny MF do szyfrowania tokena (DER)."""
        url = f"{self._base_url}/security/public-key-certificates"
        try:
            resp = httpx.get(url, timeout=self._timeout)
            resp.raise_for_status()
            certs = resp.json()
        except httpx.HTTPStatusError as exc:
            raise KSeFAuthError(
                f"KSeF public key fetch error ({exc.response.status_code}): "
                f"{exc.response.text[:300]}"
            ) from exc
        except httpx.RequestError as exc:
            raise KSeFAuthError(f"KSeF connection error: {exc}") from exc

        for cert_info in certs:
            if _USAGE_TOKEN_ENCRYPTION in cert_info.get("usage", []):
                return base64.b64decode(cert_info["certificate"])

        raise KSeFAuthError(
            f"Nie znaleziono certyfikatu KSeF o użyciu '{_USAGE_TOKEN_ENCRYPTION}'."
        )

    def _encrypt_token(self, ksef_token: str, timestamp_ms: int) -> str:
        """Szyfruje token RSA-OAEP (SHA-256) i koduje w Base64."""
        cert_der = self._fetch_token_encryption_key()
        cert = load_der_x509_certificate(cert_der)
        public_key = cert.public_key()

        plaintext = f"{ksef_token}|{timestamp_ms}".encode("utf-8")
        encrypted = public_key.encrypt(
            plaintext,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None,
            ),
        )
        return base64.b64encode(encrypted).decode("ascii")

    def _init_token_auth(
        self, nip: str, challenge: str, encrypted_token: str
    ) -> dict:
        """POST /auth/ksef-token — inicjuje uwierzytelnienie tokenem."""
        url = f"{self._base_url}/auth/ksef-token"
        payload = {
            "challenge": challenge,
            "contextIdentifier": {"type": "Nip", "value": nip},
            "encryptedToken": encrypted_token,
        }
        try:
            resp = httpx.post(url, json=payload, timeout=self._timeout)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as exc:
            raise KSeFAuthError(
                f"KSeF init token error ({exc.response.status_code}): "
                f"{exc.response.text[:300]}"
            ) from exc
        except httpx.RequestError as exc:
            raise KSeFAuthError(f"KSeF connection error: {exc}") from exc

    def _redeem_tokens(self, authentication_token: str) -> KSeFSession:
        """POST /auth/token/redeem — wymienia authenticationToken na access/refresh."""
        url = f"{self._base_url}/auth/token/redeem"
        try:
            resp = httpx.post(
                url,
                headers={"Authorization": f"Bearer {authentication_token}"},
                timeout=self._timeout,
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as exc:
            raise KSeFAuthError(
                f"KSeF token redeem error ({exc.response.status_code}): "
                f"{exc.response.text[:300]}"
            ) from exc
        except httpx.RequestError as exc:
            raise KSeFAuthError(f"KSeF connection error: {exc}") from exc

        return KSeFSession(
            access_token=data["accessToken"]["token"],
            refresh_token=data["refreshToken"]["token"],
            access_valid_until=_parse_dt(data["accessToken"].get("validUntil")),
            refresh_valid_until=_parse_dt(data["refreshToken"].get("validUntil")),
        )


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
