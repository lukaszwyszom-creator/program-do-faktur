from __future__ import annotations

import logging

from lxml import etree

from app.domain.models.invoice import Invoice

logger = logging.getLogger(__name__)

_NS_FA = "http://crd.gov.pl/wzor/2023/06/29/9781/"
_NS_XSI = "http://www.w3.org/2001/XMLSchema-instance"
_NS_MAP = {"fa": _NS_FA, "xsi": _NS_XSI}


def _el(parent: etree._Element, tag: str, text: str | None = None) -> etree._Element:
    el = etree.SubElement(parent, f"{{{_NS_FA}}}{tag}")
    if text is not None:
        el.text = str(text)
    return el


def _fmt(value) -> str:
    return f"{float(value):.2f}"


class KSeFMapper:
    """Transformacja modelu wewnetrznego faktury do formatu KSeF."""

    @staticmethod
    def invoice_to_xml(invoice: Invoice) -> bytes:
        root = etree.Element(f"{{{_NS_FA}}}Faktura", nsmap=_NS_MAP)

        # — Naglowek
        hdr = _el(root, "Naglowek")
        _el(hdr, "KodFormularza", "FA")
        _el(hdr, "WariantFormularza", "2")
        _el(hdr, "DataWytworzeniaFa", invoice.issue_date.isoformat())
        _el(hdr, "SystemInfo", "KSeF-Backend/0.1")

        # — Podmiot1 (Sprzedawca)
        podmiot1 = _el(root, "Podmiot1")
        sprzedawca = _el(podmiot1, "Sprzedawca")
        s = invoice.seller_snapshot or {}
        if s.get("nip"):
            _el(sprzedawca, "NIP", s["nip"])
        if s.get("name"):
            _el(sprzedawca, "Nazwa", s["name"])
        adres_s = _el(sprzedawca, "Adres")
        if s.get("street") or s.get("building_no"):
            l1 = " ".join(filter(None, [s.get("street"), s.get("building_no")]))
            _el(adres_s, "AdresL1", l1)
        if s.get("apartment_no"):
            _el(adres_s, "AdresL2", f"m. {s['apartment_no']}")
        if s.get("postal_code"):
            _el(adres_s, "KodPocztowy", s["postal_code"])
        if s.get("city"):
            _el(adres_s, "Miejscowosc", s["city"])
        _el(adres_s, "KodKraju", s.get("country") or "PL")

        # — Podmiot2 (Nabywca)
        podmiot2 = _el(root, "Podmiot2")
        nabywca = _el(podmiot2, "Nabywca")
        b = invoice.buyer_snapshot or {}
        if b.get("nip"):
            _el(nabywca, "NIP", b["nip"])
        if b.get("name"):
            _el(nabywca, "Nazwa", b["name"])
        adres_b = _el(nabywca, "Adres")
        if b.get("street") or b.get("building_no"):
            l1 = " ".join(filter(None, [b.get("street"), b.get("building_no")]))
            _el(adres_b, "AdresL1", l1)
        if b.get("apartment_no"):
            _el(adres_b, "AdresL2", f"m. {b['apartment_no']}")
        if b.get("postal_code"):
            _el(adres_b, "KodPocztowy", b["postal_code"])
        if b.get("city"):
            _el(adres_b, "Miejscowosc", b["city"])
        _el(adres_b, "KodKraju", b.get("country") or "PL")

        # — Fa (główka)
        fa = _el(root, "Fa")
        _el(fa, "KodWaluty", invoice.currency or "PLN")
        _el(fa, "P_1", invoice.issue_date.isoformat())
        _el(fa, "P_1M", invoice.sale_date.isoformat())
        if invoice.number_local is not None:
            _el(fa, "P_2", invoice.number_local)
        _el(fa, "P_13_1", _fmt(invoice.total_net))
        _el(fa, "P_14_1", _fmt(invoice.total_vat))
        _el(fa, "P_15", _fmt(invoice.total_gross))
        _el(fa, "RodzajFaktury", "VAT")

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
    def validate_xml(xml_bytes: bytes) -> bool:
        if not xml_bytes:
            return False
        try:
            etree.fromstring(xml_bytes)
            return True
        except etree.XMLSyntaxError:
            return False
