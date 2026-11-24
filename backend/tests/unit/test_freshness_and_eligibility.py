"""Freshness labelling, verification separation and batch eligibility.

Covers spec 3.4, 3.5 and the inventory entries of the edge-case register.
"""
from __future__ import annotations

import pytest

from domain.blood import BatchStatus, FreshnessLabel, VerificationStatus
from domain.eligibility import (
    REASON_EXPIRED,
    REASON_INVALID_EXPIRY,
    REASON_MISSING_EXPIRY,
    REASON_NEGATIVE_UNITS,
    REASON_NO_UNITS,
    REASON_QUARANTINED,
    REASON_WITHDRAWN,
    evaluate_batch_eligibility,
    is_near_expiry,
)
from domain.freshness import freshness_label, verification_status
from tests.conftest import NOW, days_ago, days_ahead, hours_ago, hours_ahead

pytestmark = pytest.mark.unit


class TestFreshnessLabels:
    """The spec defines exact bands; these assert the boundaries, not just the middles."""

    @pytest.mark.parametrize(
        ("age_hours", "expected"),
        [
            (0.0, FreshnessLabel.FRESH),
            (5.9, FreshnessLabel.FRESH),
            (6.0, FreshnessLabel.FRESH),       # inclusive upper bound of 0-6h
            (6.1, FreshnessLabel.AGING),
            (23.9, FreshnessLabel.AGING),
            (24.0, FreshnessLabel.AGING),      # inclusive upper bound of >6-24h
            (24.1, FreshnessLabel.STALE),
            (47.9, FreshnessLabel.STALE),
            (48.0, FreshnessLabel.STALE),      # inclusive upper bound of >24-48h
            (48.1, FreshnessLabel.OUTDATED),
            (720.0, FreshnessLabel.OUTDATED),
        ],
    )
    def test_bands_match_specification(self, age_hours, expected):
        assert freshness_label(hours_ago(age_hours), NOW) is expected

    def test_missing_timestamp_is_unknown_not_fresh(self):
        assert freshness_label(None, NOW) is FreshnessLabel.UNKNOWN

    def test_future_timestamp_is_unknown_not_fresh(self):
        """Clock skew or bad data must not be rewarded with a FRESH label."""
        assert freshness_label(hours_ahead(5), NOW) is FreshnessLabel.UNKNOWN


class TestVerificationIsSeparateFromFreshness:
    """ADR-0003 / spec 3.5: an update is not a verification."""

    def test_never_verified_is_unverified(self):
        assert verification_status(None, NOW) is VerificationStatus.UNVERIFIED

    def test_recent_verification_is_verified(self):
        assert verification_status(hours_ago(10), NOW) is VerificationStatus.VERIFIED

    def test_old_verification_expires(self):
        assert (
            verification_status(hours_ago(100), NOW) is VerificationStatus.VERIFICATION_EXPIRED
        )

    def test_fresh_update_does_not_imply_verification(self):
        """The central integrity claim: a batch updated seconds ago by an API feed
        is FRESH but still UNVERIFIED."""
        assert freshness_label(hours_ago(0.01), NOW) is FreshnessLabel.FRESH
        assert verification_status(None, NOW) is VerificationStatus.UNVERIFIED


class TestBatchEligibility:
    def test_healthy_batch_is_eligible(self):
        result = evaluate_batch_eligibility(
            status=BatchStatus.AVAILABLE,
            available_units=5,
            expires_at=days_ahead(10),
            collected_at=days_ago(5),
            now=NOW,
        )
        assert result.eligible is True
        assert result.reasons == ()

    def test_expired_batch_is_ineligible(self):
        result = evaluate_batch_eligibility(
            status=BatchStatus.AVAILABLE,
            available_units=5,
            expires_at=hours_ago(1),
            collected_at=days_ago(40),
            now=NOW,
        )
        assert result.eligible is False
        assert REASON_EXPIRED in result.reasons

    def test_quarantined_batch_is_ineligible(self):
        result = evaluate_batch_eligibility(
            status=BatchStatus.QUARANTINED,
            available_units=5,
            expires_at=days_ahead(10),
            collected_at=days_ago(5),
            now=NOW,
        )
        assert result.eligible is False
        assert REASON_QUARANTINED in result.reasons

    def test_withdrawn_batch_is_ineligible(self):
        result = evaluate_batch_eligibility(
            status=BatchStatus.WITHDRAWN,
            available_units=5,
            expires_at=days_ahead(10),
            collected_at=days_ago(5),
            now=NOW,
        )
        assert result.eligible is False
        assert REASON_WITHDRAWN in result.reasons

    def test_missing_expiry_does_not_silently_pass(self):
        """Spec 3.4: invalid or missing required dates must not produce eligible stock."""
        result = evaluate_batch_eligibility(
            status=BatchStatus.AVAILABLE,
            available_units=5,
            expires_at=None,
            collected_at=days_ago(5),
            now=NOW,
        )
        assert result.eligible is False
        assert REASON_MISSING_EXPIRY in result.reasons

    def test_expiry_before_collection_is_flagged_as_invalid(self):
        result = evaluate_batch_eligibility(
            status=BatchStatus.AVAILABLE,
            available_units=5,
            expires_at=days_ago(10),
            collected_at=days_ago(5),
            now=NOW,
        )
        assert result.eligible is False
        assert REASON_INVALID_EXPIRY in result.reasons

    def test_zero_units_is_ineligible(self):
        result = evaluate_batch_eligibility(
            status=BatchStatus.AVAILABLE,
            available_units=0,
            expires_at=days_ahead(10),
            collected_at=days_ago(5),
            now=NOW,
        )
        assert result.eligible is False
        assert REASON_NO_UNITS in result.reasons

    def test_negative_units_is_ineligible(self):
        result = evaluate_batch_eligibility(
            status=BatchStatus.AVAILABLE,
            available_units=-3,
            expires_at=days_ahead(10),
            collected_at=days_ago(5),
            now=NOW,
        )
        assert result.eligible is False
        assert REASON_NEGATIVE_UNITS in result.reasons

    def test_expiring_exactly_now_is_expired(self):
        """Boundary: expiry is exclusive -- a batch expiring at this instant is out."""
        result = evaluate_batch_eligibility(
            status=BatchStatus.AVAILABLE,
            available_units=5,
            expires_at=NOW,
            collected_at=days_ago(5),
            now=NOW,
        )
        assert result.eligible is False
        assert REASON_EXPIRED in result.reasons

    def test_multiple_problems_are_all_reported(self):
        result = evaluate_batch_eligibility(
            status=BatchStatus.QUARANTINED,
            available_units=0,
            expires_at=None,
            collected_at=None,
            now=NOW,
        )
        assert result.eligible is False
        assert REASON_QUARANTINED in result.reasons
        assert REASON_NO_UNITS in result.reasons
        assert REASON_MISSING_EXPIRY in result.reasons


class TestNearExpiry:
    def test_batch_expiring_tomorrow_is_near_expiry(self):
        assert is_near_expiry(hours_ahead(20), NOW) is True

    def test_batch_expiring_next_month_is_not(self):
        assert is_near_expiry(days_ahead(30), NOW) is False

    def test_already_expired_is_not_near_expiry(self):
        """Already expired is a different state; it is handled by eligibility."""
        assert is_near_expiry(hours_ago(1), NOW) is False

    def test_missing_expiry_is_not_near_expiry(self):
        assert is_near_expiry(None, NOW) is False
