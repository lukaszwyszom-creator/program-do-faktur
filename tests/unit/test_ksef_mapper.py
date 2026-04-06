"""Testy KSeFMapper — mapowanie faktury do XML FA(3)."""
from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from lxml import etree

from app.domain.enums import InvoiceStatus
from app.domain.models.invoice import Invoice, InvoiceItem
from app.integrations.ksef.mapper import KSeFMapper, _NS_FA, _rate_key


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

def _make_item(
    name: str = "Usługa testowa",
    quantity: str = "1",
    unit: str = "szt.",
    unit_price_net: str = "100.00",
    vat_rate: str = "23",
    net_total: str = "100.00",
    vat_total: str = "23.00",
    gross_total: str = "123.00",
    sort_order: int = 1,
) -> InvoiceItem:
    return InvoiceItem(
        name=name,
        quantity=Decimal(quantity),
        unit=unit,
        unit_price_net=Decimal(unit_price_net),
        vat_rate=Decimal(vat_rate),
        net_total=Decimal(net_total),
        vat_total=Decimal(vat_total),
        gross_total=Decimal(gross_total),
        sort_order=sort_order,
    )


def _make_invoice(
    items: list[InvoiceItem] | None = None,
    issue_date: date | None = None,
    sale_date: date | None = None,
    currency: str = "PLN",
    number_local: str | None = "FV/1/04/2026",
    total_net: str = "100.00",
    total_vat: str = "23.00",
    total_gross: str = "123.00",
    seller_snapshot: dict | None = None,
    buyer_snapshot: dict | None = None,
) -> Invoice:
    now = datetime.now(UTC)
    return Invoice(
        id=uuid4(),
        status=InvoiceStatus.READY_FOR_SUBMISSION,
        issue_date=issue_date or date(2026, 4, 5),
        sale_date=sale_date or date(2026, 4, 5),
        currency=currency,
        number_local=number_local,
        seller_snapshot=seller_snapshot or {
            "nip": "1234567890",
            "name": "Sprzedawca Sp. z o.o.",
            "street": "ul. Testowa",
            "building_no": "1",
            "postal_code": "00-001",
            "city": "Warszawa",
            "country": "PL",
        },
        buyer_snapshot=buyer_snapshot or {
            "nip": "9876543210",
            "name": "Nabywca S.A.",
            "street": "ul. Kupiecka",
            "building_no": "5",
            "apartment_no": "10",
            "postal_code": "30-002",
            "city": "Kraków",
            "country": "PL",
        },
        items=items or [_make_item()],
        total_net=Decimal(total_net),
        total_vat=Decimal(total_vat),
        total_gross=Decimal(total_gross),
        created_at=now,
        updated_at=now,
    )


def _parse_xml(xml_bytes: bytes) -> etree._Element:
    return etree.fromstring(xml_bytes)


def _find(root: etree._Element, *tags: str) -> etree._Element | None:
    """Traversuje elementy po tagach z namespace FA."""
    current = root
    for tag in tags:
        found = current.find(f"{{{_NS_FA}}}{tag}")
        if found is None:
            return None
        current = found
    return current


def _text(root: etree._Element, *tags: str) -> str | None:
    el = _find(root, *tags)
    return el.text if el is not None else None


# ---------------------------------------------------------------------------
# TESTY
# ---------------------------------------------------------------------------


class TestInvoiceToXml:
    def test_returns_bytes(self):
        xml = KSeFMapper.invoice_to_xml(_make_invoice())
        assert isinstance(xml, bytes)

    def test_well_formed_xml(self):
        xml = KSeFMapper.invoice_to_xml(_make_invoice())
        root = _parse_xml(xml)
        assert root is not None

    def test_root_tag_faktura(self):
        xml = KSeFMapper.invoice_to_xml(_make_invoice())
        root = _parse_xml(xml)
        assert root.tag == f"{{{_NS_FA}}}Faktura"

    def test_naglowek_kod_formularza(self):
        xml = KSeFMapper.invoice_to_xml(_make_invoice())
        root = _parse_xml(xml)
        assert _text(root, "Naglowek", "KodFormularza") == "FA"

    def test_naglowek_wariant_formularza(self):
        xml = KSeFMapper.invoice_to_xml(_make_invoice())
        root = _parse_xml(xml)
        assert _text(root, "Naglowek", "WariantFormularza") == "3"

    def test_naglowek_data_wytworzenia(self):
        xml = KSeFMapper.invoice_to_xml(_make_invoice(issue_date=date(2026, 4, 5)))
        root = _parse_xml(xml)
        # FA(3): DataWytworzeniaFa to pełny datetime ISO 8601 UTC, nie sama data
        val = _text(root, "Naglowek", "DataWytworzeniaFa")
        assert val is not None
        assert "T" in val, f"Oczekiwano datetime ISO, otrzymano: {val}"
        assert val.endswith("Z"), f"Oczekiwano UTC Z, otrzymano: {val}"

    def test_fa_currency(self):
        xml = KSeFMapper.invoice_to_xml(_make_invoice(currency="EUR"))
        root = _parse_xml(xml)
        assert _text(root, "Fa", "KodWaluty") == "EUR"

    def test_fa_number_local_present(self):
        xml = KSeFMapper.invoice_to_xml(_make_invoice(number_local="FV/7/01/2026"))
        root = _parse_xml(xml)
        assert _text(root, "Fa", "P_2") == "FV/7/01/2026"

    def test_fa_number_local_absent(self):
        xml = KSeFMapper.invoice_to_xml(_make_invoice(number_local=None))
        root = _parse_xml(xml)
        # Element P_2 nie powinien istnieć
        assert _find(root, "Fa", "P_2") is None

    def test_fa_issue_date(self):
        xml = KSeFMapper.invoice_to_xml(_make_invoice(issue_date=date(2026, 3, 15)))
        root = _parse_xml(xml)
        assert _text(root, "Fa", "P_1") == "2026-03-15"

    def test_fa_sale_date(self):
        xml = KSeFMapper.invoice_to_xml(_make_invoice(sale_date=date(2026, 3, 10)))
        root = _parse_xml(xml)
        assert _text(root, "Fa", "P_1M") == "2026-03-10"

    def test_fa_total_net(self):
        # FA(3): P_13_x pochodzi z sum pozycji, nie z pola total_net faktury
        item = _make_item(net_total="500.00", vat_total="115.00", gross_total="615.00")
        xml = KSeFMapper.invoice_to_xml(
            _make_invoice(items=[item], total_net="500.00", total_vat="115.00", total_gross="615.00")
        )
        root = _parse_xml(xml)
        assert _text(root, "Fa", "P_13_1") == "500.00"

    def test_fa_total_vat(self):
        # FA(3): P_14_x pochodzi z sum pozycji, nie z pola total_vat faktury
        item = _make_item(net_total="500.00", vat_total="115.00", gross_total="615.00")
        xml = KSeFMapper.invoice_to_xml(
            _make_invoice(items=[item], total_net="500.00", total_vat="115.00", total_gross="615.00")
        )
        root = _parse_xml(xml)
        assert _text(root, "Fa", "P_14_1") == "115.00"

    def test_fa_total_gross(self):
        xml = KSeFMapper.invoice_to_xml(_make_invoice(total_gross="615.00"))
        root = _parse_xml(xml)
        assert _text(root, "Fa", "P_15") == "615.00"

    def test_fa_rodzaj_faktury(self):
        xml = KSeFMapper.invoice_to_xml(_make_invoice())
        root = _parse_xml(xml)
        assert _text(root, "Fa", "RodzajFaktury") == "VAT"


class TestSellerSnapshot:
    def test_seller_nip(self):
        xml = KSeFMapper.invoice_to_xml(_make_invoice())
        root = _parse_xml(xml)
        nip = _text(root, "Podmiot1", "Sprzedawca", "NIP")
        assert nip == "1234567890"

    def test_seller_name(self):
        xml = KSeFMapper.invoice_to_xml(_make_invoice())
        root = _parse_xml(xml)
        name = _text(root, "Podmiot1", "Sprzedawca", "Nazwa")
        assert name == "Sprzedawca Sp. z o.o."

    def test_seller_city(self):
        xml = KSeFMapper.invoice_to_xml(_make_invoice())
        root = _parse_xml(xml)
        city = _text(root, "Podmiot1", "Sprzedawca", "Adres", "Miejscowosc")
        assert city == "Warszawa"

    def test_seller_postal_code(self):
        xml = KSeFMapper.invoice_to_xml(_make_invoice())
        root = _parse_xml(xml)
        postal = _text(root, "Podmiot1", "Sprzedawca", "Adres", "KodPocztowy")
        assert postal == "00-001"

    def test_seller_country_default_pl(self):
        seller = {"nip": "1111111111", "name": "Firma"}
        xml = KSeFMapper.invoice_to_xml(_make_invoice(seller_snapshot=seller))
        root = _parse_xml(xml)
        country = _text(root, "Podmiot1", "Sprzedawca", "Adres", "KodKraju")
        assert country == "PL"

    def test_seller_no_nip_omitted(self):
        seller = {"name": "Firma bez NIP", "city": "Wrocław"}
        xml = KSeFMapper.invoice_to_xml(_make_invoice(seller_snapshot=seller))
        root = _parse_xml(xml)
        nip_el = _find(root, "Podmiot1", "Sprzedawca", "NIP")
        assert nip_el is None


class TestBuyerSnapshot:
    def test_buyer_nip(self):
        xml = KSeFMapper.invoice_to_xml(_make_invoice())
        root = _parse_xml(xml)
        nip = _text(root, "Podmiot2", "Nabywca", "NIP")
        assert nip == "9876543210"

    def test_buyer_apartment_no(self):
        xml = KSeFMapper.invoice_to_xml(_make_invoice())
        root = _parse_xml(xml)
        apt = _text(root, "Podmiot2", "Nabywca", "Adres", "AdresL2")
        assert apt == "m. 10"

    def test_buyer_street_building_in_adres_l1(self):
        xml = KSeFMapper.invoice_to_xml(_make_invoice())
        root = _parse_xml(xml)
        adres_l1 = _text(root, "Podmiot2", "Nabywca", "Adres", "AdresL1")
        assert "ul. Kupiecka" in adres_l1
        assert "5" in adres_l1


class TestInvoiceItems:
    def test_single_item_row(self):
        item = _make_item(name="Programowanie", quantity="2", sort_order=1)
        xml = KSeFMapper.invoice_to_xml(_make_invoice(items=[item]))
        root = _parse_xml(xml)
        fa = _find(root, "Fa")
        rows = fa.findall(f"{{{_NS_FA}}}FaWiersz")
        assert len(rows) == 1

    def test_multiple_items_count(self):
        items = [
            _make_item(name="A", sort_order=1),
            _make_item(name="B", sort_order=2),
            _make_item(name="C", sort_order=3),
        ]
        xml = KSeFMapper.invoice_to_xml(_make_invoice(items=items))
        root = _parse_xml(xml)
        fa = _find(root, "Fa")
        rows = fa.findall(f"{{{_NS_FA}}}FaWiersz")
        assert len(rows) == 3

    def test_item_name(self):
        item = _make_item(name="Konsulting")
        xml = KSeFMapper.invoice_to_xml(_make_invoice(items=[item]))
        root = _parse_xml(xml)
        fa = _find(root, "Fa")
        row = fa.find(f"{{{_NS_FA}}}FaWiersz")
        assert row.find(f"{{{_NS_FA}}}P_7").text == "Konsulting"

    def test_item_unit(self):
        item = _make_item(unit="godz.")
        xml = KSeFMapper.invoice_to_xml(_make_invoice(items=[item]))
        root = _parse_xml(xml)
        fa = _find(root, "Fa")
        row = fa.find(f"{{{_NS_FA}}}FaWiersz")
        assert row.find(f"{{{_NS_FA}}}P_8A").text == "godz."

    def test_item_quantity_formatted(self):
        item = _make_item(quantity="3.5")
        xml = KSeFMapper.invoice_to_xml(_make_invoice(items=[item]))
        root = _parse_xml(xml)
        fa = _find(root, "Fa")
        row = fa.find(f"{{{_NS_FA}}}FaWiersz")
        assert row.find(f"{{{_NS_FA}}}P_8B").text == "3.50"

    def test_item_unit_price_net(self):
        item = _make_item(unit_price_net="250.00")
        xml = KSeFMapper.invoice_to_xml(_make_invoice(items=[item]))
        root = _parse_xml(xml)
        fa = _find(root, "Fa")
        row = fa.find(f"{{{_NS_FA}}}FaWiersz")
        assert row.find(f"{{{_NS_FA}}}P_9A").text == "250.00"

    def test_item_vat_rate(self):
        item = _make_item(vat_rate="8")
        xml = KSeFMapper.invoice_to_xml(_make_invoice(items=[item]))
        root = _parse_xml(xml)
        fa = _find(root, "Fa")
        row = fa.find(f"{{{_NS_FA}}}FaWiersz")
        assert row.find(f"{{{_NS_FA}}}P_12").text == "8.00"

    def test_item_sort_order(self):
        item = _make_item(sort_order=42)
        xml = KSeFMapper.invoice_to_xml(_make_invoice(items=[item]))
        root = _parse_xml(xml)
        fa = _find(root, "Fa")
        row = fa.find(f"{{{_NS_FA}}}FaWiersz")
        assert row.find(f"{{{_NS_FA}}}NrWierszaFa").text == "42"


class TestValidateXml:
    def test_valid_xml_returns_true(self):
        xml = KSeFMapper.invoice_to_xml(_make_invoice())
        assert KSeFMapper.validate_xml(xml) is True

    def test_invalid_xml_returns_false(self):
        assert KSeFMapper.validate_xml(b"<not-closed>") is False

    def test_empty_bytes_returns_false(self):
        assert KSeFMapper.validate_xml(b"") is False


class TestFA3VatTotals:
    """Testy grupowania sum VAT per stawka."""

    def _make_item_with_rate(self, vat_rate: str, net: str, vat: str,
                              gross: str, sort_order: int = 1) -> InvoiceItem:
        return _make_item(
            vat_rate=vat_rate,
            net_total=net,
            vat_total=vat,
            gross_total=gross,
            sort_order=sort_order,
        )

    def test_single_rate_23_emits_p13_1_p14_1(self):
        item = self._make_item_with_rate("23", "100.00", "23.00", "123.00")
        xml = KSeFMapper.invoice_to_xml(_make_invoice(items=[item], total_net="100.00", total_vat="23.00"))
        root = _parse_xml(xml)
        assert _text(root, "Fa", "P_13_1") == "100.00"
        assert _text(root, "Fa", "P_14_1") == "23.00"
        assert _find(root, "Fa", "P_13_2") is None

    def test_single_rate_8_emits_p13_2_p14_2(self):
        item = self._make_item_with_rate("8", "100.00", "8.00", "108.00")
        xml = KSeFMapper.invoice_to_xml(_make_invoice(items=[item], total_net="100.00", total_vat="8.00", total_gross="108.00"))
        root = _parse_xml(xml)
        assert _text(root, "Fa", "P_13_2") == "100.00"
        assert _text(root, "Fa", "P_14_2") == "8.00"
        assert _find(root, "Fa", "P_13_1") is None

    def test_single_rate_5_emits_p13_3_p14_3(self):
        item = self._make_item_with_rate("5", "200.00", "10.00", "210.00")
        xml = KSeFMapper.invoice_to_xml(_make_invoice(items=[item], total_net="200.00", total_vat="10.00", total_gross="210.00"))
        root = _parse_xml(xml)
        assert _text(root, "Fa", "P_13_3") == "200.00"
        assert _text(root, "Fa", "P_14_3") == "10.00"

    def test_single_rate_0_emits_p13_4_p14_4(self):
        item = self._make_item_with_rate("0", "500.00", "0.00", "500.00")
        xml = KSeFMapper.invoice_to_xml(_make_invoice(items=[item], total_net="500.00", total_vat="0.00", total_gross="500.00"))
        root = _parse_xml(xml)
        assert _text(root, "Fa", "P_13_4") == "500.00"
        assert _text(root, "Fa", "P_14_4") == "0.00"

    def test_two_rates_emits_both_groups(self):
        item23 = self._make_item_with_rate("23", "100.00", "23.00", "123.00", sort_order=1)
        item8 = self._make_item_with_rate("8", "200.00", "16.00", "216.00", sort_order=2)
        xml = KSeFMapper.invoice_to_xml(_make_invoice(
            items=[item23, item8],
            total_net="300.00", total_vat="39.00", total_gross="339.00",
        ))
        root = _parse_xml(xml)
        assert _text(root, "Fa", "P_13_1") == "100.00"
        assert _text(root, "Fa", "P_14_1") == "23.00"
        assert _text(root, "Fa", "P_13_2") == "200.00"
        assert _text(root, "Fa", "P_14_2") == "16.00"

    def test_multiple_items_same_rate_sums_correctly(self):
        i1 = self._make_item_with_rate("23", "100.00", "23.00", "123.00", sort_order=1)
        i2 = self._make_item_with_rate("23", "200.00", "46.00", "246.00", sort_order=2)
        xml = KSeFMapper.invoice_to_xml(_make_invoice(
            items=[i1, i2], total_net="300.00", total_vat="69.00", total_gross="369.00",
        ))
        root = _parse_xml(xml)
        assert _text(root, "Fa", "P_13_1") == "300.00"
        assert _text(root, "Fa", "P_14_1") == "69.00"


class TestFA3P6DeliveryDate:
    """Testy pola P_6 (data dostawy) w FA(3)."""

    def test_p6_emitted_when_sale_date_differs_from_issue_date(self):
        xml = KSeFMapper.invoice_to_xml(_make_invoice(
            issue_date=date(2026, 4, 10),
            sale_date=date(2026, 4, 8),
        ))
        root = _parse_xml(xml)
        assert _text(root, "Fa", "P_6") == "2026-04-08"

    def test_p6_not_emitted_when_sale_date_equals_issue_date(self):
        xml = KSeFMapper.invoice_to_xml(_make_invoice(
            issue_date=date(2026, 4, 10),
            sale_date=date(2026, 4, 10),
        ))
        root = _parse_xml(xml)
        assert _find(root, "Fa", "P_6") is None

    def test_p6_uses_delivery_date_when_set(self):
        now = datetime.now(UTC)
        inv = Invoice(
            id=uuid4(),
            status=InvoiceStatus.READY_FOR_SUBMISSION,
            issue_date=date(2026, 4, 10),
            sale_date=date(2026, 4, 9),
            delivery_date=date(2026, 4, 7),
            currency="PLN",
            number_local="FV/1/04/2026",
            seller_snapshot={"nip": "1234567890", "name": "S"},
            buyer_snapshot={"nip": "9876543210", "name": "B"},
            items=[_make_item()],
            total_net=Decimal("100.00"),
            total_vat=Decimal("23.00"),
            total_gross=Decimal("123.00"),
            created_at=now,
            updated_at=now,
        )
        xml = KSeFMapper.invoice_to_xml(inv)
        root = _parse_xml(xml)
        assert _text(root, "Fa", "P_6") == "2026-04-07"

    def test_p6_not_emitted_when_delivery_date_equals_issue_date(self):
        now = datetime.now(UTC)
        inv = Invoice(
            id=uuid4(),
            status=InvoiceStatus.READY_FOR_SUBMISSION,
            issue_date=date(2026, 4, 10),
            sale_date=date(2026, 4, 8),
            delivery_date=date(2026, 4, 10),  # równa issue_date
            currency="PLN",
            number_local=None,
            seller_snapshot={"nip": "1234567890", "name": "S"},
            buyer_snapshot={"nip": "9876543210", "name": "B"},
            items=[_make_item()],
            total_net=Decimal("100.00"),
            total_vat=Decimal("23.00"),
            total_gross=Decimal("123.00"),
            created_at=now,
            updated_at=now,
        )
        xml = KSeFMapper.invoice_to_xml(inv)
        root = _parse_xml(xml)
        assert _find(root, "Fa", "P_6") is None


class TestRateKey:
    """Testy helpera _rate_key."""

    def test_23_percent(self):
        assert _rate_key(Decimal("23")) == "23"

    def test_23_decimal(self):
        assert _rate_key(Decimal("23.00")) == "23"

    def test_8_percent(self):
        assert _rate_key(Decimal("8")) == "8"

    def test_5_percent(self):
        assert _rate_key(Decimal("5")) == "5"

    def test_0_percent(self):
        assert _rate_key(Decimal("0")) == "0"


class TestExceptions:
    def test_ksef_exceptions_importable(self):
        from app.integrations.ksef.exceptions import (
            KSeFError,
            KSeFAuthError,
            KSeFClientError,
            KSeFMappingError,
            KSeFSessionError,
        )
        assert issubclass(KSeFMappingError, KSeFError)
        assert issubclass(KSeFSessionError, KSeFError)

    def test_ksef_client_error_is_exception(self):
        from app.integrations.ksef.exceptions import KSeFClientError
        err = KSeFClientError("test", status_code=500, transient=True)
        assert str(err) == "test"
        assert err.transient is True
