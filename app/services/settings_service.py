from __future__ import annotations

import re

from sqlalchemy.orm import Session

from app.core.config import settings as env_settings
from app.core.exceptions import ValidationError
from app.persistence.models.app_settings import AppSettingsORM
from app.persistence.repositories.app_settings_repository import AppSettingsRepository

_NIP_RE = re.compile(r"^\d{10}$")

# Pola które serwis obsługuje (guard przed przypadkowym nadpisaniem)
_ALLOWED_FIELDS = frozenset(
    {
        "seller_nip",
        "seller_name",
        "seller_street",
        "seller_building_no",
        "seller_apartment_no",
        "seller_postal_code",
        "seller_city",
        "seller_country",
    }
)


class SettingsService:
    def __init__(self, session: Session, repository: AppSettingsRepository) -> None:
        self.session = session
        self.repository = repository

    # ------------------------------------------------------------------
    # PUBLIC API
    # ------------------------------------------------------------------

    def get_settings(self) -> dict:
        """Zwraca ustawienia: DB-first, fallback do zmiennych środowiskowych."""
        row = self.repository.get()
        return self._merge(row)

    def update_settings(self, data: dict) -> dict:
        """Waliduje i utrwala część ustawień w DB.

        Przyjmuje tylko pola z _ALLOWED_FIELDS — pozostałe są ignorowane.
        """
        filtered = {k: v for k, v in data.items() if k in _ALLOWED_FIELDS}
        if not filtered:
            raise ValidationError("Brak rozpoznanych pól do aktualizacji.")

        if "seller_nip" in filtered and filtered["seller_nip"] is not None:
            nip = filtered["seller_nip"]
            if not _NIP_RE.match(nip):
                raise ValidationError(
                    f"seller_nip musi składać się dokładnie z 10 cyfr, otrzymano: {nip!r}"
                )

        row = self.repository.upsert(filtered)
        return self._merge(row)

    # ------------------------------------------------------------------
    # PRIVATE
    # ------------------------------------------------------------------

    def _merge(self, row: AppSettingsORM | None) -> dict:
        """Scala DB z env: DB ma pierwszeństwo, env jako fallback."""
        env = env_settings

        def db_or_env(db_val: str | None, env_val: str | None) -> str | None:
            return db_val if db_val is not None else env_val

        return {
            "seller_nip": db_or_env(
                row.seller_nip if row else None, env.seller_nip
            ),
            "seller_name": db_or_env(
                row.seller_name if row else None, env.seller_name
            ),
            "seller_street": db_or_env(
                row.seller_street if row else None, env.seller_street
            ),
            "seller_building_no": db_or_env(
                row.seller_building_no if row else None, env.seller_building_no
            ),
            "seller_apartment_no": db_or_env(
                row.seller_apartment_no if row else None, env.seller_apartment_no
            ),
            "seller_postal_code": db_or_env(
                row.seller_postal_code if row else None, env.seller_postal_code
            ),
            "seller_city": db_or_env(
                row.seller_city if row else None, env.seller_city
            ),
            "seller_country": db_or_env(
                row.seller_country if row else None, env.seller_country or "PL"
            ),
            # źródło: tylko env (nie edytowalne przez API)
            "ksef_environment": env.ksef_environment,
            "app_env": env.app_env,
            "app_version": env.app_version,
        }
