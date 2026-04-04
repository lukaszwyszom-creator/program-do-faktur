class KSeFClient:
    def __init__(self, environment: str, timeout_seconds: int) -> None:
        self.environment = environment
        self.timeout_seconds = timeout_seconds
