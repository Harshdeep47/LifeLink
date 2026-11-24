"""Blood compatibility lookup (spec 6.5, ADR-0008).

The important assertions here are about what the engine *refuses* to do:
it never infers, never defaults to compatible, and never hides that the
reference table has not been clinically reviewed for this deployment.
"""
from __future__ import annotations

import pytest

from domain.blood import BloodGroup, Component
from domain.compatibility import (
    CompatibilityVerdict,
    check_compatibility,
    compatible_donor_groups,
    get_reference,
)

pytestmark = pytest.mark.unit


class TestReferenceIntegrity:
    def test_reference_declares_its_review_status(self):
        ref = get_reference()
        assert ref.review_status == "UNREVIEWED_SYNTHETIC"
        assert ref.reviewed_by is None

    def test_reference_carries_a_disclaimer(self):
        assert "qualified" in get_reference().disclaimer.lower()

    def test_every_result_propagates_version_and_review_status(self):
        result = check_compatibility(
            recipient_group=BloodGroup.A_POS,
            donor_group=BloodGroup.O_NEG,
            component=Component.PRBC,
        )
        assert result.rules_version == "1.0.0"
        assert result.review_status == "UNREVIEWED_SYNTHETIC"
        assert result.disclaimer


class TestRedCellCompatibility:
    @pytest.mark.parametrize(
        ("recipient", "donor", "expected"),
        [
            # O- is the universal red-cell donor.
            (BloodGroup.AB_POS, BloodGroup.O_NEG, True),
            (BloodGroup.O_NEG, BloodGroup.O_NEG, True),
            # AB+ is the universal red-cell recipient.
            (BloodGroup.AB_POS, BloodGroup.AB_POS, True),
            (BloodGroup.AB_POS, BloodGroup.B_NEG, True),
            # An Rh-negative recipient must never be offered Rh-positive red cells.
            (BloodGroup.O_NEG, BloodGroup.O_POS, False),
            (BloodGroup.A_NEG, BloodGroup.A_POS, False),
            (BloodGroup.AB_NEG, BloodGroup.AB_POS, False),
            # ABO mismatches.
            (BloodGroup.A_POS, BloodGroup.B_POS, False),
            (BloodGroup.O_POS, BloodGroup.A_POS, False),
            (BloodGroup.B_NEG, BloodGroup.A_NEG, False),
        ],
    )
    def test_known_red_cell_pairs(self, recipient, donor, expected):
        result = check_compatibility(
            recipient_group=recipient, donor_group=donor, component=Component.PRBC
        )
        assert result.is_match is expected

    def test_o_negative_recipient_accepts_only_o_negative(self):
        groups = compatible_donor_groups(
            recipient_group=BloodGroup.O_NEG, component=Component.PRBC
        )
        assert groups == (BloodGroup.O_NEG,)

    def test_ab_positive_recipient_accepts_all_eight(self):
        groups = compatible_donor_groups(
            recipient_group=BloodGroup.AB_POS, component=Component.PRBC
        )
        assert len(groups) == 8


class TestPlasmaIsTheInverseOfRedCells:
    """A good check that the table was not copy-pasted: plasma runs the other way."""

    def test_ab_is_the_universal_plasma_donor(self):
        for recipient in BloodGroup:
            result = check_compatibility(
                recipient_group=recipient,
                donor_group=BloodGroup.AB_POS,
                component=Component.FFP,
            )
            assert result.is_match is True, f"AB+ plasma should suit {recipient}"

    def test_o_recipient_can_receive_any_plasma(self):
        groups = compatible_donor_groups(
            recipient_group=BloodGroup.O_POS, component=Component.FFP
        )
        assert len(groups) == 8

    def test_ab_recipient_can_only_receive_ab_plasma(self):
        groups = compatible_donor_groups(
            recipient_group=BloodGroup.AB_POS, component=Component.FFP
        )
        assert set(groups) == {BloodGroup.AB_NEG, BloodGroup.AB_POS}


class TestWholeBloodRequiresIdenticalAbo:
    def test_o_negative_cannot_receive_a_negative_whole_blood(self):
        result = check_compatibility(
            recipient_group=BloodGroup.O_NEG,
            donor_group=BloodGroup.A_NEG,
            component=Component.WHOLE_BLOOD,
        )
        assert result.is_match is False

    def test_universal_donor_rule_does_not_apply_to_whole_blood(self):
        """O- is not a universal donor for whole blood -- a classic error."""
        result = check_compatibility(
            recipient_group=BloodGroup.AB_POS,
            donor_group=BloodGroup.O_NEG,
            component=Component.WHOLE_BLOOD,
        )
        assert result.is_match is False


class TestPlateletsFlagNonIdenticalForReview:
    def test_identical_platelets_need_no_extra_review_flag(self):
        result = check_compatibility(
            recipient_group=BloodGroup.A_POS,
            donor_group=BloodGroup.A_POS,
            component=Component.PLATELETS,
        )
        assert result.is_match is True
        assert result.requires_clinical_review is False

    def test_compatible_but_non_identical_platelets_are_flagged(self):
        result = check_compatibility(
            recipient_group=BloodGroup.A_POS,
            donor_group=BloodGroup.O_NEG,
            component=Component.PLATELETS,
        )
        assert result.is_match is True
        assert result.requires_clinical_review is True


class TestFailClosedBehaviour:
    """The engine must never invent compatibility (spec 6.5)."""

    def test_unknown_component_resolves_to_unknown_not_compatible(self):
        class FakeComponent:
            value = "CRYOPRECIPITATE"

        result = check_compatibility(
            recipient_group=BloodGroup.A_POS,
            donor_group=BloodGroup.A_POS,
            component=FakeComponent(),  # type: ignore[arg-type]
        )
        assert result.verdict is CompatibilityVerdict.UNKNOWN
        assert result.is_match is False

    def test_unknown_resolves_to_empty_donor_list_not_all_groups(self):
        class FakeComponent:
            value = "CRYOPRECIPITATE"

        groups = compatible_donor_groups(
            recipient_group=BloodGroup.A_POS,
            component=FakeComponent(),  # type: ignore[arg-type]
        )
        assert groups == ()

    def test_only_explicit_compatible_counts_as_a_match(self):
        incompatible = check_compatibility(
            recipient_group=BloodGroup.O_NEG,
            donor_group=BloodGroup.AB_POS,
            component=Component.PRBC,
        )
        assert incompatible.verdict is CompatibilityVerdict.INCOMPATIBLE
        assert incompatible.is_match is False


class TestEveryGroupAndComponentIsCovered:
    def test_all_eight_groups_present_for_every_component(self):
        """Spec 3.2 requires all eight groups and all four components."""
        ref = get_reference()
        for component in Component:
            for group in BloodGroup:
                donors = ref.compatible_donor_groups(group, component)
                assert donors is not None, f"{component.value}/{group.value} missing"
                assert len(donors) >= 1

    def test_self_compatibility_holds_for_red_cells(self):
        for group in BloodGroup:
            result = check_compatibility(
                recipient_group=group, donor_group=group, component=Component.PRBC
            )
            assert result.is_match is True, f"{group} should accept its own group"
