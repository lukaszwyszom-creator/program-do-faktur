"""Integracja faktura ↔ magazyn (SQLite in-memory)."""
from __future__ import annotations

import os
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

# Przed importem Settings — lokalne testy bez produkcji
os.environ["APP_ENV"] = "development"
os.environ["JWT_SECRET_KEY"] = "test-secret-key-exactly-32-chars!!"
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

# JSONB → JSON patch dla SQLite DDL (jak w test_transaction_hardening)
if not hasattr(SQLiteTypeCompiler, "visit_JSONB"):
    SQLiteTypeCompiler.visit_JSONB = lambda self, type_, **kw: "JSON"  # type: ignore[attr-defined]

from app.core.security import AuthenticatedUser
from app.domain.exceptions import InvalidInvoiceError
from app.domain.models.stock import MovementType
from app.persistence.base import Base
from app.persistence.models import *  # noqa: F401,F403 — register metadata
from app.persistence.models.contractor import ContractorORM
from app.persistence.models.stock import StockMovementORM, StockORM, WarehouseORM
from app.persistence.repositories.audit_repository import AuditRepository
from app.persistence.repositories.contractor_override_repository import (
    ContractorOverrideRepository,
)
from app.persistence.repositories.contractor_repository import ContractorRepository
from app.persistence.repositories.invoice_repository import InvoiceRepository
from app.persistence.repositories.stock_repository import StockRepository
from app.services.audit_service import AuditService
from app.services.invoice_service import InvoiceService
from app.services.stock_service import DEFAULT_WAREHOUSE_ID, StockError, StockService


DEFAULT_WH = DEFAULT_WAREHOUSE_ID


@pytest.fixture()
def engine():
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def session_factory(engine):
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


@pytest.fixture()
def session(session_factory):
    s = session_factory()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


@pytest.fixture()
def default_warehouse(session: Session, monkeypatch):
    """Seed magazynu domyślnego i podmień DEFAULT_WAREHOUSE_ID (SQLite UUID quirk)."""
    wh_id = uuid4()
    session.add(
        WarehouseORM(
            id=wh_id,
            name="Magazyn główny",
            is_default=True,
            created_at=datetime.now(UTC),
        )
    )
    session.flush()
    monkeypatch.setattr(
        "app.services.stock_service.DEFAULT_WAREHOUSE_ID",
        wh_id,
    )
    return wh_id


@pytest.fixture()
def actor() -> AuthenticatedUser:
    return AuthenticatedUser(user_id=str(uuid4()), username="tester", role="administrator")


@pytest.fixture()
def buyer(session: Session) -> ContractorORM:
    c = ContractorORM(
        id=uuid4(),
        nip="5252344078",
        name="Nabywca Test",
        city="Warszawa",
        country="PL",
        source="test",
    )
    session.add(c)
    session.flush()
    return c


@pytest.fixture()
def services(session: Session, default_warehouse):
    stock_repo = StockRepository(session)
    stock = StockService(session, stock_repo)
    invoice = InvoiceService(
        session=session,
        invoice_repository=InvoiceRepository(session),
        contractor_repository=ContractorRepository(session),
        contractor_override_repository=ContractorOverrideRepository(session),
        audit_service=AuditService(session, AuditRepository(session)),
        stock_service=stock,
    )
    return stock, invoice


def _create_product(stock: StockService, name: str = "Książka", isbn: str = "978-83-123456-7-8"):
    return stock.create_product(name=name, isbn=isbn, unit="szt")


def _seed_qty(session: Session, product_id, qty: str, warehouse_id) -> None:
    orm = session.execute(
        select(StockORM)
        .where(StockORM.product_id == product_id)
        .where(StockORM.warehouse_id == warehouse_id)
    ).scalar_one_or_none()
    if orm is None:
        session.add(
            StockORM(
                id=uuid4(),
                product_id=product_id,
                warehouse_id=warehouse_id,
                quantity=Decimal(qty),
            )
        )
    else:
        orm.quantity = Decimal(qty)
    session.flush()


def _invoice_payload(buyer_id, items, direction="sale"):
    return {
        "buyer_id": buyer_id,
        "issue_date": date(2026, 7, 31),
        "sale_date": date(2026, 7, 31),
        "currency": "PLN",
        "direction": direction,
        "items": items,
    }


_SELLER = dict(
    seller_nip="5250001008",
    seller_name="Sprzedawca",
    seller_street="ul. A",
    seller_building_no="1",
    seller_apartment_no=None,
    seller_postal_code="00-001",
    seller_city="Warszawa",
    seller_country="PL",
)


class TestInvoiceStockIntegration:
    def test_sale_decreases_stock(self, session, services, buyer, actor, override_settings, default_warehouse):
        stock, invoice_svc = services
        with override_settings(**_SELLER):
            product = _create_product(stock)
            _seed_qty(session, product.id, "10", default_warehouse)
            inv = invoice_svc.create_invoice(
                _invoice_payload(
                    buyer.id,
                    [
                        {
                            "name": product.name,
                            "quantity": "3",
                            "unit": "szt",
                            "unit_price_net": "10.00",
                            "vat_rate": "23",
                            "product_id": product.id,
                        }
                    ],
                ),
                actor,
            )
            assert inv.id is not None
            st = stock.list_stock()[0]
            assert st.quantity == Decimal("7")
            moves = stock.list_movements(invoice_id=inv.id)
            assert len(moves) == 1
            assert moves[0].movement_type == MovementType.SALE
            assert moves[0].invoice_item_id == inv.items[0].id

    def test_purchase_increases_stock(self, session, services, buyer, actor, override_settings, default_warehouse):
        stock, invoice_svc = services
        with override_settings(**_SELLER):
            product = _create_product(stock, name="Towar Z", isbn="978-83-999999-9-9")
            _seed_qty(session, product.id, "1", default_warehouse)
            inv = invoice_svc.create_invoice(
                _invoice_payload(
                    buyer.id,
                    [
                        {
                            "name": product.name,
                            "quantity": "5",
                            "unit": "szt",
                            "unit_price_net": "2.00",
                            "vat_rate": "23",
                            "product_id": product.id,
                        }
                    ],
                    direction="purchase",
                ),
                actor,
            )
            st = stock.list_stock()[0]
            assert st.quantity == Decimal("6")
            assert stock.list_movements(invoice_id=inv.id)[0].movement_type == MovementType.PURCHASE

    def test_service_item_skips_movement(self, session, services, buyer, actor, override_settings):
        stock, invoice_svc = services
        with override_settings(**_SELLER):
            inv = invoice_svc.create_invoice(
                _invoice_payload(
                    buyer.id,
                    [
                        {
                            "name": "Usługa IT",
                            "quantity": "2",
                            "unit": "godz.",
                            "unit_price_net": "100.00",
                            "vat_rate": "23",
                            "product_id": None,
                        }
                    ],
                ),
                actor,
            )
            assert stock.list_movements(invoice_id=inv.id) == []
            assert stock.list_stock() == []

    def test_oversell_rolls_back_invoice_and_movements(
        self, session, services, buyer, actor, override_settings, default_warehouse
    ):
        stock, invoice_svc = services
        with override_settings(**_SELLER):
            product = _create_product(stock)
            _seed_qty(session, product.id, "2", default_warehouse)
            with session.begin_nested():
                with pytest.raises(StockError):
                    invoice_svc.create_invoice(
                        _invoice_payload(
                            buyer.id,
                            [
                                {
                                    "name": product.name,
                                    "quantity": "5",
                                    "unit": "szt",
                                    "unit_price_net": "10.00",
                                    "vat_rate": "23",
                                    "product_id": product.id,
                                }
                            ],
                        ),
                        actor,
                    )
            # Savepoint cofnięty — seed stanu nienaruszony, brak ruchów
            st = session.execute(select(StockORM)).scalars().all()
            assert len(st) == 1
            assert Decimal(str(st[0].quantity)) == Decimal("2")
            assert session.execute(select(StockMovementORM)).scalars().all() == []

    def test_two_products_two_movements(self, session, services, buyer, actor, override_settings, default_warehouse):
        stock, invoice_svc = services
        with override_settings(**_SELLER):
            p1 = stock.create_product(name="A", isbn="978-83-111111-1-1", unit="szt")
            p2 = stock.create_product(name="B", isbn="978-83-222222-2-2", unit="szt")
            _seed_qty(session, p1.id, "10", default_warehouse)
            _seed_qty(session, p2.id, "10", default_warehouse)
            inv = invoice_svc.create_invoice(
                _invoice_payload(
                    buyer.id,
                    [
                        {
                            "name": "A",
                            "quantity": "1",
                            "unit": "szt",
                            "unit_price_net": "1",
                            "vat_rate": "23",
                            "product_id": p1.id,
                        },
                        {
                            "name": "B",
                            "quantity": "2",
                            "unit": "szt",
                            "unit_price_net": "1",
                            "vat_rate": "23",
                            "product_id": p2.id,
                        },
                    ],
                ),
                actor,
            )
            moves = stock.list_movements(invoice_id=inv.id)
            assert len(moves) == 2
            by_product = {m.product_id: m.quantity for m in moves}
            assert by_product[p1.id] == Decimal("1")
            assert by_product[p2.id] == Decimal("2")

    def test_reprocess_same_invoice_does_not_duplicate(
        self, session, services, buyer, actor, override_settings, default_warehouse
    ):
        stock, invoice_svc = services
        with override_settings(**_SELLER):
            product = _create_product(stock)
            _seed_qty(session, product.id, "10", default_warehouse)
            inv = invoice_svc.create_invoice(
                _invoice_payload(
                    buyer.id,
                    [
                        {
                            "name": product.name,
                            "quantity": "2",
                            "unit": "szt",
                            "unit_price_net": "10",
                            "vat_rate": "23",
                            "product_id": product.id,
                        }
                    ],
                ),
                actor,
            )
            again = stock.handle_invoice_created(
                invoice_id=inv.id,
                direction="sale",
                items=[
                    {
                        "product_id": product.id,
                        "quantity": Decimal("2"),
                        "invoice_item_id": inv.items[0].id,
                    }
                ],
            )
            assert len(again) == 1
            assert len(stock.list_movements(invoice_id=inv.id)) == 1
            assert stock.list_stock()[0].quantity == Decimal("8")

    def test_reverse_restores_stock(self, session, services, buyer, actor, override_settings, default_warehouse):
        stock, invoice_svc = services
        with override_settings(**_SELLER):
            product = _create_product(stock)
            _seed_qty(session, product.id, "10", default_warehouse)
            inv = invoice_svc.create_invoice(
                _invoice_payload(
                    buyer.id,
                    [
                        {
                            "name": product.name,
                            "quantity": "4",
                            "unit": "szt",
                            "unit_price_net": "10",
                            "vat_rate": "23",
                            "product_id": product.id,
                        }
                    ],
                ),
                actor,
            )
            assert stock.list_stock()[0].quantity == Decimal("6")
            reversed_m = stock.reverse_invoice_stock_movements(inv.id)
            assert len(reversed_m) == 1
            assert reversed_m[0].movement_type == MovementType.PURCHASE
            assert stock.list_stock()[0].quantity == Decimal("10")
            assert len(stock.list_movements(invoice_id=inv.id)) == 2
            assert stock.reverse_invoice_stock_movements(inv.id) == []

    def test_sequential_sales_cannot_go_negative(
        self, session_factory, actor, override_settings, monkeypatch
    ):
        """Dwie kolejne sprzedaże przy stanie 1 — druga musi failować bez zejścia poniżej 0."""
        with override_settings(**_SELLER):
            s1 = session_factory()
            try:
                wh_id = uuid4()
                s1.add(
                    WarehouseORM(
                        id=wh_id,
                        name="Magazyn główny",
                        is_default=True,
                        created_at=datetime.now(UTC),
                    )
                )
                monkeypatch.setattr("app.services.stock_service.DEFAULT_WAREHOUSE_ID", wh_id)
                buyer = ContractorORM(
                    id=uuid4(),
                    nip="5252344099",
                    name="Nabywca Seq",
                    city="Warszawa",
                    country="PL",
                    source="test",
                )
                s1.add(buyer)
                s1.flush()
                stock = StockService(s1, StockRepository(s1))
                invoice_svc = InvoiceService(
                    session=s1,
                    invoice_repository=InvoiceRepository(s1),
                    contractor_repository=ContractorRepository(s1),
                    contractor_override_repository=ContractorOverrideRepository(s1),
                    audit_service=AuditService(s1, AuditRepository(s1)),
                    stock_service=stock,
                )
                product = _create_product(stock)
                _seed_qty(s1, product.id, "1", wh_id)
                invoice_svc.create_invoice(
                    _invoice_payload(
                        buyer.id,
                        [
                            {
                                "name": product.name,
                                "quantity": "1",
                                "unit": "szt",
                                "unit_price_net": "10",
                                "vat_rate": "23",
                                "product_id": product.id,
                            }
                        ],
                    ),
                    actor,
                )
                s1.commit()
                product_id = product.id
                buyer_id = buyer.id
            finally:
                s1.close()

            s2 = session_factory()
            try:
                stock2 = StockService(s2, StockRepository(s2))
                invoice_svc2 = InvoiceService(
                    session=s2,
                    invoice_repository=InvoiceRepository(s2),
                    contractor_repository=ContractorRepository(s2),
                    contractor_override_repository=ContractorOverrideRepository(s2),
                    audit_service=AuditService(s2, AuditRepository(s2)),
                    stock_service=stock2,
                )
                with pytest.raises(StockError):
                    invoice_svc2.create_invoice(
                        _invoice_payload(
                            buyer_id,
                            [
                                {
                                    "name": "x",
                                    "quantity": "1",
                                    "unit": "szt",
                                    "unit_price_net": "10",
                                    "vat_rate": "23",
                                    "product_id": product_id,
                                }
                            ],
                        ),
                        actor,
                    )
                s2.rollback()
                assert stock2.list_stock()[0].quantity == Decimal("0")
            finally:
                s2.close()

    def test_transfer_rejected(self, services):
        stock, _ = services
        product = _create_product(stock)
        with pytest.raises(StockError, match="TRANSFER"):
            stock.create_movement(
                movement_type=MovementType.TRANSFER,
                product_id=product.id,
                quantity=Decimal("1"),
            )

    def test_unknown_product_id_rejected(self, services, buyer, actor, override_settings):
        _, invoice_svc = services
        with override_settings(**_SELLER):
            with pytest.raises(InvalidInvoiceError, match="nie istnieje"):
                invoice_svc.create_invoice(
                    _invoice_payload(
                        buyer.id,
                        [
                            {
                                "name": "X",
                                "quantity": "1",
                                "unit": "szt",
                                "unit_price_net": "1",
                                "vat_rate": "23",
                                "product_id": uuid4(),
                            }
                        ],
                    ),
                    actor,
                )


class TestMigrationSmoke:
    def test_revision_file_and_chain(self):
        from pathlib import Path
        import importlib.util

        path = (
            Path(__file__).resolve().parents[2]
            / "alembic"
            / "versions"
            / "0011_k1l2m3n4o5p6_invoice_item_product_stock_idempotency.py"
        )
        spec = importlib.util.spec_from_file_location("mig0011", path)
        mod = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(mod)
        assert mod.down_revision == "j0k1l2m3n4o5"
        assert mod.revision == "k1l2m3n4o5p6"
        assert callable(mod.upgrade)
        assert callable(mod.downgrade)

    def test_schema_has_new_columns(self, engine):
        with engine.connect() as conn:
            cols_items = {
                row[1] for row in conn.execute(text("PRAGMA table_info(invoice_items)"))
            }
            cols_mov = {
                row[1] for row in conn.execute(text("PRAGMA table_info(stock_movements)"))
            }
        assert "product_id" in cols_items
        assert "invoice_item_id" in cols_mov
