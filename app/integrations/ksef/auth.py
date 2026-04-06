from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

import httpx

logger = logging.getLogger(__name__)

_KSEF_URLS = {
    "test": "https://ksef-test.mf.gov.pl/api",
    "demo": "https://ksef-demo.mf.gov.pl/api",
    "production": "https://ksef.mf.gov.pl/api",
}


class KSeFAuthError(Exception):
    """Błąd uwierzytelnienia w KSeF."""


@dataclass
class KSeFSession:
    session_token: str
    session_reference: str
    expires_at: datetime | None


class KSeFAuthProvider:
    def __init__(self, environment: str, timeout_seconds: int = 30) -> None:
        self.environment = environment
        self._base_url = _KSEF_URLS.get(environment, _KSEF_URLS["test"])
        self._timeout = timeout_seconds

    def get_challenge(self, nip: str) -> dict:
        url = f"{self._base_url}/online/Session/AuthorisationChallenge"
        payload = {"contextIdentifier": {"type": "onip", "identifier": nip}}

        try:
            resp = httpx.post(url, json=payload, timeout=self._timeout)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as exc:
            raise KSeFAuthError(
                f"KSeF challenge error ({exc.response.status_code}): "
                f"{exc.response.text[:200]}"
            ) from exc
        except httpx.RequestError as exc:
            raise KSeFAuthError(f"KSeF connection error: {exc}") from exc

        return {
            "challenge": data["challenge"],
            "timestamp": data["timestamp"],
        }

    def init_session(
        self, nip: str, challenge: str, auth_token: str
    ) -> KSeFSession:
        url = f"{self._base_url}/online/Session/InitToken"
        payload = {
            "contextRequest": {
                "contextIdentifier": {"type": "onip", "identifier": nip}
            },
            "queryContext": {},
            "authenticationContext": {
                "contextReferenceNumber": challenge,
                "authorisationToken": auth_token,
            },
        }

        try:
            resp = httpx.post(url, json=payload, timeout=self._timeout)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as exc:
            raise KSeFAuthError(
                f"KSeF session init error ({exc.response.status_code}): "
                f"{exc.response.text[:200]}"
            ) from exc
        except httpx.RequestError as exc:
            raise KSeFAuthError(f"KSeF connection error: {exc}") from exc

        return KSeFSession(
            session_token=data["sessionToken"],
            session_reference=data["referenceNumber"],
            expires_at=None,
        )

    def terminate_session(self, session_token: str) -> None:
        url = f"{self._base_url}/online/Session/Terminate"

        try:
            resp = httpx.get(
                url,
                headers={"SessionToken": session_token},
                timeout=self._timeout,
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "KSeF terminate session failed (%s): %s",
                exc.response.status_code,
                exc.response.text[:200],
            )
        except httpx.RequestError as exc:
            logger.warning("KSeF terminate session connection error: %s", exc)
