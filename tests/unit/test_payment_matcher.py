"""Testy matching engine — jednostkowe (bez bazy)."""
from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

from app.services.payment_matcher import (
    AUTO_MATCH_THRESHOLD,
    MANUAL_REVIEW_THRESHOLD,
    InvoiceCandidate,
    PaymentMatcher,
    TransactionCandidate,
)


@pytest.fixture()
def matcher() -> PaymentMatcher:
    return PaymentMatcher()


def _tx(amount: Decimal = Decimal("1230.00"), title: str = "", cp_name: str = "") -> TransactionCandidate:
    return TransactionCandidate(
        transaction_id=uuid4(),
        amount=amount,
        title=title,
        counterparty_name=cp_name,
        counterparty_account=None,
    )


def _inv(
    invoice_number: str = "FV/1/04/2026",
    gross_amount: Decimal = Decimal("1230.00"),
    buyer_name: str = "ACME Sp. z o.o.",
    buyer_nip: str = "1234567890",
    seller_nip: str = "9876543210",
) -> InvoiceCandidate:
    return InvoiceCandidate(
        invoice_id=uuid4(),
        invoice_number=invoice_number,
        gross_amount=gross_amount,
        buyer_name=buyer_name,
        buyer_nip=buyer_nip,
        seller_nip=seller_nip,
    )


class TestMatcherScoring:
    def test_exact_number_and_amount_gives_auto_score(self, matcher: PaymentMatcher):
        # number(+40) + amount(+30) + name similarity(+10) = 80 ≥ AUTO_MATCH_THRESHOLD
        tx = _tx(Decimal("1230.00"), title="FV/1/04/2026 za uslugi", cp_name="ACME Sp. z o.o.")
        inv = _inv(invoice_number="FV/1/04/2026", gross_amount=Decimal("1230.00"), buyer_name="ACME Sp. z o.o.")
        candidates = matcher.find_candidates(tx, [inv])
        assert candidates, "Oczekiwano kandydata"
        assert candidates[0].score >= AUTO_MATCH_THRESHOLD

    def test_no_match_returns_empty(self, matcher: PaymentMatcher):
        tx = _tx(Decimal("500.00"), title="Zupełnie przypadkowy tytuł")
        inv = _inv(invoice_number="FV/99/12/2025", gross_amount=Decimal("9999.00"))
        candidates = matcher.find_candidates(tx, [inv])
        assert candidates == []

    def test_amount_only_not_sufficient_for_auto(self, matcher: PaymentMatcher):
        # Same amount but no number in title → max score = 30, below AUTO threshold
        tx = _tx(Decimal("1230.00"), title="Przelew ogólny")
        inv = _inv(invoice_number="FV/1/04/2026", gross_amount=Decimal("1230.00"))
        candidates = matcher.find_candidates(tx, [inv])
        # Should be in manual_review range (30 < 75), or absent
        if candidates:
            assert candidates[0].score < AUTO_MATCH_THRESHOLD

    def test_nip_in_title_boosts_score(self, matcher: PaymentMatcher):
        tx = _tx(Decimal("1230.00"), title="Zapłata FV/1/04/2026 NIP 1234567890")
        inv = _inv(invoice_number="FV/1/04/2026", gross_amount=Decimal("1230.00"), buyer_nip="1234567890")
        candidates = matcher.find_candidates(tx, [inv])
        assert candidates
        # exact number (40) + amount (30) + nip (20) = 90
        assert candidates[0].score >= 90

    def test_tolerance_within_2pct(self, matcher: PaymentMatcher):
        # amount differs by 1% → +15 pts
        tx = _tx(Decimal("1242.30"), title="FV/1/04/2026")  # 1% above
        inv = _inv(invoice_number="FV/1/04/2026", gross_amount=Decimal("1230.00"))
        candidates = matcher.find_candidates(tx, [inv])
        assert candidates
        # number (40) + tolerance (15) = 55 → manual_review range
        assert MANUAL_REVIEW_THRESHOLD <= candidates[0].score < AUTO_MATCH_THRESHOLD

    def test_best_auto_returns_none_when_insufficient(self, matcher: PaymentMatcher):
        tx = _tx(Decimal("1230.00"), title="Przelew bez sensu")
        inv = _inv(invoice_number="FV/1/04/2026", gross_amount=Decimal("1230.00"))
        best = matcher.best_auto(tx, [inv])
        assert best is None

    def test_best_auto_returns_result_when_above_threshold(self, matcher: PaymentMatcher):
        # number(+40) + amount(+30) + name(+10) = 80 ≥ 75
        tx = _tx(Decimal("1230.00"), title="FV/1/04/2026", cp_name="ACME Sp. z o.o.")
        inv = _inv(invoice_number="FV/1/04/2026", gross_amount=Decimal("1230.00"), buyer_name="ACME Sp. z o.o.")
        best = matcher.best_auto(tx, [inv])
        assert best is not None
        assert best.score >= AUTO_MATCH_THRESHOLD
        assert best.invoice_id == inv.invoice_id

    def test_multiple_candidates_sorted_by_score(self, matcher: PaymentMatcher):
        tx = _tx(Decimal("1230.00"), title="FV/1/04/2026 przelew")
        inv_high = _inv(invoice_number="FV/1/04/2026", gross_amount=Decimal("1230.00"))
        inv_low = _inv(invoice_number="FV/2/04/2026", gross_amount=Decimal("1230.00"))
        candidates = matcher.find_candidates(tx, [inv_high, inv_low])
        # inv_high should score higher due to exact number match
        if len(candidates) >= 2:
            assert candidates[0].score >= candidates[1].score
