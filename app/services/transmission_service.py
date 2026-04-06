from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.core.security import AuthenticatedUser
from app.domain.enums import InvoiceStatus, TransmissionStatus
from app.domain.exceptions import InvalidInvoiceError, InvalidStatusTransitionError
from app.persistence.models.background_job import BackgroundJob
from app.persistence.models.transmission import TransmissionORM
from app.persistence.repositories.invoice_repository import InvoiceRepository
from app.persistence.repositories.job_repository import JobRepository
from app.persistence.repositories.transmission_repository import TransmissionRepository
from app.services.audit_service import AuditService

logger = logging.getLogger(__name__)

_ACTIVE_STATUSES = (
    TransmissionStatus.QUEUED,
    TransmissionStatus.PROCESSING,
    TransmissionStatus.SUBMITTED,
    TransmissionStatus.WAITING_STATUS,
)
_RETRYABLE_STATUSES = (TransmissionStatus.FAILED_RETRYABLE,)

MAX_RETRY_ATTEMPTS = 5


class TransmissionService:
    def __init__(
        self,
        session: Session,
        transmission_repository: TransmissionRepository,
        invoice_repository: InvoiceRepository,
        job_repository: JobRepository,
        audit_service: AuditService,
    ) -> None:
        self.session = session
        self._transmission_repo = transmission_repository
        self._invoice_repo = invoice_repository
        self._job_repo = job_repository
        self._audit_service = audit_service

    # -------------------------------------------------------------------------
    # PUBLIC API
    # -------------------------------------------------------------------------

    def submit_invoice(
        self, invoice_id: UUID, actor: AuthenticatedUser
    ) -> TransmissionORM:
        invoice = self._invoice_repo.lock_for_update(invoice_id)
        if invoice is None:
            raise NotFoundError(f"Nie znaleziono faktury {invoice_id}.")

        if not invoice.can_transition_to(InvoiceStatus.SENDING):
            raise InvalidStatusTransitionError(
                f"Faktura musi mieć status 'ready_for_submission' "
                f"(aktualnie: '{invoice.status.value}')."
            )

        active = self._transmission_repo.get_active_for_invoice(invoice_id)
        if active is not None:
            raise InvalidInvoiceError(
                f"Faktura {invoice_id} ma już aktywną transmisję {active.id} "
                f"(status: {active.status})."
            )

        now = datetime.now(UTC)
        transmission = TransmissionORM(
            id=uuid4(),
            invoice_id=invoice_id,
            channel="ksef",
            operation_type="submit",
            status=TransmissionStatus.QUEUED,
            attempt_no=1,
            idempotency_key=str(uuid4()),
            created_at=now,
        )
        saved_transmission = self._transmission_repo.add(transmission)

        invoice.transition_to(InvoiceStatus.SENDING)
        invoice.updated_at = now

        self._job_repo.add(
            BackgroundJob(
                id=uuid4(),
                job_type="submit_invoice",
                status="pending",
                payload_json={"transmission_id": str(saved_transmission.id),
                         "invoice_id": str(invoice_id)},
                created_at=now,
            )
        )

        self.session.flush()

        self._audit_service.record(
            actor_user_id=actor.user_id,
            actor_role=actor.role,
            event_type="transmission.created",
            entity_type="transmission",
            entity_id=str(saved_transmission.id),
            after={"status": TransmissionStatus.QUEUED.value},
        )
        self._audit_service.record(
            actor_user_id=actor.user_id,
            actor_role=actor.role,
            event_type="invoice.status_changed",
            entity_type="invoice",
            entity_id=str(invoice_id),
            after={"status": InvoiceStatus.SENDING.value},
        )

        return saved_transmission

    def retry_transmission(
        self, transmission_id: UUID, actor: AuthenticatedUser
    ) -> TransmissionORM:
        transmission = self._transmission_repo.lock_for_update(transmission_id)
        if transmission is None:
            raise NotFoundError(f"Nie znaleziono transmisji {transmission_id}.")

        if transmission.status not in _RETRYABLE_STATUSES:
            raise InvalidInvoiceError(
                f"Nie można wykonać retry transmisji w statusie "
                f"'{transmission.status}' — dozwolone: {_RETRYABLE_STATUSES}."
            )

        if transmission.attempt_no >= MAX_RETRY_ATTEMPTS:
            raise InvalidInvoiceError(
                f"Przekroczono maksymalną liczbę prób ({MAX_RETRY_ATTEMPTS}) "
                f"dla transmisji {transmission_id}."
            )

        now = datetime.now(UTC)
        transmission.attempt_no += 1
        transmission.status = TransmissionStatus.QUEUED
        transmission.error_code = None
        transmission.error_message = None

        self._job_repo.add(
            BackgroundJob(
                id=uuid4(),
                job_type="submit_invoice",
                status="pending",
                payload_json={
                    "transmission_id": str(transmission_id),
                    "invoice_id": str(transmission.invoice_id),
                },
                created_at=now,
            )
        )

        self.session.flush()

        self._audit_service.record(
            actor_user_id=actor.user_id,
            actor_role=actor.role,
            event_type="transmission.retry",
            entity_type="transmission",
            entity_id=str(transmission_id),
            after={"attempt_no": transmission.attempt_no},
        )

        return transmission

    def get_transmission(self, transmission_id: UUID) -> TransmissionORM:
        transmission = self._transmission_repo.get_by_id(transmission_id)
        if transmission is None:
            raise NotFoundError(f"Nie znaleziono transmisji {transmission_id}.")
        return transmission

    def list_for_invoice(self, invoice_id: UUID) -> list[TransmissionORM]:
        return self._transmission_repo.list_for_invoice(invoice_id)
