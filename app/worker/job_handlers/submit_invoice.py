from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.domain.enums import TransmissionStatus
from app.integrations.ksef.client import KSeFClient, KSeFClientError, KSeFSessionExpiredError
from app.integrations.ksef.exceptions import KSeFMappingError
from app.integrations.ksef.mapper import KSeFMapper
from app.persistence.models.background_job import BackgroundJob
from app.persistence.repositories.invoice_repository import InvoiceRepository
from app.persistence.repositories.job_repository import JobRepository
from app.persistence.repositories.transmission_repository import TransmissionRepository
from app.services.ksef_session_service import KSeFSessionService

logger = logging.getLogger(__name__)

_MAX_AUTO_RETRY_ATTEMPTS = 5


def _backoff_minutes(attempt_no: int) -> int:
    """Wykładniczy backoff: 1, 2, 4, 8, 16 minut dla prób 1–5."""
    return 2 ** min(attempt_no - 1, 4)


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
            # NIP sprzedawcy — wymagany do izolacji sesji per-NIP
            seller_nip = (invoice.seller_snapshot or {}).get("nip", "")
            if not seller_nip:
                raise KSeFMappingError(
                    "Brak NIP sprzedawcy w seller_snapshot — nie można wybrać sesji KSeF."
                )

            ctx = self._ksef_session_service.get_session_context(seller_nip)
            xml_bytes = KSeFMapper.invoice_to_xml(invoice)

            # Idempotency key oparty o C14N hash XML — deterministyczny przy retry
            idempotency_key = KSeFMapper.xml_content_hash(xml_bytes)

            send_result = self._ksef_client.send_invoice(
                ctx.access_token,
                ctx.session_reference,
                ctx.symmetric_key,
                ctx.initialization_vector,
                xml_bytes,
            )

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
                        "idempotency_key": idempotency_key,
                    },
                    created_at=now,
                )
            )

            self.session.flush()

        except KSeFMappingError as exc:
            # Blad kontraktu adaptera - dokument strukturalnie niepoprawny, nie ponawiamy
            logger.error(
                "submit_invoice: blad mapowania faktury %s: %s",
                invoice_id,
                exc,
            )
            transmission.status = TransmissionStatus.FAILED_PERMANENT
            transmission.error_code = "MAPPING_ERROR"
            transmission.error_message = str(exc)[:512]
            transmission.finished_at = datetime.now(UTC)
            self.session.flush()

        except NotFoundError as exc:
            # Brak aktywnej sesji KSeF — retryable (sesja może zostać otwarta między próbami)
            logger.warning(
                "submit_invoice: brak sesji KSeF dla transmisji %s (NIP=%s): %s",
                transmission_id,
                (invoice.seller_snapshot or {}).get("nip", "?") if invoice else "?",
                exc,
            )
            now = datetime.now(UTC)
            transmission.status = TransmissionStatus.FAILED_RETRYABLE
            transmission.error_code = "NO_KSEF_SESSION"
            transmission.error_message = str(exc)[:512]
            transmission.finished_at = now
            self.session.flush()

        except KSeFSessionExpiredError as exc:
            # KSeF zwrócił 401/403 — token wygasł, invalidujemy sesję i planujemy retry
            seller_nip = (invoice.seller_snapshot or {}).get("nip", "") if invoice else ""
            logger.warning(
                "submit_invoice: wygasła sesja KSeF dla transmisji %s (NIP=%s): %s",
                transmission_id,
                seller_nip,
                exc,
            )
            if seller_nip:
                try:
                    self._ksef_session_service.mark_session_expired(seller_nip)
                except Exception:  # noqa: BLE001
                    logger.warning(
                        "submit_invoice: nie udało się unieważnić sesji dla NIP %s.",
                        seller_nip,
                    )
            now = datetime.now(UTC)
            transmission.status = TransmissionStatus.FAILED_RETRYABLE
            transmission.error_code = "SESSION_EXPIRED"
            transmission.error_message = str(exc)[:512]
            transmission.finished_at = now
            self.session.flush()

        except KSeFClientError as exc:
            now = datetime.now(UTC)
            if exc.transient and transmission.attempt_no < _MAX_AUTO_RETRY_ATTEMPTS:
                backoff = timedelta(minutes=_backoff_minutes(transmission.attempt_no))
                retry_at = now + backoff
                transmission.attempt_no += 1
                transmission.status = TransmissionStatus.FAILED_TEMPORARY
                transmission.next_retry_at = retry_at
                transmission.error_code = str(exc.status_code) if exc.status_code else "UNKNOWN"
                transmission.error_message = str(exc)
                transmission.finished_at = now
                self._job_repo.add(BackgroundJob(
                    id=uuid4(),
                    job_type="submit_invoice",
                    status="pending",
                    available_at=retry_at,
                    payload_json={
                        "transmission_id": str(transmission.id),
                        "invoice_id": str(transmission.invoice_id),
                    },
                    created_at=now,
                ))
            else:
                transmission.status = TransmissionStatus.FAILED_PERMANENT
                transmission.error_code = str(exc.status_code) if exc.status_code else "UNKNOWN"
                transmission.error_message = str(exc)
                transmission.finished_at = now
            self.session.flush()

        except Exception as exc:
            logger.exception(
                "submit_invoice: nieoczekiwany blad dla transmisji %s.",
                transmission_id,
            )
            now = datetime.now(UTC)
            if transmission.attempt_no < _MAX_AUTO_RETRY_ATTEMPTS:
                backoff = timedelta(minutes=_backoff_minutes(transmission.attempt_no))
                retry_at = now + backoff
                transmission.attempt_no += 1
                transmission.status = TransmissionStatus.FAILED_TEMPORARY
                transmission.next_retry_at = retry_at
                self._job_repo.add(BackgroundJob(
                    id=uuid4(),
                    job_type="submit_invoice",
                    status="pending",
                    available_at=retry_at,
                    payload_json={
                        "transmission_id": str(transmission.id),
                        "invoice_id": str(transmission.invoice_id),
                    },
                    created_at=now,
                ))
            else:
                transmission.status = TransmissionStatus.FAILED_PERMANENT
            transmission.error_code = "INTERNAL_ERROR"
            transmission.error_message = str(exc)[:512]
            transmission.finished_at = now
            self.session.flush()