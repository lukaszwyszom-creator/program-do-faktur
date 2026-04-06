from __future__ import annotations

import logging
from datetime import UTC, datetime
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

    # -------------------------------------------------------------------------
    # PUBLIC API
    # -------------------------------------------------------------------------

    def open_session(
        self, nip: str, actor_user_id: UUID | None = None
    ) -> KSeFSessionORM:
        auth_token = settings.ksef_auth_token
        if not auth_token:
            raise AppError(
                "KSEF_AUTH_TOKEN nie jest skonfigurowany."
            )

        active = self._get_active_db_session()
        if active is not None:
            raise ConflictError(
                f"Istnieje już aktywna sesja KSeF: {active.session_reference}."
            )

        challenge_resp = self.auth_provider.get_challenge(nip)
        ksef_session = self.auth_provider.init_session(
            nip, challenge_resp["challenge"], auth_token
        )

        now = datetime.now(UTC)
        orm = KSeFSessionORM(
            id=uuid4(),
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

        self.audit_service.record(
            actor_user_id=actor_user_id,
            actor_role="system",
            event_type="ksef_session.opened",
            entity_type="ksef_session",
            entity_id=str(orm.id),
            after={"status": SESSION_ACTIVE},
        )

        return orm

    def get_active_session(self) -> KSeFSessionORM:
        orm = self._get_active_db_session()
        if orm is None:
            raise NotFoundError("Brak aktywnej sesji KSeF.")

        now = datetime.now(UTC)
        if orm.expires_at is not None and orm.expires_at <= now:
            orm.status = SESSION_EXPIRED
            self.session.flush()
            raise NotFoundError("Sesja KSeF wygasła.")

        return orm

    def get_session_token(self) -> str:
        orm = self.get_active_session()
        metadata = orm.token_metadata_json or {}
        token = metadata.get("session_token")
        if not token:
            raise AppError(
                "Brak tokenu sesji KSeF — zainicjuj sesję ponownie."
            )
        return token

    def close_session(
        self, actor_user_id: UUID | None = None
    ) -> KSeFSessionORM:
        orm = self.get_active_session()
        token = (orm.token_metadata_json or {}).get("session_token")
        self.auth_provider.terminate_session(token)

        now = datetime.now(UTC)
        orm.status = SESSION_TERMINATED
        orm.updated_at = now
        self.session.flush()

        self.audit_service.record(
            actor_user_id=actor_user_id,
            actor_role="system",
            event_type="ksef_session.closed",
            entity_type="ksef_session",
            entity_id=str(orm.id),
            after={"status": SESSION_TERMINATED},
        )

        return orm

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
        if rows:
            self.session.flush()
        return len(rows)

    # -------------------------------------------------------------------------
    # PRIVATE HELPERS
    # -------------------------------------------------------------------------

    def _get_active_db_session(self) -> KSeFSessionORM | None:
        stmt = select(KSeFSessionORM).where(
            KSeFSessionORM.status == SESSION_ACTIVE
        )
        return self.session.execute(stmt).scalar_one_or_none()
