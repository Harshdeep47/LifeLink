"""Consistent API response envelopes (spec 10.2).

One success shape, one error shape, one pagination shape -- used by every
endpoint so clients can write a single response handler. Errors always carry a
stable ``code``; the human-readable message may change without breaking clients.
"""
from __future__ import annotations

import base64
import json
from typing import Any

from domain.errors import LifeLinkError

JSON_HEADERS = {
    "Content-Type": "application/json",
    "Cache-Control": "no-store",
    # Defence-in-depth headers; the CDN/API Gateway also sets these.
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


def _body(payload: dict) -> str:
    return json.dumps(payload, default=str, separators=(",", ":"))


def success(data: Any, *, status: int = 200, correlation_id: str | None = None,
            meta: dict | None = None) -> dict:
    payload: dict[str, Any] = {"data": data}
    if meta:
        payload["meta"] = meta
    if correlation_id:
        payload["correlationId"] = correlation_id
    return {
        "statusCode": status,
        "headers": dict(JSON_HEADERS),
        "body": _body(payload),
    }


def created(data: Any, *, correlation_id: str | None = None, location: str | None = None) -> dict:
    response = success(data, status=201, correlation_id=correlation_id)
    if location:
        response["headers"]["Location"] = location
    return response


def no_content() -> dict:
    return {"statusCode": 204, "headers": dict(JSON_HEADERS), "body": ""}


def error(
    code: str,
    message: str,
    *,
    status: int = 400,
    details: dict | None = None,
    correlation_id: str | None = None,
) -> dict:
    payload: dict[str, Any] = {"error": {"code": code, "message": message}}
    if details:
        payload["error"]["details"] = details
    if correlation_id:
        payload["correlationId"] = correlation_id
    return {
        "statusCode": status,
        "headers": dict(JSON_HEADERS),
        "body": _body(payload),
    }


def from_exception(exc: LifeLinkError, *, correlation_id: str | None = None) -> dict:
    return error(
        exc.code,
        exc.message,
        status=exc.http_status,
        details=exc.details or None,
        correlation_id=correlation_id,
    )


# --- Pagination (ADR: cursor-based; offset paging is not offered) -------------

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


def encode_cursor(last_evaluated_key: dict | None, query_fingerprint: str) -> str | None:
    """Opaque cursor binding the position to the query that produced it.

    Binding the fingerprint means a cursor from one query presented against a
    different one is rejected rather than silently returning wrong results.
    """
    if not last_evaluated_key:
        return None
    raw = json.dumps(
        {"k": last_evaluated_key, "q": query_fingerprint}, separators=(",", ":"), default=str
    )
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(cursor: str | None, query_fingerprint: str) -> dict | None:
    from domain.errors import ValidationError

    if not cursor:
        return None
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        parsed = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
    except Exception:
        raise ValidationError("malformed pagination cursor") from None
    if parsed.get("q") != query_fingerprint:
        raise ValidationError(
            "pagination cursor does not belong to this query",
            details={"hint": "restart pagination without a cursor"},
        )
    return parsed.get("k")


def clamp_page_size(requested: int | str | None) -> int:
    if requested is None or requested == "":
        return DEFAULT_PAGE_SIZE
    try:
        size = int(requested)
    except (TypeError, ValueError):
        return DEFAULT_PAGE_SIZE
    return max(1, min(size, MAX_PAGE_SIZE))


def paginated(
    items: list,
    *,
    next_cursor: str | None = None,
    correlation_id: str | None = None,
    extra_meta: dict | None = None,
) -> dict:
    meta: dict[str, Any] = {"count": len(items), "nextCursor": next_cursor}
    if extra_meta:
        meta.update(extra_meta)
    return success(items, correlation_id=correlation_id, meta=meta)
