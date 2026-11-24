#!/usr/bin/env python
"""Remove synthetic batches that contradict the showcase scenarios.

Why this is a separate script: ``seed_cloud.py`` promises in its own docstring
that it has no delete path, and that promise is worth keeping literally rather
than approximately. A destructive capability should be visible in the name of
the thing that holds it.

The problem it solves. ``seed_demo`` numbers generic batches sequentially over
(facility x group x component). Adding an exclusion -- leaving O-negative PRBC
at the showcase facilities to ``seed_showcase_inventory`` -- shifted every
subsequent identifier, so a handful of batches written by an earlier run are no
longer regenerated and simply persist. One of them, ``demo-batch-0230``, added
7 units of O-negative PRBC to a facility whose scenario specifies 9, so the
live API reported 16 and the documented scenario no longer matched reality.

What it deletes is deliberately narrow. Every one of these must hold:

1.  ``demoData`` is true -- never a record the application or a user created.
2.  The facility is one of ``SHOWCASE_FACILITIES``.
3.  The blood group is O-negative and the component is PRBC.
4.  The batch id does not start with ``demo-showcase-``.

Anything failing any condition is left alone and reported as skipped. There is
no wildcard, no truncate, no table-level operation, and no way to widen the
scope from the command line.

Usage::

    python scripts/reconcile_showcase_batches.py --stack lifelink-dev
    python scripts/reconcile_showcase_batches.py --stack lifelink-dev --apply
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from seed_demo import SHOWCASE_FACILITIES  # noqa: E402

# AFTER the seed_demo import, never before: that module sets a localhost
# endpoint and placeholder credentials at import time, which is correct for the
# local path and fatal here. Sanitising first lets the import undo it, which is
# how this script first failed with InvalidClientTokenId.
os.environ.pop("DYNAMODB_ENDPOINT", None)
for _ph in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
    if os.environ.get(_ph) == "local":
        os.environ.pop(_ph)

KEEP_PREFIX = "demo-showcase-"
TARGET_GROUP = "O-"
TARGET_COMPONENT = "PRBC"


def main() -> int:
    import boto3

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stack", default="lifelink-dev")
    parser.add_argument("--region", default="ap-southeast-2")
    parser.add_argument("--apply", action="store_true",
                        help="actually delete (default is a preview)")
    args = parser.parse_args()

    cfn = boto3.client("cloudformation", region_name=args.region)
    stack = cfn.describe_stacks(StackName=args.stack)["Stacks"][0]
    params = {p["ParameterKey"]: p["ParameterValue"] for p in stack.get("Parameters", [])}
    environment = (params.get("Environment") or "").lower()
    if environment not in ("dev", "development"):
        print(f"REFUSING: stack Environment is {environment!r}; dev only.", file=sys.stderr)
        return 2

    table_name = f"lifelink-{environment}-inventory"
    ddb = boto3.client("dynamodb", region_name=args.region)
    print(f"Table: {table_name}")
    print(f"Scope: demoData batches of {TARGET_GROUP} {TARGET_COMPONENT} at "
          f"{len(SHOWCASE_FACILITIES)} showcase facilities, excluding "
          f"{KEEP_PREFIX}*")
    print("-" * 74)

    doomed, kept = [], []
    kwargs = {"TableName": table_name}
    while True:
        page = ddb.scan(**kwargs)
        for item in page["Items"]:
            facility = item.get("facilityId", {}).get("S")
            group = item.get("bloodGroup", {}).get("S")
            component = item.get("component", {}).get("S")
            batch_id = item.get("batchId", {}).get("S") or ""
            is_demo = item.get("demoData", {}).get("BOOL", False)

            matches = (
                is_demo
                and facility in SHOWCASE_FACILITIES
                and group == TARGET_GROUP
                and component == TARGET_COMPONENT
                and not batch_id.startswith(KEEP_PREFIX)
            )
            record = {
                "PK": item["PK"],
                "SK": item["SK"],
                "batchId": batch_id,
                "facilityId": facility,
                "units": item.get("availableUnits", {}).get("N"),
            }
            (doomed if matches else kept).append(record)
        if "LastEvaluatedKey" not in page:
            break
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]

    if not doomed:
        print("  Nothing to reconcile: no conflicting batches found.")
        return 0

    for r in doomed:
        verb = "DELETE" if args.apply else "would delete"
        print(f"  {verb:<14} {r['batchId']:<20} {r['facilityId']:<16} {r['units']:>4} units")

    if not args.apply:
        print(f"\n  PREVIEW: {len(doomed)} batch(es) would be deleted, "
              f"{len(kept)} left untouched. Add --apply.")
        return 0

    for r in doomed:
        ddb.delete_item(
            TableName=table_name,
            Key={"PK": r["PK"], "SK": r["SK"]},
            # Belt and braces: refuse at the database if the item is somehow not
            # a demo record by the time the delete lands.
            ConditionExpression="demoData = :true",
            ExpressionAttributeValues={":true": {"BOOL": True}},
        )
    print(f"\n  Deleted {len(doomed)} conflicting synthetic batch(es); "
          f"{len(kept)} untouched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
