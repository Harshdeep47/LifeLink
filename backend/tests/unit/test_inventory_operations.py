"""Stock operations, negative-stock prevention, stale updates and availability.

Covers spec 3.3, 3.6 and the concurrency-related edge cases.
"""
from __future__ import annotations

import pytest

from domain.blood import AvailabilityState, BatchStatus, BloodGroup, Component, FreshnessLabel
from domain.errors import (
    InsufficientStockError,
    InvalidStateTransitionError,
    ValidationError,
)
from domain.inventory import (
    StockOperation,
    apply_stock_operation,
    is_stale_update,
    summarise_availability,
)
from tests.conftest import NOW, days_ago, days_ahead, hours_ago, make_batch

pytestmark = pytest.mark.unit


class TestStockDeduction:
    def test_deduct_reduces_units_and_bumps_version(self):
        batch = make_batch(available_units=10, version=3)
        change = apply_stock_operation(
            batch=batch, operation=StockOperation.DEDUCT, units=4, now=NOW, source="STAFF"
        )
        assert change.batch.available_units == 6
        assert change.batch.version == 4
        assert change.units_delta == -4
        assert change.previous_units == 10

    def test_deducting_more_than_available_is_refused(self):
        """Spec 3.3: never allow a negative available quantity."""
        batch = make_batch(available_units=3)
        with pytest.raises(InsufficientStockError) as exc:
            apply_stock_operation(
                batch=batch, operation=StockOperation.DEDUCT, units=5, now=NOW, source="STAFF"
            )
        assert exc.value.details["available"] == 3
        assert exc.value.code == "INSUFFICIENT_STOCK"

    def test_deducting_everything_marks_batch_consumed(self):
        batch = make_batch(available_units=5)
        change = apply_stock_operation(
            batch=batch, operation=StockOperation.DEDUCT, units=5, now=NOW, source="STAFF"
        )
        assert change.batch.available_units == 0
        assert change.batch.status is BatchStatus.CONSUMED

    def test_cannot_deduct_from_quarantined_batch(self):
        batch = make_batch(status=BatchStatus.QUARANTINED, quarantine_reason="under test")
        with pytest.raises(InvalidStateTransitionError):
            apply_stock_operation(
                batch=batch, operation=StockOperation.DEDUCT, units=1, now=NOW, source="STAFF"
            )

    def test_negative_unit_count_is_rejected(self):
        batch = make_batch(available_units=10)
        with pytest.raises(ValidationError):
            apply_stock_operation(
                batch=batch, operation=StockOperation.DEDUCT, units=-1, now=NOW, source="STAFF"
            )

    def test_zero_unit_deduction_is_rejected(self):
        batch = make_batch(available_units=10)
        with pytest.raises(ValidationError):
            apply_stock_operation(
                batch=batch, operation=StockOperation.DEDUCT, units=0, now=NOW, source="STAFF"
            )


class TestStockAddition:
    def test_add_increases_units(self):
        batch = make_batch(available_units=2)
        change = apply_stock_operation(
            batch=batch, operation=StockOperation.ADD, units=8, now=NOW, source="STAFF"
        )
        assert change.batch.available_units == 10
        assert change.units_delta == 8

    def test_cannot_add_to_expired_batch(self):
        batch = make_batch(status=BatchStatus.EXPIRED)
        with pytest.raises(InvalidStateTransitionError):
            apply_stock_operation(
                batch=batch, operation=StockOperation.ADD, units=1, now=NOW, source="STAFF"
            )


class TestQuarantineLifecycle:
    def test_quarantine_requires_a_reason(self):
        batch = make_batch()
        with pytest.raises(ValidationError):
            apply_stock_operation(
                batch=batch, operation=StockOperation.QUARANTINE, units=None, now=NOW, source="STAFF"
            )

    def test_quarantine_sets_status_and_reason(self):
        batch = make_batch()
        change = apply_stock_operation(
            batch=batch,
            operation=StockOperation.QUARANTINE,
            units=None,
            now=NOW,
            source="STAFF",
            reason="awaiting serology",
        )
        assert change.batch.status is BatchStatus.QUARANTINED
        assert change.batch.quarantine_reason == "awaiting serology"

    def test_release_returns_batch_to_available(self):
        batch = make_batch(status=BatchStatus.QUARANTINED, quarantine_reason="held")
        change = apply_stock_operation(
            batch=batch,
            operation=StockOperation.RELEASE_QUARANTINE,
            units=None,
            now=NOW,
            source="STAFF",
        )
        assert change.batch.status is BatchStatus.AVAILABLE
        assert change.batch.quarantine_reason is None

    def test_releasing_an_expired_batch_does_not_resurrect_it(self):
        """Release must never make expired stock available again."""
        batch = make_batch(
            status=BatchStatus.QUARANTINED, quarantine_reason="held", expires_at=hours_ago(2)
        )
        change = apply_stock_operation(
            batch=batch,
            operation=StockOperation.RELEASE_QUARANTINE,
            units=None,
            now=NOW,
            source="STAFF",
        )
        assert change.batch.status is BatchStatus.EXPIRED


class TestStaleUpdateRejection:
    """Spec 3.6: a delayed external update must not overwrite newer state."""

    def test_older_source_timestamp_is_stale(self):
        assert is_stale_update(hours_ago(5), hours_ago(1)) is True

    def test_newer_source_timestamp_is_accepted(self):
        assert is_stale_update(hours_ago(1), hours_ago(5)) is False

    def test_missing_source_timestamp_is_treated_as_stale(self):
        """An external system that cannot say when it read the stock does not get
        to overwrite a known-newer value."""
        assert is_stale_update(None, hours_ago(5)) is True


class TestAvailabilitySummary:
    def test_sums_only_eligible_batches(self):
        batches = [
            make_batch(batch_id="ok-1", available_units=5),
            make_batch(batch_id="expired", available_units=100, expires_at=hours_ago(1)),
            make_batch(batch_id="quarantined", available_units=50, status=BatchStatus.QUARANTINED),
            make_batch(batch_id="ok-2", available_units=3),
        ]
        summary = summarise_availability(
            batches=batches,
            blood_group=BloodGroup.O_NEG,
            component=Component.PRBC,
            requested_units=2,
            now=NOW,
        )
        assert summary.eligible_units == 8
        assert summary.batch_count == 2
        assert summary.state is AvailabilityState.AVAILABLE

    def test_partial_when_less_than_requested(self):
        batches = [make_batch(available_units=2)]
        summary = summarise_availability(
            batches=batches,
            blood_group=BloodGroup.O_NEG,
            component=Component.PRBC,
            requested_units=10,
            now=NOW,
        )
        assert summary.state is AvailabilityState.PARTIAL
        assert summary.eligible_units == 2

    def test_unknown_inventory_is_not_converted_to_zero(self):
        """Spec 4.4: unknown must remain UNKNOWN.

        'We have no data' and 'they have none' lead a user to entirely different
        actions, so conflating them is a safety issue, not a cosmetic one.
        """
        summary = summarise_availability(
            batches=[],
            blood_group=BloodGroup.O_NEG,
            component=Component.PRBC,
            requested_units=5,
            now=NOW,
            inventory_known=False,
        )
        assert summary.state is AvailabilityState.UNKNOWN
        assert summary.freshness is FreshnessLabel.UNKNOWN

    def test_known_but_empty_inventory_is_unavailable_not_unknown(self):
        summary = summarise_availability(
            batches=[],
            blood_group=BloodGroup.O_NEG,
            component=Component.PRBC,
            requested_units=5,
            now=NOW,
            inventory_known=True,
        )
        assert summary.state is AvailabilityState.UNAVAILABLE

    def test_filters_by_group_and_component_independently(self):
        """Spec 3.2: group and component are separate dimensions."""
        batches = [
            make_batch(batch_id="a", blood_group=BloodGroup.O_NEG, component=Component.PRBC,
                       available_units=5),
            make_batch(batch_id="b", blood_group=BloodGroup.O_NEG, component=Component.FFP,
                       available_units=99),
            make_batch(batch_id="c", blood_group=BloodGroup.A_POS, component=Component.PRBC,
                       available_units=99),
        ]
        summary = summarise_availability(
            batches=batches,
            blood_group=BloodGroup.O_NEG,
            component=Component.PRBC,
            requested_units=1,
            now=NOW,
        )
        assert summary.eligible_units == 5

    def test_near_expiry_units_are_counted_separately(self):
        batches = [
            make_batch(batch_id="soon", available_units=4, expires_at=days_ahead(1)),
            make_batch(batch_id="later", available_units=6, expires_at=days_ahead(20)),
        ]
        summary = summarise_availability(
            batches=batches,
            blood_group=BloodGroup.O_NEG,
            component=Component.PRBC,
            requested_units=1,
            now=NOW,
        )
        assert summary.eligible_units == 10
        assert summary.near_expiry_units == 4
        assert summary.earliest_expiry == days_ahead(1)

    def test_summary_freshness_reflects_newest_relevant_batch(self):
        batches = [
            make_batch(batch_id="old", available_units=1, last_updated_at=days_ago(5)),
            make_batch(batch_id="new", available_units=1, last_updated_at=hours_ago(2)),
        ]
        summary = summarise_availability(
            batches=batches,
            blood_group=BloodGroup.O_NEG,
            component=Component.PRBC,
            requested_units=1,
            now=NOW,
        )
        assert summary.freshness is FreshnessLabel.FRESH
