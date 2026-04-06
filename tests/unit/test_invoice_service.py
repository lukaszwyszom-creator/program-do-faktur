"""Testy InvoiceService — unit (mocki repozytoriów)."""
from __future__ import annotations

from datetime import date, datetime, UTC
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.core.exceptions import NotFoundError
from app.core.security import AuthenticatedUser
from app.domain.enums import InvoiceStatus
from app.domain.exceptions import InvalidInvoiceError, InvalidStatusTransitionError
from app.domain.models.invoice import Invoice, InvoiceItem
from app.services.invoice_service import InvoiceService


@pytest.fixture()
def service(mock_session: MagicMock) -> InvoiceService:
    return InvoiceService(
        session=mock_session,
        invoice_repository=MagicMock(),
        contractor_repository=MagicMock(),
        contractor_override_repository=MagicMock(),
        audit_service=MagicMock(),
    )


def _valid_create_data(buyer_id=None) -> dict:
    return {
        "buyer_id": buyer_id or uuid4(),
        "issue_date": date(2026, 4, 5),
        "sale_date": date(2026, 4, 5),
        "currency": "PLN",
        "items": [
            {
                "name": "Usługa",
                "quantity": "10",
                "unit": "godz.",
                "unit_price_net": "200.00",
                "vat_rate": "23",
            }
        ],
    }


class TestCreateInvoice:
    def test_missing_buyer_id_raises(self, service: InvoiceService, actor: AuthenticatedUser):
        data = _valid_create_data()
        data["buyer_id"] = None
        with pytest.raises(InvalidInvoiceError, match="buyer_id"):
            service.create_invoice(data, actor)

    def test_empty_items_raises(self, service: InvoiceService, actor: AuthenticatedUser):
        data = _valid_create_data()
        data["items"] = []
        with pytest.raises(InvalidInvoiceError, match="co najmniej jedną pozycję"):
            service.create_invoice(data, actor)

    def test_sale_date_after_issue_date_raises(self, service: InvoiceService, actor: AuthenticatedUser):
        data = _valid_create_data()
        data["issue_date"] = date(2026, 4, 1)
        data["sale_date"] = date(2026, 4, 5)
        with pytest.raises(InvalidInvoiceError, match="Data sprzedaży"):
            service.create_invoice(data, actor)

    @patch("app.services.invoice_service.settings")
    def test_create_success(self, mock_settings, service: InvoiceService, actor: AuthenticatedUser):
        mock_settings.seller_nip = "1234567890"
        mock_settings.seller_name = "Firma"
        mock_settings.seller_street = "ul. Testowa"
        mock_settings.seller_building_no = "1"
        mock_settings.seller_apartment_no = None
        mock_settings.seller_postal_code = "00-001"
        mock_settings.seller_city = "Warszawa"
        mock_settings.seller_country = "PL"

        buyer_id = uuid4()
        data = _valid_create_data(buyer_id)

        # Mock contractor repo
        contractor_mock = MagicMock()
        contractor_mock.nip = "0987654321"
        contractor_mock.name = "Nabywca"
        service.contractor_repository.get_by_id.return_value = contractor_mock
        service.contractor_override_repository.get_active_by_contractor_id.return_value = None

        # Mock invoice repo
        now = datetime.now(UTC)
        expected = Invoice(
            id=uuid4(),
            status=InvoiceStatus.DRAFT,
            issue_date=data["issue_date"],
            sale_date=data["sale_date"],
            currency="PLN",
            seller_snapshot={},
            buyer_snapshot={},
            items=[],
            total_net=Decimal("2000.00"),
            total_vat=Decimal("460.00"),
            total_gross=Decimal("2460.00"),
            created_at=now,
            updated_at=now,
        )
        service.invoice_repository.add.return_value = expected

        result = service.create_invoice(data, actor)

        assert result == expected
        service.invoice_repository.add.assert_called_once()
        service.audit_service.record.assert_called_once()

    def test_item_negative_quantity_raises(self, service: InvoiceService, actor: AuthenticatedUser):
        data = _valid_create_data()
        data["items"][0]["quantity"] = "-1"

        # Need contractor mock for _resolve_buyer_snapshot
        service.contractor_repository.get_by_id.return_value = MagicMock()
        service.contractor_override_repository.get_active_by_contractor_id.return_value = None

        with pytest.raises(InvalidInvoiceError, match="ilość"):
            with patch("app.services.invoice_service.settings") as mock_s:
                mock_s.seller_nip = "1234567890"
                mock_s.seller_name = "F"
                mock_s.seller_street = "S"
                mock_s.seller_building_no = "1"
                mock_s.seller_apartment_no = None
                mock_s.seller_postal_code = "00-001"
                mock_s.seller_city = "W"
                mock_s.seller_country = "PL"
                service.create_invoice(data, actor)

    def test_item_empty_name_raises(self, service: InvoiceService, actor: AuthenticatedUser):
        data = _valid_create_data()
        data["items"][0]["name"] = "   "

        service.contractor_repository.get_by_id.return_value = MagicMock()
        service.contractor_override_repository.get_active_by_contractor_id.return_value = None

        with pytest.raises(InvalidInvoiceError, match="nazwa"):
            with patch("app.services.invoice_service.settings") as mock_s:
                mock_s.seller_nip = "X"
                mock_s.seller_name = "F"
                mock_s.seller_street = "S"
                mock_s.seller_building_no = "1"
                mock_s.seller_apartment_no = None
                mock_s.seller_postal_code = "00-001"
                mock_s.seller_city = "W"
                mock_s.seller_country = "PL"
                service.create_invoice(data, actor)

    def test_item_vat_over_100_raises(self, service: InvoiceService, actor: AuthenticatedUser):
        data = _valid_create_data()
        data["items"][0]["vat_rate"] = "101"

        service.contractor_repository.get_by_id.return_value = MagicMock()
        service.contractor_override_repository.get_active_by_contractor_id.return_value = None

        with pytest.raises(InvalidInvoiceError, match="VAT"):
            with patch("app.services.invoice_service.settings") as mock_s:
                mock_s.seller_nip = "X"
                mock_s.seller_name = "F"
                mock_s.seller_street = "S"
                mock_s.seller_building_no = "1"
                mock_s.seller_apartment_no = None
                mock_s.seller_postal_code = "00-001"
                mock_s.seller_city = "W"
                mock_s.seller_country = "PL"
                service.create_invoice(data, actor)


class TestGetInvoice:
    def test_found(self, service: InvoiceService, sample_invoice: Invoice):
        service.invoice_repository.get_by_id.return_value = sample_invoice
        result = service.get_invoice(sample_invoice.id)
        assert result.id == sample_invoice.id

    def test_not_found_raises(self, service: InvoiceService):
        service.invoice_repository.get_by_id.return_value = None
        with pytest.raises(NotFoundError):
            service.get_invoice(uuid4())


class TestListInvoices:
    def test_returns_tuple(self, service: InvoiceService, sample_invoice: Invoice):
        service.invoice_repository.list_paginated.return_value = ([sample_invoice], 1)
        items, total = service.list_invoices(page=1, size=20)
        assert total == 1
        assert len(items) == 1


class TestMarkAsReady:
    def test_invalid_transition_raises(self, service: InvoiceService, actor: AuthenticatedUser):
        invoice = MagicMock()
        invoice.can_transition_to.return_value = False
        invoice.status = MagicMock()
        invoice.status.value = "accepted"
        service.invoice_repository.lock_for_update.return_value = invoice

        with pytest.raises(InvalidStatusTransitionError):
            service.mark_as_ready(uuid4(), actor)

    def test_success(self, service: InvoiceService, actor: AuthenticatedUser, sample_invoice: Invoice):
        sample_invoice.status = InvoiceStatus.DRAFT
        service.invoice_repository.lock_for_update.return_value = sample_invoice
        service.invoice_repository.get_next_sequence_number.return_value = 1
        service.invoice_repository.exists_by_number.return_value = False

        updated = Invoice(
            id=sample_invoice.id,
            status=InvoiceStatus.READY_FOR_SUBMISSION,
            issue_date=sample_invoice.issue_date,
            sale_date=sample_invoice.sale_date,
            currency="PLN",
            seller_snapshot={},
            buyer_snapshot={},
            items=[],
            total_net=Decimal("0"),
            total_vat=Decimal("0"),
            total_gross=Decimal("0"),
            created_at=sample_invoice.created_at,
            updated_at=sample_invoice.updated_at,
            number_local="FV/1/04/2026",
        )
        service.invoice_repository.update.return_value = updated

        result = service.mark_as_ready(sample_invoice.id, actor)
        assert result.status == InvoiceStatus.READY_FOR_SUBMISSION
        assert result.number_local == "FV/1/04/2026"
