"""Emergency request lifecycle, priority certification and fair scheduling.

Covers spec 6.4, 6.6, 6.7, 6.8 and the emergency edge cases -- including P3
starvation, which the spec singles out as a required fairness property.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from domain.emergency import (
    AGING_INTERVAL_MINUTES,
    LABEL_TO_PRIORITY,
    PRIORITY_LABELS,
    ClinicalPriority,
    ProviderResponseType,
    RequestStatus,
    assert_transition,
    can_transition,
    compute_effective_priority,
    dispatch_sort_key,
    is_expired,
    parse_priority_label,
    tally_responses,
)
from domain.errors import InvalidStateTransitionError, ValidationError
from tests.conftest import NOW, hours_ago, hours_ahead

pytestmark = pytest.mark.unit


def minutes_ago(m: float):
    return NOW - timedelta(minutes=m)


def minutes_ahead(m: float):
    return NOW + timedelta(minutes=m)


class TestPriorityMapping:
    def test_spec_mapping_is_exact(self):
        """Spec 6.4: Critical -> P1, Urgent -> P2, Scheduled -> P3."""
        assert LABEL_TO_PRIORITY["CRITICAL"] is ClinicalPriority.P1
        assert LABEL_TO_PRIORITY["URGENT"] is ClinicalPriority.P2
        assert LABEL_TO_PRIORITY["SCHEDULED"] is ClinicalPriority.P3

    def test_labels_round_trip(self):
        for priority, label in PRIORITY_LABELS.items():
            assert parse_priority_label(label) is priority

    def test_internal_codes_are_accepted(self):
        assert parse_priority_label("P1") is ClinicalPriority.P1

    def test_parsing_is_case_insensitive(self):
        assert parse_priority_label("critical") is ClinicalPriority.P1

    def test_unknown_priority_is_rejected(self):
        with pytest.raises(ValidationError):
            parse_priority_label("SUPER_URGENT")


class TestRequestLifecycle:
    def test_full_happy_path_is_valid(self):
        path = [
            RequestStatus.REQUEST_CREATED,
            RequestStatus.VERIFICATION_PENDING,
            RequestStatus.HOSPITAL_CERTIFIED,
            RequestStatus.MATCHING_INITIATED,
            RequestStatus.PROVIDERS_NOTIFIED,
            RequestStatus.RESPONSES_RECEIVED,
            RequestStatus.AVAILABILITY_CONFIRMED,
            RequestStatus.RESOLVED,
        ]
        for current, target in zip(path[:-1], path[1:], strict=True):
            assert_transition(current, target)

    def test_cannot_jump_straight_to_resolved(self):
        with pytest.raises(InvalidStateTransitionError):
            assert_transition(RequestStatus.REQUEST_CREATED, RequestStatus.RESOLVED)

    def test_cannot_skip_hospital_certification(self):
        with pytest.raises(InvalidStateTransitionError):
            assert_transition(
                RequestStatus.VERIFICATION_PENDING, RequestStatus.MATCHING_INITIATED
            )

    def test_cancellation_is_allowed_from_any_active_state(self):
        for status in [
            RequestStatus.REQUEST_CREATED,
            RequestStatus.VERIFICATION_PENDING,
            RequestStatus.HOSPITAL_CERTIFIED,
            RequestStatus.MATCHING_INITIATED,
            RequestStatus.PROVIDERS_NOTIFIED,
            RequestStatus.RESPONSES_RECEIVED,
            RequestStatus.AVAILABILITY_CONFIRMED,
        ]:
            assert can_transition(status, RequestStatus.CANCELLED) is True

    def test_terminal_states_allow_nothing(self):
        for terminal in (
            RequestStatus.RESOLVED,
            RequestStatus.CANCELLED,
            RequestStatus.EXPIRED,
        ):
            for target in RequestStatus:
                assert can_transition(terminal, target) is False

    def test_late_response_after_cancellation_cannot_revive_request(self):
        """Spec 12.4: late response after cancellation."""
        with pytest.raises(InvalidStateTransitionError):
            assert_transition(RequestStatus.CANCELLED, RequestStatus.RESPONSES_RECEIVED)

    def test_rematch_is_allowed_when_all_providers_decline(self):
        assert can_transition(
            RequestStatus.RESPONSES_RECEIVED, RequestStatus.MATCHING_INITIATED
        ) is True


class TestEffectivePriorityAndFairness:
    def test_fresh_request_keeps_its_clinical_priority(self):
        effective = compute_effective_priority(
            clinical_priority=ClinicalPriority.P3,
            created_at=NOW,
            required_by=None,
            now=NOW,
        )
        assert effective is ClinicalPriority.P3

    def test_p3_ages_to_p2_after_one_interval(self):
        effective = compute_effective_priority(
            clinical_priority=ClinicalPriority.P3,
            created_at=minutes_ago(AGING_INTERVAL_MINUTES),
            required_by=None,
            now=NOW,
        )
        assert effective is ClinicalPriority.P2

    def test_p3_ages_to_p1_after_two_intervals(self):
        effective = compute_effective_priority(
            clinical_priority=ClinicalPriority.P3,
            created_at=minutes_ago(AGING_INTERVAL_MINUTES * 2),
            required_by=None,
            now=NOW,
        )
        assert effective is ClinicalPriority.P1

    def test_aging_never_goes_above_p1(self):
        effective = compute_effective_priority(
            clinical_priority=ClinicalPriority.P3,
            created_at=hours_ago(24),
            required_by=None,
            now=NOW,
        )
        assert effective is ClinicalPriority.P1

    def test_waiting_p3_overtakes_a_fresh_p2(self):
        """The anti-starvation property the spec requires, stated as an ordering."""
        aged_p3 = compute_effective_priority(
            clinical_priority=ClinicalPriority.P3,
            created_at=hours_ago(1),
            required_by=None,
            now=NOW,
        )
        fresh_p2 = compute_effective_priority(
            clinical_priority=ClinicalPriority.P2,
            created_at=NOW,
            required_by=None,
            now=NOW,
        )
        aged_key = dispatch_sort_key(effective_priority=aged_p3, created_at=hours_ago(1))
        fresh_key = dispatch_sort_key(effective_priority=fresh_p2, created_at=NOW)
        assert aged_key < fresh_key

    def test_imminent_deadline_promotes_to_p1(self):
        effective = compute_effective_priority(
            clinical_priority=ClinicalPriority.P3,
            created_at=NOW,
            required_by=minutes_ahead(20),
            now=NOW,
        )
        assert effective is ClinicalPriority.P1

    def test_distant_deadline_does_not_promote(self):
        effective = compute_effective_priority(
            clinical_priority=ClinicalPriority.P3,
            created_at=NOW,
            required_by=hours_ahead(10),
            now=NOW,
        )
        assert effective is ClinicalPriority.P3

    def test_fairness_does_not_mutate_clinical_priority(self):
        """Spec 6.6: fairness mechanisms must never change clinical priority.

        The function is pure and returns a separate value; the caller stores it
        in a different field. This test pins the contract that it returns a new
        value rather than reporting a changed clinical priority.
        """
        clinical = ClinicalPriority.P3
        effective = compute_effective_priority(
            clinical_priority=clinical,
            created_at=hours_ago(5),
            required_by=None,
            now=NOW,
        )
        assert clinical is ClinicalPriority.P3
        assert effective is ClinicalPriority.P1
        assert effective is not clinical


class TestDispatchOrdering:
    def test_higher_priority_sorts_first(self):
        p1 = dispatch_sort_key(effective_priority=ClinicalPriority.P1, created_at=NOW)
        p3 = dispatch_sort_key(effective_priority=ClinicalPriority.P3, created_at=hours_ago(1))
        assert p1 < p3

    def test_fifo_within_a_band(self):
        older = dispatch_sort_key(
            effective_priority=ClinicalPriority.P2, created_at=hours_ago(2)
        )
        newer = dispatch_sort_key(
            effective_priority=ClinicalPriority.P2, created_at=hours_ago(1)
        )
        assert older < newer


class TestExpiry:
    def test_past_deadline_is_expired(self):
        assert is_expired(hours_ago(1), NOW) is True

    def test_future_deadline_is_not_expired(self):
        assert is_expired(hours_ahead(1), NOW) is False

    def test_no_deadline_never_expires(self):
        assert is_expired(None, NOW) is False


class TestProviderResponseTally:
    def test_counts_each_response_type(self):
        tally = tally_responses([
            {"responseType": ProviderResponseType.ACCEPTED, "unitsOffered": 3},
            {"responseType": ProviderResponseType.REJECTED},
            {"responseType": ProviderResponseType.INSUFFICIENT_STOCK, "unitsOffered": 1},
            {"responseType": ProviderResponseType.NEEDS_CLARIFICATION},
        ])
        assert (tally.accepted, tally.rejected, tally.insufficient, tally.clarification) == (
            1, 1, 1, 1
        )
        assert tally.total == 4

    def test_units_offered_sums_accepted_and_partial(self):
        tally = tally_responses([
            {"responseType": ProviderResponseType.ACCEPTED, "unitsOffered": 4},
            {"responseType": ProviderResponseType.INSUFFICIENT_STOCK, "unitsOffered": 2},
        ])
        assert tally.units_offered == 6

    def test_two_providers_accepting_do_not_reserve_the_same_units(self):
        """ADR-0017: offers are willingness, not reservations.

        Both offers are recorded in full. Nothing is netted off a shared counter,
        because no such counter exists -- which is what makes double-counting
        structurally impossible rather than merely avoided.
        """
        tally = tally_responses([
            {"responseType": ProviderResponseType.ACCEPTED, "unitsOffered": 5},
            {"responseType": ProviderResponseType.ACCEPTED, "unitsOffered": 5},
        ])
        assert tally.accepted == 2
        assert tally.units_offered == 10

    def test_missing_units_offered_defaults_to_zero(self):
        tally = tally_responses([{"responseType": ProviderResponseType.ACCEPTED}])
        assert tally.units_offered == 0

    def test_empty_response_list(self):
        tally = tally_responses([])
        assert tally.total == 0
        assert tally.units_offered == 0
