"""Testy TransmissionService — unit (mocki)."""
from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.core.exceptions import NotFoundError
from app.core.security import AuthenticatedUser
from app.domain.enums import InvoiceStatus, TransmissionStatus
from app.domain.exceptions import InvalidInvoiceError, InvalidStatusTransitionError
from app.services.transmission_service import TransmissionService


@pytest.fixture()
def service(mock_session: MagicMock) -> TransmissionService:
    return TransmissionService(
        session=mock_session,
        transmission_repository=MagicMock(),
        invoice_repository=MagicMock(),
        job_repository=MagicMock(),
        audit_service=MagicMock(),
    )


class TestSubmitInvoice:
    def test_wrong_status_raises(self, service: TransmissionService, actor: AuthenticatedUser):
        invoice = MagicMock()
        invoice.status = InvoiceStatus.DRAFT
        invoice.can_transition_to = MagicMock(return_value=False)
        service._invoice_repo.lock_for_update.return_value = invoice

        with pytest.raises(InvalidStatusTransitionError, match="ready_for_submission"):
            service.submit_invoice(uuid4(), actor)

    def test_active_transmission_exists_raises(self, service: TransmissionService, actor: AuthenticatedUser):
        invoice = MagicMock()
        invoice.status = InvoiceStatus.READY_FOR_SUBMISSION
        invoice.can_transition_to = MagicMock(return_value=True)
        service._invoice_repo.lock_for_update.return_value = invoice
        service._transmission_repo.get_active_for_invoice.return_value = MagicMock(id=uuid4(), status="queued")

        with pytest.raises(InvalidInvoiceError, match="aktywną transmisję"):
            service.submit_invoice(uuid4(), actor)

    def test_success(self, service: TransmissionService, actor: AuthenticatedUser):
        invoice_id = uuid4()
        invoice = MagicMock()
        invoice.status = InvoiceStatus.READY_FOR_SUBMISSION
        invoice.can_transition_to = MagicMock(return_value=True)
        service._invoice_repo.lock_for_update.return_value = invoice
        service._transmission_repo.get_active_for_invoice.return_value = None

        transmission = MagicMock()
        transmission.id = uuid4()
        transmission.invoice_id = invoice_id
        transmission.status = TransmissionStatus.QUEUED
        service._transmission_repo.add.return_value = transmission

        result = service.submit_invoice(invoice_id, actor)
        assert result == transmission
        service._job_repo.add.assert_called_once()
        assert service._audit_service.record.call_count == 2


class TestRetryTransmission:
    def test_not_found_raises(self, service: TransmissionService, actor: AuthenticatedUser):
        service._transmission_repo.lock_for_update.return_value = None
        with pytest.raises(NotFoundError):
            service.retry_transmission(uuid4(), actor)

    def test_wrong_status_raises(self, service: TransmissionService, actor: AuthenticatedUser):
        t = MagicMock()
        t.status = TransmissionStatus.SUCCESS
        service._transmission_repo.lock_for_update.return_value = t

        with pytest.raises(InvalidInvoiceError, match="retry"):
            service.retry_transmission(uuid4(), actor)

    def test_max_attempts_raises(self, service: TransmissionService, actor: AuthenticatedUser):
        t = MagicMock()
        t.status = TransmissionStatus.FAILED_RETRYABLE
        t.attempt_no = 5
        service._transmission_repo.lock_for_update.return_value = t

        with pytest.raises(InvalidInvoiceError, match="Przekroczono"):
            service.retry_transmission(uuid4(), actor)


class TestGetTransmission:
    def test_not_found_raises(self, service: TransmissionService):
        service._transmission_repo.get_by_id.return_value = None
        with pytest.raises(NotFoundError):
            service.get_transmission(uuid4())

    def test_found(self, service: TransmissionService):
        t = MagicMock()
        t.id = uuid4()
        service._transmission_repo.get_by_id.return_value = t
        assert service.get_transmission(t.id) == t
