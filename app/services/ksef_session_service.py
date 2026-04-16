from __future__ import annotations

import base64
import logging
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import AppError, ConflictError, ExternalServiceError, NotFoundError
from app.integrations.ksef.auth import KSeFAuthError, KSeFAuthProvider
from app.integrations.ksef.client import KSeFClient, KSeFClientError
from app.persistence.models.ksef_session import KSeFSessionORM
from app.services.audit_service import AuditService

logger = logging.getLogger(__name__)

SESSION_ACTIVE = "active"
SESSION_TERMINATED = "terminated"
SESSION_EXPIRED = "expired"
SESSION_FAILED = "failed"

# Margines przed wygaśnięciem — token uznajemy za ważny jeśli trwa > MARGIN
_TOKEN_CACHE_MARGIN = timedelta(seconds=30)

# Klucze w token_metadata_json
_KEY_ACCESS_TOKEN = "access_token"
_KEY_REFRESH_TOKEN = "refresh_token"
_KEY_REFRESH_VALID = "refresh_valid_until"
_KEY_SYMMETRIC_KEY = "symmetric_key"
_KEY_IV = "initialization_vector"


@dataclass
class KSeFSessionContext:
    """Kontekst potrzebny do operacji na fakturach w danej sesji KSeF."""

    access_token: str
    session_reference: str
    symmetric_key: bytes
    initialization_vector: bytes


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
        ksef_client: KSeFClient,
        audit_service: AuditService,
    ) -> None:
        self.session = session
        self.auth_provider = auth_provider
        self.ksef_client = ksef_client
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

        # 1. Uwierzytelnienie → access token + refresh token
        try:
            ksef_session = self.auth_provider.get_tokens(nip, auth_token)
        except KSeFAuthError as exc:
            raise ExternalServiceError(f"Błąd uwierzytelnienia KSeF: {exc}") from exc

        # 2. Otwarcie sesji interaktywnej → session reference + klucz symetryczny
        try:
            online_session = self.ksef_client.open_online_session(ksef_session.access_token)
        except KSeFClientError as exc:
            raise ExternalServiceError(f"Błąd otwarcia sesji KSeF: {exc}") from exc

        now = datetime.now(UTC)
        expires_at = ksef_session.access_valid_until

        orm = KSeFSessionORM(
            id=uuid4(),
            nip=nip,
            environment=self.auth_provider.environment,
            auth_method="token",
            session_reference=online_session.session_reference,
            token_metadata_json={
                _KEY_ACCESS_TOKEN: ksef_session.access_token,
                _KEY_REFRESH_TOKEN: ksef_session.refresh_token,
                _KEY_REFRESH_VALID: (
                    ksef_session.refresh_valid_until.isoformat()
                    if ksef_session.refresh_valid_until else None
                ),
                _KEY_SYMMETRIC_KEY: base64.b64encode(online_session.symmetric_key).decode("ascii"),
                _KEY_IV: base64.b64encode(online_session.initialization_vector).decode("ascii"),
            },
            status=SESSION_ACTIVE,
            expires_at=expires_at,
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

    def get_session_context(self, nip: str) -> KSeFSessionContext:
        """Zwraca pełny kontekst sesji potrzebny do wysyłki faktur.

        Wynik access tokena jest cachowany (TTL = czas ważności − margines).
        """
        with self._cache_lock:
            entry = self._token_cache.get(nip)
            if entry is not None and entry.is_valid():
                # Cache ma tylko access_token — pełny kontekst musi być z DB
                pass

        orm = self.get_active_session(nip)
        metadata = orm.token_metadata_json or {}
        access_token = metadata.get(_KEY_ACCESS_TOKEN)
        symmetric_key_b64 = metadata.get(_KEY_SYMMETRIC_KEY)
        iv_b64 = metadata.get(_KEY_IV)

        if not access_token or not symmetric_key_b64 or not iv_b64:
            raise AppError(
                f"Niekompletny kontekst sesji KSeF dla NIP {nip} — "
                "zainicjuj sesję ponownie."
            )

        with self._cache_lock:
            self._token_cache[nip] = _TokenCacheEntry(access_token, orm.expires_at)

        return KSeFSessionContext(
            access_token=access_token,
            session_reference=orm.session_reference or "",
            symmetric_key=base64.b64decode(symmetric_key_b64),
            initialization_vector=base64.b64decode(iv_b64),
        )

    def get_session_token(self, nip: str) -> str:
        """Zwraca access token dla danego NIP (alias dla wstecznej zgodności)."""
        return self.get_session_context(nip).access_token

    def close_session(
        self, nip: str, actor_user_id: UUID | None = None
    ) -> KSeFSessionORM:
        orm = self.get_active_session(nip)
        metadata = orm.token_metadata_json or {}
        access_token = metadata.get(_KEY_ACCESS_TOKEN, "")
        self.ksef_client.close_online_session(access_token, orm.session_reference or "")

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
        """Oznacza aktywną sesję KSeF dla danego NIP jako wygasłą."""
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
