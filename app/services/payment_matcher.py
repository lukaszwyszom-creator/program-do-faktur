"""Silnik scoringowy dopasowania przelewów do faktur.

Scoring (MAX = 100 pkt):
  +40 – dokładny numer faktury w tytule przelewu
  +20 – częściowy numer (np. '123/2024' gdy pełny to 'FV/123/2024')
  +30 – kwota przelewu == kwota brutto faktury
  +15 – kwota w tolerancji ±2%
  +20 – NIP kontrahenta w tytule lub nazwie kontrahenta przelewu
  +10 – podobieństwo nazwy kontrahenta (≥80%)

Progi:
  ≥75 → AUTO (alokacja automatyczna)
  40–74 → MANUAL_REVIEW (wymaga zatwierdzenia)
  <40  → UNMATCHED (brak dopasowania)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal

AUTO_MATCH_THRESHOLD = 75
MANUAL_REVIEW_THRESHOLD = 40


@dataclass(slots=True)
class CandidateResult:
    invoice_id: "UUID"
    score: int
    reasons: list[str] = field(default_factory=list)


class PaymentMatcher:
    """Dopasowuje transakcję bankową do listy faktur (domenowych DTO)."""

    def find_candidates(
        self,
        transaction: "_TransactionCandidate",
        invoices: list["_InvoiceCandidate"],
    ) -> list[CandidateResult]:
        results: list[CandidateResult] = []
        for inv in invoices:
            result = self._score(transaction, inv)
            if result.score >= MANUAL_REVIEW_THRESHOLD:
                results.append(result)
        results.sort(key=lambda r: r.score, reverse=True)
        return results

    def best_auto(
        self,
        transaction: "_TransactionCandidate",
        invoices: list["_InvoiceCandidate"],
    ) -> CandidateResult | None:
        candidates = self.find_candidates(transaction, invoices)
        for c in candidates:
            if c.score >= AUTO_MATCH_THRESHOLD:
                return c
        return None

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _score(
        self,
        tx: "_TransactionCandidate",
        inv: "_InvoiceCandidate",
    ) -> CandidateResult:
        score = 0
        reasons: list[str] = []
        title = (tx.title or "").upper()
        cp_name = (tx.counterparty_name or "").upper()

        # — numer faktury w tytule —
        inv_number_clean = re.sub(r"[$\s]", "", inv.invoice_number.upper())
        if inv_number_clean and inv_number_clean in title.replace(" ", ""):
            score += 40
            reasons.append(f"Dokładny numer faktury w tytule (+40)")
        elif inv_number_clean:
            # liczba z numeru (np. "123" z "FV/123/2024")
            digits = re.search(r"\d{2,}", inv_number_clean)
            if digits and digits.group() in title:
                score += 20
                reasons.append(f"Częściowy numer faktury w tytule (+20)")

        # — kwota —
        inv_amount = inv.gross_amount
        tx_amount = tx.amount
        if tx_amount == inv_amount:
            score += 30
            reasons.append(f"Kwota identyczna: {tx_amount} PLN (+30)")
        elif inv_amount != 0 and abs(tx_amount - inv_amount) / inv_amount <= Decimal("0.02"):
            score += 15
            reasons.append(f"Kwota w tolerancji ±2% (+15)")

        # — NIP kontrahenta —
        buyer_nip = inv.buyer_nip or ""
        seller_nip = inv.seller_nip or ""
        for nip in (buyer_nip, seller_nip):
            nip_clean = re.sub(r"[^0-9]", "", nip)
            if nip_clean and len(nip_clean) >= 8 and nip_clean in title.replace("-", "").replace(" ", ""):
                score += 20
                reasons.append(f"NIP {nip_clean} w tytule przelewu (+20)")
                break

        # — nazwa kontrahenta —
        inv_name_upper = (inv.buyer_name or "").upper()
        if inv_name_upper and cp_name:
            sim = _name_similarity(inv_name_upper, cp_name)
            if sim >= 0.80:
                score += 10
                reasons.append(f"Podobieństwo nazwy kontrahenta {sim:.0%} (+10)")

        return CandidateResult(invoice_id=inv.invoice_id, score=min(score, 100), reasons=reasons)


# ---------------------------------------------------------------------------
# Lightweight DTO – żeby matcher nie zależał od ORM / schematu Pydantic
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class TransactionCandidate:
    transaction_id: "UUID"
    amount: Decimal
    title: str | None
    counterparty_name: str | None
    counterparty_account: str | None


@dataclass(slots=True)
class InvoiceCandidate:
    invoice_id: "UUID"
    invoice_number: str
    gross_amount: Decimal
    buyer_name: str | None
    buyer_nip: str | None
    seller_nip: str | None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _name_similarity(a: str, b: str) -> float:
    """Prosta metryka podobieństwa (Jaccard słów)."""
    words_a = set(re.split(r"\W+", a))
    words_b = set(re.split(r"\W+", b))
    words_a.discard("")
    words_b.discard("")
    if not words_a or not words_b:
        return 0.0
    intersection = len(words_a & words_b)
    union = len(words_a | words_b)
    return intersection / union


# make UUID importable without circular dep at module level
from uuid import UUID  # noqa: E402
_TransactionCandidate = TransactionCandidate
_InvoiceCandidate = InvoiceCandidate
