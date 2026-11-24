"""Temporary reservation workflow.

Orchestrates the hold lifecycle: validate against live inventory, write
atomically, release on cancel/reject/expiry, and audit every transition.

The ordering here is deliberate and worth stating, because getting it backwards
is the classic way to oversell stock:

1.  Read live eligible inventory.
2.  Read existing holds for the same pool.
3.  Ask the domain whether a hold is permissible (advisory).
4.  Attempt the atomic write, which re-checks the arithmetic as a condition.

Step 3 can say yes to two callers at once. Only step 4 decides. The service
never treats step 3 as permission to write without the condition in step 4.
"""

from __future__ import annotations

from datetime import datetime

from domain.blood import BloodGroup, Component
from domain.clock import to_iso
from domain.errors import (
    ConcurrentModificationError,
    ForbiddenError,
    LifeLinkError,
    NotFoundError,
    ValidationError,
)
from domain.inventory import summarise_availability
from domain.reservations import (
    HOLDING_STATES,
    Reservation,
    ReservationError,
    ReservationStatus,
    apply_transition,
    available_after_holds,
    due_for_expiry,
    effective_status,
    held_units,
    validate_request,
)

#: Reservation requests are never a clinical statement. Returned with every
#: reservation so a client cannot present a hold as medical clearance.
RESERVATION_NOTICE = (
    "A reservation holds units for a limited time. It is not clinical approval, "
    "not a cross-match, and not a guarantee of release. Compatibility and "
    "release remain decisions for qualified staff at the facility."
)


class ReservationService:
    def __init__(
        self,
        *,
        reservation_repository,
        inventory_repository,
        facility_repository,
        audit_repository,
        id_factory,
    ):
        self._reservations = reservation_repository
        self._inventory = inventory_repository
        self._facilities = facility_repository
        self._audit = audit_repository
        self._new_id = id_factory

    # --- helpers ---

    def _eligible_units(
        self,
        facility: dict,
        blood_group: BloodGroup,
        component: Component,
        *,
        now: datetime,
    ) -> int | None:
        """Live eligible units, or None when the facility has never reported.

        Returns None rather than 0 for an unreported facility, matching
        ``summarise_availability``. A reservation against an unknown quantity
        is refused downstream; inventing a number here would be the same
        defect as reporting zero for an unreported facility.
        """
        inventory_known = bool(facility.get("inventoryKnown"))
        if not inventory_known:
            return None
        batches = self._inventory.list_eligible_batches(
            facility["facilityId"], blood_group, component, now=now
        )
        summary = summarise_availability(
            batches=batches,
            blood_group=blood_group,
            component=component,
            requested_units=0,
            now=now,
            inventory_known=True,
        )
        return summary.eligible_units

    def _serialise(self, reservation: Reservation, *, now: datetime) -> dict:
        effective = effective_status(reservation, now)
        return {
            "reservationId": reservation.reservation_id,
            "facilityId": reservation.facility_id,
            "bloodGroup": reservation.blood_group.value,
            "component": reservation.component.value,
            "units": reservation.units,
            # Stored status and the status a reader should act on. They differ
            # when a hold has expired but no sweep has rewritten the row yet,
            # and hiding that difference would make an expired hold look live.
            "status": effective.value,
            "storedStatus": reservation.status.value,
            "holdsUnits": effective in HOLDING_STATES,
            "createdAt": to_iso(reservation.created_at),
            "expiresAt": to_iso(reservation.expires_at),
            "releasedAt": to_iso(reservation.released_at),
            "decisionReason": reservation.decision_reason,
            "isReservation": True,
            "isClinicalApproval": False,
            "notice": RESERVATION_NOTICE,
        }

    # --- public availability integration ---

    def reserved_units(
        self, facility_id: str, blood_group: BloodGroup, component: Component,
        *, now: datetime,
    ) -> int:
        """Units currently held at a facility for one group and component."""
        existing = self._reservations.list_for_pool(facility_id, blood_group, component)
        return held_units(existing, now)

    def adjust_availability(
        self,
        facility_id: str,
        blood_group: BloodGroup,
        component: Component,
        eligible_units: int | None,
        *,
        now: datetime,
    ) -> tuple[int | None, int]:
        """Return (units free after holds, units held).

        Used by the discovery and availability paths so a reserved unit stops
        being offered to the next searcher.
        """
        existing = self._reservations.list_for_pool(facility_id, blood_group, component)
        return available_after_holds(eligible_units, existing, now), held_units(existing, now)

    # --- lifecycle ---

    def request_reservation(
        self,
        *,
        facility_id: str,
        blood_group: BloodGroup,
        component: Component,
        units: int,
        requester_user_id: str,
        hold_minutes: int | None,
        now: datetime,
        correlation_id: str | None = None,
    ) -> dict:
        facility = self._facilities.get_facility(facility_id)
        if facility is None:
            raise NotFoundError("no such facility")

        eligible = self._eligible_units(facility, blood_group, component, now=now)
        existing = self._reservations.list_for_pool(facility_id, blood_group, component)

        decision = validate_request(
            units=units,
            eligible_units=eligible,
            existing=existing,
            requester_user_id=requester_user_id,
            now=now,
            hold_minutes=hold_minutes,
        )
        if not decision.allowed:
            # Reason codes are contract; the message is for a human.
            messages = {
                "UNITS_MUST_BE_POSITIVE": "units must be greater than zero",
                "UNITS_EXCEED_PER_REQUEST_LIMIT":
                    "a single reservation cannot exceed 10 units",
                "INVENTORY_NOT_REPORTED":
                    "this facility has not reported inventory, so units cannot be held",
                "NO_UNRESERVED_STOCK": "no unreserved units are available",
                "INSUFFICIENT_UNRESERVED_STOCK":
                    f"only {decision.units_granted} unreserved unit(s) are available",
                "ALREADY_HOLDING":
                    "you already hold a reservation for this group and component here",
            }
            raise ValidationError(
                messages.get(decision.reason_code, "reservation refused"),
                details={
                    "rule": decision.reason_code,
                    "unreservedUnits": decision.units_granted,
                },
            )

        reservation = Reservation(
            reservation_id=self._new_id(),
            facility_id=facility_id,
            organization_id=facility.get("organizationId", ""),
            requester_user_id=requester_user_id,
            blood_group=blood_group,
            component=component,
            units=units,
            status=ReservationStatus.PENDING,
            created_at=now,
            expires_at=decision.expires_at,
            version=1,
        )

        try:
            self._reservations.create_atomically(reservation, eligible_units=eligible)
        except ConcurrentModificationError:
            # The condition on the pool counter refused: someone else took the
            # units between our read and our write. This is the race the
            # transaction exists to lose safely.
            raise ValidationError(
                "those units were reserved by someone else a moment ago; "
                "please search again",
                details={"rule": "RESERVATION_RACE_LOST"},
            ) from None

        self._audit_event(
            "RESERVATION_REQUESTED", reservation, requester_user_id, now, correlation_id
        )
        return self._serialise(reservation, now=now)

    def _load(
        self, facility_id: str, blood_group: BloodGroup, component: Component,
        reservation_id: str,
    ) -> Reservation:
        found = self._reservations.get(
            facility_id, blood_group, component, reservation_id
        )
        if found is None:
            raise NotFoundError("no such reservation")
        return found

    def _transition(
        self,
        reservation: Reservation,
        target: ReservationStatus,
        *,
        actor_user_id: str,
        reason: str | None,
        now: datetime,
        correlation_id: str | None,
        event: str,
    ) -> dict:
        # An expired hold must not be confirmed. Checked against effective
        # status so an unprocessed expiry cannot be acted on as if live.
        if effective_status(reservation, now) is ReservationStatus.EXPIRED and (
            target is ReservationStatus.CONFIRMED
        ):
            raise ValidationError(
                "this reservation has expired",
                details={"rule": "RESERVATION_EXPIRED"},
            )
        try:
            updated = apply_transition(
                reservation, target, now=now, actor_user_id=actor_user_id, reason=reason
            )
        except ReservationError as exc:
            raise ValidationError(str(exc), details={"rule": exc.reason_code}) from None

        # Units are released when the hold *stops* holding them -- that is,
        # when it leaves the holding states. Not merely when it was holding
        # them before.
        #
        # This previously read `releases = reservation.status in HOLDING_STATES`,
        # which is true for a PENDING hold being CONFIRMED. So confirming a
        # reservation decremented the pool counter while the reservation went
        # on reporting that it held its units. Two consequences, both
        # user-visible and both found against the deployed API rather than
        # here:
        #
        #   * the units silently returned to availability and another caller
        #     could reserve them, while the first requester still saw a live
        #     hold -- overselling, which is the one thing the pool counter
        #     exists to prevent; and
        #   * the counter then underflowed, so the confirmed hold could
        #     afterwards be neither cancelled nor fulfilled. Both paths hit
        #     the `heldUnits >= :units` condition and refused with
        #     CONCURRENT_MODIFICATION, leaving the reservation stuck.
        #
        # The repository was right all along and its tests pass
        # `release_units` by hand, which is exactly why nothing caught this:
        # the service's own decision had no test. It has one now.
        releases = (
            reservation.status in HOLDING_STATES
            and updated.status not in HOLDING_STATES
        )
        try:
            self._reservations.transition_atomically(
                reservation, updated, release_units=releases
            )
        except ConcurrentModificationError:
            raise ValidationError(
                "this reservation changed while your request was in flight; "
                "please reload",
                details={"rule": "CONCURRENT_MODIFICATION"},
            ) from None

        self._audit_event(event, updated, actor_user_id, now, correlation_id)
        return self._serialise(updated, now=now)

    def cancel(self, *, facility_id, blood_group, component, reservation_id,
               actor_user_id, now, correlation_id=None) -> dict:
        reservation = self._load(facility_id, blood_group, component, reservation_id)
        if reservation.requester_user_id != actor_user_id:
            # Only the requester cancels. A facility declines instead, which is
            # a different event and a different audit record.
            raise ForbiddenError("only the requester can cancel a reservation")
        return self._transition(
            reservation, ReservationStatus.CANCELLED,
            actor_user_id=actor_user_id, reason="cancelled by requester",
            now=now, correlation_id=correlation_id, event="RESERVATION_CANCELLED",
        )

    def decide(self, *, facility_id, blood_group, component, reservation_id,
               approve: bool, reason, actor_user_id, actor_organization_id,
               now, correlation_id=None) -> dict:
        reservation = self._load(facility_id, blood_group, component, reservation_id)
        if reservation.organization_id and actor_organization_id != reservation.organization_id:
            raise ForbiddenError("this reservation belongs to another organization")
        target = ReservationStatus.CONFIRMED if approve else ReservationStatus.REJECTED
        return self._transition(
            reservation, target,
            actor_user_id=actor_user_id, reason=reason, now=now,
            correlation_id=correlation_id,
            event="RESERVATION_CONFIRMED" if approve else "RESERVATION_REJECTED",
        )

    def fulfil(self, *, facility_id, blood_group, component, reservation_id,
               actor_user_id, actor_organization_id, now, correlation_id=None) -> dict:
        reservation = self._load(facility_id, blood_group, component, reservation_id)
        if reservation.organization_id and actor_organization_id != reservation.organization_id:
            raise ForbiddenError("this reservation belongs to another organization")
        # FULFILLED consumes the hold: the units left the shelf, so they are
        # not returned to availability. release_units stays False for this
        # transition by way of apply_transition's handling.
        return self._transition(
            reservation, ReservationStatus.FULFILLED,
            actor_user_id=actor_user_id, reason="units issued",
            now=now, correlation_id=correlation_id, event="RESERVATION_FULFILLED",
        )

    def list_mine(self, user_id: str, *, now: datetime) -> list[dict]:
        return [
            self._serialise(r, now=now)
            for r in self._reservations.list_for_user(user_id)
        ]

    def list_for_facility(self, facility_id: str, *, now: datetime) -> list[dict]:
        return [
            self._serialise(r, now=now)
            for r in self._reservations.list_for_facility(facility_id)
        ]

    # --- expiry ---

    def expire_due(self, *, now: datetime, correlation_id: str | None = None) -> dict:
        """Release holds whose time has passed.

        Driven by the maintenance schedule rather than DynamoDB TTL. TTL
        deletes items on a best-effort basis within roughly 48 hours, which
        would leave units held long after the hold ended -- a correctness
        problem, not a tidiness one.

        Each release is independent: one failure must not stop the rest, or a
        single stuck row would hold every later reservation's units hostage.
        """
        candidates = self._reservations.due_for_expiry(now)
        released = 0
        failures = 0
        for reservation in due_for_expiry(candidates, now):
            try:
                updated = apply_transition(
                    reservation, ReservationStatus.EXPIRED, now=now,
                    reason="hold expired",
                )
                self._reservations.transition_atomically(
                    reservation, updated, release_units=True
                )
                self._audit_event(
                    "RESERVATION_EXPIRED", updated, "system", now, correlation_id
                )
                released += 1
            except (LifeLinkError, ReservationError):
                # Already released by a concurrent action, most likely.
                failures += 1
        return {"examined": len(candidates), "released": released, "failed": failures}

    # --- audit ---

    def _audit_event(
        self, event: str, reservation: Reservation, actor: str,
        now: datetime, correlation_id: str | None,
    ) -> None:
        self._audit.record(
            actor_id=actor,
            actor_role=None,
            action=event,
            resource_type="RESERVATION",
            resource_id=reservation.reservation_id,
            correlation_id=correlation_id or "",
            occurred_at=now,
            organization_id=reservation.organization_id or None,
            metadata={
                "facilityId": reservation.facility_id,
                "bloodGroup": reservation.blood_group.value,
                "component": reservation.component.value,
                "units": reservation.units,
                "status": reservation.status.value,
                "expiresAt": to_iso(reservation.expires_at),
            },
        )


__all__ = ["RESERVATION_NOTICE", "ReservationService"]
