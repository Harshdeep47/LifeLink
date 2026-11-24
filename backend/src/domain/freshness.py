"""Inventory freshness labelling (spec 3.5).

These are LifeLink *software data-quality* labels. They are not medical standards
and must never be presented as clinical guidance.

Crucially (ADR-0003): freshness derives ONLY from the last inventory update time.
An automated API update refreshes this label but says nothing about whether a human
independently verified the stock -- that is tracked separately.
"""
from __future__ import annotations

from datetime import datetime

from .blood import FreshnessLabel, VerificationStatus
from .clock import hours_between

FRESH_MAX_HOURS = 6.0
AGING_MAX_HOURS = 24.0
STALE_MAX_HOURS = 48.0

# How long an independent human verification stays meaningful before it is
# downgraded. Configurable; not a medical claim.
VERIFICATION_VALIDITY_HOURS = 72.0


def freshness_label(last_updated_at: datetime | None, now: datetime) -> FreshnessLabel:
    """Map age-since-update onto a freshness band.

    A missing or future-dated timestamp yields UNKNOWN rather than a flattering
    default -- spec 3.4 forbids invalid dates silently producing eligible stock.
    """
    if last_updated_at is None:
        return FreshnessLabel.UNKNOWN
    age = hours_between(last_updated_at, now)
    if age < 0:
        # Clock skew or bad data. Refuse to label it fresh.
        return FreshnessLabel.UNKNOWN
    if age <= FRESH_MAX_HOURS:
        return FreshnessLabel.FRESH
    if age <= AGING_MAX_HOURS:
        return FreshnessLabel.AGING
    if age <= STALE_MAX_HOURS:
        return FreshnessLabel.STALE
    return FreshnessLabel.OUTDATED


def verification_status(
    last_verified_at: datetime | None,
    now: datetime,
    validity_hours: float = VERIFICATION_VALIDITY_HOURS,
) -> VerificationStatus:
    """Independent human verification state -- deliberately separate from freshness."""
    if last_verified_at is None:
        return VerificationStatus.UNVERIFIED
    age = hours_between(last_verified_at, now)
    if age < 0:
        return VerificationStatus.UNVERIFIED
    if age <= validity_hours:
        return VerificationStatus.VERIFIED
    return VerificationStatus.VERIFICATION_EXPIRED


def freshness_score(label: FreshnessLabel) -> float:
    """0.0-1.0 contribution used by facility ranking (spec 4.4)."""
    return {
        FreshnessLabel.FRESH: 1.0,
        FreshnessLabel.AGING: 0.7,
        FreshnessLabel.STALE: 0.3,
        FreshnessLabel.OUTDATED: 0.05,
        FreshnessLabel.UNKNOWN: 0.0,
    }[label]


def verification_score(status: VerificationStatus) -> float:
    return {
        VerificationStatus.VERIFIED: 1.0,
        VerificationStatus.VERIFICATION_EXPIRED: 0.4,
        VerificationStatus.UNVERIFIED: 0.0,
    }[status]
