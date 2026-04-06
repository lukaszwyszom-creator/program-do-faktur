"""Testy PollKSeFStatusJobHandler — unit (mocki)."""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.domain.enums import InvoiceStatus, TransmissionStatus
from app.domain.models.invoice import Invoice
from app.integrations.ksef.client import KSeFClientError
from app.worker.job_handlers.poll_ksef_status import PollKSeFStatusJobHandler


@pytest.fixture()
def handler(mock_session: MagicMock) -> PollKSeFStatusJobHandler:
    return PollKSeFStatusJobHandler(
        session=mock_session,
        transmission_repository=MagicMock(),
        invoice_repository=MagicMock(),
        job_repository=MagicMock(),
        ksef_client=MagicMock(),
        ksef_session_service=MagicMock(),
    )


def _make_payload(transmission_id=None) -> dict:
    return {
        "transmission_id": str(transmission_id or uuid4()),
        "reference_number": "REF-123",
    }


def _make_sending_invoice() -> Invoice:
    from datetime import date
    from decimal import Decimal
    now = datetime.now(UTC)
    return Invoice(
        id=uuid4(), status=InvoiceStatus.SENDING,
        issue_date=date(2026, 1, 15), sale_date=date(2026, 1, 15),
        currency="PLN", seller_snapshot={}, buyer_snapshot={}, items=[],
        total_net=Decimal("0"), total_vat=Decimal("0"), total_gross=Decimal("0"),
        created_at=now, updated_at=now,
    )


class TestPollHandler:
    def test_missing_transmission_skips(self, handler: PollKSeFStatusJobHandler):
        handler._transmission_repo.lock_for_update.return_value = None
        handler.handle(_make_payload())  # nie rzuca

    def test_code_200_marks_success(self, handler: PollKSeFStatusJobHandler):
        transmission = MagicMock()
        transmission.status = TransmissionStatus.SUBMITTED
        transmission.invoice_id = uuid4()
        handler._transmission_repo.lock_for_update.return_value = transmission
        handler._ksef_session_service.get_session_token.return_value = "tok"

        invoice = _make_sending_invoice()
        handler._invoice_repo.lock_for_update.return_value = invoice
        handler._invoice_repo.update.return_value = invoice

        status_result = MagicMock()
        status_result.processing_code = 200
        status_result.processing_description = "OK"
        status_result.ksef_reference_number = "KSEF-ABC"
        handler._ksef_client.get_invoice_status.return_value = status_result

        handler.handle(_make_payload())

        assert transmission.status == TransmissionStatus.SUCCESS
        assert transmission.ksef_reference_number == "KSEF-ABC"
        assert invoice.status == InvoiceStatus.ACCEPTED

    def test_code_400_marks_rejected(self, handler: PollKSeFStatusJobHandler):
        transmission = MagicMock()
        transmission.status = TransmissionStatus.SUBMITTED
        transmission.invoice_id = uuid4()
        handler._transmission_repo.lock_for_update.return_value = transmission
        handler._ksef_session_service.get_session_token.return_value = "tok"

        invoice = _make_sending_invoice()
        handler._invoice_repo.lock_for_update.return_value = invoice
        handler._invoice_repo.update.return_value = invoice

        status_result = MagicMock()
        status_result.processing_code = 400
        status_result.processing_description = "Bad request"
        status_result.ksef_reference_number = None
        handler._ksef_client.get_invoice_status.return_value = status_result

        handler.handle(_make_payload())

        assert transmission.status == TransmissionStatus.FAILED_PERMANENT
        assert invoice.status == InvoiceStatus.REJECTED

    def test_other_code_schedules_retry(self, handler: PollKSeFStatusJobHandler):
        transmission = MagicMock()
        transmission.status = TransmissionStatus.SUBMITTED
        handler._transmission_repo.lock_for_update.return_value = transmission
        handler._ksef_session_service.get_session_token.return_value = "tok"

        status_result = MagicMock()
        status_result.processing_code = 100
        status_result.processing_description = "Processing"
        handler._ksef_client.get_invoice_status.return_value = status_result

        handler.handle(_make_payload())

        handler._job_repo.add.assert_called_once()

    def test_ksef_error_schedules_retry(self, handler: PollKSeFStatusJobHandler):
        transmission = MagicMock()
        transmission.status = TransmissionStatus.SUBMITTED
        handler._transmission_repo.lock_for_update.return_value = transmission
        handler._ksef_session_service.get_session_token.return_value = "tok"
        handler._ksef_client.get_invoice_status.side_effect = KSeFClientError("Network error")

        handler.handle(_make_payload())

        handler._job_repo.add.assert_called_once()


class TestPollWaitingStatus:
    """Commit 07: WAITING_STATUS oznacza 'oczekujemy na odpowiedz KSeF'."""

    def test_other_code_sets_waiting_status(self, handler: PollKSeFStatusJobHandler):
        transmission = MagicMock()
        handler._transmission_repo.lock_for_update.return_value = transmission
        handler._ksef_session_service.get_session_token.return_value = "tok"

        status_result = MagicMock()
        status_result.processing_code = 100  # KSeF przetwarza
        handler._ksef_client.get_invoice_status.return_value = status_result

        handler.handle(_make_payload())

        assert transmission.status == TransmissionStatus.WAITING_STATUS
        handler._job_repo.add.assert_called_once()

    def test_ksef_error_sets_waiting_status(self, handler: PollKSeFStatusJobHandler):
        transmission = MagicMock()
        handler._transmission_repo.lock_for_update.return_value = transmission
        handler._ksef_session_service.get_session_token.return_value = "tok"
        handler._ksef_client.get_invoice_status.side_effect = KSeFClientError("timeout")

        handler.handle(_make_payload())

        assert transmission.status == TransmissionStatus.WAITING_STATUS
        handler._job_repo.add.assert_called_once()

    def test_code_200_does_not_set_waiting_status(self, handler: PollKSeFStatusJobHandler):
        transmission = MagicMock()
        transmission.invoice_id = uuid4()
        handler._transmission_repo.lock_for_update.return_value = transmission
        handler._ksef_session_service.get_session_token.return_value = "tok"
        handler._invoice_repo.lock_for_update.return_value = _make_sending_invoice()

        status_result = MagicMock()
        status_result.processing_code = 200
        status_result.ksef_reference_number = "KSEF-XYZ"
        handler._ksef_client.get_invoice_status.return_value = status_result

        handler.handle(_make_payload())

        assert transmission.status == TransmissionStatus.SUCCESS
