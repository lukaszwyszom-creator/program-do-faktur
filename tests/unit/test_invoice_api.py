"""
Testy endpointów API faktur — używają TestClient z FastAPI (bez bazy danych).

Strategia:
- Nadpisujemy zależności DI przez app.dependency_overrides
- Mockujemy InvoiceService i IdempotencyService
- Sprawdzamy kody HTTP, strukturę odpowiedzi i poprawne skierowanie filtrów
"""
from __future__ import annotations

import os
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest import mock
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-123")

from app.api.deps import get_current_user, get_idempotency_service, get_invoice_service
from app.core.security import AuthenticatedUser
from app.domain.enums import InvoiceStatus
from app.domain.models.invoice import Invoice, InvoiceItem
from app.main import app
from app.services.idempotency_service import IdempotencyService
from app.services.invoice_service import InvoiceService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_actor() -> AuthenticatedUser:
    return AuthenticatedUser(user_id=str(uuid4()), username="tester", role="administrator")


def _make_item() -> InvoiceItem:
    return InvoiceItem(
        id=uuid4(),
        name="Usługa",
        quantity=Decimal("10"),
        unit="godz.",
        unit_price_net=Decimal("200.00"),
        vat_rate=Decimal("23"),
        net_total=Decimal("2000.00"),
        vat_total=Decimal("460.00"),
        gross_total=Decimal("2460.00"),
        sort_order=1,
    )


def _make_invoice(status: InvoiceStatus = InvoiceStatus.DRAFT, number: str | None = None) -> Invoice:
    now = datetime.now(UTC)
    return Invoice(
        id=uuid4(),
        number_local=number,
        status=status,
        issue_date=date(2026, 4, 5),
        sale_date=date(2026, 4, 5),
        currency="PLN",
        seller_snapshot={"nip": "1234567890", "name": "Sprzedawca"},
        buyer_snapshot={"nip": "0987654321", "name": "Nabywca"},
        items=[_make_item()],
        total_net=Decimal("2000.00"),
        total_vat=Decimal("460.00"),
        total_gross=Decimal("2460.00"),
        created_by=uuid4(),
        created_at=now,
        updated_at=now,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_invoice_service() -> MagicMock:
    return MagicMock(spec=InvoiceService)


@pytest.fixture()
def mock_idempotency_service() -> MagicMock:
    svc = MagicMock(spec=IdempotencyService)
    svc.acquire.return_value = None  # no cached response
    return svc


@pytest.fixture()
def actor() -> AuthenticatedUser:
    return _make_actor()


@pytest.fixture()
def client(mock_invoice_service, mock_idempotency_service, actor) -> TestClient:
    app.dependency_overrides[get_current_user] = lambda: actor
    app.dependency_overrides[get_invoice_service] = lambda: mock_invoice_service
    app.dependency_overrides[get_idempotency_service] = lambda: mock_idempotency_service
    _patch = mock.patch("app.services.auth_service.AuthService.bootstrap_initial_admin")
    _patch.start()
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
    _patch.stop()
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# GET /api/v1/invoices/
# ---------------------------------------------------------------------------

class TestListInvoices:
    def test_returns_200_with_empty_list(self, client, mock_invoice_service):
        mock_invoice_service.list_invoices.return_value = ([], 0)

        res = client.get("/api/v1/invoices/")

        assert res.status_code == 200
        body = res.json()
        assert body["total"] == 0
        assert body["items"] == []
        assert body["page"] == 1
        assert body["size"] == 20

    def test_returns_items(self, client, mock_invoice_service):
        inv = _make_invoice(InvoiceStatus.ACCEPTED, "FV/2026/001")
        mock_invoice_service.list_invoices.return_value = ([inv], 1)

        res = client.get("/api/v1/invoices/")

        assert res.status_code == 200
        items = res.json()["items"]
        assert len(items) == 1
        assert items[0]["number_local"] == "FV/2026/001"
        assert items[0]["status"] == "accepted"

    def test_passes_status_filter(self, client, mock_invoice_service):
        mock_invoice_service.list_invoices.return_value = ([], 0)

        client.get("/api/v1/invoices/?status=DRAFT")

        call_kwargs = mock_invoice_service.list_invoices.call_args.kwargs
        assert call_kwargs["status"] == "DRAFT"  # passed as-is (string from query param)

    def test_passes_date_filters(self, client, mock_invoice_service):
        mock_invoice_service.list_invoices.return_value = ([], 0)

        client.get("/api/v1/invoices/?issue_date_from=2026-01-01&issue_date_to=2026-03-31")

        call_kwargs = mock_invoice_service.list_invoices.call_args.kwargs
        assert call_kwargs["issue_date_from"] == date(2026, 1, 1)
        assert call_kwargs["issue_date_to"] == date(2026, 3, 31)

    def test_passes_number_filter(self, client, mock_invoice_service):
        mock_invoice_service.list_invoices.return_value = ([], 0)

        client.get("/api/v1/invoices/?number_filter=FV%2F2026")

        call_kwargs = mock_invoice_service.list_invoices.call_args.kwargs
        assert call_kwargs["number_filter"] == "FV/2026"

    def test_pagination_defaults(self, client, mock_invoice_service):
        mock_invoice_service.list_invoices.return_value = ([], 0)

        client.get("/api/v1/invoices/")

        call_kwargs = mock_invoice_service.list_invoices.call_args.kwargs
        assert call_kwargs["page"] == 1
        assert call_kwargs["size"] == 20

    def test_custom_pagination(self, client, mock_invoice_service):
        mock_invoice_service.list_invoices.return_value = ([], 0)

        client.get("/api/v1/invoices/?page=3&size=10")

        call_kwargs = mock_invoice_service.list_invoices.call_args.kwargs
        assert call_kwargs["page"] == 3
        assert call_kwargs["size"] == 10

    def test_size_over_100_rejected(self, client, mock_invoice_service):
        res = client.get("/api/v1/invoices/?size=101")
        assert res.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/v1/invoices/{id}
# ---------------------------------------------------------------------------

class TestGetInvoice:
    def test_returns_invoice(self, client, mock_invoice_service):
        inv = _make_invoice(InvoiceStatus.DRAFT)
        mock_invoice_service.get_invoice.return_value = inv

        res = client.get(f"/api/v1/invoices/{inv.id}")

        assert res.status_code == 200
        body = res.json()
        assert UUID(body["id"]) == inv.id
        assert body["status"] == "draft"

    def test_not_found_returns_404(self, client, mock_invoice_service):
        from app.core.exceptions import NotFoundError
        mock_invoice_service.get_invoice.side_effect = NotFoundError("nie znaleziono")

        res = client.get(f"/api/v1/invoices/{uuid4()}")

        assert res.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/v1/invoices/{id}/mark-ready
# ---------------------------------------------------------------------------

class TestMarkReady:
    def test_mark_ready_returns_invoice(self, client, mock_invoice_service):
        inv = _make_invoice(InvoiceStatus.READY_FOR_SUBMISSION, "FV/2026/001")
        mock_invoice_service.mark_as_ready.return_value = inv

        res = client.post(f"/api/v1/invoices/{inv.id}/mark-ready")

        assert res.status_code == 200
        assert res.json()["status"] == "ready_for_submission"


# ---------------------------------------------------------------------------
# GET /api/v1/invoices/{id}/pdf
# ---------------------------------------------------------------------------

class TestInvoicePdf:
    def test_returns_html_content(self, client, mock_invoice_service):
        inv = _make_invoice(InvoiceStatus.ACCEPTED, "FV/2026/001")
        mock_invoice_service.get_invoice.return_value = inv

        res = client.get(f"/api/v1/invoices/{inv.id}/pdf")

        assert res.status_code == 200
        assert "text/html" in res.headers["content-type"]
        assert "Faktura" in res.text
        assert "FV/2026/001" in res.text

    def test_pdf_contains_buyer_name(self, client, mock_invoice_service):
        inv = _make_invoice(InvoiceStatus.ACCEPTED, "FV/2026/001")
        mock_invoice_service.get_invoice.return_value = inv

        res = client.get(f"/api/v1/invoices/{inv.id}/pdf")

        assert "Nabywca" in res.text

    def test_pdf_contains_totals(self, client, mock_invoice_service):
        inv = _make_invoice(InvoiceStatus.ACCEPTED, "FV/2026/001")
        mock_invoice_service.get_invoice.return_value = inv

        res = client.get(f"/api/v1/invoices/{inv.id}/pdf")

        assert "2460" in res.text


# ---------------------------------------------------------------------------
# Frontend routes
# ---------------------------------------------------------------------------

class TestFrontendRoutes:
    def test_ui_root_returns_html(self, client):
        res = client.get("/ui/")
        assert res.status_code == 200
        assert "text/html" in res.headers["content-type"]

    def test_ui_login_returns_html(self, client):
        res = client.get("/ui/login")
        assert res.status_code == 200
        assert "text/html" in res.headers["content-type"]

    def test_ui_invoice_returns_html(self, client):
        res = client.get("/ui/invoice")
        assert res.status_code == 200
        assert "text/html" in res.headers["content-type"]

    def test_ui_manifest_returns_json(self, client):
        res = client.get("/ui/manifest.webmanifest")
        assert res.status_code == 200
        assert "manifest" in res.headers["content-type"] or "json" in res.headers["content-type"]

    def test_ui_sw_returns_js(self, client):
        res = client.get("/ui/sw.js")
        assert res.status_code == 200
        assert "javascript" in res.headers["content-type"]


# ---------------------------------------------------------------------------
# FA(3) new fields: delivery_date, ksef_reference_number
# ---------------------------------------------------------------------------

class TestFA3FieldsInAPI:
    """Sprawdza, ze nowe pola FA(3) sa widoczne w odpowiedziach API."""

    def test_get_invoice_response_contains_delivery_date_null(self, client, mock_invoice_service):
        inv = _make_invoice()
        assert inv.delivery_date is None
        mock_invoice_service.get_invoice.return_value = inv

        res = client.get(f"/api/v1/invoices/{inv.id}")

        assert res.status_code == 200
        body = res.json()
        assert "delivery_date" in body
        assert body["delivery_date"] is None

    def test_get_invoice_response_contains_delivery_date_value(self, client, mock_invoice_service):
        from datetime import date as _date
        now = datetime.now(UTC)
        inv = Invoice(
            id=uuid4(),
            number_local=None,
            status=InvoiceStatus.DRAFT,
            issue_date=_date(2026, 4, 6),
            sale_date=_date(2026, 4, 6),
            delivery_date=_date(2026, 4, 4),
            currency="PLN",
            seller_snapshot={"nip": "1234567890", "name": "Sprzedawca"},
            buyer_snapshot={"nip": "0987654321", "name": "Nabywca"},
            items=[_make_item()],
            total_net=Decimal("2000.00"),
            total_vat=Decimal("460.00"),
            total_gross=Decimal("2460.00"),
            created_by=uuid4(),
            created_at=now,
            updated_at=now,
        )
        mock_invoice_service.get_invoice.return_value = inv

        res = client.get(f"/api/v1/invoices/{inv.id}")

        assert res.status_code == 200
        assert res.json()["delivery_date"] == "2026-04-04"

    def test_get_invoice_response_contains_ksef_reference_number_null(self, client, mock_invoice_service):
        inv = _make_invoice()
        mock_invoice_service.get_invoice.return_value = inv

        res = client.get(f"/api/v1/invoices/{inv.id}")

        assert res.status_code == 200
        body = res.json()
        assert "ksef_reference_number" in body
        assert body["ksef_reference_number"] is None

    def test_get_invoice_response_contains_ksef_reference_number_value(self, client, mock_invoice_service):
        inv = _make_invoice()
        inv.ksef_reference_number = "9999909999-20260406-ABC12345-01"
        mock_invoice_service.get_invoice.return_value = inv

        res = client.get(f"/api/v1/invoices/{inv.id}")

        assert res.status_code == 200
        assert res.json()["ksef_reference_number"] == "9999909999-20260406-ABC12345-01"

    def test_create_invoice_with_delivery_date(self, client, mock_invoice_service, mock_idempotency_service):
        from datetime import date as _date
        inv = _make_invoice()
        mock_invoice_service.create_invoice.return_value = inv

        payload = {
            "buyer_id": str(uuid4()),
            "issue_date": "2026-04-06",
            "sale_date": "2026-04-06",
            "delivery_date": "2026-04-04",
            "currency": "PLN",
            "items": [{"name": "Usługa", "quantity": "1", "unit": "szt.", "unit_price_net": "100", "vat_rate": "23"}],
        }

        res = client.post("/api/v1/invoices/", json=payload)

        assert res.status_code == 201
        call_data = mock_invoice_service.create_invoice.call_args[0][0]
        assert call_data["delivery_date"] == _date(2026, 4, 4)

    def test_create_invoice_without_delivery_date(self, client, mock_invoice_service, mock_idempotency_service):
        inv = _make_invoice()
        mock_invoice_service.create_invoice.return_value = inv

        payload = {
            "buyer_id": str(uuid4()),
            "issue_date": "2026-04-06",
            "sale_date": "2026-04-06",
            "currency": "PLN",
            "items": [{"name": "Usługa", "quantity": "1", "unit": "szt.", "unit_price_net": "100", "vat_rate": "23"}],
        }

        res = client.post("/api/v1/invoices/", json=payload)

        assert res.status_code == 201
        call_data = mock_invoice_service.create_invoice.call_args[0][0]
        assert call_data["delivery_date"] is None
