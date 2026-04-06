"""Testy middleware RequestIdMiddleware + correlation ID w audit."""
from __future__ import annotations

from app.core.middleware import request_id_ctx, RequestIdMiddleware


class TestRequestIdContext:
    def test_default_empty(self):
        # contextvars default
        assert request_id_ctx.get("") == ""

    def test_set_and_get(self):
        token = request_id_ctx.set("test-request-123")
        try:
            assert request_id_ctx.get() == "test-request-123"
        finally:
            request_id_ctx.reset(token)

    def test_reset_restores_default(self):
        token = request_id_ctx.set("abc")
        request_id_ctx.reset(token)
        assert request_id_ctx.get("") == ""
