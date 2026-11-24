#!/usr/bin/env python
"""Remove duplicate synthetic REQUEST_EVENT rows left by earlier seed runs.

Why this is a separate script. ``seed_cloud.py`` promises in its own docstring
that it has no delete path, and that promise is worth keeping literally rather
than approximately. A destructive capability should be visible in the name of
the thing that holds it -- the same reason
``reconcile_showcase_batches.py`` exists.

The problem it solves. The seeder wrote request events with the sort key
``EVENT#<iso-now>#seed0001``. The ``seed0001`` suffix was fixed but the
timestamp came from the run clock, so each seed run created a *new* sort key
for the same logical event rather than overwriting the old one. Five runs
against ``lifelink-dev`` left ``demo-req-p1-1`` carrying five
``REQUEST_CREATED`` events, and the emergency tracking page -- which sorts by
sort key and renders every entry -- showed "REQUEST CREATED" five times.

The cause is fixed in ``seed_demo.seed_event_sk``, which now returns a
deterministic ``EVENT#0000#seed0001``. This script removes the rows the old
behaviour already wrote.

What it deletes is deliberately narrow. Every one of these must hold:

1.  ``entityType`` is exactly ``REQUEST_EVENT``.
2.  ``demoData`` is true -- never a row the application or a user created.
3.  The partition key is ``REQUEST#demo-req-*``, the seeder's fixed ids.
4.  The sort key ends in ``#seed0001``. A genuine event written by
    ``emergency_repo.append_event`` ends in a random uuid fragment and can
    never match.
5.  Another row survives for the same request and the same ``eventType``.
    This is the safety property that matters: a request can never be left with
    no event for a type it had one for, so no timeline loses its history.

Anything failing any condition is left alone and reported as skipped. There is
no wildcard, no truncate, no table-level operation, and no way to widen the
scope from the command line.

Which row is kept, per (request, eventType) group:

*   the row with the new deterministic key, if the seeder has been re-run since
    the fix; otherwise
*   the row with the earliest ``occurredAt``, because the seeded event is the
    request's creation and the oldest stamp is the most faithful to that.

Usage::

    python scripts/dedupe_request_events.py --stack lifelink-dev
    python scripts/dedupe_request_events.py --stack lifelink-dev --apply
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

# AFTER any seed_demo import, never before: that module sets a localhost
# endpoint and placeholder credentials at import time, which is correct for the
# local path and fatal here.
os.environ.pop("DYNAMODB_ENDPOINT", None)
for _ph in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
    if os.environ.get(_ph) == "local":
        os.environ.pop(_ph)

#: The seeder's fixed request-id prefix. Anything else is out of scope.
DEMO_REQUEST_PREFIX = "REQUEST#demo-req-"

#: The seeder's sort-key suffix. A genuine event ends in a uuid fragment.
SEED_SUFFIX = "#seed0001"

#: The deterministic form introduced by the fix: EVENT#<4 digits>#seed0001.
DETERMINISTIC_SK = re.compile(r"^EVENT#\d{4}" + re.escape(SEED_SUFFIX) + r"$")


def is_candidate(item: dict) -> bool:
    """Conditions 1-4. Condition 5 is a property of the group, not the row."""
    if item.get("entityType", {}).get("S") != "REQUEST_EVENT":
        return False
    if not item.get("demoData", {}).get("BOOL"):
        return False
    if not item.get("PK", {}).get("S", "").startswith(DEMO_REQUEST_PREFIX):
        return False
    sk = item.get("SK", {}).get("S", "")
    return sk.startswith("EVENT#") and sk.endswith(SEED_SUFFIX)


def choose_keeper(rows: list[dict]) -> dict:
    """The one row in a group that survives.

    Prefers the deterministic key, so that re-running the fixed seeder before
    this script converges on the canonical row. Otherwise the earliest
    ``occurredAt``, which is the most faithful stamp for a creation event.
    """
    for row in rows:
        if DETERMINISTIC_SK.match(row["SK"]["S"]):
            return row
    return min(rows, key=lambda r: r.get("occurredAt", {}).get("S", ""))


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
        print(
            f"REFUSING: stack {args.stack} has Environment={environment!r}. "
            "This script only runs against a development stack.",
            file=sys.stderr,
        )
        return 2

    table = f"lifelink-{environment}-emergency"
    ddb = boto3.client("dynamodb", region_name=args.region)
    print(f"Table: {table}")
    print(f"Mode : {'APPLY -- rows will be deleted' if args.apply else 'PREVIEW'}\n")

    # Scan the whole table once; this is an operator tool, run by hand.
    items: list[dict] = []
    kwargs: dict = {"TableName": table}
    while True:
        page = ddb.scan(**kwargs)
        items.extend(page["Items"])
        if "LastEvaluatedKey" not in page:
            break
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]

    events = [i for i in items if i.get("entityType", {}).get("S") == "REQUEST_EVENT"]
    candidates = [i for i in events if is_candidate(i)]
    protected = [i for i in events if not is_candidate(i)]

    print(f"  rows in table            : {len(items)}")
    print(f"  REQUEST_EVENT rows       : {len(events)}")
    print(f"  in scope (conditions 1-4): {len(candidates)}")
    print(f"  protected, left untouched: {len(protected)}")
    for row in protected[:10]:
        why = []
        if not row.get("demoData", {}).get("BOOL"):
            why.append("not demoData")
        if not row.get("PK", {}).get("S", "").startswith(DEMO_REQUEST_PREFIX):
            why.append("not a demo-req id")
        if not row.get("SK", {}).get("S", "").endswith(SEED_SUFFIX):
            why.append("genuine event (uuid suffix)")
        print(f"      keep {row['PK']['S']} {row['SK']['S'][:46]}  ({', '.join(why) or 'out of scope'})")
    if len(protected) > 10:
        print(f"      ... and {len(protected) - 10} more")

    # Group by (request, eventType). Condition 5 is enforced here: a group of
    # one is never touched, and exactly one row per group always survives.
    groups: dict[tuple[str, str], list[dict]] = {}
    for row in candidates:
        key = (row["PK"]["S"], row.get("eventType", {}).get("S", "?"))
        groups.setdefault(key, []).append(row)

    to_delete: list[dict] = []
    print("\n  Per request and event type:")
    for (pk, event_type), rows in sorted(groups.items()):
        if len(rows) == 1:
            print(f"    {pk:34} {event_type:18} 1 row, nothing to do")
            continue
        keeper = choose_keeper(rows)
        losers = [r for r in rows if r["SK"]["S"] != keeper["SK"]["S"]]
        to_delete.extend(losers)
        print(f"    {pk:34} {event_type:18} {len(rows)} rows -> keep 1, remove {len(losers)}")
        print(f"      keep   {keeper['SK']['S']}  (occurredAt {keeper.get('occurredAt', {}).get('S', '?')})")
        for r in losers:
            verb = "DELETE" if args.apply else "would delete"
            print(f"      {verb} {r['SK']['S']}  (occurredAt {r.get('occurredAt', {}).get('S', '?')})")

    print(f"\n  Duplicates identified: {len(to_delete)}")
    if not to_delete:
        print("  Nothing to do.")
        return 0

    if not args.apply:
        print("\n  PREVIEW ONLY -- nothing was deleted. Add --apply to remove them.")
        return 0

    deleted = 0
    for row in to_delete:
        # Conditioned on the row still being exactly what was inspected, so a
        # concurrent write cannot be clobbered by this delete.
        try:
            ddb.delete_item(
                TableName=table,
                Key={"PK": row["PK"], "SK": row["SK"]},
                ConditionExpression=(
                    "entityType = :t AND demoData = :d AND attribute_exists(PK)"
                ),
                ExpressionAttributeValues={
                    ":t": {"S": "REQUEST_EVENT"},
                    ":d": {"BOOL": True},
                },
            )
            deleted += 1
        except ddb.exceptions.ConditionalCheckFailedException:
            print(f"    SKIPPED {row['PK']['S']} {row['SK']['S']}: row changed since it was read")

    print(f"\n  Deleted {deleted} duplicate event row(s).")
    print(f"  {len(protected)} protected row(s) and every request record left untouched.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
