"""
E2E MVP integration test — pełny stos HTTP → serwis → SQLite in-memory.

Uruchomienie pojedyncze:
    python -m pytest tests/e2e_mvp.py -v

Co testuje:
  1. Health check
  2. Login (poprawny / błędne hasło / brak tokenu)
  3. Tworzenie kontrahenta i faktury
  4. Lista faktur + filtry
  5. Przejście statusu DRAFT → READY_FOR_SUBMISSION
  6. Podgląd PDF (HTML)
  7. Próba niedozwolonych przejść statusów
  8. JWT: 401 bez tokenu, 401 z niepoprawnym tokenem
  9. Import CSV przelewów i matching płatności
 10. Historia płatności faktury
"""
from __future__ import annotations

import os

# Zmienne muszą być ustawione PRZED importem modułów aplikacji
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("JWT_SECRET_KEY", "e2e-test-secret-key-exactly-32chars!!")
os.environ.setdefault("SELLER_NIP", "1234567890")
os.environ.setdefault("SELLER_NAME", "E2E Sprzedawca Sp. z o.o.")
os.environ.setdefault("SELLER_STREET", "ul. Testowa")
os.environ.setdefault("SELLER_BUILDING_NO", "1")
os.environ.setdefault("SELLER_POSTAL_CODE", "00-001")
os.environ.setdefault("SELLER_CITY", "Warszawa")

import io
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

# ---------------------------------------------------------------------------
# Patch: JSONB → JSON dla SQLite (tylko dla testów E2E)
# ---------------------------------------------------------------------------
# Musi być PRZED importem modeli aplikacji, żeby JSONB zdążyło być
# zarejestrowane zanim SQLite type compiler spróbuje je skompilować.
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler

if not hasattr(SQLiteTypeCompiler, "visit_JSONB"):
    SQLiteTypeCompiler.visit_JSONB = lambda self, type_, **kw: "JSON"  # type: ignore[attr-defined]

# Import po ustawieniu env - wymuszony porządek
from app.api.deps import get_db_session
from app.core.security import hash_password
from app.main import app
from app.persistence.base import Base
from app.persistence.models import (  # noqa: F401 — rejestracja wszystkich modeli
    AuditLog,
    BackgroundJob,
    BankTransactionORM,
    ContractorORM,
    ContractorOverrideORM,
    IdempotencyKeyORM,
    InvoiceItemORM,
    InvoiceORM,
    KSeFSessionORM,
    PaymentAllocationORM,
    TransmissionORM,
    UserORM,
)

# ---------------------------------------------------------------------------
# Shared state między testami w klasie (workflow sekwencyjny)
# ---------------------------------------------------------------------------

_STATE: dict = {}


# ---------------------------------------------------------------------------
# Session-scoped fixtures — baza żyje przez cały moduł
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def engine():
    """
    SQLite in-memory z StaticPool — JEDNA wspólna połączenie dla wszystkich sesji.
    Podmieniamy globalny engine aplikacji, żeby request-sessions i seed-sessions
    widziały te same dane.  Przywracamy po zakończeniu modułu.
    """
    from sqlalchemy.pool import StaticPool
    import app.persistence.db as db_module

    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False,
    )
    Base.metadata.create_all(eng)

    # Podmień globalny engine i SessionLocal
    orig_engine = db_module.engine
    orig_session_local = db_module.SessionLocal
    db_module.engine = eng
    db_module.SessionLocal = sessionmaker(
        bind=eng, autoflush=False, autocommit=False, expire_on_commit=False
    )

    yield eng

    db_module.engine = orig_engine
    db_module.SessionLocal = orig_session_local
    eng.dispose()


@pytest.fixture(scope="module")
def db_session(engine):
    """Sesja seedująca — korzysta z tego samego silnika co app."""
    import app.persistence.db as db_module

    session = db_module.SessionLocal()
    yield session
    session.close()


@pytest.fixture(scope="module")
def client(engine):
    """
    TestClient — tabele istnieją zanim uruchomi się lifespan.
    Wyłączamy lifespan-bootstrap admina, żeby nie kolidował z seeded userem.
    """
    from app.core.config import settings

    orig_admin_usr = settings.initial_admin_username
    orig_admin_pwd = settings.initial_admin_password
    orig_seller_nip = settings.seller_nip
    orig_seller_name = settings.seller_name
    orig_seller_street = settings.seller_street
    orig_seller_building_no = settings.seller_building_no
    orig_seller_postal_code = settings.seller_postal_code
    orig_seller_city = settings.seller_city
    object.__setattr__(settings, "initial_admin_username", None)
    object.__setattr__(settings, "initial_admin_password", None)
    object.__setattr__(settings, "seller_nip", "1234567890")
    object.__setattr__(settings, "seller_name", "E2E Sprzedawca Sp. z o.o.")
    object.__setattr__(settings, "seller_street", "ul. Testowa")
    object.__setattr__(settings, "seller_building_no", "1")
    object.__setattr__(settings, "seller_postal_code", "00-001")
    object.__setattr__(settings, "seller_city", "Warszawa")

    with TestClient(app, raise_server_exceptions=True) as c:
        yield c

    object.__setattr__(settings, "initial_admin_username", orig_admin_usr)
    object.__setattr__(settings, "initial_admin_password", orig_admin_pwd)
    object.__setattr__(settings, "seller_nip", orig_seller_nip)
    object.__setattr__(settings, "seller_name", orig_seller_name)
    object.__setattr__(settings, "seller_street", orig_seller_street)
    object.__setattr__(settings, "seller_building_no", orig_seller_building_no)
    object.__setattr__(settings, "seller_postal_code", orig_seller_postal_code)
    object.__setattr__(settings, "seller_city", orig_seller_city)


@pytest.fixture(scope="module")
def seeded(db_session, client):
    """Seed: admin + kontrahent — uruchamiane raz dla całego modułu."""
    admin = UserORM(
        username="e2e_admin",
        password_hash=hash_password("Admin1234!"),
        role="administrator",
        is_active=True,
    )
    buyer = ContractorORM(
        nip="9876543210",
        name="Nabywca Testowy Sp. z o.o.",
        city="Kraków",
        source="manual",
    )
    db_session.add_all([admin, buyer])
    db_session.commit()
    db_session.refresh(admin)
    db_session.refresh(buyer)

    _STATE["admin_id"] = str(admin.id)
    _STATE["buyer_id"] = str(buyer.id)
    return _STATE


# ---------------------------------------------------------------------------
# Testy — uruchamiane w kolejności pliku
# ---------------------------------------------------------------------------


class TestE2EMvp:
    # ── 1. Health ────────────────────────────────────────────────────────────

    def test_01_health(self, client, seeded):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    # ── 2. Auth ─────────────────────────────────────────────────────────────

    def test_02a_login_ok(self, client, seeded):
        r = client.post(
            "/api/v1/auth/login",
            json={"username": "e2e_admin", "password": "Admin1234!"},
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert "access_token" in data
        assert data["username"] == "e2e_admin"
        _STATE["token"] = data["access_token"]
        _STATE["headers"] = {"Authorization": f"Bearer {data['access_token']}"}

    def test_02b_login_wrong_password(self, client, seeded):
        r = client.post(
            "/api/v1/auth/login",
            json={"username": "e2e_admin", "password": "ZleHaslo"},
        )
        assert r.status_code == 401

    def test_02c_no_token_returns_401(self, client, seeded):
        r = client.get("/api/v1/invoices/")
        assert r.status_code == 401

    def test_02d_invalid_token_returns_401(self, client, seeded):
        r = client.get(
            "/api/v1/invoices/",
            headers={"Authorization": "Bearer nie.prawdziwy.token"},
        )
        assert r.status_code == 401

    # ── 3. Tworzenie faktury ─────────────────────────────────────────────────

    def test_03a_create_invoice(self, client, seeded):
        today = date.today().isoformat()
        r = client.post(
            "/api/v1/invoices/",
            json={
                "buyer_id": _STATE["buyer_id"],
                "issue_date": today,
                "sale_date": today,
                "currency": "PLN",
                "items": [
                    {
                        "name": "Usługa programistyczna",
                        "quantity": "10",
                        "unit": "godz.",
                        "unit_price_net": "200.00",
                        "vat_rate": "23",
                    }
                ],
            },
            headers=_STATE["headers"],
        )
        assert r.status_code == 201, r.text
        data = r.json()
        assert data["status"] == "draft"
        assert data["number_local"] is None
        assert Decimal(data["total_gross"]) == Decimal("2460.00")
        _STATE["invoice_id"] = data["id"]

    def test_03b_create_invoice_no_items_returns_422(self, client, seeded):
        today = date.today().isoformat()
        r = client.post(
            "/api/v1/invoices/",
            json={
                "buyer_id": _STATE["buyer_id"],
                "issue_date": today,
                "sale_date": today,
                "items": [],
            },
            headers=_STATE["headers"],
        )
        assert r.status_code in (400, 422)

    def test_03c_create_invoice_unknown_buyer_returns_404(self, client, seeded):
        from uuid import uuid4
        today = date.today().isoformat()
        r = client.post(
            "/api/v1/invoices/",
            json={
                "buyer_id": str(uuid4()),
                "issue_date": today,
                "sale_date": today,
                "items": [{"name": "X", "quantity": "1", "unit_price_net": "100", "vat_rate": "23"}],
            },
            headers=_STATE["headers"],
        )
        assert r.status_code == 404

    # ── 4. Lista faktur + filtry ─────────────────────────────────────────────

    def test_04a_list_invoices(self, client, seeded):
        r = client.get("/api/v1/invoices/", headers=_STATE["headers"])
        assert r.status_code == 200
        data = r.json()
        assert data["total"] >= 1
        ids = [inv["id"] for inv in data["items"]]
        assert _STATE["invoice_id"] in ids

    def test_04b_filter_by_status_draft(self, client, seeded):
        r = client.get("/api/v1/invoices/?status=draft", headers=_STATE["headers"])
        assert r.status_code == 200
        data = r.json()
        assert data["total"] >= 1
        assert all(inv["status"] == "draft" for inv in data["items"])

    def test_04c_filter_status_nonexistent_returns_empty(self, client, seeded):
        r = client.get("/api/v1/invoices/?status=accepted", headers=_STATE["headers"])
        assert r.status_code == 200
        assert r.json()["total"] == 0

    def test_04d_filter_by_date_range(self, client, seeded):
        today = date.today().isoformat()
        r = client.get(
            f"/api/v1/invoices/?issue_date_from={today}&issue_date_to={today}",
            headers=_STATE["headers"],
        )
        assert r.status_code == 200
        assert r.json()["total"] >= 1

    def test_04e_filter_date_outside_range_returns_empty(self, client, seeded):
        past = (date.today() - timedelta(days=365)).isoformat()
        r = client.get(
            f"/api/v1/invoices/?issue_date_from={past}&issue_date_to={past}",
            headers=_STATE["headers"],
        )
        assert r.status_code == 200
        assert r.json()["total"] == 0

    def test_04f_pagination(self, client, seeded):
        r = client.get("/api/v1/invoices/?page=1&size=1", headers=_STATE["headers"])
        assert r.status_code == 200
        data = r.json()
        assert len(data["items"]) <= 1
        assert data["size"] == 1

    # ── 5. Szczegóły faktury ──────────────────────────────────────────────

    def test_05a_get_invoice_detail(self, client, seeded):
        r = client.get(f"/api/v1/invoices/{_STATE['invoice_id']}", headers=_STATE["headers"])
        assert r.status_code == 200
        data = r.json()
        assert data["id"] == _STATE["invoice_id"]
        assert data["buyer_snapshot"]["nip"] == "9876543210"
        assert data["seller_snapshot"]["nip"] == "1234567890"

    def test_05b_get_nonexistent_invoice_returns_404(self, client, seeded):
        from uuid import uuid4
        r = client.get(f"/api/v1/invoices/{uuid4()}", headers=_STATE["headers"])
        assert r.status_code == 404

    # ── 6. Przejście statusu DRAFT → READY_FOR_SUBMISSION ────────────────

    def test_06a_mark_ready(self, client, seeded):
        r = client.post(
            f"/api/v1/invoices/{_STATE['invoice_id']}/mark-ready",
            headers=_STATE["headers"],
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["status"] == "ready_for_submission"
        assert data["number_local"] is not None
        assert data["number_local"].startswith("FV/")
        _STATE["invoice_number"] = data["number_local"]

    def test_06b_mark_ready_again_returns_error(self, client, seeded):
        """Ponowne mark-ready na fakturze już gotowej powinno zwrócić błąd."""
        r = client.post(
            f"/api/v1/invoices/{_STATE['invoice_id']}/mark-ready",
            headers=_STATE["headers"],
        )
        assert r.status_code in (400, 409, 422)

    def test_06c_number_filter(self, client, seeded):
        """Filtr po fragmencie numeru faktury."""
        fragment = _STATE["invoice_number"][:6]  # np. "FV/202"
        r = client.get(
            f"/api/v1/invoices/?number_filter={fragment}",
            headers=_STATE["headers"],
        )
        assert r.status_code == 200
        data = r.json()
        assert data["total"] >= 1
        assert any(
            inv["number_local"] and fragment in inv["number_local"]
            for inv in data["items"]
        )

    # ── 7. Podgląd PDF (HTML renderer) ───────────────────────────────────

    def test_07_pdf_preview(self, client, seeded):
        r = client.get(
            f"/api/v1/invoices/{_STATE['invoice_id']}/pdf",
            headers=_STATE["headers"],
        )
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
        body = r.text
        # Sprawdź klucz treści faktury
        assert _STATE["invoice_number"] in body
        assert "Usługa programistyczna" in body
        assert "2 460" in body or "2460" in body
        assert "1234567890" in body  # NIP sprzedawcy

    # ── 8. UI strony frontendowe ────────────────────────────────────────

    def test_08a_ui_index(self, client, seeded):
        r = client.get("/ui/")
        assert r.status_code == 200

    def test_08b_ui_login(self, client, seeded):
        r = client.get("/ui/login")
        assert r.status_code == 200

    def test_08c_ui_invoice(self, client, seeded):
        r = client.get("/ui/invoice")
        assert r.status_code == 200

    def test_08d_ui_payments(self, client, seeded):
        r = client.get("/ui/payments")
        assert r.status_code == 200

    # ── 9. Swagger docs ─────────────────────────────────────────────────

    def test_09_swagger_docs(self, client, seeded):
        r = client.get("/docs")
        assert r.status_code == 200
        assert "swagger" in r.text.lower() or "openapi" in r.text.lower()

    # ── 10. Import CVS przelewów i matching ──────────────────────────────

    def test_10a_import_csv_transactions(self, client, seeded):
        """Import przykładowego CSV z przelewem dopasowanym do faktury."""
        invoice_number = _STATE.get("invoice_number", "FV/2026/04/001")
        today = date.today().isoformat()

        csv_content = (
            "data,kwota,waluta,nadawca,rachunek_nadawcy,tytul\n"
            f"{today},2460.00,PLN,Nabywca Testowy Sp z o o,"
            f"PL12345678901234567890123456,{invoice_number}\n"
        )
        csv_bytes = csv_content.encode("utf-8")
        file = io.BytesIO(csv_bytes)

        r = client.post(
            "/api/v1/payments/import",
            files={"file": ("przelewy.csv", file, "text/csv")},
            headers=_STATE["headers"],
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["imported"] >= 1
        _STATE["import_result"] = data

    def test_10b_list_transactions(self, client, seeded):
        r = client.get("/api/v1/payments/transactions", headers=_STATE["headers"])
        assert r.status_code == 200
        data = r.json()
        assert data["total"] >= 1
        _STATE["transaction_id"] = data["items"][0]["id"]

    def test_10c_list_transactions_filter_unmatched(self, client, seeded):
        r = client.get(
            "/api/v1/payments/transactions?match_status=unmatched",
            headers=_STATE["headers"],
        )
        assert r.status_code == 200

    def test_10d_manual_allocate(self, client, seeded):
        """Ręczna alokacja przelewu do faktury."""
        r = client.post(
            f"/api/v1/payments/transactions/{_STATE['transaction_id']}/allocate",
            json={
                "invoice_id": _STATE["invoice_id"],
                "amount": "100.00",
            },
            headers=_STATE["headers"],
        )
        assert r.status_code in (200, 201), r.text
        data = r.json()
        assert Decimal(str(data["allocated_amount"])) == Decimal("100.00")
        _STATE["allocation_id"] = data["id"]

    def test_10e_invoice_payment_history(self, client, seeded):
        r = client.get(
            f"/api/v1/payments/invoice/{_STATE['invoice_id']}/history",
            headers=_STATE["headers"],
        )
        assert r.status_code == 200
        data = r.json()
        assert len(data) >= 1

    def test_10f_reverse_allocation(self, client, seeded):
        r = client.delete(
            f"/api/v1/payments/allocations/{_STATE['allocation_id']}",
            headers=_STATE["headers"],
        )
        assert r.status_code == 204

    def test_10g_double_reverse_returns_error(self, client, seeded):
        """Próba cofnięcia już cofniętej alokacji."""
        r = client.delete(
            f"/api/v1/payments/allocations/{_STATE['allocation_id']}",
            headers=_STATE["headers"],
        )
        assert r.status_code in (400, 404, 422)

    # ── 11. Rematch transaction ──────────────────────────────────────────

    def test_11_rematch_transaction(self, client, seeded):
        r = client.post(
            f"/api/v1/payments/transactions/{_STATE['transaction_id']}/match",
            headers=_STATE["headers"],
        )
        assert r.status_code == 200
        data = r.json()
        assert "outcome" in data

    # ── 12. Database integrity ───────────────────────────────────────────

    def test_12_db_integrity(self, db_session, seeded):
        """Sprawdź że w bazie jest faktura z numerem i statusem."""
        from uuid import UUID
        from sqlalchemy import select
        stmt = select(InvoiceORM).where(
            InvoiceORM.id == UUID(_STATE["invoice_id"])
        )
        orm = db_session.execute(stmt).scalar_one_or_none()
        assert orm is not None
        assert orm.status == "ready_for_submission"
        assert orm.number_local == _STATE["invoice_number"]
        assert orm.payment_status == "unpaid"  # alokacja cofnięta
