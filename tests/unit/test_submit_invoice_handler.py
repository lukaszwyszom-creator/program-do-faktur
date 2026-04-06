"""Testy SubmitInvoiceJobHandler — unit (mocki)."""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.domain.enums import InvoiceStatus, TransmissionStatus
from app.domain.models.invoice import Invoice, InvoiceItem
from app.integrations.ksef.client import KSeFClientError
from app.integrations.ksef.exceptions import KSeFMappingError
from app.worker.job_handlers.submit_invoice import SubmitInvoiceJobHandler


@pytest.fixture()
def handler(mock_session: MagicMock) -> SubmitInvoiceJobHandler:
    return SubmitInvoiceJobHandler(
        session=mock_session,
        transmission_repository=MagicMock(),
        invoice_repository=MagicMock(),
        job_repository=MagicMock(),
        ksef_client=MagicMock(),
        ksef_session_service=MagicMock(),
    )


def _make_payload(transmission_id=None, invoice_id=None) -> dict:
    return {
        "transmission_id": str(transmission_id or uuid4()),
        "invoice_id": str(invoice_id or uuid4()),
    }


def _make_invoice() -> Invoice:
    now = datetime.now(UTC)
    return Invoice(
        id=uuid4(),
        status=InvoiceStatus.SENDING,
        issue_date=datetime(2026, 4, 5).date(),
        sale_date=datetime(2026, 4, 5).date(),
        currency="PLN",
        seller_snapshot={"nip": "1234567890", "name": "Seller"},
        buyer_snapshot={"nip": "0987654321", "name": "Buyer"},
        items=[
            InvoiceItem(
                name="Item", quantity=Decimal("1"), unit="szt.",
                unit_price_net=Decimal("100"), vat_rate=Decimal("23"),
                net_total=Decimal("100"), vat_total=Decimal("23"),
                gross_total=Decimal("123"), sort_order=1,
            )
        ],
        total_net=Decimal("100"),
        total_vat=Decimal("23"),
        total_gross=Decimal("123"),
        created_at=now,
        updated_at=now,
    )


class TestSubmitInvoiceHandler:
    def test_missing_transmission_skips(self, handler: SubmitInvoiceJobHandler):
        handler._transmission_repo.lock_for_update.return_value = None
        handler.handle(_make_payload())  # nie rzuca

    def test_missing_invoice_marks_permanent(self, handler: SubmitInvoiceJobHandler):
        transmission = MagicMock()
        handler._transmission_repo.lock_for_update.return_value = transmission
        handler._invoice_repo.get_by_id.return_value = None

        handler.handle(_make_payload())

        assert transmission.status == TransmissionStatus.FAILED_PERMANENT

    def test_ksef_error_marks_retryable(self, handler: SubmitInvoiceJobHandler):
        transmission = MagicMock()
        handler._transmission_repo.lock_for_update.return_value = transmission
        handler._invoice_repo.get_by_id.return_value = _make_invoice()
        handler._ksef_session_service.get_session_token.return_value = "tok"
        handler._ksef_client.send_invoice.side_effect = KSeFClientError(
            "HTTP 500", status_code=500, transient=True
        )

        handler.handle(_make_payload())

        assert transmission.status == TransmissionStatus.FAILED_RETRYABLE

    def test_success_creates_poll_job(self, handler: SubmitInvoiceJobHandler):
        transmission = MagicMock()
        handler._transmission_repo.lock_for_update.return_value = transmission
        handler._invoice_repo.get_by_id.return_value = _make_invoice()
        handler._ksef_session_service.get_session_token.return_value = "tok"

        send_result = MagicMock()
        send_result.reference_number = "REF-123"
        send_result.processing_code = 200
        send_result.processing_description = "OK"
        handler._ksef_client.send_invoice.return_value = send_result

        handler.handle(_make_payload())

        assert transmission.status == TransmissionStatus.SUBMITTED
        assert transmission.external_reference == "REF-123"
        handler._job_repo.add.assert_called_once()

    def test_mapping_error_marks_permanent(self, handler: SubmitInvoiceJobHandler):
        """KSeFMappingError to błąd strukturalny — transmisja FAILED_PERMANENT."""
        transmission = MagicMock()
        handler._transmission_repo.lock_for_update.return_value = transmission
        handler._invoice_repo.get_by_id.return_value = _make_invoice()
        handler._ksef_session_service.get_session_token.return_value = "tok"
        handler._ksef_client.send_invoice.side_effect = KSeFMappingError(
            "Brak NIP sprzedawcy"
        )

        handler.handle(_make_payload())

        assert transmission.status == TransmissionStatus.FAILED_PERMANENT
        assert transmission.error_code == "MAPPING_ERROR"
