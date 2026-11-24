"""Local development orchestrator.

    python scripts/dev.py keys          generate the dev JWT keypair
    python scripts/dev.py dynamo-start  download (first run) and start DynamoDB Local
    python scripts/dev.py create-tables create the 11 tables locally
    python scripts/dev.py token <user>  mint a dev token for a seeded user
    python scripts/dev.py status        show what is running

DynamoDB Local runs from its Java JAR rather than Docker (ADR-0011): Java is
installed on this machine and Docker is not.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend" / "src"))

KEYS_DIR = ROOT / ".local-keys"
DYNAMO_DIR = ROOT / ".dynamodb-local"
DYNAMO_URL = "https://d1ni2b6xgvw0s0.cloudfront.net/v2.x/dynamodb_local_latest.zip"
DYNAMO_PORT = 8000

os.environ.setdefault("LIFELINK_ENV", "local")
os.environ.setdefault("AWS_REGION", "ap-southeast-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "local")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "local")
os.environ.setdefault("DYNAMODB_ENDPOINT", f"http://localhost:{DYNAMO_PORT}")


def generate_keys() -> int:
    """Create an RSA keypair for locally issued development tokens.

    These keys are for local development only. They are gitignored and must
    never be used anywhere else; production uses Cognito's own JWKS.
    """
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    KEYS_DIR.mkdir(exist_ok=True)
    private_path = KEYS_DIR / "dev_private.pem"
    public_path = KEYS_DIR / "dev_public.pem"

    if private_path.exists() and public_path.exists():
        print(f"keys already present in {KEYS_DIR}")
        return 0

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    public_path.write_bytes(
        key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    (KEYS_DIR / "README.txt").write_text(
        "LOCAL DEVELOPMENT KEYS ONLY.\n"
        "These sign development JWTs for the local server. They are gitignored.\n"
        "Never reuse them outside local development. Production uses Amazon Cognito.\n",
        encoding="utf-8",
    )
    print(f"generated dev keypair in {KEYS_DIR}")
    return 0


def _java_available() -> bool:
    return shutil.which("java") is not None


def moto_start(detach: bool = True, port: int = DYNAMO_PORT) -> int:
    """Start a local DynamoDB-compatible endpoint using moto in server mode.

    This is the default local backend: it needs no download and no Docker, and
    it speaks the real DynamoDB API over HTTP, so the application code and
    boto3 client are unchanged from AWS. DynamoDB Local (the Java JAR) remains
    available via ``dynamo-start`` for anyone who prefers it -- see
    docs/LOCAL_DEVELOPMENT.md for the trade-offs.
    """
    cmd = [
        sys.executable,
        "-m",
        "moto.server",
        "-p",
        str(port),
        "-H",
        "127.0.0.1",
    ]
    print("starting local DynamoDB-compatible endpoint (moto):", " ".join(cmd))
    if detach:
        log_path = ROOT / ".local-moto.log"
        with open(log_path, "ab") as log:
            subprocess.Popen(cmd, cwd=str(ROOT), stdout=log, stderr=log)
        print(f"listening on port {port}; log: {log_path}")
        return 0
    return subprocess.call(cmd, cwd=str(ROOT))


def ensure_dynamo() -> Path | None:
    jar = DYNAMO_DIR / "DynamoDBLocal.jar"
    if jar.exists():
        return jar
    if not _java_available():
        print("ERROR: java is not on PATH. DynamoDB Local needs a JRE.")
        return None

    DYNAMO_DIR.mkdir(exist_ok=True)
    archive = DYNAMO_DIR / "dynamodb_local.zip"
    print(f"downloading DynamoDB Local to {archive} ...")
    try:
        urllib.request.urlretrieve(DYNAMO_URL, archive)  # noqa: S310
    except Exception as exc:
        print(f"ERROR: download failed: {exc}")
        print("Download manually from:")
        print("  https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/DynamoDBLocal.DownloadingAndRunning.html")
        print(f"and extract into {DYNAMO_DIR}")
        return None

    with zipfile.ZipFile(archive) as zf:
        zf.extractall(DYNAMO_DIR)
    archive.unlink(missing_ok=True)
    return jar if jar.exists() else None


def dynamo_start(detach: bool = True) -> int:
    jar = ensure_dynamo()
    if jar is None:
        return 1
    data_dir = DYNAMO_DIR / "data"
    data_dir.mkdir(exist_ok=True)
    cmd = [
        "java",
        f"-Djava.library.path={DYNAMO_DIR / 'DynamoDBLocal_lib'}",
        "-jar",
        str(jar),
        "-sharedDb",
        "-port",
        str(DYNAMO_PORT),
        "-dbPath",
        str(data_dir),
    ]
    print("starting DynamoDB Local:", " ".join(cmd))
    if detach:
        subprocess.Popen(cmd, cwd=str(DYNAMO_DIR))
        print(f"DynamoDB Local starting on port {DYNAMO_PORT}")
        return 0
    return subprocess.call(cmd, cwd=str(DYNAMO_DIR))


def create_tables() -> int:
    """Create all tables from the canonical schema definitions."""
    from botocore.exceptions import ClientError, EndpointConnectionError
    from repositories.dynamo import Tables, _resource, table_name
    from repositories.schema import create_table_kwargs

    client = _resource().meta.client
    created, existing, failed = [], [], []

    for logical in Tables.all():
        name = table_name(logical)
        try:
            client.create_table(**create_table_kwargs(logical, name))
            created.append(name)
        except EndpointConnectionError:
            print(f"ERROR: cannot reach DynamoDB at {os.environ['DYNAMODB_ENDPOINT']}")
            print("Run: python scripts/dev.py dynamo-start")
            return 1
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ResourceInUseException":
                existing.append(name)
            else:
                failed.append((name, exc.response["Error"]["Code"]))

    # Enable TTL where the schema declares it.
    from repositories.schema import TABLE_DEFINITIONS

    for logical, definition in TABLE_DEFINITIONS.items():
        attribute = definition.get("ttl")
        if not attribute:
            continue
        try:
            client.update_time_to_live(
                TableName=table_name(logical),
                TimeToLiveSpecification={"Enabled": True, "AttributeName": attribute},
            )
        except ClientError:
            pass  # DynamoDB Local accepts but does not enforce TTL

    print(f"created : {len(created)}")
    for n in created:
        print(f"  + {n}")
    if existing:
        print(f"existing: {len(existing)}")
    if failed:
        print(f"FAILED  : {len(failed)}")
        for n, code in failed:
            print(f"  ! {n} ({code})")
        return 1
    return 0


def drop_tables(confirm: bool) -> int:
    if not confirm:
        print("refusing to drop tables without --yes")
        return 1
    from botocore.exceptions import ClientError
    from repositories.dynamo import Tables, _resource, table_name

    client = _resource().meta.client
    for logical in Tables.all():
        try:
            client.delete_table(TableName=table_name(logical))
            print(f"  - {table_name(logical)}")
        except ClientError:
            pass
    return 0


def mint_token(user_id: str, ttl_hours: int = 12) -> int:
    from appcore.auth import issue_local_token

    private_path = KEYS_DIR / "dev_private.pem"
    if not private_path.exists():
        print("no dev keys found. Run: python scripts/dev.py keys")
        return 1

    from repositories.identity_repo import IdentityRepository

    try:
        user = IdentityRepository().get_user(user_id)
    except Exception:
        user = None

    if user is None:
        print(f"WARNING: no seeded user '{user_id}'. The token will be rejected at /me.")
        print("Run: python scripts/seed_demo.py")

    token = issue_local_token(
        private_path.read_bytes(),
        subject=user_id,
        email=(user or {}).get("email"),
        ttl_seconds=ttl_hours * 3600,
    )
    print(token)
    return 0


def status() -> int:
    import socket

    from botocore.exceptions import ClientError, EndpointConnectionError

    print("LifeLink local status")
    print(f"  java            : {'yes' if _java_available() else 'NO'}")
    print(f"  dev keys        : {'yes' if (KEYS_DIR / 'dev_private.pem').exists() else 'no'}")
    print(f"  dynamo jar      : {'yes' if (DYNAMO_DIR / 'DynamoDBLocal.jar').exists() else 'no'}")

    sock = socket.socket()
    sock.settimeout(1.0)
    reachable = sock.connect_ex(("127.0.0.1", DYNAMO_PORT)) == 0
    sock.close()
    print(f"  dynamo port {DYNAMO_PORT}: {'listening' if reachable else 'not listening'}")

    if reachable:
        from repositories.dynamo import Tables, _resource, table_name

        client = _resource().meta.client
        present = 0
        for logical in Tables.all():
            try:
                client.describe_table(TableName=table_name(logical))
                present += 1
            except (ClientError, EndpointConnectionError):
                pass
        print(f"  tables present  : {present}/{len(Tables.all())}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="LifeLink local dev helper")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("keys", help="generate the local JWT keypair")
    up = sub.add_parser("db-start", help="start the local DynamoDB endpoint (moto, default)")
    up.add_argument("--foreground", action="store_true")
    up.add_argument("--port", type=int, default=DYNAMO_PORT)
    start = sub.add_parser("dynamo-start", help="start DynamoDB Local (Java JAR, alternative)")
    start.add_argument("--foreground", action="store_true")
    sub.add_parser("create-tables", help="create all tables locally")
    drop = sub.add_parser("drop-tables", help="delete all local tables")
    drop.add_argument("--yes", action="store_true")
    token = sub.add_parser("token", help="mint a local dev token")
    token.add_argument("user_id")
    token.add_argument("--hours", type=int, default=12)
    sub.add_parser("status", help="show local status")

    args = parser.parse_args()

    if args.command == "keys":
        return generate_keys()
    if args.command == "db-start":
        return moto_start(detach=not args.foreground, port=args.port)
    if args.command == "dynamo-start":
        return dynamo_start(detach=not args.foreground)
    if args.command == "create-tables":
        return create_tables()
    if args.command == "drop-tables":
        return drop_tables(args.yes)
    if args.command == "token":
        return mint_token(args.user_id, args.hours)
    if args.command == "status":
        return status()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
