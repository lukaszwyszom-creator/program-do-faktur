"""Commit 10 (10.6): test E2E logiki workflow KSeF — od gotowej faktury do UPO.

Nie używa bazy danych. Buduje oba handlery z mockami i uruchamia je
sekwencyjnie, symulując pełen przepływ:
    1. SubmitInvoiceJobHandler.handle()  → status SUBMITTED + job poll
    2. PollKSeFStatusJobHandler.handle() → status SUCCESS + numer KSeF + UPO
"""
from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.domain.enums import InvoiceStatus, TransmissionStatus
from app.domain.models.invoice import Invoice, InvoiceItem
from app.integrations.ksef.client import KSeFClientError
from app.worker.job_handlers.poll_ksef_status import PollKSeFStatusJobHandler
from app.worker.job_handlers.submit_invoice import SubmitInvoiceJobHandler


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ready_invoice() -> Invoice:
    now = datetime.now(UTC)
    return Invoice(
        id=uuid4(),
        status=InvoiceStatus.SENDING,
        issue_date=date(2026, 4, 6),
        sale_date=date(2026, 4, 6),
        currency="PLN",
        seller_snapshot={"nip": "1000000035", "name": "Sprzedawca Sp. z o.o."},
        buyer_snapshot={"nip": "1000000070", "name": "Nabywca S.A."},
        items=[
            InvoiceItem(
                name="Usługa projektowa",
                quantity=Decimal("1"),
                unit="szt.",
                unit_price_net=Decimal("1000.00"),
                vat_rate=Decimal("23"),
                net_total=Decimal("1000.00"),
                vat_total=Decimal("230.00"),
                gross_total=Decimal("1230.00"),
                sort_order=1,
            )
        ],
        total_net=Decimal("1000.00"),
        total_vat=Decimal("230.00"),
        total_gross=Decimal("1230.00"),
        created_at=now,
        updated_at=now,
    )


def _make_submit_handler(session, transmission, invoice) -> SubmitInvoiceJobHandler:
    h = SubmitInvoiceJobHandler(
        session=session,
        transmission_repository=MagicMock(),
        invoice_repository=MagicMock(),
        job_repository=MagicMock(),
        ksef_client=MagicMock(),
        ksef_session_service=MagicMock(),
    )
    h._transmission_repo.lock_for_update.return_value = transmission  # type: ignore[attr-defined]
    h._invoice_repo.get_by_id.return_value = invoice  # type: ignore[attr-defined]
    h._ksef_session_service.get_session_token.return_value = "session-token-abc"  # type: ignore[attr-defined]
    return h


def _make_poll_handler(session, transmission, invoice) -> PollKSeFStatusJobHandler:
    h = PollKSeFStatusJobHandler(
        session=session,
        transmission_repository=MagicMock(),
        invoice_repository=MagicMock(),
        job_repository=MagicMock(),
        ksef_client=MagicMock(),
        ksef_session_service=MagicMock(),
    )
    h._transmission_repo.lock_for_update.return_value = transmission  # type: ignore[attr-defined]
    h._invoice_repo.lock_for_update.return_value = invoice  # type: ignore[attr-defined]
    h._invoice_repo.update.return_value = invoice  # type: ignore[attr-defined]
    h._ksef_session_service.get_session_token.return_value = "session-token-abc"  # type: ignore[attr-defined]
    return h


# ---------------------------------------------------------------------------
# Testy E2E
# ---------------------------------------------------------------------------

class TestKSeFWorkflowE2E:
    """Commit 10 (10.6): pełny przebieg logiki workflow KSeF."""

    def test_happy_path_submit_then_poll_success_with_upo(self, mock_session: MagicMock):
        """Pozytywna ścieżka: submit → SUBMITTED → poll → SUCCESS + ksef_number + UPO."""
        invoice = _make_ready_invoice()
        invoice_id = invoice.id
        transmission_id = uuid4()

        transmission = MagicMock()
        transmission.status = TransmissionStatus.QUEUED
        transmission.invoice_id = invoice_id

        # --- KROK 1: Submit ---
        submit_handler = _make_submit_handler(mock_session, transmission, invoice)
        send_result = MagicMock()
        send_result.reference_number = "REF-E2E-001"
        send_result.processing_code = 200
        submit_handler._ksef_client.send_invoice.return_value = send_result  # type: ignore[attr-defined]

        submit_handler.handle({
            "transmission_id": str(transmission_id),
            "invoice_id": str(invoice_id),
        })

        assert transmission.status == TransmissionStatus.SUBMITTED
        assert transmission.external_reference == "REF-E2E-001"
        submit_handler._job_repo.add.assert_called_once()  # type: ignore[attr-defined]

        # --- KROK 2: Poll → SUCCESS ---
        poll_handler = _make_poll_handler(mock_session, transmission, invoice)
        status_result = MagicMock()
        status_result.processing_code = 200
        status_result.ksef_reference_number = "KSeF/001/2026/04"
        poll_handler._ksef_client.get_invoice_status.return_value = status_result  # type: ignore[attr-defined]
        poll_handler._ksef_client.get_upo.return_value = b"<UPO>xml</UPO>"  # type: ignore[attr-defined]

        poll_handler.handle({
            "transmission_id": str(transmission_id),
            "reference_number": "REF-E2E-001",
        })

        assert transmission.status == TransmissionStatus.SUCCESS
        assert transmission.ksef_reference_number == "KSeF/001/2026/04"
        assert transmission.upo_xml == b"<UPO>xml</UPO>"
        assert transmission.upo_status == "fetched"
        assert invoice.status == InvoiceStatus.ACCEPTED
        assert invoice.ksef_reference_number == "KSeF/001/2026/04"

    def test_happy_path_poll_waits_then_succeeds(self, mock_session: MagicMock):
        """Polling: pierwsza odpowiedź kod 100 (czeka), druga 200 (sukces)."""
        invoice = _make_ready_invoice()
        invoice_id = invoice.id
        transmission_id = uuid4()

        transmission = MagicMock()
        transmission.invoice_id = invoice_id

        poll_handler = _make_poll_handler(mock_session, transmission, invoice)

        # Pierwsze wywołanie: KSeF przetwarza (kod 100)
        waiting_result = MagicMock()
        waiting_result.processing_code = 100
        poll_handler._ksef_client.get_invoice_status.return_value = waiting_result  # type: ignore[attr-defined]

        poll_handler.handle({
            "transmission_id": str(transmission_id),
            "reference_number": "REF-E2E-002",
        })

        assert transmission.status == TransmissionStatus.WAITING_STATUS
        poll_handler._job_repo.add.assert_called_once()  # type: ignore[attr-defined]
        poll_handler._job_repo.reset_mock()  # type: ignore[attr-defined]

        # Drugie wywołanie: sukces (kod 200)
        success_result = MagicMock()
        success_result.processing_code = 200
        success_result.ksef_reference_number = "KSeF/002/2026/04"
        poll_handler._ksef_client.get_invoice_status.return_value = success_result  # type: ignore[attr-defined]
        poll_handler._ksef_client.get_upo.return_value = b"<UPO>ok</UPO>"  # type: ignore[attr-defined]

        poll_handler.handle({
            "transmission_id": str(transmission_id),
            "reference_number": "REF-E2E-002",
        })

        assert transmission.status == TransmissionStatus.SUCCESS
        assert invoice.status == InvoiceStatus.ACCEPTED
        poll_handler._job_repo.add.assert_not_called()  # type: ignore[attr-defined]

    def test_rejection_path(self, mock_session: MagicMock):
        """Ścieżka odrzucenia: poll → kod 400 → FAILED_PERMANENT + REJECTED."""
        invoice = _make_ready_invoice()
        invoice_id = invoice.id
        transmission_id = uuid4()

        transmission = MagicMock()
        transmission.invoice_id = invoice_id

        poll_handler = _make_poll_handler(mock_session, transmission, invoice)
        rej_result = MagicMock()
        rej_result.processing_code = 400
        rej_result.processing_description = "Nieprawidłowa faktura"
        rej_result.ksef_reference_number = None
        poll_handler._ksef_client.get_invoice_status.return_value = rej_result  # type: ignore[attr-defined]

        poll_handler.handle({
            "transmission_id": str(transmission_id),
            "reference_number": "REF-E2E-003",
        })

        assert transmission.status == TransmissionStatus.FAILED_PERMANENT
        assert invoice.status == InvoiceStatus.REJECTED
        poll_handler._ksef_client.get_upo.assert_not_called()  # type: ignore[attr-defined]

    def test_upo_failure_does_not_revert_success(self, mock_session: MagicMock):
        """Awaria pobierania UPO nie wycofuje statusu SUCCESS ani numeru KSeF."""
        invoice = _make_ready_invoice()
        invoice_id = invoice.id
        transmission_id = uuid4()

        transmission = MagicMock()
        transmission.invoice_id = invoice_id

        poll_handler = _make_poll_handler(mock_session, transmission, invoice)
        status_result = MagicMock()
        status_result.processing_code = 200
        status_result.ksef_reference_number = "KSeF/003/2026/04"
        poll_handler._ksef_client.get_invoice_status.return_value = status_result  # type: ignore[attr-defined]
        poll_handler._ksef_client.get_upo.side_effect = Exception("UPO service down")  # type: ignore[attr-defined]

        poll_handler.handle({
            "transmission_id": str(transmission_id),
            "reference_number": "REF-E2E-004",
        })

        assert transmission.status == TransmissionStatus.SUCCESS
        assert transmission.ksef_reference_number == "KSeF/003/2026/04"
        assert transmission.upo_status == "failed"
        assert invoice.status == InvoiceStatus.ACCEPTED

    def test_submit_transient_error_retryable(self, mock_session: MagicMock):
        """Błąd przejściowy przy submit → FAILED_TEMPORARY, retry job zaplanowany."""
        invoice = _make_ready_invoice()
        transmission = MagicMock()
        transmission.invoice_id = invoice.id
        transmission.attempt_no = 1

        submit_handler = _make_submit_handler(mock_session, transmission, invoice)
        submit_handler._ksef_client.send_invoice.side_effect = KSeFClientError(  # type: ignore[attr-defined]
            "HTTP 503", status_code=503, transient=True
        )

        submit_handler.handle({
            "transmission_id": str(uuid4()),
            "invoice_id": str(invoice.id),
        })

        assert transmission.status == TransmissionStatus.FAILED_TEMPORARY
        submit_handler._job_repo.add.assert_called_once()  # type: ignore[attr-defined]
