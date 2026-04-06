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


class TestKSeFReferenceNumberCommit08:
    """Commit 08: zapis i propagacja numeru KSeF po sukcesie."""

    def test_success_propagates_ksef_number_to_invoice(self, handler: PollKSeFStatusJobHandler):
        """Numer KSeF trafia do faktury (InvoiceORM) przez invoice_repo.update."""
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
        status_result.ksef_reference_number = "KSeF/001/2026/04"
        handler._ksef_client.get_invoice_status.return_value = status_result

        handler.handle(_make_payload())

        assert invoice.ksef_reference_number == "KSeF/001/2026/04"
        handler._invoice_repo.update.assert_called_once()

    def test_success_with_no_ksef_number_does_not_crash(self, handler: PollKSeFStatusJobHandler):
        """KSeF zwrocil 200 bez numeru — nie rzucamy wyjatku, status SUCCESS."""
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
        status_result.ksef_reference_number = None
        handler._ksef_client.get_invoice_status.return_value = status_result

        handler.handle(_make_payload())  # nie rzuca

        assert transmission.status == TransmissionStatus.SUCCESS
        assert transmission.ksef_reference_number is None
        assert invoice.ksef_reference_number is None

    def test_already_success_transmission_is_skipped(self, handler: PollKSeFStatusJobHandler):
        """Idempotentnosc: ponowne wywolanie dla SUCCESS nie wywoluje klienta KSeF."""
        transmission = MagicMock()
        transmission.status = TransmissionStatus.SUCCESS
        handler._transmission_repo.lock_for_update.return_value = transmission

        handler.handle(_make_payload())

        handler._ksef_client.get_invoice_status.assert_not_called()
        handler._invoice_repo.update.assert_not_called()

    def test_already_permanent_failure_is_skipped(self, handler: PollKSeFStatusJobHandler):
        """Idempotentnosc: ponowne wywolanie dla FAILED_PERMANENT nie wywoluje klienta."""
        transmission = MagicMock()
        transmission.status = TransmissionStatus.FAILED_PERMANENT
        handler._transmission_repo.lock_for_update.return_value = transmission

        handler.handle(_make_payload())

        handler._ksef_client.get_invoice_status.assert_not_called()


class TestUPOCommit09:
    """Commit 09: pobranie i zapis UPO po sukcesie numeru KSeF."""

    def _make_success_setup(self, handler: PollKSeFStatusJobHandler):
        """Pomocnik: ustawia handler w stan sukcesu z numerem KSeF."""
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
        status_result.ksef_reference_number = "KSeF/001/2026/04"
        handler._ksef_client.get_invoice_status.return_value = status_result

        return transmission

    def test_success_fetches_upo(self, handler: PollKSeFStatusJobHandler):
        """Po sukcesie numer KSeF → wywolanie get_upo."""
        transmission = self._make_success_setup(handler)
        handler._ksef_client.get_upo.return_value = b"<UPO>tresc</UPO>"

        handler.handle(_make_payload())

        handler._ksef_client.get_upo.assert_called_once_with("tok", "KSeF/001/2026/04")
        assert transmission.upo_xml == b"<UPO>tresc</UPO>"
        assert transmission.upo_status == "fetched"

    def test_success_upo_error_does_not_revert_ksef_number(self, handler: PollKSeFStatusJobHandler):
        """Blad pobrania UPO nie cofa numeru KSeF ani statusu SUCCESS."""
        transmission = self._make_success_setup(handler)
        handler._ksef_client.get_upo.side_effect = Exception("timeout")

        handler.handle(_make_payload())

        # Status transmisji i numer KSeF zachowane
        assert transmission.status == TransmissionStatus.SUCCESS
        assert transmission.ksef_reference_number == "KSeF/001/2026/04"
        # UPO oznaczone jako blad
        assert transmission.upo_status == "failed"

    def test_success_upo_empty_response_marks_failed(self, handler: PollKSeFStatusJobHandler):
        """Puste bytes z UPO → upo_status='failed', nie crashuje, status SUCCESS zachowany."""
        transmission = self._make_success_setup(handler)
        handler._ksef_client.get_upo.return_value = b""

        handler.handle(_make_payload())

        assert transmission.upo_status == "failed"
        assert transmission.status == TransmissionStatus.SUCCESS

    def test_success_no_ksef_number_skips_upo(self, handler: PollKSeFStatusJobHandler):
        """Bez numeru KSeF (kod 200 ale brak numeru) → upo_status='failed', no crash."""
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
        status_result.ksef_reference_number = None
        handler._ksef_client.get_invoice_status.return_value = status_result

        handler.handle(_make_payload())

        handler._ksef_client.get_upo.assert_not_called()
        assert transmission.upo_status == "failed"

    def test_code_400_does_not_fetch_upo(self, handler: PollKSeFStatusJobHandler):
        """Blad permanentny → brak wywolania get_upo."""
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

        handler._ksef_client.get_upo.assert_not_called()
