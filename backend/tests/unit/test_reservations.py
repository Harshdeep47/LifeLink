"""Temporary reservation rules.

The invariant every test here defends: **PENDING and CONFIRMED are the only
states that hold units.** Everything else follows from that.

Two rules get particular attention because breaking them would be invisible
rather than loud:

*   An expired-but-unprocessed hold must release its units *immediately* for
    availability purposes. If release waited for the sweep, units would appear
    held for up to a minute after their hold ended — and if the sweep ever
    stopped, forever.
*   Unknown eligible stock must stay unknown. Subtracting a hold from an
    unreported facility must not produce a number, or the "unknown is not zero"
    defect returns by a new route.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from domain.blood import BloodGroup, Component
from domain.reservations import (
    DEFAULT_HOLD_MINUTES,
    HOLDING_STATES,
    MAX_HOLD_MINUTES,
    MAX_UNITS_PER_RESERVATION,
    MIN_HOLD_MINUTES,
    TERMINAL_STATES,
    VALID_TRANSITIONS,
    Reservation,
    ReservationError,
    ReservationStatus,
    apply_transition,
    available_after_holds,
    clamp_hold_minutes,
    due_for_expiry,
    effective_status,
    held_units,
    is_expired,
    validate_request,
)

NOW = datetime(2026, 11, 15, 12, 0, 0, tzinfo=UTC)


def hold(
    units=2,
    status=ReservationStatus.PENDING,
    *,
    user="user-1",
    expires_in_minutes=120,
    reservation_id="res-1",
) -> Reservation:
    return Reservation(
        reservation_id=reservation_id,
        facility_id="fac-1",
        organization_id="org-1",
        requester_user_id=user,
        blood_group=BloodGroup.O_NEG,
        component=Component.PRBC,
        units=units,
        status=status,
        created_at=NOW,
        expires_at=NOW + timedelta(minutes=expires_in_minutes),
    )


class TestWhichStatesHoldUnits:
    def test_only_pending_and_confirmed_hold(self):
        assert {ReservationStatus.PENDING, ReservationStatus.CONFIRMED} == HOLDING_STATES

    @pytest.mark.parametrize(
        "status", [ReservationStatus.PENDING, ReservationStatus.CONFIRMED]
    )
    def test_holding_states_count(self, status):
        assert held_units([hold(3, status)], NOW) == 3

    @pytest.mark.parametrize("status", sorted(TERMINAL_STATES, key=lambda s: s.value))
    def test_terminal_states_do_not_count(self, status):
        assert held_units([hold(3, status)], NOW) == 0

    def test_fulfilled_does_not_return_units_to_availability(self):
        """FULFILLED consumes the hold: the units left the shelf."""
        assert held_units([hold(3, ReservationStatus.FULFILLED)], NOW) == 0

    def test_sums_across_several_holds(self):
        holds = [
            hold(2, reservation_id="a"),
            hold(3, ReservationStatus.CONFIRMED, reservation_id="b"),
            hold(5, ReservationStatus.CANCELLED, reservation_id="c"),
        ]
        assert held_units(holds, NOW) == 5


class TestExpiryIsImmediate:
    """Expiry must not wait for a sweep."""

    def test_expired_hold_releases_units_at_once(self):
        h = hold(4, expires_in_minutes=60)
        later = NOW + timedelta(minutes=61)
        assert h.status is ReservationStatus.PENDING, "stored status is unchanged"
        assert effective_status(h, later) is ReservationStatus.EXPIRED
        assert held_units([h], later) == 0

    def test_not_expired_before_its_time(self):
        h = hold(4, expires_in_minutes=60)
        assert held_units([h], NOW + timedelta(minutes=59)) == 4

    def test_expiry_boundary_is_inclusive(self):
        h = hold(expires_in_minutes=60)
        assert is_expired(h, NOW + timedelta(minutes=60)) is True

    def test_effective_status_leaves_terminal_states_alone(self):
        h = hold(status=ReservationStatus.CANCELLED, expires_in_minutes=-10)
        assert effective_status(h, NOW) is ReservationStatus.CANCELLED

    def test_due_for_expiry_finds_only_unprocessed_holds(self):
        live = hold(expires_in_minutes=120, reservation_id="live")
        stale = hold(expires_in_minutes=-5, reservation_id="stale")
        already = hold(
            status=ReservationStatus.EXPIRED, expires_in_minutes=-5, reservation_id="done"
        )
        due = due_for_expiry([live, stale, already], NOW)
        assert [r.reservation_id for r in due] == ["stale"]


class TestAvailabilityAfterHolds:
    def test_subtracts_held_units(self):
        assert available_after_holds(10, [hold(3)], NOW) == 7

    def test_never_negative(self):
        """A counter and the rows can disagree; the answer is still not negative."""
        assert available_after_holds(2, [hold(5)], NOW) == 0

    def test_unknown_stays_unknown(self):
        """The rule that matters most: unknown minus a hold is not a number."""
        assert available_after_holds(None, [hold(3)], NOW) is None

    def test_unknown_with_no_holds_stays_unknown(self):
        assert available_after_holds(None, [], NOW) is None

    def test_zero_eligible_is_still_zero(self):
        assert available_after_holds(0, [], NOW) == 0

    def test_expired_hold_does_not_reduce_availability(self):
        later = NOW + timedelta(hours=3)
        assert available_after_holds(10, [hold(4, expires_in_minutes=60)], later) == 10


class TestValidateRequest:
    def test_grants_a_hold_when_stock_is_free(self):
        decision = validate_request(
            units=3, eligible_units=10, existing=[], requester_user_id="u1", now=NOW
        )
        assert decision.allowed is True
        assert decision.units_granted == 3
        assert decision.expires_at == NOW + timedelta(minutes=DEFAULT_HOLD_MINUTES)

    def test_refuses_unreported_inventory(self):
        """Holding units a facility never reported would invent supply."""
        decision = validate_request(
            units=1, eligible_units=None, existing=[], requester_user_id="u1", now=NOW
        )
        assert decision.allowed is False
        assert decision.reason_code == "INVENTORY_NOT_REPORTED"

    def test_refuses_zero_and_negative_units(self):
        for units in (0, -1):
            decision = validate_request(
                units=units, eligible_units=10, existing=[],
                requester_user_id="u1", now=NOW,
            )
            assert decision.allowed is False
            assert decision.reason_code == "UNITS_MUST_BE_POSITIVE"

    def test_refuses_more_than_the_per_request_limit(self):
        decision = validate_request(
            units=MAX_UNITS_PER_RESERVATION + 1, eligible_units=100, existing=[],
            requester_user_id="u1", now=NOW,
        )
        assert decision.allowed is False
        assert decision.reason_code == "UNITS_EXCEED_PER_REQUEST_LIMIT"

    def test_refuses_when_all_stock_is_already_held(self):
        decision = validate_request(
            units=1, eligible_units=3,
            existing=[hold(3, user="other")], requester_user_id="u1", now=NOW,
        )
        assert decision.allowed is False
        assert decision.reason_code == "NO_UNRESERVED_STOCK"

    def test_refuses_partial_and_reports_what_is_free(self):
        """No silent partial hold: a user must not travel expecting more."""
        decision = validate_request(
            units=5, eligible_units=6,
            existing=[hold(4, user="other")], requester_user_id="u1", now=NOW,
        )
        assert decision.allowed is False
        assert decision.reason_code == "INSUFFICIENT_UNRESERVED_STOCK"
        assert decision.units_granted == 2, "tells the caller what it could have"

    def test_one_active_hold_per_person_per_pool(self):
        decision = validate_request(
            units=1, eligible_units=50,
            existing=[hold(1, user="u1")], requester_user_id="u1", now=NOW,
        )
        assert decision.allowed is False
        assert decision.reason_code == "ALREADY_HOLDING"

    def test_a_released_hold_does_not_block_a_new_one(self):
        decision = validate_request(
            units=1, eligible_units=50,
            existing=[hold(1, ReservationStatus.CANCELLED, user="u1")],
            requester_user_id="u1", now=NOW,
        )
        assert decision.allowed is True

    def test_an_expired_hold_does_not_block_a_new_one(self):
        later = NOW + timedelta(hours=5)
        decision = validate_request(
            units=1, eligible_units=50,
            existing=[hold(1, user="u1", expires_in_minutes=60)],
            requester_user_id="u1", now=later,
        )
        assert decision.allowed is True

    def test_another_persons_hold_does_not_trigger_already_holding(self):
        decision = validate_request(
            units=1, eligible_units=50,
            existing=[hold(1, user="someone-else")], requester_user_id="u1", now=NOW,
        )
        assert decision.allowed is True


class TestHoldDuration:
    def test_default_when_unspecified(self):
        assert clamp_hold_minutes(None) == DEFAULT_HOLD_MINUTES

    def test_clamped_up_from_too_short(self):
        assert clamp_hold_minutes(1) == MIN_HOLD_MINUTES

    def test_clamped_down_from_too_long(self):
        assert clamp_hold_minutes(10_000) == MAX_HOLD_MINUTES

    def test_a_reasonable_request_is_honoured(self):
        assert clamp_hold_minutes(90) == 90

    def test_bounds_are_sane(self):
        assert MIN_HOLD_MINUTES < DEFAULT_HOLD_MINUTES <= MAX_HOLD_MINUTES


class TestTransitions:
    def test_pending_can_be_confirmed(self):
        updated = apply_transition(
            hold(), ReservationStatus.CONFIRMED, now=NOW, actor_user_id="staff-1"
        )
        assert updated.status is ReservationStatus.CONFIRMED
        assert updated.decided_by_user_id == "staff-1"
        assert updated.version == 2

    def test_confirmed_can_be_fulfilled(self):
        confirmed = hold(status=ReservationStatus.CONFIRMED)
        updated = apply_transition(confirmed, ReservationStatus.FULFILLED, now=NOW)
        assert updated.status is ReservationStatus.FULFILLED

    def test_rejected_cannot_be_revived(self):
        rejected = hold(status=ReservationStatus.REJECTED)
        with pytest.raises(ReservationError) as excinfo:
            apply_transition(rejected, ReservationStatus.CONFIRMED, now=NOW)
        assert excinfo.value.reason_code == "INVALID_STATE_TRANSITION"

    def test_a_fulfilled_hold_is_final(self):
        done = hold(status=ReservationStatus.FULFILLED)
        for target in (ReservationStatus.CANCELLED, ReservationStatus.CONFIRMED):
            with pytest.raises(ReservationError):
                apply_transition(done, target, now=NOW)

    def test_pending_cannot_jump_to_fulfilled(self):
        """A facility must decide before it can issue."""
        with pytest.raises(ReservationError):
            apply_transition(hold(), ReservationStatus.FULFILLED, now=NOW)

    def test_a_no_op_is_refused_not_ignored(self):
        with pytest.raises(ReservationError) as excinfo:
            apply_transition(hold(), ReservationStatus.PENDING, now=NOW)
        assert excinfo.value.reason_code == "NO_OP_TRANSITION"

    def test_transition_does_not_mutate_the_input(self):
        original = hold()
        apply_transition(original, ReservationStatus.CANCELLED, now=NOW)
        assert original.status is ReservationStatus.PENDING
        assert original.version == 1

    def test_releasing_transitions_stamp_released_at(self):
        for target in (
            ReservationStatus.CANCELLED,
            ReservationStatus.REJECTED,
            ReservationStatus.EXPIRED,
        ):
            updated = apply_transition(hold(), target, now=NOW)
            assert updated.released_at == NOW, target

    def test_every_terminal_state_is_a_dead_end(self):
        for status in TERMINAL_STATES:
            assert VALID_TRANSITIONS[status] == frozenset(), status

    def test_transition_table_covers_every_status(self):
        assert set(VALID_TRANSITIONS) == set(ReservationStatus)


class TestReservationIsNotClinicalApproval:
    """The claim the feature must never make."""

    def test_a_reservation_carries_no_compatibility_assertion(self):
        h = hold()
        assert not hasattr(h, "compatible")
        assert not hasattr(h, "clinicallyApproved")
        assert not hasattr(h, "crossMatched")

    def test_the_service_notice_says_so(self):
        from services.reservation_service import RESERVATION_NOTICE

        lowered = RESERVATION_NOTICE.lower()
        assert "not clinical approval" in lowered
        assert "cross-match" in lowered
