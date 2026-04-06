"""Testy AuthService — unit (mocki)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.core.exceptions import UnauthorizedError
from app.services.auth_service import AuthService


@pytest.fixture()
def service(mock_session: MagicMock) -> AuthService:
    return AuthService(
        session=mock_session,
        user_repository=MagicMock(),
    )


class TestLogin:
    def test_user_not_found_raises(self, service: AuthService):
        service.user_repository.get_by_username.return_value = None
        with pytest.raises(UnauthorizedError, match="login"):
            service.login("nonexistent", "password")

    @patch("app.services.auth_service.verify_password", return_value=False)
    def test_wrong_password_raises(self, _mock_verify, service: AuthService):
        user = MagicMock()
        user.password_hash = "hashed"
        service.user_repository.get_by_username.return_value = user

        with pytest.raises(UnauthorizedError, match="login"):
            service.login("admin", "wrong")

    @patch("app.services.auth_service.verify_password", return_value=True)
    @patch("app.services.auth_service.create_access_token", return_value="token-abc")
    def test_inactive_user_raises(self, _mock_token, _mock_verify, service: AuthService):
        user = MagicMock()
        user.is_active = False
        user.password_hash = "hashed"
        service.user_repository.get_by_username.return_value = user

        with pytest.raises(UnauthorizedError, match="nieaktywne"):
            service.login("admin", "password")

    @patch("app.services.auth_service.verify_password", return_value=True)
    @patch("app.services.auth_service.create_access_token", return_value="token-abc")
    @patch("app.services.auth_service.settings")
    def test_success(self, mock_settings, _mock_token, _mock_verify, service: AuthService):
        mock_settings.access_token_expire_minutes = 30
        user = MagicMock()
        user.id = uuid4()
        user.username = "admin"
        user.role = "administrator"
        user.is_active = True
        user.password_hash = "hashed"
        service.user_repository.get_by_username.return_value = user

        result = service.login("admin", "password")
        assert result.access_token == "token-abc"
        assert result.username == "admin"


class TestGetAuthenticatedUser:
    @patch("app.services.auth_service.decode_access_token", side_effect=Exception("bad"))
    def test_invalid_token_raises(self, _mock, service: AuthService):
        with pytest.raises(UnauthorizedError, match="token"):
            service.get_authenticated_user("invalid-token")

    @patch("app.services.auth_service.decode_access_token", return_value={"sub": str(uuid4())})
    def test_user_not_found_raises(self, _mock, service: AuthService):
        service.user_repository.get_by_id.return_value = None
        with pytest.raises(UnauthorizedError, match="nie istnieje"):
            service.get_authenticated_user("some-token")

    @patch("app.services.auth_service.decode_access_token")
    def test_success(self, mock_decode, service: AuthService):
        uid = uuid4()
        mock_decode.return_value = {"sub": str(uid)}
        user = MagicMock()
        user.id = uid
        user.username = "admin"
        user.role = "administrator"
        user.is_active = True
        service.user_repository.get_by_id.return_value = user

        result = service.get_authenticated_user("valid-token")
        assert result.user_id == str(uid)
        assert result.role == "administrator"


class TestBootstrapInitialAdmin:
    def test_already_exists_returns_none(self, service: AuthService):
        service.user_repository.get_by_username.return_value = MagicMock()
        assert service.bootstrap_initial_admin("admin", "pass") is None

    @patch("app.services.auth_service.hash_password", return_value="hashed")
    def test_creates_new(self, _mock_hash, service: AuthService, mock_session: MagicMock):
        service.user_repository.get_by_username.return_value = None
        result = service.bootstrap_initial_admin("admin", "pass")
        service.user_repository.add.assert_called_once()
        mock_session.flush.assert_called_once()
        mock_session.commit.assert_not_called()
