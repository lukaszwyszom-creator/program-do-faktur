"""Testy startup-guard: Settings blokuje uruchomienie produkcji z niezabezpieczoną konfiguracją."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings

_PROD_DB = "postgresql://user:pass@localhost/db"
_SAFE_KEY = "production-ready-random-key-abc123XY-z9876543210123456"


def _make(**overrides):
    """Tworzy instancję Settings z minimalnym zestawem wymaganych pól."""
    defaults = dict(DATABASE_URL=_PROD_DB, APP_ENV="production", JWT_SECRET_KEY=_SAFE_KEY)
    defaults.update(overrides)
    return Settings(**defaults)


class TestProductionGuard:
    def test_production_safe_key_accepted(self):
        settings = _make()
        assert settings.app_env == "production"

    def test_production_missing_key_rejected(self):
        with pytest.raises((ValueError, ValidationError)):
            _make(JWT_SECRET_KEY=None)

    def test_production_short_key_rejected(self):
        with pytest.raises((ValueError, ValidationError)):
            _make(JWT_SECRET_KEY="too-short")

    def test_production_key_31_chars_rejected(self):
        with pytest.raises((ValueError, ValidationError)):
            _make(JWT_SECRET_KEY="a" * 31)

    def test_production_key_32_chars_accepted(self):
        settings = _make(JWT_SECRET_KEY="a" * 32)
        assert settings.jwt_secret_key == "a" * 32

    def test_production_change_me_pattern_rejected(self):
        with pytest.raises((ValueError, ValidationError)):
            _make(JWT_SECRET_KEY="change-me-in-production-please!!!")

    def test_production_secret_pattern_rejected(self):
        with pytest.raises((ValueError, ValidationError)):
            _make(JWT_SECRET_KEY="secret-key-for-app-running-in-prod")

    def test_production_debug_true_rejected(self):
        with pytest.raises((ValueError, ValidationError)):
            _make(DEBUG=True)

    def test_local_env_no_guard_applied(self):
        """W środowisku local brak klucza JWT jest dopuszczalny (brak wyjątku)."""
        # _env_file=None wymusza ignorowanie pliku .env, żeby test był izolowany
        settings = Settings(_env_file=None, DATABASE_URL="sqlite:///./test.db", APP_ENV="local")
        assert settings.app_env == "local"

    def test_local_env_debug_allowed(self):
        settings = Settings(_env_file=None, DATABASE_URL="sqlite:///./test.db", APP_ENV="local", DEBUG=True)
        assert settings.debug is True
