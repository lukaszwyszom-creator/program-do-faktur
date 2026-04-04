from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routers.auth import router as auth_router
from app.api.routers.contractors import router as contractors_router
from app.api.routers.health import router as health_router
from app.api.routers.invoices import router as invoices_router
from app.api.routers.transmissions import router as transmissions_router
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.persistence.db import session_scope
from app.persistence.repositories.user_repository import UserRepository
from app.services.auth_service import AuthService


@asynccontextmanager
async def application_lifespan(_: FastAPI) -> AsyncIterator[None]:
    configure_logging(settings.log_level)

    if settings.initial_admin_username and settings.initial_admin_password:
        with session_scope() as session:
            auth_service = AuthService(session=session, user_repository=UserRepository(session))
            auth_service.bootstrap_initial_admin(
                username=settings.initial_admin_username,
                password=settings.initial_admin_password,
            )

    yield


def create_application() -> FastAPI:
    application = FastAPI(
        title=settings.app_name,
        debug=settings.debug,
        version="0.1.0",
        lifespan=application_lifespan,
    )

    register_exception_handlers(application)

    application.include_router(health_router)
    application.include_router(auth_router, prefix=settings.api_v1_prefix)
    application.include_router(contractors_router, prefix=settings.api_v1_prefix)
    application.include_router(invoices_router, prefix=settings.api_v1_prefix)
    application.include_router(transmissions_router, prefix=settings.api_v1_prefix)

    return application


app = create_application()
