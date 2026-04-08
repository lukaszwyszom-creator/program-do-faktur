from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import AppError, ConflictError, NotFoundError
from app.integrations.ksef.auth import KSeFAuthProvider
from app.persistence.models.ksef_session import KSeFSessionORM
from app.services.audit_service import AuditService

logger = logging.getLogger(__name__)

SESSION_ACTIVE = "active"
SESSION_TERMINATED = "terminated"
SESSION_EXPIRED = "expired"
SESSION_FAILED = "failed"

# Margines przed wygaśnięciem — token uznajemy za ważny jeśli trwa > MARGIN
_TOKEN_CACHE_MARGIN = timedelta(seconds=30)


class _TokenCacheEntry:
    __slots__ = ("token", "expires_at")

    def __init__(self, token: str, expires_at: datetime | None) -> None:
        self.token = token
        self.expires_at = expires_at

    def is_valid(self) -> bool:
        if self.expires_at is None:
            return True
        return datetime.now(UTC) < self.expires_at - _TOKEN_CACHE_MARGIN


class KSeFSessionService:
    def __init__(
        self,
        session: Session,
        auth_provider: KSeFAuthProvider,
        audit_service: AuditService,
    ) -> None:
        self.session = session
        self.auth_provider = auth_provider
        self.audit_service = audit_service
        # cache tokenów — klucz: nip (str), wartość: _TokenCacheEntry
        self._token_cache: dict[str, _TokenCacheEntry] = {}
        self._cache_lock = threading.Lock()

    # -------------------------------------------------------------------------
    # PUBLIC API
    # -------------------------------------------------------------------------

    def open_session(
        self, nip: str, actor_user_id: UUID | None = None
    ) -> KSeFSessionORM:
        auth_token = settings.ksef_auth_token
        if not auth_token:
            raise AppError("KSEF_AUTH_TOKEN nie jest skonfigurowany.")

        active = self._get_active_db_session(nip)
        if active is not None:
            raise ConflictError(
                f"Istnieje już aktywna sesja KSeF dla NIP {nip}: "
                f"{active.session_reference}."
            )

        challenge_resp = self.auth_provider.get_challenge(nip)
        ksef_session = self.auth_provider.init_session(
            nip, challenge_resp["challenge"], auth_token
        )

        now = datetime.now(UTC)
        orm = KSeFSessionORM(
            id=uuid4(),
            nip=nip,
            environment=self.auth_provider.environment,
            auth_method="token",
            session_reference=ksef_session.session_reference,
            token_metadata_json={"session_token": ksef_session.session_token},
            status=SESSION_ACTIVE,
            expires_at=ksef_session.expires_at,
            created_at=now,
            updated_at=now,
        )
        self.session.add(orm)
        self.session.flush()

        # Unieważnij cache dla tego NIP po otwarciu nowej sesji
        self._invalidate_cache(nip)

        self.audit_service.record(
            actor_user_id=actor_user_id,
            actor_role="system",
            event_type="ksef_session.opened",
            entity_type="ksef_session",
            entity_id=str(orm.id),
            after={"status": SESSION_ACTIVE, "nip": nip},
        )

        return orm

    def get_active_session(self, nip: str) -> KSeFSessionORM:
        orm = self._get_active_db_session(nip)
        if orm is None:
            raise NotFoundError(f"Brak aktywnej sesji KSeF dla NIP {nip}.")

        now = datetime.now(UTC)
        if orm.expires_at is not None and orm.expires_at <= now:
            orm.status = SESSION_EXPIRED
            self.session.flush()
            self._invalidate_cache(nip)
            raise NotFoundError(f"Sesja KSeF dla NIP {nip} wygasła.")

        return orm

    def get_session_token(self, nip: str) -> str:
        """Zwraca token sesji dla danego NIP.

        Wynik jest cachowany w pamięci procesu (TTL = czas ważności tokenu
        minus _TOKEN_CACHE_MARGIN). Cache jest per-NIP i thread-safe.
        """
        with self._cache_lock:
            entry = self._token_cache.get(nip)
            if entry is not None and entry.is_valid():
                return entry.token

        orm = self.get_active_session(nip)
        metadata = orm.token_metadata_json or {}
        token = metadata.get("session_token")
        if not token:
            raise AppError(
                f"Brak tokenu sesji KSeF dla NIP {nip} — zainicjuj sesję ponownie."
            )

        with self._cache_lock:
            self._token_cache[nip] = _TokenCacheEntry(token, orm.expires_at)

        return token

    def close_session(
        self, nip: str, actor_user_id: UUID | None = None
    ) -> KSeFSessionORM:
        orm = self.get_active_session(nip)
        token = (orm.token_metadata_json or {}).get("session_token")
        self.auth_provider.terminate_session(token)

        now = datetime.now(UTC)
        orm.status = SESSION_TERMINATED
        orm.updated_at = now
        self.session.flush()
        self._invalidate_cache(nip)

        self.audit_service.record(
            actor_user_id=actor_user_id,
            actor_role="system",
            event_type="ksef_session.closed",
            entity_type="ksef_session",
            entity_id=str(orm.id),
            after={"status": SESSION_TERMINATED, "nip": nip},
        )

        return orm

    def mark_session_expired(self, nip: str) -> None:
        """Oznacza aktywną sesję KSeF dla danego NIP jako wygasłą.

        Wywoływana przez worker gdy KSeF zwróci 401/403 w trakcie wysyłki.
        Nie rzuca wyjątku jeśli aktywna sesja nie istnieje.
        """
        orm = self._get_active_db_session(nip)
        if orm is not None:
            orm.status = SESSION_EXPIRED
            orm.updated_at = datetime.now(UTC)
            self.session.flush()
        self._invalidate_cache(nip)

    def get_session_by_id(self, session_id: UUID) -> KSeFSessionORM:
        orm = self.session.get(KSeFSessionORM, session_id)
        if orm is None:
            raise NotFoundError(f"Nie znaleziono sesji KSeF {session_id}.")
        return orm

    def expire_stale_sessions(self) -> int:
        now = datetime.now(UTC)
        stmt = select(KSeFSessionORM).where(
            KSeFSessionORM.status == SESSION_ACTIVE,
            KSeFSessionORM.expires_at <= now,
        )
        rows = self.session.scalars(stmt).all()
        for orm in rows:
            orm.status = SESSION_EXPIRED
            self._invalidate_cache(orm.nip)
        if rows:
            self.session.flush()
        return len(rows)

    # -------------------------------------------------------------------------
    # PRIVATE HELPERS
    # -------------------------------------------------------------------------

    def _get_active_db_session(self, nip: str) -> KSeFSessionORM | None:
        stmt = select(KSeFSessionORM).where(
            KSeFSessionORM.nip == nip,
            KSeFSessionORM.status == SESSION_ACTIVE,
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def _invalidate_cache(self, nip: str) -> None:
        with self._cache_lock:
            self._token_cache.pop(nip, None)
