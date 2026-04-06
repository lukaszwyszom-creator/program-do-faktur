"""Testy transition_to() w domain model Invoice."""
from datetime import date, datetime, UTC
from decimal import Decimal
from uuid import uuid4

import pytest

from app.domain.enums import InvoiceStatus
from app.domain.exceptions import InvalidStatusTransitionError
from app.domain.models.invoice import Invoice


def _make_invoice(status: InvoiceStatus = InvoiceStatus.DRAFT) -> Invoice:
    now = datetime.now(UTC)
    return Invoice(
        id=uuid4(), status=status,
        issue_date=date(2026, 1, 15), sale_date=date(2026, 1, 15),
        currency="PLN", seller_snapshot={}, buyer_snapshot={}, items=[],
        total_net=Decimal("0"), total_vat=Decimal("0"), total_gross=Decimal("0"),
        created_at=now, updated_at=now,
    )


class TestTransitionTo:
    def test_draft_to_ready(self):
        inv = _make_invoice(InvoiceStatus.DRAFT)
        inv.transition_to(InvoiceStatus.READY_FOR_SUBMISSION)
        assert inv.status == InvoiceStatus.READY_FOR_SUBMISSION

    def test_ready_to_sending(self):
        inv = _make_invoice(InvoiceStatus.READY_FOR_SUBMISSION)
        inv.transition_to(InvoiceStatus.SENDING)
        assert inv.status == InvoiceStatus.SENDING

    def test_sending_to_accepted(self):
        inv = _make_invoice(InvoiceStatus.SENDING)
        inv.transition_to(InvoiceStatus.ACCEPTED)
        assert inv.status == InvoiceStatus.ACCEPTED

    def test_sending_to_rejected(self):
        inv = _make_invoice(InvoiceStatus.SENDING)
        inv.transition_to(InvoiceStatus.REJECTED)
        assert inv.status == InvoiceStatus.REJECTED

    def test_draft_to_sending_raises(self):
        inv = _make_invoice(InvoiceStatus.DRAFT)
        with pytest.raises(InvalidStatusTransitionError, match="draft → sending"):
            inv.transition_to(InvoiceStatus.SENDING)

    def test_accepted_to_anything_raises(self):
        inv = _make_invoice(InvoiceStatus.ACCEPTED)
        with pytest.raises(InvalidStatusTransitionError):
            inv.transition_to(InvoiceStatus.DRAFT)

    def test_rejected_to_anything_raises(self):
        inv = _make_invoice(InvoiceStatus.REJECTED)
        with pytest.raises(InvalidStatusTransitionError):
            inv.transition_to(InvoiceStatus.READY_FOR_SUBMISSION)

    def test_full_happy_path(self):
        """Pełny cykl: DRAFT → READY → SENDING → ACCEPTED."""
        inv = _make_invoice(InvoiceStatus.DRAFT)
        inv.transition_to(InvoiceStatus.READY_FOR_SUBMISSION)
        inv.transition_to(InvoiceStatus.SENDING)
        inv.transition_to(InvoiceStatus.ACCEPTED)
        assert inv.status == InvoiceStatus.ACCEPTED

    def test_full_rejection_path(self):
        """Pełny cykl: DRAFT → READY → SENDING → REJECTED."""
        inv = _make_invoice(InvoiceStatus.DRAFT)
        inv.transition_to(InvoiceStatus.READY_FOR_SUBMISSION)
        inv.transition_to(InvoiceStatus.SENDING)
        inv.transition_to(InvoiceStatus.REJECTED)
        assert inv.status == InvoiceStatus.REJECTED
