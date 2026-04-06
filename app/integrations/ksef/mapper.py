from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal

from lxml import etree

from app.domain.models.invoice import Invoice
from app.integrations.ksef.exceptions import KSeFMappingError

logger = logging.getLogger(__name__)

_NS_FA = "http://crd.gov.pl/wzor/2023/06/29/9781/"
_NS_XSI = "http://www.w3.org/2001/XMLSchema-instance"
_NS_MAP = {"fa": _NS_FA, "xsi": _NS_XSI}

# Mapowanie stawki VAT (procent jako Decimal) na parę pól FA(3): (P_13_x, P_14_x)
# P_14_x = None oznacza brak pola VAT dla stawki zwolnionej/np.
_VAT_RATE_FIELDS: dict[str, tuple[str, str | None]] = {
    "23": ("P_13_1", "P_14_1"),
    "8":  ("P_13_2", "P_14_2"),
    "5":  ("P_13_3", "P_14_3"),
    "0":  ("P_13_4", "P_14_4"),
    "zw": ("P_13_6", None),
    "np": ("P_13_7", None),
}


def _el(parent: etree._Element, tag: str, text: str | None = None) -> etree._Element:
    el = etree.SubElement(parent, f"{{{_NS_FA}}}{tag}")
    if text is not None:
        el.text = str(text)
    return el


def _fmt(value) -> str:
    """Formatuje wartość liczbową do 2 miejsc po przecinku."""
    return f"{Decimal(str(value)):.2f}"


def _rate_key(vat_rate: Decimal) -> str:
    """Zwraca klucz stawki VAT dla tabeli _VAT_RATE_FIELDS."""
    normalized = vat_rate.normalize()
    if normalized == Decimal("0"):
        return "0"
    # zaokrąglamy do int jeśli całkowita
    if normalized == normalized.to_integral_value():
        return str(int(normalized))
    return str(normalized)


class KSeFMapper:
    """Transformacja modelu wewnętrznego faktury do formatu KSeF FA(3)."""

    @staticmethod
    def invoice_to_xml(invoice: Invoice) -> bytes:
        KSeFMapper._validate_invoice(invoice)
        root = etree.Element(f"{{{_NS_FA}}}Faktura", nsmap=_NS_MAP)

        # — Nagłówek
        hdr = _el(root, "Naglowek")
        _el(hdr, "KodFormularza", "FA")
        _el(hdr, "WariantFormularza", "3")
        _el(hdr, "DataWytworzeniaFa",
            datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        _el(hdr, "SystemInfo", "KSeF-Backend/0.1")

        # — Podmiot1 (Sprzedawca)
        KSeFMapper._build_party(root, "Podmiot1", "Sprzedawca",
                                invoice.seller_snapshot or {})

        # — Podmiot2 (Nabywca)
        KSeFMapper._build_party(root, "Podmiot2", "Nabywca",
                                invoice.buyer_snapshot or {})

        # — Fa (główka dokumentu)
        fa = _el(root, "Fa")
        _el(fa, "KodWaluty", invoice.currency or "PLN")
        _el(fa, "P_1", invoice.issue_date.isoformat())
        _el(fa, "P_1M", invoice.sale_date.isoformat())

        # P_6: data dostawy/wykonania usługi (FA(3))
        # Emituj tylko jeśli różna od daty wystawienia lub jawnie podana
        p6_date = invoice.delivery_date or invoice.sale_date
        if p6_date != invoice.issue_date:
            _el(fa, "P_6", p6_date.isoformat())

        if invoice.number_local is not None:
            _el(fa, "P_2", invoice.number_local)

        # Sumy per stawka VAT
        KSeFMapper._build_vat_totals(fa, invoice)

        _el(fa, "P_15", _fmt(invoice.total_gross))
        _el(fa, "RodzajFaktury", "VAT")

        # Pozycje
        for item in invoice.items:
            row = _el(fa, "FaWiersz")
            _el(row, "NrWierszaFa", str(item.sort_order))
            _el(row, "P_7", item.name)
            _el(row, "P_8A", item.unit)
            _el(row, "P_8B", _fmt(item.quantity))
            _el(row, "P_9A", _fmt(item.unit_price_net))
            _el(row, "P_11", _fmt(item.net_total))
            _el(row, "P_12", _fmt(item.vat_rate))

        return etree.tostring(root, encoding="UTF-8", xml_declaration=True)

    # ------------------------------------------------------------------
    # Prywatne helpery
    # ------------------------------------------------------------------

    @staticmethod
    def _build_party(root: etree._Element, wrapper_tag: str,
                     party_tag: str, snapshot: dict) -> None:
        wrapper = _el(root, wrapper_tag)
        party = _el(wrapper, party_tag)
        if snapshot.get("nip"):
            _el(party, "NIP", snapshot["nip"])
        if snapshot.get("name"):
            _el(party, "Nazwa", snapshot["name"])
        adres = _el(party, "Adres")
        if snapshot.get("street") or snapshot.get("building_no"):
            l1 = " ".join(filter(None, [snapshot.get("street"),
                                        snapshot.get("building_no")]))
            _el(adres, "AdresL1", l1)
        if snapshot.get("apartment_no"):
            _el(adres, "AdresL2", f"m. {snapshot['apartment_no']}")
        if snapshot.get("postal_code"):
            _el(adres, "KodPocztowy", snapshot["postal_code"])
        if snapshot.get("city"):
            _el(adres, "Miejscowosc", snapshot["city"])
        _el(adres, "KodKraju", snapshot.get("country") or "PL")

    @staticmethod
    def _build_vat_totals(fa: etree._Element, invoice: Invoice) -> None:
        """Emituje pola P_13_x / P_14_x pogrupowane wg stawki VAT.

        Jeśli faktura ma tylko jedną stawkę i sumy domenowe są spójne,
        używamy sum domenowych (total_net / total_vat).
        Jeśli stawek jest więcej, sumujemy pozycje per stawka.
        Fallback: używamy total_net / total_vat na P_13_1 / P_14_1 (23%).
        """
        items = invoice.items
        if not items:
            # Brak pozycji — emituj sumy domenowe na domyślnej stawce 23%
            _el(fa, "P_13_1", _fmt(invoice.total_net))
            _el(fa, "P_14_1", _fmt(invoice.total_vat))
            return

        # Grupowanie sum per stawka
        net_by_rate: dict[str, Decimal] = defaultdict(Decimal)
        vat_by_rate: dict[str, Decimal] = defaultdict(Decimal)
        for item in items:
            key = _rate_key(item.vat_rate)
            net_by_rate[key] += item.net_total
            vat_by_rate[key] += item.vat_total

        for key in sorted(net_by_rate):
            fields = _VAT_RATE_FIELDS.get(key)
            if fields is None:
                # Nieznana stawka — emituj na P_13_1/P_14_1 z ostrzeżeniem
                logger.warning("Nieznana stawka VAT: %s — mapowana na P_13_1/P_14_1", key)
                p13, p14 = "P_13_1", "P_14_1"
            else:
                p13, p14 = fields

            _el(fa, p13, _fmt(net_by_rate[key]))
            if p14 is not None:
                _el(fa, p14, _fmt(vat_by_rate[key]))

    @staticmethod
    def _validate_invoice(invoice: Invoice) -> None:
        """Weryfikuje kontrakt adaptera KSeF przed budową XML.

        Raises:
            KSeFMappingError: gdy dokument byłby odrzucony przez KSeF
                              z powodu brakujących danych krytycznych.
        """
        seller = invoice.seller_snapshot or {}
        if not seller.get("nip"):
            raise KSeFMappingError(
                "Brak NIP sprzedawcy — pole wymagane przez KSeF (Podmiot1/NIP)"
            )
        if not invoice.items:
            raise KSeFMappingError(
                "Faktura nie zawiera pozycji — wymagany co najmniej jeden FaWiersz"
            )

    @staticmethod
    def validate_xml(xml_bytes: bytes) -> bool:
        if not xml_bytes:
            return False
        try:
            etree.fromstring(xml_bytes)
            return True
        except etree.XMLSyntaxError:
            return False

