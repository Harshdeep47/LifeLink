"""Unknown inventory must never be reported as a quantity.

LifeLink's first rule is that "we have not been told" and "there are none" are
different facts that lead a user to opposite actions: one calls the facility,
the other does not.

The rule was enforced in the search endpoint and broken in the per-facility
availability matrix. ``AvailabilitySummary.eligible_units`` was typed ``int``
and set to ``0`` for an unreported facility; the search path happened to
special-case it and publish ``null``, while the matrix published ``0``. The
live deployed API returned, for a facility that has never submitted anything:

    {"availability": "UNKNOWN", "eligibleUnits": 0, ...}

These tests pin the corrected behaviour at the domain boundary, where every
caller inherits it, rather than in each service.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from domain.blood import ALL_COMPONENTS, ALL_GROUPS, BatchStatus, BloodGroup, Component
from domain.inventory import AvailabilityState, Batch, summarise_availability

NOW = datetime(2026, 11, 15, 12, 0, 0, tzinfo=UTC)


def batch(units: int, *, group=BloodGroup.O_NEG, component=Component.PRBC) -> Batch:
    return Batch(
        batch_id="b1",
        facility_id="fac-1",
        organization_id="org-1",
        blood_group=group,
        component=component,
        available_units=units,
        status=BatchStatus.AVAILABLE,
        collected_at=NOW - timedelta(days=3),
        expires_at=NOW + timedelta(days=20),
        last_updated_at=NOW - timedelta(hours=1),
        last_verified_at=None,
        update_source="TEST",
        version=1,
    )


class TestUnreportedInventory:
    def test_eligible_units_is_none_not_zero(self):
        """The regression test for the deployed defect."""
        summary = summarise_availability(
            batches=[],
            blood_group=BloodGroup.O_NEG,
            component=Component.PRBC,
            requested_units=2,
            now=NOW,
            inventory_known=False,
        )
        assert summary.state is AvailabilityState.UNKNOWN
        assert summary.eligible_units is None, "unknown must not be reported as a quantity"

    def test_none_is_not_merely_falsy(self):
        """`0` is falsy too, so identity is the assertion that matters."""
        summary = summarise_availability(
            batches=[],
            blood_group=BloodGroup.A_POS,
            component=Component.WHOLE_BLOOD,
            requested_units=1,
            now=NOW,
            inventory_known=False,
        )
        assert summary.eligible_units is not 0  # noqa: F632 - identity is the point
        assert summary.eligible_units is None

    @pytest.mark.parametrize("group", ALL_GROUPS)
    @pytest.mark.parametrize("component", ALL_COMPONENTS)
    def test_holds_for_every_group_and_component(self, group, component):
        """All 32 cells of an unreported facility's matrix, not just one."""
        summary = summarise_availability(
            batches=[],
            blood_group=group,
            component=component,
            requested_units=1,
            now=NOW,
            inventory_known=False,
        )
        assert summary.state is AvailabilityState.UNKNOWN
        assert summary.eligible_units is None

    def test_unreported_ignores_any_batches_passed(self):
        """inventory_known=False wins, even if batches somehow arrive.

        Defensive: a caller that fetched batches but also decided inventory is
        unknown must not get a quantity back.
        """
        summary = summarise_availability(
            batches=[batch(12)],
            blood_group=BloodGroup.O_NEG,
            component=Component.PRBC,
            requested_units=2,
            now=NOW,
            inventory_known=False,
        )
        assert summary.state is AvailabilityState.UNKNOWN
        assert summary.eligible_units is None


class TestGenuineZeroIsStillZero:
    """The fix must not blur the other direction.

    A facility that reports and has nothing must say 0, not None. Collapsing
    these two would be the same error with the sign reversed.
    """

    def test_reported_but_empty_is_zero(self):
        summary = summarise_availability(
            batches=[],
            blood_group=BloodGroup.O_NEG,
            component=Component.PRBC,
            requested_units=2,
            now=NOW,
            inventory_known=True,
        )
        assert summary.eligible_units == 0
        assert summary.eligible_units is not None
        assert summary.state is not AvailabilityState.UNKNOWN

    def test_zero_unit_batch_is_zero(self):
        summary = summarise_availability(
            batches=[batch(0)],
            blood_group=BloodGroup.O_NEG,
            component=Component.PRBC,
            requested_units=1,
            now=NOW,
            inventory_known=True,
        )
        assert summary.eligible_units == 0

    def test_available_stock_reports_its_quantity(self):
        summary = summarise_availability(
            batches=[batch(7)],
            blood_group=BloodGroup.O_NEG,
            component=Component.PRBC,
            requested_units=4,
            now=NOW,
            inventory_known=True,
        )
        assert summary.eligible_units == 7
        assert summary.state is AvailabilityState.AVAILABLE

    def test_partial_reports_what_exists(self):
        summary = summarise_availability(
            batches=[batch(2)],
            blood_group=BloodGroup.O_NEG,
            component=Component.PRBC,
            requested_units=5,
            now=NOW,
            inventory_known=True,
        )
        assert summary.eligible_units == 2
        assert summary.state is AvailabilityState.PARTIAL


class TestSufficiencyNeverSatisfiedByUnknown:
    """An unknown quantity must not satisfy a stock requirement."""

    def test_none_does_not_compare_as_enough(self):
        summary = summarise_availability(
            batches=[],
            blood_group=BloodGroup.O_NEG,
            component=Component.PRBC,
            requested_units=1,
            now=NOW,
            inventory_known=False,
        )
        units = summary.eligible_units
        sufficient = units is not None and units >= 1
        assert sufficient is False
