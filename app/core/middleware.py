"""
Middleware: Correlation ID (X-Request-ID) + Access Log + Metryki HTTP.

Każdy request dostaje unikalny request_id:
- z nagłówka X-Request-ID (jeśli podany)
- lub generowany automatycznie (UUID4)

request_id jest:
- propagowany do LogRecord (widoczny w JSON formatter)
- dodawany do odpowiedzi HTTP jako nagłówek X-Request-ID
- dostępny w request.state.request_id

txn_result_ctx — wynik ostatniej transakcji DB w kontekście requestu:
- ustawiany przez app.persistence.db po commit/rollback
- odczytywany przez middleware do access logu
- wartości: 'commit' | 'rollback_expected' | 'rollback_unexpected' | ''
"""

from __future__ import annotations

import contextvars
import logging
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

# Context variable — dostępny z dowolnego miejsca w tym samym async/thread context
request_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default=""
)

# Wynik transakcji DB — ustawiany przez db.py, odczytywany przez middleware
txn_result_ctx: contextvars.ContextVar[str] = contextvars.ContextVar(
    "txn_result", default=""
)

_HEADER = "X-Request-ID"
_access_logger = logging.getLogger("app.access")

# Ścieżki pomijane w access logu i metrykach (monitoring overhead)
_SKIP_ACCESS_PATHS = frozenset(("/health", "/metrics"))


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Middleware dodający correlation ID, access log i podstawowe metryki."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        rid = request.headers.get(_HEADER) or uuid.uuid4().hex
        request_id_ctx.set(rid)
        txn_result_ctx.set("")  # reset per request
        request.state.request_id = rid

        response = await call_next(request)
        response.headers[_HEADER] = rid

        status = response.status_code
        path = request.url.path

        if path not in _SKIP_ACCESS_PATHS:
            _access_logger.info(
                "http.access",
                extra={
                    "method": request.method,
                    "endpoint": path,
                    "status_code": status,
                    "transaction_result": txn_result_ctx.get("") or "no_db",
                },
            )

            # Inline import aby uniknąć modułowego cyklu importu
            from app.core.metrics import counters  # noqa: PLC0415
            counters.inc_request()
            if 400 <= status < 500:
                counters.inc_4xx()
            elif status >= 500:
                counters.inc_5xx()

        return response
