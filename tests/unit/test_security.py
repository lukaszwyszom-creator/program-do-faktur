"""Testy security — hash/verify, JWT tokens."""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

import pytest

from app.core.security import (
    AuthenticatedUser,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


class TestPasswordHashing:
    def test_hash_and_verify(self):
        pw = "MojeHasło123!"
        hashed = hash_password(pw)
        assert hashed != pw
        assert verify_password(pw, hashed) is True

    def test_wrong_password(self):
        hashed = hash_password("correct")
        assert verify_password("wrong", hashed) is False


class TestJWT:
    @patch("app.core.security.settings")
    def test_roundtrip(self, mock_settings):
        mock_settings.jwt_secret_key = "test-secret"
        mock_settings.jwt_algorithm = "HS256"
        mock_settings.access_token_expire_minutes = 30

        token = create_access_token(
            subject="user-123",
            expires_delta=timedelta(minutes=5),
            additional_claims={"role": "admin"},
        )
        payload = decode_access_token(token)
        assert payload["sub"] == "user-123"
        assert payload["role"] == "admin"

    @patch("app.core.security.settings")
    def test_expired_token_raises(self, mock_settings):
        mock_settings.jwt_secret_key = "test-secret"
        mock_settings.jwt_algorithm = "HS256"

        token = create_access_token(
            subject="user-123",
            expires_delta=timedelta(seconds=-1),
        )
        with pytest.raises(Exception):
            decode_access_token(token)

    @patch("app.core.security.settings")
    def test_tampered_token_raises(self, mock_settings):
        mock_settings.jwt_secret_key = "test-secret"
        mock_settings.jwt_algorithm = "HS256"

        token = create_access_token(subject="user-123", expires_delta=timedelta(minutes=5))
        tampered = token[:-4] + "XXXX"
        with pytest.raises(Exception):
            decode_access_token(tampered)


class TestAuthenticatedUser:
    def test_frozen(self):
        user = AuthenticatedUser(user_id="1", username="admin", role="administrator")
        with pytest.raises(AttributeError):
            user.role = "operator"
