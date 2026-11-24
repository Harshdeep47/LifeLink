"""Structured JSON logging with field redaction (spec 8.3, 8.5).

Two non-negotiables from the spec, both enforced here rather than left to the
discipline of each caller:

* Sensitive information must never reach logs, URLs or error messages.
* Every log line carries a correlation id so a request can be followed across
  API, queue and background workflow.

Redaction works on key names at any depth, so a nested payload cannot smuggle a
token through by burying it.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import UTC, datetime
from typing import Any

# Key names that are redacted anywhere they appear, at any nesting depth.
SENSITIVE_KEYS: frozenset[str] = frozenset({
    "password", "passwd", "secret", "token", "accesstoken", "refreshtoken",
    "idtoken", "authorization", "apikey", "api_key", "sessiontoken",
    "secretaccesskey", "privatekey", "credential", "credentials",
    "ssn", "aadhaar", "pan", "otp", "pin",
    # Contact details and precise location are personal data; they are logged
    # only in redacted form. Spec 4.2 also warns against storing precise
    # coordinates unnecessarily.
    "email", "phone", "mobile", "contactnumber", "contactemail",
    "latitude", "longitude", "address", "dateofbirth", "dob",
})

REDACTED = "[REDACTED]"
MAX_STRING_LENGTH = 2000


def _is_sensitive(key: str) -> bool:
    normalised = key.replace("_", "").replace("-", "").lower()
    return normalised in SENSITIVE_KEYS


def redact(value: Any, _depth: int = 0) -> Any:
    """Recursively redact sensitive keys. Depth-limited to avoid pathological input."""
    if _depth > 12:
        return "[TRUNCATED_DEPTH]"
    if isinstance(value, dict):
        return {
            k: (REDACTED if _is_sensitive(str(k)) else redact(v, _depth + 1))
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(v, _depth + 1) for v in value]
    if isinstance(value, str) and len(value) > MAX_STRING_LENGTH:
        return value[:MAX_STRING_LENGTH] + "...[TRUNCATED]"
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC)
            .isoformat()
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in ("correlation_id", "actor_id", "organization_id", "event", "duration_ms"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        extra = getattr(record, "context", None)
        if extra:
            payload["context"] = redact(extra)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str | None = None) -> None:
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel((level or os.environ.get("LOG_LEVEL") or "INFO").upper())


class ContextLogger:
    """Logger bound to a correlation id so callers cannot forget to include it."""

    def __init__(self, name: str, *, correlation_id: str,
                 actor_id: str | None = None, organization_id: str | None = None):
        self._logger = logging.getLogger(name)
        self._base = {
            "correlation_id": correlation_id,
            "actor_id": actor_id,
            "organization_id": organization_id,
        }

    def _log(self, level: int, message: str, event: str | None = None, **context):
        extra = dict(self._base)
        if event:
            extra["event"] = event
        if context:
            extra["context"] = context
        self._logger.log(level, message, extra=extra)

    def debug(self, message: str, event: str | None = None, **context):
        self._log(logging.DEBUG, message, event, **context)

    def info(self, message: str, event: str | None = None, **context):
        self._log(logging.INFO, message, event, **context)

    def warning(self, message: str, event: str | None = None, **context):
        self._log(logging.WARNING, message, event, **context)

    def error(self, message: str, event: str | None = None, **context):
        self._log(logging.ERROR, message, event, **context)

    def exception(self, message: str, event: str | None = None, **context):
        extra = dict(self._base)
        if event:
            extra["event"] = event
        if context:
            extra["context"] = context
        self._logger.exception(message, extra=extra)


def get_logger(name: str, context=None) -> ContextLogger:
    if context is None:
        return ContextLogger(name, correlation_id="no-context")
    return ContextLogger(
        name,
        correlation_id=context.correlation_id,
        actor_id=getattr(context, "actor_id", None),
        organization_id=getattr(context, "organization_id", None),
    )
