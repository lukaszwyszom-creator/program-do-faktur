from collections.abc import Generator
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import UnauthorizedError
from app.core.security import AuthenticatedUser
from app.integrations.ksef.auth import KSeFAuthProvider
from app.integrations.ksef.client import KSeFClient, RetryConfig
from app.integrations.regon.client import RegonClient
from app.integrations.regon.mapper import RegonMapper
from app.persistence.db import get_session
from app.persistence.repositories.app_settings_repository import AppSettingsRepository
from app.persistence.repositories.audit_repository import AuditRepository
from app.persistence.repositories.bank_transaction_repository import BankTransactionRepository
from app.persistence.repositories.contractor_override_repository import ContractorOverrideRepository
from app.persistence.repositories.contractor_repository import ContractorRepository
from app.persistence.repositories.idempotency_repository import IdempotencyRepository
from app.persistence.repositories.invoice_repository import InvoiceRepository
from app.persistence.repositories.job_repository import JobRepository
from app.persistence.repositories.payment_allocation_repository import PaymentAllocationRepository
from app.persistence.repositories.stock_repository import StockRepository
from app.persistence.repositories.transmission_repository import TransmissionRepository
from app.persistence.repositories.user_repository import UserRepository
from app.services.audit_service import AuditService
from app.services.auth_service import AuthService
from app.services.contractor_service import ContractorService
from app.services.idempotency_service import IdempotencyService
from app.services.invoice_service import InvoiceService
from app.services.ksef_session_service import KSeFSessionService
from app.services.payment_service import PaymentService
from app.services.settings_service import SettingsService
from app.services.stock_service import StockService
from app.services.transmission_service import TransmissionService


http_bearer = HTTPBearer(auto_error=False)


def get_db_session() -> Generator[Session, None, None]:
    yield from get_session()


def get_settings_service(
    session: Annotated[Session, Depends(get_db_session)],
) -> SettingsService:
    return SettingsService(
        session=session,
        repository=AppSettingsRepository(session),
    )


def get_audit_service(session: Annotated[Session, Depends(get_db_session)]) -> AuditService:
    return AuditService(session=session, audit_repository=AuditRepository(session))


def get_auth_service(session: Annotated[Session, Depends(get_db_session)]) -> AuthService:
    return AuthService(session=session, user_repository=UserRepository(session))


def get_contractor_service(
    session: Annotated[Session, Depends(get_db_session)],
    audit_service: Annotated[AuditService, Depends(get_audit_service)],
) -> ContractorService:
    return ContractorService(
        session=session,
        contractor_repository=ContractorRepository(session),
        contractor_override_repository=ContractorOverrideRepository(session),
        audit_service=audit_service,
        regon_client=RegonClient(
            api_key=settings.regon_api_key,
            environment=settings.regon_environment,
            timeout_seconds=settings.request_timeout_seconds,
            wsdl_test=settings.regon_wsdl_test,
            wsdl_production=settings.regon_wsdl_production,
        ),
        regon_mapper=RegonMapper(),
    )


def get_invoice_service(
    session: Annotated[Session, Depends(get_db_session)],
    audit_service: Annotated[AuditService, Depends(get_audit_service)],
) -> InvoiceService:
    return InvoiceService(
        session=session,
        invoice_repository=InvoiceRepository(session),
        contractor_repository=ContractorRepository(session),
        contractor_override_repository=ContractorOverrideRepository(session),
        audit_service=audit_service,
        stock_service=StockService(
            session=session,
            stock_repository=StockRepository(session),
        ),
    )


def get_idempotency_service(
    session: Annotated[Session, Depends(get_db_session)],
) -> IdempotencyService:
    return IdempotencyService(
        session=session,
        idempotency_repository=IdempotencyRepository(session),
    )


def get_ksef_client() -> KSeFClient:
    return KSeFClient(
        environment=settings.ksef_environment,
        timeout_seconds=settings.ksef_timeout_seconds,
        retry_config=RetryConfig(),
    )


def get_ksef_session_service(
    session: Annotated[Session, Depends(get_db_session)],
    audit_service: Annotated[AuditService, Depends(get_audit_service)],
) -> KSeFSessionService:
    return KSeFSessionService(
        session=session,
        auth_provider=KSeFAuthProvider(
            environment=settings.ksef_environment,
            timeout_seconds=settings.ksef_timeout_seconds,
        ),
        ksef_client=KSeFClient(
            environment=settings.ksef_environment,
            timeout_seconds=settings.ksef_timeout_seconds,
            retry_config=RetryConfig(),
        ),
        audit_service=audit_service,
        invoice_repository=InvoiceRepository(session),
    )


def get_transmission_service(
    session: Annotated[Session, Depends(get_db_session)],
    audit_service: Annotated[AuditService, Depends(get_audit_service)],
    ksef_session_service: Annotated[KSeFSessionService, Depends(get_ksef_session_service)],
) -> TransmissionService:
    return TransmissionService(
        session=session,
        transmission_repository=TransmissionRepository(session),
        invoice_repository=InvoiceRepository(session),
        job_repository=JobRepository(session),
        audit_service=audit_service,
        ksef_session_service=ksef_session_service,
    )


def get_payment_service(
    session: Annotated[Session, Depends(get_db_session)],
    audit_service: Annotated[AuditService, Depends(get_audit_service)],
) -> PaymentService:
    return PaymentService(
        session=session,
        bank_transaction_repository=BankTransactionRepository(session),
        allocation_repository=PaymentAllocationRepository(session),
        invoice_repository=InvoiceRepository(session),
        audit_service=audit_service,
    )


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(http_bearer)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> AuthenticatedUser:
    if credentials is None:
        raise UnauthorizedError("Brak tokenu dostepu.")

    return auth_service.get_authenticated_user(credentials.credentials)


def get_stock_service(
    session: Annotated[Session, Depends(get_db_session)],
) -> StockService:
    return StockService(
        session=session,
        stock_repository=StockRepository(session),
    )

