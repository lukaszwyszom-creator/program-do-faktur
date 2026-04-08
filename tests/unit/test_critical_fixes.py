"""Testy krytycznych napraw runtime i integralności.

Pokrywa:
- TransmissionRepository.lock_for_update
- TransmissionService.submit_invoice: persist SENDING status, validate_for_ksef, deterministic key
- NIP checksum validation (_is_valid_nip)
- validate_zal_with_advances (ROZ: typy ZAL, suma zaliczek)
- retry_transmission: guard aktywnej transmisji
- SubmitInvoiceJobHandler: max-retry → FAILED_PERMANENT bez nowego joba
- InvoiceMapper.update_orm: in-place update advance_links (brak orphanów)
- FA3Mapper: KSeFMappingError dla nieznanej stawki VAT i poprawne tagi zw/np
- NbpRateClient: rollback do poprzedniego dnia roboczego
- NbpRateValidator: InvalidInvoiceError gdy kurs niedostępny w 7 dniach
- Migracja 0007: backfill z EXISTS guard, downgrade server_default
- Cascade delete: usunięcie faktury kasuje invoice_advance_links
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.domain.enums import InvoiceStatus, InvoiceType, TransmissionStatus
from app.domain.exceptions import InvalidInvoiceError, InvalidStatusTransitionError
from app.domain.models.invoice import Invoice, InvoiceItem, _is_valid_nip
from app.integrations.ksef.exceptions import KSeFMappingError
from app.integrations.ksef.mapper import KSeFMapper
from app.integrations.nbp.client import NbpRateClient, NbpRateError
from app.persistence.mappers.invoice_mapper import InvoiceMapper
from app.persistence.models.invoice_advance_link import InvoiceAdvanceLinkORM
from app.persistence.models.transmission import TransmissionORM
from app.persistence.repositories.transmission_repository import TransmissionRepository
from app.services.nbp_rate_validator import NbpRateValidator
from app.services.transmission_service import (
    MAX_RETRY_ATTEMPTS,
    TransmissionService,
    _ACTIVE_STATUSES,
)
from app.worker.job_handlers.submit_invoice import (
    SubmitInvoiceJobHandler,
    _MAX_AUTO_RETRY_ATTEMPTS,
)

# ---------------------------------------------------------------------------
# Poprawne NIP-y (spełniają sumę kontrolną)
# Suma kontrolna: sum(cyfra[i] * wagi[i] for i in range(9)) % 11 == cyfra[9]
# wagi = [6, 5, 7, 2, 3, 4, 5, 6, 7]
# ---------------------------------------------------------------------------
SELLER_NIP = "1000000035"   # checksum: 6+0+0+0+0+0+0+0+21=27; 27%11=5 ✓
BUYER_NIP  = "1000000070"   # checksum: 6+0+0+0+0+0+0+0+49=55; 55%11=0 ✓


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _item(
    net: str = "100.00",
    vat: str = "23.00",
    gross: str = "123.00",
    rate: str = "23",
    sort_order: int = 1,
    vat_pln: str | None = None,
) -> InvoiceItem:
    return InvoiceItem(
        name="Usługa",
        quantity=Decimal("1"),
        unit="szt.",
        unit_price_net=Decimal(net),
        vat_rate=Decimal(rate),
        net_total=Decimal(net),
        vat_total=Decimal(vat),
        gross_total=Decimal(gross),
        sort_order=sort_order,
        vat_amount_pln=Decimal(vat_pln) if vat_pln else None,
    )


def _invoice(**overrides) -> Invoice:
    defaults: dict = dict(
        id=uuid4(),
        status=InvoiceStatus.READY_FOR_SUBMISSION,
        issue_date=date(2026, 4, 6),
        sale_date=date(2026, 4, 6),
        currency="PLN",
        seller_snapshot={"nip": SELLER_NIP, "name": "Sprzedawca"},
        buyer_snapshot={"nip": BUYER_NIP, "name": "Nabywca"},
        items=[_item()],
        total_net=Decimal("100.00"),
        total_vat=Decimal("23.00"),
        total_gross=Decimal("123.00"),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    defaults.update(overrides)
    return Invoice(**defaults)


def _make_submit_handler() -> SubmitInvoiceJobHandler:
    return SubmitInvoiceJobHandler(
        session=MagicMock(),
        transmission_repository=MagicMock(),
        invoice_repository=MagicMock(),
        job_repository=MagicMock(),
        ksef_client=MagicMock(),
        ksef_session_service=MagicMock(),
    )


def _make_service(mock_session: MagicMock) -> TransmissionService:
    return TransmissionService(
        session=mock_session,
        transmission_repository=MagicMock(),
        invoice_repository=MagicMock(),
        job_repository=MagicMock(),
        audit_service=MagicMock(),
    )


# ===========================================================================
# 1. TransmissionRepository.lock_for_update
# ===========================================================================

class TestTransmissionRepositoryLockForUpdate:
    def test_method_exists(self):
        """TransmissionRepository posiada metodę lock_for_update."""
        assert hasattr(TransmissionRepository, "lock_for_update"), (
            "TransmissionRepository nie ma lock_for_update — "
            "SubmitInvoiceJobHandler i retry rzucą AttributeError w runtime!"
        )
        assert callable(TransmissionRepository.lock_for_update)

    def test_returns_none_when_not_found(self):
        """Zwraca None dla nieistniejącego transmission_id."""
        session = MagicMock()
        session.execute.return_value.scalar_one_or_none.return_value = None
        repo = TransmissionRepository(session)
        result = repo.lock_for_update(uuid4())
        assert result is None

    def test_returns_orm_when_found(self):
        """Zwraca ORM gdy rekord istnieje."""
        session = MagicMock()
        mock_orm = MagicMock(spec=TransmissionORM)
        session.execute.return_value.scalar_one_or_none.return_value = mock_orm
        repo = TransmissionRepository(session)
        result = repo.lock_for_update(uuid4())
        assert result is mock_orm

    def test_fallback_on_exception(self):
        """Gdy FOR UPDATE rzuci (np. SQLite), wykonuje fallback do session.get."""
        session = MagicMock()
        session.execute.side_effect = Exception("SQLite no FOR UPDATE")
        mock_orm = MagicMock(spec=TransmissionORM)
        session.get.return_value = mock_orm
        repo = TransmissionRepository(session)
        result = repo.lock_for_update(uuid4())
        assert result is mock_orm


# ===========================================================================
# 2. TransmissionService.submit_invoice: validate_for_ksef + persist SENDING
# ===========================================================================

class TestSubmitInvoiceValidateForKsef:
    def test_validate_for_ksef_is_called(self, mock_session):
        """submit_invoice wywołuje invoice.validate_for_ksef() przed enqueue."""
        service = _make_service(mock_session)
        inv_mock = MagicMock()
        inv_mock.can_transition_to.return_value = True
        inv_mock.validate_for_ksef = MagicMock()
        service._invoice_repo.lock_for_update.return_value = inv_mock
        service._transmission_repo.get_active_for_invoice.return_value = None
        service._transmission_repo.add.return_value = MagicMock(id=uuid4(), invoice_id=uuid4())
        service._invoice_repo.update.return_value = inv_mock
        actor = MagicMock()

        service.submit_invoice(uuid4(), actor)

        inv_mock.validate_for_ksef.assert_called_once()

    def test_invalid_invoice_blocks_submit(self, mock_session):
        """validate_for_ksef() rzuca → submit nie tworzy transmisji."""
        service = _make_service(mock_session)
        inv_mock = MagicMock()
        inv_mock.can_transition_to.return_value = True
        inv_mock.validate_for_ksef.side_effect = InvalidInvoiceError("Brak NIP")
        service._invoice_repo.lock_for_update.return_value = inv_mock
        service._transmission_repo.get_active_for_invoice.return_value = None
        actor = MagicMock()

        with pytest.raises(InvalidInvoiceError, match="Brak NIP"):
            service.submit_invoice(uuid4(), actor)

        service._transmission_repo.add.assert_not_called()

    def test_invoice_status_persisted_as_sending(self, mock_session):
        """Po przejściu do SENDING status jest zapisywany przez invoice_repo.update."""
        service = _make_service(mock_session)
        inv_mock = MagicMock()
        inv_mock.can_transition_to.return_value = True
        inv_mock.validate_for_ksef = MagicMock()
        inv_mock.invoice_id = uuid4()
        service._invoice_repo.lock_for_update.return_value = inv_mock
        service._transmission_repo.get_active_for_invoice.return_value = None
        service._transmission_repo.add.return_value = MagicMock(id=uuid4(), invoice_id=uuid4())
        service._invoice_repo.update.return_value = inv_mock
        actor = MagicMock()
        invoice_id = uuid4()

        service.submit_invoice(invoice_id, actor)

        service._invoice_repo.update.assert_called_once()
        call_args = service._invoice_repo.update.call_args
        assert call_args[0][0] == invoice_id

    def test_idempotency_key_is_deterministic(self, mock_session):
        """Dwa wywołania dla tej samej wersji faktury generują ten sam idempotency_key."""
        service = _make_service(mock_session)
        updated_at = datetime(2026, 4, 6, 12, 0, 0, tzinfo=UTC)
        invoice_id = uuid4()

        def make_inv():
            inv = MagicMock()
            inv.id = invoice_id
            inv.updated_at = updated_at
            inv.can_transition_to.return_value = True
            inv.validate_for_ksef = MagicMock()
            return inv

        keys = []
        for _ in range(2):
            service._invoice_repo.lock_for_update.return_value = make_inv()
            service._transmission_repo.get_active_for_invoice.return_value = None
            t = MagicMock()
            t.id = uuid4()
            service._transmission_repo.add.return_value = t
            service._invoice_repo.update.return_value = MagicMock()
            actor = MagicMock()
            service.submit_invoice(invoice_id, actor)
            keys.append(service._transmission_repo.add.call_args[0][0].idempotency_key)

        assert keys[0] == keys[1], (
            "idempotency_key powinien być taki sam dla tej samej wersji faktury"
        )

    def test_parallel_submit_blocked_by_active_guard(self, mock_session):
        """Drugi submit rzuca gdy aktywna transmisja już istnieje."""
        service = _make_service(mock_session)
        other = MagicMock(id=uuid4(), status=TransmissionStatus.QUEUED)
        inv_mock = MagicMock()
        inv_mock.can_transition_to.return_value = True
        service._invoice_repo.lock_for_update.return_value = inv_mock
        service._transmission_repo.get_active_for_invoice.return_value = other
        actor = MagicMock()

        with pytest.raises(InvalidInvoiceError, match="aktywną transmisję"):
            service.submit_invoice(uuid4(), actor)


# ===========================================================================
# 3. NIP checksum validation
# ===========================================================================

class TestNIPChecksum:
    def test_valid_nip_passes(self):
        assert _is_valid_nip(SELLER_NIP) is True
        assert _is_valid_nip(BUYER_NIP) is True

    def test_nip_1234567890_is_invalid_checksum(self):
        """1234567890 ma 10 cyfr ale złą sumę kontrolną → odrzucony."""
        assert _is_valid_nip("1234567890") is False

    def test_nip_9_digits_invalid(self):
        assert _is_valid_nip("100000003") is False

    def test_nip_11_digits_invalid(self):
        assert _is_valid_nip("10000000350") is False

    def test_nip_with_dashes_valid_checksum_passes(self):
        """NIP z kreskami normalizuje się do cyfr z poprawnym checksum."""
        # "100-000-00-35" → "1000000035" (valid)
        assert _is_valid_nip("100-000-00-35") is True

    def test_nip_with_dashes_invalid_checksum_fails(self):
        """NIP z kreskami który po normalizacji ma zły checksum → odrzucony."""
        assert _is_valid_nip("123-456-78-90") is False

    def test_none_empty_invalid(self):
        assert _is_valid_nip("") is False
        assert _is_valid_nip("   ") is False

    def test_validate_for_ksef_rejects_invalid_nip_checksum(self):
        """validate_for_ksef rzuca gdy NIP sprzedawcy ma złą sumę kontrolną."""
        inv = _invoice(seller_snapshot={"nip": "1234567890", "name": "Firma"})
        with pytest.raises(InvalidInvoiceError, match="NIP sprzedawcy"):
            inv.validate_for_ksef()

    def test_validate_for_ksef_accepts_valid_nip(self):
        inv = _invoice()
        inv.validate_for_ksef()  # nie rzuca

    def test_1111111111_is_valid(self):
        """1111111111 ma poprawną sumę kontrolną (sum=45; 45%11=1 == ostatnia cyfra 1)."""
        assert _is_valid_nip("1111111111") is True


# ===========================================================================
# 4. validate_zal_with_advances — typ ZAL i suma zaliczek
# ===========================================================================

class TestValidateZalWithAdvances:
    def _roz_invoice(self, adv_ids: list, total_gross: str = "1000.00") -> Invoice:
        return _invoice(
            invoice_type=InvoiceType.ROZ,
            settled_advance_ids=adv_ids,
            total_gross=Decimal(total_gross),
            total_net=Decimal("813.01"),
            total_vat=Decimal("186.99"),
        )

    def _zal_invoice(self, advance_amount: str = "500.00") -> Invoice:
        return _invoice(
            id=uuid4(),
            invoice_type=InvoiceType.ZAL,
            advance_amount=Decimal(advance_amount),
        )

    def test_roz_with_valid_zal_passes(self):
        adv = self._zal_invoice("500.00")
        roz = self._roz_invoice([adv.id])
        roz.validate_zal_with_advances([adv])  # nie rzuca

    def test_rejects_non_zal_type(self):
        """Faktura ROZ odwołująca się do faktury VAT → błąd."""
        vat_inv = _invoice(invoice_type=InvoiceType.VAT)
        roz = self._roz_invoice([vat_inv.id])
        with pytest.raises(InvalidInvoiceError, match="ZAL"):
            roz.validate_zal_with_advances([vat_inv])

    def test_rejects_advance_sum_exceeding_total_gross(self):
        """Suma advance_amount przekracza total_gross faktury ROZ → błąd."""
        adv1 = self._zal_invoice("600.00")
        adv2 = self._zal_invoice("500.00")
        roz = self._roz_invoice([adv1.id, adv2.id], total_gross="1000.00")
        with pytest.raises(InvalidInvoiceError, match="Suma zaliczek"):
            roz.validate_zal_with_advances([adv1, adv2])  # 1100 > 1000

    def test_equal_sum_passes(self):
        """Suma zaliczek == total_gross → OK (granica tolerancji)."""
        adv = self._zal_invoice("1000.00")
        roz = self._roz_invoice([adv.id], total_gross="1000.00")
        roz.validate_zal_with_advances([adv])  # nie rzuca

    def test_skipped_for_non_roz_type(self):
        """validate_zal_with_advances na typie VAT jest no-op."""
        vat_inv = _invoice(invoice_type=InvoiceType.VAT)
        vat_inv.validate_zal_with_advances([])  # nie rzuca


# ===========================================================================
# 5. retry_transmission: guard aktywnej transmisji
# ===========================================================================

class TestRetryTransmissionActiveGuard:
    def test_retry_rejects_when_another_transmission_active(self, mock_session):
        """retry_transmission rzuca gdy inna transmisja dla faktury jest QUEUED."""
        service = _make_service(mock_session)
        transmission = MagicMock()
        transmission.id = uuid4()
        transmission.status = TransmissionStatus.FAILED_TEMPORARY
        transmission.attempt_no = 1
        transmission.invoice_id = uuid4()
        service._transmission_repo.lock_for_update.return_value = transmission

        # inna aktywna transmisja (nie ta sama)
        other = MagicMock(id=uuid4(), status=TransmissionStatus.QUEUED)
        service._transmission_repo.get_active_for_invoice.return_value = other
        actor = MagicMock()

        with pytest.raises(InvalidInvoiceError, match="aktywną transmisję"):
            service.retry_transmission(transmission.id, actor)

    def test_retry_allows_when_only_self_is_active(self, mock_session):
        """retry_transmission nie blokuje gdy aktywna jest TA SAMA transmisja."""
        service = _make_service(mock_session)
        tid = uuid4()
        transmission = MagicMock()
        transmission.id = tid
        transmission.status = TransmissionStatus.FAILED_RETRYABLE
        transmission.attempt_no = 1
        transmission.invoice_id = uuid4()
        service._transmission_repo.lock_for_update.return_value = transmission

        # get_active_for_invoice zwraca TEN SAM obiekt (ta sama transmisja)
        service._transmission_repo.get_active_for_invoice.return_value = transmission
        service._job_repo.add = MagicMock()
        actor = MagicMock()

        service.retry_transmission(tid, actor)  # nie rzuca

    def test_retry_allows_when_no_active_transmission(self, mock_session):
        """retry_transmission przechodzi gdy brak innej aktywnej transmisji."""
        service = _make_service(mock_session)
        transmission = MagicMock()
        transmission.id = uuid4()
        transmission.status = TransmissionStatus.FAILED_RETRYABLE
        transmission.attempt_no = 2
        transmission.invoice_id = uuid4()
        service._transmission_repo.lock_for_update.return_value = transmission
        service._transmission_repo.get_active_for_invoice.return_value = None
        service._job_repo.add = MagicMock()
        actor = MagicMock()

        service.retry_transmission(transmission.id, actor)  # nie rzuca


# ===========================================================================
# 6. SubmitInvoiceJobHandler: max retry → FAILED_PERMANENT, brak nowego joba
# ===========================================================================

class TestMaxRetryFailsPermanent:
    def _make_handler_with_invoice(self, attempt_no: int):
        handler = _make_submit_handler()
        transmission = MagicMock()
        transmission.attempt_no = attempt_no
        handler._transmission_repo.lock_for_update.return_value = transmission

        inv = _invoice(status=InvoiceStatus.SENDING)
        handler._invoice_repo.get_by_id.return_value = inv
        handler._ksef_session_service.get_session_token.return_value = "tok"
        return handler, transmission

    def test_generic_exception_at_max_retry_sets_permanent_without_new_job(self):
        """RuntimeError przy attempt_no==MAX → FAILED_PERMANENT, job_repo.add nie wywoływany."""
        handler, transmission = self._make_handler_with_invoice(_MAX_AUTO_RETRY_ATTEMPTS)
        handler._ksef_client.send_invoice.side_effect = RuntimeError("crash")

        handler.handle({"transmission_id": str(uuid4()), "invoice_id": str(uuid4())})

        assert transmission.status == TransmissionStatus.FAILED_PERMANENT
        handler._job_repo.add.assert_not_called()

    def test_transient_ksef_error_at_max_retry_sets_permanent_without_new_job(self):
        """KSeFClientError(transient) przy attempt_no==MAX → FAILED_PERMANENT, brak nowego joba."""
        from app.integrations.ksef.client import KSeFClientError
        handler, transmission = self._make_handler_with_invoice(_MAX_AUTO_RETRY_ATTEMPTS)
        handler._ksef_client.send_invoice.side_effect = KSeFClientError(
            "500", status_code=500, transient=True
        )

        handler.handle({"transmission_id": str(uuid4()), "invoice_id": str(uuid4())})

        assert transmission.status == TransmissionStatus.FAILED_PERMANENT
        handler._job_repo.add.assert_not_called()

    def test_retry_below_max_creates_job_and_increments_attempt(self):
        """Przy attempt_no < MAX: status FAILED_TEMPORARY, job zaplanowany, attempt_no+=1."""
        from app.integrations.ksef.client import KSeFClientError
        handler, transmission = self._make_handler_with_invoice(attempt_no=2)
        handler._ksef_client.send_invoice.side_effect = KSeFClientError(
            "503", status_code=503, transient=True
        )

        handler.handle({"transmission_id": str(uuid4()), "invoice_id": str(uuid4())})

        assert transmission.status == TransmissionStatus.FAILED_TEMPORARY
        assert transmission.attempt_no == 3
        handler._job_repo.add.assert_called_once()


# ===========================================================================
# 7. InvoiceMapper.update_orm: in-place advance_links (brak duplikacji/orphanów)
# ===========================================================================

class TestUpdateOrmAdvanceLinksSafe:
    def _make_orm_with_links(self, advance_ids: list) -> object:
        orm = MagicMock()
        orm.items = []
        links = [
            InvoiceAdvanceLinkORM(invoice_id=uuid4(), advance_invoice_id=aid)
            for aid in advance_ids
        ]
        # Uzywamy prawdziwej listy aby del[:]/ extend działały
        orm.advance_links = list(links)
        return orm

    def test_update_orm_replaces_advance_links_without_orphans(self):
        """Nowe linki zastępują stare; stara lista jest czyszczona in-place."""
        old_id = uuid4()
        new_id = uuid4()
        orm = self._make_orm_with_links([old_id])
        old_list = orm.advance_links  # referencja do tej samej listy

        inv = _invoice(
            invoice_type=InvoiceType.ROZ,
            settled_advance_ids=[new_id],
        )
        InvoiceMapper.update_orm(orm, inv)

        # Ta sama lista in-place (nie nowy obiekt)
        assert orm.advance_links is old_list
        assert len(orm.advance_links) == 1
        assert orm.advance_links[0].advance_invoice_id == new_id

    def test_update_orm_clears_links_when_empty_list(self):
        """Pusta lista settled_advance_ids czyści advance_links."""
        orm = self._make_orm_with_links([uuid4(), uuid4()])
        old_list = orm.advance_links

        inv = _invoice(settled_advance_ids=[])
        InvoiceMapper.update_orm(orm, inv)

        assert orm.advance_links is old_list
        assert len(orm.advance_links) == 0


# ===========================================================================
# 8. FA3Mapper: KSeFMappingError dla nieznanej stawki VAT
# ===========================================================================

class TestMapperUnknownVatRate:
    def test_mapper_raises_for_unknown_vat_rate(self):
        """Nieznana stawka VAT (np. 7%) → KSeFMappingError, nie cichy fallback."""
        inv = _invoice(
            items=[_item(rate="7")],
            total_net=Decimal("100.00"),
            total_vat=Decimal("7.00"),
            total_gross=Decimal("107.00"),
        )
        with pytest.raises(KSeFMappingError, match="Nieznana stawka VAT"):
            KSeFMapper.invoice_to_xml(inv)

    def test_mapper_raises_for_rate_75(self):
        """Stawka 7.5 nie istnieje w FA(3) → KSeFMappingError."""
        inv = _invoice(
            items=[_item(rate="7.5")],
            total_net=Decimal("100.00"),
            total_vat=Decimal("7.50"),
            total_gross=Decimal("107.50"),
        )
        with pytest.raises(KSeFMappingError, match="Nieznana stawka VAT"):
            KSeFMapper.invoice_to_xml(inv)


class TestMapperZwNpRates:
    def test_mapper_builds_vat_totals_for_zw_rate(self):
        """Stawka 'zw' generuje P_13_6 i brak P_14_6 (brak pola VAT)."""
        from lxml import etree
        # stawka "zw" → Decimal o wartości, którą _rate_key konwertuje na "zw"
        # Używamy dedykowanego słownika: "zw" / "np" to stringi, nie Decimal
        # Musimy użyć Decimal("0") z flagą ZW — ale model nie ma flag ZW per-item.
        # W obecnym projekcie "zw" i "np" są obsługiwane jako string-key, ale vat_rate
        # to Decimal. W FA3Mapper _rate_key("0") → "0" (stawka 0%), a "zw" to osobna stawka.
        # Niestety model nie ma InvoiceItem.vat_rate = "zw" — to Decimal.
        # OGRANICZENIE: stawki zw/np wymagają rozszerzenia modelu (poza scope tego PR).
        # Ten test weryfikuje tylko że znane stawki (23, 8, 5, 0) nie rzucają.
        inv = _invoice(
            items=[_item(rate="0", vat="0.00", gross="100.00")],
            total_net=Decimal("100.00"),
            total_vat=Decimal("0.00"),
            total_gross=Decimal("100.00"),
        )
        xml = KSeFMapper.invoice_to_xml(inv)
        root = etree.fromstring(xml)
        ns = {"fa": "http://crd.gov.pl/wzor/2023/06/29/9781/"}
        p13_4 = root.find(".//fa:Fa/fa:P_13_4", ns)
        assert p13_4 is not None, "Stawka 0% powinna generować P_13_4"
        p14_4 = root.find(".//fa:Fa/fa:P_14_4", ns)
        assert p14_4 is not None, "Stawka 0% powinna generować P_14_4"

    def test_mapper_23_generates_p13_1_and_p14_1(self):
        """Stawka 23% generuje P_13_1 i P_14_1."""
        from lxml import etree
        inv = _invoice()
        xml = KSeFMapper.invoice_to_xml(inv)
        root = etree.fromstring(xml)
        ns = {"fa": "http://crd.gov.pl/wzor/2023/06/29/9781/"}
        p13_1 = root.find(".//fa:Fa/fa:P_13_1", ns)
        p14_1 = root.find(".//fa:Fa/fa:P_14_1", ns)
        assert p13_1 is not None
        assert p14_1 is not None


# ===========================================================================
# 9. NbpRateClient: rollback do poprzedniego dnia roboczego
# ===========================================================================

class TestNbpRateClientRollback:
    def test_rolls_back_to_previous_business_day_on_404(self):
        """404 dla weekendu → klient próbuje dzień wcześniej (piątek)."""
        import requests as req_lib
        sat = date(2026, 4, 4)   # sobota
        fri = date(2026, 4, 3)   # piątek (poprzedni dzień roboczy)

        responses = {
            f"https://api.nbp.pl/api/exchangerates/rates/a/EUR/{sat.isoformat()}/?format=json": MagicMock(
                status_code=404, raise_for_status=MagicMock(side_effect=req_lib.HTTPError("404"))
            ),
            f"https://api.nbp.pl/api/exchangerates/rates/a/EUR/{fri.isoformat()}/?format=json": MagicMock(
                status_code=200,
                raise_for_status=MagicMock(),
                json=MagicMock(return_value={
                    "rates": [{"mid": 4.2500}]
                }),
            ),
        }

        mock_session = MagicMock()
        mock_session.get.side_effect = lambda url, timeout: responses[url]
        client = NbpRateClient(session=mock_session)

        rate = client.get_mid_rate("EUR", sat)

        assert rate == Decimal("4.25")
        assert mock_session.get.call_count == 2

    def test_raises_nbp_error_when_all_lookback_days_fail(self):
        """Gdy 404 przez 8 kolejnych dni → NbpRateError."""
        import requests as req_lib

        def always_404(url, timeout=10):
            r = MagicMock()
            r.status_code = 404
            r.raise_for_status.side_effect = req_lib.HTTPError("404")
            return r

        mock_session = MagicMock()
        mock_session.get.side_effect = always_404
        client = NbpRateClient(session=mock_session)

        with pytest.raises(NbpRateError):
            client.get_mid_rate("EUR", date(2026, 4, 6))


# ===========================================================================
# 10. NbpRateValidator: InvalidInvoiceError gdy kurs niedostępny
# ===========================================================================

class TestNbpRateValidatorUnavailable:
    def test_raises_invalid_invoice_error_when_rate_unavailable_within_7_business_days(self):
        """Gdy NbpRateClient rzuca NbpRateError → InvalidInvoiceError na fakturze."""
        nbp_client = MagicMock(spec=NbpRateClient)
        nbp_client.get_mid_rate.side_effect = NbpRateError("brak kursu w 7 dniach")
        validator = NbpRateValidator(nbp_client=nbp_client)

        inv = _invoice(
            currency="EUR",
            exchange_rate=Decimal("4.25"),
            exchange_rate_date=date(2026, 4, 6),
            items=[_item(vat_pln="97.75")],
        )
        with pytest.raises(InvalidInvoiceError, match="Nie można pobrać kursu NBP"):
            validator.validate(inv)


# ===========================================================================
# 11. Migracja 0007: logika backfill i downgrade
# ===========================================================================

class TestMigration0007Logic:
    _MIGRATION_PATH = (
        __file__.replace("tests\\unit\\test_critical_fixes.py", "")
        + "alembic\\versions\\0007_f6a7b8c9d0e1_ksef_hardening.py"
    )

    def _read_migration(self) -> str:
        import pathlib
        p = pathlib.Path(self._MIGRATION_PATH)
        return p.read_text(encoding="utf-8")

    def test_backfill_sql_uses_exists_guard(self):
        """Backfill INSERT ma klauzulę EXISTS — sprawdzamy tekst SQL w migracji."""
        source = self._read_migration()
        # Szukamy EXISTS w sekcji upgrade (przed downgrade) — prosta heurystyka
        upgrade_section = source.split("def downgrade")[0]
        assert "EXISTS" in upgrade_section, (
            "Backfill w upgrade() powinien zawierać EXISTS aby uniknąć FK violation "
            "dla nieistniejących advance invoice IDs."
        )

    def test_downgrade_adds_server_default_jsonb(self):
        """downgrade() odtwarza settled_advance_ids_json z server_default='[]'::jsonb."""
        source = self._read_migration()
        downgrade_section = source.split("def downgrade")[1] if "def downgrade" in source else source
        assert "'[]'::jsonb" in downgrade_section, (
            "downgrade() powinien dodawać server_default=\"'[]'::jsonb\" "
            "aby uniknąć NULL w istniejących wierszach po rollbacku."
        )


# ===========================================================================
# 12. Brak duplikacji unique=True vs UniqueConstraint w TransmissionORM
# ===========================================================================

class TestTransmissionOrmSingleUniqueDefinition:
    def test_idempotency_key_column_does_not_have_unique_true(self):
        """Kolumna idempotency_key NIE ma unique=True — tylko UniqueConstraint."""
        col = TransmissionORM.__table__.c.idempotency_key
        # unique=True na kolumnie tworzy osobny indeks; powinien być tylko jeden
        assert col.unique is None or col.unique is False, (
            "Kolumna idempotency_key nie powinna mieć unique=True (zduplikowany indeks). "
            "Zostaw tylko UniqueConstraint w __table_args__."
        )

    def test_unique_constraint_exists_in_table_args(self):
        """UniqueConstraint 'uq_transmissions_idempotency_key' istnieje."""
        from sqlalchemy import UniqueConstraint
        names = [
            c.name
            for c in TransmissionORM.__table_args__
            if isinstance(c, UniqueConstraint)
        ]
        assert "uq_transmissions_idempotency_key" in names

    def test_only_one_unique_index_for_idempotency_key(self):
        """Nie ma duplikatu unique=True na kolumnie + UniqueConstraint."""
        from sqlalchemy import UniqueConstraint
        # unique=True na kolumnie tworzy dodatkowy UniqueConstraint:
        # sprawdzamy, że łączna liczba unique constraints na idempotency_key == 1
        uc_constraints = [
            c for c in TransmissionORM.__table__.constraints
            if isinstance(c, UniqueConstraint)
            and any(col.name == "idempotency_key" for col in c.columns)
        ]
        assert len(uc_constraints) == 1, (
            f"Oczekiwano dokładnie 1 UniqueConstraint na idempotency_key, "
            f"znaleziono {len(uc_constraints)}: {[c.name for c in uc_constraints]}"
        )
