from collections.abc import Generator
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import UnauthorizedError
from app.core.security import AuthenticatedUser
from app.persistence.db import get_session
from app.persistence.repositories.audit_repository import AuditRepository
from app.persistence.repositories.contractor_override_repository import ContractorOverrideRepository
from app.persistence.repositories.contractor_repository import ContractorRepository
from app.persistence.repositories.user_repository import UserRepository
from app.integrations.regon.client import RegonClient
from app.integrations.regon.mapper import RegonMapper
from app.services.audit_service import AuditService
from app.services.auth_service import AuthService
from app.services.contractor_service import ContractorService


http_bearer = HTTPBearer(auto_error=False)


def get_db_session() -> Generator[Session, None, None]:
    yield from get_session()


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


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(http_bearer)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> AuthenticatedUser:
    if credentials is None:
        raise UnauthorizedError("Brak tokenu dostepu.")

    return auth_service.get_authenticated_user(credentials.credentials)
