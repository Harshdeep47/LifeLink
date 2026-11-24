"""Minimal router shared by the Lambda entrypoint and the local dev server.

Deliberately not a web framework (spec 2.2 discourages unnecessary frameworks
and names FastAPI/Mangum specifically). A route table plus path-parameter
matching is all an API Gateway proxy integration needs, and the same table drives
local development, so the two cannot diverge.

Every route declares the permission it requires. A test enumerates this table and
fails the build if any route is missing authorization metadata, which is what
makes "no endpoint was left unprotected" a checkable claim rather than a hope.
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass

from appcore.auth import build_context
from appcore.context import RequestContext
from appcore.cors import is_preflight, preflight_response
from appcore.logging import configure_logging, get_logger
from appcore.rbac import Permission
from appcore.responses import error, from_exception
from domain.errors import LifeLinkError

Handler = Callable[[dict, RequestContext], dict]


def strip_stage_prefix(raw_path: str, event: dict) -> str:
    """Remove an API Gateway stage name from the front of the path.

    An HTTP API deployed to a named stage (ours is ``dev``) serves requests at
    ``/dev/health`` and reports ``rawPath`` as ``/dev/health``, while the route
    table is written in terms of ``/health``. Without this, every route 404s in
    the deployed environment while working perfectly locally — which is exactly
    what the first live request after deployment showed.

    The stage is read from ``requestContext.stage`` rather than from a constant,
    so renaming the stage cannot silently reintroduce the bug. ``$default`` is
    ignored because that stage adds no prefix.

    Only a leading segment that exactly equals the stage name is removed, so a
    route that merely starts with the same characters (``/dev-tools``) is left
    alone.
    """
    stage = ((event.get("requestContext") or {}).get("stage") or "").strip()
    if not stage or stage == "$default":
        return raw_path
    prefix = f"/{stage}"
    if raw_path == prefix:
        return "/"
    if raw_path.startswith(prefix + "/"):
        return raw_path[len(prefix):]
    return raw_path


@dataclass(frozen=True)
class Route:
    method: str
    path: str
    handler: Handler
    permission: Permission | None
    allow_anonymous: bool
    summary: str
    pattern: re.Pattern = None  # type: ignore[assignment]

    @staticmethod
    def compile_path(path: str) -> re.Pattern:
        """Turn ``/facilities/{facilityId}`` into a capturing regex."""
        regex = re.sub(r"\{([a-zA-Z0-9_]+)\}", r"(?P<\1>[^/]+)", path)
        return re.compile(f"^{regex}$")


class Router:
    def __init__(self):
        self._routes: list[Route] = []

    def add(
        self,
        method: str,
        path: str,
        handler: Handler,
        *,
        permission: Permission | None = None,
        allow_anonymous: bool = False,
        summary: str = "",
    ) -> None:
        self._routes.append(
            Route(
                method=method.upper(),
                path=path,
                handler=handler,
                permission=permission,
                allow_anonymous=allow_anonymous,
                summary=summary,
                pattern=Route.compile_path(path),
            )
        )

    @property
    def routes(self) -> list[Route]:
        return list(self._routes)

    def match(self, method: str, path: str) -> tuple[Route | None, dict, bool]:
        """Find a route. Returns (route, path_params, path_exists_other_method)."""
        path_exists = False
        for route in self._routes:
            match = route.pattern.match(path)
            if match:
                if route.method == method.upper():
                    return route, match.groupdict(), True
                path_exists = True
        return None, {}, path_exists

    def dispatch(self, event: dict, *, authenticator=None) -> dict:
        """Execute a request end to end, translating domain errors to HTTP."""
        method = (
            event.get("httpMethod")
            or (event.get("requestContext", {}).get("http", {}) or {}).get("method", "GET")
        )
        raw_path = event.get("path") or event.get("rawPath") or "/"
        path = strip_stage_prefix(raw_path, event).rstrip("/") or "/"

        # Preflight is answered before routing, because there is no OPTIONS
        # route to find and a 404 without CORS headers is what a browser
        # reports as "No 'Access-Control-Allow-Origin' header is present".
        # API Gateway would normally answer this at the edge, but our routes
        # are declared Method: ANY, which matches OPTIONS and takes precedence.
        headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
        if is_preflight(method, headers):
            return preflight_response(headers.get("origin"))

        route, params, path_exists = self.match(method, path)

        if route is None:
            if path_exists:
                return error(
                    "METHOD_NOT_ALLOWED",
                    f"{method} is not supported for this path",
                    status=405,
                )
            return error("NOT_FOUND", f"no route for {method} {path}", status=404)

        try:
            context = build_context(event, authenticator)
        except LifeLinkError as exc:
            return from_exception(exc)

        log = get_logger(__name__, context)
        enriched = {**event, "pathParameters": {**(event.get("pathParameters") or {}), **params}}

        try:
            result = route.handler(enriched, context)
            log.info(
                f"{method} {path} -> {result.get('statusCode', 200)}",
                event="http.request",
                method=method,
                path=path,
                status=result.get("statusCode", 200),
            )
            return result
        except LifeLinkError as exc:
            log.warning(
                f"{method} {path} -> {exc.http_status} {exc.code}",
                event="http.error",
                method=method,
                path=path,
                code=exc.code,
            )
            return from_exception(exc, correlation_id=context.correlation_id)
        except Exception:
            # Never leak an internal error's details to the client (spec 8.3).
            log.exception("unhandled error", event="http.unhandled",
                          method=method, path=path)
            return error(
                "INTERNAL_ERROR",
                "an unexpected error occurred",
                status=500,
                correlation_id=context.correlation_id,
            )


def parse_body(event: dict) -> dict:
    """Parse and validate a JSON request body."""
    from domain.errors import ValidationError

    raw = event.get("body")
    if raw is None or raw == "":
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"request body is not valid JSON: {exc.msg}") from None
    if not isinstance(parsed, dict):
        raise ValidationError("request body must be a JSON object")
    return parsed


def query_params(event: dict) -> dict:
    return event.get("queryStringParameters") or {}


def path_param(event: dict, name: str) -> str:
    from domain.errors import ValidationError

    value = (event.get("pathParameters") or {}).get(name)
    if not value:
        raise ValidationError(f"missing path parameter '{name}'")
    return value


def require_float(params: dict, name: str, *, default: float | None = None) -> float:
    from domain.errors import ValidationError

    raw = params.get(name)
    if raw is None or raw == "":
        if default is not None:
            return default
        raise ValidationError(f"query parameter '{name}' is required")
    try:
        return float(raw)
    except (TypeError, ValueError):
        raise ValidationError(f"query parameter '{name}' must be a number") from None


def require_int(params: dict, name: str, *, default: int | None = None) -> int:
    from domain.errors import ValidationError

    raw = params.get(name)
    if raw is None or raw == "":
        if default is not None:
            return default
        raise ValidationError(f"query parameter '{name}' is required")
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise ValidationError(f"query parameter '{name}' must be an integer") from None


def parse_iso_param(value: str | None, field: str):
    from domain.clock import parse_iso
    from domain.errors import ValidationError

    if value is None or value == "":
        return None
    try:
        return parse_iso(value)
    except ValueError as exc:
        raise ValidationError(f"'{field}' is not a valid ISO-8601 timestamp: {exc}") from None


configure_logging()
