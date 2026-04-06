from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.persistence.models.idempotency_key import IdempotencyKeyORM


class IdempotencyRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_scope_and_key(
        self, scope: str, idempotency_key: str
    ) -> IdempotencyKeyORM | None:
        stmt = select(IdempotencyKeyORM).where(
            IdempotencyKeyORM.scope == scope,
            IdempotencyKeyORM.idempotency_key == idempotency_key,
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def add(
        self,
        scope: str,
        key: str,
        status: str,
        body_hash: str | None = None,
        expires_at: datetime | None = None,
    ) -> IdempotencyKeyORM:
        orm = IdempotencyKeyORM(
            id=uuid4(),
            scope=scope,
            idempotency_key=key,
            request_hash=body_hash,
            status=status,
            expires_at=expires_at,
        )
        self.session.add(orm)
        return orm

    def update_status(
        self,
        orm: IdempotencyKeyORM,
        status: str,
        entity_type: str | None = None,
        entity_id: str | None = None,
        response_snapshot: dict | None = None,
    ) -> None:
        orm.status = status
        if entity_type is not None:
            orm.entity_type = entity_type
        if entity_id is not None:
            orm.entity_id = entity_id
        if response_snapshot is not None:
            orm.response_snapshot_json = response_snapshot
