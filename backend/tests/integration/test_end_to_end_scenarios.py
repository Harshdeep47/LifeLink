"""The ten end-to-end scenarios the specification requires (PART 13.4).

Each test is named for the numbered scenario it covers and exercises the flow
through real services against a real DynamoDB surface -- conditional writes,
transactions, GSI queries and all. Where a scenario asserts something the system
must *refuse*, the refusal is asserted, not the happy path.
"""
from __future__ import annotations

import pytest

from domain.emergency import RequestStatus
from domain.errors import (
    CapacityExceededError,
    ConcurrentModificationError,
    DuplicateError,
    ForbiddenError,
    InvalidStateTransitionError,
    ValidationError,
)
from tests.integration.conftest import (
    days_ago,
    days_ahead,
    hours_ago,
    hours_ahead,
    make_context,
)

pytestmark = pytest.mark.integration


def add_stock(inventory_service, now, *, facility_id="fac-1", organization_id="org-bb-1",
              group="O-", component="PRBC", units=10, expires_at=None, actor="u-bb-admin"):
    context = make_context(user_id=actor, organization_id=organization_id)
    return inventory_service.create_batch(
        context=context,
        facility_id=facility_id,
        organization_id=organization_id,
        blood_group=group,
        component=component,
        units=units,
        collected_at=days_ago(3),
        expires_at=expires_at or days_ahead(25),
        now=now,
    )


class TestScenario01_StaffAddInventoryPublicDiscovers:
    """1. Blood bank staff add inventory; a public user discovers eligible stock."""

    def test_added_stock_becomes_publicly_discoverable(
        self, seeded, inventory_service, discovery_service, now
    ):
        add_stock(inventory_service, now, units=8)

        outcome = discovery_service.search_facilities(
            latitude=30.3398, longitude=76.3869, now=now,
            radius_km=10, blood_group="O-", component="PRBC", requested_units=2,
        )
        match = next(r for r in outcome["results"] if r["facilityId"] == "fac-1")
        assert match["availability"] == "AVAILABLE"
        assert match["eligibleUnits"] == 8
        assert match["straightLineKm"] == 0.0
        # A public search must never be told a road distance it does not have.
        assert match["roadKm"] is None
        assert match["routingAvailable"] is False


class TestScenario02_StockBecomesStale:
    """2. Stock becomes stale; the availability presentation changes."""

    def test_the_same_stock_is_labelled_stale_once_it_ages(
        self, seeded, inventory_service, discovery_service, repos, now
    ):
        batch = add_stock(inventory_service, now, units=6)

        fresh = discovery_service.search_facilities(
            latitude=30.3398, longitude=76.3869, now=now,
            radius_km=10, blood_group="O-", component="PRBC", requested_units=1,
        )
        fresh_row = next(r for r in fresh["results"] if r["facilityId"] == "fac-1")
        assert fresh_row["freshness"] == "FRESH"

        # Rewind the recorded update time to 30 hours ago. Batch is a frozen
        # slots dataclass, so replace() is the way to derive a variant.
        from dataclasses import replace

        from domain.clock import to_iso
        from repositories.inventory_repo import batch_to_item

        stored = repos.inventory.get_batch("fac-1", batch["batchId"])
        aged = replace(stored, last_updated_at=hours_ago(30))
        repos.inventory.put(batch_to_item(aged))
        repos.facilities.update(
            pk="FACILITY#fac-1", sk="META",
            update_expression="SET inventoryLastUpdatedAt = :at",
            expression_values={":at": to_iso(hours_ago(30))},
        )

        stale = discovery_service.search_facilities(
            latitude=30.3398, longitude=76.3869, now=now,
            radius_km=10, blood_group="O-", component="PRBC", requested_units=1,
        )
        stale_row = next(r for r in stale["results"] if r["facilityId"] == "fac-1")
        assert stale_row["freshness"] == "STALE"
        # Still available -- staleness is a data-quality signal, not an eligibility rule.
        assert stale_row["availability"] == "AVAILABLE"
        assert any("stale" in reason.lower() for reason in stale_row["rankExplanation"])


class TestScenario03_AlertMatchTriggersNotification:
    """3. A user creates an availability alert; matching stock notifies them."""

    def test_alert_matches_existing_stock_and_notifies_once(
        self, seeded, inventory_service, alert_service, notification_service, now
    ):
        add_stock(inventory_service, now, units=5)
        donor = make_context(user_id="u-donor-1", roles=("DONOR",), organization_id=None)

        created = alert_service.create_alert(
            context=donor, blood_group="O-", component="PRBC", required_units=2,
            latitude=30.3398, longitude=76.3869, radius_km=15, now=now,
        )

        assert created["immediateMatches"], "stock already nearby should match at once"
        match = created["immediateMatches"][0]
        assert match["facilityId"] == "fac-1"
        assert match["eligibleUnits"] == 5
        assert match["isReservation"] is False

        in_app = notification_service.test_channels[
            list(notification_service.test_channels)[1]
        ]
        email = notification_service.test_channels[list(notification_service.test_channels)[0]]
        delivered = in_app.sent + email.sent
        assert delivered, "a match must produce a notification"
        assert any("not reserved" in m.body_text.lower() for m in delivered)

        # Re-matching must not notify again for the same facility.
        before = len(in_app.sent) + len(email.sent)
        alert_service.match_alert(alert_id=created["alertId"], now=now, context=donor)
        assert len(in_app.sent) + len(email.sent) == before

    def test_an_unreported_facility_never_matches(
        self, seeded, alert_service, now
    ):
        """A silent facility is not a match, because unknown is not stock."""
        donor = make_context(user_id="u-donor-1", roles=("DONOR",), organization_id=None)
        created = alert_service.create_alert(
            context=donor, blood_group="AB-", component="PLATELETS", required_units=1,
            latitude=30.3450, longitude=76.3900, radius_km=5, now=now,
        )
        assert created["immediateMatches"] == []


class TestScenario04_CampRegisterCheckInVerify:
    """4. A user discovers and registers for a camp; staff check them in and
    verify a donation."""

    def test_the_full_camp_flow(self, seeded, camp_service, now):
        organizer = make_context(
            user_id="u-camp-org", roles=("CAMP_ORGANIZER",), organization_id="org-camp-1"
        )
        admin = make_context(user_id="u-admin", roles=("PLATFORM_ADMIN",), organization_id=None)
        donor = make_context(user_id="u-donor-1", roles=("DONOR",), organization_id=None)
        staff = make_context(
            user_id="u-camp-staff", roles=("CAMP_STAFF",), organization_id="org-camp-1"
        )

        camp = camp_service.create_camp(
            context=organizer, name="E2E Camp", description="scenario 4",
            latitude=30.3398, longitude=76.3869, address="1 Road", city="Patiala",
            starts_at=hours_ahead(26), ends_at=hours_ahead(34), capacity=10,
            registration_deadline=hours_ahead(20), now=now,
        )
        camp_id = camp["campId"]
        assert camp["status"] == "PENDING_APPROVAL"

        camp_service.approve_camp(context=admin, camp_id=camp_id, approve=True, now=now)
        camp_service.assign_staff(
            context=organizer, camp_id=camp_id, user_id="u-camp-staff", now=now
        )

        registration = camp_service.register(context=donor, camp_id=camp_id, now=now)
        assert registration["status"] == "REGISTERED"
        # Registration is explicitly not attendance or eligibility.
        assert "not attendance" in registration["notice"].lower()

        check_in = camp_service.check_in(
            context=staff, camp_id=camp_id, donor_id="u-donor-1", now=now
        )
        assert check_in["attendanceStatus"] == "CHECKED_IN"
        assert "does not record a donation" in check_in["notice"].lower()

        recorded = camp_service.record_donation(
            context=staff, camp_id=camp_id, donor_id="u-donor-1",
            blood_group="O-", component="WHOLE_BLOOD", units=1, now=now,
        )
        assert recorded["status"] == "RECORDED"

        verified = camp_service.verify_donation(
            context=staff, camp_id=camp_id, donor_id="u-donor-1",
            donation_id=recorded["donationId"], now=now,
        )
        assert verified["status"] == "VERIFIED"
        assert verified["impactScore"] == 100
        assert verified["verifiedDonations"] == 1
        assert "First Drop" in verified["newMilestones"]

    def test_a_donation_cannot_be_recorded_before_check_in(self, seeded, camp_service, now):
        organizer = make_context(
            user_id="u-camp-org", roles=("CAMP_ORGANIZER",), organization_id="org-camp-1"
        )
        admin = make_context(user_id="u-admin", roles=("PLATFORM_ADMIN",), organization_id=None)
        donor = make_context(user_id="u-donor-2", roles=("DONOR",), organization_id=None)

        camp = camp_service.create_camp(
            context=organizer, name="Order Camp", description="x",
            latitude=30.3398, longitude=76.3869, address="1", city="Patiala",
            starts_at=hours_ahead(26), ends_at=hours_ahead(34), capacity=5, now=now,
        )
        camp_service.approve_camp(
            context=admin, camp_id=camp["campId"], approve=True, now=now
        )
        camp_service.register(context=donor, camp_id=camp["campId"], now=now)

        with pytest.raises(ValidationError) as exc:
            camp_service.record_donation(
                context=organizer, camp_id=camp["campId"], donor_id="u-donor-2",
                blood_group="O+", component="WHOLE_BLOOD", units=1, now=now,
            )
        assert exc.value.details["rule"] == "ATTENDANCE_REQUIRED"


class TestScenario05_ImpactCreditedExactlyOnce:
    """5. A verified donation updates the impact ledger exactly once."""

    def test_replaying_verification_does_not_double_credit(
        self, seeded, camp_service, repos, now
    ):
        organizer = make_context(
            user_id="u-camp-org", roles=("CAMP_ORGANIZER",), organization_id="org-camp-1"
        )
        admin = make_context(user_id="u-admin", roles=("PLATFORM_ADMIN",), organization_id=None)
        donor = make_context(user_id="u-donor-1", roles=("DONOR",), organization_id=None)

        camp = camp_service.create_camp(
            context=organizer, name="Once Camp", description="scenario 5",
            latitude=30.3398, longitude=76.3869, address="1", city="Patiala",
            starts_at=hours_ahead(26), ends_at=hours_ahead(34), capacity=5, now=now,
        )
        camp_id = camp["campId"]
        camp_service.approve_camp(context=admin, camp_id=camp_id, approve=True, now=now)
        camp_service.register(context=donor, camp_id=camp_id, now=now)
        camp_service.check_in(
            context=organizer, camp_id=camp_id, donor_id="u-donor-1", now=now
        )
        recorded = camp_service.record_donation(
            context=organizer, camp_id=camp_id, donor_id="u-donor-1",
            blood_group="O-", component="WHOLE_BLOOD", units=1, now=now,
        )

        first = camp_service.verify_donation(
            context=organizer, camp_id=camp_id, donor_id="u-donor-1",
            donation_id=recorded["donationId"], now=now,
        )
        assert first["impactScore"] == 100

        # A second verification of the same donation must be refused outright.
        with pytest.raises(InvalidStateTransitionError):
            camp_service.verify_donation(
                context=organizer, camp_id=camp_id, donor_id="u-donor-1",
                donation_id=recorded["donationId"], now=now,
            )

        ledger = repos.donations.list_ledger("u-donor-1")
        entries = [e for e in ledger if e["donationId"] == recorded["donationId"]]
        assert len(entries) == 1, "exactly one ledger entry per verified donation"

        profile = camp_service.donor_profile(context=donor, now=now)
        assert profile["impactScore"] == 100
        assert profile["verifiedDonations"] == 1


class TestScenario06_HospitalCertifiesPriority:
    """6. A hospital-authorized user certifies an emergency request priority."""

    def test_authorized_hospital_user_certifies(self, seeded, emergency_service, now):
        staff = make_context(
            user_id="u-hosp-staff", roles=("HOSPITAL_STAFF",), organization_id="org-hosp-1"
        )
        created = emergency_service.create_request(
            context=staff, blood_group="O-", component="PRBC", required_units=3,
            latitude=30.3398, longitude=76.3869, required_by=hours_ahead(8),
            contact_name="Ward Sister", contact_phone="+91-00000-00000",
            consent_given=True, now=now,
        )
        # A new request carries no clinical priority.
        assert created["clinicalPriority"] is None
        assert created["status"] == RequestStatus.VERIFICATION_PENDING.value

        authorizer = make_context(
            user_id="u-hosp-auth", roles=("HOSPITAL_AUTHORIZER",),
            organization_id="org-hosp-1",
        )
        certified = emergency_service.certify_priority(
            context=authorizer, request_id=created["requestId"],
            priority_label="CRITICAL", now=now,
        )
        assert certified["clinicalPriority"] == "P1"
        assert certified["certifiedBy"] == "u-hosp-auth"

        detail = emergency_service.get_request(
            context=authorizer, request_id=created["requestId"]
        )
        assert detail["certifiedBy"] == "u-hosp-auth"
        assert detail["status"] == RequestStatus.HOSPITAL_CERTIFIED.value

    def test_a_suspended_hospital_cannot_certify(self, seeded, emergency_service, now):
        """Spec 6.3: a suspended hospital loses privileged capability immediately."""
        staff = make_context(
            user_id="u-hosp-staff", roles=("HOSPITAL_STAFF",), organization_id="org-hosp-1"
        )
        created = emergency_service.create_request(
            context=staff, blood_group="A+", component="PRBC", required_units=1,
            latitude=30.3398, longitude=76.3869, required_by=hours_ahead(6),
            contact_name="X", contact_phone="+91-0", consent_given=True, now=now,
        )

        suspended = make_context(
            user_id="u-hosp-susp-auth", roles=("HOSPITAL_AUTHORIZER",),
            organization_id="org-hosp-susp",
        )
        with pytest.raises(ForbiddenError) as exc:
            emergency_service.certify_priority(
                context=suspended, request_id=created["requestId"],
                priority_label="CRITICAL", now=now,
            )
        assert exc.value.details["organizationStatus"] == "SUSPENDED"


class TestScenario07_MatchingDiscoversFacilities:
    """7. The matching engine discovers suitable facilities and notifies providers."""

    def test_matching_uses_the_versioned_compatibility_reference(
        self, seeded, inventory_service, emergency_service, now
    ):
        # O- stock at fac-1, and A+ stock which is NOT compatible for an O- patient.
        add_stock(inventory_service, now, facility_id="fac-1", group="O-", units=6)
        add_stock(
            inventory_service, now, facility_id="fac-2", organization_id="org-bb-2",
            group="A+", units=50, actor="u-bb-other",
        )

        staff = make_context(
            user_id="u-hosp-staff", roles=("HOSPITAL_STAFF",), organization_id="org-hosp-1"
        )
        created = emergency_service.create_request(
            context=staff, blood_group="O-", component="PRBC", required_units=2,
            latitude=30.3398, longitude=76.3869, required_by=hours_ahead(10),
            contact_name="X", contact_phone="+91-0", consent_given=True, now=now,
        )
        authorizer = make_context(
            user_id="u-hosp-auth", roles=("HOSPITAL_AUTHORIZER",),
            organization_id="org-hosp-1",
        )
        emergency_service.certify_priority(
            context=authorizer, request_id=created["requestId"],
            priority_label="URGENT", now=now,
        )

        outcome = emergency_service.run_matching(
            context=authorizer, request_id=created["requestId"], now=now, radius_km=25
        )

        # An O- recipient may only receive O- red cells.
        assert outcome["compatibleDonorGroups"] == ["O-"]
        assert outcome["compatibilityRulesVersion"] == "1.0.0"
        assert outcome["compatibilityReviewStatus"] == "UNREVIEWED_SYNTHETIC"
        assert outcome["providersNotified"] >= 1

        matched_facilities = {c["facilityId"] for c in outcome["candidates"]}
        assert "fac-1" in matched_facilities
        # The A+ stock must never be offered to an O- patient.
        assert "fac-2" not in matched_facilities

    def test_an_unknown_combination_matches_nothing(
        self, seeded, emergency_service, now, monkeypatch
    ):
        """Fail-closed: no compatibility rule means no match, not a guess."""
        staff = make_context(
            user_id="u-hosp-staff", roles=("HOSPITAL_STAFF",), organization_id="org-hosp-1"
        )
        created = emergency_service.create_request(
            context=staff, blood_group="O-", component="PRBC", required_units=1,
            latitude=30.3398, longitude=76.3869, required_by=hours_ahead(6),
            contact_name="X", contact_phone="+91-0", consent_given=True, now=now,
        )
        authorizer = make_context(
            user_id="u-hosp-auth", roles=("HOSPITAL_AUTHORIZER",),
            organization_id="org-hosp-1",
        )
        emergency_service.certify_priority(
            context=authorizer, request_id=created["requestId"],
            priority_label="SCHEDULED", now=now,
        )

        monkeypatch.setattr(
            "services.emergency_service.compatible_donor_groups",
            lambda **kwargs: (),
        )
        outcome = emergency_service.run_matching(
            context=authorizer, request_id=created["requestId"], now=now
        )
        assert outcome["candidates"] == []
        assert outcome["reason"] == "NO_COMPATIBILITY_DATA"


class TestScenario08_ProviderResponsesDoNotDoubleCount:
    """8. Provider responses update tracking without double-counting stock."""

    def test_two_providers_offering_the_same_units_are_not_summed_into_supply(
        self, seeded, inventory_service, emergency_service, repos, now
    ):
        add_stock(inventory_service, now, facility_id="fac-1", group="O-", units=10)
        add_stock(
            inventory_service, now, facility_id="fac-2", organization_id="org-bb-2",
            group="O-", units=10, actor="u-bb-other",
        )

        staff = make_context(
            user_id="u-hosp-staff", roles=("HOSPITAL_STAFF",), organization_id="org-hosp-1"
        )
        created = emergency_service.create_request(
            context=staff, blood_group="O-", component="PRBC", required_units=4,
            latitude=30.3398, longitude=76.3869, required_by=hours_ahead(10),
            contact_name="X", contact_phone="+91-0", consent_given=True, now=now,
        )
        authorizer = make_context(
            user_id="u-hosp-auth", roles=("HOSPITAL_AUTHORIZER",),
            organization_id="org-hosp-1",
        )
        emergency_service.certify_priority(
            context=authorizer, request_id=created["requestId"],
            priority_label="URGENT", now=now,
        )
        emergency_service.run_matching(
            context=authorizer, request_id=created["requestId"], now=now, radius_km=25
        )

        # Record stock before any response, so the assertion afterwards proves
        # nothing moved rather than merely matching a hard-coded number.
        stock_before_1 = sum(b.available_units for b in repos.inventory.list_batches("fac-1")[0])
        stock_before_2 = sum(b.available_units for b in repos.inventory.list_batches("fac-2")[0])

        bb1 = make_context(
            user_id="u-bb-admin", roles=("BLOOD_BANK_ADMIN",), organization_id="org-bb-1"
        )
        bb2 = make_context(
            user_id="u-bb-other", roles=("BLOOD_BANK_ADMIN",), organization_id="org-bb-2"
        )

        first = emergency_service.submit_response(
            context=bb1, request_id=created["requestId"],
            response_type="ACCEPTED", units_offered=4, now=now,
        )
        second = emergency_service.submit_response(
            context=bb2, request_id=created["requestId"],
            response_type="ACCEPTED", units_offered=4, now=now,
        )

        # Both offers are recorded in full.
        assert first["tally"]["accepted"] == 1
        assert second["tally"]["accepted"] == 2
        assert second["tally"]["totalUnitsOffered"] == 8

        # And no inventory moved: an offer is willingness, not a reservation.
        batches_1, _ = repos.inventory.list_batches("fac-1")
        batches_2, _ = repos.inventory.list_batches("fac-2")
        assert sum(b.available_units for b in batches_1) == stock_before_1 == 10
        assert sum(b.available_units for b in batches_2) == stock_before_2 == 10

        detail = emergency_service.get_request(
            context=authorizer, request_id=created["requestId"]
        )
        assert all(r["isReservation"] is False for r in detail["responses"])

    def test_a_provider_cannot_respond_twice(
        self, seeded, inventory_service, emergency_service, now
    ):
        add_stock(inventory_service, now, facility_id="fac-1", group="O-", units=10)
        staff = make_context(
            user_id="u-hosp-staff", roles=("HOSPITAL_STAFF",), organization_id="org-hosp-1"
        )
        created = emergency_service.create_request(
            context=staff, blood_group="O-", component="PRBC", required_units=2,
            latitude=30.3398, longitude=76.3869, required_by=hours_ahead(10),
            contact_name="X", contact_phone="+91-0", consent_given=True, now=now,
        )
        authorizer = make_context(
            user_id="u-hosp-auth", roles=("HOSPITAL_AUTHORIZER",),
            organization_id="org-hosp-1",
        )
        emergency_service.certify_priority(
            context=authorizer, request_id=created["requestId"],
            priority_label="URGENT", now=now,
        )
        emergency_service.run_matching(
            context=authorizer, request_id=created["requestId"], now=now, radius_km=25
        )

        bb1 = make_context(
            user_id="u-bb-admin", roles=("BLOOD_BANK_ADMIN",), organization_id="org-bb-1"
        )
        emergency_service.submit_response(
            context=bb1, request_id=created["requestId"],
            response_type="ACCEPTED", units_offered=2, now=now,
        )
        # The second response fails its ConditionExpression, which surfaces as a
        # concurrency conflict rather than being silently accepted.
        with pytest.raises(ConcurrentModificationError):
            emergency_service.submit_response(
                context=bb1, request_id=created["requestId"],
                response_type="REJECTED", units_offered=0, now=now,
            )

    def test_a_provider_that_was_not_asked_cannot_respond(
        self, seeded, inventory_service, emergency_service, now
    ):
        add_stock(inventory_service, now, facility_id="fac-1", group="O-", units=10)
        staff = make_context(
            user_id="u-hosp-staff", roles=("HOSPITAL_STAFF",), organization_id="org-hosp-1"
        )
        created = emergency_service.create_request(
            context=staff, blood_group="O-", component="PRBC", required_units=1,
            latitude=30.3398, longitude=76.3869, required_by=hours_ahead(10),
            contact_name="X", contact_phone="+91-0", consent_given=True, now=now,
        )
        rogue = make_context(
            user_id="u-camp-org", roles=("BLOOD_BANK_ADMIN",), organization_id="org-camp-1"
        )
        with pytest.raises(ForbiddenError) as exc:
            emergency_service.submit_response(
                context=rogue, request_id=created["requestId"],
                response_type="ACCEPTED", units_offered=1, now=now,
            )
        assert exc.value.details["rule"] == "PROVIDER_NOT_NOTIFIED"


class TestScenario09_UnauthorizedActionIsDenied:
    """9. An unauthorized user attempts a privileged action and is denied."""

    def test_a_donor_cannot_verify_their_own_donation(self, seeded, camp_service, now):
        organizer = make_context(
            user_id="u-camp-org", roles=("CAMP_ORGANIZER",), organization_id="org-camp-1"
        )
        admin = make_context(user_id="u-admin", roles=("PLATFORM_ADMIN",), organization_id=None)
        donor = make_context(user_id="u-donor-1", roles=("DONOR",), organization_id=None)

        camp = camp_service.create_camp(
            context=organizer, name="Self Camp", description="scenario 9",
            latitude=30.3398, longitude=76.3869, address="1", city="Patiala",
            starts_at=hours_ahead(26), ends_at=hours_ahead(34), capacity=5, now=now,
        )
        camp_id = camp["campId"]
        camp_service.approve_camp(context=admin, camp_id=camp_id, approve=True, now=now)
        camp_service.register(context=donor, camp_id=camp_id, now=now)
        camp_service.check_in(context=organizer, camp_id=camp_id, donor_id="u-donor-1", now=now)
        recorded = camp_service.record_donation(
            context=organizer, camp_id=camp_id, donor_id="u-donor-1",
            blood_group="O-", component="WHOLE_BLOOD", units=1, now=now,
        )

        # The donor is even granted the verify role here, and is still refused.
        self_verifier = make_context(
            user_id="u-donor-1", roles=("DONOR", "CAMP_STAFF"), organization_id="org-camp-1"
        )
        with pytest.raises(ForbiddenError) as exc:
            camp_service.verify_donation(
                context=self_verifier, camp_id=camp_id, donor_id="u-donor-1",
                donation_id=recorded["donationId"], now=now,
            )
        assert exc.value.details["rule"] == "SELF_VERIFICATION_FORBIDDEN"

    def test_an_organizer_cannot_manage_another_organizations_camp(
        self, seeded, camp_service, now
    ):
        organizer = make_context(
            user_id="u-camp-org", roles=("CAMP_ORGANIZER",), organization_id="org-camp-1"
        )
        camp = camp_service.create_camp(
            context=organizer, name="Mine", description="x",
            latitude=30.3398, longitude=76.3869, address="1", city="Patiala",
            starts_at=hours_ahead(30), ends_at=hours_ahead(38), capacity=5, now=now,
        )
        intruder = make_context(
            user_id="u-bb-admin", roles=("CAMP_ORGANIZER",), organization_id="org-bb-1"
        )
        with pytest.raises(ForbiddenError):
            camp_service.cancel_camp(
                context=intruder, camp_id=camp["campId"], reason="not mine", now=now
            )

    def test_duplicate_camp_registration_is_refused(self, seeded, camp_service, now):
        organizer = make_context(
            user_id="u-camp-org", roles=("CAMP_ORGANIZER",), organization_id="org-camp-1"
        )
        admin = make_context(user_id="u-admin", roles=("PLATFORM_ADMIN",), organization_id=None)
        donor = make_context(user_id="u-donor-1", roles=("DONOR",), organization_id=None)

        camp = camp_service.create_camp(
            context=organizer, name="Dup Camp", description="x",
            latitude=30.3398, longitude=76.3869, address="1", city="Patiala",
            starts_at=hours_ahead(30), ends_at=hours_ahead(38), capacity=5, now=now,
        )
        camp_service.approve_camp(
            context=admin, camp_id=camp["campId"], approve=True, now=now
        )
        camp_service.register(context=donor, camp_id=camp["campId"], now=now)

        with pytest.raises((DuplicateError, ValidationError)):
            camp_service.register(context=donor, camp_id=camp["campId"], now=now)

    def test_a_camp_cannot_be_oversubscribed(self, seeded, camp_service, now):
        """The capacity transaction, executed for real."""
        organizer = make_context(
            user_id="u-camp-org", roles=("CAMP_ORGANIZER",), organization_id="org-camp-1"
        )
        admin = make_context(user_id="u-admin", roles=("PLATFORM_ADMIN",), organization_id=None)

        camp = camp_service.create_camp(
            context=organizer, name="Tiny Camp", description="capacity one",
            latitude=30.3398, longitude=76.3869, address="1", city="Patiala",
            starts_at=hours_ahead(30), ends_at=hours_ahead(38), capacity=1, now=now,
        )
        camp_id = camp["campId"]
        camp_service.approve_camp(context=admin, camp_id=camp_id, approve=True, now=now)

        first = make_context(user_id="u-donor-1", roles=("DONOR",), organization_id=None)
        second = make_context(user_id="u-donor-2", roles=("DONOR",), organization_id=None)

        camp_service.register(context=first, camp_id=camp_id, now=now)
        with pytest.raises((CapacityExceededError, ValidationError)):
            camp_service.register(context=second, camp_id=camp_id, now=now)


class TestScenario10_MappingFailureDoesNotBreakDiscovery:
    """10. An external mapping or routing failure does not break facility
    discovery."""

    def test_discovery_survives_a_routing_outage(
        self, seeded, inventory_service, discovery_service, now
    ):
        add_stock(inventory_service, now, units=5)

        outcome = discovery_service.search_facilities(
            latitude=30.3398, longitude=76.3869, now=now,
            radius_km=10, blood_group="O-", component="PRBC", requested_units=1,
        )
        assert outcome["results"], "the facility list must survive without routing"
        row = outcome["results"][0]
        assert row["straightLineKm"] is not None
        assert row["roadKm"] is None
        assert row["routingAvailable"] is False
        assert row["contactPhone"] is not None or "contactPhone" in row

    def test_a_route_request_reports_unavailable_rather_than_guessing(
        self, seeded, discovery_service
    ):
        from domain.geo import Coordinates

        result = discovery_service.route_to_facility(
            origin=Coordinates(30.3398, 76.3869), facility_id="fac-1"
        )
        assert result["routingAvailable"] is False
        assert result["roadKm"] is None
        assert result["etaMinutes"] is None
        assert result["straightLineKm"] is not None
        # The straight-line figure must never be presented as a driving distance.
        assert "straight-line" in result["notice"].lower()

    def test_geocoding_failure_is_reported_not_faked(self, seeded, discovery_service):
        outcome = discovery_service.geocode(query="zzzz-nonexistent-place")
        assert outcome["results"] == []
        assert outcome["providerAvailable"] is True
