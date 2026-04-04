class TransmissionService:
    def __init__(self, transmission_repository, audit_service, idempotency_service) -> None:
        self.transmission_repository = transmission_repository
        self.audit_service = audit_service
        self.idempotency_service = idempotency_service
