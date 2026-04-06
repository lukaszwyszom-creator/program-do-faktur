import json
import logging
import sys
import threading
import urllib.request
from datetime import UTC, datetime

_STANDARD_FIELDS = frozenset({
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "message", "taskName",
})


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", None),
            "job_id": getattr(record, "job_id", None),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        # Dodaj niestandardowe pola (np. endpoint, status_code, transaction_result)
        for key, value in record.__dict__.items():
            if key not in _STANDARD_FIELDS and not key.startswith("_"):
                if key not in payload:
                    payload[key] = value
        return json.dumps(payload, ensure_ascii=True, default=str)


class _WebhookAlertHandler(logging.Handler):
    """Wysyła alerty ERROR+ do webhooka (np. Slack, Teams) w wątku daemon."""

    def __init__(self, webhook_url: str) -> None:
        super().__init__(level=logging.ERROR)
        self._url = webhook_url

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
            payload = json.dumps({"text": message}).encode()
            req = urllib.request.Request(
                self._url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            t = threading.Thread(target=self._send, args=(req,), daemon=True)
            t.start()
        except Exception:
            self.handleError(record)

    @staticmethod
    def _send(req: urllib.request.Request) -> None:
        try:
            urllib.request.urlopen(req, timeout=5)  # noqa: S310
        except Exception:
            pass


def configure_logging(level: str, alert_webhook_url: str | None = None) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(level.upper())
    root_logger.addHandler(handler)

    if alert_webhook_url:
        alert_logger = logging.getLogger("app.alerts")
        alert_logger.addHandler(_WebhookAlertHandler(alert_webhook_url))
