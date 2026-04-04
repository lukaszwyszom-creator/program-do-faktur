class IdempotencyService:
    def __init__(self, idempotency_repository) -> None:
        self.idempotency_repository = idempotency_repository
