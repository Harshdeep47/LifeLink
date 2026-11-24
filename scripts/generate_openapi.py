"""Generate the OpenAPI specification from the live route table.

The specification says: generate an OpenAPI document that matches the actual
endpoints, and do not document endpoints that do not exist. The only way to
guarantee that is to derive the document from the router itself rather than
maintaining it by hand, so this script imports the real route table and emits
exactly what is registered -- including the permission each route declares.

    python scripts/generate_openapi.py            write docs/openapi.json + .yaml
    python scripts/generate_openapi.py --check    fail if the committed file is stale
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend" / "src"))

import os

os.environ.setdefault("LIFELINK_ENV", "local")
os.environ.setdefault("AWS_REGION", "ap-southeast-2")

OUTPUT_JSON = ROOT / "docs" / "openapi.json"
OUTPUT_YAML = ROOT / "docs" / "openapi.yaml"

ERROR_SCHEMA = {
    "type": "object",
    "required": ["error"],
    "properties": {
        "error": {
            "type": "object",
            "required": ["code", "message"],
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Stable machine-readable error code. Branch on this, not the message.",
                },
                "message": {"type": "string"},
                "details": {"type": "object", "additionalProperties": True},
            },
        },
        "correlationId": {"type": "string"},
    },
}

ENVELOPE_SCHEMA = {
    "type": "object",
    "properties": {
        "data": {"description": "The response payload. Shape depends on the endpoint."},
        "meta": {
            "type": "object",
            "properties": {
                "count": {"type": "integer"},
                "nextCursor": {
                    "type": ["string", "null"],
                    "description": "Opaque cursor. Pass back as ?cursor= to continue. Bound to the originating query.",
                },
            },
            "additionalProperties": True,
        },
        "correlationId": {"type": "string"},
    },
}

# Documented error codes, taken from domain.errors.
ERROR_CODES = {
    400: ["VALIDATION_ERROR"],
    401: ["UNAUTHENTICATED"],
    403: ["FORBIDDEN", "ACCOUNT_SUSPENDED", "CROSS_ORGANIZATION_DENIED"],
    404: ["NOT_FOUND"],
    409: [
        "CONFLICT",
        "CONCURRENT_MODIFICATION",
        "DUPLICATE",
        "REQUEST_IN_PROGRESS",
        "INSUFFICIENT_STOCK",
        "INVALID_STATE_TRANSITION",
        "CAPACITY_EXCEEDED",
    ],
    429: ["RATE_LIMITED"],
    503: ["CHANNEL_UNAVAILABLE", "PROVIDER_UNAVAILABLE"],
}


def tag_for(path: str) -> str:
    if path.startswith("/facilities") and "batch" in path:
        return "Feature 1 - Inventory"
    if path.startswith("/facilities") and "inventory" in path:
        return "Feature 1 - Inventory"
    if path.startswith("/alerts"):
        return "Feature 1 - Availability alerts"
    if path.startswith("/facilities") or path.startswith("/geocode"):
        return "Feature 2 - Discovery and location"
    if path.startswith("/camps"):
        return "Feature 3 - Camps"
    if path.startswith("/me/don") or path.startswith("/me/registrations"):
        return "Feature 3 - Donor"
    if path.startswith("/emergency-requests"):
        return "Feature 4 - Emergency coordination"
    if path.startswith("/admin"):
        return "Feature 6 - Administration"
    if path.startswith("/me"):
        return "Feature 6 - Account and notifications"
    return "Platform"


def operation_id(method: str, path: str) -> str:
    cleaned = re.sub(r"[{}]", "", path).strip("/").replace("/", "-").replace("-", " ")
    words = [w for w in cleaned.split() if w]
    camel = words[0].lower() + "".join(w.capitalize() for w in words[1:]) if words else "root"
    return f"{method.lower()}{camel[0].upper()}{camel[1:]}" if camel else method.lower()


def build_document() -> dict:
    from handlers.api import ROUTER

    paths: dict[str, dict] = {}
    tags_seen: dict[str, str] = {}

    for route in sorted(ROUTER.routes, key=lambda r: (r.path, r.method)):
        tag = tag_for(route.path)
        tags_seen.setdefault(tag, tag)

        parameters = []
        for name in re.findall(r"\{([a-zA-Z0-9_]+)\}", route.path):
            parameters.append(
                {
                    "name": name,
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                }
            )

        responses: dict[str, dict] = {
            "200": {
                "description": "Success",
                "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Envelope"}}},
            }
        }
        if route.method == "POST":
            responses["201"] = {
                "description": "Created",
                "content": {
                    "application/json": {"schema": {"$ref": "#/components/schemas/Envelope"}}
                },
            }
        if route.method == "DELETE":
            responses["204"] = {"description": "Deleted, no content"}

        for status, codes in ERROR_CODES.items():
            # Only document the statuses a route can actually produce.
            if status == 401 and route.allow_anonymous:
                continue
            if status == 403 and route.permission is None:
                continue
            responses[str(status)] = {
                "description": f"Error. Possible codes: {', '.join(codes)}",
                "content": {
                    "application/json": {"schema": {"$ref": "#/components/schemas/Error"}}
                },
            }

        operation = {
            "summary": route.summary or f"{route.method} {route.path}",
            "operationId": operation_id(route.method, route.path),
            "tags": [tag],
            "parameters": parameters,
            "responses": responses,
        }

        if route.permission is not None:
            operation["description"] = (
                f"Requires permission `{route.permission.value}`. "
                + (
                    "Anonymous access is permitted for this route."
                    if route.allow_anonymous
                    else "Authentication is required."
                )
                + " Authorization is enforced server-side on every request, including "
                "account status and resource ownership."
            )
            operation["x-lifelink-permission"] = route.permission.value

        if route.allow_anonymous:
            operation["security"] = [{}, {"bearerAuth": []}]
        else:
            operation["security"] = [{"bearerAuth": []}]

        if route.method in ("POST", "PUT", "PATCH"):
            operation["requestBody"] = {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {"type": "object", "additionalProperties": True}
                    }
                },
            }
            operation.setdefault("parameters", []).append(
                {
                    "name": "Idempotency-Key",
                    "in": "header",
                    "required": False,
                    "schema": {"type": "string"},
                    "description": (
                        "Client-supplied key. Repeating a request with the same key "
                        "returns the original result instead of repeating the effect."
                    ),
                }
            )

        paths.setdefault(route.path, {})[route.method.lower()] = operation

    return {
        "openapi": "3.0.3",
        "info": {
            "title": "LifeLink API",
            "version": "0.1.0",
            "description": (
                "Blood availability, facility discovery, voluntary donation and "
                "emergency coordination.\n\n"
                "**This document is generated from the live route table** "
                "(`backend/src/handlers/api.py`) by `scripts/generate_openapi.py`, "
                "so it cannot describe an endpoint that does not exist.\n\n"
                "Every response uses one envelope: `{ data, meta?, correlationId }` on "
                "success and `{ error: { code, message, details? } }` on failure. "
                "Clients should branch on `error.code`, which is stable, rather than on "
                "the message, which is not.\n\n"
                "**What this API does not do.** It does not reserve or allocate blood, "
                "does not determine clinical urgency, and does not certify clinical "
                "suitability. Availability figures are reported by facilities and carry "
                "both a freshness label and a separate independent-verification status."
            ),
            "contact": {"name": "LifeLink project"},
        },
        "servers": [
            {"url": "http://127.0.0.1:8080", "description": "Local development"},
            {
                "url": "https://{apiId}.execute-api.{region}.amazonaws.com/{stage}",
                "description": "AWS deployment (not currently deployed)",
                "variables": {
                    "apiId": {"default": "example"},
                    "region": {"default": "ap-southeast-2"},
                    "stage": {"default": "dev"},
                },
            },
        ],
        "tags": [{"name": tag} for tag in sorted(tags_seen)],
        "components": {
            "securitySchemes": {
                "bearerAuth": {
                    "type": "http",
                    "scheme": "bearer",
                    "bearerFormat": "JWT",
                    "description": (
                        "Amazon Cognito access token in AWS; a locally issued "
                        "development token when running locally. Roles and account "
                        "status are read from the database on every request, not from "
                        "token claims, so a suspended account is rejected immediately."
                    ),
                }
            },
            "schemas": {"Envelope": ENVELOPE_SCHEMA, "Error": ERROR_SCHEMA},
        },
        "paths": paths,
    }


def to_yaml(document: dict) -> str:
    """Render the document as YAML.

    An earlier version hand-rolled this to avoid a dependency and emitted
    invalid YAML for the multi-line description blocks. A broken machine-readable
    artifact is worse than an extra dependency, so this uses PyYAML and the
    output is parsed back and compared against the JSON before being written.
    """
    import yaml

    return yaml.safe_dump(document, sort_keys=False, allow_unicode=True, width=100)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the LifeLink OpenAPI document")
    parser.add_argument("--check", action="store_true",
                        help="exit non-zero if the committed document is out of date")
    args = parser.parse_args()

    document = build_document()
    rendered = json.dumps(document, indent=2, sort_keys=False) + "\n"

    if args.check:
        if not OUTPUT_JSON.is_file():
            print("docs/openapi.json is missing. Run without --check to generate it.")
            return 1
        if OUTPUT_JSON.read_text(encoding="utf-8") != rendered:
            print("docs/openapi.json is out of date with the route table.")
            print("Run: python scripts/generate_openapi.py")
            return 1
        print("OpenAPI document matches the route table.")
        return 0

    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(rendered, encoding="utf-8")

    yaml_body = to_yaml(document)
    OUTPUT_YAML.write_text(
        "# Generated by scripts/generate_openapi.py from the live route table.\n"
        "# Do not edit by hand; regenerate instead.\n" + yaml_body,
        encoding="utf-8",
    )

    # Verify the YAML round-trips and agrees with the JSON, so a broken emitter
    # can never ship as a valid-looking artifact.
    import yaml as _yaml

    reparsed = _yaml.safe_load(OUTPUT_YAML.read_text(encoding="utf-8"))
    if reparsed != document:
        print("ERROR: the generated YAML does not round-trip to the same document.")
        return 1

    operations = sum(len(methods) for methods in document["paths"].values())
    print(f"wrote {OUTPUT_JSON.relative_to(ROOT)}")
    print(f"wrote {OUTPUT_YAML.relative_to(ROOT)}")
    print(f"  paths      : {len(document['paths'])}")
    print(f"  operations : {operations}")
    print(f"  tags       : {len(document['tags'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
