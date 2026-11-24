"""Inventory persistence: batches, conditional stock writes, audit history.

Every mutation is a conditional write (ADR-0002). The condition re-states the
invariants the domain layer already checked, because between that check and this
write another request may have changed the row. Belt and braces is the point:
the domain gives a good error message, the condition guarantees correctness.
"""
from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

from boto3.dynamodb.conditions import Attr, Key

from domain.blood import BatchStatus, BloodGroup, Component
from domain.clock import parse_iso, to_iso
from domain.inventory import Batch, StockChange

from .dynamo import DynamoRepository, Tables, clean, table_name, to_dynamo, to_expression_values

EXPIRY_SHARDS = 10


def expiry_shard(batch_id: str) -> int:
    """Spread the expiry sweep across partitions so it cannot create a hot key."""
    digest = hashlib.sha256(batch_id.encode()).digest()
    return digest[0] % EXPIRY_SHARDS


def _batch_pk(facility_id: str) -> str:
    return f"FACILITY#{facility_id}"


def _batch_sk(batch_id: str) -> str:
    return f"BATCH#{batch_id}"


def _gsi1_pk(facility_id: str, group: str, component: str) -> str:
    return f"FACILITY#{facility_id}#{group}#{component}"


def _gsi1_sk(status: str, expires_at: datetime | None) -> str:
    # Sorting on status then expiry lets one range condition select available,
    # unexpired stock without a filter expression.
    return f"STATUS#{status}#{to_iso(expires_at) or '9999-12-31T23:59:59Z'}"


def batch_to_item(batch: Batch) -> dict[str, Any]:
    return {
        "PK": _batch_pk(batch.facility_id),
        "SK": _batch_sk(batch.batch_id),
        "entityType": "BATCH",
        "batchId": batch.batch_id,
        "facilityId": batch.facility_id,
        "organizationId": batch.organization_id,
        "bloodGroup": batch.blood_group.value,
        "component": batch.component.value,
        "availableUnits": batch.available_units,
        "status": batch.status.value,
        "collectedAt": to_iso(batch.collected_at),
        "expiresAt": to_iso(batch.expires_at),
        "lastUpdatedAt": to_iso(batch.last_updated_at),
        "lastVerifiedAt": to_iso(batch.last_verified_at),
        "updateSource": batch.update_source,
        "version": batch.version,
        "quarantineReason": batch.quarantine_reason,
        "GSI1PK": _gsi1_pk(batch.facility_id, batch.blood_group.value, batch.component.value),
        "GSI1SK": _gsi1_sk(batch.status.value, batch.expires_at),
        "GSI2PK": f"EXPIRY_SHARD#{expiry_shard(batch.batch_id)}",
        "GSI2SK": to_iso(batch.expires_at) or "9999-12-31T23:59:59Z",
    }


def item_to_batch(item: dict) -> Batch:
    return Batch(
        batch_id=item["batchId"],
        facility_id=item["facilityId"],
        organization_id=item["organizationId"],
        blood_group=BloodGroup(item["bloodGroup"]),
        component=Component(item["component"]),
        available_units=int(item["availableUnits"]),
        status=BatchStatus(item["status"]),
        collected_at=parse_iso(item.get("collectedAt")),
        expires_at=parse_iso(item.get("expiresAt")),
        last_updated_at=parse_iso(item["lastUpdatedAt"]),
        last_verified_at=parse_iso(item.get("lastVerifiedAt")),
        update_source=item.get("updateSource", "UNKNOWN"),
        version=int(item.get("version", 1)),
        quarantine_reason=item.get("quarantineReason"),
    )


class InventoryRepository(DynamoRepository):
    logical_table = Tables.INVENTORY

    # --- reads ---

    def get_batch(self, facility_id: str, batch_id: str) -> Batch | None:
        item = self.get(_batch_pk(facility_id), _batch_sk(batch_id))
        return item_to_batch(item) if item else None

    def get_batch_consistent(self, facility_id: str, batch_id: str) -> Batch | None:
        """Used when re-reading after a failed conditional write."""
        item = self.get_consistent(_batch_pk(facility_id), _batch_sk(batch_id))
        return item_to_batch(item) if item else None

    def list_batches(self, facility_id: str, *, limit: int = 100,
                     start_key: dict | None = None) -> tuple[list[Batch], dict | None]:
        items, next_key = self.query_partition(
            _batch_pk(facility_id), sk_prefix="BATCH#", limit=limit,
            exclusive_start_key=start_key,
        )
        return [item_to_batch(i) for i in items], next_key

    def list_eligible_batches(
        self, facility_id: str, group: BloodGroup, component: Component, *, now: datetime
    ) -> list[Batch]:
        """Query AVAILABLE batches that have not yet expired.

        The range condition does the filtering: because GSI1SK is
        ``STATUS#<status>#<expiry>``, everything from ``STATUS#AVAILABLE#<now>``
        upward is available stock expiring in the future. Quarantined, expired
        and withdrawn rows sort under different status prefixes and are never
        read -- they cannot leak into an availability answer by accident.
        """
        lower = f"STATUS#{BatchStatus.AVAILABLE.value}#{to_iso(now)}"
        upper = f"STATUS#{BatchStatus.AVAILABLE.value}#9999-12-31T23:59:59Z"
        condition = Key("GSI1PK").eq(
            _gsi1_pk(facility_id, group.value, component.value)
        ) & Key("GSI1SK").between(lower, upper)

        items = self.query_all(key_condition=condition, index_name="GSI1-group-component")
        # The index projection is partial, so hydrate from the base table only
        # what we actually need for aggregation.
        return [
            Batch(
                batch_id=i["batchId"],
                facility_id=facility_id,
                organization_id=i.get("organizationId", ""),
                blood_group=group,
                component=component,
                available_units=int(i["availableUnits"]),
                status=BatchStatus(i["status"]),
                collected_at=None,
                expires_at=parse_iso(i.get("expiresAt")),
                last_updated_at=parse_iso(i["lastUpdatedAt"]),
                last_verified_at=parse_iso(i.get("lastVerifiedAt")),
                update_source="INDEX",
                version=0,
            )
            for i in items
        ]

    def list_expiring_before(self, cutoff: datetime, *, shard: int) -> list[dict]:
        """Keys of batches due to expire, for the scheduled sweep."""
        condition = Key("GSI2PK").eq(f"EXPIRY_SHARD#{shard}") & Key("GSI2SK").lt(to_iso(cutoff))
        return self.query_all(key_condition=condition, index_name="GSI2-expiry")

    def get_audit_history(self, batch_id: str, *, limit: int = 50) -> list[dict]:
        items, _ = self.query_partition(
            f"BATCH#{batch_id}", sk_prefix="AUDIT#", limit=limit, scan_forward=False
        )
        return items

    # --- writes ---

    def create_batch(self, batch: Batch) -> Batch:
        self.put(
            batch_to_item(batch),
            condition=Attr("PK").not_exists() & Attr("SK").not_exists(),
        )
        return batch

    def apply_change(self, change: StockChange, *, expected_version: int) -> Batch:
        """Persist a stock change with an optimistic-concurrency guard.

        The condition asserts the version we read is still current AND, for
        deductions, that enough units remain. A concurrent writer that got there
        first fails this check and surfaces as 409 rather than silently
        overwriting -- the lost-update problem, closed.
        """
        batch = change.batch
        item = batch_to_item(batch)

        condition = Attr("version").eq(expected_version)
        if change.units_delta < 0:
            # Re-assert non-negativity at the storage layer.
            condition = condition & Attr("availableUnits").gte(abs(change.units_delta))

        # A failed condition here is a version conflict, not a duplicate, so the
        # caller gets ConcurrentModificationError and its retry path engages.
        self.put(item, condition=condition, on_conflict="version")
        return batch

    def apply_change_with_audit(
        self,
        change: StockChange,
        *,
        expected_version: int,
        audit_item: dict,
        outbox_item: dict | None = None,
    ) -> Batch:
        """Stock change, audit row and (optionally) an outbox event, atomically.

        ADR-0005: writing the event in the same transaction is what stops a crash
        between the update and the publish from losing the event entirely.
        """
        from .dynamo import transact_write

        batch = change.batch
        table = table_name(self.logical_table)

        condition_expression = "#v = :expected"
        values: dict[str, Any] = {":expected": expected_version}
        if change.units_delta < 0:
            condition_expression += " AND availableUnits >= :needed"
            values[":needed"] = abs(change.units_delta)

        operations: list[dict] = [
            {
                "Put": {
                    "TableName": table,
                    "Item": to_dynamo(clean(batch_to_item(batch))),
                    "ConditionExpression": condition_expression,
                    "ExpressionAttributeNames": {"#v": "version"},
                    "ExpressionAttributeValues": to_expression_values(values),
                }
            },
            {"Put": {"TableName": table, "Item": to_dynamo(clean(audit_item))}},
        ]
        if outbox_item is not None:
            operations.append(
                {
                    "Put": {
                        "TableName": table_name(Tables.OUTBOX),
                        "Item": to_dynamo(clean(outbox_item)),
                    }
                }
            )

        transact_write(operations)
        return batch

    def record_verification(
        self, *, facility_id: str, batch_id: str, verified_at: datetime,
        verified_by: str, expected_version: int
    ) -> dict:
        """Write ONLY the verification fields.

        ADR-0003: this is the single code path permitted to set
        ``lastVerifiedAt``. No other repository method touches it, so an
        automated feed can never imply human verification.
        """
        # Every declared placeholder must be referenced by an expression, or
        # DynamoDB rejects the whole request with ValidationException. The
        # condition below builds its own placeholders, so none is added here.
        return self.update(
            pk=_batch_pk(facility_id),
            sk=_batch_sk(batch_id),
            update_expression="SET lastVerifiedAt = :at, verifiedBy = :by, #v = :next",
            expression_values={
                ":at": to_iso(verified_at),
                ":by": verified_by,
                ":next": expected_version + 1,
            },
            expression_names={"#v": "version"},
            condition=Attr("version").eq(expected_version),
        )
