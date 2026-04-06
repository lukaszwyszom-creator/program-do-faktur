from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.domain.enums import TransmissionStatus
from app.integrations.ksef.client import KSeFClient, KSeFClientError
from app.integrations.ksef.mapper import KSeFMapper
from app.persistence.models.background_job import BackgroundJob
from app.persistence.repositories.invoice_repository import InvoiceRepository
from app.persistence.repositories.job_repository import JobRepository
from app.persistence.repositories.transmission_repository import TransmissionRepository
from app.services.ksef_session_service import KSeFSessionService

logger = logging.getLogger(__name__)


class SubmitInvoiceJobHandler:
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
        invoice_id = UUID(payload["invoice_id"])

        transmission = self._transmission_repo.lock_for_update(transmission_id)
        if transmission is None:
            logger.warning(
                "submit_invoice: nie znaleziono transmisji %s — pomijam.",
                transmission_id,
            )
            return

        now = datetime.now(UTC)
        transmission.status = TransmissionStatus.PROCESSING
        transmission.started_at = now

        invoice = self._invoice_repo.get_by_id(invoice_id)
        if invoice is None:
            logger.error(
                "submit_invoice: nie znaleziono faktury %s dla transmisji %s.",
                invoice_id,
                transmission_id,
            )
            transmission.status = TransmissionStatus.FAILED_PERMANENT
            transmission.error_code = "INVOICE_NOT_FOUND"
            transmission.finished_at = datetime.now(UTC)
            self.session.flush()
            return

        try:
            session_token = self._ksef_session_service.get_session_token()
            xml_bytes = KSeFMapper.invoice_to_xml(invoice)
            send_result = self._ksef_client.send_invoice(session_token, xml_bytes)

            transmission.status = TransmissionStatus.SUBMITTED
            transmission.external_reference = send_result.reference_number
            transmission.finished_at = datetime.now(UTC)

            # Zaplanuj polling statusu
            self._job_repo.add(
                BackgroundJob(
                    id=uuid4(),
                    job_type="poll_ksef_status",
                    status="pending",
                    payload_json={
                        "transmission_id": str(transmission_id),
                        "reference_number": send_result.reference_number,
                    },
                    created_at=now,
                )
            )

            self.session.flush()

        except KSeFClientError as exc:
            if exc.transient:
                transmission.status = TransmissionStatus.FAILED_RETRYABLE
            else:
                transmission.status = TransmissionStatus.FAILED_PERMANENT
            transmission.error_code = str(exc.status_code) if exc.status_code else "UNKNOWN"
            transmission.error_message = str(exc)
            transmission.finished_at = datetime.now(UTC)
            self.session.flush()

        except Exception as exc:
            logger.exception(
                "submit_invoice: nieoczekiwany błąd dla transmisji %s.",
                transmission_id,
            )
            transmission.status = TransmissionStatus.FAILED_RETRYABLE
            transmission.error_code = "INTERNAL_ERROR"
            transmission.error_message = str(exc)[:512]
            transmission.finished_at = datetime.now(UTC)
            self.session.flush()
from app.persistence.repositories.invoice_repository import InvoiceRepository
from app.persistence.repositories.job_repository import JobRepository
from app.persistence.repositories.transmission_repository import TransmissionRepository
from app.services.ksef_session_service import KSeFSessionService

logger = logging.getLogger(__name__)


class SubmitInvoiceJobHandler:
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
        invoice_id = UUID(payload["invoice_id"])

        transmission = self._transmission_repo.lock_for_update(transmission_id)
        if transmission is None:
            logger.warning(
                "submit_invoice: ni znaleziono transmisji %s — pomijam.",
                transmission_id,
            )
            return

        now = datetime.now(UTC)
        transmission.status = TransmissionStatus.PROCESSING
        transmission.started_at = now

        invoice = self._invoice_repo.get_by_id(invoice_id)
        if invoice is None:
            logger.error(
                "submit_invoice: nie znaleziono faktury %s dla transmisji %s.",
                invoice_id,
                transmission_id,
            )
            transmission.status = TransmissionStatus.FAILED_PERMANENT
            transmission.error_code = "INVOICE_NOT_FOUND"
            transmission.finished_at = datetime.now(UTC)
            self.session.flush()
            return

        try:
            session_token = self._ksef_session_service.get_session_token()
            xml_bytes = KSeFMapper.invoice_to_xml(invoice)
            send_result = self._ksef_client.send_invoice(session_token, xml_bytes)

            transmission.status = TransmissionStatus.SUBMITTED
            transmission.external_reference = send_result.reference_number
            transmission.finished_at = datetime.now(UTC)

            # Zaplanuj polling statusu
            self._job_repo.add(
                BackgroundJob(
                    id=uuid4(),
                    job_type="poll_ksef_status",
                    status="pending",
                    payload_json={
                        "transmission_id": str(transmission_id),
                        "reference_number": send_result.reference_number,
                    },
                    created_at=datetime.now(UTC),
                )
            )

            self.session.flush()

        except KSeFClientError as exc:
            if exc.transient:
                transmission.status = TransmissionStatus.FAILED_RETRYABLE
            else:
                transmission.status = TransmissionStatus.FAILED_PERMANENT
            transmission.error_code = str(exc.status_code) if exc.status_code else "UNKNOWN"
            transmission.error_message = str(exc)
            transmission.finished_at = datetime.now(UTC)
            self.session.flush()

        except Exception as exc:
            logger.exception(
                "submit_invoice: nieoczekiwany błąd dla transmisji %s.",
                transmission_id,
            )
            transmission.status = TransmissionStatus.FAILED_RETRYABLE
            transmission.error_code = "INTERNAL_ERROR"
            transmission.error_message = str(exc)[:512]
            transmission.finished_at = datetime.now(UTC)
            self.session.flush()
