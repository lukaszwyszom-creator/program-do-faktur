from collections.abc import Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    status_code = 400
    code = "application_error"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class UnauthorizedError(AppError):
    status_code = 401
    code = "unauthorized"


class ExternalServiceError(AppError):
    status_code = 502
    code = "external_service_error"


def register_exception_handlers(app: FastAPI) -> None:
    def build_handler() -> Callable[[Request, AppError], JSONResponse]:
        async def handler(_: Request, exc: AppError) -> JSONResponse:
            return JSONResponse(
                status_code=exc.status_code,
                content={"error": {"code": exc.code, "message": exc.message}},
            )

        return handler

    app.add_exception_handler(AppError, build_handler())
