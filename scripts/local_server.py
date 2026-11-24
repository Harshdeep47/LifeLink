"""Local HTTP server for LifeLink.

Translates plain HTTP into the same API Gateway-shaped event the Lambda handler
receives, and calls the same router. There is deliberately no separate "local
app" -- the spec warns against a mock that behaves differently from the real
architecture, so the only difference here is the transport and the token issuer.

    python scripts/local_server.py --port 8080
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend" / "src"))

os.environ.setdefault("LIFELINK_ENV", "local")
os.environ.setdefault("DYNAMODB_ENDPOINT", "http://localhost:8000")
os.environ.setdefault("AWS_REGION", "ap-southeast-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "local")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "local")
os.environ.setdefault("LOCAL_JWT_PUBLIC_KEY", str(ROOT / ".local-keys" / "dev_public.pem"))

ALLOWED_ORIGINS = os.environ.get("CORS_ORIGINS", "http://localhost:5173").split(",")


class LifeLinkRequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "LifeLinkLocal/1.0"

    def _cors_headers(self) -> dict:
        origin = self.headers.get("Origin", "")
        allow = origin if origin in ALLOWED_ORIGINS else ALLOWED_ORIGINS[0]
        return {
            "Access-Control-Allow-Origin": allow,
            "Access-Control-Allow-Methods": "GET,POST,PUT,PATCH,DELETE,OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type,Authorization,Idempotency-Key,X-Correlation-Id",
            "Access-Control-Max-Age": "600",
            "Vary": "Origin",
        }

    def _send(self, status: int, body: str, headers: dict | None = None) -> None:
        payload = body.encode("utf-8")
        self.send_response(status)
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        for key, value in self._cors_headers().items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if payload:
            self.wfile.write(payload)

    def do_OPTIONS(self):  # noqa: N802
        self._send(204, "")

    def _handle(self, method: str) -> None:
        from handlers.api import ROUTER
        from services.container import get_services

        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        raw_body = self.rfile.read(length).decode("utf-8") if length else ""

        query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        event = {
            "httpMethod": method,
            "path": parsed.path,
            "queryStringParameters": query,
            "headers": dict(self.headers),
            "body": raw_body,
            "requestContext": {
                "identity": {"sourceIp": self.client_address[0]},
                "http": {"method": method, "sourceIp": self.client_address[0]},
            },
        }

        try:
            services = get_services()
            result = ROUTER.dispatch(event, authenticator=services.authenticator)
        except Exception as exc:  # last-resort guard so the dev server stays up
            result = {
                "statusCode": 500,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps(
                    {"error": {"code": "LOCAL_SERVER_ERROR", "message": str(exc)[:500]}}
                ),
            }

        self._send(
            result.get("statusCode", 200),
            result.get("body", ""),
            result.get("headers", {}),
        )

    def do_GET(self):  # noqa: N802
        self._handle("GET")

    def do_POST(self):  # noqa: N802
        self._handle("POST")

    def do_PUT(self):  # noqa: N802
        self._handle("PUT")

    def do_PATCH(self):  # noqa: N802
        self._handle("PATCH")

    def do_DELETE(self):  # noqa: N802
        self._handle("DELETE")

    def log_message(self, fmt, *args):
        # The application already emits structured logs; this would duplicate them.
        pass


def main() -> int:
    parser = argparse.ArgumentParser(description="LifeLink local API server")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    from handlers.api import ROUTER

    print(f"LifeLink local API on http://{args.host}:{args.port}")
    print(f"  DynamoDB endpoint : {os.environ['DYNAMODB_ENDPOINT']}")
    print(f"  Routes registered : {len(ROUTER.routes)}")
    print(f"  CORS origins      : {', '.join(ALLOWED_ORIGINS)}")
    print("  DEMO ENVIRONMENT - SYNTHETIC DATA - NOT REAL BLOOD AVAILABILITY")
    print("Press Ctrl+C to stop.")

    server = ThreadingHTTPServer((args.host, args.port), LifeLinkRequestHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
