import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any, Callable

# NOTE: correlation lives in app.aws.correlation. It is imported lazily (see
# ``_correlation_fields``) so the core logging layer does not depend on the AWS
# layer at import time — importing it eagerly creates a circular import
# (core.logging -> aws.* -> core.logging) whenever a core/db module is imported
# before the aws package.
_correlation_provider: Callable[[], dict[str, str]] | None = None


def _correlation_fields() -> dict[str, str]:
    """Return correlation fields, resolving the provider lazily and safely."""
    global _correlation_provider
    if _correlation_provider is None:
        try:
            from app.aws.correlation import get_correlation_fields
        except Exception:  # pragma: no cover - only during import bootstrap
            return {}
        _correlation_provider = get_correlation_fields
    return _correlation_provider()


_LOG_RECORD_STANDARD_ATTRS = {
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "module",
    "msecs",
    "message",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "taskName",
    "thread",
    "threadName",
}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Correlation fields (run_id, lambda, sfn) — never overwrite explicit extras.
        for key, value in _correlation_fields().items():
            payload.setdefault(key, value)

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        for key, value in record.__dict__.items():
            if key not in _LOG_RECORD_STANDARD_ATTRS and not key.startswith("_"):
                payload[key] = value

        return json.dumps(payload, ensure_ascii=False, default=str)


def setup_logging(level: str = "INFO") -> None:
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(level.upper())

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root_logger.addHandler(handler)

    for logger_name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        uvicorn_logger = logging.getLogger(logger_name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
