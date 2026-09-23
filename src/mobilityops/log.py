"""Structured (JSON) logging on the standard library.

One JSON object per line, so logs are greppable locally and parseable by any log tool. Extra
context goes in via ``logger.info("msg", extra={"ctx": {...}})``. Values whose key looks like a
secret are redacted, so a stray ``api_key`` in context can never reach the log.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

_SECRET_HINTS = ("key", "token", "secret", "password", "authorization")
_RESERVED = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "message",
    "asctime",
    "ctx",
}


def redact(value: Any, key: str = "") -> Any:
    """Recursively replace anything that looks like a secret with a placeholder."""
    if any(h in key.lower() for h in _SECRET_HINTS):
        return "***redacted***"
    if isinstance(value, dict):
        return {k: redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [redact(v, key) for v in value]
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        ctx = getattr(record, "ctx", None)
        if isinstance(ctx, dict):
            payload.update(redact(ctx))
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    """Idempotent: safe to call more than once (tests, API startup, CLI)."""
    root = logging.getLogger("mobilityops")
    root.setLevel(level)
    root.propagate = False
    if not any(isinstance(h.formatter, JsonFormatter) for h in root.handlers):
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(JsonFormatter())
        root.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"mobilityops.{name}")
