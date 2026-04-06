from __future__ import annotations

import hashlib
import logging
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from lxml import etree

from app.domain.enums import InvoiceType
from app.domain.models.invoice import Invoice, _is_valid_nip
from app.integrations.ksef.exceptions import KSeFMappingError

logger = logging.getLogger(__name__)

_NS_FA = "http://crd.gov.pl/wzor/2023/06/29/9781/"
_NS_XSI = "http://www.w3.org/2001/XMLSchema-instance"
_NS_MAP = {"fa": _NS_FA, "xsi": _NS_XSI}

# Ścieżka do pliku XSD FA(3) — opcjonalny, umieszczony obok mappera
_XSD_PATH = Path(__file__).with_name("fa3.xsd")

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

# Mapowanie stawki VAT na pole P_14_xW (kwota VAT w PLN przy kursie NBP)
_VAT_RATE_FIELDS_PLN: dict[str, str] = {
    "23": "P_14_1W",
    "8":  "P_14_2W",
    "5":  "P_14_3W",
    "0":  "P_14_4W",
}

_SCHEMA_VERSION = "3"
_SCHEMA_CODE = "FA"


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
    if normalized == normalized.to_integral_value():
        return str(int(normalized))
    return str(normalized)


def _strip_nip_prefix(nip: str) -> str:
    """Zwraca NIP bez dwuliterowego prefiksu kraju (np. 'PL1234567890' → '1234567890')."""
    if nip and len(nip) > 2 and nip[:2].isalpha():
        return nip[2:]
    return nip


def _normalize_nip(raw_nip: str) -> str:
    """Zwraca NIP jako 10 cyfr — usuwa kreski, spacje i opcjonalny prefix kraju."""
    stripped = _strip_nip_prefix(raw_nip.strip())
    return stripped.replace("-", "").replace(" ", "")


class FA3Mapper:
    """Transformacja modelu wewnętrznego faktury do formatu KSeF FA(3).

    Nazwa klasy jawnie wersjonowana (FA3Mapper), aby umożliwić przyszłe
    FA4Mapper itp. bez zmiany call-sites korzystających z KSeFMapper.
    """

    SCHEMA_VERSION = _SCHEMA_VERSION

    # ------------------------------------------------------------------
    # PUBLIC API
    # ------------------------------------------------------------------

    @staticmethod
    def invoice_to_xml(invoice: Invoice) -> bytes:
        FA3Mapper._validate_invoice(invoice)
        root = etree.Element(f"{{{_NS_FA}}}Faktura", nsmap=_NS_MAP)

        # — Nagłówek
        hdr = _el(root, "Naglowek")
        _el(hdr, "KodFormularza", _SCHEMA_CODE)
        _el(hdr, "WariantFormularza", _SCHEMA_VERSION)
        _el(hdr, "DataWytworzeniaFa",
            datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        _el(hdr, "SystemInfo", "KSeF-Backend/0.1")

        # — Podmiot1 (Sprzedawca)
        FA3Mapper._build_party(root, "Podmiot1", "Sprzedawca",
                               invoice.seller_snapshot or {})

        # — Podmiot2 (Nabywca)
        FA3Mapper._build_party(root, "Podmiot2", "Nabywca",
                               invoice.buyer_snapshot or {})

        # — Fa (główka dokumentu)
        fa = _el(root, "Fa")
        _el(fa, "KodWaluty", invoice.currency or "PLN")
        _el(fa, "P_1", invoice.issue_date.isoformat())
        _el(fa, "P_1M", invoice.sale_date.isoformat())

        # P_6: data dostawy/wykonania usługi
        p6_date = invoice.delivery_date or invoice.sale_date
        if p6_date != invoice.issue_date:
            _el(fa, "P_6", p6_date.isoformat())

        if invoice.number_local is not None:
            _el(fa, "P_2", invoice.number_local)

        # Kurs wymiany dla walut obcych (FA(3): KursWaluty i DataKursuWaluty)
        if invoice.currency != "PLN" and invoice.exchange_rate is not None:
            _el(fa, "KursWaluty", _fmt(invoice.exchange_rate))
            if invoice.exchange_rate_date is not None:
                _el(fa, "DataKursuWaluty", invoice.exchange_rate_date.isoformat())

        # Sumy per stawka VAT
        FA3Mapper._build_vat_totals(fa, invoice)

        _el(fa, "P_15", _fmt(invoice.total_gross))
        _el(fa, "RodzajFaktury", invoice.invoice_type.value)

        # — Adnotacje (wymagane w FA(3), flagi z modelu Invoice)
        FA3Mapper._build_adnotacje(fa, invoice)

        # — FaKorygowana (dla korekty)
        if invoice.invoice_type in (InvoiceType.KOR, InvoiceType.KOR_ZAL, InvoiceType.KOR_ROZ):
            FA3Mapper._build_fa_korygowana(fa, invoice)

        # — Pozycje
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

    @staticmethod
    def xml_content_hash(xml_bytes: bytes) -> str:
        """Zwraca SHA-256 kanonicznego (C14N) reprezentacji XML.

        Użyj jako idempotency_key transmisji zamiast ``uuid4()``.
        C14N eliminuje różnice w kolejności atrybutów, whitespace itp.
        """
        import io

        if not xml_bytes:
            raise KSeFMappingError("Pusty XML — nie można wyliczyć hasha.")
        try:
            root = etree.fromstring(xml_bytes)
        except etree.XMLSyntaxError as exc:
            raise KSeFMappingError(f"XML nie jest poprawny składniowo: {exc}") from exc

        buf = io.BytesIO()
        root.getroottree().write_c14n(buf)
        return hashlib.sha256(buf.getvalue()).hexdigest()

    @staticmethod
    def validate_xml(xml_bytes: bytes) -> bool:
        """Waliduje well-formedness XML.

        Jeśli plik XSD FA(3) jest dostępny pod _XSD_PATH, wykonuje
        walidację względem schematu i zgłasza KSeFMappingError przy niezgodności.
        Bez XSD — sprawdza tylko well-formed.
        """
        if not xml_bytes:
            return False
        try:
            root = etree.fromstring(xml_bytes)
        except etree.XMLSyntaxError as exc:
            raise KSeFMappingError(f"XML nie jest poprawny składniowo: {exc}") from exc

        if _XSD_PATH.exists():
            FA3Mapper._validate_against_xsd(root)

        return True

    @staticmethod
    def validate_xml_against_xsd(xml_bytes: bytes) -> None:
        """Waliduje XML względem XSD FA(3). Rzuca KSeFMappingError przy niezgodności.

        Wymaga pliku fa3.xsd w app/integrations/ksef/.
        """
        if not xml_bytes:
            raise KSeFMappingError("Pusty XML — brak danych do walidacji XSD.")
        try:
            root = etree.fromstring(xml_bytes)
        except etree.XMLSyntaxError as exc:
            raise KSeFMappingError(f"XML nie jest poprawny składniowo: {exc}") from exc
        FA3Mapper._validate_against_xsd(root)

    # ------------------------------------------------------------------
    # Prywatne helpery
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_against_xsd(root: etree._Element) -> None:
        if not _XSD_PATH.exists():
            raise KSeFMappingError(
                f"Plik XSD FA(3) nie istnieje: {_XSD_PATH}. "
                "Umieść fa3.xsd w app/integrations/ksef/."
            )
        try:
            xsd_doc = etree.parse(str(_XSD_PATH))
            schema = etree.XMLSchema(xsd_doc)
        except etree.XMLSchemaParseError as exc:
            raise KSeFMappingError(f"Błąd wczytywania XSD: {exc}") from exc

        if not schema.validate(root):
            errors = "; ".join(str(e) for e in schema.error_log)
            raise KSeFMappingError(f"Dokument niezgodny z XSD FA(3): {errors}")

    @staticmethod
    def _build_party(root: etree._Element, wrapper_tag: str,
                     party_tag: str, snapshot: dict) -> None:
        wrapper = _el(root, wrapper_tag)
        party = _el(wrapper, party_tag)

        raw_nip = snapshot.get("nip") or ""
        country_code = snapshot.get("country") or "PL"
        if raw_nip:
            if raw_nip.strip()[:2].isalpha():
                country_code = raw_nip.strip()[:2].upper()
            pure_nip = _normalize_nip(raw_nip)
            _el(party, "NIP", pure_nip)

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
        _el(adres, "KodKraju", country_code)

    @staticmethod
    def _build_vat_totals(fa: etree._Element, invoice: Invoice) -> None:
        """Emituje pola P_13_x / P_14_x (i P_14_xW dla walut obcych)."""
        items = invoice.items
        is_foreign = invoice.currency != "PLN"

        if not items:
            _el(fa, "P_13_1", _fmt(invoice.total_net))
            _el(fa, "P_14_1", _fmt(invoice.total_vat))
            return

        net_by_rate: dict[str, Decimal] = defaultdict(Decimal)
        vat_by_rate: dict[str, Decimal] = defaultdict(Decimal)
        vat_pln_by_rate: dict[str, Decimal] = defaultdict(Decimal)

        for item in items:
            key = _rate_key(item.vat_rate)
            net_by_rate[key] += item.net_total
            vat_by_rate[key] += item.vat_total
            if is_foreign and item.vat_amount_pln is not None:
                vat_pln_by_rate[key] += item.vat_amount_pln

        for key in sorted(net_by_rate):
            fields = _VAT_RATE_FIELDS.get(key)
            if fields is None:
                logger.warning("Nieznana stawka VAT: %s — mapowana na P_13_1/P_14_1", key)
                p13, p14 = "P_13_1", "P_14_1"
            else:
                p13, p14 = fields

            _el(fa, p13, _fmt(net_by_rate[key]))
            if p14 is not None:
                _el(fa, p14, _fmt(vat_by_rate[key]))
                # P_14_xW — kwota VAT w PLN (wymagana gdy currency != PLN)
                if is_foreign:
                    p14w = _VAT_RATE_FIELDS_PLN.get(key)
                    if p14w and vat_pln_by_rate.get(key):
                        _el(fa, p14w, _fmt(vat_pln_by_rate[key]))

    @staticmethod
    def _build_adnotacje(fa: etree._Element, invoice: Invoice) -> None:
        """Emituje sekcję Adnotacje z dynamicznych flag Invoice."""
        adnotacje = _el(fa, "Adnotacje")
        _el(adnotacje, "P_16", "1" if invoice.use_split_payment else "0")
        _el(adnotacje, "P_17", "1" if invoice.self_billing else "0")
        _el(adnotacje, "P_18", "1" if invoice.reverse_charge else "0")
        _el(adnotacje, "P_18A", "1" if invoice.reverse_charge_art else "0")
        _el(adnotacje, "P_18B", "1" if invoice.reverse_charge_flag else "0")
        if invoice.cash_accounting_method:
            _el(adnotacje, "P_19", "1")

    @staticmethod
    def _build_fa_korygowana(fa: etree._Element, invoice: Invoice) -> None:
        """Emituje element FaKorygowana dla faktur korygujących."""
        fa_kor = _el(fa, "FaKorygowana")
        if invoice.correction_of_ksef_number:
            _el(fa_kor, "NrKSeFFaKorygowanej", invoice.correction_of_ksef_number)
        if invoice.correction_reason:
            _el(fa_kor, "PrzyczynaKorekty", invoice.correction_reason)

    @staticmethod
    def _validate_invoice(invoice: Invoice) -> None:
        """Weryfikuje kontrakt adaptera KSeF przed budową XML."""
        seller = invoice.seller_snapshot or {}
        raw_nip = seller.get("nip") or ""
        pure_nip = _normalize_nip(raw_nip)
        if not _is_valid_nip(pure_nip):
            raise KSeFMappingError(
                f"NIP sprzedawcy jest nieprawidłowy: '{raw_nip}'. "
                "Wymagane dokładnie 10 cyfr bez separatorów."
            )
        if not invoice.items:
            raise KSeFMappingError(
                "Faktura nie zawiera pozycji — wymagany co najmniej jeden FaWiersz"
            )
        if invoice.invoice_type in (InvoiceType.KOR, InvoiceType.KOR_ZAL, InvoiceType.KOR_ROZ):
            if not invoice.correction_of_ksef_number and not invoice.correction_of_invoice_id:
                raise KSeFMappingError(
                    "Faktura korygująca wymaga correction_of_ksef_number lub "
                    "correction_of_invoice_id."
                )


# Alias dla backward-compatibility — istniejący kod używający KSeFMapper nadal działa
KSeFMapper = FA3Mapper

