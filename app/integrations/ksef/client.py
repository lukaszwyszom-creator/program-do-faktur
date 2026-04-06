from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger(__name__)

# Statusy HTTP traktowane jako przejściowe (warte retr)
_TRANSIENT_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


class KSeFClientError(Exception):
    """Błąd komunikacji z KSeF."""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        transient: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.transient = transient


@dataclass
class SendInvoiceResult:
    reference_number: str
    processing_code: int
    processing_description: str


@dataclass
class InvoiceStatusResult:
    processing_code: int
    processing_description: str
    ksef_reference_number: str | None
    upo: bytes | None


@dataclass
class RetryConfig:
    max_retries: int = 3
    backoff_base: float = 1.0
    backoff_max: float = 30.0


_KSEF_URLS = {
    "test": "https://ksef-test.mf.gov.pl/api",
    "demo": "https://ksef-demo.mf.gov.pl/api",
    "production": "https://ksef.mf.gov.pl/api",
}


class KSeFClient:
    def __init__(
        self,
        environment: str,
        timeout_seconds: int,
        retry_config: RetryConfig | None = None,
    ) -> None:
        self._base_url = _KSEF_URLS.get(environment, _KSEF_URLS["test"])
        self._timeout = timeout_seconds
        self._retry = retry_config or RetryConfig()

    # -------------------------------------------------------------------------
    # PUBLIC API
    # -------------------------------------------------------------------------

    def send_invoice(
        self, session_token: str, invoice_xml: bytes
    ) -> SendInvoiceResult:
        resp = self._request_with_retry(
            method="POST",
            path="/online/Invoice/Send",
            headers={
                "Content-Type": "application/octet-stream",
                "SessionToken": session_token,
            },
            content=invoice_xml,
        )
        data = resp.json()
        return SendInvoiceResult(
            reference_number=data["elementReferenceNumber"],
            processing_code=data["processingCode"],
            processing_description=data["processingDescription"],
        )

    def get_invoice_status(
        self, session_token: str, reference_number: str
    ) -> InvoiceStatusResult:
        resp = self._request_with_retry(
            method="GET",
            path=f"/online/Invoice/Status/{reference_number}",
            headers={"SessionToken": session_token},
        )
        data = resp.json()
        return InvoiceStatusResult(
            processing_code=data["processingCode"],
            processing_description=data["processingDescription"],
            ksef_reference_number=data.get("ksefReferenceNumber"),
            upo=data.get("upo"),
        )

    def get_upo(
        self, session_token: str, ksef_reference_number: str
    ) -> bytes:
        resp = self._request_with_retry(
            method="GET",
            path=f"/online/Invoice/GetUPO/{ksef_reference_number}",
            headers={"SessionToken": session_token},
        )
        return resp.content

    # -------------------------------------------------------------------------
    # INTERNAL RETRY LOGIC
    # -------------------------------------------------------------------------

    def _request_with_retry(
        self,
        method: str,
        path: str,
        headers: dict | None = None,
        **kwargs,
    ):
        url = self._base_url + path
        last_exc: Exception | None = None

        for attempt in range(self._retry.max_retries + 1):
            if attempt > 0:
                backoff = min(
                    self._retry.backoff_base * (2 ** (attempt - 1))
                    + random.uniform(0, 0.1 * self._retry.backoff_base),
                    self._retry.backoff_max,
                )
                logger.warning(
                    "KSeF retry: attempt=%s/%s backoff=%.2fs url=%s",
                    attempt,
                    self._retry.max_retries,
                    backoff,
                    url,
                )
                time.sleep(backoff)

            try:
                with httpx.Client(timeout=self._timeout) as client:
                    response = client.request(method, url, headers=headers, **kwargs)

                if response.status_code == 200:
                    return response

                transient = response.status_code in _TRANSIENT_STATUS_CODES
                last_exc = KSeFClientError(
                    f"KSeF odpowiedział statusem {response.status_code}: "
                    f"{response.text[:200]}",
                    status_code=response.status_code,
                    transient=transient,
                )

                if not transient:
                    raise last_exc

            except KSeFClientError:
                raise
            except httpx.TimeoutException as exc:
                last_exc = KSeFClientError(
                    f"KSeF: timeout po {self._timeout}s: {exc}",
                    transient=True,
                )
            except httpx.RequestError as exc:
                last_exc = KSeFClientError(
                    f"KSeF: błąd połączenia: {exc}",
                    transient=True,
                )

        raise last_exc or KSeFClientError(
            "KSeF: wyczerpano liczbę prób (nie powiodła się żadna).",
            transient=True,
        )
