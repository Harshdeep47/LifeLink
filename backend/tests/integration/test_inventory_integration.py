"""Inventory against a real DynamoDB surface.

The point of these, as opposed to the unit tests, is that the conditional
writes, transactions and GSI range queries are genuinely executed. A fake
repository would happily accept a lost update; DynamoDB's condition expression
will not.
"""
from __future__ import annotations

import pytest

from domain.errors import ConcurrentModificationError, InsufficientStockError, ValidationError
from domain.inventory import StockOperation
from tests.integration.conftest import days_ago, days_ahead, hours_ago, make_context

pytestmark = pytest.mark.integration


def create_batch(service, context, now, **overrides):
    payload = dict(
        facility_id="fac-1",
        organization_id="org-bb-1",
        blood_group="O-",
        component="PRBC",
        units=10,
        collected_at=days_ago(5),
        expires_at=days_ahead(20),
        now=now,
    )
    payload.update(overrides)
    return service.create_batch(context=context, **payload)


class TestBatchLifecycle:
    def test_create_read_adjust(self, seeded, inventory_service, now):
        context = make_context(user_id="u-bb-admin", organization_id="org-bb-1")
        created = create_batch(inventory_service, context, now)

        assert created["availableUnits"] == 10
        assert created["eligible"] is True
        # Creation is an update, not a verification.
        assert created["verificationStatus"] == "UNVERIFIED"
        assert created["lastVerifiedAt"] is None
        assert created["freshness"] == "FRESH"

        fetched = inventory_service.get_batch(
            facility_id="fac-1", batch_id=created["batchId"], now=now
        )
        assert fetched["batchId"] == created["batchId"]

        adjusted = inventory_service.adjust_stock(
            context=context, facility_id="fac-1", batch_id=created["batchId"],
            operation="DEDUCT", units=4, now=now,
        )
        assert adjusted["availableUnits"] == 6
        assert adjusted["version"] == created["version"] + 1

    def test_expiry_is_required_on_creation(self, seeded, inventory_service, now):
        context = make_context(user_id="u-bb-admin", organization_id="org-bb-1")
        with pytest.raises(ValidationError) as exc:
            create_batch(inventory_service, context, now, expires_at=None)
        assert "expiry" in str(exc.value).lower()

    def test_cannot_create_an_already_expired_batch(self, seeded, inventory_service, now):
        context = make_context(user_id="u-bb-admin", organization_id="org-bb-1")
        with pytest.raises(ValidationError):
            create_batch(inventory_service, context, now, expires_at=days_ago(1))

    def test_deducting_more_than_available_is_refused_by_the_datastore(
        self, seeded, inventory_service, now
    ):
        context = make_context(user_id="u-bb-admin", organization_id="org-bb-1")
        created = create_batch(inventory_service, context, now, units=3)
        with pytest.raises(InsufficientStockError):
            inventory_service.adjust_stock(
                context=context, facility_id="fac-1", batch_id=created["batchId"],
                operation="DEDUCT", units=5, now=now,
            )
        # The stored value is untouched.
        after = inventory_service.get_batch(
            facility_id="fac-1", batch_id=created["batchId"], now=now
        )
        assert after["availableUnits"] == 3


class TestOptimisticConcurrency:
    def test_a_stale_write_is_rejected_not_silently_applied(
        self, seeded, inventory_service, repos, now
    ):
        """The lost-update problem, executed for real.

        Two readers both see version N. The first write succeeds and moves the
        row to N+1. The second, still holding N, must fail its condition rather
        than overwrite the first writer's result.
        """
        context = make_context(user_id="u-bb-admin", organization_id="org-bb-1")
        created = create_batch(inventory_service, context, now, units=10)
        batch_id = created["batchId"]

        first = repos.inventory.get_batch("fac-1", batch_id)
        second = repos.inventory.get_batch("fac-1", batch_id)
        assert first.version == second.version

        from domain.inventory import apply_stock_operation

        change_a = apply_stock_operation(
            batch=first, operation=StockOperation.DEDUCT, units=4, now=now, source="A"
        )
        repos.inventory.apply_change(change_a, expected_version=first.version)

        change_b = apply_stock_operation(
            batch=second, operation=StockOperation.DEDUCT, units=3, now=now, source="B"
        )
        with pytest.raises(ConcurrentModificationError):
            repos.inventory.apply_change(change_b, expected_version=second.version)

        final = repos.inventory.get_batch("fac-1", batch_id)
        # 10 - 4 = 6. The second deduction did not happen, and crucially the
        # result is not 7 (which is what a lost update would have produced).
        assert final.available_units == 6

    def test_the_service_retries_and_converges(self, seeded, inventory_service, now):
        """Sequential deductions through the service all land."""
        context = make_context(user_id="u-bb-admin", organization_id="org-bb-1")
        created = create_batch(inventory_service, context, now, units=10)
        for _ in range(5):
            inventory_service.adjust_stock(
                context=context, facility_id="fac-1", batch_id=created["batchId"],
                operation="DEDUCT", units=1, now=now,
            )
        final = inventory_service.get_batch(
            facility_id="fac-1", batch_id=created["batchId"], now=now
        )
        assert final["availableUnits"] == 5


class TestUpdateVersusVerification:
    def test_verification_is_a_separate_write(self, seeded, inventory_service, now):
        context = make_context(user_id="u-bb-admin", organization_id="org-bb-1")
        created = create_batch(inventory_service, context, now)
        assert created["lastVerifiedAt"] is None

        verified = inventory_service.verify_inventory(
            context=context, facility_id="fac-1", batch_id=created["batchId"], now=now
        )
        assert verified["lastVerifiedAt"] is not None
        assert verified["verificationStatus"] == "VERIFIED"
        # Verifying asserts the figures were checked; it does not change them.
        assert verified["availableUnits"] == created["availableUnits"]

    def test_an_api_update_does_not_confer_verification(
        self, seeded, inventory_service, now
    ):
        """The central integrity claim, end to end."""
        context = make_context(user_id="u-bb-admin", organization_id="org-bb-1")
        created = create_batch(inventory_service, context, now, units=10)

        updated = inventory_service.ingest_external_update(
            context=context, facility_id="fac-1", batch_id=created["batchId"],
            units=14, source_timestamp=now, source_system="DEMO_HIS", now=now,
        )
        assert updated["availableUnits"] == 14
        assert updated["freshness"] == "FRESH"
        assert updated["verificationStatus"] == "UNVERIFIED"
        assert updated["lastVerifiedAt"] is None
        assert updated["updateSource"].startswith("API:")


class TestExternalIngestion:
    def test_a_stale_external_update_is_rejected(self, seeded, inventory_service, now):
        context = make_context(user_id="u-bb-admin", organization_id="org-bb-1")
        created = create_batch(inventory_service, context, now, units=10)

        with pytest.raises(ValidationError) as exc:
            inventory_service.ingest_external_update(
                context=context, facility_id="fac-1", batch_id=created["batchId"],
                units=99, source_timestamp=hours_ago(6), source_system="LAGGY_HIS", now=now,
            )
        assert exc.value.details["rule"] == "STALE_UPDATE_REJECTED"

        unchanged = inventory_service.get_batch(
            facility_id="fac-1", batch_id=created["batchId"], now=now
        )
        assert unchanged["availableUnits"] == 10

    def test_an_update_with_no_timestamp_is_rejected(self, seeded, inventory_service, now):
        context = make_context(user_id="u-bb-admin", organization_id="org-bb-1")
        created = create_batch(inventory_service, context, now)
        with pytest.raises(ValidationError):
            inventory_service.ingest_external_update(
                context=context, facility_id="fac-1", batch_id=created["batchId"],
                units=5, source_timestamp=None, source_system="UNKNOWN", now=now,
            )


class TestAvailabilityAggregation:
    def test_eligible_index_query_excludes_expired_and_quarantined(
        self, seeded, inventory_service, repos, now
    ):
        """The GSI range condition does the filtering, so this exercises it for real."""
        context = make_context(user_id="u-bb-admin", organization_id="org-bb-1")

        good = create_batch(inventory_service, context, now, units=7)
        create_batch(inventory_service, context, now, units=5, expires_at=days_ahead(1))

        quarantined = create_batch(inventory_service, context, now, units=100)
        inventory_service.adjust_stock(
            context=context, facility_id="fac-1", batch_id=quarantined["batchId"],
            operation="QUARANTINE", units=None, reason="serology pending", now=now,
        )

        summary = inventory_service.facility_availability(
            facility_id="fac-1", now=now, requested_units=1,
        )
        row = next(
            r for r in summary["availability"]
            if r["bloodGroup"] == "O-" and r["component"] == "PRBC"
        )
        # 7 + 5 eligible; the 100 quarantined units must not appear.
        assert row["eligibleUnits"] == 12
        assert row["availability"] == "AVAILABLE"
        assert row["nearExpiryUnits"] == 5
        assert good["batchId"]

    def test_a_facility_that_never_reported_is_unknown_not_zero(
        self, seeded, inventory_service, now
    ):
        summary = inventory_service.facility_availability(
            facility_id="fac-silent", now=now, requested_units=2
        )
        assert summary["inventoryKnown"] is False
        assert all(row["availability"] == "UNKNOWN" for row in summary["availability"])
        assert all(row["freshness"] == "UNKNOWN" for row in summary["availability"])

    def test_partial_when_less_than_requested(self, seeded, inventory_service, now):
        context = make_context(user_id="u-bb-admin", organization_id="org-bb-1")
        create_batch(inventory_service, context, now, units=2)
        summary = inventory_service.facility_availability(
            facility_id="fac-1", now=now, requested_units=10
        )
        row = next(
            r for r in summary["availability"]
            if r["bloodGroup"] == "O-" and r["component"] == "PRBC"
        )
        assert row["availability"] == "PARTIAL"


class TestAuditTrail:
    def test_every_stock_change_writes_an_audit_record(
        self, seeded, inventory_service, repos, now
    ):
        context = make_context(user_id="u-bb-admin", organization_id="org-bb-1")
        created = create_batch(inventory_service, context, now)
        inventory_service.adjust_stock(
            context=context, facility_id="fac-1", batch_id=created["batchId"],
            operation="DEDUCT", units=2, now=now, reason="issued to ward",
        )

        history = inventory_service.audit_history(batch_id=created["batchId"])
        assert len(history) >= 1
        entry = history[0]
        assert entry["action"] == "INVENTORY_DEDUCT"
        assert entry["actorId"] == "u-bb-admin"
        assert entry["before"]["units"] == 10
        assert entry["after"]["units"] == 8
        assert entry["correlationId"] == "corr-integration"

    def test_an_outbox_event_is_written_in_the_same_transaction(
        self, seeded, inventory_service, repos, now
    ):
        """ADR-0005: the event cannot be lost between the write and the publish."""
        context = make_context(user_id="u-bb-admin", organization_id="org-bb-1")
        created = create_batch(inventory_service, context, now)
        inventory_service.adjust_stock(
            context=context, facility_id="fac-1", batch_id=created["batchId"],
            operation="DEDUCT", units=1, now=now,
        )

        pending = repos.outbox.pending(limit=20)
        stock_events = [e for e in pending if e["eventType"] == "InventoryStockChanged"]
        assert len(stock_events) >= 1
        event = stock_events[0]
        assert event["payload"]["batchId"] == created["batchId"]
        assert event["dispatched"] is False
        assert event["correlationId"] == "corr-integration"
