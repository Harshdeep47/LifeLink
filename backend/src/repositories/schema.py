"""Canonical table and index definitions.

Single source of truth, consumed by:
  * the local DynamoDB bootstrap script (ADR-0011),
  * integration tests,
  * a generator that emits the SAM/CloudFormation resources,
so the three cannot drift apart. See docs/DATABASE_DESIGN.md for the rationale
behind each key and index.
"""
from __future__ import annotations

from typing import Any

from .dynamo import Tables

S = "S"
N = "N"


def _gsi(name: str, pk: str, sk: str | None = None, *,
         projection: str = "ALL", attributes: list[str] | None = None) -> dict:
    key_schema = [{"AttributeName": pk, "KeyType": "HASH"}]
    if sk:
        key_schema.append({"AttributeName": sk, "KeyType": "RANGE"})
    proj: dict[str, Any] = {"ProjectionType": projection}
    if projection == "INCLUDE":
        proj["NonKeyAttributes"] = attributes or []
    return {"IndexName": name, "KeySchema": key_schema, "Projection": proj}


TABLE_DEFINITIONS: dict[str, dict[str, Any]] = {
    Tables.ORGANIZATIONS: {
        "attributes": {"PK": S, "SK": S, "GSI1PK": S, "GSI1SK": S},
        "indexes": [
            # Organizations by verification status, for the admin queue.
            _gsi("GSI1-status", "GSI1PK", "GSI1SK"),
        ],
        "ttl": None,
        "description": "Users, organizations and memberships.",
    },
    Tables.FACILITIES: {
        "attributes": {
            "PK": S, "SK": S,
            "GSI1PK": S, "GSI1SK": S,   # geohash precision 5
            "GSI2PK": S, "GSI2SK": S,   # geohash precision 6
            "GSI3PK": S, "GSI3SK": S,   # by organization
            "GSI4PK": S, "GSI4SK": S,   # by verification status
            "GSI5PK": S, "GSI5SK": S,   # geohash precision 4, for wide searches
        },
        "indexes": [
            _gsi("GSI1-geo5", "GSI1PK", "GSI1SK"),
            _gsi("GSI2-geo6", "GSI2PK", "GSI2SK"),
            _gsi("GSI3-org", "GSI3PK", "GSI3SK"),
            _gsi("GSI4-verification", "GSI4PK", "GSI4SK"),
            _gsi("GSI5-geo4", "GSI5PK", "GSI5SK"),
        ],
        "ttl": None,
        "description": "Blood banks and other facilities, with geospatial indexes.",
    },
    Tables.INVENTORY: {
        "attributes": {
            "PK": S, "SK": S,
            "GSI1PK": S, "GSI1SK": S,   # FACILITY#<id>#<group>#<component> / STATUS#..#<expiry>
            "GSI2PK": S, "GSI2SK": S,   # sharded expiry sweep
        },
        "indexes": [
            _gsi(
                "GSI1-group-component", "GSI1PK", "GSI1SK",
                projection="INCLUDE",
                attributes=[
                    "batchId", "availableUnits", "lastUpdatedAt",
                    "lastVerifiedAt", "status", "expiresAt", "organizationId",
                ],
            ),
            _gsi("GSI2-expiry", "GSI2PK", "GSI2SK", projection="KEYS_ONLY"),
        ],
        "ttl": None,
        "description": "Batch-level blood stock and its audit history.",
    },
    Tables.ALERTS: {
        "attributes": {
            "PK": S, "SK": S,
            "GSI1PK": S, "GSI1SK": S,   # by user
            "GSI2PK": S, "GSI2SK": S,   # MATCH#<geohash5>#<group>#<component>
        },
        "indexes": [
            _gsi("GSI1-user", "GSI1PK", "GSI1SK"),
            _gsi("GSI2-match", "GSI2PK", "GSI2SK"),
        ],
        "ttl": "expiresAtEpoch",
        "description": "Short-term blood availability alerts (Feature 1 submodule).",
    },
    Tables.RESERVATIONS: {
        "attributes": {
            "PK": S, "SK": S,
            "GSI1PK": S, "GSI1SK": S,   # USER#<id> -- "my reservations"
            "GSI2PK": S, "GSI2SK": S,   # RESSTATUS#<status> / expiresAt
        },
        "indexes": [
            _gsi("GSI1-requester", "GSI1PK", "GSI1SK"),
            _gsi("GSI2-expiry", "GSI2PK", "GSI2SK"),
        ],
        # Cleanup only, never the release mechanism: TTL is best-effort within
        # ~48 hours, and a hold must stop holding the moment it expires. See
        # domain/reservations.py and the maintenance sweep.
        "ttl": "purgeAtEpoch",
        "description": "Temporary unit holds, one partition per facility.",
    },
    Tables.CAMPS: {
        "attributes": {
            "PK": S, "SK": S,
            "GSI1PK": S, "GSI1SK": S,   # geo
            "GSI2PK": S, "GSI2SK": S,   # by user (registrations)
            "GSI3PK": S, "GSI3SK": S,   # by organizer
            "GSI4PK": S, "GSI4SK": S,   # reminder windows
        },
        "indexes": [
            _gsi("GSI1-geo", "GSI1PK", "GSI1SK"),
            _gsi("GSI2-user", "GSI2PK", "GSI2SK"),
            _gsi("GSI3-organizer", "GSI3PK", "GSI3SK"),
            _gsi("GSI4-reminder", "GSI4PK", "GSI4SK"),
        ],
        "ttl": None,
        "description": "Camps, registrations and staff assignments in one partition each.",
    },
    Tables.DONATIONS: {
        "attributes": {"PK": S, "SK": S, "GSI1PK": S, "GSI1SK": S},
        "indexes": [_gsi("GSI1-camp", "GSI1PK", "GSI1SK")],
        "ttl": None,
        "description": "Donation records and the append-only impact ledger.",
    },
    Tables.EMERGENCY: {
        "attributes": {
            "PK": S, "SK": S,
            "GSI1PK": S, "GSI1SK": S,   # dispatcher: DISPATCH#<status> / <priority>#<created>
            "GSI2PK": S, "GSI2SK": S,   # by requesting organization
            "GSI3PK": S, "GSI3SK": S,   # by provider
            "GSI4PK": S, "GSI4SK": S,   # by deadline
        },
        "indexes": [
            _gsi("GSI1-dispatch", "GSI1PK", "GSI1SK"),
            _gsi("GSI2-requester", "GSI2PK", "GSI2SK"),
            _gsi("GSI3-provider", "GSI3PK", "GSI3SK"),
            _gsi("GSI4-deadline", "GSI4PK", "GSI4SK"),
        ],
        "ttl": None,
        "description": "Emergency requests, provider responses and lifecycle events.",
    },
    Tables.NOTIFICATIONS: {
        "attributes": {"PK": S, "SK": S, "GSI1PK": S, "GSI1SK": S},
        "indexes": [_gsi("GSI1-status", "GSI1PK", "GSI1SK")],
        "ttl": "expiresAtEpoch",
        "description": "User notification preferences, in-app messages, delivery status.",
    },
    Tables.AUDIT: {
        "attributes": {"PK": S, "SK": S, "GSI1PK": S, "GSI1SK": S},
        "indexes": [_gsi("GSI1-actor", "GSI1PK", "GSI1SK")],
        "ttl": None,
        "description": "Append-only audit trail. Write-only IAM policy in AWS.",
    },
    Tables.IDEMPOTENCY: {
        "attributes": {"PK": S, "SK": S},
        "indexes": [],
        "ttl": "expiresAtEpoch",
        "description": "Idempotency claims for mutating requests and queue consumers.",
    },
    Tables.OUTBOX: {
        "attributes": {"PK": S, "SK": S, "GSI1PK": S, "GSI1SK": S},
        "indexes": [_gsi("GSI1-pending", "GSI1PK", "GSI1SK")],
        "ttl": "expiresAtEpoch",
        "description": "Transactional outbox; a stream publisher drains it to SQS.",
    },
}


def create_table_kwargs(logical: str, table_name: str) -> dict[str, Any]:
    """boto3 ``create_table`` arguments for one logical table."""
    definition = TABLE_DEFINITIONS[logical]
    kwargs: dict[str, Any] = {
        "TableName": table_name,
        "KeySchema": [
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        "AttributeDefinitions": [
            {"AttributeName": name, "AttributeType": kind}
            for name, kind in definition["attributes"].items()
        ],
        "BillingMode": "PAY_PER_REQUEST",
    }
    if definition["indexes"]:
        kwargs["GlobalSecondaryIndexes"] = definition["indexes"]
    return kwargs
