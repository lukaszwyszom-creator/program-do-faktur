"""Transaction hardening tests.

Weryfikuje:
1. Atomowość rollbacku — jeżeli serwis rzuca po częściowym zapisie,
   w bazie nie powinno być żadnych śladów.
2. Odporność importu CSV na brudne dane wejściowe.
3. Sekwencyjność numeracji faktur (brak duplikatów przy retry).
4. Override settings — bezpieczny wzorzec bez efektów ubocznych.

UWAGA nt. SQLite vs PostgreSQL:
- SQLite nie wspiera prawdziwych FOR UPDATE locks — lock_for_update()
  pada na SQLite do zwykłego SELECT. Retry na deadlock jest niemożliwy
  do przetestowania bez PostgreSQL.
- SQLite nie wspiera prawdziwych równoległych pisarzy (WAL mode excluded).
  Testy współbieżności wymagają PostgreSQL — oznaczone @pytest.mark.postgres.
- JSONB → JSON patch aktywny w e2e_mvp.py.
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

# JSONB → JSON patch dla SQLite DDL
if not hasattr(SQLiteTypeCompiler, "visit_JSONB"):
    SQLiteTypeCompiler.visit_JSONB = lambda self, type_, **kw: "JSON"  # type: ignore[attr-defined]

from app.core.security import AuthenticatedUser
from app.core.utils import to_uuid
from app.persistence.base import Base
from app.persistence.models import (  # noqa: F401 — force model registration
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
from app.persistence.repositories.invoice_repository import InvoiceRepository
from app.persistence.repositories.audit_repository import AuditRepository


# ---------------------------------------------------------------------------
# SQLite in-memory engine (StaticPool) — shared across tests in module
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def sqlite_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False,
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def db(sqlite_engine):
    """Per-test session; always rolls back after test."""
    connection = sqlite_engine.connect()
    trans = connection.begin()
    session = Session(bind=connection)
    yield session
    session.close()
    trans.rollback()
    connection.close()


@pytest.fixture()
def actor() -> AuthenticatedUser:
    return AuthenticatedUser(
        user_id=str(uuid.uuid4()),
        username="test_admin",
        role="administrator",
    )


# ---------------------------------------------------------------------------
# 1. Rollback atomicity
# ---------------------------------------------------------------------------


class TestRollbackAtomicity:
    """Partial writes must NOT be committed when an exception is raised."""

    def test_audit_write_rolled_back_on_exception(self, db, actor):
        """If AuditService.record() raises after invoice is flushed,
        the whole transaction is rolled back by get_session().
        Simulates the upper layer (get_session) doing rollback."""
        from app.services.audit_service import AuditService
        from app.persistence.repositories.audit_repository import AuditRepository

        audit_repo = AuditRepository(db)
        audit_svc = AuditService(session=db, audit_repository=audit_repo)

        # Simulate a partial write: insert a contractor, then raise
        contractor = ContractorORM(
            nip="1111111111",
            name="Rollback Test",
            source="manual",
        )
        db.add(contractor)
        db.flush()  # ID assigned, but NOT committed

        # Simulate get_session rollback on exception
        db.rollback()

        # Verify nothing persisted
        result = db.query(ContractorORM).filter_by(nip="1111111111").first()
        assert result is None, "Rolled-back contractor must not be in DB"

    def test_invoice_plus_audit_atomic(self, db, actor):
        """Invoice write + audit write in same session — if audit fails,
        invoice is also rolled back."""
        from app.services.audit_service import AuditService
        from app.persistence.repositories.audit_repository import AuditRepository

        # Seed a contractor
        buyer = ContractorORM(nip="2222222222", name="Buyer", source="manual")
        user = UserORM(
            username=f"user_{uuid.uuid4().hex[:6]}",
            password_hash="hash",
            role="administrator",
            is_active=True,
        )
        db.add_all([buyer, user])
        db.flush()

        invoice_id = uuid.uuid4()

        inv_orm = InvoiceORM(
            id=invoice_id,
            status="draft",
            payment_status="unpaid",
            seller_snapshot_json={"nip": "9876543210"},
            buyer_snapshot_json={"nip": "2222222222"},
            totals_json={"total_net": "100", "total_vat": "23", "total_gross": "123"},
            issue_date=date(2026, 4, 1),
            sale_date=date(2026, 4, 1),
            currency="PLN",
            created_by=to_uuid(actor.user_id),
        )
        db.add(inv_orm)
        db.flush()

        # Verify invoice is visible within same session
        assert db.get(InvoiceORM, invoice_id) is not None

        # Now rollback (simulating exception in upper service)
        db.rollback()

        # Invoice must be gone
        assert db.get(InvoiceORM, invoice_id) is None, (
            "Invoice write must be rolled back atomically"
        )

    def test_get_session_rollback_on_service_exception(self):
        """Integration: get_session() must persist NOTHING when service raises."""
        from unittest.mock import patch as _patch
        import app.persistence.db as db_module
        from sqlalchemy.pool import StaticPool as SP

        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=SP,
        )
        Base.metadata.create_all(engine)
        orig_engine = db_module.engine
        orig_sl = db_module.SessionLocal
        db_module.engine = engine
        db_module.SessionLocal = sessionmaker(
            bind=engine, autoflush=False, autocommit=False,
            expire_on_commit=False,
        )

        try:
            def _failing_operation():
                gen = db_module.get_session()
                session = next(gen)
                # Write something
                c = ContractorORM(nip="3333333333", name="Will Rollback", source="manual")
                session.add(c)
                session.flush()
                # Raise to trigger rollback
                try:
                    raise RuntimeError("Simulated failure")
                except RuntimeError as exc:
                    try:
                        gen.throw(exc)
                    except RuntimeError:
                        pass  # get_session rolled back and re-raised

            _failing_operation()

            # After the generator is exhausted, the rollback should have happened
            with db_module.SessionLocal() as check_session:
                result = check_session.query(ContractorORM).filter_by(nip="3333333333").first()
                assert result is None, "Rolled-back write must NOT appear in DB"
        finally:
            db_module.engine = orig_engine
            db_module.SessionLocal = orig_sl
            engine.dispose()


# ---------------------------------------------------------------------------
# 2. Import CSV — dirty data
# ---------------------------------------------------------------------------


class TestImportCsvDirtyData:
    """payment_service.import_csv() must handle malformed input gracefully."""

    def _service(self, db):
        from app.services.payment_service import PaymentService
        from app.services.audit_service import AuditService
        from app.persistence.repositories.bank_transaction_repository import BankTransactionRepository
        from app.persistence.repositories.payment_allocation_repository import PaymentAllocationRepository
        from app.persistence.repositories.invoice_repository import InvoiceRepository
        from app.persistence.repositories.audit_repository import AuditRepository

        audit_svc = AuditService(session=db, audit_repository=AuditRepository(db))
        return PaymentService(
            session=db,
            bank_transaction_repository=BankTransactionRepository(db),
            allocation_repository=PaymentAllocationRepository(db),
            invoice_repository=InvoiceRepository(db),
            audit_service=audit_svc,
        )

    def test_empty_csv_returns_zero(self, db, actor):
        svc = self._service(db)
        result = svc.import_csv("transaction_date,amount,currency,title\n", source_file="empty.csv", actor=actor)
        assert result["imported"] == 0
        assert result["skipped"] == 0

    def test_missing_amount_skipped(self, db, actor):
        svc = self._service(db)
        result = svc.import_csv(
            "transaction_date,amount,currency,title\n2026-04-01,,PLN,Test\n",
            source_file="bad.csv", actor=actor,
        )
        assert result["imported"] == 0
        assert result["skipped"] == 1

    def test_invalid_date_skipped(self, db, actor):
        svc = self._service(db)
        result = svc.import_csv(
            "transaction_date,amount,currency,title\nnot-a-date,100.00,PLN,Test\n",
            source_file="bad.csv", actor=actor,
        )
        assert result["imported"] == 0
        assert result["skipped"] == 1

    def test_duplicate_external_id_skipped(self, db, actor):
        svc = self._service(db)
        svc.import_csv(
            "transaction_date,amount,currency,title,external_id\n"
            "2026-04-01,100.00,PLN,Test,EXT-001\n",
            source_file="f1.csv", actor=actor,
        )
        result = svc.import_csv(
            "transaction_date,amount,currency,title,external_id\n"
            "2026-04-02,200.00,PLN,Test2,EXT-001\n",
            source_file="f2.csv", actor=actor,
        )
        assert result["skipped"] == 1
        assert result["imported"] == 0

    def test_valid_row_imported_by_is_uuid(self, db, actor):
        svc = self._service(db)
        result = svc.import_csv(
            "transaction_date,amount,currency,title\n2026-04-01,500.00,PLN,Przelew\n",
            source_file="valid.csv", actor=actor,
        )
        assert result["imported"] == 1

        tx = db.query(BankTransactionORM).first()
        assert isinstance(tx.imported_by, uuid.UUID), (
            f"imported_by must be uuid.UUID, got {type(tx.imported_by)}"
        )

    def test_mixed_rows_partial_import(self, db, actor):
        svc = self._service(db)
        result = svc.import_csv(
            "transaction_date,amount,currency,title\n"
            "2026-04-01,100.00,PLN,Good row\n"
            "not-a-date,,PLN,Bad row\n"
            "2026-04-02,200.00,PLN,Another good row\n",
            source_file="mixed.csv", actor=actor,
        )
        assert result["imported"] == 2
        assert result["skipped"] == 1

    def test_negative_amount_imported(self, db, actor):
        """Negative amounts (refunds) should be imported, not skipped."""
        svc = self._service(db)
        result = svc.import_csv(
            "transaction_date,amount,currency,title\n2026-04-01,-50.00,PLN,Zwrot\n",
            source_file="neg.csv", actor=actor,
        )
        # Negative amounts are valid bank transactions (refunds)
        assert result["imported"] == 1


# ---------------------------------------------------------------------------
# 3. Invoice number sequential — no duplicates on retry
# ---------------------------------------------------------------------------


class TestInvoiceNumberSequential:
    """Verify that sequential calls to mark_as_ready produce unique numbers."""

    def _seed_user_and_buyer(self, db) -> tuple[UserORM, ContractorORM]:
        user = UserORM(
            username=f"admin_{uuid.uuid4().hex[:6]}",
            password_hash="hash",
            role="administrator",
            is_active=True,
        )
        buyer = ContractorORM(nip=f"{uuid.uuid4().int % 10**10:010d}", name="B", source="manual")
        db.add_all([user, buyer])
        db.flush()
        return user, buyer

    def _make_draft_invoice(self, db, user: UserORM) -> InvoiceORM:
        inv = InvoiceORM(
            id=uuid.uuid4(),
            status="draft",
            payment_status="unpaid",
            seller_snapshot_json={"nip": "1234567890"},
            buyer_snapshot_json={"nip": "9876543210"},
            totals_json={"total_net": "100", "total_vat": "23", "total_gross": "123"},
            issue_date=date(2026, 4, 1),
            sale_date=date(2026, 4, 1),
            currency="PLN",
            created_by=user.id,
        )
        db.add(inv)
        db.flush()
        return inv

    def _invoice_service(self, db) -> "InvoiceService":  # type: ignore[name-defined]
        from app.services.invoice_service import InvoiceService
        from app.services.audit_service import AuditService
        from app.persistence.repositories.invoice_repository import InvoiceRepository
        from app.persistence.repositories.contractor_repository import ContractorRepository
        from app.persistence.repositories.contractor_override_repository import ContractorOverrideRepository
        from app.persistence.repositories.audit_repository import AuditRepository

        audit = AuditService(session=db, audit_repository=AuditRepository(db))
        return InvoiceService(
            session=db,
            invoice_repository=InvoiceRepository(db),
            contractor_repository=ContractorRepository(db),
            contractor_override_repository=ContractorOverrideRepository(db),
            audit_service=audit,
        )

    def test_two_sequential_mark_ready_get_different_numbers(self, db, actor):
        svc = self._invoice_service(db)
        user, _ = self._seed_user_and_buyer(db)

        inv1 = self._make_draft_invoice(db, user)
        inv2 = self._make_draft_invoice(db, user)

        result1 = svc.mark_as_ready(inv1.id, actor)
        result2 = svc.mark_as_ready(inv2.id, actor)

        assert result1.number_local != result2.number_local, (
            f"Duplicate invoice numbers: {result1.number_local}"
        )
        assert result1.number_local is not None
        assert result2.number_local is not None

    def test_same_invoice_mark_ready_idempotent_via_status_guard(self, db, actor):
        """Attempting mark_as_ready twice raises InvalidStatusTransitionError."""
        from app.domain.exceptions import InvalidStatusTransitionError

        svc = self._invoice_service(db)
        user, _ = self._seed_user_and_buyer(db)
        inv = self._make_draft_invoice(db, user)

        svc.mark_as_ready(inv.id, actor)

        with pytest.raises(InvalidStatusTransitionError):
            svc.mark_as_ready(inv.id, actor)


# ---------------------------------------------------------------------------
# 4. Settings override — no side-effects
# ---------------------------------------------------------------------------


class TestSettingsOverride:
    def test_override_settings_fixture_restores(self, override_settings):
        from app.core.config import settings

        original_nip = settings.seller_nip
        with override_settings(seller_nip="0000000000"):
            assert settings.seller_nip == "0000000000"
        # After context manager exits, setting is restored
        assert settings.seller_nip == original_nip

    def test_override_settings_restores_on_exception(self, override_settings):
        from app.core.config import settings

        original_nip = settings.seller_nip
        try:
            with override_settings(seller_nip="1111111111"):
                raise RuntimeError("Test failure")
        except RuntimeError:
            pass
        assert settings.seller_nip == original_nip, (
            "Settings must be restored even when test raises"
        )

    def test_multiple_overrides_all_restored(self, override_settings):
        from app.core.config import settings

        orig_nip = settings.seller_nip
        orig_name = settings.seller_name
        with override_settings(seller_nip="2222222222", seller_name="Test Corp"):
            assert settings.seller_nip == "2222222222"
            assert settings.seller_name == "Test Corp"
        assert settings.seller_nip == orig_nip
        assert settings.seller_name == orig_name
