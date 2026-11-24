"""Background workers: queue consumers, stream publisher, scheduled jobs.

Every consumer is idempotent. Queue delivery is at-least-once, so a message
arriving twice is normal operation rather than an error, and the idempotency
table is what makes the second delivery a no-op instead of a double effect.

Batch handlers return ``batchItemFailures`` so that one bad message does not
force the whole batch to be retried -- which, at this account's concurrency
ceiling of 10, would turn a single poison message into a backlog.
"""
from __future__ import annotations

import contextlib
import json
from typing import Any

from appcore.context import Principal, RequestContext, new_correlation_id
from appcore.logging import configure_logging, get_logger
from domain.clock import now_utc
from services.container import get_services

configure_logging()

SYSTEM_PRINCIPAL = Principal(
    user_id="system",
    email=None,
    roles=("PLATFORM_ADMIN",),
    organization_id=None,
    account_status="ACTIVE",
    display_name="LifeLink scheduler",
)


def system_context(correlation_id: str | None = None) -> RequestContext:
    """Context for work no human initiated. Still audited, under 'system'."""
    return RequestContext(
        correlation_id=correlation_id or new_correlation_id(),
        principal=SYSTEM_PRINCIPAL,
    )


def _parse_record(record: dict) -> dict:
    body = record.get("body")
    if isinstance(body, str):
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {}
    return body or {}


def _claim(event_id: str, operation: str, now) -> bool:
    """Returns True when this worker should do the work.

    False means an earlier delivery already completed it, which is the expected
    outcome for a duplicate rather than a failure.
    """
    if not event_id:
        # Without an id there is no way to deduplicate; process and rely on the
        # handler's own idempotency.
        return True
    services = get_services()
    existing = services.repos.idempotency.claim(
        f"worker#{operation}#{event_id}", now=now, operation=operation
    )
    return existing is None


def _complete(event_id: str, operation: str, result: dict, now) -> None:
    if not event_id:
        return
    get_services().repos.idempotency.complete(
        f"worker#{operation}#{event_id}", result=result, now=now
    )


# ---------------------------------------------------------------------------
# Notification queue consumer
# ---------------------------------------------------------------------------


def notification_handler(event: dict, lambda_context=None) -> dict:
    """Send queued notifications.

    A queue write is not a delivery (spec 10.3), so this is where delivery
    actually happens and where its real status is recorded.
    """
    now = now_utc()
    services = get_services()
    failures: list[dict] = []

    for record in event.get("Records", []):
        message = _parse_record(record)
        correlation_id = message.get("correlationId") or new_correlation_id()
        log = get_logger(__name__, system_context(correlation_id))
        event_id = message.get("eventId", "")

        try:
            if not _claim(event_id, "notify", now):
                log.info("duplicate notification suppressed",
                         event="worker.notify.duplicate", eventId=event_id)
                continue

            payload = message.get("payload", message)
            outcome = services.notifications.notify(
                user_id=payload["userId"],
                category=payload.get("category", "ACCOUNT_NOTICE"),
                subject=payload.get("subject", "LifeLink notification"),
                body=payload.get("body", ""),
                now=now,
                metadata=payload.get("metadata"),
                dedupe_key=payload.get("dedupeKey"),
            )
            _complete(event_id, "notify", outcome.to_dict(), now)
            log.info("notification processed", event="worker.notify.done",
                     delivered=outcome.any_delivered, suppressed=outcome.suppressed)
        except Exception as exc:
            log.exception("notification failed", event="worker.notify.failed",
                          error=str(exc)[:300])
            failures.append({"itemIdentifier": record.get("messageId", "")})

    return {"batchItemFailures": failures}


# ---------------------------------------------------------------------------
# Work queue consumer
# ---------------------------------------------------------------------------


def work_handler(event: dict, lambda_context=None) -> dict:
    """Follow-up work triggered by domain events.

    Chiefly: stock changed at a facility, so find the alerts that were waiting
    for it. That reverse lookup uses the alert match index, so it stays a
    bounded query rather than a scan.
    """
    now = now_utc()
    services = get_services()
    failures: list[dict] = []

    for record in event.get("Records", []):
        message = _parse_record(record)
        correlation_id = message.get("correlationId") or new_correlation_id()
        context = system_context(correlation_id)
        log = get_logger(__name__, context)
        event_id = message.get("eventId", "")
        event_type = message.get("eventType", "")

        try:
            if not _claim(event_id, "work", now):
                log.info("duplicate work message suppressed",
                         event="worker.work.duplicate", eventId=event_id)
                continue

            payload = message.get("payload", {})
            result: dict[str, Any] = {"eventType": event_type}

            if event_type in ("InventoryStockChanged", "InventoryBatchCreated"):
                # Only an increase can newly satisfy a waiting alert.
                if payload.get("unitsDelta", 0) > 0 or event_type == "InventoryBatchCreated":
                    result = services.alerts.match_on_stock_change(
                        facility_id=payload["facilityId"],
                        blood_group=payload["bloodGroup"],
                        component=payload["component"],
                        now=now,
                        context=context,
                    )
                else:
                    result = {"skipped": "NOT_AN_INCREASE"}
            else:
                result = {"skipped": "UNHANDLED_EVENT_TYPE", "eventType": event_type}
                log.warning("unhandled event type", event="worker.work.unhandled",
                            eventType=event_type)

            _complete(event_id, "work", result, now)
            log.info("work message processed", event="worker.work.done", result=result)
        except Exception as exc:
            log.exception("work message failed", event="worker.work.failed",
                          error=str(exc)[:300])
            failures.append({"itemIdentifier": record.get("messageId", "")})

    return {"batchItemFailures": failures}


# ---------------------------------------------------------------------------
# Outbox stream publisher
# ---------------------------------------------------------------------------

# Which queue each event type is routed to.
EVENT_ROUTING: dict[str, str] = {
    "InventoryStockChanged": "work",
    "InventoryBatchCreated": "work",
    "EmergencyRequestCreated": "work",
    "NotificationRequested": "notification",
}


def outbox_handler(event: dict, lambda_context=None) -> dict:
    """Publish outbox rows to SQS and mark them dispatched.

    The outbox row was written in the same transaction as its domain change
    (ADR-0005), so by the time this runs the event cannot have been lost. The
    worst case is publishing it twice, which consumers absorb.
    """
    import boto3

    now = now_utc()
    services = get_services()
    sqs = boto3.client("sqs")

    import os

    queues = {
        "work": os.environ.get("WORK_QUEUE_URL", ""),
        "notification": os.environ.get("NOTIFICATION_QUEUE_URL", ""),
    }
    failures: list[dict] = []

    for record in event.get("Records", []):
        if record.get("eventName") not in ("INSERT", "MODIFY"):
            continue

        image = record.get("dynamodb", {}).get("NewImage", {})
        if not image:
            continue

        # DynamoDB Streams uses the low-level attribute-value format.
        def plain(attribute: dict):
            if "S" in attribute:
                return attribute["S"]
            if "N" in attribute:
                value = attribute["N"]
                return int(value) if "." not in value else float(value)
            if "BOOL" in attribute:
                return attribute["BOOL"]
            if "M" in attribute:
                return {k: plain(v) for k, v in attribute["M"].items()}
            if "L" in attribute:
                return [plain(v) for v in attribute["L"]]
            if "NULL" in attribute:
                return None
            return None

        row = {k: plain(v) for k, v in image.items()}
        if row.get("dispatched"):
            continue

        event_id = row.get("eventId", "")
        event_type = row.get("eventType", "")
        correlation_id = row.get("correlationId") or new_correlation_id()
        log = get_logger(__name__, system_context(correlation_id))

        target = EVENT_ROUTING.get(event_type)
        if target is None:
            log.warning("no route for event type; marking dispatched to avoid a stuck row",
                        event="outbox.unrouted", eventType=event_type)
            # Best effort: if this fails the row stays pending and the
            # reconciliation alarm picks it up, which is the safe outcome.
            with contextlib.suppress(Exception):
                services.repos.outbox.mark_dispatched(event_id, now=now)
            continue

        queue_url = queues.get(target, "")
        if not queue_url:
            log.error("queue url not configured", event="outbox.no_queue", target=target)
            failures.append({"itemIdentifier": record.get("eventID", "")})
            continue

        try:
            sqs.send_message(
                QueueUrl=queue_url,
                MessageBody=json.dumps(
                    {
                        "eventId": event_id,
                        "eventType": event_type,
                        "eventVersion": row.get("eventVersion", 1),
                        "occurredAt": row.get("occurredAt"),
                        "correlationId": correlation_id,
                        "aggregateId": row.get("aggregateId"),
                        "payload": row.get("payload", {}),
                    },
                    default=str,
                ),
            )
            services.repos.outbox.mark_dispatched(event_id, now=now)
            log.info("outbox event dispatched", event="outbox.dispatched",
                     eventType=event_type, target=target)
        except Exception as exc:
            # Leaving the row undispatched is the safe failure: the
            # reconciliation job and the pending-rows alarm will surface it.
            log.exception("outbox dispatch failed", event="outbox.failed",
                          eventId=event_id, error=str(exc)[:300])
            failures.append({"itemIdentifier": record.get("eventID", "")})

    return {"batchItemFailures": failures}


# ---------------------------------------------------------------------------
# Scheduled jobs
# ---------------------------------------------------------------------------


def dispatcher_handler(event: dict, lambda_context=None) -> dict:
    """Priority dispatcher (ADR-0006), on a one-minute schedule.

    Recomputes effective priority with aging so P3 cannot starve, then processes
    in priority-then-FIFO order. Hospital-certified clinical priority is never
    modified here.
    """
    context = system_context()
    log = get_logger(__name__, context)
    services = get_services()
    now = now_utc()

    try:
        outcome = services.emergency.run_dispatcher(context=context, now=now, batch_size=10)
        expired = services.emergency.expire_overdue(context=context, now=now)
        log.info("dispatcher complete", event="scheduler.dispatch.done",
                 processed=len(outcome.get("processed", [])),
                 aged=len(outcome.get("priorityAged", [])),
                 expired=expired.get("expired", 0))
        return {"statusCode": 200, "dispatch": outcome, "expiry": expired}
    except Exception as exc:
        log.exception("dispatcher failed", event="scheduler.dispatch.failed",
                      error=str(exc)[:300])
        # Re-raised so the Lambda error metric fires its alarm. A silently
        # failing dispatcher means emergency requests stop being matched.
        raise


def maintenance_handler(event: dict, lambda_context=None) -> dict:
    """Expiry sweep, camp status transitions and camp reminders.

    Each step is independent: one failing must not prevent the others, so
    failures are collected and reported rather than raised immediately.
    """
    context = system_context()
    log = get_logger(__name__, context)
    services = get_services()
    now = now_utc()
    results: dict[str, Any] = {}
    errors: list[str] = []

    try:
        results["expiry"] = services.inventory.sweep_expired(context=context, now=now)
    except Exception as exc:
        errors.append(f"expiry: {exc}")
        log.exception("expiry sweep failed", event="scheduler.expiry.failed")

    try:
        results["reminders"] = services.camps.send_due_reminders(now=now, context=context)
    except Exception as exc:
        errors.append(f"reminders: {exc}")
        log.exception("reminder sweep failed", event="scheduler.reminders.failed")

    try:
        # Reservation expiry is swept actively rather than left to DynamoDB
        # TTL: TTL deletes within roughly 48 hours on a best-effort basis,
        # which would keep units held long after the hold ended.
        results["reservations"] = services.reservations.expire_due(
            now=now, correlation_id=context.correlation_id
        )
    except Exception as exc:
        errors.append(f"reservations: {exc}")
        log.exception("reservation expiry failed", event="scheduler.reservations.failed")

    try:
        results["alerts"] = services.alerts.expire_due_alerts(now=now, context=context)
    except Exception as exc:
        errors.append(f"alerts: {exc}")
        log.exception("alert expiry failed", event="scheduler.alerts.failed")

    log.info("maintenance complete", event="scheduler.maintenance.done",
             results=results, errorCount=len(errors))

    if errors:
        raise RuntimeError(f"maintenance completed with {len(errors)} failures: {errors}")
    return {"statusCode": 200, **results}
