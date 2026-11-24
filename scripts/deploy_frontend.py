#!/usr/bin/env python
"""Build and publish the frontend to the deployed S3 bucket and CloudFront.

Reads the bucket name and the API endpoint from the CloudFormation stack rather
than taking them as arguments, so the deployed frontend cannot be built against
the wrong API. That is the mistake worth engineering against here: a bundle
pointing at a stale endpoint looks completely normal and fails only at runtime,
in the browser, in front of an audience.

Content types are set explicitly. S3 does not infer them, and a JavaScript
module served as ``binary/octet-stream`` is refused by the browser with a MIME
type error that looks nothing like a deployment problem.

Cache headers differ by file:

*   ``index.html`` -- ``no-cache``. It names the hashed asset files, so a cached
    copy would keep pointing at the previous build.
*   everything in ``assets/`` -- immutable for a year. Vite puts a content hash
    in each filename, so a changed file gets a new name and an unchanged one can
    be cached indefinitely.

Usage::

    python scripts/deploy_frontend.py --stack lifelink-dev
    python scripts/deploy_frontend.py --stack lifelink-dev --skip-build
"""

from __future__ import annotations

import argparse
import mimetypes
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
DIST = FRONTEND / "dist"

# Explicit, because mimetypes on Windows reads the registry and has been known
# to return text/plain for .js, which browsers refuse to execute as a module.
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".webp": "image/webp",
    ".woff2": "font/woff2",
    ".ico": "image/x-icon",
    ".map": "application/json",
    ".txt": "text/plain; charset=utf-8",
}


def content_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in CONTENT_TYPES:
        return CONTENT_TYPES[suffix]
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"


def cache_control(key: str) -> str:
    if key == "index.html":
        # Must never be cached: it is the only file whose name does not change.
        return "no-cache, no-store, must-revalidate"
    if key.startswith("assets/"):
        return "public, max-age=31536000, immutable"
    return "public, max-age=300"


def stack_outputs(stack_name: str, region: str) -> dict[str, str]:
    import boto3

    cfn = boto3.client("cloudformation", region_name=region)
    stacks = cfn.describe_stacks(StackName=stack_name)["Stacks"]
    return {o["OutputKey"]: o["OutputValue"] for o in stacks[0].get("Outputs", [])}


def find_npm() -> str:
    """Locate npm without relying on PATH inheritance.

    Subprocesses on this machine do not reliably inherit the Node installer's
    PATH entry, so a bare "npm" fails with FileNotFoundError even though npm
    works in an interactive shell.
    """
    from shutil import which

    for candidate in ("npm.cmd", "npm"):
        found = which(candidate)
        if found:
            return found
    for candidate in (
        Path(r"C:\Program Files\nodejs\npm.cmd"),
        Path(r"C:\Program Files (x86)\nodejs\npm.cmd"),
    ):
        if candidate.is_file():
            return str(candidate)
    raise SystemExit("npm not found. Install Node.js or add it to PATH.")


def cognito_domain(outputs: dict[str, str]) -> str:
    """Derive the Cognito hosted-UI domain from the login URL output.

    Taken from the stack rather than rebuilt from a prefix and a region: the
    prefix is a deploy-time parameter, and reconstructing it here would be a
    second place for it to be wrong.
    """
    login = outputs.get("CognitoLoginUrl", "")
    if "/login" in login:
        return login.split("/login", 1)[0]
    return ""


def map_style_url(outputs: dict[str, str], region: str) -> str:
    """Build the MapLibre style URL, fetching the API key value from AWS.

    The key *value* is not a CloudFormation attribute -- AWS exposes it only
    through ``location:GetKey`` -- which is the better arrangement: a
    secret-shaped string does not sit in stack outputs, readable by anyone who
    can describe the stack.

    Returns an empty string on any failure. That is deliberate: the map
    component already renders a usable facility list when no style is
    configured, and a broken tile URL would give an empty grey box instead.
    A degraded map must not take the page down with it.
    """
    key_name = outputs.get("MapApiKeyName")
    map_name = outputs.get("MapName")
    if not key_name or not map_name:
        return ""
    try:
        import boto3

        key = boto3.client("location", region_name=region).describe_key(KeyName=key_name)
        value = key.get("Key")
        if not value:
            return ""
        return (
            f"https://maps.geo.{region}.amazonaws.com/maps/v0/maps/"
            f"{map_name}/style-descriptor?key={value}"
        )
    except Exception as exc:  # noqa: BLE001 - reported, not fatal
        print(f"  WARNING: could not read the map API key: {type(exc).__name__}")
        print("           the map will render its list fallback.")
        return ""


def build(api_base: str, outputs: dict[str, str], region: str) -> None:
    """Write .env.production from the stack outputs, then build.

    Every value is read from the deployed stack. A bundle built against a stale
    API endpoint or the wrong user pool looks entirely normal and fails only in
    the browser, which is exactly the failure this prevents.

    All of these are public identifiers. A user pool id, a public app client id
    and a hosted-UI domain are visible to any browser that signs in; none is a
    secret, and no secret belongs in a browser bundle.
    """
    env_file = FRONTEND / ".env.production"
    domain = cognito_domain(outputs)
    frontend = outputs.get("FrontendUrl", "").rstrip("/")

    lines = [
        "# GENERATED by scripts/deploy_frontend.py -- do not edit by hand.",
        "# Every value comes from the CloudFormation stack outputs.",
        "# All are public identifiers; no credential belongs in a browser bundle.",
        f"VITE_API_BASE={api_base}",
        f"VITE_COGNITO_DOMAIN={domain}",
        f"VITE_COGNITO_CLIENT_ID={outputs.get('UserPoolClientId', '')}",
        f"VITE_COGNITO_USER_POOL_ID={outputs.get('UserPoolId', '')}",
        f"VITE_COGNITO_REDIRECT_URI={frontend}/auth/callback",
        f"VITE_COGNITO_LOGOUT_URI={frontend}/",
        "VITE_COGNITO_SCOPES=openid email profile",
    ]

    style = map_style_url(outputs, region)
    lines.append(f"VITE_MAP_STYLE_URL={style}")
    env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"  VITE_API_BASE         = {api_base}")
    print(f"  VITE_COGNITO_DOMAIN   = {domain or '(none - sign-in disabled)'}")
    print(f"  VITE_COGNITO_CLIENT_ID= {outputs.get('UserPoolClientId', '')}")
    print(f"  VITE_COGNITO_REDIRECT = {frontend}/auth/callback")
    print(f"  VITE_MAP_STYLE_URL    = "
          f"{'configured' if style else '(none - map renders its list fallback)'}")
    if not domain:
        print("  WARNING: no Cognito domain in the stack outputs. The sign-in")
        print("           page will say sign-in is unavailable rather than fail.")

    npm = find_npm()
    env = os.environ.copy()
    env["NODE_ENV"] = "production"  # disables source maps; see vite.config.js
    node_dir = str(Path(npm).parent)
    env["PATH"] = node_dir + os.pathsep + env.get("PATH", "")

    if DIST.exists():
        import shutil

        shutil.rmtree(DIST)

    result = subprocess.run(
        [npm, "run", "build"], cwd=str(FRONTEND), env=env, capture_output=True, text=True
    )
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr, file=sys.stderr)
        raise SystemExit("frontend build failed")
    print("  build complete")


def verify_bundle(api_base: str) -> None:
    """Confirm the built bundle really contains the deployed API endpoint.

    Cheap, and catches the case where the build silently used a cached or
    stale env file. Without this the failure surfaces only in the browser.
    """
    index = DIST / "index.html"
    if not index.is_file():
        raise SystemExit(f"no build output at {DIST}")

    host = api_base.split("//", 1)[-1].split("/", 1)[0]
    for js in (DIST / "assets").glob("index-*.js"):
        if host in js.read_text(encoding="utf-8", errors="ignore"):
            print(f"  verified: bundle references {host}")
            return
    raise SystemExit(
        f"built bundle does not reference {host}. The build used a stale "
        "environment; delete frontend/dist and frontend/.env.production and retry."
    )


def upload(bucket: str, region: str) -> list[str]:
    import boto3

    s3 = boto3.client("s3", region_name=region)
    uploaded = []
    for path in sorted(p for p in DIST.rglob("*") if p.is_file()):
        key = path.relative_to(DIST).as_posix()
        s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=path.read_bytes(),
            ContentType=content_type(path),
            CacheControl=cache_control(key),
        )
        uploaded.append(key)
        print(f"    {key:<44} {content_type(path).split(';')[0]:<26}"
              f" {path.stat().st_size / 1024:>8.1f} KB")
    return uploaded


def invalidate(distribution_id: str, region: str) -> str:
    import boto3

    cf = boto3.client("cloudfront", region_name="us-east-1")
    res = cf.create_invalidation(
        DistributionId=distribution_id,
        InvalidationBatch={
            "Paths": {"Quantity": 1, "Items": ["/*"]},
            "CallerReference": f"lifelink-{int(time.time())}",
        },
    )
    return res["Invalidation"]["Id"]


def distribution_id_for(domain: str, region: str) -> str | None:
    """Find the distribution by its domain name, taken from the stack output."""
    import boto3

    cf = boto3.client("cloudfront", region_name="us-east-1")
    paginator = cf.get_paginator("list_distributions")
    for page in paginator.paginate():
        for item in (page.get("DistributionList") or {}).get("Items") or []:
            if item.get("DomainName") == domain:
                return item["Id"]
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stack", default="lifelink-dev")
    parser.add_argument("--region", default="ap-southeast-2")
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--skip-invalidation", action="store_true")
    args = parser.parse_args()

    print(f"Publishing frontend from stack {args.stack}")
    outputs = stack_outputs(args.stack, args.region)
    bucket = outputs.get("FrontendBucketName")
    api_base = outputs.get("ApiEndpoint")
    frontend_url = outputs.get("FrontendUrl", "")
    if not bucket or not api_base:
        raise SystemExit(
            "stack is missing FrontendBucketName or ApiEndpoint outputs; "
            f"found: {sorted(outputs)}"
        )
    print(f"  bucket  : {bucket}")

    if not args.skip_build:
        build(api_base, outputs, args.region)
    verify_bundle(api_base)

    print("  uploading:")
    uploaded = upload(bucket, args.region)
    print(f"  {len(uploaded)} files uploaded")

    if not args.skip_invalidation and frontend_url:
        domain = frontend_url.split("//", 1)[-1].rstrip("/")
        dist_id = distribution_id_for(domain, args.region)
        if dist_id:
            inv = invalidate(dist_id, args.region)
            print(f"  invalidation {inv} created on {dist_id}")
        else:
            print(f"  WARNING: no CloudFront distribution found for {domain};"
                  " cached copies may persist")

    print(f"\nFrontend published: {frontend_url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
