"""Testy KSeFSessionService — unit (mocki)."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from app.core.exceptions import AppError, ConflictError, NotFoundError
from app.integrations.ksef.auth import KSeFSession
from app.services.ksef_session_service import (
    SESSION_ACTIVE,
    SESSION_EXPIRED,
    SESSION_TERMINATED,
    KSeFSessionService,
)


@pytest.fixture()
def auth_provider() -> MagicMock:
    provider = MagicMock()
    provider.environment = "test"
    return provider


@pytest.fixture()
def service(mock_session: MagicMock, auth_provider: MagicMock) -> KSeFSessionService:
    return KSeFSessionService(
        session=mock_session,
        auth_provider=auth_provider,
        audit_service=MagicMock(),
    )


class TestOpenSession:
    @patch("app.services.ksef_session_service.settings")
    def test_no_auth_token_raises(self, mock_settings, service: KSeFSessionService):
        mock_settings.ksef_auth_token = None
        with pytest.raises(AppError, match="KSEF_AUTH_TOKEN"):
            service.open_session("1234567890")

    @patch("app.services.ksef_session_service.settings")
    def test_active_session_exists_raises(self, mock_settings, service: KSeFSessionService, mock_session: MagicMock):
        mock_settings.ksef_auth_token = "token"
        active = MagicMock()
        active.session_reference = "ref-123"

        # Mock _get_active_session
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = active
        mock_session.execute.return_value = mock_result

        with pytest.raises(ConflictError, match="aktywna sesja"):
            service.open_session("1234567890")

    @patch("app.services.ksef_session_service.settings")
    def test_success(self, mock_settings, service: KSeFSessionService, auth_provider: MagicMock, mock_session: MagicMock):
        mock_settings.ksef_auth_token = "token"

        # Brak aktywnej sesji
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        auth_provider.get_challenge.return_value = {"challenge": "ch-1", "timestamp": "ts"}
        auth_provider.init_session.return_value = KSeFSession(
            session_token="sess-tok",
            session_reference="ref-new",
            expires_at=None,
        )

        result = service.open_session("1234567890")
        assert result.session_reference == "ref-new"
        assert result.status == SESSION_ACTIVE
        mock_session.add.assert_called_once()


class TestGetActiveSession:
    def test_no_active_raises(self, service: KSeFSessionService, mock_session: MagicMock):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        with pytest.raises(NotFoundError, match="Brak aktywnej"):
            service.get_active_session("1234567890")

    def test_expired_session_raises(self, service: KSeFSessionService, mock_session: MagicMock):
        orm = MagicMock()
        orm.status = SESSION_ACTIVE
        orm.nip = "1234567890"
        orm.expires_at = datetime.now(UTC) - timedelta(minutes=10)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = orm
        mock_session.execute.return_value = mock_result

        with pytest.raises(NotFoundError, match="wygasła"):
            service.get_active_session("1234567890")
        assert orm.status == SESSION_EXPIRED


class TestGetSessionToken:
    def test_returns_token(self, service: KSeFSessionService, mock_session: MagicMock):
        orm = MagicMock()
        orm.expires_at = datetime.now(UTC) + timedelta(hours=1)
        orm.token_metadata_json = {"session_token": "tok-123"}
        orm.nip = "1234567890"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = orm
        mock_session.execute.return_value = mock_result

        assert service.get_session_token("1234567890") == "tok-123"

    def test_no_token_in_metadata_raises(self, service: KSeFSessionService, mock_session: MagicMock):
        orm = MagicMock()
        orm.expires_at = datetime.now(UTC) + timedelta(hours=1)
        orm.token_metadata_json = {}
        orm.nip = "1234567890"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = orm
        mock_session.execute.return_value = mock_result

        with pytest.raises(AppError, match="tokenu"):
            service.get_session_token("1234567890")


class TestCloseSession:
    def test_success(self, service: KSeFSessionService, auth_provider: MagicMock, mock_session: MagicMock):
        orm = MagicMock()
        orm.expires_at = datetime.now(UTC) + timedelta(hours=1)
        orm.token_metadata_json = {"session_token": "tok"}
        orm.session_reference = "ref"
        orm.nip = "1234567890"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = orm
        mock_session.execute.return_value = mock_result

        result = service.close_session("1234567890")
        assert result.status == SESSION_TERMINATED
        auth_provider.terminate_session.assert_called_once_with("tok")


class TestGetSessionById:
    def test_not_found_raises(self, service: KSeFSessionService, mock_session: MagicMock):
        mock_session.get.return_value = None
        with pytest.raises(NotFoundError):
            service.get_session_by_id(uuid.uuid4())

    def test_found(self, service: KSeFSessionService, mock_session: MagicMock):
        orm = MagicMock()
        mock_session.get.return_value = orm
        assert service.get_session_by_id(uuid.uuid4()) == orm
