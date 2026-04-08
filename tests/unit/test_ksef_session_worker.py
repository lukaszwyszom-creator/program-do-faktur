"""Testy obsługi sesji KSeF w warstwie worker i serwisów.

Sprawdzamy:
1. Brak sesji KSeF → NO_KSEF_SESSION + FAILED_RETRYABLE (nie crash)
2. Poprawna sesja → submit przechodzi do KSeFClient.send_invoice
3. KSeF 401/403 → SESSION_EXPIRED + sesja oznaczona + FAILED_RETRYABLE
4. mark_session_expired() w KSeFSessionService
5. TransmissionService.submit_invoice → NoKSeFSessionError gdy brak sesji
6. KSeFSessionExpiredError jest podklasą KSeFClientError
"""
from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.core.exceptions import NotFoundError
from app.domain.enums import InvoiceStatus, TransmissionStatus
from app.domain.exceptions import InvalidInvoiceError, NoKSeFSessionError
from app.domain.models.invoice import Invoice, InvoiceItem
from app.integrations.ksef.client import (
    KSeFClientError,
    KSeFSessionExpiredError,
    SendInvoiceResult,
)
from app.persistence.models.transmission import TransmissionORM
from app.services.ksef_session_service import (
    SESSION_ACTIVE,
    SESSION_EXPIRED,
    KSeFSessionService,
)
from app.worker.job_handlers.submit_invoice import SubmitInvoiceJobHandler


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _make_item() -> InvoiceItem:
    return InvoiceItem(
        name="Usługa",
        quantity=Decimal("1"),
        unit="szt.",
        unit_price_net=Decimal("100.00"),
        vat_rate=Decimal("23"),
        net_total=Decimal("100.00"),
        vat_total=Decimal("23.00"),
        gross_total=Decimal("123.00"),
        sort_order=1,
    )


def _make_invoice(**kwargs) -> Invoice:
    defaults = dict(
        id=uuid4(),
        status=InvoiceStatus.SENDING,
        issue_date=date(2026, 4, 7),
        sale_date=date(2026, 4, 7),
        currency="PLN",
        seller_snapshot={
            "nip": "1111111111",
            "name": "Sprzedawca Sp. z o.o.",
            "street": "ul. Testowa",
            "building_no": "1",
            "postal_code": "00-001",
            "city": "Warszawa",
        },
        buyer_snapshot={"nip": "1234563218", "name": "Nabywca S.A."},
        items=[_make_item()],
        total_net=Decimal("100.00"),
        total_vat=Decimal("23.00"),
        total_gross=Decimal("123.00"),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    defaults.update(kwargs)
    return Invoice(**defaults)


def _make_transmission(invoice_id=None, attempt_no: int = 1) -> TransmissionORM:
    t = MagicMock(spec=TransmissionORM)
    t.id = uuid4()
    t.invoice_id = invoice_id or uuid4()
    t.attempt_no = attempt_no
    t.status = TransmissionStatus.QUEUED
    t.error_code = None
    t.error_message = None
    t.finished_at = None
    return t


def _make_handler(
    invoice: Invoice | None = None,
    transmission: TransmissionORM | None = None,
    session_token: str | None = "tok-123",
    ksef_client=None,
) -> tuple[SubmitInvoiceJobHandler, TransmissionORM, Invoice]:
    inv = invoice or _make_invoice()
    tr = transmission or _make_transmission(invoice_id=inv.id)

    transmission_repo = MagicMock()
    transmission_repo.lock_for_update.return_value = tr

    invoice_repo = MagicMock()
    invoice_repo.get_by_id.return_value = inv

    ksef_session_svc = MagicMock(spec=KSeFSessionService)
    if session_token is None:
        ksef_session_svc.get_session_token.side_effect = NotFoundError(
            "Brak aktywnej sesji KSeF dla NIP 1111111111."
        )
    else:
        ksef_session_svc.get_session_token.return_value = session_token

    handler = SubmitInvoiceJobHandler(
        session=MagicMock(),
        transmission_repository=transmission_repo,
        invoice_repository=invoice_repo,
        job_repository=MagicMock(),
        ksef_client=ksef_client or MagicMock(),
        ksef_session_service=ksef_session_svc,
    )
    return handler, tr, inv


# ---------------------------------------------------------------------------
# 1. Brak sesji KSeF → NO_KSEF_SESSION + FAILED_RETRYABLE
# ---------------------------------------------------------------------------

class TestNoKSeFSession:
    def test_missing_session_sets_no_ksef_session_code(self):
        """get_session_token rzuca NotFoundError → error_code=NO_KSEF_SESSION."""
        handler, tr, inv = _make_handler(session_token=None)

        payload = {"transmission_id": str(tr.id), "invoice_id": str(inv.id)}
        handler.handle(payload)

        assert tr.error_code == "NO_KSEF_SESSION"

    def test_missing_session_sets_failed_retryable(self):
        """Brak sesji to błąd retryable — sesja może zostać otwarta między próbami."""
        handler, tr, inv = _make_handler(session_token=None)

        payload = {"transmission_id": str(tr.id), "invoice_id": str(inv.id)}
        handler.handle(payload)

        assert tr.status == TransmissionStatus.FAILED_RETRYABLE

    def test_missing_session_does_not_call_ksef_client(self):
        """KSeFClient.send_invoice nie jest wołany gdy brak sesji."""
        mock_client = MagicMock()
        handler, tr, inv = _make_handler(session_token=None, ksef_client=mock_client)

        payload = {"transmission_id": str(tr.id), "invoice_id": str(inv.id)}
        handler.handle(payload)

        mock_client.send_invoice.assert_not_called()

    def test_missing_session_sets_error_message(self):
        """error_message zawiera czytelny opis braku sesji."""
        handler, tr, inv = _make_handler(session_token=None)

        payload = {"transmission_id": str(tr.id), "invoice_id": str(inv.id)}
        handler.handle(payload)

        assert tr.error_message is not None
        assert "sesji" in tr.error_message.lower() or "session" in tr.error_message.lower()


# ---------------------------------------------------------------------------
# 2. Poprawna sesja → submit przechodzi do KSeFClient
# ---------------------------------------------------------------------------

class TestValidSession:
    def test_valid_session_calls_send_invoice(self):
        """Aktywna sesja → send_invoice jest wywoływane z poprawnym tokenem."""
        mock_client = MagicMock()
        mock_client.send_invoice.return_value = SendInvoiceResult(
            reference_number="ref-001",
            processing_code=200,
            processing_description="OK",
        )

        with patch("app.worker.job_handlers.submit_invoice.KSeFMapper") as mock_mapper:
            mock_mapper.invoice_to_xml.return_value = b"<xml/>"
            mock_mapper.xml_content_hash.return_value = "hash-abc"

            handler, tr, inv = _make_handler(session_token="valid-token", ksef_client=mock_client)
            payload = {"transmission_id": str(tr.id), "invoice_id": str(inv.id)}
            handler.handle(payload)

        mock_client.send_invoice.assert_called_once_with("valid-token", b"<xml/>")

    def test_valid_session_sets_submitted_status(self):
        """Po udanym send_invoice → status=SUBMITTED."""
        mock_client = MagicMock()
        mock_client.send_invoice.return_value = SendInvoiceResult(
            reference_number="ref-001",
            processing_code=200,
            processing_description="OK",
        )

        with patch("app.worker.job_handlers.submit_invoice.KSeFMapper") as mock_mapper:
            mock_mapper.invoice_to_xml.return_value = b"<xml/>"
            mock_mapper.xml_content_hash.return_value = "hash-abc"

            handler, tr, inv = _make_handler(session_token="valid-token", ksef_client=mock_client)
            payload = {"transmission_id": str(tr.id), "invoice_id": str(inv.id)}
            handler.handle(payload)

        assert tr.status == TransmissionStatus.SUBMITTED
        assert tr.external_reference == "ref-001"


# ---------------------------------------------------------------------------
# 3. KSeF 401/403 → SESSION_EXPIRED + invalidacja sesji + FAILED_RETRYABLE
# ---------------------------------------------------------------------------

class TestSessionExpired:
    def test_401_sets_session_expired_code(self):
        """KSeF 401 → error_code=SESSION_EXPIRED."""
        mock_client = MagicMock()
        mock_client.send_invoice.side_effect = KSeFSessionExpiredError(
            "KSeF: sesja wygasła (401): Unauthorized",
            status_code=401,
        )

        with patch("app.worker.job_handlers.submit_invoice.KSeFMapper") as mock_mapper:
            mock_mapper.invoice_to_xml.return_value = b"<xml/>"
            mock_mapper.xml_content_hash.return_value = "hash-abc"

            handler, tr, inv = _make_handler(session_token="expired-tok", ksef_client=mock_client)
            payload = {"transmission_id": str(tr.id), "invoice_id": str(inv.id)}
            handler.handle(payload)

        assert tr.error_code == "SESSION_EXPIRED"

    def test_401_sets_failed_retryable(self):
        """KSeF 401 → FAILED_RETRYABLE (nie FAILED_PERMANENT)."""
        mock_client = MagicMock()
        mock_client.send_invoice.side_effect = KSeFSessionExpiredError(
            "Unauthorized", status_code=401
        )

        with patch("app.worker.job_handlers.submit_invoice.KSeFMapper") as mock_mapper:
            mock_mapper.invoice_to_xml.return_value = b"<xml/>"
            mock_mapper.xml_content_hash.return_value = "hash-abc"

            handler, tr, inv = _make_handler(session_token="expired-tok", ksef_client=mock_client)
            payload = {"transmission_id": str(tr.id), "invoice_id": str(inv.id)}
            handler.handle(payload)

        assert tr.status == TransmissionStatus.FAILED_RETRYABLE

    def test_401_calls_mark_session_expired(self):
        """KSeF 401 → KSeFSessionService.mark_session_expired jest wywoływane."""
        mock_client = MagicMock()
        mock_client.send_invoice.side_effect = KSeFSessionExpiredError(
            "Unauthorized", status_code=401
        )

        with patch("app.worker.job_handlers.submit_invoice.KSeFMapper") as mock_mapper:
            mock_mapper.invoice_to_xml.return_value = b"<xml/>"
            mock_mapper.xml_content_hash.return_value = "hash-abc"

            handler, tr, inv = _make_handler(session_token="expired-tok", ksef_client=mock_client)
            payload = {"transmission_id": str(tr.id), "invoice_id": str(inv.id)}
            handler.handle(payload)

        handler._ksef_session_service.mark_session_expired.assert_called_once_with("1111111111")

    def test_403_also_invalidates_session(self):
        """KSeF 403 (Forbidden) traktujemy tak samo jak 401."""
        mock_client = MagicMock()
        mock_client.send_invoice.side_effect = KSeFSessionExpiredError(
            "Forbidden", status_code=403
        )

        with patch("app.worker.job_handlers.submit_invoice.KSeFMapper") as mock_mapper:
            mock_mapper.invoice_to_xml.return_value = b"<xml/>"
            mock_mapper.xml_content_hash.return_value = "hash-abc"

            handler, tr, inv = _make_handler(session_token="tok", ksef_client=mock_client)
            payload = {"transmission_id": str(tr.id), "invoice_id": str(inv.id)}
            handler.handle(payload)

        assert tr.error_code == "SESSION_EXPIRED"
        handler._ksef_session_service.mark_session_expired.assert_called_once_with("1111111111")


# ---------------------------------------------------------------------------
# 4. mark_session_expired() w KSeFSessionService
# ---------------------------------------------------------------------------

class TestMarkSessionExpired:
    def _make_service(self, active_orm=None):
        session = MagicMock()
        service = KSeFSessionService(
            session=session,
            auth_provider=MagicMock(),
            audit_service=MagicMock(),
        )
        service._get_active_db_session = MagicMock(return_value=active_orm)
        return service

    def test_marks_active_session_as_expired(self):
        """Aktywna sesja → status zmieniony na SESSION_EXPIRED."""
        orm = MagicMock()
        orm.status = SESSION_ACTIVE
        service = self._make_service(active_orm=orm)

        service.mark_session_expired("1111111111")

        assert orm.status == SESSION_EXPIRED

    def test_no_active_session_does_not_raise(self):
        """Brak aktywnej sesji → żaden wyjątek nie jest rzucany."""
        service = self._make_service(active_orm=None)

        service.mark_session_expired("1111111111")  # nie rzuca

    def test_invalidates_token_cache(self):
        """Po oznaczeniu sesji jako wygasłej cache jest czyszczony."""
        orm = MagicMock()
        orm.status = SESSION_ACTIVE
        service = self._make_service(active_orm=orm)
        service._token_cache["1111111111"] = MagicMock()

        service.mark_session_expired("1111111111")

        assert "1111111111" not in service._token_cache


# ---------------------------------------------------------------------------
# 5. TransmissionService → NoKSeFSessionError gdy brak sesji
# ---------------------------------------------------------------------------

class TestTransmissionServiceSessionCheck:
    def _make_service(self, invoice: Invoice, session_active: bool):
        from app.services.transmission_service import TransmissionService

        session = MagicMock()

        invoice_repo = MagicMock()
        invoice_repo.lock_for_update.return_value = invoice

        transmission_repo = MagicMock()
        transmission_repo.get_active_for_invoice.return_value = None

        ksef_session_svc = MagicMock(spec=KSeFSessionService)
        if not session_active:
            ksef_session_svc.get_active_session.side_effect = NotFoundError(
                "Brak aktywnej sesji KSeF dla NIP 1111111111."
            )

        svc = TransmissionService(
            session=session,
            transmission_repository=transmission_repo,
            invoice_repository=invoice_repo,
            job_repository=MagicMock(),
            audit_service=MagicMock(),
            ksef_session_service=ksef_session_svc,
        )
        return svc

    def test_missing_session_raises_no_ksef_session_error(self):
        """submit_invoice → NoKSeFSessionError gdy brak aktywnej sesji KSeF."""
        inv = _make_invoice(status=InvoiceStatus.READY_FOR_SUBMISSION)
        svc = self._make_service(inv, session_active=False)

        actor = MagicMock()
        actor.user_id = str(uuid4())
        actor.role = "admin"

        with pytest.raises(NoKSeFSessionError, match="ksef-sessions"):
            svc.submit_invoice(inv.id, actor)

    def test_active_session_does_not_raise(self):
        """submit_invoice → brak wyjątku gdy sesja aktywna."""
        inv = _make_invoice(status=InvoiceStatus.READY_FOR_SUBMISSION)
        svc = self._make_service(inv, session_active=True)

        actor = MagicMock()
        actor.user_id = str(uuid4())
        actor.role = "admin"

        # Może rzucić przy flush/audit, ale NIE NoKSeFSessionError
        try:
            svc.submit_invoice(inv.id, actor)
        except NoKSeFSessionError:
            pytest.fail("NoKSeFSessionError rzucony mimo aktywnej sesji")
        except Exception:
            pass  # Inne błędy (mock flush/commit) są OK


# ---------------------------------------------------------------------------
# 6. KSeFSessionExpiredError jest podklasą KSeFClientError
# ---------------------------------------------------------------------------

class TestKSeFSessionExpiredErrorHierarchy:
    def test_is_subclass_of_ksef_client_error(self):
        assert issubclass(KSeFSessionExpiredError, KSeFClientError)

    def test_transient_is_false(self):
        exc = KSeFSessionExpiredError("test", status_code=401)
        assert exc.transient is False

    def test_status_code_preserved(self):
        exc = KSeFSessionExpiredError("test", status_code=403)
        assert exc.status_code == 403

    def test_not_caught_by_generic_handler_when_specific_first(self):
        """Gwarantuje porządek handlerów: SessionExpired przed KSeFClientError."""
        caught_as_expired = False
        caught_as_client = False

        try:
            raise KSeFSessionExpiredError("tok expired", status_code=401)
        except KSeFSessionExpiredError:
            caught_as_expired = True
        except KSeFClientError:
            caught_as_client = True

        assert caught_as_expired
        assert not caught_as_client

    def test_is_caught_by_ksef_client_error_if_no_specific_handler(self):
        """Dziedziczy po KSeFClientError — catchable przez starszy kod."""
        caught = False
        try:
            raise KSeFSessionExpiredError("tok expired", status_code=401)
        except KSeFClientError:
            caught = True

        assert caught


# ---------------------------------------------------------------------------
# 7. NoKSeFSessionError jest podklasą InvalidInvoiceError (→ HTTP 422)
# ---------------------------------------------------------------------------

class TestNoKSeFSessionErrorHierarchy:
    def test_is_subclass_of_invalid_invoice_error(self):
        assert issubclass(NoKSeFSessionError, InvalidInvoiceError)

    def test_http_status_code_is_422(self):
        exc = NoKSeFSessionError("brak sesji")
        assert exc.status_code == 422

    def test_error_code(self):
        exc = NoKSeFSessionError("brak sesji")
        assert exc.code == "no_ksef_session"
