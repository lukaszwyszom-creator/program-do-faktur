"""Process-wide in-memory counters.

Brak zewnętrznych zależności — działa na każdej instalacji.
Eksponowane przez GET /metrics w formacie Prometheus plain-text.
Liczniki są zerowane przy restarcie procesu (jednoprocesorowy model uvicorn workers).

Dla multi-worker deploymentu każdy worker trzyma własne liczniki;
zsumowane wartości wymagają Prometheus push-gateway lub persystencji zewnętrznej.
"""
from __future__ import annotations

import threading


class _Counters:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.requests_total: int = 0
        self.errors_4xx_total: int = 0
        self.errors_5xx_total: int = 0
        self.rollbacks_expected_total: int = 0
        self.rollbacks_unexpected_total: int = 0

    def _inc(self, attr: str) -> None:
        with self._lock:
            setattr(self, attr, getattr(self, attr) + 1)

    def inc_request(self) -> None:
        self._inc("requests_total")

    def inc_4xx(self) -> None:
        self._inc("errors_4xx_total")

    def inc_5xx(self) -> None:
        self._inc("errors_5xx_total")

    def inc_rollback_expected(self) -> None:
        self._inc("rollbacks_expected_total")

    def inc_rollback_unexpected(self) -> None:
        self._inc("rollbacks_unexpected_total")

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return {
                "requests_total": self.requests_total,
                "errors_4xx_total": self.errors_4xx_total,
                "errors_5xx_total": self.errors_5xx_total,
                "rollbacks_expected_total": self.rollbacks_expected_total,
                "rollbacks_unexpected_total": self.rollbacks_unexpected_total,
            }

    def reset(self) -> None:
        """Resetuje liczniki — wyłącznie do testów."""
        with self._lock:
            self.requests_total = 0
            self.errors_4xx_total = 0
            self.errors_5xx_total = 0
            self.rollbacks_expected_total = 0
            self.rollbacks_unexpected_total = 0


counters = _Counters()
