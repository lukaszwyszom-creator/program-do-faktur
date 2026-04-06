"""Testy pakietu monitoringu: counters, /metrics, /health extended, access log."""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-123")


# ---------------------------------------------------------------------------
# Counters
# ---------------------------------------------------------------------------

class TestCounters:
    def setup_method(self):
        from app.core.metrics import counters
        counters.reset()

    def test_initial_all_zero(self):
        from app.core.metrics import counters
        s = counters.snapshot()
        assert all(v == 0 for v in s.values())

    def test_inc_request(self):
        from app.core.metrics import counters
        counters.inc_request()
        counters.inc_request()
        assert counters.snapshot()["requests_total"] == 2

    def test_inc_4xx(self):
        from app.core.metrics import counters
        counters.inc_4xx()
        assert counters.snapshot()["errors_4xx_total"] == 1

    def test_inc_5xx(self):
        from app.core.metrics import counters
        counters.inc_5xx()
        assert counters.snapshot()["errors_5xx_total"] == 1

    def test_inc_rollback_expected(self):
        from app.core.metrics import counters
        counters.inc_rollback_expected()
        counters.inc_rollback_expected()
        assert counters.snapshot()["rollbacks_expected_total"] == 2

    def test_inc_rollback_unexpected(self):
        from app.core.metrics import counters
        counters.inc_rollback_unexpected()
        assert counters.snapshot()["rollbacks_unexpected_total"] == 1

    def test_reset_zeroes_all(self):
        from app.core.metrics import counters
        counters.inc_request()
        counters.inc_5xx()
        counters.inc_rollback_unexpected()
        counters.reset()
        assert all(v == 0 for v in counters.snapshot().values())

    def test_snapshot_is_copy(self):
        from app.core.metrics import counters
        s1 = counters.snapshot()
        counters.inc_request()
        s2 = counters.snapshot()
        assert s1["requests_total"] == 0
        assert s2["requests_total"] == 1

    def test_thread_safety(self):
        """Równoległe inkrementy nie gubią zliczeń."""
        import threading
        from app.core.metrics import counters
        counters.reset()
        n = 500
        threads = [threading.Thread(target=counters.inc_request) for _ in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert counters.snapshot()["requests_total"] == n


# ---------------------------------------------------------------------------
# GET /metrics endpoint
# ---------------------------------------------------------------------------

class TestMetricsEndpoint:
    @pytest.fixture(autouse=True)
    def reset_counters(self):
        from app.core.metrics import counters
        counters.reset()
        yield
        counters.reset()

    @pytest.fixture
    def client(self) -> TestClient:
        from app.api.deps import get_db_session
        from app.core.config import settings
        from app.main import app

        mock_session = MagicMock()
        mock_session.execute.return_value = MagicMock()

        # Wyłącz bootstrap admina — nie wymaga działającej bazy w liłącespanie
        orig_user = settings.initial_admin_username
        orig_pass = settings.initial_admin_password
        object.__setattr__(settings, "initial_admin_username", None)
        object.__setattr__(settings, "initial_admin_password", None)

        app.dependency_overrides[get_db_session] = lambda: mock_session
        try:
            with TestClient(app, raise_server_exceptions=True) as c:
                yield c
        finally:
            app.dependency_overrides.clear()
            object.__setattr__(settings, "initial_admin_username", orig_user)
            object.__setattr__(settings, "initial_admin_password", orig_pass)

    def test_metrics_returns_200(self, client):
        r = client.get("/metrics")
        assert r.status_code == 200

    def test_metrics_content_type_text(self, client):
        r = client.get("/metrics")
        assert "text/plain" in r.headers["content-type"]

    def test_metrics_contains_all_counter_names(self, client):
        r = client.get("/metrics")
        body = r.text
        for name in (
            "requests_total",
            "errors_4xx_total",
            "errors_5xx_total",
            "rollbacks_expected_total",
            "rollbacks_unexpected_total",
        ):
            assert name in body, f"'{name}' not found in /metrics"

    def test_metrics_increments_on_requests(self, client):
        from app.core.metrics import counters
        counters.reset()
        # /metrics i /health są wykluczone z liczenia — użyj nieistniejącego endpointu
        client.get("/api/v1/invoices")  # 401 (brak tokena) → liczy się jako request
        snap = counters.snapshot()
        assert snap["requests_total"] >= 1
        assert snap["errors_4xx_total"] >= 1

    def test_metrics_not_in_openapi_schema(self, client):
        r = client.get("/openapi.json")
        assert "/metrics" not in r.text


# ---------------------------------------------------------------------------
# GET /health extended
# ---------------------------------------------------------------------------

class TestHealthExtended:
    @pytest.fixture
    def client_with_mock_db(self) -> TestClient:
        from app.api.deps import get_db_session
        from app.core.config import settings
        from app.main import app

        # SHOW timezone: scalar_one_or_none() zwraca "UTC"
        tz_result = MagicMock()
        tz_result.scalar_one_or_none.return_value = "UTC"
        mock_session = MagicMock()
        mock_session.execute.return_value = tz_result

        # Wyłącz bootstrap admina
        orig_user = settings.initial_admin_username
        orig_pass = settings.initial_admin_password
        object.__setattr__(settings, "initial_admin_username", None)
        object.__setattr__(settings, "initial_admin_password", None)

        app.dependency_overrides[get_db_session] = lambda: mock_session
        try:
            with TestClient(app, raise_server_exceptions=True) as c:
                yield c
        finally:
            app.dependency_overrides.clear()
            object.__setattr__(settings, "initial_admin_username", orig_user)
            object.__setattr__(settings, "initial_admin_password", orig_pass)

    def test_health_200(self, client_with_mock_db):
        r = client_with_mock_db.get("/health")
        assert r.status_code == 200

    def test_health_contains_status_ok(self, client_with_mock_db):
        r = client_with_mock_db.get("/health")
        assert r.json()["status"] == "ok"

    def test_health_contains_app_version(self, client_with_mock_db):
        r = client_with_mock_db.get("/health")
        assert "app_version" in r.json()

    def test_health_contains_db_timezone(self, client_with_mock_db):
        r = client_with_mock_db.get("/health")
        data = r.json()
        assert "db_timezone" in data

    def test_health_db_timezone_utc_flag(self, client_with_mock_db):
        r = client_with_mock_db.get("/health")
        data = r.json()
        # db_timezone_utc może być True/False/None (None = SQLite)
        assert "db_timezone_utc" in data

    def test_health_db_timezone_utc_true_when_utc(self, client_with_mock_db):
        r = client_with_mock_db.get("/health")
        data = r.json()
        # Nasz mock zwraca "UTC" → powinno być True
        if data["db_timezone"] is not None:
            assert data["db_timezone_utc"] is True

    def test_health_environment_present(self, client_with_mock_db):
        r = client_with_mock_db.get("/health")
        assert "environment" in r.json()


# ---------------------------------------------------------------------------
# txn_result_ctx — context variable
# ---------------------------------------------------------------------------

class TestTxnResultCtx:
    def test_default_empty(self):
        from app.core.middleware import txn_result_ctx
        assert txn_result_ctx.get("") == ""

    def test_set_commit(self):
        from app.core.middleware import txn_result_ctx
        token = txn_result_ctx.set("commit")
        try:
            assert txn_result_ctx.get() == "commit"
        finally:
            txn_result_ctx.reset(token)

    def test_set_rollback_unexpected(self):
        from app.core.middleware import txn_result_ctx
        token = txn_result_ctx.set("rollback_unexpected")
        try:
            assert txn_result_ctx.get() == "rollback_unexpected"
        finally:
            txn_result_ctx.reset(token)


# ---------------------------------------------------------------------------
# JsonFormatter — extra fields
# ---------------------------------------------------------------------------

class TestJsonFormatterExtraFields:
    def test_extra_fields_in_output(self):
        import json
        import logging
        from app.core.logging import JsonFormatter

        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="http.access", args=(), exc_info=None,
        )
        record.__dict__["endpoint"] = "/api/v1/invoices"
        record.__dict__["status_code"] = 200
        record.__dict__["transaction_result"] = "commit"

        output = json.loads(formatter.format(record))
        assert output["endpoint"] == "/api/v1/invoices"
        assert output["status_code"] == 200
        assert output["transaction_result"] == "commit"

    def test_standard_fields_not_duplicated(self):
        import json
        import logging
        from app.core.logging import JsonFormatter

        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="hello", args=(), exc_info=None,
        )
        output = json.loads(formatter.format(record))
        # Standardowe pola LogRecord nie powinny być duplikowane
        assert "lineno" not in output
        assert "pathname" not in output
        assert "args" not in output


# ---------------------------------------------------------------------------
# WebhookAlertHandler
# ---------------------------------------------------------------------------

class TestWebhookAlertHandler:
    def test_emit_posts_to_url(self):
        import logging
        from app.core.logging import _WebhookAlertHandler

        handler = _WebhookAlertHandler("http://example.com/webhook")
        record = logging.LogRecord(
            name="app.alerts", level=logging.ERROR, pathname="", lineno=0,
            msg="db.rollback.unexpected", args=(), exc_info=None,
        )
        # Mockujemy urlopen żeby nie robić sieci
        with patch("urllib.request.urlopen") as mock_urlopen:
            handler.emit(record)
            import time; time.sleep(0.05)  # daemon thread
            # urlopen powinien być wywołany raz
            assert mock_urlopen.called

    def test_emit_swallows_network_error(self):
        import logging
        from app.core.logging import _WebhookAlertHandler

        handler = _WebhookAlertHandler("http://unreachable.invalid/")
        record = logging.LogRecord(
            name="app.alerts", level=logging.ERROR, pathname="", lineno=0,
            msg="test alert", args=(), exc_info=None,
        )
        # Nie rzuca wyjątku nawet przy błędzie sieci
        handler.emit(record)
        import time; time.sleep(0.05)
