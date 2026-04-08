from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from app.domain.enums import CorrectionType, InvoiceStatus, InvoiceType
from app.domain.exceptions import InvalidInvoiceError, InvalidStatusTransitionError

if TYPE_CHECKING:
    pass


_ALLOWED_TRANSITIONS: dict[InvoiceStatus, frozenset[InvoiceStatus]] = {
    InvoiceStatus.DRAFT: frozenset({InvoiceStatus.READY_FOR_SUBMISSION}),
    InvoiceStatus.READY_FOR_SUBMISSION: frozenset({InvoiceStatus.SENDING}),
    InvoiceStatus.SENDING: frozenset({InvoiceStatus.ACCEPTED, InvoiceStatus.REJECTED}),
    InvoiceStatus.ACCEPTED: frozenset(),
    InvoiceStatus.REJECTED: frozenset(),
}

_CORRECTION_TYPES = frozenset({InvoiceType.KOR, InvoiceType.KOR_ZAL, InvoiceType.KOR_ROZ})


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
    # kwota VAT przeliczona na PLN (wymagana przez FA(3) gdy currency != PLN)
    vat_amount_pln: Decimal | None = None


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
    correction_type: CorrectionType | None = None
    # Adnotacje FA(3)
    use_split_payment: bool = False      # P_16 — mechanizm podzielonej płatności
    self_billing: bool = False            # P_17 — samofakturowanie
    reverse_charge: bool = False          # P_18 — odwrotne obciążenie
    reverse_charge_art: bool = False      # P_18A — art. 17 ust.1 pkt 7 lub 8
    reverse_charge_flag: bool = False     # P_18B — procedura odwrotnego obciążenia
    cash_accounting_method: bool = False  # P_19 — metoda kasowa
    # Waluta obca — kurs wymiany do PLN
    exchange_rate: Decimal | None = None       # np. 4.2500
    exchange_rate_date: date | None = None     # data kursu NBP
    # Faktury zaliczkowe (ZAL/ROZ)
    advance_amount: Decimal | None = None                       # kwota zaliczki (ZAL)
    settled_advance_ids: list[UUID] = field(default_factory=list)  # UUID faktur ZAL (ROZ)
    # Kierunek dokumentu: 'sale' | 'purchase'
    direction: str = "sale"
    created_by: UUID | None = None

    # -----------------------
    # STATE MACHINE
    # -----------------------

    def can_transition_to(self, target: InvoiceStatus) -> bool:
        return target in _ALLOWED_TRANSITIONS.get(self.status, frozenset())

    def transition_to(self, target: InvoiceStatus) -> None:
        if not self.can_transition_to(target):
            raise InvalidStatusTransitionError(
                f"Niedozwolone przejście: {self.status.value} → {target.value}"
            )
        self.status = target

    # -----------------------
    # ITEMS INTEGRITY
    # -----------------------

    def normalize_items_order(self) -> None:
        if not self.items:
            return
        sorted_items = sorted(self.items, key=lambda item: item.sort_order)
        for idx, item in enumerate(sorted_items, start=1):
            item.sort_order = idx
        self.items = sorted_items

    def validate_items_order(self) -> None:
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
    # KSeF PRE-SEND VALIDATION (rozbite na typy)
    # -----------------------

    def validate_for_ksef(self) -> None:
        """Główny walidator.  Deleguje do wyspecjalizowanych metod."""
        if self.status != InvoiceStatus.READY_FOR_SUBMISSION:
            raise InvalidInvoiceError(
                f"Faktura musi mieć status '{InvoiceStatus.READY_FOR_SUBMISSION.value}' "
                f"przed wysyłką do KSeF (aktualnie: '{self.status.value}')."
            )
        self.validate_vat()
        if self.invoice_type in _CORRECTION_TYPES:
            self.validate_kor()
        if self.invoice_type in (InvoiceType.ZAL, InvoiceType.ROZ):
            self.validate_zal()

    def validate_vat(self) -> None:
        """Waliduje pola wymagane dla każdej faktury (NIP, sumy).

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

        # Suma VAT z pozycji musi zgadzać się z total_vat (tolerancja 1 gr/pozycję)
        if self.items:
            computed_vat = sum(item.vat_total for item in self.items)
            tolerance = Decimal("0.01") * max(1, len(self.items))
            if abs(computed_vat - self.total_vat) > tolerance:
                raise InvalidInvoiceError(
                    f"Suma VAT z pozycji ({computed_vat}) nie zgadza się z "
                    f"total_vat faktury ({self.total_vat}) — "
                    f"dozwolona tolerancja: {tolerance}."
                )

        if self.currency != "PLN":
            if self.exchange_rate is None:
                raise InvalidInvoiceError(
                    f"Faktura w walucie {self.currency} wymaga podania exchange_rate."
                )
            if self.exchange_rate <= Decimal("0"):
                raise InvalidInvoiceError(
                    f"exchange_rate musi być dodatnie, otrzymano: {self.exchange_rate}."
                )
            # Weryfikuj vat_amount_pln na pozycjach
            for item in self.items:
                if item.vat_amount_pln is None:
                    raise InvalidInvoiceError(
                        f"Pozycja '{item.name}' (sort_order={item.sort_order}) "
                        "wymaga vat_amount_pln gdy currency != PLN."
                    )

    def validate_kor(self) -> None:
        """Waliduje pola wymagane dla faktury korygującej.

        Sprawdza:
        - faktura bazowa ma status ACCEPTED
        - faktura bazowa ma numer KSeF
        - correction_reason podany
        - correction_type podany

        Raises:
            InvalidInvoiceError
        """
        if not self.correction_of_ksef_number and not self.correction_of_invoice_id:
            raise InvalidInvoiceError(
                "Faktura korygująca wymaga correction_of_ksef_number lub "
                "correction_of_invoice_id."
            )
        if not self.correction_reason:
            raise InvalidInvoiceError(
                "Faktura korygująca wymaga podania correction_reason."
            )
        if self.correction_type is None:
            raise InvalidInvoiceError(
                "Faktura korygująca wymaga podania correction_type (FULL lub PARTIAL)."
            )

    def validate_zal(self) -> None:
        """Waliduje pola wymagane dla faktury zaliczkowej (ZAL) i rozliczającej (ROZ).

        Sprawdza:
        - ZAL: advance_amount > 0 i <= total_gross
        - ROZ: settled_advance_ids niepusta;
               suma zaliczek <= total_gross faktury rozliczającej

        Raises:
            InvalidInvoiceError
        """
        if self.invoice_type == InvoiceType.ZAL:
            if self.advance_amount is None or self.advance_amount <= Decimal("0"):
                raise InvalidInvoiceError(
                    "Faktura zaliczkowa wymaga advance_amount > 0."
                )
            if self.advance_amount > self.total_gross:
                raise InvalidInvoiceError(
                    f"advance_amount ({self.advance_amount}) nie może być większy "
                    f"niż total_gross ({self.total_gross})."
                )

        elif self.invoice_type == InvoiceType.ROZ:
            if not self.settled_advance_ids:
                raise InvalidInvoiceError(
                    "Faktura rozliczająca wymaga podania settled_advance_ids "
                    "(listy UUID faktur ZAL)."
                )

    def validate_zal_with_advances(self, advance_invoices: list["Invoice"]) -> None:
        """Waliduje fakturę ROZ względem rzeczywistych faktur zaliczkowych.

        Sprawdza:
        - Wszystkie advance_invoices są typu ZAL.
        - Suma advance_amount faktur ZAL <= total_gross faktury ROZ.

        Wywołaj ze serwisu po pobraniu Invoice dla każdego settled_advance_id.

        Raises:
            InvalidInvoiceError
        """
        if self.invoice_type != InvoiceType.ROZ:
            return
        for adv in advance_invoices:
            if adv.invoice_type != InvoiceType.ZAL:
                raise InvalidInvoiceError(
                    f"Faktura {adv.id} nie jest zaliczkową (ZAL) — "
                    f"typ: {adv.invoice_type.value}."
                )
        total_advances = sum(
            (adv.advance_amount or Decimal("0")) for adv in advance_invoices
        )
        if total_advances > self.total_gross:
            raise InvalidInvoiceError(
                f"Suma zaliczek ({total_advances}) przekracza "
                f"total_gross faktury rozliczającej ({self.total_gross})."
            )

    # -----------------------
    # AGREGACJA i PORÓWNANIA
    # -----------------------

    def aggregate_vat_totals(
        self,
    ) -> dict[Decimal, tuple[Decimal, Decimal, Decimal | None]]:
        """Zwraca słownik {stawka_vat: (net_total, vat_total, vat_total_pln)}.

        ``vat_total_pln`` to None, gdy żadna z pozycji nie ma ustawionego
        ``vat_amount_pln`` dla danej stawki (waluta PLN lub brakujące dane).
        Używane przez mapper KSeF do emisji P_13_x / P_14_x / P_14_xW.
        """
        net: dict[Decimal, Decimal] = defaultdict(Decimal)
        vat: dict[Decimal, Decimal] = defaultdict(Decimal)
        vat_pln: dict[Decimal, Decimal] = defaultdict(Decimal)
        has_pln: set[Decimal] = set()

        for item in self.items:
            rate = item.vat_rate
            net[rate] += item.net_total
            vat[rate] += item.vat_total
            if item.vat_amount_pln is not None:
                vat_pln[rate] += item.vat_amount_pln
                has_pln.add(rate)

        return {
            rate: (net[rate], vat[rate], vat_pln[rate] if rate in has_pln else None)
            for rate in net
        }

    def validate_exchange_rate_against_nbp(
        self,
        official_rate: Decimal,
        tolerance: Decimal = Decimal("0.01"),
    ) -> None:
        """Sprawdza, czy exchange_rate mieści się w tolerancji kursu NBP.

        Args:
            official_rate: kurs środkowy NBP pobierany z zewnątrz.
            tolerance: maksymalna dozwolona różnica (domyślnie 1 grosz).

        Raises:
            InvalidInvoiceError: gdy różnica przekracza ``tolerance``.
        """
        if self.exchange_rate is None:
            return
        diff = abs(self.exchange_rate - official_rate)
        if diff > tolerance:
            raise InvalidInvoiceError(
                f"Kurs {self.currency} w fakturze ({self.exchange_rate}) "
                f"różni się od kursu NBP ({official_rate}) o {diff} — "
                f"dozwolona tolerancja: {tolerance}."
            )


_NIP_WEIGHTS = (6, 5, 7, 2, 3, 4, 5, 6, 7)


def _is_valid_nip(nip: str) -> bool:
    """Zwraca True jeśli NIP ma dokładnie 10 cyfr i poprawną sumę kontrolną.

    Algorytm sumy kontrolnej NIP:
    - Waż pierwsze 9 cyfr przez wagi [6, 5, 7, 2, 3, 4, 5, 6, 7].
    - Suma ważona mod 11 == cyfra 10 (ostatnia).
    - Wynik mod 11 == 10 jest zawsze błędny (cyfra nie może być 10).
    """
    if not nip:
        return False
    stripped = nip.strip().replace("-", "").replace(" ", "")
    if not stripped.isdigit() or len(stripped) != 10:
        return False
    checksum = sum(int(stripped[i]) * _NIP_WEIGHTS[i] for i in range(9)) % 11
    return checksum == int(stripped[9])
