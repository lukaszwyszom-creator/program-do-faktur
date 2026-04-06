"""Testy PaymentService — unit (mocki repozytoriów, bez bazy danych)."""
from __future__ import annotations

import uuid
from datetime import date, datetime, UTC
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.core.exceptions import NotFoundError
from app.core.security import AuthenticatedUser
from app.domain.enums import InvoicePaymentStatus, PaymentMatchMethod, PaymentMatchStatus
from app.persistence.models.bank_transaction import BankTransactionORM
from app.persistence.models.invoice import InvoiceORM
from app.persistence.models.payment_allocation import PaymentAllocationORM
from app.services.payment_service import PaymentService, _parse_csv


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_service(
    session=None,
    tx_repo=None,
    alloc_repo=None,
    inv_repo=None,
    audit=None,
    matcher=None,
) -> PaymentService:
    return PaymentService(
        session=session or MagicMock(),
        bank_transaction_repository=tx_repo or MagicMock(),
        allocation_repository=alloc_repo or MagicMock(),
        invoice_repository=inv_repo or MagicMock(),
        audit_service=audit or MagicMock(),
        matcher=matcher,
    )


def _make_tx_orm(amount: Decimal = Decimal("1000.00")) -> BankTransactionORM:
    orm = BankTransactionORM(
        id=uuid4(),
        transaction_date=date(2026, 4, 1),
        amount=amount,
        currency="PLN",
        remaining_amount=amount,
        match_status=PaymentMatchStatus.UNMATCHED.value,
        imported_at=datetime.now(UTC),
    )
    return orm


def _make_invoice_orm(gross: Decimal = Decimal("1000.00")) -> InvoiceORM:
    orm = MagicMock(spec=InvoiceORM)
    orm.id = uuid4()
    orm.totals_json = {"total_gross": str(gross)}
    orm.payment_status = InvoicePaymentStatus.UNPAID.value
    return orm


def _make_alloc_orm(tx_id, invoice_id, amount: Decimal = Decimal("1000.00")) -> PaymentAllocationORM:
    orm = PaymentAllocationORM(
        id=uuid4(),
        transaction_id=tx_id,
        invoice_id=invoice_id,
        allocated_amount=amount,
        match_method=PaymentMatchMethod.MANUAL.value,
        is_reversed=False,
        created_at=datetime.now(UTC),
    )
    return orm


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def actor() -> AuthenticatedUser:
    return AuthenticatedUser(user_id=str(uuid4()), username="test", role="administrator")


@pytest.fixture()
def mock_session() -> MagicMock:
    s = MagicMock()
    s.begin.return_value.__enter__ = MagicMock(return_value=None)
    s.begin.return_value.__exit__ = MagicMock(return_value=False)
    return s


# ---------------------------------------------------------------------------
# CSV parsing
# ---------------------------------------------------------------------------

class TestCsvParsing:
    def test_parse_comma_csv(self):
        content = (
            "data,kwota,waluta,nazwa kontrahenta,tytuł\n"
            "2026-04-01,1230.00,PLN,ACME Sp. z o.o.,FV/1/04/2026\n"
        )
        rows = _parse_csv(content)
        assert len(rows) == 1
        assert rows[0]["transaction_date"] == "2026-04-01"
        assert rows[0]["amount"] == "1230.00"
        assert rows[0]["title"] == "FV/1/04/2026"

    def test_parse_semicolon_csv(self):
        content = "data;kwota;waluta\n2026-04-02;500,00;PLN\n"
        rows = _parse_csv(content)
        assert len(rows) == 1
        assert rows[0]["transaction_date"] == "2026-04-02"

    def test_empty_csv_returns_empty(self):
        rows = _parse_csv("")
        assert rows == []


# ---------------------------------------------------------------------------
# allocate_manual
# ---------------------------------------------------------------------------

class TestAllocateManual:
    def test_allocate_full_payment(self, actor, mock_session):
        tx = _make_tx_orm(Decimal("1000.00"))
        inv = _make_invoice_orm(Decimal("1000.00"))

        tx_repo = MagicMock()
        tx_repo.get_by_id.return_value = tx

        alloc_repo = MagicMock()
        alloc_repo.add.side_effect = lambda x: x
        alloc_repo.sum_allocated_for_transaction.return_value = Decimal("1000.00")
        alloc_repo.sum_allocated_for_invoice.return_value = Decimal("1000.00")

        inv_repo = MagicMock()
        inv_repo.get_orm_by_id.return_value = inv

        svc = _make_service(
            session=mock_session,
            tx_repo=tx_repo,
            alloc_repo=alloc_repo,
            inv_repo=inv_repo,
        )

        alloc = svc.allocate_manual(tx.id, inv.id, Decimal("1000.00"), actor)
        assert alloc.allocated_amount == Decimal("1000.00")
        # Invoice payment_status should be set to paid
        assert inv.payment_status == InvoicePaymentStatus.PAID.value

    def test_allocate_partial_payment(self, actor, mock_session):
        tx = _make_tx_orm(Decimal("1000.00"))
        inv = _make_invoice_orm(Decimal("2000.00"))

        tx_repo = MagicMock()
        tx_repo.get_by_id.return_value = tx

        alloc_repo = MagicMock()
        alloc_repo.add.side_effect = lambda x: x
        alloc_repo.sum_allocated_for_transaction.return_value = Decimal("1000.00")
        alloc_repo.sum_allocated_for_invoice.return_value = Decimal("1000.00")

        inv_repo = MagicMock()
        inv_repo.get_orm_by_id.return_value = inv

        svc = _make_service(
            session=mock_session,
            tx_repo=tx_repo,
            alloc_repo=alloc_repo,
            inv_repo=inv_repo,
        )

        alloc = svc.allocate_manual(tx.id, inv.id, Decimal("1000.00"), actor)
        assert alloc.allocated_amount == Decimal("1000.00")
        assert inv.payment_status == InvoicePaymentStatus.PARTIALLY_PAID.value

    def test_amount_exceeds_remaining_raises(self, actor, mock_session):
        tx = _make_tx_orm(Decimal("500.00"))  # remaining = 500
        inv = _make_invoice_orm(Decimal("1000.00"))

        tx_repo = MagicMock()
        tx_repo.get_by_id.return_value = tx
        inv_repo = MagicMock()
        inv_repo.get_orm_by_id.return_value = inv

        svc = _make_service(session=mock_session, tx_repo=tx_repo, inv_repo=inv_repo)

        with pytest.raises(ValueError, match="przekracza"):
            svc.allocate_manual(tx.id, inv.id, Decimal("600.00"), actor)

    def test_transaction_not_found_raises(self, actor, mock_session):
        tx_repo = MagicMock()
        tx_repo.get_by_id.return_value = None
        svc = _make_service(session=mock_session, tx_repo=tx_repo)
        with pytest.raises(NotFoundError):
            svc.allocate_manual(uuid4(), uuid4(), Decimal("100.00"), actor)

    def test_invoice_not_found_raises(self, actor, mock_session):
        tx = _make_tx_orm(Decimal("1000.00"))
        tx_repo = MagicMock()
        tx_repo.get_by_id.return_value = tx
        inv_repo = MagicMock()
        inv_repo.get_orm_by_id.return_value = None
        svc = _make_service(session=mock_session, tx_repo=tx_repo, inv_repo=inv_repo)
        with pytest.raises(NotFoundError):
            svc.allocate_manual(tx.id, uuid4(), Decimal("100.00"), actor)


# ---------------------------------------------------------------------------
# reverse_allocation
# ---------------------------------------------------------------------------

class TestReverseAllocation:
    def test_reverse_restores_invoice_to_unpaid(self, actor, mock_session):
        tx = _make_tx_orm(Decimal("1000.00"))
        inv = _make_invoice_orm(Decimal("1000.00"))
        alloc = _make_alloc_orm(tx.id, inv.id, Decimal("1000.00"))

        alloc_repo = MagicMock()
        alloc_repo.get_by_id.return_value = alloc
        alloc_repo.reverse.side_effect = lambda aid, uid: setattr(alloc, "is_reversed", True) or alloc
        alloc_repo.sum_allocated_for_transaction.return_value = Decimal("0.00")
        alloc_repo.sum_allocated_for_invoice.return_value = Decimal("0.00")

        tx_repo = MagicMock()
        tx_repo.get_by_id.return_value = tx

        inv_repo = MagicMock()
        inv_repo.get_orm_by_id.return_value = inv
        inv.payment_status = InvoicePaymentStatus.PAID.value

        svc = _make_service(
            session=mock_session,
            tx_repo=tx_repo,
            alloc_repo=alloc_repo,
            inv_repo=inv_repo,
        )

        svc.reverse_allocation(alloc.id, actor)

        # After reversal tx remaining = full amount → unmatched
        tx_repo.update_match_status.assert_called_once()
        call_args = tx_repo.update_match_status.call_args
        assert call_args[0][1] == PaymentMatchStatus.UNMATCHED
        # Invoice payment_status should revert to unpaid
        assert inv.payment_status == InvoicePaymentStatus.UNPAID.value

    def test_allocation_not_found_raises(self, actor, mock_session):
        alloc_repo = MagicMock()
        alloc_repo.get_by_id.return_value = None
        svc = _make_service(session=mock_session, alloc_repo=alloc_repo)
        with pytest.raises(NotFoundError):
            svc.reverse_allocation(uuid4(), actor)


# ---------------------------------------------------------------------------
# _compute_tx_match_status
# ---------------------------------------------------------------------------

class TestComputeTxMatchStatus:
    def test_remaining_zero_is_matched(self):
        status = PaymentService._compute_tx_match_status(Decimal("1000"), Decimal("0"))
        assert status == PaymentMatchStatus.MATCHED

    def test_remaining_partial_is_partial(self):
        status = PaymentService._compute_tx_match_status(Decimal("1000"), Decimal("500"))
        assert status == PaymentMatchStatus.PARTIAL

    def test_remaining_full_is_unmatched(self):
        status = PaymentService._compute_tx_match_status(Decimal("1000"), Decimal("1000"))
        assert status == PaymentMatchStatus.UNMATCHED
