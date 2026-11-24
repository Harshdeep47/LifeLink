#!/usr/bin/env python
"""Seed synthetic demonstration data into a DEPLOYED LifeLink environment.

Separate from ``seed_demo.py`` deliberately. That script writes to a local
in-memory endpoint and refuses to run without ``DYNAMODB_ENDPOINT`` set; this
one writes to real DynamoDB tables that cost money and are reachable from the
internet. Reusing one script for both would mean one typo stands between a
local seed and a live write, so instead the dangerous one is its own file with
its own guards and a dry run by default.

What it does NOT do, by design:

*   **It never deletes, resets or truncates anything.** There is no ``--reset``
    flag and no code path that removes an item. The local script has one; this
    one must not, because the thing it would be pointed at is a deployed
    database.
*   It never writes without ``--apply``. The default is a preview.
*   It never touches a stack whose ``Environment`` parameter is ``staging`` or
    ``prod``.

Records are written through the same repositories and the same
``DemoSeeder`` the local path uses, so the schema, the key construction and the
validation rules are identical. There is no parallel data path.

Idempotency comes from fixed identifiers (``demo-batch-0001``,
``fac-patiala-1``, ...) and a fixed RNG seed: a second run rewrites the same
items rather than adding more. Application records created by a real user carry
ULIDs and cannot collide with these.

Usage::

    python scripts/seed_cloud.py --stack lifelink-dev                 # preview
    python scripts/seed_cloud.py --stack lifelink-dev --apply         # write
    python scripts/seed_cloud.py --stack lifelink-dev --verify-only   # read back
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

# Imported here, at module level, deliberately. seed_demo sets
# DYNAMODB_ENDPOINT to localhost at import time via os.environ.setdefault,
# because that is the right default for the local path it was written for.
# Importing it lazily meant it ran *after* configure_environment had cleared
# that variable, so every write was silently redirected to the local database
# while the console reported success against the deployed stack. Importing it
# first means configure_environment runs last and wins.
import seed_demo  # noqa: E402

# seed_demo's import-time defaults are correct for the local path and wrong for
# every line of this script: a localhost endpoint, and placeholder credentials
# ("local") that make real AWS calls fail with InvalidClientTokenId. Undo them
# here, at module scope, so nothing between this line and the first AWS call can
# observe them. Doing it inside a function was not enough -- describe_stack ran
# first and inherited the placeholders.
for _leftover in ("DYNAMODB_ENDPOINT",):
    os.environ.pop(_leftover, None)
for _placeholder in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
    if os.environ.get(_placeholder) == "local":
        os.environ.pop(_placeholder)

BANNER = "DEMO ENVIRONMENT - SYNTHETIC DATA - NOT REAL BLOOD AVAILABILITY"

#: Logical tables this script writes -- one per repository DemoSeeder uses:
#: IdentityRepository -> organizations, FacilityRepository -> facilities,
#: InventoryRepository -> inventory, CampRepository -> camps,
#: DonationRepository -> donations, EmergencyRepository -> emergency,
#: AlertRepository -> alerts, NotificationRepository -> notifications.
#:
#: Named here rather than written inline in the preview, because the two
#: drifted: the preview listed seven tables and omitted `notifications`, so an
#: operator reviewing a dry run could not see that notification preferences
#: would be rewritten. Add a repository to DemoSeeder, add its table here.
SEEDED_TABLES = (
    "organizations",
    "facilities",
    "inventory",
    "camps",
    "donations",
    "emergency",
    "alerts",
    "notifications",
)

#: Logical tables this script must never write, shown in the preview because
#: "what is safe" is the question an operator actually has. Reservations hold
#: live user state; neither this file nor seed_demo.py references that table.
UNTOUCHED_TABLES = ("reservations", "audit", "idempotency", "outbox")

#: Environments this script will write to. Anything else is refused.
ALLOWED_ENVIRONMENTS = {"dev", "development"}


def fail(message: str, *lines: str) -> None:
    print(f"REFUSING TO SEED: {message}", file=sys.stderr)
    for line in lines:
        print(f"  {line}", file=sys.stderr)
    raise SystemExit(2)


def describe_stack(stack_name: str, region: str) -> dict:
    """Read the deployed stack, and refuse anything that is not a dev stack.

    The environment is taken from the stack's own parameters rather than from a
    local variable, because the local variable is the thing most likely to be
    stale or wrong.
    """
    import boto3
    from botocore.exceptions import ClientError

    cfn = boto3.client("cloudformation", region_name=region)
    try:
        stacks = cfn.describe_stacks(StackName=stack_name)["Stacks"]
    except ClientError as exc:
        fail(f"cannot describe stack {stack_name!r} in {region}", str(exc))
    stack = stacks[0]

    status = stack["StackStatus"]
    if status not in ("CREATE_COMPLETE", "UPDATE_COMPLETE", "UPDATE_ROLLBACK_COMPLETE"):
        fail(
            f"stack {stack_name} is in status {status}",
            "Seed only a stack that has finished deploying.",
        )

    params = {p["ParameterKey"]: p["ParameterValue"] for p in stack.get("Parameters", [])}
    outputs = {o["OutputKey"]: o["OutputValue"] for o in stack.get("Outputs", [])}

    environment = (params.get("Environment") or "").lower()
    if environment not in ALLOWED_ENVIRONMENTS:
        fail(
            f"stack {stack_name} has Environment={environment!r}",
            f"This script writes only to {sorted(ALLOWED_ENVIRONMENTS)}.",
            "Synthetic data must never reach staging or production.",
        )

    return {
        "name": stack_name,
        "region": region,
        "status": status,
        "environment": environment,
        "params": params,
        "outputs": outputs,
        "account": stack["StackId"].split(":")[4],
    }


def guard(stack: dict, expected_account: str | None) -> None:
    """Four independent refusals.

    Independent because any single check is one mistake away from being
    bypassed, and the cost of being wrong here is writing invented blood
    inventory into a reachable database.
    """
    # 1. The stack's own Environment parameter -- checked in describe_stack.

    # 2. A local endpoint must not be set: that would mean the operator thinks
    #    they are seeding locally while this script talks to AWS.
    endpoint = os.environ.get("DYNAMODB_ENDPOINT", "")
    if endpoint:
        fail(
            "DYNAMODB_ENDPOINT is set while seeding a deployed stack",
            f"value: {endpoint}",
            "Unset it. Use seed_demo.py for local seeding.",
        )

    # 3. The caller's account must be the stack's account.
    import boto3

    identity = boto3.client("sts", region_name=stack["region"]).get_caller_identity()
    if identity["Account"] != stack["account"]:
        fail(
            "the active credentials are for a different account",
            f"credentials: {identity['Account']}",
            f"stack:       {stack['account']}",
        )
    if expected_account and identity["Account"] != expected_account:
        fail(
            "account does not match --expect-account",
            f"actual:   {identity['Account']}",
            f"expected: {expected_account}",
        )

    # 4. Table names must carry the environment, so a prefix typo cannot land
    #    on another environment's tables.
    prefix = os.environ.get("LIFELINK_TABLE_PREFIX", "")
    if not prefix.endswith(f"-{stack['environment']}"):
        fail(
            f"table prefix {prefix!r} does not end with -{stack['environment']}",
            "This is set by the script; a mismatch means the wiring changed.",
        )


def configure_environment(stack: dict) -> None:
    """Point the repositories at the deployed tables.

    Set before any repository import, because ``dynamo.py`` reads the prefix at
    module import time.
    """
    os.environ["LIFELINK_ENV"] = stack["environment"]
    os.environ["LIFELINK_TABLE_PREFIX"] = f"lifelink-{stack['environment']}"
    os.environ["AWS_REGION"] = stack["region"]
    os.environ.pop("DYNAMODB_ENDPOINT", None)
    # These exist only so the local script can run without credentials; they
    # would shadow the real session here.
    for leftover in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
        if os.environ.get(leftover) == "local":
            os.environ.pop(leftover)


def assert_writing_to_aws(stack: dict) -> None:
    """Fifth guard: check the real client, not the environment variable.

    The environment-variable check in ``guard()`` was not enough. Importing
    ``seed_demo`` re-set ``DYNAMODB_ENDPOINT`` to localhost after that check
    had passed, so the seeder wrote every record to the local database while
    reporting success against the deployed stack. Nothing failed loudly; the
    console output was indistinguishable from a successful cloud seed.

    The lesson is that a guard on configuration is weaker than a guard on the
    thing configuration produces. This inspects the repository's actual boto3
    client: where it will really send a request, and against which table name.
    Called immediately before the first write, after every import has run.
    """
    from repositories import dynamo
    from repositories.platform_repo import NotificationRepository

    repo = NotificationRepository()
    endpoint = repo.table.meta.client.meta.endpoint_url or ""
    region = repo.table.meta.client.meta.region_name
    table = repo.table.name
    expected_prefix = f"lifelink-{stack['environment']}-"

    if "amazonaws.com" not in endpoint:
        fail(
            "the repositories are not pointed at AWS",
            f"effective endpoint: {endpoint}",
            "A local endpoint is still configured, so records would be written",
            "to the local database while appearing to succeed against the stack.",
        )
    if "localhost" in endpoint or "127.0.0.1" in endpoint:
        fail("the effective endpoint is local", f"endpoint: {endpoint}")
    if region != stack["region"]:
        fail(
            "the client region does not match the stack region",
            f"client: {region}",
            f"stack:  {stack['region']}",
        )
    if not table.startswith(expected_prefix):
        fail(
            f"resolved table {table!r} does not start with {expected_prefix!r}",
            f"TABLE_PREFIX is {dynamo.TABLE_PREFIX!r}",
        )

    print(f"  verified target : {endpoint} ({region})")
    print(f"  verified prefix : {dynamo.TABLE_PREFIX}-*")


def existing_counts(stack: dict) -> dict[str, int]:
    """Count demo items already present, per table.

    Used for the preview and for the before/after report. Uses a filtered scan,
    which is acceptable here because this is an operator tool run by hand, not a
    user-facing path.
    """
    import boto3

    dynamodb = boto3.client("dynamodb", region_name=stack["region"])
    prefix = f"lifelink-{stack['environment']}"
    counts = {}
    for logical in SEEDED_TABLES:
        name = f"{prefix}-{logical}"
        try:
            total = 0
            demo = 0
            kwargs = {
                "TableName": name,
                "Select": "SPECIFIC_ATTRIBUTES",
                "ProjectionExpression": "demoData",
            }
            while True:
                page = dynamodb.scan(**kwargs)
                total += len(page["Items"])
                demo += sum(1 for i in page["Items"] if i.get("demoData", {}).get("BOOL"))
                if "LastEvaluatedKey" not in page:
                    break
                kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
            counts[logical] = {"total": total, "demo": demo}
        except Exception as exc:  # noqa: BLE001 - reported, not swallowed
            counts[logical] = {"error": repr(exc)[:120]}
    return counts


def preview(stack: dict) -> int:
    print(f"\nPREVIEW ONLY - nothing will be written. Add --apply to seed.")
    print("-" * 72)
    print(f"  stack        : {stack['name']}  ({stack['status']})")
    print(f"  account      : {stack['account']}")
    print(f"  region       : {stack['region']}")
    print(f"  environment  : {stack['environment']}")
    print(f"  table prefix : lifelink-{stack['environment']}")
    api = stack["outputs"].get("ApiEndpoint", "?")
    print(f"  api          : {api}")
    print(f"\n  Tables this run WOULD WRITE ({len(SEEDED_TABLES)}), and their current contents:")
    for logical, info in existing_counts(stack).items():
        if "error" in info:
            print(f"    {logical:<14} ERROR {info['error']}")
        else:
            print(f"    {logical:<14} {info['total']:>5} items ({info['demo']} marked demoData)")
    print(f"\n  Tables this run WOULD NOT TOUCH ({len(UNTOUCHED_TABLES)}):")
    print(f"    {', '.join(UNTOUCHED_TABLES)}")
    print("    (reservations hold live user state; no code path here writes them)")
    print("\n  Records written: organizations, users, memberships, facilities,")
    print("  inventory batches, showcase batches, camps, camp staff, registrations,")
    print("  donations, the impact ledger, emergency requests, provider responses,")
    print("  request events, availability alerts and notification preferences --")
    print("  all marked demoData/SYNTHETIC/DEVELOPMENT.")
    print("\n  This script never deletes, resets or truncates. Re-running rewrites")
    print("  the same fixed identifiers rather than adding duplicates.")
    return 0


def run_seed(stack: dict) -> int:
    from datetime import datetime, timezone

    print(f"\n{BANNER}")
    print("-" * 72)
    print(f"Seeding {stack['name']} ({stack['account']} / {stack['region']})")
    print("-" * 72)

    # Last line of defence, after every import has had its say.
    assert_writing_to_aws(stack)

    before = existing_counts(stack)

    now = datetime.now(timezone.utc)
    seeder = seed_demo.DemoSeeder(now)

    seeder.seed_organizations()
    print(f"  organizations     : {seeder.summary['organizations']}")
    seeder.seed_users()
    print(f"  users             : {seeder.summary['users']}")
    seeder.seed_facilities()
    print(f"  facilities        : {seeder.summary['facilities']}")
    inv = seeder.seed_inventory()
    print(f"  inventory batches : {inv['total']}"
          f" (available {inv['available']}, expired {inv['expired']},"
          f" quarantined {inv['quarantined']}, near-expiry {inv['near_expiry']})")
    print(f"  freshness spread  : fresh {inv['fresh']}, aging {inv['aging']},"
          f" stale {inv['stale']}, outdated {inv['outdated']}")
    print(f"  verification      : verified {inv['verified']},"
          f" unverified {inv['unverified']}")
    show = seeder.seed_showcase_inventory()
    print(f"  showcase batches  : {show['total']}")
    for s in show["scenarios"]:
        print(f"      {s['facilityId']:<16} {s['units']:>3} units  {s['note']}")
    seeder.seed_camps()
    print(f"  camps             : {seeder.summary['camps']}")
    seeder.seed_registrations_and_donations()
    print(f"  registrations     : {seeder.summary['registrations']}")
    print(f"  donations         : {seeder.summary['donations']}")
    seeder.seed_emergency()
    print(f"  emergency requests: {seeder.summary['emergencyRequests']}")
    seeder.seed_alerts()
    print(f"  alerts            : {seeder.summary['alerts']}")

    after = existing_counts(stack)
    print("\n  Before and after, by table:")
    print(f"    {'table':<12} {'before':>8} {'after':>8} {'added':>8}  {'demo after':>10}")
    for logical in before:
        b = before.get(logical, {})
        a = after.get(logical, {})
        if "error" in b or "error" in a:
            print(f"    {logical:<12} (count unavailable)")
            continue
        print(f"    {logical:<12} {b['total']:>8} {a['total']:>8} "
              f"{a['total'] - b['total']:>8}  {a['demo']:>10}")

    print("\n  Nothing was deleted: this script has no delete path.")
    return 0


def verify(stack: dict) -> int:
    """Read back through the repositories and check coverage.

    Reuses ``seed_demo.validate_dataset`` so the deployed data is held to the
    same 24+ checks as the local data.
    """
    print(f"\nVerifying deployed dataset in {stack['name']}")
    assert_writing_to_aws(stack)
    return seed_demo.validate_dataset()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stack", required=True, help="deployed CloudFormation stack name")
    parser.add_argument("--region", default="ap-southeast-2")
    parser.add_argument("--apply", action="store_true",
                        help="actually write (default is a preview)")
    parser.add_argument("--verify-only", action="store_true",
                        help="validate what is already deployed, write nothing")
    parser.add_argument("--expect-account", default=None,
                        help="refuse unless the account matches this id")
    args = parser.parse_args()

    stack = describe_stack(args.stack, args.region)
    configure_environment(stack)
    guard(stack, args.expect_account)

    if args.verify_only:
        return verify(stack)
    if not args.apply:
        return preview(stack)

    code = run_seed(stack)
    if code != 0:
        return code
    return verify(stack)


if __name__ == "__main__":
    raise SystemExit(main())
