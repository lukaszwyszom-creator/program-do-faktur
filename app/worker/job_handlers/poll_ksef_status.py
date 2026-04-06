from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.domain.enums import InvoiceStatus, TransmissionStatus
from app.integrations.ksef.client import KSeFClient, KSeFClientError
from app.persistence.models.background_job import BackgroundJob
from app.persistence.repositories.invoice_repository import InvoiceRepository
from app.persistence.repositories.job_repository import JobRepository
from app.persistence.repositories.transmission_repository import TransmissionRepository
from app.services.ksef_session_service import KSeFSessionService

logger = logging.getLogger(__name__)

_PERMANENT_ERROR_CODES = frozenset({400, 401, 403, 404, 422})
_POLL_RETRY_DELAY_SECONDS = 30


class PollKSeFStatusJobHandler:
    def __init__(
        self,
        session: Session,
        transmission_repository: TransmissionRepository,
        invoice_repository: InvoiceRepository,
        job_repository: JobRepository,
        ksef_client: KSeFClient,
        ksef_session_service: KSeFSessionService,
    ) -> None:
        self.session = session
        self._transmission_repo = transmission_repository
        self._invoice_repo = invoice_repository
        self._job_repo = job_repository
        self._ksef_client = ksef_client
        self._ksef_session_service = ksef_session_service

    def handle(self, payload: dict) -> None:
        transmission_id = UUID(payload["transmission_id"])
        reference_number = payload["reference_number"]

        transmission = self._transmission_repo.lock_for_update(transmission_id)
        if transmission is None:
            logger.warning(
                "poll_ksef_status: nie znaleziono transmisji %s — pomijam.",
                transmission_id,
            )
            return

        # Idempotentnosc: jesli transmisja juz zakonczona, pomijamy
        if transmission.status in (
            TransmissionStatus.SUCCESS,
            TransmissionStatus.FAILED_PERMANENT,
        ):
            logger.info(
                "poll_ksef_status: transmisja %s juz zakonczona (%s) — pomijam.",
                transmission_id,
                transmission.status,
            )
            return

        try:
            session_token = self._ksef_session_service.get_session_token()
            status_result = self._ksef_client.get_invoice_status(
                session_token, reference_number
            )
        except KSeFClientError as exc:
            logger.warning(
                "poll_ksef_status: blad KSeF dla transmisji %s: %s",
                transmission_id,
                exc,
            )
            transmission.status = TransmissionStatus.WAITING_STATUS
            self._schedule_retry(transmission_id, reference_number)
            return
        except Exception as exc:
            logger.exception(
                "poll_ksef_status: nieoczekiwany blad dla transmisji %s.",
                transmission_id,
            )
            transmission.status = TransmissionStatus.WAITING_STATUS
            self._schedule_retry(transmission_id, reference_number)
            return

        code = status_result.processing_code

        if code == 200:
            # KSeF potwierdzil przetworzenie faktury
            if status_result.ksef_reference_number is None:
                logger.warning(
                    "poll_ksef_status: KSeF zwrocil kod 200 bez ksefReferenceNumber"
                    " dla transmisji %s.",
                    transmission_id,
                )
            transmission.status = TransmissionStatus.SUCCESS
            transmission.ksef_reference_number = status_result.ksef_reference_number
            transmission.finished_at = datetime.now(UTC)

            invoice = self._invoice_repo.lock_for_update(transmission.invoice_id)
            if invoice is not None:
                invoice.transition_to(InvoiceStatus.ACCEPTED)
                invoice.ksef_reference_number = status_result.ksef_reference_number
                self._invoice_repo.update(invoice.id, invoice)

        elif code in _PERMANENT_ERROR_CODES:
            # KSeF odrzucil fakture — blad permanentny
            transmission.status = TransmissionStatus.FAILED_PERMANENT
            transmission.error_code = str(code)
            transmission.error_message = status_result.processing_description
            transmission.finished_at = datetime.now(UTC)

            invoice = self._invoice_repo.lock_for_update(transmission.invoice_id)
            if invoice is not None:
                invoice.transition_to(InvoiceStatus.REJECTED)
                self._invoice_repo.update(invoice.id, invoice)

        else:
            # Faktura jest jeszcze w kolejce KSeF — czekamy
            transmission.status = TransmissionStatus.WAITING_STATUS
            self._schedule_retry(transmission_id, reference_number)
            return

        self.session.flush()

    def _schedule_retry(
        self, transmission_id: UUID, reference_number: str
    ) -> None:
        retry_at = datetime.now(UTC) + timedelta(seconds=_POLL_RETRY_DELAY_SECONDS)
        self._job_repo.add(
            BackgroundJob(
                id=uuid4(),
                job_type="poll_ksef_status",
                status="pending",
                payload_json={
                    "transmission_id": str(transmission_id),
                    "reference_number": reference_number,
                },
                available_at=retry_at,
                created_at=datetime.now(UTC),
            )
        )
        self.session.flush()