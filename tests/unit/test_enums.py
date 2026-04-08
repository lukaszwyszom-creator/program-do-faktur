"""Testy enums."""
from app.domain.enums import InvoiceStatus, TransmissionStatus, UserRole


class TestInvoiceStatus:
    def test_values(self):
        assert InvoiceStatus.DRAFT == "draft"
        assert InvoiceStatus.READY_FOR_SUBMISSION == "ready_for_submission"
        assert InvoiceStatus.SENDING == "sending"
        assert InvoiceStatus.ACCEPTED == "accepted"
        assert InvoiceStatus.REJECTED == "rejected"

    def test_all_values_count(self):
        assert len(InvoiceStatus) == 5


class TestTransmissionStatus:
    def test_values(self):
        assert TransmissionStatus.QUEUED == "queued"
        assert TransmissionStatus.SUCCESS == "success"
        assert TransmissionStatus.FAILED_RETRYABLE == "failed_retryable"
        assert TransmissionStatus.FAILED_PERMANENT == "failed_permanent"

    def test_all_values_count(self):
        assert len(TransmissionStatus) == 8


class TestUserRole:
    def test_values(self):
        assert UserRole.OPERATOR == "operator"
        assert UserRole.ADMINISTRATOR == "administrator"
