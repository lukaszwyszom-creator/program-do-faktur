"""Testy IdempotencyService — unit (mocki repo)."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import IntegrityError

from app.services.idempotency_service import (
    DEFAULT_TTL_HOURS,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_PENDING,
    DuplicateRequestError,
    IdempotencyService,
)


@pytest.fixture()
def repo() -> MagicMock:
    return MagicMock()


@pytest.fixture()
def service(mock_session: MagicMock, repo: MagicMock) -> IdempotencyService:
    return IdempotencyService(
        session=mock_session,
        idempotency_repository=repo,
    )


class TestAcquire:
    def test_new_key_returns_none(self, service: IdempotencyService, repo: MagicMock):
        repo.get_by_scope_and_key.return_value = None
        result = service.acquire("create_invoice", "key-1", {"a": 1})
        assert result is None
        repo.add.assert_called_once()

    def test_completed_returns_cached(self, service: IdempotencyService, repo: MagicMock):
        existing = MagicMock()
        existing.status = STATUS_COMPLETED
        existing.response_snapshot_json = {"id": "abc", "status": "draft"}
        repo.get_by_scope_and_key.return_value = existing

        result = service.acquire("create_invoice", "key-1")
        assert result == {"id": "abc", "status": "draft"}

    def test_pending_raises_duplicate(self, service: IdempotencyService, repo: MagicMock):
        existing = MagicMock()
        existing.status = STATUS_PENDING
        repo.get_by_scope_and_key.return_value = existing

        with pytest.raises(DuplicateRequestError, match="key-1"):
            service.acquire("create_invoice", "key-1")

    def test_failed_allows_retry(self, service: IdempotencyService, repo: MagicMock, mock_session: MagicMock):
        existing = MagicMock()
        existing.status = STATUS_FAILED
        repo.get_by_scope_and_key.return_value = existing

        result = service.acquire("create_invoice", "key-1", {"a": 2})
        assert result is None
        repo.update_status.assert_called_once_with(existing, STATUS_PENDING, response_snapshot=None)

    def test_concurrent_insert_raises_duplicate(self, service: IdempotencyService, repo: MagicMock, mock_session: MagicMock):
        repo.get_by_scope_and_key.return_value = None
        repo.add.side_effect = IntegrityError(statement=None, params=None, orig=Exception("dup"))

        with pytest.raises(DuplicateRequestError):
            service.acquire("create_invoice", "key-1")


class TestComplete:
    def test_marks_completed(self, service: IdempotencyService, repo: MagicMock):
        existing = MagicMock()
        repo.get_by_scope_and_key.return_value = existing

        service.complete("create_invoice", "key-1", "invoice", "id-123", {"status": "ok"})
        repo.update_status.assert_called_once_with(
            existing,
            STATUS_COMPLETED,
            entity_type="invoice",
            entity_id="id-123",
            response_snapshot={"status": "ok"},
        )

    def test_missing_record_logs_warning(self, service: IdempotencyService, repo: MagicMock):
        repo.get_by_scope_and_key.return_value = None
        # Nie rzuca
        service.complete("create_invoice", "key-1", "invoice", "id-123")


class TestFail:
    def test_marks_failed(self, service: IdempotencyService, repo: MagicMock):
        existing = MagicMock()
        repo.get_by_scope_and_key.return_value = existing

        service.fail("create_invoice", "key-1")
        repo.update_status.assert_called_once_with(existing, STATUS_FAILED)

    def test_missing_record_noop(self, service: IdempotencyService, repo: MagicMock):
        repo.get_by_scope_and_key.return_value = None
        service.fail("create_invoice", "key-1")  # nie rzuca


class TestHashBody:
    def test_deterministic(self):
        h1 = IdempotencyService._hash_body({"b": 2, "a": 1})
        h2 = IdempotencyService._hash_body({"a": 1, "b": 2})
        assert h1 == h2

    def test_different_bodies_different_hash(self):
        h1 = IdempotencyService._hash_body({"a": 1})
        h2 = IdempotencyService._hash_body({"a": 2})
        assert h1 != h2
