"""Testy modelu domenowego Invoice."""
from datetime import date, datetime, UTC
from decimal import Decimal
from uuid import uuid4

import pytest

from app.domain.enums import InvoiceStatus
from app.domain.exceptions import InvalidInvoiceError
from app.domain.models.invoice import Invoice, InvoiceItem


def _make_invoice(status: InvoiceStatus = InvoiceStatus.DRAFT) -> Invoice:
    now = datetime.now(UTC)
    return Invoice(
        id=uuid4(),
        status=status,
        issue_date=date(2026, 1, 15),
        sale_date=date(2026, 1, 15),
        currency="PLN",
        seller_snapshot={},
        buyer_snapshot={},
        items=[],
        total_net=Decimal("0"),
        total_vat=Decimal("0"),
        total_gross=Decimal("0"),
        created_at=now,
        updated_at=now,
    )


class TestInvoiceStatusTransitions:
    def test_draft_can_transition_to_ready(self):
        inv = _make_invoice(InvoiceStatus.DRAFT)
        assert inv.can_transition_to(InvoiceStatus.READY_FOR_SUBMISSION) is True

    def test_draft_cannot_transition_to_accepted(self):
        inv = _make_invoice(InvoiceStatus.DRAFT)
        assert inv.can_transition_to(InvoiceStatus.ACCEPTED) is False

    def test_ready_can_transition_to_sending(self):
        inv = _make_invoice(InvoiceStatus.READY_FOR_SUBMISSION)
        assert inv.can_transition_to(InvoiceStatus.SENDING) is True

    def test_ready_cannot_transition_to_accepted(self):
        inv = _make_invoice(InvoiceStatus.READY_FOR_SUBMISSION)
        assert inv.can_transition_to(InvoiceStatus.ACCEPTED) is False

    def test_sending_can_transition_to_accepted(self):
        inv = _make_invoice(InvoiceStatus.SENDING)
        assert inv.can_transition_to(InvoiceStatus.ACCEPTED) is True

    def test_sending_can_transition_to_rejected(self):
        inv = _make_invoice(InvoiceStatus.SENDING)
        assert inv.can_transition_to(InvoiceStatus.REJECTED) is True

    def test_accepted_is_terminal(self):
        inv = _make_invoice(InvoiceStatus.ACCEPTED)
        for s in InvoiceStatus:
            assert inv.can_transition_to(s) is False

    def test_rejected_is_terminal(self):
        inv = _make_invoice(InvoiceStatus.REJECTED)
        for s in InvoiceStatus:
            assert inv.can_transition_to(s) is False


class TestNormalizeItemsOrder:
    def test_empty_items(self):
        inv = _make_invoice()
        inv.normalize_items_order()
        assert inv.items == []

    def test_reindexes_items(self):
        inv = _make_invoice()
        inv.items = [
            InvoiceItem(
                name="B", quantity=Decimal("1"), unit="szt.",
                unit_price_net=Decimal("10"), vat_rate=Decimal("23"),
                net_total=Decimal("10"), vat_total=Decimal("2.30"),
                gross_total=Decimal("12.30"), sort_order=5,
            ),
            InvoiceItem(
                name="A", quantity=Decimal("1"), unit="szt.",
                unit_price_net=Decimal("20"), vat_rate=Decimal("23"),
                net_total=Decimal("20"), vat_total=Decimal("4.60"),
                gross_total=Decimal("24.60"), sort_order=2,
            ),
        ]
        inv.normalize_items_order()
        assert inv.items[0].name == "A"
        assert inv.items[0].sort_order == 1
        assert inv.items[1].name == "B"
        assert inv.items[1].sort_order == 2


class TestValidateItemsOrder:
    def test_valid_order(self):
        inv = _make_invoice()
        inv.items = [
            InvoiceItem(
                name="A", quantity=Decimal("1"), unit="szt.",
                unit_price_net=Decimal("10"), vat_rate=Decimal("23"),
                net_total=Decimal("10"), vat_total=Decimal("2.30"),
                gross_total=Decimal("12.30"), sort_order=1,
            ),
            InvoiceItem(
                name="B", quantity=Decimal("1"), unit="szt.",
                unit_price_net=Decimal("10"), vat_rate=Decimal("23"),
                net_total=Decimal("10"), vat_total=Decimal("2.30"),
                gross_total=Decimal("12.30"), sort_order=2,
            ),
        ]
        inv.validate_items_order()  # nie rzuca

    def test_duplicate_order_raises(self):
        inv = _make_invoice()
        inv.items = [
            InvoiceItem(
                name="A", quantity=Decimal("1"), unit="szt.",
                unit_price_net=Decimal("10"), vat_rate=Decimal("23"),
                net_total=Decimal("10"), vat_total=Decimal("2.30"),
                gross_total=Decimal("12.30"), sort_order=1,
            ),
            InvoiceItem(
                name="B", quantity=Decimal("1"), unit="szt.",
                unit_price_net=Decimal("10"), vat_rate=Decimal("23"),
                net_total=Decimal("10"), vat_total=Decimal("2.30"),
                gross_total=Decimal("12.30"), sort_order=1,
            ),
        ]
        with pytest.raises(InvalidInvoiceError):
            inv.validate_items_order()

    def test_gap_in_order_raises(self):
        inv = _make_invoice()
        inv.items = [
            InvoiceItem(
                name="A", quantity=Decimal("1"), unit="szt.",
                unit_price_net=Decimal("10"), vat_rate=Decimal("23"),
                net_total=Decimal("10"), vat_total=Decimal("2.30"),
                gross_total=Decimal("12.30"), sort_order=1,
            ),
            InvoiceItem(
                name="B", quantity=Decimal("1"), unit="szt.",
                unit_price_net=Decimal("10"), vat_rate=Decimal("23"),
                net_total=Decimal("10"), vat_total=Decimal("2.30"),
                gross_total=Decimal("12.30"), sort_order=3,
            ),
        ]
        with pytest.raises(InvalidInvoiceError):
            inv.validate_items_order()


class TestFA3NewFields:
    """Testy nowych pól domenowych dodanych na potrzeby FA(3)."""

    def test_delivery_date_defaults_to_none(self):
        inv = _make_invoice()
        assert inv.delivery_date is None

    def test_ksef_reference_number_defaults_to_none(self):
        inv = _make_invoice()
        assert inv.ksef_reference_number is None

    def test_delivery_date_can_be_set(self):
        now = datetime.now(UTC)
        inv = Invoice(
            id=uuid4(),
            status=InvoiceStatus.DRAFT,
            issue_date=date(2026, 4, 6),
            sale_date=date(2026, 4, 5),
            delivery_date=date(2026, 4, 4),
            currency="PLN",
            seller_snapshot={},
            buyer_snapshot={},
            items=[],
            total_net=Decimal("0"),
            total_vat=Decimal("0"),
            total_gross=Decimal("0"),
            created_at=now,
            updated_at=now,
        )
        assert inv.delivery_date == date(2026, 4, 4)

    def test_ksef_reference_number_can_be_set(self):
        inv = _make_invoice()
        inv.ksef_reference_number = "9999909999-20260406-ABC12345-01"
        assert inv.ksef_reference_number == "9999909999-20260406-ABC12345-01"

    def test_delivery_date_independent_of_sale_date(self):
        """delivery_date to osobne pole, niezalezne od sale_date."""
        now = datetime.now(UTC)
        inv = Invoice(
            id=uuid4(),
            status=InvoiceStatus.DRAFT,
            issue_date=date(2026, 4, 10),
            sale_date=date(2026, 4, 8),
            delivery_date=date(2026, 4, 7),
            currency="PLN",
            seller_snapshot={},
            buyer_snapshot={},
            items=[],
            total_net=Decimal("0"),
            total_vat=Decimal("0"),
            total_gross=Decimal("0"),
            created_at=now,
            updated_at=now,
        )
        assert inv.delivery_date != inv.sale_date
        assert inv.delivery_date == date(2026, 4, 7)
