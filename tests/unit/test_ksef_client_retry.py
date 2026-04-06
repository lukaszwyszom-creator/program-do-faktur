"""Testy KSeFClient — retry, backoff, klasyfikacja błędów."""
from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import httpx
import pytest

from app.integrations.ksef.client import (
    KSeFClient,
    KSeFClientError,
    RetryConfig,
    SendInvoiceResult,
)


@pytest.fixture()
def client() -> KSeFClient:
    return KSeFClient(
        environment="test",
        timeout_seconds=5,
        retry_config=RetryConfig(max_retries=2, backoff_base=0.01, backoff_max=0.05),
    )


class TestKSeFClientRetry:
    def test_success_no_retry(self, client: KSeFClient):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "elementReferenceNumber": "REF-1",
            "processingCode": 200,
            "processingDescription": "OK",
        }

        with patch("httpx.Client") as mock_client_cls:
            ctx = MagicMock()
            ctx.__enter__ = MagicMock(return_value=ctx)
            ctx.__exit__ = MagicMock(return_value=False)
            ctx.request.return_value = response
            mock_client_cls.return_value = ctx

            result = client.send_invoice("token", b"<xml/>")

        assert result.reference_number == "REF-1"
        assert ctx.request.call_count == 1

    def test_transient_error_retries_then_succeeds(self, client: KSeFClient):
        fail_resp = MagicMock()
        fail_resp.status_code = 503
        fail_resp.text = "Service Unavailable"

        ok_resp = MagicMock()
        ok_resp.status_code = 200
        ok_resp.json.return_value = {
            "elementReferenceNumber": "REF-2",
            "processingCode": 200,
            "processingDescription": "OK",
        }

        with patch("httpx.Client") as mock_client_cls:
            ctx = MagicMock()
            ctx.__enter__ = MagicMock(return_value=ctx)
            ctx.__exit__ = MagicMock(return_value=False)
            ctx.request.side_effect = [fail_resp, ok_resp]
            mock_client_cls.return_value = ctx

            result = client.send_invoice("token", b"<xml/>")

        assert result.reference_number == "REF-2"
        assert ctx.request.call_count == 2

    def test_permanent_error_no_retry(self, client: KSeFClient):
        fail_resp = MagicMock()
        fail_resp.status_code = 400
        fail_resp.text = "Bad Request"

        with patch("httpx.Client") as mock_client_cls:
            ctx = MagicMock()
            ctx.__enter__ = MagicMock(return_value=ctx)
            ctx.__exit__ = MagicMock(return_value=False)
            ctx.request.return_value = fail_resp
            mock_client_cls.return_value = ctx

            with pytest.raises(KSeFClientError) as exc_info:
                client.send_invoice("token", b"<xml/>")

        assert exc_info.value.transient is False
        assert exc_info.value.status_code == 400
        assert ctx.request.call_count == 1

    def test_timeout_retries(self, client: KSeFClient):
        ok_resp = MagicMock()
        ok_resp.status_code = 200
        ok_resp.json.return_value = {
            "elementReferenceNumber": "REF-3",
            "processingCode": 200,
            "processingDescription": "OK",
        }

        with patch("httpx.Client") as mock_client_cls:
            ctx = MagicMock()
            ctx.__enter__ = MagicMock(return_value=ctx)
            ctx.__exit__ = MagicMock(return_value=False)
            ctx.request.side_effect = [
                httpx.TimeoutException("Read timed out"),
                ok_resp,
            ]
            mock_client_cls.return_value = ctx

            result = client.send_invoice("token", b"<xml/>")

        assert result.reference_number == "REF-3"
        assert ctx.request.call_count == 2

    def test_all_retries_exhausted(self, client: KSeFClient):
        fail_resp = MagicMock()
        fail_resp.status_code = 503
        fail_resp.text = "Service Unavailable"

        with patch("httpx.Client") as mock_client_cls:
            ctx = MagicMock()
            ctx.__enter__ = MagicMock(return_value=ctx)
            ctx.__exit__ = MagicMock(return_value=False)
            ctx.request.return_value = fail_resp
            mock_client_cls.return_value = ctx

            with pytest.raises(KSeFClientError) as exc_info:
                client.send_invoice("token", b"<xml/>")

        assert exc_info.value.transient is True
        # initial + 2 retries = 3 calls
        assert ctx.request.call_count == 3

    def test_transient_flag_on_error(self):
        err_transient = KSeFClientError("err", status_code=503, transient=True)
        assert err_transient.transient is True

        err_permanent = KSeFClientError("err", status_code=400, transient=False)
        assert err_permanent.transient is False


class TestKSeFClientGetInvoiceStatus:
    """Commit 10: kontrakt i retry dla get_invoice_status."""

    def _make_client(self) -> KSeFClient:
        return KSeFClient(
            environment="test",
            timeout_seconds=5,
            retry_config=RetryConfig(max_retries=2, backoff_base=0.01, backoff_max=0.05),
        )

    def _ctx(self, mock_client_cls, side_effects):
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=ctx)
        ctx.__exit__ = MagicMock(return_value=False)
        ctx.request.side_effect = side_effects
        mock_client_cls.return_value = ctx
        return ctx

    def test_returns_invoice_status_result(self):
        client = self._make_client()
        ok_resp = MagicMock()
        ok_resp.status_code = 200
        ok_resp.json.return_value = {
            "processingCode": 200,
            "processingDescription": "OK",
            "ksefReferenceNumber": "KSeF/001/2026",
            "upo": None,
        }
        with patch("httpx.Client") as mock_cls:
            ctx = self._ctx(mock_cls, [ok_resp])
            from app.integrations.ksef.client import InvoiceStatusResult
            result = client.get_invoice_status("tok", "REF-1")

        assert result.processing_code == 200
        assert result.ksef_reference_number == "KSeF/001/2026"
        assert result.upo is None

    def test_transient_error_retries(self):
        client = self._make_client()
        fail = MagicMock(status_code=503, text="overload")
        ok = MagicMock(status_code=200)
        ok.json.return_value = {
            "processingCode": 100,
            "processingDescription": "Processing",
            "ksefReferenceNumber": None,
            "upo": None,
        }
        with patch("httpx.Client") as mock_cls:
            ctx = self._ctx(mock_cls, [fail, ok])
            result = client.get_invoice_status("tok", "REF-2")

        assert result.processing_code == 100
        assert ctx.request.call_count == 2

    def test_ksef_reference_number_can_be_none(self):
        """Przy processing_code != 200 ksef_reference_number może być null."""
        client = self._make_client()
        ok = MagicMock(status_code=200)
        ok.json.return_value = {
            "processingCode": 100,
            "processingDescription": "In queue",
            "upo": None,
        }
        with patch("httpx.Client") as mock_cls:
            self._ctx(mock_cls, [ok])
            result = client.get_invoice_status("tok", "REF-3")

        assert result.ksef_reference_number is None


class TestKSeFClientGetUPO:
    """Commit 10: kontrakt get_upo."""

    def test_returns_bytes(self):
        client = KSeFClient(environment="test", timeout_seconds=5)
        ok = MagicMock(status_code=200, content=b"<UPO>content</UPO>")
        with patch("httpx.Client") as mock_cls:
            ctx = MagicMock()
            ctx.__enter__ = MagicMock(return_value=ctx)
            ctx.__exit__ = MagicMock(return_value=False)
            ctx.request.return_value = ok
            mock_cls.return_value = ctx
            result = client.get_upo("tok", "KSeF/001/2026")

        assert result == b"<UPO>content</UPO>"

    def test_error_raises_ksef_client_error(self):
        client = KSeFClient(
            environment="test",
            timeout_seconds=5,
            retry_config=RetryConfig(max_retries=0),
        )
        fail = MagicMock(status_code=404, text="Not found")
        with patch("httpx.Client") as mock_cls:
            ctx = MagicMock()
            ctx.__enter__ = MagicMock(return_value=ctx)
            ctx.__exit__ = MagicMock(return_value=False)
            ctx.request.return_value = fail
            mock_cls.return_value = ctx
            with pytest.raises(KSeFClientError) as exc_info:
                client.get_upo("tok", "KSeF/999/2026")

        assert exc_info.value.status_code == 404
