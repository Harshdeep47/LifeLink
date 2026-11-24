"""Donation impact ledger and recognition milestones (spec 5.6).

Design constraints taken directly from the spec:

* Points are awarded only for *verified* donations, never for registration or
  attendance.
* Credit must be granted exactly once -- enforced by an append-only ledger keyed
  on the donation id, so a replayed event cannot double-credit.
* The score is non-monetary and must not encourage unsafe donation frequency or
  imply medical eligibility. The system therefore surfaces a minimum-interval
  advisory and never gamifies frequency.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

POINTS_PER_VERIFIED_DONATION = 100

# Advisory only. Indian national guidance commonly cites 90 days between whole
# blood donations; this is surfaced as information, never as medical clearance.
MIN_DONATION_INTERVAL_DAYS = 90


class Milestone(StrEnum):
    FIRST_DROP = "FIRST_DROP"
    LIFE_SAVER = "LIFE_SAVER"
    COMMUNITY_HERO = "COMMUNITY_HERO"
    LEGACY_DONOR = "LEGACY_DONOR"


MILESTONE_THRESHOLDS: dict[Milestone, int] = {
    Milestone.FIRST_DROP: 1,
    Milestone.LIFE_SAVER: 3,
    Milestone.COMMUNITY_HERO: 5,
    Milestone.LEGACY_DONOR: 10,
}

MILESTONE_LABELS: dict[Milestone, str] = {
    Milestone.FIRST_DROP: "First Drop",
    Milestone.LIFE_SAVER: "Life Saver",
    Milestone.COMMUNITY_HERO: "Community Hero",
    Milestone.LEGACY_DONOR: "Legacy Donor",
}


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    donation_id: str
    donor_id: str
    points: int
    reason: str
    occurred_at: datetime


def points_for_verified_donation(points: int = POINTS_PER_VERIFIED_DONATION) -> int:
    return points


def compute_score(entries: list[LedgerEntry]) -> int:
    """Total score is always derived from the ledger, never stored as truth.

    A cached counter may exist for display, but any disagreement is resolved in
    favour of the ledger -- which is what makes the recalculation edge case safe.
    """
    return sum(e.points for e in entries)


def verified_donation_count(entries: list[LedgerEntry]) -> int:
    return sum(1 for e in entries if e.reason == "VERIFIED_DONATION")


def earned_milestones(verified_count: int) -> list[Milestone]:
    return [m for m, threshold in MILESTONE_THRESHOLDS.items() if verified_count >= threshold]


def newly_earned_milestones(previous_count: int, new_count: int) -> list[Milestone]:
    """Milestones crossed by this donation -- used to avoid re-announcing old ones."""
    before = set(earned_milestones(previous_count))
    after = set(earned_milestones(new_count))
    gained = after - before
    return [m for m in MILESTONE_THRESHOLDS if m in gained]


def next_milestone(verified_count: int) -> tuple[Milestone, int] | None:
    """The next milestone and how many more donations it needs."""
    for milestone, threshold in MILESTONE_THRESHOLDS.items():
        if verified_count < threshold:
            return milestone, threshold - verified_count
    return None


def is_duplicate_credit(donation_id: str, existing_entries: list[LedgerEntry]) -> bool:
    """Exactly-once credit check. The repository also enforces this with a
    conditional write; this function makes the rule unit-testable."""
    return any(e.donation_id == donation_id for e in existing_entries)


@dataclass(frozen=True, slots=True)
class DonationIntervalAdvice:
    eligible_by_interval: bool
    days_since_last: int | None
    next_eligible_date: datetime | None
    message: str


def donation_interval_advice(
    last_donation_at: datetime | None,
    now: datetime,
    interval_days: int = MIN_DONATION_INTERVAL_DAYS,
) -> DonationIntervalAdvice:
    """Informational interval guidance.

    This is deliberately NOT a medical eligibility decision. LifeLink cannot
    assess fitness to donate; it only reports elapsed time and points the user at
    camp staff. The wording here is part of that commitment.
    """
    if last_donation_at is None:
        return DonationIntervalAdvice(
            eligible_by_interval=True,
            days_since_last=None,
            next_eligible_date=None,
            message=(
                "No previous verified donation on record. Camp staff will assess "
                "your eligibility on the day."
            ),
        )

    days = (now - last_donation_at).days
    next_date = last_donation_at + timedelta(days=interval_days)
    if days >= interval_days:
        return DonationIntervalAdvice(
            eligible_by_interval=True,
            days_since_last=days,
            next_eligible_date=next_date,
            message=(
                f"{days} days since your last verified donation. Final eligibility "
                "is determined by camp staff, not by this app."
            ),
        )
    return DonationIntervalAdvice(
        eligible_by_interval=False,
        days_since_last=days,
        next_eligible_date=next_date,
        message=(
            f"Only {days} days since your last verified donation. The usual minimum "
            f"interval is {interval_days} days. Please speak to camp staff before "
            "registering."
        ),
    )
