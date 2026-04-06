"""GET /metrics — Prometheus-compatible plain text format.

Eksponuje liczniki procesu z app.core.metrics.
Endpoint jest wyłączony ze schematu OpenAPI (nie pojawia się w /docs).

Uwaga: przy multi-worker (uvicorn --workers N) każdy worker trzyma osobne liczniki.
Do agregacji po wielu workerach użyj Prometheus push-gateway lub redis-based counters.
"""
from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

from app.core.metrics import counters

router = APIRouter(tags=["metrics"], include_in_schema=False)

_TEMPLATE = """\
# HELP requests_total Łączna liczba żądań HTTP (z wyłączeniem /health i /metrics)
# TYPE requests_total counter
requests_total {requests_total}

# HELP errors_4xx_total Liczba odpowiedzi HTTP 4xx
# TYPE errors_4xx_total counter
errors_4xx_total {errors_4xx_total}

# HELP errors_5xx_total Liczba odpowiedzi HTTP 5xx
# TYPE errors_5xx_total counter
errors_5xx_total {errors_5xx_total}

# HELP rollbacks_expected_total Rollbacki z błędów walidacyjnych i domenowych (AppError itp.)
# TYPE rollbacks_expected_total counter
rollbacks_expected_total {rollbacks_expected_total}

# HELP rollbacks_unexpected_total Rollbacki z błędów systemowych — każdy = alert
# TYPE rollbacks_unexpected_total counter
rollbacks_unexpected_total {rollbacks_unexpected_total}
"""


@router.get("/metrics", response_class=PlainTextResponse)
def prometheus_metrics() -> str:
    return _TEMPLATE.format(**counters.snapshot())
