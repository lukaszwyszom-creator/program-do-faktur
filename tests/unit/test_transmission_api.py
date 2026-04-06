"""Testy kontraktowe API transmisji — Commit 11.

Strategia:
- Nadpisujemy zależności DI przez app.dependency_overrides
- Mockujemy TransmissionService
- Sprawdzamy kody HTTP, strukturę odpowiedzi, kontrakt numeru KSeF i upo_status
"""
from __future__ import annotations

import os
from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-123")

from app.api.deps import get_current_user, get_transmission_service
from app.core.exceptions import NotFoundError
from app.core.security import AuthenticatedUser
from app.domain.enums import TransmissionStatus
from app.main import app
from app.services.transmission_service import TransmissionService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_actor() -> AuthenticatedUser:
    return AuthenticatedUser(user_id=str(uuid4()), username="tester", role="administrator")


def _make_transmission_orm(
    status: str = TransmissionStatus.SUCCESS,
    ksef_reference_number: str | None = None,
    upo_status: str | None = None,
) -> MagicMock:
    t = MagicMock()
    t.id = uuid4()
    t.invoice_id = uuid4()
    t.channel = "ksef"
    t.operation_type = "submit"
    t.status = status
    t.attempt_no = 1
    t.idempotency_key = str(uuid4())
    t.external_reference = "ext-ref-001"
    t.ksef_reference_number = ksef_reference_number
    t.upo_status = upo_status
    t.error_code = None
    t.error_message = None
    t.started_at = datetime.now(UTC)
    t.finished_at = datetime.now(UTC)
    t.created_at = datetime.now(UTC)
    return t


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_transmission_service() -> MagicMock:
    return MagicMock(spec=TransmissionService)


@pytest.fixture()
def actor() -> AuthenticatedUser:
    return _make_actor()


@pytest.fixture()
def client(mock_transmission_service, actor) -> TestClient:
    from unittest import mock as _mock
    app.dependency_overrides[get_current_user] = lambda: actor
    app.dependency_overrides[get_transmission_service] = lambda: mock_transmission_service
    _patch = _mock.patch("app.services.auth_service.AuthService.bootstrap_initial_admin")
    _patch.start()
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
    _patch.stop()
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# GET /api/v1/transmissions/{id}  —  pełna odpowiedź TransmissionResponse
# ---------------------------------------------------------------------------

class TestGetTransmission:
    def test_returns_200_with_ksef_reference_number(self, client, mock_transmission_service):
        t = _make_transmission_orm(
            status=TransmissionStatus.SUCCESS,
            ksef_reference_number="KSeF-2026-001",
            upo_status="fetched",
        )
        mock_transmission_service.get_transmission.return_value = t

        res = client.get(f"/api/v1/transmissions/{t.id}")

        assert res.status_code == 200
        body = res.json()
        assert body["ksef_reference_number"] == "KSeF-2026-001"
        assert body["upo_status"] == "fetched"
        assert body["status"] == TransmissionStatus.SUCCESS

    def test_ksef_reference_number_null_when_not_yet_available(self, client, mock_transmission_service):
        t = _make_transmission_orm(
            status=TransmissionStatus.WAITING_STATUS,
            ksef_reference_number=None,
            upo_status=None,
        )
        mock_transmission_service.get_transmission.return_value = t

        res = client.get(f"/api/v1/transmissions/{t.id}")

        assert res.status_code == 200
        body = res.json()
        assert body["ksef_reference_number"] is None
        assert body["upo_status"] is None

    def test_not_found_returns_404(self, client, mock_transmission_service):
        mock_transmission_service.get_transmission.side_effect = NotFoundError("brak")

        res = client.get(f"/api/v1/transmissions/{uuid4()}")

        assert res.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/v1/transmissions/{id}/ksef-status  —  KSeFStatusResponse
# ---------------------------------------------------------------------------

class TestGetKSeFStatus:
    def test_success_with_ksef_number_is_final(self, client, mock_transmission_service):
        t = _make_transmission_orm(
            status=TransmissionStatus.SUCCESS,
            ksef_reference_number="KSeF-2026-XYZ",
            upo_status="fetched",
        )
        mock_transmission_service.get_transmission.return_value = t

        res = client.get(f"/api/v1/transmissions/{t.id}/ksef-status")

        assert res.status_code == 200
        body = res.json()
        assert body["status"] == TransmissionStatus.SUCCESS
        assert body["ksef_reference_number"] == "KSeF-2026-XYZ"
        assert body["upo_status"] == "fetched"
        assert body["is_final"] is True

    def test_waiting_status_is_not_final(self, client, mock_transmission_service):
        t = _make_transmission_orm(
            status=TransmissionStatus.WAITING_STATUS,
            ksef_reference_number=None,
            upo_status=None,
        )
        mock_transmission_service.get_transmission.return_value = t

        res = client.get(f"/api/v1/transmissions/{t.id}/ksef-status")

        assert res.status_code == 200
        body = res.json()
        assert body["status"] == TransmissionStatus.WAITING_STATUS
        assert body["ksef_reference_number"] is None
        assert body["is_final"] is False

    def test_failed_permanent_is_final_no_ksef_number(self, client, mock_transmission_service):
        t = _make_transmission_orm(
            status=TransmissionStatus.FAILED_PERMANENT,
            ksef_reference_number=None,
            upo_status=None,
        )
        mock_transmission_service.get_transmission.return_value = t

        res = client.get(f"/api/v1/transmissions/{t.id}/ksef-status")

        assert res.status_code == 200
        body = res.json()
        assert body["status"] == TransmissionStatus.FAILED_PERMANENT
        assert body["ksef_reference_number"] is None
        assert body["is_final"] is True

    def test_upo_failed_but_success_status(self, client, mock_transmission_service):
        """UPO fetch failure nie cofa statusu SUCCESS — is_final dalej True."""
        t = _make_transmission_orm(
            status=TransmissionStatus.SUCCESS,
            ksef_reference_number="KSeF-2026-UPO-FAIL",
            upo_status="failed",
        )
        mock_transmission_service.get_transmission.return_value = t

        res = client.get(f"/api/v1/transmissions/{t.id}/ksef-status")

        assert res.status_code == 200
        body = res.json()
        assert body["is_final"] is True
        assert body["upo_status"] == "failed"
        assert body["ksef_reference_number"] == "KSeF-2026-UPO-FAIL"

    def test_not_found_returns_404(self, client, mock_transmission_service):
        mock_transmission_service.get_transmission.side_effect = NotFoundError("brak")

        res = client.get(f"/api/v1/transmissions/{uuid4()}/ksef-status")

        assert res.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/v1/invoices/{id}  —  numer KSeF w odpowiedzi faktury
# ---------------------------------------------------------------------------

class TestInvoiceResponseKSeFNumber:
    """Weryfikuje, że InvoiceResponse.ksef_reference_number jest eksponowany poprawnie."""

    def test_accepted_invoice_returns_ksef_number(self, actor):
        from decimal import Decimal
        from datetime import date
        from unittest import mock
        from unittest.mock import MagicMock
        from fastapi.testclient import TestClient
        from app.api.deps import get_invoice_service, get_idempotency_service
        from app.domain.enums import InvoiceStatus
        from app.domain.models.invoice import Invoice, InvoiceItem
        from app.services.invoice_service import InvoiceService
        from app.services.idempotency_service import IdempotencyService

        now = datetime.now(UTC)
        invoice = Invoice(
            id=uuid4(),
            number_local="FV/2026/099",
            status=InvoiceStatus.ACCEPTED,
            issue_date=date(2026, 4, 5),
            sale_date=date(2026, 4, 5),
            currency="PLN",
            seller_snapshot={"nip": "1234567890", "name": "Sprzedawca"},
            buyer_snapshot={"nip": "0987654321", "name": "Nabywca"},
            items=[InvoiceItem(
                name="Usługa",
                quantity=Decimal("1"),
                unit="szt",
                unit_price_net=Decimal("100"),
                vat_rate=Decimal("23"),
                net_total=Decimal("100"),
                vat_total=Decimal("23"),
                gross_total=Decimal("123"),
            )],
            total_net=Decimal("100"),
            total_vat=Decimal("23"),
            total_gross=Decimal("123"),
            ksef_reference_number="KSeF-2026-RESP",
            created_by=uuid4(),
            created_at=now,
            updated_at=now,
        )

        mock_invoice_service = MagicMock(spec=InvoiceService)
        mock_invoice_service.get_invoice.return_value = invoice
        mock_idempotency_service = MagicMock(spec=IdempotencyService)
        mock_idempotency_service.acquire.return_value = None

        app.dependency_overrides[get_current_user] = lambda: actor
        app.dependency_overrides[get_invoice_service] = lambda: mock_invoice_service
        app.dependency_overrides[get_idempotency_service] = lambda: mock_idempotency_service
        _patch = mock.patch("app.services.auth_service.AuthService.bootstrap_initial_admin")
        _patch.start()
        try:
            with TestClient(app, raise_server_exceptions=True) as c:
                res = c.get(f"/api/v1/invoices/{invoice.id}")
        finally:
            _patch.stop()
            app.dependency_overrides.clear()

        assert res.status_code == 200
        body = res.json()
        assert body["ksef_reference_number"] == "KSeF-2026-RESP"
        assert body["status"] == "accepted"

    def test_draft_invoice_has_null_ksef_number(self, actor):
        from decimal import Decimal
        from datetime import date
        from unittest import mock
        from unittest.mock import MagicMock
        from fastapi.testclient import TestClient
        from app.api.deps import get_invoice_service, get_idempotency_service
        from app.domain.enums import InvoiceStatus
        from app.domain.models.invoice import Invoice, InvoiceItem
        from app.services.invoice_service import InvoiceService
        from app.services.idempotency_service import IdempotencyService

        now = datetime.now(UTC)
        invoice = Invoice(
            id=uuid4(),
            number_local=None,
            status=InvoiceStatus.DRAFT,
            issue_date=date(2026, 4, 5),
            sale_date=date(2026, 4, 5),
            currency="PLN",
            seller_snapshot={"nip": "1234567890", "name": "Sprzedawca"},
            buyer_snapshot={"nip": "0987654321", "name": "Nabywca"},
            items=[InvoiceItem(
                name="Usługa",
                quantity=Decimal("1"),
                unit="szt",
                unit_price_net=Decimal("100"),
                vat_rate=Decimal("23"),
                net_total=Decimal("100"),
                vat_total=Decimal("23"),
                gross_total=Decimal("123"),
            )],
            total_net=Decimal("100"),
            total_vat=Decimal("23"),
            total_gross=Decimal("123"),
            ksef_reference_number=None,
            created_by=uuid4(),
            created_at=now,
            updated_at=now,
        )

        mock_invoice_service = MagicMock(spec=InvoiceService)
        mock_invoice_service.get_invoice.return_value = invoice
        mock_idempotency_service = MagicMock(spec=IdempotencyService)
        mock_idempotency_service.acquire.return_value = None

        app.dependency_overrides[get_current_user] = lambda: actor
        app.dependency_overrides[get_invoice_service] = lambda: mock_invoice_service
        app.dependency_overrides[get_idempotency_service] = lambda: mock_idempotency_service
        _patch = mock.patch("app.services.auth_service.AuthService.bootstrap_initial_admin")
        _patch.start()
        try:
            with TestClient(app, raise_server_exceptions=True) as c:
                res = c.get(f"/api/v1/invoices/{invoice.id}")
        finally:
            _patch.stop()
            app.dependency_overrides.clear()

        assert res.status_code == 200
        body = res.json()
        assert body["ksef_reference_number"] is None


# ---------------------------------------------------------------------------
# GET /api/v1/transmissions/{id}/upo  —  pobieranie UPO (Commit 12)
# ---------------------------------------------------------------------------

class TestDownloadUPO:
    def test_returns_xml_bytes_when_fetched(self, client, mock_transmission_service):
        upo_bytes = b"<?xml version='1.0'?><UPO><Ref>KSeF-2026-001</Ref></UPO>"
        t = _make_transmission_orm(
            status=TransmissionStatus.SUCCESS,
            ksef_reference_number="KSeF-2026-001",
            upo_status="fetched",
        )
        t.upo_xml = upo_bytes
        mock_transmission_service.get_transmission.return_value = t

        res = client.get(f"/api/v1/transmissions/{t.id}/upo")

        assert res.status_code == 200
        assert res.content == upo_bytes
        assert "application/xml" in res.headers["content-type"]
        assert "attachment" in res.headers["content-disposition"]
        assert "UPO_KSeF-2026-001.xml" in res.headers["content-disposition"]

    def test_returns_404_when_upo_not_fetched(self, client, mock_transmission_service):
        t = _make_transmission_orm(
            status=TransmissionStatus.WAITING_STATUS,
            ksef_reference_number=None,
            upo_status=None,
        )
        t.upo_xml = None
        mock_transmission_service.get_transmission.return_value = t

        res = client.get(f"/api/v1/transmissions/{t.id}/upo")

        assert res.status_code == 404

    def test_returns_404_when_upo_failed(self, client, mock_transmission_service):
        t = _make_transmission_orm(
            status=TransmissionStatus.SUCCESS,
            ksef_reference_number="KSeF-2026-FAIL",
            upo_status="failed",
        )
        t.upo_xml = None
        mock_transmission_service.get_transmission.return_value = t

        res = client.get(f"/api/v1/transmissions/{t.id}/upo")

        assert res.status_code == 404

    def test_returns_404_when_upo_xml_empty(self, client, mock_transmission_service):
        """upo_status='fetched' ale plik pusty — traktujemy jak brak."""
        t = _make_transmission_orm(
            status=TransmissionStatus.SUCCESS,
            ksef_reference_number="KSeF-2026-EMPTY",
            upo_status="fetched",
        )
        t.upo_xml = b""
        mock_transmission_service.get_transmission.return_value = t

        res = client.get(f"/api/v1/transmissions/{t.id}/upo")

        assert res.status_code == 404

    def test_not_found_transmission_returns_404(self, client, mock_transmission_service):
        mock_transmission_service.get_transmission.side_effect = NotFoundError("brak")

        res = client.get(f"/api/v1/transmissions/{uuid4()}/upo")

        assert res.status_code == 404
