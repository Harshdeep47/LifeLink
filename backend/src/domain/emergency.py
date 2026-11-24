"""Emergency request lifecycle, priority and scheduling (spec Part 6).

This is a coordination system, not a clinical decision system. Two separations
carry that intent into the code:

* ``clinical_priority`` is hospital-certified and may only be set by an authorized
  actor through the certification path. No scheduler, heuristic or model touches it.
* ``effective_priority`` exists purely for dispatch ordering and may be recomputed
  freely. The spec requires that fairness mechanisms never alter clinical priority.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .errors import InvalidStateTransitionError, ValidationError


class ClinicalPriority(StrEnum):
    """Hospital-facing names map explicitly onto internal levels (spec 6.4)."""

    P1 = "P1"  # Critical
    P2 = "P2"  # Urgent
    P3 = "P3"  # Scheduled


PRIORITY_LABELS: dict[ClinicalPriority, str] = {
    ClinicalPriority.P1: "Critical",
    ClinicalPriority.P2: "Urgent",
    ClinicalPriority.P3: "Scheduled",
}

LABEL_TO_PRIORITY: dict[str, ClinicalPriority] = {
    "CRITICAL": ClinicalPriority.P1,
    "URGENT": ClinicalPriority.P2,
    "SCHEDULED": ClinicalPriority.P3,
}


def parse_priority_label(label: str) -> ClinicalPriority:
    """Accept either the hospital-facing word or the internal code."""
    key = label.strip().upper()
    if key in LABEL_TO_PRIORITY:
        return LABEL_TO_PRIORITY[key]
    try:
        return ClinicalPriority(key)
    except ValueError:
        raise ValidationError(
            f"unknown priority '{label}'",
            details={"allowed": sorted(LABEL_TO_PRIORITY) + [p.value for p in ClinicalPriority]},
        ) from None


class HospitalVerificationState(StrEnum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"


class RequestStatus(StrEnum):
    REQUEST_CREATED = "REQUEST_CREATED"
    VERIFICATION_PENDING = "VERIFICATION_PENDING"
    HOSPITAL_CERTIFIED = "HOSPITAL_CERTIFIED"
    MATCHING_INITIATED = "MATCHING_INITIATED"
    PROVIDERS_NOTIFIED = "PROVIDERS_NOTIFIED"
    RESPONSES_RECEIVED = "RESPONSES_RECEIVED"
    AVAILABILITY_CONFIRMED = "AVAILABILITY_CONFIRMED"
    RESOLVED = "RESOLVED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class ProviderResponseType(StrEnum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    INSUFFICIENT_STOCK = "INSUFFICIENT_STOCK"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"


TERMINAL_STATUSES: frozenset[RequestStatus] = frozenset(
    {RequestStatus.RESOLVED, RequestStatus.CANCELLED, RequestStatus.EXPIRED}
)

# Explicit transition table. The spec requires valid transitions to be defined and
# everything else rejected -- so this is data, not scattered conditionals.
VALID_TRANSITIONS: dict[RequestStatus, frozenset[RequestStatus]] = {
    RequestStatus.REQUEST_CREATED: frozenset(
        {RequestStatus.VERIFICATION_PENDING, RequestStatus.CANCELLED, RequestStatus.EXPIRED}
    ),
    RequestStatus.VERIFICATION_PENDING: frozenset(
        {RequestStatus.HOSPITAL_CERTIFIED, RequestStatus.CANCELLED, RequestStatus.EXPIRED}
    ),
    RequestStatus.HOSPITAL_CERTIFIED: frozenset(
        {RequestStatus.MATCHING_INITIATED, RequestStatus.CANCELLED, RequestStatus.EXPIRED}
    ),
    RequestStatus.MATCHING_INITIATED: frozenset(
        {RequestStatus.PROVIDERS_NOTIFIED, RequestStatus.CANCELLED, RequestStatus.EXPIRED}
    ),
    RequestStatus.PROVIDERS_NOTIFIED: frozenset(
        {RequestStatus.RESPONSES_RECEIVED, RequestStatus.CANCELLED, RequestStatus.EXPIRED}
    ),
    RequestStatus.RESPONSES_RECEIVED: frozenset(
        {
            RequestStatus.AVAILABILITY_CONFIRMED,
            RequestStatus.MATCHING_INITIATED,  # re-match when every provider declined
            RequestStatus.CANCELLED,
            RequestStatus.EXPIRED,
        }
    ),
    RequestStatus.AVAILABILITY_CONFIRMED: frozenset(
        {RequestStatus.RESOLVED, RequestStatus.CANCELLED, RequestStatus.EXPIRED}
    ),
    RequestStatus.RESOLVED: frozenset(),
    RequestStatus.CANCELLED: frozenset(),
    RequestStatus.EXPIRED: frozenset(),
}


def can_transition(current: RequestStatus, target: RequestStatus) -> bool:
    return target in VALID_TRANSITIONS[current]


def assert_transition(current: RequestStatus, target: RequestStatus) -> None:
    """Raise unless the transition is permitted. Called by every state change."""
    if not can_transition(current, target):
        raise InvalidStateTransitionError(
            f"cannot move request from {current.value} to {target.value}",
            details={
                "from": current.value,
                "to": target.value,
                "allowed": sorted(s.value for s in VALID_TRANSITIONS[current]),
            },
        )


# --- Priority scheduling (ADR-0006) ------------------------------------------

AGING_INTERVAL_MINUTES = 15
DEADLINE_URGENCY_MINUTES = 30

PRIORITY_ORDER: dict[ClinicalPriority, int] = {
    ClinicalPriority.P1: 0,
    ClinicalPriority.P2: 1,
    ClinicalPriority.P3: 2,
}
ORDER_TO_PRIORITY: dict[int, ClinicalPriority] = {v: k for k, v in PRIORITY_ORDER.items()}


def compute_effective_priority(
    *,
    clinical_priority: ClinicalPriority,
    created_at: datetime,
    required_by: datetime | None,
    now: datetime,
    aging_interval_minutes: int = AGING_INTERVAL_MINUTES,
) -> ClinicalPriority:
    """Scheduling priority only -- never written back onto ``clinical_priority``.

    Two documented fairness mechanisms:
      * Aging: one band per aging interval spent waiting, so P3 cannot starve.
      * Deadline urgency: a request due within 30 minutes sorts as P1.
    """
    base = PRIORITY_ORDER[clinical_priority]

    waited_minutes = max(0.0, (now - created_at).total_seconds() / 60.0)
    bands_gained = int(waited_minutes // aging_interval_minutes)
    effective = max(0, base - bands_gained)

    if required_by is not None:
        minutes_left = (required_by - now).total_seconds() / 60.0
        if 0 < minutes_left <= DEADLINE_URGENCY_MINUTES:
            effective = 0

    return ORDER_TO_PRIORITY[effective]


def dispatch_sort_key(
    *, effective_priority: ClinicalPriority, created_at: datetime
) -> tuple[int, datetime]:
    """Dispatch ordering: higher priority first, FIFO within a band."""
    return (PRIORITY_ORDER[effective_priority], created_at)


def is_expired(required_by: datetime | None, now: datetime) -> bool:
    return required_by is not None and required_by <= now


@dataclass(frozen=True, slots=True)
class ResponseTally:
    """Aggregate of provider responses.

    ``units_offered`` is the sum of what providers said they are *willing to
    provide*. It is explicitly NOT a reservation and never decrements inventory
    (ADR-0017), which is what makes double-counting structurally impossible.
    """

    accepted: int = 0
    rejected: int = 0
    insufficient: int = 0
    clarification: int = 0
    units_offered: int = 0

    @property
    def total(self) -> int:
        return self.accepted + self.rejected + self.insufficient + self.clarification


def tally_responses(responses: list[dict]) -> ResponseTally:
    """Summarise responses without mutating or reserving any stock."""
    accepted = rejected = insufficient = clarification = units = 0
    for r in responses:
        kind = ProviderResponseType(r["responseType"])
        if kind == ProviderResponseType.ACCEPTED:
            accepted += 1
            units += int(r.get("unitsOffered") or 0)
        elif kind == ProviderResponseType.REJECTED:
            rejected += 1
        elif kind == ProviderResponseType.INSUFFICIENT_STOCK:
            insufficient += 1
            # Partial offers still count toward what is on the table.
            units += int(r.get("unitsOffered") or 0)
        else:
            clarification += 1
    return ResponseTally(accepted, rejected, insufficient, clarification, units)
