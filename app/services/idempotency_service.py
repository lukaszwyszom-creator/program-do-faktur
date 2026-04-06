from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.persistence.repositories.idempotency_repository import IdempotencyRepository

logger = logging.getLogger(__name__)

DEFAULT_TTL_HOURS: int = 24

STATUS_PENDING = "pending"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"


class DuplicateRequestError(Exception):
    """Zgłaszany gdy klucz idempotencji ma status PENDING (duplikat w toku)."""


class IdempotencyService:
    def __init__(
        self,
        session: Session,
        idempotency_repository: IdempotencyRepository,
    ) -> None:
        self.session = session
        self.idempotency_repository = idempotency_repository

    # -------------------------------------------------------------------------
    # PUBLIC API
    # -------------------------------------------------------------------------

    def acquire(
        self,
        scope: str,
        idempotency_key: str,
        request_body: dict | None = None,
    ) -> dict | None:
        """
        Spróbuj zarejestrować klucz idempotencji.

        Returns:
            None — klucz nie istnieje, przetworz żądanie
            dict — odpowiedź z poprzedniego (zakończonego) żądania
        Raises:
            DuplicateRequestError — klucz istnieje ze statusem PENDING
        """
        try:
            existing = self.idempotency_repository.get_by_scope_and_key(
                scope, idempotency_key
            )

            if existing is None:
                body_hash = (
                    self._hash_body(request_body) if request_body is not None else None
                )
                self.idempotency_repository.add(
                    scope=scope,
                    key=idempotency_key,
                    status=STATUS_PENDING,
                    body_hash=body_hash,
                    expires_at=datetime.now(UTC) + timedelta(hours=DEFAULT_TTL_HOURS),
                )
                self.session.flush()
                return None

            if existing.status == STATUS_PENDING:
                raise DuplicateRequestError(
                    f"Żądanie z kluczem '{idempotency_key}' jest już przetwarzane."
                )

            if existing.status == STATUS_COMPLETED:
                snapshot = getattr(existing, "response_snapshot_json", None)
                if snapshot:
                    return snapshot

            # STATUS_FAILED lub COMPLETED bez snapshotu — pozwól ponownie przetworzyć
            self.idempotency_repository.update_status(
                existing, STATUS_PENDING, response_snapshot=None
            )
            self.session.flush()
            return None

        except DuplicateRequestError:
            raise
        except IntegrityError as exc:
            raise DuplicateRequestError(
                f"Duplikat klucza idempotencji '{idempotency_key}'."
            ) from exc

    def complete(
        self,
        scope: str,
        key: str,
        entity_type: str,
        entity_id: str,
        response_snapshot: dict | None = None,
    ) -> None:
        existing = self.idempotency_repository.get_by_scope_and_key(scope, key)
        if existing is None:
            logger.warning("Idempotency record not found: scope=%s key=%s", scope, key)
            return
        self.idempotency_repository.update_status(
            existing,
            STATUS_COMPLETED,
            entity_type=entity_type,
            entity_id=entity_id,
            response_snapshot=response_snapshot,
        )

    def fail(self, scope: str, key: str) -> None:
        existing = self.idempotency_repository.get_by_scope_and_key(scope, key)
        if existing is None:
            return
        self.idempotency_repository.update_status(existing, STATUS_FAILED)

    # -------------------------------------------------------------------------
    # PRIVATE HELPERS
    # -------------------------------------------------------------------------

    @staticmethod
    def _hash_body(body: dict) -> str:
        serialized = json.dumps(body, sort_keys=True, ensure_ascii=True)
        return hashlib.sha256(serialized.encode()).hexdigest()
