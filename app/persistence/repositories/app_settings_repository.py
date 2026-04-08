from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.persistence.models.app_settings import AppSettingsORM


class AppSettingsRepository:
    """Obsługuje singleton wiersz w tabeli app_settings (id zawsze = 1)."""

    _SINGLETON_ID = 1

    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self) -> AppSettingsORM | None:
        return self.session.get(AppSettingsORM, self._SINGLETON_ID)

    def upsert(self, data: dict) -> AppSettingsORM:
        """Wstaw lub zaktualizuj singleton wiersz z podanymi polami."""
        stmt = (
            pg_insert(AppSettingsORM)
            .values(id=self._SINGLETON_ID, **data)
            .on_conflict_do_update(
                index_elements=["id"],
                set_={k: v for k, v in data.items()},
            )
            .returning(AppSettingsORM)
        )
        row = self.session.execute(stmt).scalar_one()
        self.session.flush()
        return row
