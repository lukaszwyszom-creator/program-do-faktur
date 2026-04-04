from sqlalchemy.orm import Session

from app.persistence.models.audit_log import AuditLog

class AuditRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, audit_log: AuditLog) -> AuditLog:
        self.session.add(audit_log)
        self.session.flush()
        return audit_log
