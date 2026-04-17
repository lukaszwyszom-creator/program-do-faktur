"""KSeF 2.0 — klient HTTP do operacji na sesjach i fakturach.

Wymaga Bearer accessToken uzyskanego przez KSeFAuthProvider.get_tokens().
Faktury są szyfrowane AES-256-CBC; klucz symetryczny jest generowany przy
otwarciu sesji i przechowywany w token_metadata_json.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
import random
import time
from dataclasses import dataclass, field

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7
from cryptography.x509 import load_der_x509_certificate

logger = logging.getLogger(__name__)

# Statusy HTTP traktowane jako przejściowe (warte retry)
_TRANSIENT_STATUS_CODES = frozenset({429, 500, 502, 503, 504})

# Przyjmowane sukcesowe kody HTTP (202 dla invoice send/session open)
_SUCCESS_STATUS_CODES = frozenset({200, 201, 202})

_USAGE_SYMMETRIC_KEY = "SymmetricKeyEncryption"


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


class KSeFSessionExpiredError(KSeFClientError):
    """KSeF zwrócił 401/403 — access token wygasł lub jest nieważny."""

    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message, status_code=status_code, transient=False)


@dataclass
class KSeFOnlineSession:
    """Dane otwartej sesji interaktywnej z kluczem symetrycznym."""

    session_reference: str
    symmetric_key: bytes           # 32 bajty — AES-256
    initialization_vector: bytes   # 16 bajtów — AES-256-CBC IV
    valid_until: str | None        # ISO 8601


@dataclass
class SendInvoiceResult:
    reference_number: str
    processing_code: int = 202
    processing_description: str = "Accepted"


@dataclass
class InvoiceStatusResult:
    processing_code: int           # 200 = przyjęta, 100 = przetwarzanie, 400 = odrzucona
    processing_description: str
    ksef_reference_number: str | None
    upo: bytes | None = None
    upo_url: str | None = None


@dataclass
class ReceivedInvoiceResult:
    """Faktura odebrana z KSeF — numer referencyjny i zdekryptowany XML FA(3)."""

    ksef_reference_number: str
    xml_bytes: bytes


@dataclass
class RetryConfig:
    max_retries: int = 3
    backoff_base: float = 1.0
    backoff_max: float = 30.0


_KSEF_URLS = {
    "test": "https://api-test.ksef.mf.gov.pl/v2",
    "production": "https://api.ksef.mf.gov.pl/v2",
}

# FA(3) — kod formularza wymagany przy otwieraniu sesji interaktywnej
_FORM_CODE = {
    "systemCode": "FA (3)",
    "schemaVersion": "1-0E",
    "value": "FA",
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
    # SESSION MANAGEMENT
    # -------------------------------------------------------------------------

    def open_online_session(self, access_token: str) -> KSeFOnlineSession:
        """POST /sessions/online — otwiera sesję interaktywną FA(3).

        Generuje losowy klucz AES-256 i IV, szyfruje klucz kluczem publicznym MF
        (RSA-OAEP SHA-256), a następnie otwiera sesję interaktywną.
        """
        symmetric_key = os.urandom(32)
        iv = os.urandom(16)

        encrypted_symmetric_key = self._encrypt_symmetric_key(symmetric_key)

        resp = self._request_with_retry(
            method="POST",
            path="/sessions/online",
            headers={"Authorization": f"Bearer {access_token}"},
            json={
                "formCode": _FORM_CODE,
                "encryption": {
                    "encryptedSymmetricKey": base64.b64encode(encrypted_symmetric_key).decode("ascii"),
                    "initializationVector": base64.b64encode(iv).decode("ascii"),
                },
            },
        )
        data = resp.json()
        return KSeFOnlineSession(
            session_reference=data["referenceNumber"],
            symmetric_key=symmetric_key,
            initialization_vector=iv,
            valid_until=data.get("validUntil"),
        )

    def close_online_session(self, access_token: str, session_reference: str) -> None:
        """POST /sessions/online/{referenceNumber}/close — zamknięcie sesji."""
        try:
            self._request_with_retry(
                method="POST",
                path=f"/sessions/online/{session_reference}/close",
                headers={"Authorization": f"Bearer {access_token}"},
            )
        except KSeFClientError as exc:
            logger.warning(
                "KSeF close session failed (%s): %s",
                exc.status_code,
                exc,
            )

    # -------------------------------------------------------------------------
    # INVOICE OPERATIONS
    # -------------------------------------------------------------------------

    def send_invoice(
        self,
        access_token: str,
        session_reference: str,
        symmetric_key: bytes,
        iv: bytes,
        invoice_xml: bytes,
    ) -> SendInvoiceResult:
        """POST /sessions/online/{ref}/invoices — wysyła zaszyfrowaną fakturę."""
        encrypted_invoice = _aes_cbc_encrypt(invoice_xml, symmetric_key, iv)

        invoice_hash = base64.b64encode(hashlib.sha256(invoice_xml).digest()).decode("ascii")
        enc_invoice_hash = base64.b64encode(hashlib.sha256(encrypted_invoice).digest()).decode("ascii")

        resp = self._request_with_retry(
            method="POST",
            path=f"/sessions/online/{session_reference}/invoices",
            headers={"Authorization": f"Bearer {access_token}"},
            json={
                "invoiceHash": invoice_hash,
                "invoiceSize": len(invoice_xml),
                "encryptedInvoiceHash": enc_invoice_hash,
                "encryptedInvoiceSize": len(encrypted_invoice),
                "encryptedInvoiceContent": base64.b64encode(encrypted_invoice).decode("ascii"),
            },
        )
        data = resp.json()
        return SendInvoiceResult(reference_number=data["referenceNumber"])

    def get_invoice_status(
        self,
        access_token: str,
        session_reference: str,
        invoice_reference: str,
    ) -> InvoiceStatusResult:
        """GET /sessions/{ref}/invoices/{invoiceRef} — sprawdza status faktury.

        Mapowanie na kody przetwarzania:
          200 = KSeF przydzielił numer (ksefNumber != null)
          100 = przetwarzanie w toku
          400 = faktura odrzucona (obecna na liście failed)
        """
        resp = self._request_with_retry(
            method="GET",
            path=f"/sessions/{session_reference}/invoices/{invoice_reference}",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        data = resp.json()
        ksef_number = data.get("ksefNumber")

        if ksef_number:
            return InvoiceStatusResult(
                processing_code=200,
                processing_description="Faktura przyjęta przez KSeF",
                ksef_reference_number=ksef_number,
                upo_url=data.get("upoDownloadUrl"),
            )

        # Sprawdź listę odrzuconych
        if self._is_invoice_failed(access_token, session_reference, invoice_reference):
            return InvoiceStatusResult(
                processing_code=400,
                processing_description="Faktura odrzucona przez KSeF",
                ksef_reference_number=None,
            )

        return InvoiceStatusResult(
            processing_code=100,
            processing_description="Faktura w kolejce przetwarzania",
            ksef_reference_number=None,
        )

    def _is_invoice_failed(
        self, access_token: str, session_reference: str, invoice_reference: str
    ) -> bool:
        """Sprawdza czy faktura jest na liście odrzuconych w sesji."""
        try:
            resp = self._request_with_retry(
                method="GET",
                path=f"/sessions/{session_reference}/invoices/failed",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            data = resp.json()
            for inv in data.get("invoices", []):
                if inv.get("referenceNumber") == invoice_reference:
                    return True
        except KSeFClientError:
            pass
        return False

    def query_received_invoices(
        self,
        access_token: str,
        session_reference: str,
        symmetric_key: bytes,
        iv: bytes,
        invoicing_date_from: str,
        invoicing_date_to: str,
    ) -> list[ReceivedInvoiceResult]:
        """Pobiera faktury zakupowe (odebrane) z KSeF za podany zakres dat.

        Flow:
        1. POST /invoices/query → queryReferenceNumber (202)
        2. Poll GET /invoices/query/{queryRef} aż processingCode == 200
        3. Dla każdego ksefReferenceNumber: GET /invoices/{ref} → decrypt AES-256-CBC
        Zwraca listę ReceivedInvoiceResult (ksef_reference_number + XML bytes).
        """
        # 1. Zgłoś zapytanie
        resp = self._request_with_retry(
            method="POST",
            path="/invoices/query",
            headers={"Authorization": f"Bearer {access_token}"},
            json={
                "queryCriteria": {
                    "invoiceType": "received",
                    "subjectType": "subject2",
                    "invoicingDateFrom": invoicing_date_from,
                    "invoicingDateTo": invoicing_date_to,
                },
            },
        )
        query_ref = resp.json()["referenceNumber"]
        logger.info("KSeF query received invoices: queryRef=%s", query_ref)

        # 2. Polling — max 60s co 3s
        invoice_refs: list[str] = []
        for _attempt in range(20):
            time.sleep(3)
            try:
                poll_resp = self._request_with_retry(
                    method="GET",
                    path=f"/invoices/query/{query_ref}",
                    headers={"Authorization": f"Bearer {access_token}"},
                )
            except KSeFClientError as exc:
                if exc.status_code == 202:
                    # Jeszcze przetwarza — czekamy
                    continue
                raise
            data = poll_resp.json()
            code = data.get("processingCode", 0)
            if code == 200:
                invoice_refs = [
                    inv["ksefReferenceNumber"]
                    for inv in data.get("invoiceList", [])
                ]
                logger.info(
                    "KSeF query done: queryRef=%s, count=%d", query_ref, len(invoice_refs)
                )
                break
            if code >= 400:
                raise KSeFClientError(
                    f"KSeF query zakończone błędem: code={code}",
                    status_code=code,
                )

        # 3. Pobierz i odszyfruj każdą fakturę
        results: list[ReceivedInvoiceResult] = []
        for ref in invoice_refs:
            try:
                inv_resp = self._request_with_retry(
                    method="GET",
                    path=f"/invoices/{ref}",
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                enc_content = base64.b64decode(inv_resp.json()["encryptedInvoiceContent"])
                xml_bytes = _aes_cbc_decrypt(enc_content, symmetric_key, iv)
                results.append(ReceivedInvoiceResult(
                    ksef_reference_number=ref,
                    xml_bytes=xml_bytes,
                ))
            except Exception as exc:  # noqa: BLE001
                logger.warning("KSeF: błąd pobierania faktury %s: %s", ref, exc)

        return results

    def get_upo(self, upo_url: str) -> bytes:
        """Pobiera UPO z URL zwróconego w statusie faktury (bez uwierzytelnienia)."""
        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.get(upo_url)
            resp.raise_for_status()
            return resp.content
        except httpx.HTTPStatusError as exc:
            raise KSeFClientError(
                f"KSeF UPO download error ({exc.response.status_code}): "
                f"{exc.response.text[:200]}",
                status_code=exc.response.status_code,
            ) from exc
        except httpx.RequestError as exc:
            raise KSeFClientError(
                f"KSeF UPO connection error: {exc}",
                transient=True,
            ) from exc

    # -------------------------------------------------------------------------
    # ENCRYPTION HELPERS
    # -------------------------------------------------------------------------

    def _fetch_symmetric_key_encryption_cert(self) -> bytes:
        """Pobiera certyfikat MF do szyfrowania klucza symetrycznego (DER)."""
        url = f"{self._base_url}/security/public-key-certificates"
        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.get(url)
            resp.raise_for_status()
            certs = resp.json()
        except httpx.HTTPStatusError as exc:
            raise KSeFClientError(
                f"KSeF public key fetch error ({exc.response.status_code})",
                status_code=exc.response.status_code,
            ) from exc
        except httpx.RequestError as exc:
            raise KSeFClientError(
                f"KSeF connection error: {exc}", transient=True
            ) from exc

        for cert_info in certs:
            if _USAGE_SYMMETRIC_KEY in cert_info.get("usage", []):
                return base64.b64decode(cert_info["certificate"])

        raise KSeFClientError(
            f"Nie znaleziono certyfikatu KSeF o użyciu '{_USAGE_SYMMETRIC_KEY}'."
        )

    def _encrypt_symmetric_key(self, symmetric_key: bytes) -> bytes:
        """Szyfruje klucz symetryczny RSA-OAEP (SHA-256) kluczem publicznym MF."""
        cert_der = self._fetch_symmetric_key_encryption_cert()
        cert = load_der_x509_certificate(cert_der)
        public_key = cert.public_key()
        return public_key.encrypt(
            symmetric_key,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None,
            ),
        )

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

                if response.status_code in _SUCCESS_STATUS_CODES:
                    return response

                if response.status_code in (401, 403):
                    raise KSeFSessionExpiredError(
                        f"KSeF: token wygasł lub nieautoryzowany "
                        f"({response.status_code}): {response.text[:200]}",
                        status_code=response.status_code,
                    )

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


# -------------------------------------------------------------------------
# STANDALONE CRYPTO HELPERS
# -------------------------------------------------------------------------

def _aes_cbc_encrypt(plaintext: bytes, key: bytes, iv: bytes) -> bytes:
    """Szyfruje dane AES-256-CBC z dopełnieniem PKCS#7."""
    padder = PKCS7(128).padder()
    padded = padder.update(plaintext) + padder.finalize()
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    encryptor = cipher.encryptor()
    return encryptor.update(padded) + encryptor.finalize()


def _aes_cbc_decrypt(ciphertext: bytes, key: bytes, iv: bytes) -> bytes:
    """Odszyfrowuje dane AES-256-CBC z dopełnieniem PKCS#7."""
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    decryptor = cipher.decryptor()
    padded = decryptor.update(ciphertext) + decryptor.finalize()
    unpadder = PKCS7(128).unpadder()
    return unpadder.update(padded) + unpadder.finalize()
