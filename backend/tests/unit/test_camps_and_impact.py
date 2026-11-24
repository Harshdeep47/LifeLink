"""Camp lifecycle, registration rules, donation verification and the impact ledger.

Covers spec 5.2-5.6 and the camp/donor edge cases -- especially the three rules
the spec treats as non-negotiable: registration is not attendance, attendance is
not a donation, and a donor may never verify their own donation.
"""
from __future__ import annotations

import pytest

from domain.camps import (
    CampStatus,
    DonationStatus,
    RegistrationStatus,
    assert_camp_transition,
    assert_can_register,
    assert_can_verify_donation,
    can_register,
    derive_camp_status,
    should_send_reminder,
)
from domain.errors import (
    CapacityExceededError,
    ForbiddenError,
    InvalidStateTransitionError,
    ValidationError,
)
from domain.impact import (
    POINTS_PER_VERIFIED_DONATION,
    LedgerEntry,
    Milestone,
    compute_score,
    donation_interval_advice,
    earned_milestones,
    is_duplicate_credit,
    newly_earned_milestones,
    next_milestone,
    verified_donation_count,
)
from tests.conftest import NOW, days_ago, days_ahead, hours_ago, hours_ahead

pytestmark = pytest.mark.unit


class TestCampLifecycle:
    def test_approval_path(self):
        assert_camp_transition(CampStatus.PENDING_APPROVAL, CampStatus.UPCOMING)
        assert_camp_transition(CampStatus.UPCOMING, CampStatus.ONGOING)
        assert_camp_transition(CampStatus.ONGOING, CampStatus.COMPLETED)

    def test_cannot_skip_from_pending_to_completed(self):
        with pytest.raises(InvalidStateTransitionError):
            assert_camp_transition(CampStatus.PENDING_APPROVAL, CampStatus.COMPLETED)

    def test_cancelled_is_terminal(self):
        with pytest.raises(InvalidStateTransitionError):
            assert_camp_transition(CampStatus.CANCELLED, CampStatus.UPCOMING)

    def test_completed_is_terminal(self):
        with pytest.raises(InvalidStateTransitionError):
            assert_camp_transition(CampStatus.COMPLETED, CampStatus.ONGOING)

    def test_error_lists_the_allowed_transitions(self):
        with pytest.raises(InvalidStateTransitionError) as exc:
            assert_camp_transition(CampStatus.COMPLETED, CampStatus.ONGOING)
        assert exc.value.details["allowed"] == []


class TestDerivedCampStatus:
    def test_future_camp_is_upcoming(self):
        status = derive_camp_status(
            current=CampStatus.UPCOMING,
            starts_at=days_ahead(2),
            ends_at=days_ahead(3),
            now=NOW,
        )
        assert status is CampStatus.UPCOMING

    def test_camp_in_progress_becomes_ongoing(self):
        status = derive_camp_status(
            current=CampStatus.UPCOMING,
            starts_at=hours_ago(1),
            ends_at=hours_ahead(4),
            now=NOW,
        )
        assert status is CampStatus.ONGOING

    def test_finished_camp_becomes_completed(self):
        status = derive_camp_status(
            current=CampStatus.ONGOING,
            starts_at=days_ago(2),
            ends_at=hours_ago(1),
            now=NOW,
        )
        assert status is CampStatus.COMPLETED

    def test_time_never_resurrects_a_cancelled_camp(self):
        status = derive_camp_status(
            current=CampStatus.CANCELLED,
            starts_at=hours_ago(1),
            ends_at=hours_ahead(4),
            now=NOW,
        )
        assert status is CampStatus.CANCELLED

    def test_unapproved_camp_does_not_auto_start(self):
        status = derive_camp_status(
            current=CampStatus.PENDING_APPROVAL,
            starts_at=hours_ago(1),
            ends_at=hours_ahead(4),
            now=NOW,
        )
        assert status is CampStatus.PENDING_APPROVAL


def _registration_args(**overrides):
    base = dict(
        camp_status=CampStatus.UPCOMING,
        registration_deadline=hours_ahead(24),
        starts_at=days_ahead(2),
        capacity=50,
        registered_count=10,
        already_registered=False,
        now=NOW,
    )
    base.update(overrides)
    return base


class TestRegistrationRules:
    def test_normal_registration_is_allowed(self):
        assert can_register(**_registration_args()).allowed is True

    def test_duplicate_registration_is_refused(self):
        check = can_register(**_registration_args(already_registered=True))
        assert check.allowed is False
        assert check.reason == "ALREADY_REGISTERED"

    def test_full_camp_is_refused(self):
        check = can_register(**_registration_args(capacity=50, registered_count=50))
        assert check.allowed is False
        assert check.reason == "CAMP_FULL"

    def test_full_camp_raises_capacity_error(self):
        with pytest.raises(CapacityExceededError):
            assert_can_register(**_registration_args(capacity=5, registered_count=5))

    def test_registration_after_deadline_is_refused(self):
        check = can_register(**_registration_args(registration_deadline=hours_ago(1)))
        assert check.allowed is False
        assert check.reason == "REGISTRATION_CLOSED"

    def test_cancelled_camp_refuses_registration(self):
        check = can_register(**_registration_args(camp_status=CampStatus.CANCELLED))
        assert check.allowed is False
        assert check.reason == "CAMP_CANCELLED"

    def test_unapproved_camp_refuses_registration(self):
        check = can_register(**_registration_args(camp_status=CampStatus.PENDING_APPROVAL))
        assert check.allowed is False
        assert check.reason == "CAMP_NOT_APPROVED"

    def test_reduced_capacity_below_current_count_blocks_new_registrations(self):
        """Spec 12.3: camp capacity reduced after registrations already exist."""
        check = can_register(**_registration_args(capacity=5, registered_count=8))
        assert check.allowed is False
        assert check.reason == "CAMP_FULL"

    def test_refusal_raises_validation_error_with_reason(self):
        with pytest.raises(ValidationError) as exc:
            assert_can_register(**_registration_args(camp_status=CampStatus.CANCELLED))
        assert exc.value.details["reason"] == "CAMP_CANCELLED"


class TestDonationVerificationAuthority:
    def test_staff_can_verify_another_persons_donation(self):
        assert_can_verify_donation(
            verifier_id="staff-1",
            donor_id="donor-1",
            verifier_is_camp_staff=True,
            donation_status=DonationStatus.RECORDED,
        )

    def test_donor_cannot_verify_their_own_donation(self):
        """The spec's hardest rule in this feature."""
        with pytest.raises(ForbiddenError) as exc:
            assert_can_verify_donation(
                verifier_id="donor-1",
                donor_id="donor-1",
                verifier_is_camp_staff=True,
                donation_status=DonationStatus.RECORDED,
            )
        assert exc.value.details["rule"] == "SELF_VERIFICATION_FORBIDDEN"

    def test_being_staff_does_not_permit_self_verification(self):
        """Even a camp organiser who donated cannot sign off their own donation."""
        with pytest.raises(ForbiddenError):
            assert_can_verify_donation(
                verifier_id="organizer-7",
                donor_id="organizer-7",
                verifier_is_camp_staff=True,
                donation_status=DonationStatus.RECORDED,
            )

    def test_non_staff_cannot_verify(self):
        with pytest.raises(ForbiddenError) as exc:
            assert_can_verify_donation(
                verifier_id="random-user",
                donor_id="donor-1",
                verifier_is_camp_staff=False,
                donation_status=DonationStatus.RECORDED,
            )
        assert exc.value.details["rule"] == "VERIFIER_NOT_CAMP_STAFF"

    def test_double_verification_is_refused(self):
        with pytest.raises(InvalidStateTransitionError):
            assert_can_verify_donation(
                verifier_id="staff-1",
                donor_id="donor-1",
                verifier_is_camp_staff=True,
                donation_status=DonationStatus.VERIFIED,
            )


def _reminder_args(**overrides):
    base = dict(
        camp_status=CampStatus.UPCOMING,
        registration_status=RegistrationStatus.REGISTERED,
        notifications_enabled=True,
        consent_given=True,
        already_sent=False,
        scheduled_for=NOW,
        now=NOW,
    )
    base.update(overrides)
    return base


class TestReminderRecheck:
    """Spec 5.5 requires five rechecks immediately before each send."""

    def test_normal_reminder_is_sent(self):
        assert should_send_reminder(**_reminder_args()) is True

    def test_no_reminder_for_a_cancelled_camp(self):
        assert should_send_reminder(**_reminder_args(camp_status=CampStatus.CANCELLED)) is False

    def test_no_duplicate_reminder(self):
        assert should_send_reminder(**_reminder_args(already_sent=True)) is False

    def test_no_reminder_for_opted_out_user(self):
        assert should_send_reminder(**_reminder_args(notifications_enabled=False)) is False

    def test_no_reminder_without_consent(self):
        assert should_send_reminder(**_reminder_args(consent_given=False)) is False

    def test_no_reminder_after_user_withdrew_registration(self):
        assert (
            should_send_reminder(
                **_reminder_args(registration_status=RegistrationStatus.CANCELLED_BY_USER)
            )
            is False
        )

    def test_stale_schedule_is_not_sent(self):
        """A job that fires hours late must not send a 2-hour reminder."""
        assert should_send_reminder(**_reminder_args(scheduled_for=hours_ago(5))) is False

    def test_small_drift_is_tolerated(self):
        assert should_send_reminder(**_reminder_args(scheduled_for=hours_ago(0.1))) is True


def _entry(donation_id: str, points: int = POINTS_PER_VERIFIED_DONATION) -> LedgerEntry:
    return LedgerEntry(
        donation_id=donation_id,
        donor_id="donor-1",
        points=points,
        reason="VERIFIED_DONATION",
        occurred_at=NOW,
    )


class TestImpactLedger:
    def test_one_verified_donation_scores_one_hundred(self):
        assert compute_score([_entry("d1")]) == 100

    def test_score_is_derived_from_the_ledger(self):
        entries = [_entry("d1"), _entry("d2"), _entry("d3")]
        assert compute_score(entries) == 300
        assert verified_donation_count(entries) == 3

    def test_duplicate_credit_is_detected(self):
        """Spec 19: donation impact credited exactly once."""
        entries = [_entry("d1")]
        assert is_duplicate_credit("d1", entries) is True
        assert is_duplicate_credit("d2", entries) is False

    def test_empty_ledger_scores_zero(self):
        assert compute_score([]) == 0


class TestMilestones:
    @pytest.mark.parametrize(
        ("count", "expected"),
        [
            (0, []),
            (1, [Milestone.FIRST_DROP]),
            (2, [Milestone.FIRST_DROP]),
            (3, [Milestone.FIRST_DROP, Milestone.LIFE_SAVER]),
            (5, [Milestone.FIRST_DROP, Milestone.LIFE_SAVER, Milestone.COMMUNITY_HERO]),
            (
                10,
                [
                    Milestone.FIRST_DROP,
                    Milestone.LIFE_SAVER,
                    Milestone.COMMUNITY_HERO,
                    Milestone.LEGACY_DONOR,
                ],
            ),
        ],
    )
    def test_thresholds_match_the_specification(self, count, expected):
        assert earned_milestones(count) == expected

    def test_only_newly_crossed_milestones_are_announced(self):
        assert newly_earned_milestones(2, 3) == [Milestone.LIFE_SAVER]

    def test_no_announcement_when_nothing_new_is_crossed(self):
        assert newly_earned_milestones(3, 4) == []

    def test_next_milestone_reports_remaining_count(self):
        assert next_milestone(1) == (Milestone.LIFE_SAVER, 2)

    def test_no_next_milestone_after_the_last_one(self):
        assert next_milestone(10) is None


class TestDonationIntervalAdvice:
    def test_first_time_donor_is_told_staff_will_assess(self):
        advice = donation_interval_advice(None, NOW)
        assert advice.eligible_by_interval is True
        assert "camp staff" in advice.message.lower()

    def test_recent_donor_is_warned_but_not_blocked_medically(self):
        advice = donation_interval_advice(days_ago(30), NOW)
        assert advice.eligible_by_interval is False
        assert advice.days_since_last == 30
        assert "camp staff" in advice.message.lower()

    def test_long_ago_donor_passes_the_interval_check(self):
        advice = donation_interval_advice(days_ago(120), NOW)
        assert advice.eligible_by_interval is True

    def test_advice_never_claims_medical_clearance(self):
        """The system must not imply medical eligibility (spec 5.6)."""
        for last in (None, days_ago(10), days_ago(200)):
            message = donation_interval_advice(last, NOW).message.lower()
            assert "eligible to donate" not in message
            assert "you are cleared" not in message
