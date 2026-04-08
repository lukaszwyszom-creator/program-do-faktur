"""
Worker loop: pobiera joby z PostgreSQL i deleguje do handlerów.

Uruchomienie:
    python -m app.worker
"""
from __future__ import annotations

import logging
import signal
import time
from datetime import UTC, datetime

from app.core.config import settings
from app.integrations.ksef.auth import KSeFAuthProvider
from app.integrations.ksef.client import KSeFClient, RetryConfig
from app.persistence.db import SessionLocal
from app.persistence.models.background_job import claimable_jobs
from app.persistence.repositories.invoice_repository import InvoiceRepository
from app.persistence.repositories.job_repository import JobRepository
from app.persistence.repositories.transmission_repository import TransmissionRepository
from app.services.audit_service import AuditService
from app.persistence.repositories.audit_repository import AuditRepository
from app.services.ksef_session_service import KSeFSessionService
from app.worker.job_handlers.submit_invoice import SubmitInvoiceJobHandler
from app.worker.job_handlers.poll_ksef_status import PollKSeFStatusJobHandler

logger = logging.getLogger("app.worker")

POLL_INTERVAL_SECONDS = int(getattr(settings, "worker_poll_interval_seconds", 5))
BATCH_SIZE = 10

_running = True


def _build_handlers(session, ksef_client, ksef_session_service):
    transmission_repo = TransmissionRepository(session)
    invoice_repo = InvoiceRepository(session)
    job_repo = JobRepository(session)
    return {
        "submit_invoice": SubmitInvoiceJobHandler(
            session=session,
            transmission_repository=transmission_repo,
            invoice_repository=invoice_repo,
            job_repository=job_repo,
            ksef_client=ksef_client,
            ksef_session_service=ksef_session_service,
        ),
        "poll_ksef_status": PollKSeFStatusJobHandler(
            session=session,
            transmission_repository=transmission_repo,
            invoice_repository=invoice_repo,
            job_repository=job_repo,
            ksef_client=ksef_client,
            ksef_session_service=ksef_session_service,
        ),
    }


def _process_batch() -> int:
    session = SessionLocal()
    try:
        jobs = claimable_jobs(session, BATCH_SIZE)
        if not jobs:
            return 0

        ksef_client = KSeFClient(
            environment=settings.ksef_environment,
            timeout_seconds=settings.ksef_timeout_seconds,
            retry_config=RetryConfig(),
        )
        audit_service = AuditService(
            session=session,
            audit_repository=AuditRepository(session),
        )
        ksef_session_service = KSeFSessionService(
            session=session,
            auth_provider=KSeFAuthProvider(
                environment=settings.ksef_environment,
                timeout_seconds=settings.ksef_timeout_seconds,
            ),
            audit_service=audit_service,
        )
        handlers = _build_handlers(session, ksef_client, ksef_session_service)

        processed = 0
        for job in jobs:
            job.status = "processing"
            job.locked_at = datetime.now(UTC)
            job.locked_by = "worker"
            job.attempts += 1
            session.flush()

            handler = handlers.get(job.job_type)
            if handler is None:
                logger.warning("Nieznany job_type=%s id=%s — pomijam.", job.job_type, job.id)
                job.status = "failed"
                job.last_error = f"Nieznany job_type: {job.job_type}"
                session.flush()
                session.commit()
                processed += 1
                continue

            try:
                handler.handle(job.payload_json)
                job.status = "done"
                logger.info("Job %s (%s) zakończony.", job.id, job.job_type)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Job %s (%s) BŁĄD: %s", job.id, job.job_type, exc)
                job.last_error = str(exc)[:1024]
                if job.attempts >= job.max_attempts:
                    job.status = "failed"
                else:
                    job.status = "pending"

            session.flush()
            session.commit()
            processed += 1

        return processed
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _handle_signal(signum, frame):  # noqa: ARG001
    global _running
    logger.info("Sygnał %s — zatrzymuję worker.", signum)
    _running = False


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format='{"time": "%(asctime)s", "level": "%(levelname)s", "logger": "%(name)s", "msg": "%(message)s"}',
    )
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    logger.info("Worker startuje. poll_interval=%ss batch=%s", POLL_INTERVAL_SECONDS, BATCH_SIZE)
    while _running:
        try:
            n = _process_batch()
            if n:
                logger.info("Przetworzone joby: %s", n)
        except Exception:  # noqa: BLE001
            logger.exception("Błąd podczas przetwarzania batcha — kontynuuję.")
        if _running:
            time.sleep(POLL_INTERVAL_SECONDS)

    logger.info("Worker zatrzymany.")


if __name__ == "__main__":
    main()
