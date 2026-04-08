"""Testy hardeningu KSeF:
1. DB constraints: UNIQUE TransmissionORM.idempotency_key
2. validate_for_ksef() sprawdza status READY_FOR_SUBMISSION
3. validate_vat() sprawdza sumę VAT z pozycji
4. Invoice.aggregate_vat_totals() zwraca poprawne agregaty
5. Invoice.validate_exchange_rate_against_nbp() — porównanie z kursem NBP
6. NbpRateValidator — integracja z klientem NBP (mock)
7. FAILED_TEMPORARY + auto-retry w SubmitInvoiceJobHandler
8. M2M InvoiceAdvanceLinkORM: mapper do_domain/to_orm
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.domain.enums import InvoiceStatus, InvoiceType, TransmissionStatus
from app.domain.exceptions import InvalidInvoiceError
from app.domain.models.invoice import Invoice, InvoiceItem
from app.integrations.ksef.client import KSeFClientError
from app.integrations.ksef.mapper import KSeFMapper
from app.integrations.nbp.client import NbpRateClient, NbpRateError
from app.persistence.mappers.invoice_mapper import InvoiceMapper
from app.persistence.models.invoice_advance_link import InvoiceAdvanceLinkORM
from app.persistence.models.transmission import TransmissionORM
from app.services.nbp_rate_validator import NbpRateValidator
from app.worker.job_handlers.submit_invoice import SubmitInvoiceJobHandler, _MAX_AUTO_RETRY_ATTEMPTS, _backoff_minutes


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_item(
    net_total: str = "100.00",
    vat_total: str = "23.00",
    gross_total: str = "123.00",
    vat_rate: str = "23",
    vat_amount_pln: str | None = None,
    sort_order: int = 1,
) -> InvoiceItem:
    return InvoiceItem(
        name="Usługa",
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
        seller_snapshot={"nip": "1000000035", "name": "Sprzedawca"},
        buyer_snapshot={"nip": "1000000070", "name": "Nabywca"},
        items=[_make_item()],
        total_net=Decimal("100.00"),
        total_vat=Decimal("23.00"),
        total_gross=Decimal("123.00"),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    defaults.update(kwargs)
    return Invoice(**defaults)


def _make_handler() -> SubmitInvoiceJobHandler:
    return SubmitInvoiceJobHandler(
        session=MagicMock(),
        transmission_repository=MagicMock(),
        invoice_repository=MagicMock(),
        job_repository=MagicMock(),
        ksef_client=MagicMock(),
        ksef_session_service=MagicMock(),
    )


# ---------------------------------------------------------------------------
# 1. DB constraints
# ---------------------------------------------------------------------------

class TestTransmissionUniqueConstraint:
    def test_unique_constraint_declared(self):
        """TransmissionORM.__table_args__ zawiera UniqueConstraint na idempotency_key."""
        from sqlalchemy import UniqueConstraint
        args = TransmissionORM.__table_args__
        names = [
            c.name
            for c in args
            if isinstance(c, UniqueConstraint)
        ]
        assert "uq_transmissions_idempotency_key" in names

    def test_idempotency_key_column_unique(self):
        """Kolumna NIE ma unique=True — unikalność zapewnia tylko UniqueConstraint w __table_args__."""
        col = TransmissionORM.__table__.c.idempotency_key
        # Podwójna deklaracja (unique=True + UniqueConstraint) tworzy dwa indeksy.
        # Po naprawie usunięto unique=True z kolumny; pozostał tylko UniqueConstraint.
        assert not col.unique, (
            "unique=True na kolumnie idempotency_key jest duplikowane przez "
            "UniqueConstraint — należy je usunąć."
        )


# ---------------------------------------------------------------------------
# 2. validate_for_ksef() — status check
# ---------------------------------------------------------------------------

class TestValidateForKsefStatusGuard:
    def test_draft_status_raises(self):
        inv = _make_invoice(status=InvoiceStatus.DRAFT)
        with pytest.raises(InvalidInvoiceError, match="ready_for_submission"):
            inv.validate_for_ksef()

    def test_sending_status_raises(self):
        inv = _make_invoice(status=InvoiceStatus.SENDING)
        with pytest.raises(InvalidInvoiceError, match="ready_for_submission"):
            inv.validate_for_ksef()

    def test_ready_status_passes(self):
        inv = _make_invoice(status=InvoiceStatus.READY_FOR_SUBMISSION)
        inv.validate_for_ksef()  # nie rzuca

    def test_accepted_status_raises(self):
        inv = _make_invoice(status=InvoiceStatus.ACCEPTED)
        with pytest.raises(InvalidInvoiceError, match="ready_for_submission"):
            inv.validate_for_ksef()


# ---------------------------------------------------------------------------
# 3. validate_vat() — suma VAT z pozycji
# ---------------------------------------------------------------------------

class TestVatSumValidation:
    def test_items_vat_sum_matches_total_passes(self):
        """Suma VAT z pozycji = total_vat → OK."""
        items = [
            _make_item(vat_total="23.00"),
            _make_item(vat_total="46.00", sort_order=2),
        ]
        inv = _make_invoice(
            items=items,
            total_net=Decimal("200.00"),
            total_vat=Decimal("69.00"),
            total_gross=Decimal("269.00"),
        )
        inv.validate_vat()

    def test_items_vat_sum_wrong_raises(self):
        """Suma VAT z pozycji ≠ total_vat → InvalidInvoiceError."""
        item = InvoiceItem(
            name="X", quantity=Decimal("1"), unit="szt.",
            unit_price_net=Decimal("100"), vat_rate=Decimal("23"),
            net_total=Decimal("100"), vat_total=Decimal("10.00"),  # wrong
            gross_total=Decimal("110"), sort_order=1,
        )
        inv = _make_invoice(
            items=[item],
            total_net=Decimal("100.00"),
            total_vat=Decimal("23.00"),
            total_gross=Decimal("123.00"),
        )
        with pytest.raises(InvalidInvoiceError, match="Suma VAT"):
            inv.validate_vat()

    def test_tolerance_within_one_grosz_per_item(self):
        """Różnica ≤ 0.01 × n_items jest akceptowalna (zaokrąglenia)."""
        # 3 pozycje, łączna różnica 0.02 (≤ 0.03 tolerancji)
        items = [
            InvoiceItem("A", Decimal("1"), "szt.", Decimal("33"), Decimal("23"),
                        Decimal("33"), Decimal("7.59"), Decimal("40.59"), sort_order=1),
            InvoiceItem("B", Decimal("1"), "szt.", Decimal("33"), Decimal("23"),
                        Decimal("33"), Decimal("7.59"), Decimal("40.59"), sort_order=2),
            InvoiceItem("C", Decimal("1"), "szt.", Decimal("34"), Decimal("23"),
                        Decimal("34"), Decimal("7.82"), Decimal("41.82"), sort_order=3),
        ]
        # Suma vat_total z pozycji = 7.59 + 7.59 + 7.82 = 23.00
        inv = _make_invoice(
            items=items,
            total_net=Decimal("100.00"),
            total_vat=Decimal("23.00"),
            total_gross=Decimal("123.00"),
        )
        inv.validate_vat()  # nie rzuca


# ---------------------------------------------------------------------------
# 4. Invoice.aggregate_vat_totals()
# ---------------------------------------------------------------------------

class TestAggregateVatTotals:
    def test_single_rate(self):
        item = _make_item(net_total="100.00", vat_total="23.00", vat_rate="23")
        inv = _make_invoice(items=[item])
        totals = inv.aggregate_vat_totals()

        assert len(totals) == 1
        rate = Decimal("23")
        net, vat, vat_pln = totals[rate]
        assert net == Decimal("100.00")
        assert vat == Decimal("23.00")
        assert vat_pln is None  # brak vat_amount_pln

    def test_multiple_rates_aggregated(self):
        items = [
            _make_item(net_total="100", vat_total="23", vat_rate="23", sort_order=1),
            _make_item(net_total="200", vat_total="16", vat_rate="8", sort_order=2),
            _make_item(net_total="50", vat_total="11.5", vat_rate="23", sort_order=3),
        ]
        inv = _make_invoice(
            items=items,
            total_net=Decimal("350"),
            total_vat=Decimal("50.5"),
            total_gross=Decimal("400.5"),
        )
        totals = inv.aggregate_vat_totals()

        assert Decimal("23") in totals
        assert Decimal("8") in totals
        net23, vat23, _ = totals[Decimal("23")]
        assert net23 == Decimal("150")
        assert vat23 == Decimal("34.5")

    def test_vat_pln_aggregated(self):
        items = [
            _make_item(vat_total="23.00", vat_amount_pln="97.75"),
            _make_item(vat_total="23.00", vat_amount_pln="97.75", sort_order=2),
        ]
        inv = _make_invoice(
            items=items,
            total_net=Decimal("200.00"),
            total_vat=Decimal("46.00"),
            total_gross=Decimal("246.00"),
        )
        totals = inv.aggregate_vat_totals()
        _, _, vat_pln = totals[Decimal("23")]
        assert vat_pln == Decimal("195.50")

    def test_empty_items_returns_empty(self):
        inv = _make_invoice(items=[])
        totals = inv.aggregate_vat_totals()
        assert totals == {}

    def test_mapper_uses_domain_totals(self):
        """FA3Mapper._build_vat_totals korzysta z aggregate_vat_totals."""
        item = _make_item(net_total="500.00", vat_total="115.00",
                          gross_total="615.00", vat_rate="23")
        inv = _make_invoice(
            items=[item],
            total_net=Decimal("500.00"),
            total_vat=Decimal("115.00"),
            total_gross=Decimal("615.00"),
        )
        with patch.object(type(inv), "aggregate_vat_totals",
                          wraps=inv.aggregate_vat_totals) as mock_method:
            KSeFMapper.invoice_to_xml(inv)
            mock_method.assert_called_once()


# ---------------------------------------------------------------------------
# 5. validate_exchange_rate_against_nbp()
# ---------------------------------------------------------------------------

class TestValidateExchangeRateAgainstNbp:
    def test_within_tolerance_passes(self):
        inv = _make_invoice(
            currency="EUR",
            exchange_rate=Decimal("4.2500"),
            exchange_rate_date=date(2026, 4, 4),
            items=[_make_item(vat_amount_pln="97.75")],
        )
        inv.validate_exchange_rate_against_nbp(
            official_rate=Decimal("4.2501"),  # diff = 0.0001 < 0.01
        )

    def test_exceeds_tolerance_raises(self):
        inv = _make_invoice(
            currency="EUR",
            exchange_rate=Decimal("4.2500"),
        )
        with pytest.raises(InvalidInvoiceError, match="kursu NBP"):
            inv.validate_exchange_rate_against_nbp(
                official_rate=Decimal("4.1000"),  # diff = 0.15 > 0.01
            )

    def test_none_exchange_rate_skipped(self):
        inv = _make_invoice()
        inv.validate_exchange_rate_against_nbp(official_rate=Decimal("4.25"))

    def test_custom_tolerance(self):
        inv = _make_invoice(currency="USD", exchange_rate=Decimal("3.80"))
        inv.validate_exchange_rate_against_nbp(
            official_rate=Decimal("3.90"),
            tolerance=Decimal("0.20"),  # duża tolerancja — przechodzi
        )

    def test_exact_tolerance_boundary_passes(self):
        inv = _make_invoice(currency="USD", exchange_rate=Decimal("3.80"))
        inv.validate_exchange_rate_against_nbp(
            official_rate=Decimal("3.81"),  # diff = 0.01 == tolerance → przechodzi
            tolerance=Decimal("0.01"),
        )


# ---------------------------------------------------------------------------
# 6. NbpRateValidator (z mock klientem)
# ---------------------------------------------------------------------------

class TestNbpRateValidator:
    def test_valid_rate_no_error(self):
        nbp_client = MagicMock(spec=NbpRateClient)
        nbp_client.get_mid_rate.return_value = Decimal("4.2500")
        validator = NbpRateValidator(nbp_client=nbp_client, tolerance=Decimal("0.05"))

        inv = _make_invoice(
            currency="EUR",
            exchange_rate=Decimal("4.2500"),
            exchange_rate_date=date(2026, 4, 4),
            items=[_make_item(vat_amount_pln="97.75")],
        )
        validator.validate(inv)  # nie rzuca
        nbp_client.get_mid_rate.assert_called_once_with("EUR", date(2026, 4, 4))

    def test_nbp_api_error_raises_invalid_invoice_error(self):
        nbp_client = MagicMock(spec=NbpRateClient)
        nbp_client.get_mid_rate.side_effect = NbpRateError("connection timeout")
        validator = NbpRateValidator(nbp_client=nbp_client)

        inv = _make_invoice(
            currency="EUR",
            exchange_rate=Decimal("4.25"),
        )
        with pytest.raises(InvalidInvoiceError, match="Nie można pobrać kursu NBP"):
            validator.validate(inv)

    def test_pln_invoice_skipped(self):
        nbp_client = MagicMock(spec=NbpRateClient)
        validator = NbpRateValidator(nbp_client=nbp_client)
        inv = _make_invoice(currency="PLN")
        validator.validate(inv)
        nbp_client.get_mid_rate.assert_not_called()

    def test_no_exchange_rate_skipped(self):
        nbp_client = MagicMock(spec=NbpRateClient)
        validator = NbpRateValidator(nbp_client=nbp_client)
        inv = _make_invoice(exchange_rate=None)
        validator.validate(inv)
        nbp_client.get_mid_rate.assert_not_called()

    def test_rate_out_of_tolerance_raises(self):
        nbp_client = MagicMock(spec=NbpRateClient)
        nbp_client.get_mid_rate.return_value = Decimal("4.0000")
        validator = NbpRateValidator(nbp_client=nbp_client, tolerance=Decimal("0.01"))

        inv = _make_invoice(
            currency="EUR",
            exchange_rate=Decimal("4.5000"),  # diff = 0.50 > 0.01
            exchange_rate_date=date(2026, 4, 4),
        )
        with pytest.raises(InvalidInvoiceError, match="kursu NBP"):
            validator.validate(inv)

    def test_uses_issue_date_when_exchange_rate_date_is_none(self):
        nbp_client = MagicMock(spec=NbpRateClient)
        nbp_client.get_mid_rate.return_value = Decimal("4.25")
        validator = NbpRateValidator(nbp_client=nbp_client)

        inv = _make_invoice(
            currency="EUR",
            exchange_rate=Decimal("4.25"),
            exchange_rate_date=None,
            issue_date=date(2026, 4, 1),
            sale_date=date(2026, 4, 1),
            items=[_make_item(vat_amount_pln="97.75")],
        )
        validator.validate(inv)
        nbp_client.get_mid_rate.assert_called_once_with("EUR", date(2026, 4, 1))


# ---------------------------------------------------------------------------
# 7. FAILED_TEMPORARY + auto-retry
# ---------------------------------------------------------------------------

class TestFailedTemporaryAutoRetry:
    def _make_sending_invoice(self) -> Invoice:
        now = datetime.now(UTC)
        return Invoice(
            id=uuid4(),
            status=InvoiceStatus.SENDING,
            issue_date=date(2026, 4, 6),
            sale_date=date(2026, 4, 6),
            currency="PLN",
            seller_snapshot={"nip": "1000000035", "name": "S"},
            buyer_snapshot={"nip": "1000000070", "name": "B"},
            items=[_make_item()],
            total_net=Decimal("100"),
            total_vat=Decimal("23"),
            total_gross=Decimal("123"),
            created_at=now,
            updated_at=now,
        )

    def test_transient_error_sets_failed_temporary(self):
        handler = _make_handler()
        transmission = MagicMock()
        transmission.attempt_no = 1
        handler._transmission_repo.lock_for_update.return_value = transmission
        handler._invoice_repo.get_by_id.return_value = self._make_sending_invoice()
        handler._ksef_session_service.get_session_token.return_value = "tok"
        handler._ksef_client.send_invoice.side_effect = KSeFClientError(
            "HTTP 503", status_code=503, transient=True
        )

        handler.handle({"transmission_id": str(uuid4()), "invoice_id": str(uuid4())})

        assert transmission.status == TransmissionStatus.FAILED_TEMPORARY

    def test_transient_error_schedules_retry_job(self):
        handler = _make_handler()
        transmission = MagicMock()
        transmission.attempt_no = 1
        handler._transmission_repo.lock_for_update.return_value = transmission
        handler._invoice_repo.get_by_id.return_value = self._make_sending_invoice()
        handler._ksef_session_service.get_session_token.return_value = "tok"
        handler._ksef_client.send_invoice.side_effect = KSeFClientError(
            "HTTP 503", status_code=503, transient=True
        )

        handler.handle({"transmission_id": str(uuid4()), "invoice_id": str(uuid4())})

        handler._job_repo.add.assert_called_once()
        job = handler._job_repo.add.call_args[0][0]
        assert job.job_type == "submit_invoice"

    def test_max_attempts_reached_sets_permanent(self):
        handler = _make_handler()
        transmission = MagicMock()
        transmission.attempt_no = _MAX_AUTO_RETRY_ATTEMPTS  # already at max
        handler._transmission_repo.lock_for_update.return_value = transmission
        handler._invoice_repo.get_by_id.return_value = self._make_sending_invoice()
        handler._ksef_session_service.get_session_token.return_value = "tok"
        handler._ksef_client.send_invoice.side_effect = KSeFClientError(
            "HTTP 500", status_code=500, transient=True
        )

        handler.handle({"transmission_id": str(uuid4()), "invoice_id": str(uuid4())})

        assert transmission.status == TransmissionStatus.FAILED_PERMANENT
        handler._job_repo.add.assert_not_called()

    def test_non_transient_error_sets_permanent(self):
        handler = _make_handler()
        transmission = MagicMock()
        transmission.attempt_no = 1
        handler._transmission_repo.lock_for_update.return_value = transmission
        handler._invoice_repo.get_by_id.return_value = self._make_sending_invoice()
        handler._ksef_session_service.get_session_token.return_value = "tok"
        handler._ksef_client.send_invoice.side_effect = KSeFClientError(
            "HTTP 400", status_code=400, transient=False
        )

        handler.handle({"transmission_id": str(uuid4()), "invoice_id": str(uuid4())})

        assert transmission.status == TransmissionStatus.FAILED_PERMANENT
        handler._job_repo.add.assert_not_called()

    def test_next_retry_at_is_set(self):
        handler = _make_handler()
        transmission = MagicMock()
        transmission.attempt_no = 1
        handler._transmission_repo.lock_for_update.return_value = transmission
        handler._invoice_repo.get_by_id.return_value = self._make_sending_invoice()
        handler._ksef_session_service.get_session_token.return_value = "tok"
        handler._ksef_client.send_invoice.side_effect = KSeFClientError(
            "fail", status_code=500, transient=True
        )

        handler.handle({"transmission_id": str(uuid4()), "invoice_id": str(uuid4())})

        assert transmission.next_retry_at is not None

    def test_failed_temporary_in_enum(self):
        assert TransmissionStatus.FAILED_TEMPORARY == "failed_temporary"

    def test_backoff_grows_exponentially(self):
        assert _backoff_minutes(1) == 1
        assert _backoff_minutes(2) == 2
        assert _backoff_minutes(3) == 4
        assert _backoff_minutes(4) == 8
        assert _backoff_minutes(5) == 16
        # Nie przekracza 16 minut
        assert _backoff_minutes(10) == 16


# ---------------------------------------------------------------------------
# 8. M2M: InvoiceAdvanceLinkORM + InvoiceMapper
# ---------------------------------------------------------------------------

class TestInvoiceAdvanceLinkORM:
    def test_tablename(self):
        assert InvoiceAdvanceLinkORM.__tablename__ == "invoice_advance_links"

    def test_primary_key_columns(self):
        pk_cols = {c.name for c in InvoiceAdvanceLinkORM.__table__.primary_key}
        assert pk_cols == {"invoice_id", "advance_invoice_id"}

    def test_fk_to_invoices(self):
        fks = {fk.column.table.name for fk in InvoiceAdvanceLinkORM.__table__.foreign_keys}
        assert fks == {"invoices"}


class TestInvoiceMapperAdvanceLinks:
    def _orm_with_links(self, advance_ids: list) -> MagicMock:
        """Zwraca mock InvoiceORM z przypisanymi linkami zaliczkowymi."""
        orm = MagicMock()
        orm.id = uuid4()
        orm.number_local = None
        orm.status = "ready_for_submission"
        orm.issue_date = date(2026, 4, 6)
        orm.sale_date = date(2026, 4, 6)
        orm.currency = "PLN"
        orm.seller_snapshot_json = {"nip": "1234567890"}
        orm.buyer_snapshot_json = {"nip": "9876543210"}
        orm.totals_json = {"total_net": "100", "total_vat": "23", "total_gross": "123"}
        orm.created_by = None
        orm.created_at = datetime.now(UTC)
        orm.updated_at = datetime.now(UTC)
        orm.items = []
        orm.payment_status = "unpaid"
        orm.delivery_date = None
        orm.ksef_reference_number = None
        orm.invoice_type = "ROZ"
        orm.correction_of_invoice_id = None
        orm.correction_of_ksef_number = None
        orm.correction_reason = None
        orm.correction_type = None
        orm.use_split_payment = False
        orm.self_billing = False
        orm.reverse_charge = False
        orm.reverse_charge_art = False
        orm.reverse_charge_flag = False
        orm.cash_accounting_method = False
        orm.exchange_rate = None
        orm.exchange_rate_date = None
        orm.advance_amount = None
        # M2M links
        links = []
        for aid in advance_ids:
            link = MagicMock(spec=InvoiceAdvanceLinkORM)
            link.advance_invoice_id = aid
            links.append(link)
        orm.advance_links = links
        return orm

    def test_to_domain_reads_advance_links(self):
        ids = [uuid4(), uuid4()]
        orm = self._orm_with_links(ids)
        domain = InvoiceMapper.to_domain(orm)
        assert domain.settled_advance_ids == ids

    def test_to_domain_empty_links(self):
        orm = self._orm_with_links([])
        domain = InvoiceMapper.to_domain(orm)
        assert domain.settled_advance_ids == []

    def test_to_orm_creates_links(self):
        ids = [uuid4(), uuid4()]
        inv = _make_invoice(
            invoice_type=InvoiceType.ROZ,
            settled_advance_ids=ids,
        )
        orm = InvoiceMapper.to_orm(inv)
        assert len(orm.advance_links) == 2
        link_ids = {link.advance_invoice_id for link in orm.advance_links}
        assert link_ids == set(ids)

    def test_to_orm_advance_links_have_correct_invoice_id(self):
        inv_id = uuid4()
        ids = [uuid4()]
        inv = _make_invoice(id=inv_id, invoice_type=InvoiceType.ROZ, settled_advance_ids=ids)
        orm = InvoiceMapper.to_orm(inv)
        assert orm.advance_links[0].invoice_id == inv_id

    def test_update_orm_sets_advance_links(self):
        ids = [uuid4()]
        orm = MagicMock()
        orm.items = []
        orm.advance_links = []
        inv = _make_invoice(
            invoice_type=InvoiceType.ROZ,
            settled_advance_ids=ids,
        )
        InvoiceMapper.update_orm(orm, inv)
        assert len(orm.advance_links) == 1
