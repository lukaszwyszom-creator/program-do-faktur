"""Testy InvoiceMapper — mapowanie domain ↔ ORM."""
from __future__ import annotations

from datetime import date, datetime, UTC
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import uuid4

from app.domain.enums import InvoiceStatus
from app.domain.models.invoice import Invoice, InvoiceItem
from app.persistence.mappers.invoice_mapper import InvoiceMapper


def _make_item_orm():
    orm = MagicMock()
    orm.id = uuid4()
    orm.name = "Usługa"
    orm.quantity = Decimal("5")
    orm.unit = "godz."
    orm.unit_price_net = Decimal("100.00")
    orm.vat_rate = Decimal("23")
    orm.net_amount = Decimal("500.00")
    orm.vat_amount = Decimal("115.00")
    orm.gross_amount = Decimal("615.00")
    orm.sort_order = 1
    return orm


def _make_invoice_orm():
    orm = MagicMock()
    orm.id = uuid4()
    orm.number_local = "FV/1/04/2026"
    orm.status = "draft"
    orm.issue_date = date(2026, 4, 5)
    orm.sale_date = date(2026, 4, 5)
    orm.currency = "PLN"
    orm.seller_snapshot_json = {"nip": "123"}
    orm.buyer_snapshot_json = {"nip": "456"}
    orm.totals_json = {
        "total_net": "500.00",
        "total_vat": "115.00",
        "total_gross": "615.00",
    }
    orm.created_by = uuid4()
    orm.created_at = datetime.now(UTC)
    orm.updated_at = datetime.now(UTC)
    orm.items = [_make_item_orm()]
    return orm


class TestToDomain:
    def test_maps_basic_fields(self):
        orm = _make_invoice_orm()
        domain = InvoiceMapper.to_domain(orm)

        assert domain.id == orm.id
        assert domain.number_local == "FV/1/04/2026"
        assert domain.status == InvoiceStatus.DRAFT
        assert domain.issue_date == date(2026, 4, 5)
        assert domain.currency == "PLN"

    def test_maps_totals(self):
        orm = _make_invoice_orm()
        domain = InvoiceMapper.to_domain(orm)

        assert domain.total_net == Decimal("500.00")
        assert domain.total_vat == Decimal("115.00")
        assert domain.total_gross == Decimal("615.00")

    def test_maps_items(self):
        orm = _make_invoice_orm()
        domain = InvoiceMapper.to_domain(orm)

        assert len(domain.items) == 1
        item = domain.items[0]
        assert item.name == "Usługa"
        assert item.quantity == Decimal("5")
        assert item.vat_rate == Decimal("23")


class TestToOrm:
    def test_creates_orm(self, sample_invoice: Invoice):
        orm = InvoiceMapper.to_orm(sample_invoice)

        assert orm.id == sample_invoice.id
        assert orm.status == "draft"
        assert orm.currency == "PLN"
        assert len(orm.items) == len(sample_invoice.items)

    def test_totals_json(self, sample_invoice: Invoice):
        orm = InvoiceMapper.to_orm(sample_invoice)

        assert orm.totals_json["total_net"] == str(sample_invoice.total_net)
        assert orm.totals_json["total_vat"] == str(sample_invoice.total_vat)
        assert orm.totals_json["total_gross"] == str(sample_invoice.total_gross)


class TestUpdateOrm:
    def test_updates_fields(self, sample_invoice: Invoice):
        orm = MagicMock()
        orm.items = []
        sample_invoice.status = InvoiceStatus.READY_FOR_SUBMISSION
        sample_invoice.number_local = "FV/1/04/2026"

        InvoiceMapper.update_orm(orm, sample_invoice)

        assert orm.status == "ready_for_submission"
        assert orm.number_local == "FV/1/04/2026"


class TestBuildContractorSnapshot:
    def test_without_override(self):
        contractor = MagicMock()
        contractor.nip = "1234567890"
        contractor.name = "Firma"
        contractor.regon = "123456789"
        contractor.krs = None
        contractor.legal_form = "sp_z_oo"
        contractor.street = "ul. Testowa"
        contractor.building_no = "1"
        contractor.apartment_no = None
        contractor.postal_code = "00-001"
        contractor.city = "Warszawa"
        contractor.voivodeship = "mazowieckie"
        contractor.county = "Warszawa"
        contractor.commune = "Warszawa"
        contractor.country = "PL"

        snapshot = InvoiceMapper.build_contractor_snapshot(contractor, override=None)

        assert snapshot["nip"] == "1234567890"
        assert snapshot["name"] == "Firma"
        assert snapshot["city"] == "Warszawa"

    def test_with_active_override(self):
        contractor = MagicMock()
        contractor.nip = "1234567890"
        contractor.name = "Firma Stara"
        for f in ("regon", "krs", "legal_form", "street", "building_no",
                   "apartment_no", "postal_code", "city", "voivodeship",
                   "county", "commune", "country"):
            setattr(contractor, f, None)

        override = MagicMock()
        override.is_active = True
        override.name = "Firma Nowa"
        override.legal_form = None
        override.street = "ul. Override"
        override.building_no = None
        override.apartment_no = None
        override.postal_code = None
        override.city = "Kraków"
        override.voivodeship = None
        override.county = None
        override.commune = None

        snapshot = InvoiceMapper.build_contractor_snapshot(contractor, override)

        assert snapshot["name"] == "Firma Nowa"
        assert snapshot["city"] == "Kraków"
        assert snapshot["street"] == "ul. Override"

    def test_inactive_override_ignored(self):
        contractor = MagicMock()
        contractor.nip = "111"
        contractor.name = "Original"
        for f in ("regon", "krs", "legal_form", "street", "building_no",
                   "apartment_no", "postal_code", "city", "voivodeship",
                   "county", "commune", "country"):
            setattr(contractor, f, None)

        override = MagicMock()
        override.is_active = False
        override.name = "Override"

        snapshot = InvoiceMapper.build_contractor_snapshot(contractor, override)
        assert snapshot["name"] == "Original"


class TestFA3Fields:
    """Testy mapowania pol FA(3): delivery_date i ksef_reference_number."""

    def _make_orm_with_fa3(self, delivery_date=None, ksef_reference_number=None):
        orm = _make_invoice_orm()
        orm.delivery_date = delivery_date
        orm.ksef_reference_number = ksef_reference_number
        return orm

    def test_to_domain_maps_delivery_date(self):
        orm = self._make_orm_with_fa3(delivery_date=date(2026, 4, 4))
        domain = InvoiceMapper.to_domain(orm)
        assert domain.delivery_date == date(2026, 4, 4)

    def test_to_domain_delivery_date_none(self):
        orm = self._make_orm_with_fa3(delivery_date=None)
        domain = InvoiceMapper.to_domain(orm)
        assert domain.delivery_date is None

    def test_to_domain_maps_ksef_reference_number(self):
        orm = self._make_orm_with_fa3(ksef_reference_number="9999909999-20260406-ABC12345-01")
        domain = InvoiceMapper.to_domain(orm)
        assert domain.ksef_reference_number == "9999909999-20260406-ABC12345-01"

    def test_to_domain_ksef_reference_number_none(self):
        orm = self._make_orm_with_fa3(ksef_reference_number=None)
        domain = InvoiceMapper.to_domain(orm)
        assert domain.ksef_reference_number is None

    def test_to_orm_writes_delivery_date(self, sample_invoice: Invoice):
        sample_invoice.delivery_date = date(2026, 4, 3)
        orm = InvoiceMapper.to_orm(sample_invoice)
        assert orm.delivery_date == date(2026, 4, 3)

    def test_to_orm_writes_ksef_reference_number(self, sample_invoice: Invoice):
        sample_invoice.ksef_reference_number = "1234567890-20260406-XYZ00001-01"
        orm = InvoiceMapper.to_orm(sample_invoice)
        assert orm.ksef_reference_number == "1234567890-20260406-XYZ00001-01"

    def test_update_orm_sets_delivery_date(self, sample_invoice: Invoice):
        from unittest.mock import MagicMock
        orm = MagicMock()
        orm.items = []
        sample_invoice.delivery_date = date(2026, 4, 2)
        InvoiceMapper.update_orm(orm, sample_invoice)
        assert orm.delivery_date == date(2026, 4, 2)

    def test_update_orm_sets_ksef_reference_number(self, sample_invoice: Invoice):
        from unittest.mock import MagicMock
        orm = MagicMock()
        orm.items = []
        sample_invoice.ksef_reference_number = "9999909999-20260406-DEF00002-01"
        InvoiceMapper.update_orm(orm, sample_invoice)
        assert orm.ksef_reference_number == "9999909999-20260406-DEF00002-01"

    def test_roundtrip_delivery_date(self, sample_invoice: Invoice):
        """to_orm a potem to_domain zachowuje delivery_date."""
        sample_invoice.delivery_date = date(2026, 3, 31)
        orm = InvoiceMapper.to_orm(sample_invoice)
        # Symulujemy odczyt z bazy — ustawiamy pola ORM recznie
        from unittest.mock import MagicMock
        read_orm = _make_invoice_orm()
        read_orm.delivery_date = orm.delivery_date
        read_orm.ksef_reference_number = orm.ksef_reference_number
        domain2 = InvoiceMapper.to_domain(read_orm)
        assert domain2.delivery_date == date(2026, 3, 31)
