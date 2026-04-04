class InvoiceService:
    def __init__(self, invoice_repository, audit_service, idempotency_service) -> None:
        self.invoice_repository = invoice_repository
        self.audit_service = audit_service
        self.idempotency_service = idempotency_service
