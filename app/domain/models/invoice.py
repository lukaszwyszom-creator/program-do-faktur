from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from app.domain.enums import InvoiceStatus, InvoiceType
from app.domain.exceptions import InvalidInvoiceError, InvalidStatusTransitionError


_ALLOWED_TRANSITIONS: dict[InvoiceStatus, frozenset[InvoiceStatus]] = {
    InvoiceStatus.DRAFT: frozenset({InvoiceStatus.READY_FOR_SUBMISSION}),
    InvoiceStatus.READY_FOR_SUBMISSION: frozenset({InvoiceStatus.SENDING}),
    InvoiceStatus.SENDING: frozenset({InvoiceStatus.ACCEPTED, InvoiceStatus.REJECTED}),
    InvoiceStatus.ACCEPTED: frozenset(),
    InvoiceStatus.REJECTED: frozenset(),
}


@dataclass(slots=True)
class InvoiceItem:
    name: str
    quantity: Decimal
    unit: str
    unit_price_net: Decimal
    vat_rate: Decimal
    net_total: Decimal
    vat_total: Decimal
    gross_total: Decimal
    sort_order: int = 0
    id: UUID | None = None


@dataclass(slots=True)
class Invoice:
    id: UUID
    status: InvoiceStatus
    issue_date: date
    sale_date: date
    currency: str
    seller_snapshot: dict
    buyer_snapshot: dict
    items: list[InvoiceItem]
    total_net: Decimal
    total_vat: Decimal
    total_gross: Decimal
    created_at: datetime
    updated_at: datetime
    number_local: str | None = None
    delivery_date: date | None = None
    ksef_reference_number: str | None = None
    payment_status: str = "unpaid"
    invoice_type: InvoiceType = InvoiceType.VAT
    correction_of_invoice_id: UUID | None = None
    correction_of_ksef_number: str | None = None
    correction_reason: str | None = None
    created_by: UUID | None = None

    # -----------------------
    # STATE MACHINE
    # -----------------------

    def can_transition_to(self, target: InvoiceStatus) -> bool:
        return target in _ALLOWED_TRANSITIONS.get(self.status, frozenset())

    def transition_to(self, target: InvoiceStatus) -> None:
        """Waliduje i wykonuje przejście statusu."""
        if not self.can_transition_to(target):
            raise InvalidStatusTransitionError(
                f"Niedozwolone przejście: {self.status.value} \u2192 {target.value}"
            )
        self.status = target

    # -----------------------
    # ITEMS INTEGRITY
    # -----------------------

    def normalize_items_order(self) -> None:
        """
        Naprawia sort_order:
        - sortuje stabilnie
        - usuwa luki
        - usuwa duplikaty poprzez reindex
        """
        if not self.items:
            return
        sorted_items = sorted(self.items, key=lambda item: item.sort_order)
        for idx, item in enumerate(sorted_items, start=1):
            item.sort_order = idx
        self.items = sorted_items

    def validate_items_order(self) -> None:
        """Waliduje że sort_order jest unikalny i ciągły od 1."""
        if not self.items:
            return
        orders = [item.sort_order for item in self.items]
        if len(orders) != len(set(orders)):
            raise InvalidInvoiceError("Duplikaty sort_order w pozycjach faktury.")
        expected = set(range(1, len(orders) + 1))
        if set(orders) != expected:
            raise InvalidInvoiceError(
                f"sort_order musi być ciągły od 1 do {len(orders)}, "
                f"otrzymano: {sorted(orders)}"
            )

    # -----------------------
    # KSeF PRE-SEND VALIDATION
    # -----------------------

    def validate_for_ksef(self) -> None:
        """Weryfikuje gotowość faktury do wysyłki do KSeF.

        Sprawdza:
        - NIP sprzedawcy i nabywcy (10 cyfr, bez separatorów)
        - Spójność sum (total_net + total_vat == total_gross, tolerancja 0.01)
        - Pola wymagane dla korekty
        Raises:
            InvalidInvoiceError
        """
        seller_nip = (self.seller_snapshot or {}).get("nip", "")
        if not _is_valid_nip(seller_nip):
            raise InvalidInvoiceError(
                f"NIP sprzedawcy jest nieprawidłowy: '{seller_nip}'. "
                "Wymagane dokładnie 10 cyfr bez separatorów."
            )

        buyer_nip = (self.buyer_snapshot or {}).get("nip")
        if buyer_nip is not None and not _is_valid_nip(buyer_nip):
            raise InvalidInvoiceError(
                f"NIP nabywcy jest nieprawidłowy: '{buyer_nip}'. "
                "Wymagane dokładnie 10 cyfr bez separatorów."
            )

        expected_gross = self.total_net + self.total_vat
        if abs(expected_gross - self.total_gross) > Decimal("0.01"):
            raise InvalidInvoiceError(
                f"Niespójność sum: total_net ({self.total_net}) + "
                f"total_vat ({self.total_vat}) = {expected_gross}, "
                f"ale total_gross = {self.total_gross}."
            )

        if self.invoice_type in (InvoiceType.KOR, InvoiceType.KOR_ZAL, InvoiceType.KOR_ROZ):
            if not self.correction_of_ksef_number and not self.correction_of_invoice_id:
                raise InvalidInvoiceError(
                    "Faktura korygująca wymaga correction_of_ksef_number lub "
                    "correction_of_invoice_id."
                )


def _is_valid_nip(nip: str) -> bool:
    """Zwraca True jeśli NIP to dokładnie 10 cyfr bez separatorów."""
    if not nip:
        return False
    stripped = nip.strip().replace("-", "").replace(" ", "")
    return stripped.isdigit() and len(stripped) == 10
