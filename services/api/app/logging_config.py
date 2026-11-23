"""Structured request-aware JSON logging."""

import json
import logging
import sys
from contextvars import ContextVar, Token
from datetime import UTC, datetime

request_id_context: ContextVar[str] = ContextVar("request_id", default="-")


class JsonFormatter(logging.Formatter):
    """Format a small allowlist of operational fields as JSON."""

    allowed_fields = ("method", "route_group", "status_code", "duration_ms", "error_type")

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, str | int | float] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_context.get(),
        }
        for field in self.allowed_fields:
            value = getattr(record, field, None)
            if isinstance(value, (str, int, float)):
                payload[field] = value
        return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def configure_logging() -> None:
    """Configure application and Uvicorn logs without request payloads."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").disabled = True


def set_request_id(request_id: str) -> Token[str]:
    """Set the request context and return its reset token."""
    return request_id_context.set(request_id)
