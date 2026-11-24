"""Temporary blood reservations: a time-limited hold on specific units.

**This capability is additive, and it does not contradict the two rules it
sits beside.** The original specification states that an availability alert is
not a reservation (spec 374) and that a provider's ACCEPTED response "does not
guarantee stock reservation, fulfilment or transfusion" (spec 727). Both remain
true and are unchanged. Spec 733 — "revalidate stock before any later
confirmation or reservation workflow" — anticipated this workflow as later
work; this module is that work.

The distinction, because conflating them is the easiest mistake available here:

*   An **alert** says "tell me if this appears". It holds nothing.
*   A provider **response** to an emergency request says "we are willing". It
    holds nothing.
*   A **reservation** holds specific units at one facility for a bounded time,
    and those units stop counting as available to anyone else.

What a reservation still is not:

*   It is **not** clinical approval. Nothing here asserts that the units are
    compatible with, or safe for, any patient. Cross-matching and release are
    clinical acts performed by qualified staff outside this system.
*   It is **not** a guarantee of fulfilment. A facility may reject a request,
    and stock can be withdrawn or quarantined for reasons that outrank any
    hold.
*   It is **not** indefinite. Every reservation carries an explicit expiry, and
    an expired hold releases its units.

This module is pure: no I/O, no clock reads. Every function takes ``now``.
The atomicity that actually prevents overselling lives in
``repositories/reservation_repo.py``, because only the datastore can enforce
it; this module decides *what* should happen, never *whether the write won*.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum

from domain.blood import BloodGroup, Component
from domain.clock import ensure_aware

#: How long a hold lasts unless the caller asks for less.
DEFAULT_HOLD_MINUTES = 120

#: Upper bound on any hold. A reservation is a promise to other users that
#: units are unavailable; the longer it runs, the more supply it sterilises.
MAX_HOLD_MINUTES = 480

#: Below this, a hold is not useful to a human travelling to a facility.
MIN_HOLD_MINUTES = 15

#: A single request cannot hold more than this many units, so one caller
#: cannot sterilise a facility's entire stock of a group with one click.
MAX_UNITS_PER_RESERVATION = 10


class ReservationStatus(StrEnum):
    """Lifecycle states.

    PENDING    -- requested, units held, facility has not decided.
    CONFIRMED  -- facility accepted; units remain held until fulfilled.
    REJECTED   -- facility declined; units released.
    CANCELLED  -- requester withdrew; units released.
    EXPIRED    -- the hold ran out; units released.
    FULFILLED  -- units were issued; the hold is consumed, not released.

    PENDING and CONFIRMED are the only states that hold units. That single
    sentence is the invariant everything else in this module protects.
    """

    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    FULFILLED = "FULFILLED"


#: States in which units are still held and must be excluded from availability.
HOLDING_STATES = frozenset({ReservationStatus.PENDING, ReservationStatus.CONFIRMED})

#: States from which nothing further can happen.
TERMINAL_STATES = frozenset(
    {
        ReservationStatus.REJECTED,
        ReservationStatus.CANCELLED,
        ReservationStatus.EXPIRED,
        ReservationStatus.FULFILLED,
    }
)

#: Enumerated rather than inferred, so an illegal move is a refusal with a
#: reason instead of an unnoticed state change. Mirrors the approach in
#: domain/emergency.py and domain/camps.py.
VALID_TRANSITIONS: dict[ReservationStatus, frozenset[ReservationStatus]] = {
    ReservationStatus.PENDING: frozenset(
        {
            ReservationStatus.CONFIRMED,
            ReservationStatus.REJECTED,
            ReservationStatus.CANCELLED,
            ReservationStatus.EXPIRED,
        }
    ),
    ReservationStatus.CONFIRMED: frozenset(
        {
            ReservationStatus.FULFILLED,
            ReservationStatus.CANCELLED,
            ReservationStatus.EXPIRED,
        }
    ),
    ReservationStatus.REJECTED: frozenset(),
    ReservationStatus.CANCELLED: frozenset(),
    ReservationStatus.EXPIRED: frozenset(),
    ReservationStatus.FULFILLED: frozenset(),
}


@dataclass(frozen=True, slots=True)
class Reservation:
    reservation_id: str
    facility_id: str
    organization_id: str
    requester_user_id: str
    blood_group: BloodGroup
    component: Component
    units: int
    status: ReservationStatus
    created_at: datetime
    expires_at: datetime
    #: Set when the hold stops holding, whatever the reason.
    released_at: datetime | None = None
    decided_by_user_id: str | None = None
    decision_reason: str | None = None
    #: Optimistic concurrency, as elsewhere in the system.
    version: int = 1

    @property
    def holds_units(self) -> bool:
        return self.status in HOLDING_STATES


@dataclass(frozen=True, slots=True)
class ReservationDecision:
    """The decided outcome of a request, ready for a conditional write.

    Returning a decision rather than performing it keeps this module pure and
    lets the repository attach the conditions that make it atomic.
    """

    allowed: bool
    reason_code: str | None
    units_granted: int
    expires_at: datetime | None


class ReservationError(ValueError):
    """A reservation rule was broken. Carries a stable reason code."""

    def __init__(self, reason_code: str, message: str):
        super().__init__(message)
        self.reason_code = reason_code


def clamp_hold_minutes(requested: int | None) -> int:
    """Hold duration, bounded at both ends.

    Clamped rather than rejected: a caller asking for 10 hours wants a long
    hold, and the useful answer is the longest we allow, not an error.
    """
    if requested is None:
        return DEFAULT_HOLD_MINUTES
    return max(MIN_HOLD_MINUTES, min(int(requested), MAX_HOLD_MINUTES))


def is_expired(reservation: Reservation, now: datetime) -> bool:
    """Whether the hold has run out.

    Compared against stored expiry, never against a TTL attribute. DynamoDB
    TTL deletes items on a best-effort basis within roughly 48 hours, which is
    useless for releasing units promptly; it is a cleanup mechanism, not a
    scheduler. A reservation is expired the moment its expiry passes,
    regardless of whether anything has processed it yet.
    """
    return ensure_aware(now, "now") >= ensure_aware(reservation.expires_at, "expiresAt")


def effective_status(reservation: Reservation, now: datetime) -> ReservationStatus:
    """The status a reader should act on.

    A PENDING reservation whose expiry has passed is EXPIRED in substance even
    if no sweep has rewritten the row yet. Availability calculations and user
    displays must use this, not the stored value, or an unprocessed expiry
    keeps units held indefinitely.
    """
    if reservation.status in HOLDING_STATES and is_expired(reservation, now):
        return ReservationStatus.EXPIRED
    return reservation.status


def held_units(reservations: list[Reservation], now: datetime) -> int:
    """Units currently held across a set of reservations.

    Uses ``effective_status``, so an expired-but-unprocessed hold releases its
    units for availability purposes immediately. This is what makes the system
    correct between sweeps rather than only after one.
    """
    return sum(
        r.units
        for r in reservations
        if effective_status(r, now) in HOLDING_STATES
    )


def available_after_holds(
    eligible_units: int | None,
    reservations: list[Reservation],
    now: datetime,
) -> int | None:
    """Eligible units minus what is held, never below zero.

    ``None`` in, ``None`` out: an unreported facility has an unknown quantity,
    and subtracting a hold from an unknown does not produce a number. This is
    the same rule as ``summarise_availability`` — unknown is not zero — and
    getting it wrong here would reintroduce that defect by another route.
    """
    if eligible_units is None:
        return None
    return max(0, eligible_units - held_units(reservations, now))


def validate_request(
    *,
    units: int,
    eligible_units: int | None,
    existing: list[Reservation],
    requester_user_id: str,
    now: datetime,
    hold_minutes: int | None = None,
) -> ReservationDecision:
    """Decide whether a hold may be granted, and for how long.

    Fails closed at every uncertainty. In particular an unknown eligible
    quantity refuses: holding units a facility has never reported would invent
    supply, which is the most damaging thing this system could do.

    The returned decision is advisory. The repository re-checks the same
    arithmetic inside a conditional write, because between this call and that
    write another caller may have taken the units. Two callers can both be told
    "allowed" here; only one can win there.
    """
    if units <= 0:
        return ReservationDecision(False, "UNITS_MUST_BE_POSITIVE", 0, None)
    if units > MAX_UNITS_PER_RESERVATION:
        return ReservationDecision(False, "UNITS_EXCEED_PER_REQUEST_LIMIT", 0, None)

    if eligible_units is None:
        # Unknown is not zero -- and it is not "probably enough" either.
        return ReservationDecision(False, "INVENTORY_NOT_REPORTED", 0, None)

    free = available_after_holds(eligible_units, existing, now)
    if free is None or free <= 0:
        return ReservationDecision(False, "NO_UNRESERVED_STOCK", 0, None)
    if free < units:
        # Partial holds are not granted silently. The caller is told how many
        # are free and may ask again for that number; quietly reserving fewer
        # units than requested would let someone travel expecting more.
        return ReservationDecision(False, "INSUFFICIENT_UNRESERVED_STOCK", free, None)

    active_for_requester = [
        r for r in existing
        if r.requester_user_id == requester_user_id
        and effective_status(r, now) in HOLDING_STATES
    ]
    if active_for_requester:
        # One active hold per person per facility/group/component. Without
        # this, repeated clicking sterilises a facility's stock.
        return ReservationDecision(False, "ALREADY_HOLDING", 0, None)

    minutes = clamp_hold_minutes(hold_minutes)
    return ReservationDecision(
        allowed=True,
        reason_code=None,
        units_granted=units,
        expires_at=ensure_aware(now, "now") + timedelta(minutes=minutes),
    )


def apply_transition(
    reservation: Reservation,
    target: ReservationStatus,
    *,
    now: datetime,
    actor_user_id: str | None = None,
    reason: str | None = None,
) -> Reservation:
    """Return the reservation in its new state, or raise.

    Pure: returns a new value and never mutates the input, so a rejected
    transition cannot leave a half-changed object behind.
    """
    current = reservation.status
    if target == current:
        raise ReservationError(
            "NO_OP_TRANSITION", f"reservation is already {current.value}"
        )
    allowed = VALID_TRANSITIONS.get(current, frozenset())
    if target not in allowed:
        raise ReservationError(
            "INVALID_STATE_TRANSITION",
            f"cannot move a reservation from {current.value} to {target.value}",
        )

    moment = ensure_aware(now, "now")
    releases = target in TERMINAL_STATES and target != ReservationStatus.FULFILLED
    return replace(
        reservation,
        status=target,
        # FULFILLED consumes the hold rather than releasing it: the units left
        # the shelf, so they must not return to availability.
        released_at=moment if releases or target == ReservationStatus.FULFILLED else None,
        decided_by_user_id=actor_user_id or reservation.decided_by_user_id,
        decision_reason=reason if reason is not None else reservation.decision_reason,
        version=reservation.version + 1,
    )


def due_for_expiry(reservations: list[Reservation], now: datetime) -> list[Reservation]:
    """Holds whose stored status still holds units but whose time has passed.

    Used by the maintenance sweep. Expiry is processed actively rather than
    left to DynamoDB TTL, which is best-effort within ~48 hours and would keep
    units held long after the hold ended.
    """
    return [
        r
        for r in reservations
        if r.status in HOLDING_STATES and is_expired(r, now)
    ]


__all__ = [
    "DEFAULT_HOLD_MINUTES",
    "HOLDING_STATES",
    "MAX_HOLD_MINUTES",
    "MAX_UNITS_PER_RESERVATION",
    "MIN_HOLD_MINUTES",
    "Reservation",
    "ReservationDecision",
    "ReservationError",
    "ReservationStatus",
    "TERMINAL_STATES",
    "VALID_TRANSITIONS",
    "apply_transition",
    "available_after_holds",
    "clamp_hold_minutes",
    "due_for_expiry",
    "effective_status",
    "held_units",
    "is_expired",
    "validate_request",
]
