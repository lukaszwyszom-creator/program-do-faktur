from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routers.auth import router as auth_router
from app.api.routers.contractors import router as contractors_router
from app.api.routers.frontend import get_favicon_path
from app.api.routers.frontend import router as frontend_router
from app.api.routers.health import router as health_router
from app.api.routers.invoices import router as invoices_router
from app.api.routers.ksef_session import router as ksef_session_router
from app.api.routers.ksef_session import router_sessions as ksef_sessions_router
from app.api.routers.metrics import router as metrics_router
from app.api.routers.payments import router as payments_router
from app.api.routers.settings import router as settings_router
from app.api.routers.stock import router as stock_router
from app.api.routers.transmissions import router as transmissions_router
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestIdMiddleware
from app.persistence.db import session_scope
from app.persistence.repositories.user_repository import UserRepository
from app.services.auth_service import AuthService

_FRONTEND_STATIC = Path(__file__).parent.parent / "frontend" / "static"


@asynccontextmanager
async def application_lifespan(_: FastAPI) -> AsyncIterator[None]:
    configure_logging(settings.log_level, alert_webhook_url=settings.alert_webhook_url)

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
        version=settings.app_version,
        lifespan=application_lifespan,
    )

    application.add_middleware(RequestIdMiddleware)
    register_exception_handlers(application)

    application.include_router(health_router)
    application.include_router(metrics_router)
    application.include_router(frontend_router)
    application.include_router(auth_router, prefix=settings.api_v1_prefix)

    @application.get("/favicon.ico", include_in_schema=False)
    def favicon() -> FileResponse:
        return FileResponse(get_favicon_path(), media_type="image/x-icon")

    application.include_router(contractors_router, prefix=settings.api_v1_prefix)
    application.include_router(invoices_router, prefix=settings.api_v1_prefix)
    application.include_router(transmissions_router, prefix=settings.api_v1_prefix)
    application.include_router(settings_router, prefix=settings.api_v1_prefix)

    if settings.enable_ksef:
        application.include_router(ksef_session_router, prefix=settings.api_v1_prefix)
        application.include_router(ksef_sessions_router, prefix=settings.api_v1_prefix)

    if settings.enable_payments:
        application.include_router(payments_router, prefix=settings.api_v1_prefix)

    if settings.enable_warehouse:
        application.include_router(stock_router, prefix=settings.api_v1_prefix)

    # Statyczne pliki frontendu (CSS, JS)
    if _FRONTEND_STATIC.exists():
        application.mount(
            "/ui/static",
            StaticFiles(directory=_FRONTEND_STATIC),
            name="frontend_static",
        )

    return application


app = create_application()
