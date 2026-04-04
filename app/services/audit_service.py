from sqlalchemy.orm import Session

from app.persistence.models.audit_log import AuditLog
from app.persistence.repositories.audit_repository import AuditRepository


class AuditService:
    def __init__(self, session: Session, audit_repository: AuditRepository) -> None:
        self.session = session
        self.audit_repository = audit_repository

    def record(
        self,
        *,
        actor_user_id: str | None,
        actor_role: str | None,
        event_type: str,
        entity_type: str,
        entity_id: str,
        before: dict | None = None,
        after: dict | None = None,
        metadata: dict | None = None,
    ) -> AuditLog:
        audit_log = AuditLog(
            actor_user_id=actor_user_id,
            actor_role=actor_role,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            before_json=before,
            after_json=after,
            metadata_json=metadata,
        )
        return self.audit_repository.add(audit_log)
