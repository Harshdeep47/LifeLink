"""Blood donation camps: lifecycle, registration, attendance, donation verification.

The spec is insistent that four states stay distinct and are never conflated:

    registration  ->  attendance  ->  donation recorded  ->  donation verified

Registration does not mean attendance. Attendance does not prove a donation.
A donor may never verify their own donation. Each of those rules is enforced
here as a function that can be unit-tested in isolation.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .errors import (
    CapacityExceededError,
    ForbiddenError,
    InvalidStateTransitionError,
    ValidationError,
)


class CampStatus(StrEnum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    UPCOMING = "UPCOMING"
    ONGOING = "ONGOING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class RegistrationStatus(StrEnum):
    REGISTERED = "REGISTERED"
    CANCELLED_BY_USER = "CANCELLED_BY_USER"
    CHECKED_IN = "CHECKED_IN"
    NO_SHOW = "NO_SHOW"


class AttendanceStatus(StrEnum):
    NOT_ATTENDED = "NOT_ATTENDED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"


class DonationStatus(StrEnum):
    """Recorded and verified are deliberately separate states."""

    RECORDED = "RECORDED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


VALID_CAMP_TRANSITIONS: dict[CampStatus, frozenset[CampStatus]] = {
    CampStatus.PENDING_APPROVAL: frozenset(
        {CampStatus.UPCOMING, CampStatus.REJECTED, CampStatus.CANCELLED}
    ),
    CampStatus.UPCOMING: frozenset({CampStatus.ONGOING, CampStatus.CANCELLED}),
    CampStatus.ONGOING: frozenset({CampStatus.COMPLETED, CampStatus.CANCELLED}),
    CampStatus.COMPLETED: frozenset(),
    CampStatus.CANCELLED: frozenset(),
    CampStatus.REJECTED: frozenset(),
}


def assert_camp_transition(current: CampStatus, target: CampStatus) -> None:
    if target not in VALID_CAMP_TRANSITIONS[current]:
        raise InvalidStateTransitionError(
            f"cannot move camp from {current.value} to {target.value}",
            details={
                "from": current.value,
                "to": target.value,
                "allowed": sorted(s.value for s in VALID_CAMP_TRANSITIONS[current]),
            },
        )


def derive_camp_status(
    *, current: CampStatus, starts_at: datetime, ends_at: datetime, now: datetime
) -> CampStatus:
    """Time-driven status, used by the scheduled sweep.

    Only advances camps that are already approved. A cancelled or rejected camp
    is never resurrected by the passage of time.
    """
    if current in (CampStatus.CANCELLED, CampStatus.REJECTED, CampStatus.COMPLETED):
        return current
    if current == CampStatus.PENDING_APPROVAL:
        return current
    if now >= ends_at:
        return CampStatus.COMPLETED
    if now >= starts_at:
        return CampStatus.ONGOING
    return CampStatus.UPCOMING


@dataclass(frozen=True, slots=True)
class RegistrationCheck:
    allowed: bool
    reason: str | None = None


def can_register(
    *,
    camp_status: CampStatus,
    registration_deadline: datetime | None,
    starts_at: datetime,
    capacity: int,
    registered_count: int,
    already_registered: bool,
    now: datetime,
) -> RegistrationCheck:
    """Every precondition for registering, as one auditable decision.

    The capacity check here is advisory only -- it gives a clean error message.
    The authoritative guard against overbooking is the conditional transaction in
    the repository, because two simultaneous requests can both pass this check.
    """
    if already_registered:
        return RegistrationCheck(False, "ALREADY_REGISTERED")
    if camp_status == CampStatus.CANCELLED:
        return RegistrationCheck(False, "CAMP_CANCELLED")
    if camp_status == CampStatus.REJECTED:
        return RegistrationCheck(False, "CAMP_REJECTED")
    if camp_status == CampStatus.COMPLETED:
        return RegistrationCheck(False, "CAMP_COMPLETED")
    if camp_status == CampStatus.PENDING_APPROVAL:
        return RegistrationCheck(False, "CAMP_NOT_APPROVED")
    if registration_deadline is not None and now > registration_deadline:
        return RegistrationCheck(False, "REGISTRATION_CLOSED")
    if now >= starts_at and camp_status != CampStatus.ONGOING:
        return RegistrationCheck(False, "CAMP_ALREADY_STARTED")
    if registered_count >= capacity:
        return RegistrationCheck(False, "CAMP_FULL")
    return RegistrationCheck(True)


def assert_can_register(**kwargs) -> None:
    check = can_register(**kwargs)
    if not check.allowed:
        if check.reason == "CAMP_FULL":
            raise CapacityExceededError("this camp is full", details={"reason": check.reason})
        raise ValidationError(
            f"registration not permitted: {check.reason}", details={"reason": check.reason}
        )


def assert_can_verify_donation(
    *,
    verifier_id: str,
    donor_id: str,
    verifier_is_camp_staff: bool,
    donation_status: DonationStatus,
) -> None:
    """The spec's hardest rule in this feature: donors cannot verify themselves.

    Checked before the authorization decorator's role check is even relevant --
    being camp staff does not entitle someone to verify their own donation.
    """
    if verifier_id == donor_id:
        raise ForbiddenError(
            "a donor cannot verify their own donation",
            details={"rule": "SELF_VERIFICATION_FORBIDDEN"},
        )
    if not verifier_is_camp_staff:
        raise ForbiddenError(
            "only authorized camp staff may verify donations",
            details={"rule": "VERIFIER_NOT_CAMP_STAFF"},
        )
    if donation_status == DonationStatus.VERIFIED:
        raise InvalidStateTransitionError(
            "donation is already verified",
            details={"rule": "ALREADY_VERIFIED"},
        )


def should_send_reminder(
    *,
    camp_status: CampStatus,
    registration_status: RegistrationStatus,
    notifications_enabled: bool,
    consent_given: bool,
    already_sent: bool,
    scheduled_for: datetime,
    now: datetime,
    tolerance_minutes: int = 10,
) -> bool:
    """Re-checked immediately before each send, never trusted from scheduling time.

    The spec requires rechecking camp status, registration status, preferences,
    consent, prior sends and schedule validity -- all five are here, so a camp
    cancelled after the reminder was queued cannot produce a reminder.
    """
    if already_sent:
        return False
    if not notifications_enabled or not consent_given:
        return False
    if camp_status in (CampStatus.CANCELLED, CampStatus.REJECTED, CampStatus.COMPLETED):
        return False
    if registration_status != RegistrationStatus.REGISTERED:
        return False
    drift_minutes = abs((now - scheduled_for).total_seconds()) / 60.0
    return drift_minutes <= tolerance_minutes
