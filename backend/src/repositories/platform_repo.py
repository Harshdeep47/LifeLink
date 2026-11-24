"""Cross-cutting persistence: idempotency, audit, outbox, notifications.

These four are what make the rest of the system safe to retry, observable after
the fact, and reliable across process crashes.
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta

from boto3.dynamodb.conditions import Attr, Key

from domain.clock import to_iso
from domain.errors import RequestInProgressError

from .dynamo import DynamoRepository, Tables

IDEMPOTENCY_TTL_HOURS = 24
# How long an IN_PROGRESS claim is honoured before another worker may retake it.
# Without this, a crashed request would block its own retry until TTL expiry.
STALE_CLAIM_MINUTES = 5


class IdempotencyRepository(DynamoRepository):
    """Exactly-once semantics for mutating requests and queue consumers (ADR-0009)."""

    logical_table = Tables.IDEMPOTENCY

    def claim(self, key: str, *, now: datetime, operation: str) -> dict | None:
        """Try to claim a key.

        Returns None when the claim succeeded (first execution). Returns the
        stored record when the work was already done, so the caller can replay
        the original result instead of repeating a side effect.
        """
        expires = now + timedelta(hours=IDEMPOTENCY_TTL_HOURS)
        item = {
            "PK": key,
            "SK": "CLAIM",
            "status": "IN_PROGRESS",
            "operation": operation,
            "claimedAt": to_iso(now),
            "expiresAtEpoch": int(expires.timestamp()),
        }
        try:
            self.put(item, condition=Attr("PK").not_exists())
            return None
        except Exception:
            existing = self.get_consistent(key, "CLAIM")
            if existing is None:
                # The row vanished between the failed put and this read (TTL).
                # Treat as a fresh claim rather than failing the request.
                self.put(item)
                return None

            if existing.get("status") == "COMPLETED":
                return existing

            claimed_at = existing.get("claimedAt")
            if claimed_at:
                from domain.clock import parse_iso

                age = (now - parse_iso(claimed_at)).total_seconds() / 60.0
                if age > STALE_CLAIM_MINUTES:
                    # The previous attempt almost certainly died. Retake it.
                    self.put(item)
                    return None

            raise RequestInProgressError(
                "an identical request is currently being processed",
                details={"idempotencyKey": key},
            ) from None

    def complete(self, key: str, *, result: dict, now: datetime) -> None:
        expires = now + timedelta(hours=IDEMPOTENCY_TTL_HOURS)
        self.put(
            {
                "PK": key,
                "SK": "CLAIM",
                "status": "COMPLETED",
                "result": result,
                "completedAt": to_iso(now),
                "expiresAtEpoch": int(expires.timestamp()),
            }
        )

    def release(self, key: str) -> None:
        """Drop a claim after an unrecoverable failure so a retry can proceed."""
        self.delete(key, "CLAIM")


class AuditRepository(DynamoRepository):
    """Append-only audit trail (spec 8.4).

    In AWS the Lambda role is granted PutItem only -- no UpdateItem, no
    DeleteItem -- so the application physically cannot rewrite history. That is
    tamper *resistance* within the platform's means, not immutability, and the
    documentation says so rather than overclaiming.
    """

    logical_table = Tables.AUDIT

    def record(
        self,
        *,
        actor_id: str,
        actor_role: str | None,
        action: str,
        resource_type: str,
        resource_id: str,
        correlation_id: str,
        occurred_at: datetime,
        organization_id: str | None = None,
        before: dict | None = None,
        after: dict | None = None,
        metadata: dict | None = None,
    ) -> dict:
        event_id = str(uuid.uuid4())
        timestamp = to_iso(occurred_at)
        item = {
            "PK": f"RESOURCE#{resource_type}#{resource_id}",
            "SK": f"{timestamp}#{event_id}",
            "GSI1PK": f"ACTOR#{actor_id}",
            "GSI1SK": f"{timestamp}#{event_id}",
            "eventId": event_id,
            "actorId": actor_id,
            "actorRole": actor_role,
            "action": action,
            "resourceType": resource_type,
            "resourceId": resource_id,
            "organizationId": organization_id,
            "correlationId": correlation_id,
            "occurredAt": timestamp,
            "before": before,
            "after": after,
            "metadata": metadata,
        }
        self.put(item)
        return item

    @staticmethod
    def build_item(**kwargs) -> dict:
        """Build an audit item without writing it, for inclusion in a transaction."""
        event_id = str(uuid.uuid4())
        timestamp = to_iso(kwargs["occurred_at"])
        return {
            "PK": f"RESOURCE#{kwargs['resource_type']}#{kwargs['resource_id']}",
            "SK": f"{timestamp}#{event_id}",
            "GSI1PK": f"ACTOR#{kwargs['actor_id']}",
            "GSI1SK": f"{timestamp}#{event_id}",
            "eventId": event_id,
            "actorId": kwargs["actor_id"],
            "actorRole": kwargs.get("actor_role"),
            "action": kwargs["action"],
            "resourceType": kwargs["resource_type"],
            "resourceId": kwargs["resource_id"],
            "organizationId": kwargs.get("organization_id"),
            "correlationId": kwargs["correlation_id"],
            "occurredAt": timestamp,
            "before": kwargs.get("before"),
            "after": kwargs.get("after"),
            "metadata": kwargs.get("metadata"),
        }

    def history_for_resource(self, resource_type: str, resource_id: str,
                             *, limit: int = 50) -> list[dict]:
        items, _ = self.query_partition(
            f"RESOURCE#{resource_type}#{resource_id}", limit=limit, scan_forward=False
        )
        return items

    def history_for_actor(self, actor_id: str, *, limit: int = 50) -> list[dict]:
        items, _ = self.query(
            key_condition=Key("GSI1PK").eq(f"ACTOR#{actor_id}"),
            index_name="GSI1-actor",
            limit=limit,
            scan_forward=False,
        )
        return items


class OutboxRepository(DynamoRepository):
    """Transactional outbox (ADR-0005)."""

    logical_table = Tables.OUTBOX

    @staticmethod
    def build_event(
        *,
        event_type: str,
        payload: dict,
        correlation_id: str,
        occurred_at: datetime,
        aggregate_id: str,
        event_version: int = 1,
        causation_id: str | None = None,
    ) -> dict:
        event_id = str(uuid.uuid4())
        timestamp = to_iso(occurred_at)
        return {
            "PK": f"EVENT#{event_id}",
            "SK": "META",
            "GSI1PK": "PENDING",
            "GSI1SK": timestamp,
            "eventId": event_id,
            "eventType": event_type,
            "eventVersion": event_version,
            "aggregateId": aggregate_id,
            "occurredAt": timestamp,
            "correlationId": correlation_id,
            "causationId": causation_id,
            "payload": payload,
            "dispatched": False,
        }

    def append(self, event: dict) -> dict:
        self.put(event)
        return event

    def pending(self, *, limit: int = 50) -> list[dict]:
        items, _ = self.query(
            key_condition=Key("GSI1PK").eq("PENDING"),
            index_name="GSI1-pending",
            limit=limit,
        )
        return items

    def mark_dispatched(self, event_id: str, *, now: datetime) -> None:
        expires = now + timedelta(days=7)
        self.update(
            pk=f"EVENT#{event_id}",
            sk="META",
            update_expression=(
                "SET dispatched = :d, dispatchedAt = :at, expiresAtEpoch = :ttl "
                "REMOVE GSI1PK, GSI1SK"
            ),
            expression_values={
                ":d": True,
                ":at": to_iso(now),
                ":ttl": int(expires.timestamp()),
            },
        )


class NotificationRepository(DynamoRepository):
    logical_table = Tables.NOTIFICATIONS

    def get_preferences(self, user_id: str) -> dict | None:
        return self.get(f"USER#{user_id}", "PREFERENCES")

    def save_preferences(self, user_id: str, preferences: dict) -> dict:
        item = {
            "PK": f"USER#{user_id}",
            "SK": "PREFERENCES",
            "entityType": "NOTIFICATION_PREFERENCES",
            **preferences,
        }
        self.put(item)
        return item

    def record_notification(self, notification: dict, *, now: datetime) -> dict:
        notification_id = notification.get("notificationId") or str(uuid.uuid4())
        expires = now + timedelta(days=90)
        item = {
            "PK": f"USER#{notification['userId']}",
            # Reverse-sortable so the newest notifications come first naturally.
            "SK": f"NOTIF#{to_iso(now)}#{notification_id}",
            "GSI1PK": f"DELIVERY#{notification.get('deliveryStatus', 'PENDING')}",
            "GSI1SK": to_iso(now),
            "notificationId": notification_id,
            "createdAt": to_iso(now),
            "expiresAtEpoch": int(expires.timestamp()),
            **notification,
        }
        self.put(item)
        return item

    def list_for_user(self, user_id: str, *, limit: int = 50) -> list[dict]:
        items, _ = self.query_partition(
            f"USER#{user_id}", sk_prefix="NOTIF#", limit=limit, scan_forward=False
        )
        return items

    def update_delivery_status(
        self, *, user_id: str, sort_key: str, status: str, detail: str | None, now: datetime
    ) -> dict:
        return self.update(
            pk=f"USER#{user_id}",
            sk=sort_key,
            update_expression=(
                "SET deliveryStatus = :s, deliveryDetail = :d, deliveryUpdatedAt = :at, "
                "GSI1PK = :gsi"
            ),
            expression_values={
                ":s": status,
                ":d": detail,
                ":at": to_iso(now),
                ":gsi": f"DELIVERY#{status}",
            },
        )

    def mark_sent_marker(self, *, user_id: str, dedupe_key: str, now: datetime) -> bool:
        """Claim a duplicate-suppression marker.

        Returns True when this is the first send for the key. Camp reminders and
        alert notifications both use this so a retried job cannot double-notify.
        """
        expires = now + timedelta(days=30)
        try:
            self.put(
                {
                    "PK": f"USER#{user_id}",
                    "SK": f"SENT#{dedupe_key}",
                    "sentAt": to_iso(now),
                    "expiresAtEpoch": int(expires.timestamp()),
                },
                condition=Attr("SK").not_exists(),
            )
            return True
        except Exception:
            return False


def epoch_now() -> int:
    return int(time.time())


__all__ = [
    "AuditRepository",
    "IdempotencyRepository",
    "NotificationRepository",
    "OutboxRepository",
    "epoch_now",
]
