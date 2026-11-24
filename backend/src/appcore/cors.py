"""CORS preflight handling, as a safety net behind API Gateway.

API Gateway's HTTP API answers preflight OPTIONS requests itself when
``CorsConfiguration`` is set -- *unless* a route matches OPTIONS, in which case
it invokes that route instead. LifeLink's routes are declared ``Method: ANY``
on ``/{proxy+}``, and ANY includes OPTIONS, so preflight can reach this Lambda
rather than being answered at the edge. The router then looked for an OPTIONS
route, found none, and returned 404 with no CORS headers, which a browser
reports as:

    Response to preflight request doesn't pass access control check:
    No 'Access-Control-Allow-Origin' header is present on the requested resource.

That is the second half of the CORS failure. The first half was the template
reading ``AllowOrigins`` from an OAuth logout URL whose default was
``http://localhost:5173/`` -- a value that, having a trailing slash, could not
match any ``Origin`` header in any environment.

Division of responsibility, kept deliberately narrow so the two layers cannot
contradict each other:

*   **This module answers preflight only** -- the OPTIONS request. It returns
    204 with the CORS headers and no body.
*   **API Gateway adds CORS headers to every other response**, including error
    responses, from its own configuration.

Normal responses are therefore never given CORS headers here, so there is no
possibility of a duplicated ``Access-Control-Allow-Origin``, which browsers
reject as strictly as a missing one.

The allowed origins come from the ``CORS_ALLOW_ORIGINS`` environment variable so
that the Lambda and the API Gateway configuration are fed from the same
template parameter rather than drifting apart.
"""

from __future__ import annotations

import os

#: Must stay in step with CorsConfiguration.AllowHeaders in the template.
ALLOWED_HEADERS = "Content-Type,Authorization,Idempotency-Key,X-Correlation-Id"
ALLOWED_METHODS = "GET,POST,PUT,PATCH,DELETE,OPTIONS"
MAX_AGE_SECONDS = "600"


def allowed_origins() -> tuple[str, ...]:
    """Origins permitted to call the API, from configuration.

    Normalised by stripping whitespace and any trailing slash, because a
    trailing slash is the exact mistake that broke this once already and a
    configuration value is the most likely place for it to recur.
    """
    raw = os.environ.get("CORS_ALLOW_ORIGINS", "")
    origins = []
    for part in raw.split(","):
        candidate = part.strip().rstrip("/")
        if candidate:
            origins.append(candidate)
    return tuple(origins)


def resolve_origin(request_origin: str | None) -> str | None:
    """Echo the request's origin if it is allowed, else None.

    Returns the *request's* origin rather than a fixed value, because
    ``Access-Control-Allow-Origin`` accepts exactly one origin and the API has
    several callers (CloudFront, and localhost during development).

    A wildcard is never returned. The API is called with an Authorization
    header, and a wildcard would let any page a signed-in user visits read
    authenticated responses from their browser.
    """
    if not request_origin:
        return None
    candidate = request_origin.strip().rstrip("/")
    return candidate if candidate in allowed_origins() else None


def is_preflight(method: str, headers: dict) -> bool:
    """A CORS preflight is an OPTIONS request carrying an Origin.

    An OPTIONS request without an Origin is not a preflight; it is a client
    asking what the resource supports, and it is not this module's business.
    """
    return method.upper() == "OPTIONS" and bool(
        headers.get("origin") or headers.get("Origin")
    )


def preflight_response(request_origin: str | None) -> dict:
    """Answer a preflight.

    An origin that is not on the list gets 403 with no CORS headers rather than
    a 204 without them. Both make the browser block the request, but the 403
    says why in the access log, which matters when the next CORS failure needs
    diagnosing.
    """
    origin = resolve_origin(request_origin)
    if origin is None:
        return {
            "statusCode": 403,
            "headers": {"Content-Type": "application/json", "Cache-Control": "no-store"},
            "body": '{"error":{"code":"ORIGIN_NOT_ALLOWED",'
                    '"message":"this origin is not permitted to call the API"}}',
        }

    return {
        "statusCode": 204,
        "headers": {
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Methods": ALLOWED_METHODS,
            "Access-Control-Allow-Headers": ALLOWED_HEADERS,
            "Access-Control-Expose-Headers": "X-Correlation-Id",
            "Access-Control-Max-Age": MAX_AGE_SECONDS,
            # Responses differ by origin, so any cache in front of the API must
            # key on it. Without this a cached response for one origin can be
            # served to another and fail its CORS check.
            "Vary": "Origin",
            "Cache-Control": "no-store",
        },
        "body": "",
    }


__all__ = [
    "ALLOWED_HEADERS",
    "ALLOWED_METHODS",
    "allowed_origins",
    "is_preflight",
    "preflight_response",
    "resolve_origin",
]
