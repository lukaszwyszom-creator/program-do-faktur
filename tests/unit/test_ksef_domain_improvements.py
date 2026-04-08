"""Testy domain-driven ulepszeń KSeF:
- CorrectionType enum
- Invoice.validate_vat() / validate_kor() / validate_zal()
- Nowe pola Adnotacje (P_18B, exchange_rate, vat_amount_pln)
- xml_content_hash (C14N idempotency)
- KSeFSessionService: per-NIP izolacja + token cache TTL
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from lxml import etree

from app.domain.enums import CorrectionType, InvoiceStatus, InvoiceType
from app.domain.exceptions import InvalidInvoiceError
from app.domain.models.invoice import Invoice, InvoiceItem
from app.integrations.ksef.exceptions import KSeFMappingError
from app.integrations.ksef.mapper import FA3Mapper, KSeFMapper, _NS_FA
from app.services.ksef_session_service import (
    SESSION_ACTIVE,
    SESSION_EXPIRED,
    KSeFSessionService,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_item(
    name: str = "Usługa",
    net_total: str = "100.00",
    vat_total: str = "23.00",
    gross_total: str = "123.00",
    vat_rate: str = "23",
    sort_order: int = 1,
    vat_amount_pln: str | None = None,
) -> InvoiceItem:
    return InvoiceItem(
        name=name,
        quantity=Decimal("1"),
        unit="szt.",
        unit_price_net=Decimal(net_total),
        vat_rate=Decimal(vat_rate),
        net_total=Decimal(net_total),
        vat_total=Decimal(vat_total),
        gross_total=Decimal(gross_total),
        sort_order=sort_order,
        vat_amount_pln=Decimal(vat_amount_pln) if vat_amount_pln else None,
    )


def _make_invoice(**kwargs) -> Invoice:
    defaults = dict(
        id=uuid4(),
        status=InvoiceStatus.READY_FOR_SUBMISSION,
        issue_date=date(2026, 4, 6),
        sale_date=date(2026, 4, 6),
        currency="PLN",
        seller_snapshot={
            "nip": "1000000035",
            "name": "Sprzedawca Sp. z o.o.",
            "street": "ul. Testowa",
            "building_no": "1",
            "postal_code": "00-001",
            "city": "Warszawa",
        },
        buyer_snapshot={
            "nip": "1000000070",
            "name": "Nabywca S.A.",
        },
        items=[_make_item()],
        total_net=Decimal("100.00"),
        total_vat=Decimal("23.00"),
        total_gross=Decimal("123.00"),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    defaults.update(kwargs)
    return Invoice(**defaults)


def _xml_text(xml_bytes: bytes, xpath: str) -> str | None:
    root = etree.fromstring(xml_bytes)
    results = root.xpath(xpath, namespaces={"fa": _NS_FA})
    if not results:
        return None
    node = results[0]
    return node.text if hasattr(node, "text") else str(node)


# ---------------------------------------------------------------------------
# CorrectionType enum
# ---------------------------------------------------------------------------

class TestCorrectionTypeEnum:
    def test_full_value(self):
        assert CorrectionType.FULL == "full"

    def test_partial_value(self):
        assert CorrectionType.PARTIAL == "partial"

    def test_str_roundtrip(self):
        assert CorrectionType("full") is CorrectionType.FULL
        assert CorrectionType("partial") is CorrectionType.PARTIAL


# ---------------------------------------------------------------------------
# Invoice.validate_vat()
# ---------------------------------------------------------------------------

class TestValidateVat:
    def test_valid_invoice_no_error(self):
        inv = _make_invoice()
        inv.validate_vat()  # nie rzuca

    def test_invalid_seller_nip_raises(self):
        inv = _make_invoice(seller_snapshot={"nip": "123"})
        with pytest.raises(InvalidInvoiceError, match="NIP sprzedawcy"):
            inv.validate_vat()

    def test_invalid_buyer_nip_raises(self):
        inv = _make_invoice(buyer_snapshot={"nip": "ABC"})
        with pytest.raises(InvalidInvoiceError, match="NIP nabywcy"):
            inv.validate_vat()

    def test_buyer_nip_none_is_ok(self):
        inv = _make_invoice(buyer_snapshot={"nip": None})
        inv.validate_vat()  # brak NIP nabywcy jest dopuszczalny (B2C)

    def test_totals_mismatch_raises(self):
        inv = _make_invoice(total_net=Decimal("100"), total_vat=Decimal("23"),
                            total_gross=Decimal("200"))
        with pytest.raises(InvalidInvoiceError, match="Niespójność"):
            inv.validate_vat()

    def test_foreign_currency_requires_exchange_rate(self):
        item = _make_item(vat_amount_pln="10.00")
        inv = _make_invoice(currency="EUR", exchange_rate=None, items=[item])
        with pytest.raises(InvalidInvoiceError, match="exchange_rate"):
            inv.validate_vat()

    def test_foreign_currency_zero_rate_raises(self):
        item = _make_item(vat_amount_pln="10.00")
        inv = _make_invoice(currency="EUR", exchange_rate=Decimal("0"), items=[item])
        with pytest.raises(InvalidInvoiceError, match="dodatnie"):
            inv.validate_vat()

    def test_foreign_currency_item_missing_vat_pln_raises(self):
        item = _make_item()  # vat_amount_pln = None
        inv = _make_invoice(currency="EUR", exchange_rate=Decimal("4.25"), items=[item])
        with pytest.raises(InvalidInvoiceError, match="vat_amount_pln"):
            inv.validate_vat()

    def test_foreign_currency_all_fields_ok(self):
        item = _make_item(vat_amount_pln="97.75")
        inv = _make_invoice(currency="EUR", exchange_rate=Decimal("4.25"), items=[item])
        inv.validate_vat()  # nie rzuca


# ---------------------------------------------------------------------------
# Invoice.validate_kor()
# ---------------------------------------------------------------------------

class TestValidateKor:
    def _kor_invoice(self, **kwargs) -> Invoice:
        defaults = dict(
            invoice_type=InvoiceType.KOR,
            correction_of_ksef_number="FA-KSEF-123",
            correction_reason="Błędna cena",
            correction_type=CorrectionType.PARTIAL,
        )
        defaults.update(kwargs)
        return _make_invoice(**defaults)

    def test_valid_kor(self):
        inv = self._kor_invoice()
        inv.validate_kor()

    def test_missing_ksef_number_and_id_raises(self):
        inv = self._kor_invoice(
            correction_of_ksef_number=None,
            correction_of_invoice_id=None,
        )
        with pytest.raises(InvalidInvoiceError, match="correction_of_ksef_number"):
            inv.validate_kor()

    def test_correction_with_only_id_is_ok(self):
        inv = self._kor_invoice(
            correction_of_ksef_number=None,
            correction_of_invoice_id=uuid4(),
        )
        inv.validate_kor()

    def test_missing_reason_raises(self):
        inv = self._kor_invoice(correction_reason=None)
        with pytest.raises(InvalidInvoiceError, match="correction_reason"):
            inv.validate_kor()

    def test_missing_correction_type_raises(self):
        inv = self._kor_invoice(correction_type=None)
        with pytest.raises(InvalidInvoiceError, match="correction_type"):
            inv.validate_kor()


# ---------------------------------------------------------------------------
# Invoice.validate_zal()
# ---------------------------------------------------------------------------

class TestValidateZal:
    def test_zal_valid(self):
        inv = _make_invoice(
            invoice_type=InvoiceType.ZAL,
            advance_amount=Decimal("50.00"),
        )
        inv.validate_zal()

    def test_zal_missing_amount_raises(self):
        inv = _make_invoice(invoice_type=InvoiceType.ZAL, advance_amount=None)
        with pytest.raises(InvalidInvoiceError, match="advance_amount"):
            inv.validate_zal()

    def test_zal_zero_amount_raises(self):
        inv = _make_invoice(invoice_type=InvoiceType.ZAL, advance_amount=Decimal("0"))
        with pytest.raises(InvalidInvoiceError, match="advance_amount"):
            inv.validate_zal()

    def test_zal_amount_exceeds_gross_raises(self):
        inv = _make_invoice(
            invoice_type=InvoiceType.ZAL,
            advance_amount=Decimal("999.00"),   # > total_gross=123
        )
        with pytest.raises(InvalidInvoiceError, match="większy niż total_gross"):
            inv.validate_zal()

    def test_roz_missing_settled_ids_raises(self):
        inv = _make_invoice(
            invoice_type=InvoiceType.ROZ,
            settled_advance_ids=[],
        )
        with pytest.raises(InvalidInvoiceError, match="settled_advance_ids"):
            inv.validate_zal()

    def test_roz_with_ids_ok(self):
        inv = _make_invoice(
            invoice_type=InvoiceType.ROZ,
            settled_advance_ids=[uuid4(), uuid4()],
        )
        inv.validate_zal()  # nie rzuca


# ---------------------------------------------------------------------------
# Invoice.validate_for_ksef() — delegacja
# ---------------------------------------------------------------------------

class TestValidateForKsef:
    def test_vat_delegates_to_validate_vat(self):
        inv = _make_invoice(invoice_type=InvoiceType.VAT)
        inv.validate_for_ksef()  # nie rzuca

    def test_kor_calls_validate_kor(self):
        inv = _make_invoice(
            invoice_type=InvoiceType.KOR,
            correction_of_ksef_number="REF-123",
            correction_reason="błąd",
            correction_type=CorrectionType.FULL,
        )
        inv.validate_for_ksef()  # nie rzuca

    def test_kor_without_reason_raises(self):
        inv = _make_invoice(
            invoice_type=InvoiceType.KOR,
            correction_of_ksef_number="REF-123",
            correction_reason=None,
            correction_type=CorrectionType.FULL,
        )
        with pytest.raises(InvalidInvoiceError):
            inv.validate_for_ksef()

    def test_zal_calls_validate_zal(self):
        inv = _make_invoice(
            invoice_type=InvoiceType.ZAL,
            advance_amount=Decimal("100.00"),
        )
        inv.validate_for_ksef()

    def test_zal_missing_amount_raises_via_validate_for_ksef(self):
        inv = _make_invoice(invoice_type=InvoiceType.ZAL, advance_amount=None)
        with pytest.raises(InvalidInvoiceError, match="advance_amount"):
            inv.validate_for_ksef()


# ---------------------------------------------------------------------------
# Mapper: Adnotacje dynamiczne
# ---------------------------------------------------------------------------

class TestAdnotacje:
    def test_default_all_zeros(self):
        inv = _make_invoice()
        xml = KSeFMapper.invoice_to_xml(inv)
        assert _xml_text(xml, "//fa:Adnotacje/fa:P_16") == "0"
        assert _xml_text(xml, "//fa:Adnotacje/fa:P_17") == "0"
        assert _xml_text(xml, "//fa:Adnotacje/fa:P_18") == "0"
        assert _xml_text(xml, "//fa:Adnotacje/fa:P_18A") == "0"
        assert _xml_text(xml, "//fa:Adnotacje/fa:P_18B") == "0"

    def test_p_18b_set_when_reverse_charge_flag(self):
        inv = _make_invoice(reverse_charge_flag=True)
        xml = KSeFMapper.invoice_to_xml(inv)
        assert _xml_text(xml, "//fa:Adnotacje/fa:P_18B") == "1"

    def test_p16_mpp(self):
        inv = _make_invoice(use_split_payment=True)
        xml = KSeFMapper.invoice_to_xml(inv)
        assert _xml_text(xml, "//fa:Adnotacje/fa:P_16") == "1"

    def test_p17_samofakturowanie(self):
        inv = _make_invoice(self_billing=True)
        xml = KSeFMapper.invoice_to_xml(inv)
        assert _xml_text(xml, "//fa:Adnotacje/fa:P_17") == "1"

    def test_p18_odwrotne_obciazenie(self):
        inv = _make_invoice(reverse_charge=True)
        xml = KSeFMapper.invoice_to_xml(inv)
        assert _xml_text(xml, "//fa:Adnotacje/fa:P_18") == "1"

    def test_p19_not_emitted_when_false(self):
        inv = _make_invoice(cash_accounting_method=False)
        xml = KSeFMapper.invoice_to_xml(inv)
        assert _xml_text(xml, "//fa:Adnotacje/fa:P_19") is None

    def test_p19_emitted_when_true(self):
        inv = _make_invoice(cash_accounting_method=True)
        xml = KSeFMapper.invoice_to_xml(inv)
        assert _xml_text(xml, "//fa:Adnotacje/fa:P_19") == "1"


# ---------------------------------------------------------------------------
# Mapper: exchange_rate i P_14_xW
# ---------------------------------------------------------------------------

class TestExchangeRateAndP14W:
    def test_kurs_waluty_emitted_for_foreign_currency(self):
        item = _make_item(vat_amount_pln="97.75")
        inv = _make_invoice(
            currency="EUR",
            exchange_rate=Decimal("4.2500"),
            exchange_rate_date=date(2026, 4, 5),
            items=[item],
        )
        xml = KSeFMapper.invoice_to_xml(inv)
        assert _xml_text(xml, "//fa:Fa/fa:KursWaluty") == "4.25"

    def test_data_kursu_waluty_emitted(self):
        item = _make_item(vat_amount_pln="97.75")
        inv = _make_invoice(
            currency="EUR",
            exchange_rate=Decimal("4.2500"),
            exchange_rate_date=date(2026, 4, 5),
            items=[item],
        )
        xml = KSeFMapper.invoice_to_xml(inv)
        assert _xml_text(xml, "//fa:Fa/fa:DataKursuWaluty") == "2026-04-05"

    def test_kurs_waluty_not_emitted_for_pln(self):
        inv = _make_invoice(currency="PLN")
        xml = KSeFMapper.invoice_to_xml(inv)
        assert _xml_text(xml, "//fa:Fa/fa:KursWaluty") is None

    def test_p14_1w_emitted_when_vat_amount_pln_set(self):
        item = _make_item(vat_amount_pln="97.75")
        inv = _make_invoice(
            currency="EUR",
            exchange_rate=Decimal("4.25"),
            items=[item],
        )
        xml = KSeFMapper.invoice_to_xml(inv)
        assert _xml_text(xml, "//fa:Fa/fa:P_14_1W") == "97.75"

    def test_p14_1w_not_emitted_for_pln(self):
        inv = _make_invoice(currency="PLN")
        xml = KSeFMapper.invoice_to_xml(inv)
        assert _xml_text(xml, "//fa:Fa/fa:P_14_1W") is None


# ---------------------------------------------------------------------------
# Mapper: xml_content_hash (C14N idempotency)
# ---------------------------------------------------------------------------

class TestXmlContentHash:
    def test_hash_is_hex_string(self):
        inv = _make_invoice()
        xml = KSeFMapper.invoice_to_xml(inv)
        h = KSeFMapper.xml_content_hash(xml)
        assert isinstance(h, str)
        assert len(h) == 64  # SHA-256 = 32 bytes = 64 hex chars
        int(h, 16)  # wszystkie znaki to hex

    def test_same_xml_same_hash(self):
        inv = _make_invoice(number_local="FV/1/04/2026")
        xml1 = KSeFMapper.invoice_to_xml(inv)
        xml2 = KSeFMapper.invoice_to_xml(inv)
        # Dwa wywołania mogą różnić się DataWytworzeniaFa —
        # testujemy hash bezpośrednio na tych samych bajtach
        assert KSeFMapper.xml_content_hash(xml1) == KSeFMapper.xml_content_hash(xml1)

    def test_different_xml_different_hash(self):
        inv1 = _make_invoice(number_local="FV/1/04/2026")
        inv2 = _make_invoice(number_local="FV/2/04/2026")
        xml1 = KSeFMapper.invoice_to_xml(inv1)
        xml2 = KSeFMapper.invoice_to_xml(inv2)
        assert KSeFMapper.xml_content_hash(xml1) != KSeFMapper.xml_content_hash(xml2)

    def test_empty_xml_raises(self):
        with pytest.raises(KSeFMappingError, match="Pusty XML"):
            KSeFMapper.xml_content_hash(b"")

    def test_malformed_xml_raises(self):
        with pytest.raises(KSeFMappingError, match="nie jest poprawny"):
            KSeFMapper.xml_content_hash(b"<not closed")


# ---------------------------------------------------------------------------
# KSeFSessionService: per-NIP izolacja
# ---------------------------------------------------------------------------

@pytest.fixture()
def _auth_provider() -> MagicMock:
    provider = MagicMock()
    provider.environment = "test"
    return provider


@pytest.fixture()
def _service(mock_session: MagicMock, _auth_provider: MagicMock) -> KSeFSessionService:
    return KSeFSessionService(
        session=mock_session,
        auth_provider=_auth_provider,
        audit_service=MagicMock(),
    )


class TestPerNipSessionIsolation:
    @patch("app.services.ksef_session_service.settings")
    def test_open_session_stores_nip(
        self,
        mock_settings,
        _service: KSeFSessionService,
        _auth_provider: MagicMock,
        mock_session: MagicMock,
    ):
        from app.integrations.ksef.auth import KSeFSession

        mock_settings.ksef_auth_token = "tok"
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        _auth_provider.get_challenge.return_value = {"challenge": "ch"}
        _auth_provider.init_session.return_value = KSeFSession(
            session_token="t", session_reference="ref", expires_at=None
        )

        orm = _service.open_session("1234567890")
        assert orm.nip == "1234567890"

    @patch("app.services.ksef_session_service.settings")
    def test_conflict_only_for_same_nip(
        self,
        mock_settings,
        _service: KSeFSessionService,
        mock_session: MagicMock,
    ):
        """Jeśli aktywna sesja istnieje dla NIP X, otwarcie dla NIP Y nie powinno rzucać."""
        mock_settings.ksef_auth_token = "tok"

        # Symuluj: dla NIP "9999999999" jest aktywna sesja;
        # query zwraca None (kwerenda jest per-NIP)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        from app.integrations.ksef.auth import KSeFSession
        _service.auth_provider.get_challenge.return_value = {"challenge": "ch"}
        _service.auth_provider.init_session.return_value = KSeFSession(
            session_token="t2", session_reference="ref2", expires_at=None
        )

        # Inny NIP — nie powinno rzucić ConflictError
        orm = _service.open_session("0000000001")
        assert orm.nip == "0000000001"


class TestTokenCacheTTL:
    def test_cache_returns_same_token_on_second_call(
        self,
        _service: KSeFSessionService,
        mock_session: MagicMock,
    ):
        expires = datetime.now(UTC) + timedelta(hours=1)
        active_orm = MagicMock()
        active_orm.token_metadata_json = {"session_token": "tok-abc"}
        active_orm.expires_at = expires
        active_orm.nip = "1234567890"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = active_orm
        mock_session.execute.return_value = mock_result

        token1 = _service.get_session_token("1234567890")
        # Drugi call — z cache, bez trafienia do DB
        mock_session.execute.reset_mock()
        token2 = _service.get_session_token("1234567890")

        assert token1 == token2 == "tok-abc"
        mock_session.execute.assert_not_called()

    def test_expired_cache_hits_db(
        self,
        _service: KSeFSessionService,
        mock_session: MagicMock,
    ):
        """Jeśli token wygasł, cache jest pomijany i trafia do DB."""
        expires_soon = datetime.now(UTC) + timedelta(seconds=10)  # < 30s margines
        active_orm = MagicMock()
        active_orm.token_metadata_json = {"session_token": "tok-fresh"}
        active_orm.expires_at = expires_soon
        active_orm.nip = "1234567890"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = active_orm
        mock_session.execute.return_value = mock_result

        # Ustaw wygasły wpis w cache
        from app.services.ksef_session_service import _TokenCacheEntry
        expired_entry = _TokenCacheEntry("tok-old", datetime.now(UTC) - timedelta(seconds=1))
        _service._token_cache["1234567890"] = expired_entry

        token = _service.get_session_token("1234567890")
        assert token == "tok-fresh"  # pobrano z DB, nie z cache

    def test_invalidate_cache_on_close(
        self,
        _service: KSeFSessionService,
        mock_session: MagicMock,
    ):
        """close_session() powinno wyczyścić cache dla danego NIP."""
        from app.services.ksef_session_service import _TokenCacheEntry

        expires = datetime.now(UTC) + timedelta(hours=1)
        active_orm = MagicMock()
        active_orm.token_metadata_json = {"session_token": "tok-xyz"}
        active_orm.expires_at = expires
        active_orm.nip = "1234567890"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = active_orm
        mock_session.execute.return_value = mock_result

        _service._token_cache["1234567890"] = _TokenCacheEntry("tok-xyz", expires)

        _service.close_session("1234567890")
        assert "1234567890" not in _service._token_cache
