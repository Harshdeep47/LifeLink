"""Reservations against a real DynamoDB-compatible datastore.

The unit tests prove the *rules*. These prove the thing only the datastore can
enforce: that two callers racing for the last units cannot both win.

That is the whole reason this feature needed a transaction rather than a
read-check-write. A unit test cannot demonstrate it, because in a single
process there is no race — the window exists only between a read and a write
that cross the network.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from domain.blood import BloodGroup, Component
from domain.errors import ConcurrentModificationError, DuplicateError
from domain.reservations import (
    Reservation,
    ReservationStatus,
    apply_transition,
    held_units,
)
from repositories.reservation_repo import ReservationRepository

NOW = datetime(2026, 11, 15, 12, 0, 0, tzinfo=UTC)

GROUP = BloodGroup.O_NEG
COMPONENT = Component.PRBC


def make(reservation_id: str, units: int, *, user="user-1", minutes=120) -> Reservation:
    return Reservation(
        reservation_id=reservation_id,
        facility_id="fac-race-1",
        organization_id="org-1",
        requester_user_id=user,
        blood_group=GROUP,
        component=COMPONENT,
        units=units,
        status=ReservationStatus.PENDING,
        created_at=NOW,
        expires_at=NOW + timedelta(minutes=minutes),
    )


@pytest.fixture
def repo(aws):
    return ReservationRepository()


class TestCreateAndRead:
    def test_a_hold_is_stored_and_read_back(self, repo):
        repo.create_atomically(make("res-a", 3), eligible_units=10)
        found = repo.get("fac-race-1", GROUP, COMPONENT, "res-a")
        assert found is not None
        assert found.units == 3
        assert found.status is ReservationStatus.PENDING

    def test_pool_counter_tracks_held_units(self, repo):
        repo.create_atomically(make("res-b", 4), eligible_units=10)
        assert repo.held_units_for_pool("fac-race-1", GROUP, COMPONENT) == 4

    def test_listing_a_pool_uses_a_key_condition(self, repo):
        repo.create_atomically(make("res-c", 2, user="u1"), eligible_units=10)
        repo.create_atomically(make("res-d", 3, user="u2"), eligible_units=10)
        found = repo.list_for_pool("fac-race-1", GROUP, COMPONENT)
        assert {r.reservation_id for r in found} == {"res-c", "res-d"}
        assert held_units(found, NOW) == 5

    def test_a_different_component_is_a_different_pool(self, repo):
        repo.create_atomically(make("res-e", 2), eligible_units=10)
        other = repo.list_for_pool("fac-race-1", GROUP, Component.FFP)
        assert other == []

    def test_my_reservations_are_queryable_by_user(self, repo):
        repo.create_atomically(make("res-f", 1, user="mine"), eligible_units=10)
        repo.create_atomically(make("res-g", 1, user="theirs"), eligible_units=10)
        mine = repo.list_for_user("mine")
        assert [r.reservation_id for r in mine] == ["res-f"]


class TestOverselling:
    """The invariant the transaction exists to enforce."""

    def test_the_second_hold_on_the_last_units_is_refused(self, repo):
        """Two callers, five units, four each. Exactly one must win."""
        repo.create_atomically(make("res-first", 4, user="u1"), eligible_units=5)

        with pytest.raises(ConcurrentModificationError):
            # Both callers read "5 eligible" before either wrote. The condition
            # on the pool counter is what makes the second one lose.
            repo.create_atomically(make("res-second", 4, user="u2"), eligible_units=5)

        assert repo.held_units_for_pool("fac-race-1", GROUP, COMPONENT) == 4

    def test_holds_may_fill_the_stock_exactly(self, repo):
        repo.create_atomically(make("res-x", 3, user="u1"), eligible_units=5)
        repo.create_atomically(make("res-y", 2, user="u2"), eligible_units=5)
        assert repo.held_units_for_pool("fac-race-1", GROUP, COMPONENT) == 5

    def test_one_unit_beyond_the_stock_is_refused(self, repo):
        repo.create_atomically(make("res-p", 5, user="u1"), eligible_units=5)
        with pytest.raises(ConcurrentModificationError):
            repo.create_atomically(make("res-q", 1, user="u2"), eligible_units=5)

    def test_a_retried_request_cannot_create_two_holds(self, repo):
        """Idempotency: a double click or a client retry must not double-hold."""
        reservation = make("res-retry", 2)
        repo.create_atomically(reservation, eligible_units=10)
        with pytest.raises(DuplicateError):
            repo.create_atomically(reservation, eligible_units=10)
        assert repo.held_units_for_pool("fac-race-1", GROUP, COMPONENT) == 2


class TestRelease:
    def test_cancelling_releases_the_units(self, repo):
        reservation = make("res-cancel", 3)
        repo.create_atomically(reservation, eligible_units=10)
        updated = apply_transition(reservation, ReservationStatus.CANCELLED, now=NOW)
        repo.transition_atomically(reservation, updated, release_units=True)

        assert repo.held_units_for_pool("fac-race-1", GROUP, COMPONENT) == 0
        stored = repo.get("fac-race-1", GROUP, COMPONENT, "res-cancel")
        assert stored.status is ReservationStatus.CANCELLED

    def test_a_hold_cannot_be_released_twice(self, repo):
        """A double release would decrement the counter twice and invent stock."""
        reservation = make("res-twice", 3)
        repo.create_atomically(reservation, eligible_units=10)
        updated = apply_transition(reservation, ReservationStatus.CANCELLED, now=NOW)
        repo.transition_atomically(reservation, updated, release_units=True)

        with pytest.raises(ConcurrentModificationError):
            # Replaying the same transition: the status/version condition fails.
            repo.transition_atomically(reservation, updated, release_units=True)

        assert repo.held_units_for_pool("fac-race-1", GROUP, COMPONENT) == 0

    def test_released_units_can_be_reserved_again(self, repo):
        first = make("res-r1", 5, user="u1")
        repo.create_atomically(first, eligible_units=5)
        released = apply_transition(first, ReservationStatus.CANCELLED, now=NOW)
        repo.transition_atomically(first, released, release_units=True)

        # The units are genuinely free again, not merely marked so.
        repo.create_atomically(make("res-r2", 5, user="u2"), eligible_units=5)
        assert repo.held_units_for_pool("fac-race-1", GROUP, COMPONENT) == 5

    def test_fulfilling_does_not_return_units_to_the_pool(self, repo):
        """Issued units left the shelf; they must not become available again."""
        reservation = make("res-fulfil", 2)
        repo.create_atomically(reservation, eligible_units=10)
        confirmed = apply_transition(reservation, ReservationStatus.CONFIRMED, now=NOW)
        repo.transition_atomically(reservation, confirmed, release_units=False)
        fulfilled = apply_transition(confirmed, ReservationStatus.FULFILLED, now=NOW)
        repo.transition_atomically(confirmed, fulfilled, release_units=False)

        stored = repo.get("fac-race-1", GROUP, COMPONENT, "res-fulfil")
        assert stored.status is ReservationStatus.FULFILLED
        # Still counted against the pool: the stock is gone, not freed.
        assert repo.held_units_for_pool("fac-race-1", GROUP, COMPONENT) == 2

    def test_confirming_keeps_the_hold(self, repo):
        reservation = make("res-confirm", 3)
        repo.create_atomically(reservation, eligible_units=10)
        confirmed = apply_transition(
            reservation, ReservationStatus.CONFIRMED, now=NOW, actor_user_id="staff"
        )
        repo.transition_atomically(reservation, confirmed, release_units=False)
        assert repo.held_units_for_pool("fac-race-1", GROUP, COMPONENT) == 3


class TestExpirySweepQuery:
    def test_due_for_expiry_finds_a_lapsed_hold(self, repo):
        repo.create_atomically(make("res-old", 2, minutes=30), eligible_units=10)
        later = NOW + timedelta(hours=2)
        due = repo.due_for_expiry(later)
        assert "res-old" in {r.reservation_id for r in due}

    def test_due_for_expiry_ignores_a_live_hold(self, repo):
        repo.create_atomically(make("res-live", 2, minutes=600), eligible_units=10)
        due = repo.due_for_expiry(NOW + timedelta(minutes=5))
        assert "res-live" not in {r.reservation_id for r in due}

    def test_a_released_hold_leaves_the_sweep_index(self, repo):
        reservation = make("res-gone", 2, minutes=30)
        repo.create_atomically(reservation, eligible_units=10)
        updated = apply_transition(reservation, ReservationStatus.EXPIRED, now=NOW)
        repo.transition_atomically(reservation, updated, release_units=True)

        # GSI2PK moves with the status, so the sweep stops seeing it.
        due = repo.due_for_expiry(NOW + timedelta(hours=2))
        assert "res-gone" not in {r.reservation_id for r in due}


class _AuditStub:
    """Records nothing; the audit trail is covered elsewhere."""

    def __init__(self):
        self.events = []

    def record(self, **kwargs):
        self.events.append(kwargs)


class TestServiceDecidesWhenUnitsAreReleased:
    """The service's own choice of ``release_units``, which nothing covered.

    Every test above calls ``transition_atomically`` directly and passes
    ``release_units`` by hand, so the repository is well covered and the
    *service's decision* was not covered at all. That gap hid a live defect.

    The service computed::

        releases = reservation.status in HOLDING_STATES

    which is true for a PENDING hold being CONFIRMED -- so confirming a
    reservation decremented the held-units counter even though a CONFIRMED
    hold still holds its units. Two consequences, both user-visible:

    * the units silently returned to availability while the requester still
      saw the hold as live, which is overselling; and
    * the counter then underflowed, so the hold could afterwards be neither
      cancelled nor fulfilled -- both paths refused with
      CONCURRENT_MODIFICATION and the reservation was stuck until expiry.

    Found by verifying the deployed API, not by the suite.
    """

    def _service(self, repo):
        from services.reservation_service import ReservationService

        return ReservationService(
            reservation_repository=repo,
            inventory_repository=None,
            facility_repository=None,
            audit_repository=_AuditStub(),
            id_factory=lambda: "unused",
        )

    def test_confirming_a_hold_does_not_release_its_units(self, repo):
        reservation = make("res-svc-confirm", 2)
        repo.create_atomically(reservation, eligible_units=10)
        assert repo.held_units_for_pool("fac-race-1", GROUP, COMPONENT) == 2

        self._service(repo).decide(
            facility_id="fac-race-1",
            blood_group=GROUP,
            component=COMPONENT,
            reservation_id="res-svc-confirm",
            approve=True,
            reason=None,
            actor_user_id="staff-1",
            actor_organization_id="org-1",
            now=NOW,
        )

        # A CONFIRMED hold still holds. The counter must be untouched.
        assert repo.held_units_for_pool("fac-race-1", GROUP, COMPONENT) == 2

    def test_a_confirmed_hold_can_still_be_cancelled(self, repo):
        """The symptom that surfaced live: a confirmed hold was stuck."""
        reservation = make("res-svc-cancel", 2)
        repo.create_atomically(reservation, eligible_units=10)
        service = self._service(repo)

        service.decide(
            facility_id="fac-race-1", blood_group=GROUP, component=COMPONENT,
            reservation_id="res-svc-cancel", approve=True, reason=None,
            actor_user_id="staff-1", actor_organization_id="org-1", now=NOW,
        )
        result = service.cancel(
            facility_id="fac-race-1", blood_group=GROUP, component=COMPONENT,
            reservation_id="res-svc-cancel", actor_user_id="user-1", now=NOW,
        )

        assert result["status"] == ReservationStatus.CANCELLED.value
        assert repo.held_units_for_pool("fac-race-1", GROUP, COMPONENT) == 0

    def test_a_confirmed_hold_can_still_be_fulfilled(self, repo):
        reservation = make("res-svc-fulfil", 2)
        repo.create_atomically(reservation, eligible_units=10)
        service = self._service(repo)

        service.decide(
            facility_id="fac-race-1", blood_group=GROUP, component=COMPONENT,
            reservation_id="res-svc-fulfil", approve=True, reason=None,
            actor_user_id="staff-1", actor_organization_id="org-1", now=NOW,
        )
        result = service.fulfil(
            facility_id="fac-race-1", blood_group=GROUP, component=COMPONENT,
            reservation_id="res-svc-fulfil",
            actor_user_id="staff-1", actor_organization_id="org-1", now=NOW,
        )

        assert result["status"] == ReservationStatus.FULFILLED.value
        # Fulfilled units left the shelf, so they are no longer *held*.
        assert repo.held_units_for_pool("fac-race-1", GROUP, COMPONENT) == 0

    def test_rejecting_a_pending_hold_releases_its_units(self, repo):
        reservation = make("res-svc-reject", 3)
        repo.create_atomically(reservation, eligible_units=10)

        self._service(repo).decide(
            facility_id="fac-race-1", blood_group=GROUP, component=COMPONENT,
            reservation_id="res-svc-reject", approve=False, reason="quarantined",
            actor_user_id="staff-1", actor_organization_id="org-1", now=NOW,
        )

        assert repo.held_units_for_pool("fac-race-1", GROUP, COMPONENT) == 0

    def test_cancelling_a_pending_hold_releases_its_units(self, repo):
        reservation = make("res-svc-cancel-pending", 3)
        repo.create_atomically(reservation, eligible_units=10)

        self._service(repo).cancel(
            facility_id="fac-race-1", blood_group=GROUP, component=COMPONENT,
            reservation_id="res-svc-cancel-pending",
            actor_user_id="user-1", now=NOW,
        )

        assert repo.held_units_for_pool("fac-race-1", GROUP, COMPONENT) == 0

    def test_confirming_then_cancelling_frees_the_units_for_someone_else(self, repo):
        """The end-to-end consequence, which is what a user would notice."""
        first = make("res-svc-a", 10, user="user-1")
        repo.create_atomically(first, eligible_units=10)
        service = self._service(repo)

        service.decide(
            facility_id="fac-race-1", blood_group=GROUP, component=COMPONENT,
            reservation_id="res-svc-a", approve=True, reason=None,
            actor_user_id="staff-1", actor_organization_id="org-1", now=NOW,
        )

        # While confirmed, the whole stock is held: nobody else may take it.
        import pytest as _pytest

        with _pytest.raises(ConcurrentModificationError):
            repo.create_atomically(
                make("res-svc-b", 1, user="user-2"), eligible_units=10
            )

        service.cancel(
            facility_id="fac-race-1", blood_group=GROUP, component=COMPONENT,
            reservation_id="res-svc-a", actor_user_id="user-1", now=NOW,
        )

        # Released, so the next caller succeeds.
        repo.create_atomically(make("res-svc-b", 1, user="user-2"), eligible_units=10)
        assert repo.held_units_for_pool("fac-race-1", GROUP, COMPONENT) == 1
