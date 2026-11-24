"""Feature 3 -- donation camps and donor engagement.

The four-state separation the spec insists on is visible in the method names:
``register`` → ``check_in`` → ``record_donation`` → ``verify_donation``. Each is
a separate authorized action with its own audit record, and the impact ledger is
credited only by the last one.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from ulid import ULID

from appcore.context import RequestContext
from appcore.logging import get_logger
from domain.camps import (
    CampStatus,
    DonationStatus,
    assert_camp_transition,
    assert_can_register,
    assert_can_verify_donation,
    derive_camp_status,
    should_send_reminder,
)
from domain.clock import parse_iso, to_iso
from domain.errors import ForbiddenError, NotFoundError, ValidationError
from domain.geo import Coordinates
from domain.impact import (
    MILESTONE_LABELS,
    POINTS_PER_VERIFIED_DONATION,
    LedgerEntry,
    compute_score,
    donation_interval_advice,
    earned_milestones,
    newly_earned_milestones,
    next_milestone,
    verified_donation_count,
)

MAX_CAMP_CAPACITY = 2000


class CampService:
    def __init__(self, *, camp_repository, donation_repository, identity_repository,
                 notification_service, audit_repository):
        self._camps = camp_repository
        self._donations = donation_repository
        self._identity = identity_repository
        self._notifications = notification_service
        self._audit = audit_repository

    # --- camp management ---

    def create_camp(
        self,
        *,
        context: RequestContext,
        name: str,
        description: str,
        latitude: float,
        longitude: float,
        address: str,
        city: str,
        starts_at: datetime,
        ends_at: datetime,
        capacity: int,
        now: datetime,
        registration_deadline: datetime | None = None,
        demo: bool = False,
    ) -> dict:
        log = get_logger(__name__, context)
        if not name.strip():
            raise ValidationError("camp name is required")
        if capacity <= 0 or capacity > MAX_CAMP_CAPACITY:
            raise ValidationError(
                f"capacity must be between 1 and {MAX_CAMP_CAPACITY}",
                details={"maximum": MAX_CAMP_CAPACITY},
            )
        if ends_at <= starts_at:
            raise ValidationError("the camp must end after it starts")
        if starts_at <= now:
            raise ValidationError("a camp must start in the future")
        if registration_deadline and registration_deadline > starts_at:
            raise ValidationError("the registration deadline cannot be after the camp starts")
        try:
            Coordinates(latitude, longitude)
        except ValueError as exc:
            raise ValidationError(str(exc)) from None

        if context.organization_id is None:
            raise ForbiddenError("organizing a camp requires organization membership")

        camp_id = str(ULID())
        camp = self._camps.create_camp(
            {
                "campId": camp_id,
                "name": name.strip(),
                "description": description,
                "organizerOrganizationId": context.organization_id,
                "organizerUserId": context.actor_id,
                "latitude": latitude,
                "longitude": longitude,
                "address": address,
                "city": city,
                "startsAt": to_iso(starts_at),
                "endsAt": to_iso(ends_at),
                "registrationDeadline": to_iso(registration_deadline or starts_at),
                "capacity": capacity,
                "registeredCount": 0,
                # New camps require approval before they are discoverable.
                "status": CampStatus.PENDING_APPROVAL.value,
                "createdAt": to_iso(now),
                "demoData": demo,
            },
            )
        self._audit.record(
            actor_id=context.actor_id,
            actor_role=",".join(context.principal.roles),
            action="CAMP_CREATED",
            resource_type="CAMP",
            resource_id=camp_id,
            organization_id=context.organization_id,
            correlation_id=context.correlation_id,
            occurred_at=now,
            after={"name": name, "capacity": capacity, "startsAt": to_iso(starts_at)},
        )
        log.info("camp created", event="camp.created", campId=camp_id)
        return self._present_camp(camp)

    def approve_camp(self, *, context: RequestContext, camp_id: str, approve: bool,
                     now: datetime, reason: str | None = None) -> dict:
        camp = self._require_camp(camp_id)
        current = CampStatus(camp["status"])
        target = CampStatus.UPCOMING if approve else CampStatus.REJECTED
        assert_camp_transition(current, target)

        self._camps.set_status(
            camp_id, status=target.value, starts_at=camp["startsAt"],
            actor_id=context.actor_id, now=now, reason=reason,
        )
        self._audit.record(
            actor_id=context.actor_id,
            actor_role=",".join(context.principal.roles),
            action="CAMP_APPROVED" if approve else "CAMP_REJECTED",
            resource_type="CAMP",
            resource_id=camp_id,
            organization_id=camp.get("organizerOrganizationId"),
            correlation_id=context.correlation_id,
            occurred_at=now,
            before={"status": current.value},
            after={"status": target.value},
            metadata={"reason": reason},
        )
        return {"campId": camp_id, "status": target.value}

    def cancel_camp(self, *, context: RequestContext, camp_id: str, reason: str,
                    now: datetime) -> dict:
        """Cancel a camp and tell everyone who registered.

        Notifying registrants is part of cancelling, not a separate step --
        the spec requires camp cancellation updates to reach opted-in users.
        """
        camp = self._require_camp(camp_id)
        self._assert_camp_authority(context, camp)
        current = CampStatus(camp["status"])
        assert_camp_transition(current, CampStatus.CANCELLED)

        self._camps.set_status(
            camp_id, status=CampStatus.CANCELLED.value, starts_at=camp["startsAt"],
            actor_id=context.actor_id, now=now, reason=reason,
        )

        registrants = [
            item["userId"]
            for item in self._camps.list_camp_partition(camp_id)
            if item.get("entityType") == "REGISTRATION" and item.get("status") == "REGISTERED"
        ]
        outcomes = self._notifications.notify_many(
            user_ids=registrants,
            category="CAMP_CANCELLED",
            subject=f"Camp cancelled: {camp['name']}",
            body=(
                f"The blood donation camp '{camp['name']}' scheduled for "
                f"{camp['startsAt']} has been cancelled.\n\nReason: {reason}"
            ),
            now=now,
            metadata={"campId": camp_id},
            dedupe_prefix=f"camp-cancelled#{camp_id}",
        )
        self._audit.record(
            actor_id=context.actor_id,
            actor_role=",".join(context.principal.roles),
            action="CAMP_CANCELLED",
            resource_type="CAMP",
            resource_id=camp_id,
            organization_id=camp.get("organizerOrganizationId"),
            correlation_id=context.correlation_id,
            occurred_at=now,
            metadata={"reason": reason, "notified": len(registrants)},
        )
        return {
            "campId": camp_id,
            "status": CampStatus.CANCELLED.value,
            "registrantsNotified": sum(1 for o in outcomes if o.any_delivered),
            "registrantsTotal": len(registrants),
        }

    def get_camp(self, *, camp_id: str, now: datetime, context=None) -> dict:
        items = self._camps.list_camp_partition(camp_id)
        if not items:
            raise NotFoundError("camp not found", details={"campId": camp_id})
        meta = next((i for i in items if i.get("SK") == "META"), None)
        if meta is None:
            raise NotFoundError("camp not found", details={"campId": camp_id})

        registrations = [i for i in items if i.get("entityType") == "REGISTRATION"]
        presented = self._present_camp(meta)
        presented["derivedStatus"] = derive_camp_status(
            current=CampStatus(meta["status"]),
            starts_at=parse_iso(meta["startsAt"]),
            ends_at=parse_iso(meta["endsAt"]),
            now=now,
        ).value
        presented["registrationCount"] = len(
            [r for r in registrations if r.get("status") == "REGISTERED"]
        )
        presented["checkedInCount"] = len(
            [r for r in registrations if r.get("attendanceStatus") == "CHECKED_IN"]
        )

        # Only staff see who registered.
        if context is not None and (
            self._camps.is_camp_staff(camp_id, context.actor_id)
            or meta.get("organizerUserId") == context.actor_id
            or "PLATFORM_ADMIN" in context.principal.roles
        ):
            presented["registrations"] = [
                {
                    "userId": r["userId"],
                    "status": r.get("status"),
                    "attendanceStatus": r.get("attendanceStatus"),
                    "registeredAt": r.get("registeredAt"),
                    "checkedInAt": r.get("checkedInAt"),
                }
                for r in registrations
            ]
        return presented

    def search_camps(self, *, latitude: float, longitude: float, radius_km: float,
                     now: datetime) -> dict:
        """Discovery is not limited by the notification radius (spec 5.4).

        It *is* limited by the camp geo index's single precision. Rather than
        apply that limit silently -- which made a 100 km search look like a
        region with one camp in it -- the effective radius is returned so the
        interface can say what was actually searched.
        """
        from repositories.camp_repo import CAMP_SEARCH_MAX_RADIUS_KM

        effective = min(radius_km, CAMP_SEARCH_MAX_RADIUS_KM)
        camps = self._camps.find_nearby_upcoming(
            latitude=latitude, longitude=longitude, radius_km=radius_km, now=now
        )
        payload = {
            "origin": {"latitude": latitude, "longitude": longitude},
            "radiusKm": radius_km,
            "effectiveRadiusKm": effective,
            "results": [self._present_camp(c) for c in camps],
            "notice": (
                "Camp search is not restricted by your notification radius. "
                "You may search any area."
            ),
        }
        if effective < radius_km:
            payload["notice"] = (
                f"Camp discovery currently searches up to "
                f"{effective:.0f} km; results beyond that are not included."
            )
        return payload

    def list_organizer_camps(self, *, context: RequestContext) -> list[dict]:
        if context.organization_id is None:
            return []
        camps = self._camps.list_by_organizer(context.organization_id)
        return [self._present_camp(c) for c in camps if c.get("entityType") == "CAMP"]

    # --- registration and attendance ---

    def register(self, *, context: RequestContext, camp_id: str, now: datetime) -> dict:
        log = get_logger(__name__, context)
        camp = self._require_camp(camp_id)
        existing = self._camps.get_registration(camp_id, context.actor_id)

        assert_can_register(
            camp_status=CampStatus(camp["status"]),
            registration_deadline=parse_iso(camp.get("registrationDeadline")),
            starts_at=parse_iso(camp["startsAt"]),
            capacity=int(camp["capacity"]),
            registered_count=int(camp.get("registeredCount", 0)),
            already_registered=existing is not None and existing.get("status") == "REGISTERED",
            now=now,
        )

        # The transaction is authoritative for the final seat, not the check above.
        registration = self._camps.register_atomically(
            camp_id=camp_id,
            user_id=context.actor_id,
            capacity=int(camp["capacity"]),
            now=now,
            registration={"campName": camp.get("name"), "campStartsAt": camp.get("startsAt")},
        )

        self._audit.record(
            actor_id=context.actor_id,
            actor_role=",".join(context.principal.roles),
            action="CAMP_REGISTERED",
            resource_type="CAMP_REGISTRATION",
            resource_id=f"{camp_id}#{context.actor_id}",
            correlation_id=context.correlation_id,
            occurred_at=now,
        )

        last = self._last_verified_donation_at(context.actor_id)
        advice = donation_interval_advice(last, now)

        self._notifications.notify(
            user_id=context.actor_id,
            category="CAMP_ANNOUNCEMENT",
            subject=f"Registered: {camp['name']}",
            body=(
                f"You are registered for '{camp['name']}' on {camp['startsAt']}.\n\n"
                f"{advice.message}"
            ),
            now=now,
            metadata={"campId": camp_id},
            dedupe_key=f"camp-registered#{camp_id}#{context.actor_id}",
        )
        log.info("camp registration", event="camp.registered", campId=camp_id)

        return {
            "campId": camp_id,
            "userId": context.actor_id,
            "status": registration["status"],
            "registeredAt": registration["registeredAt"],
            "intervalAdvice": {
                "eligibleByInterval": advice.eligible_by_interval,
                "daysSinceLast": advice.days_since_last,
                "message": advice.message,
            },
            "notice": (
                "Registration is not attendance and does not confirm medical "
                "eligibility. Camp staff will assess you on the day."
            ),
        }

    def cancel_registration(self, *, context: RequestContext, camp_id: str,
                            now: datetime) -> dict:
        registration = self._camps.get_registration(camp_id, context.actor_id)
        if registration is None:
            raise NotFoundError("you are not registered for this camp")
        result = self._camps.cancel_registration(
            camp_id=camp_id, user_id=context.actor_id, now=now
        )
        self._audit.record(
            actor_id=context.actor_id,
            actor_role=",".join(context.principal.roles),
            action="CAMP_REGISTRATION_CANCELLED",
            resource_type="CAMP_REGISTRATION",
            resource_id=f"{camp_id}#{context.actor_id}",
            correlation_id=context.correlation_id,
            occurred_at=now,
        )
        return result

    def my_registrations(self, *, context: RequestContext) -> list[dict]:
        return self._camps.list_registrations_for_user(context.actor_id)

    def assign_staff(self, *, context: RequestContext, camp_id: str, user_id: str,
                     now: datetime) -> dict:
        camp = self._require_camp(camp_id)
        self._assert_camp_authority(context, camp)
        if self._identity.get_user(user_id) is None:
            raise NotFoundError("user not found", details={"userId": user_id})
        item = self._camps.assign_staff(
            camp_id=camp_id, user_id=user_id, assigned_by=context.actor_id, now=now
        )
        self._audit.record(
            actor_id=context.actor_id,
            actor_role=",".join(context.principal.roles),
            action="CAMP_STAFF_ASSIGNED",
            resource_type="CAMP",
            resource_id=camp_id,
            organization_id=camp.get("organizerOrganizationId"),
            correlation_id=context.correlation_id,
            occurred_at=now,
            after={"staffUserId": user_id},
        )
        return {"campId": camp_id, "userId": user_id, "assignedAt": item["assignedAt"]}

    def check_in(self, *, context: RequestContext, camp_id: str, donor_id: str,
                 now: datetime) -> dict:
        """Attendance. Separate from registration and from donation (spec 5.3)."""
        camp = self._require_camp(camp_id)
        self._assert_camp_staff(context, camp_id, camp)

        registration = self._camps.get_registration(camp_id, donor_id)
        if registration is None:
            raise NotFoundError("this donor is not registered for this camp")
        if registration.get("attendanceStatus") == "CHECKED_IN":
            raise ValidationError(
                "this donor is already checked in",
                details={"rule": "DUPLICATE_CHECKIN"},
            )

        updated = self._camps.check_in(
            camp_id=camp_id, user_id=donor_id, actor_id=context.actor_id, now=now
        )
        self._audit.record(
            actor_id=context.actor_id,
            actor_role=",".join(context.principal.roles),
            action="CAMP_CHECKED_IN",
            resource_type="CAMP_REGISTRATION",
            resource_id=f"{camp_id}#{donor_id}",
            organization_id=camp.get("organizerOrganizationId"),
            correlation_id=context.correlation_id,
            occurred_at=now,
        )
        return {
            "campId": camp_id,
            "donorId": donor_id,
            "attendanceStatus": updated.get("attendanceStatus"),
            "checkedInAt": updated.get("checkedInAt"),
            "notice": "Check-in records attendance only. It does not record a donation.",
        }

    def record_donation(self, *, context: RequestContext, camp_id: str, donor_id: str,
                        blood_group: str, component: str, units: int, now: datetime) -> dict:
        """Record that a donation took place. Still unverified at this point."""
        camp = self._require_camp(camp_id)
        self._assert_camp_staff(context, camp_id, camp)

        registration = self._camps.get_registration(camp_id, donor_id)
        if registration is None:
            raise NotFoundError("this donor is not registered for this camp")
        if registration.get("attendanceStatus") != "CHECKED_IN":
            raise ValidationError(
                "a donation cannot be recorded before the donor is checked in",
                details={"rule": "ATTENDANCE_REQUIRED"},
            )
        if units <= 0:
            raise ValidationError("units must be at least one")

        from domain.blood import parse_component, parse_group

        donation_id = str(ULID())
        donation = self._donations.record_donation(
            {
                "donationId": donation_id,
                "donorId": donor_id,
                "campId": camp_id,
                "bloodGroup": parse_group(blood_group).value,
                "component": parse_component(component).value,
                "units": units,
                "recordedBy": context.actor_id,
            },
            now=now,
        )
        self._audit.record(
            actor_id=context.actor_id,
            actor_role=",".join(context.principal.roles),
            action="DONATION_RECORDED",
            resource_type="DONATION",
            resource_id=donation_id,
            organization_id=camp.get("organizerOrganizationId"),
            correlation_id=context.correlation_id,
            occurred_at=now,
            after={"donorId": donor_id, "units": units},
        )
        return {
            "donationId": donation_id,
            "status": donation["status"],
            "notice": (
                "Recorded but not yet verified. Impact points are awarded only "
                "after independent verification by authorized staff."
            ),
        }

    def verify_donation(self, *, context: RequestContext, camp_id: str, donor_id: str,
                        donation_id: str, now: datetime) -> dict:
        """Verify a donation and credit the impact ledger exactly once.

        The self-verification rule is checked here in the service, not only in
        the permission layer: holding DONATION_VERIFY does not entitle someone
        to verify their own donation.
        """
        log = get_logger(__name__, context)
        camp = self._require_camp(camp_id)
        is_staff = self._camps.is_camp_staff(camp_id, context.actor_id) or (
            camp.get("organizerUserId") == context.actor_id
        )

        donation = self._donations.get_donation(donor_id, donation_id)
        if donation is None:
            raise NotFoundError("donation not found", details={"donationId": donation_id})

        assert_can_verify_donation(
            verifier_id=context.actor_id,
            donor_id=donor_id,
            verifier_is_camp_staff=is_staff,
            donation_status=DonationStatus(donation.get("status", "RECORDED")),
        )

        previous_count = verified_donation_count(self._ledger_entries(donor_id))

        result = self._donations.verify_donation_and_credit(
            donor_id=donor_id,
            donation_id=donation_id,
            verifier_id=context.actor_id,
            points=POINTS_PER_VERIFIED_DONATION,
            now=now,
        )

        entries = self._ledger_entries(donor_id)
        new_count = verified_donation_count(entries)
        gained = newly_earned_milestones(previous_count, new_count)

        self._audit.record(
            actor_id=context.actor_id,
            actor_role=",".join(context.principal.roles),
            action="DONATION_VERIFIED",
            resource_type="DONATION",
            resource_id=donation_id,
            organization_id=camp.get("organizerOrganizationId"),
            correlation_id=context.correlation_id,
            occurred_at=now,
            after={"donorId": donor_id, "pointsAwarded": POINTS_PER_VERIFIED_DONATION},
        )

        if gained:
            labels = ", ".join(MILESTONE_LABELS[m] for m in gained)
            self._notifications.notify(
                user_id=donor_id,
                category="ACCOUNT_NOTICE",
                subject=f"Milestone reached: {labels}",
                body=(
                    f"Your donation has been verified. You have reached: {labels}.\n\n"
                    "Thank you for donating. This is a recognition record only and is "
                    "not a medical or government document."
                ),
                now=now,
                metadata={"donationId": donation_id},
                dedupe_key=f"milestone#{donor_id}#{new_count}",
                force_transactional=True,
            )

        log.info("donation verified", event="donation.verified",
                 donationId=donation_id, donorId=donor_id)

        return {
            **result,
            "impactScore": compute_score(entries),
            "verifiedDonations": new_count,
            "newMilestones": [MILESTONE_LABELS[m] for m in gained],
            "notice": "Impact points are credited once per verified donation.",
        }

    # --- donor-facing ---

    def donor_profile(self, *, context: RequestContext, now: datetime) -> dict:
        entries = self._ledger_entries(context.actor_id)
        count = verified_donation_count(entries)
        upcoming = next_milestone(count)
        last = self._last_verified_donation_at(context.actor_id)
        advice = donation_interval_advice(last, now)
        return {
            "userId": context.actor_id,
            "impactScore": compute_score(entries),
            "verifiedDonations": count,
            "milestones": [MILESTONE_LABELS[m] for m in earned_milestones(count)],
            "nextMilestone": (
                {"name": MILESTONE_LABELS[upcoming[0]], "donationsRemaining": upcoming[1]}
                if upcoming
                else None
            ),
            "lastVerifiedDonationAt": to_iso(last),
            "intervalAdvice": {
                "eligibleByInterval": advice.eligible_by_interval,
                "daysSinceLast": advice.days_since_last,
                "nextEligibleDate": to_iso(advice.next_eligible_date),
                "message": advice.message,
            },
            "pointsPerDonation": POINTS_PER_VERIFIED_DONATION,
            "notice": (
                "Impact Score is a non-monetary recognition metric. It does not "
                "indicate medical eligibility to donate."
            ),
        }

    def donation_history(self, *, context: RequestContext, user_id: str | None = None) -> list[dict]:
        target = user_id or context.actor_id
        if target != context.actor_id and "PLATFORM_ADMIN" not in context.principal.roles:
            raise ForbiddenError("donation history is private to the donor")
        return self._donations.list_donations(target)

    def certificate_data(self, *, context: RequestContext, donation_id: str) -> dict:
        """Certificate payload, generated from verified records only.

        Private to the donor and explicitly labelled as recognition -- not a
        medical certificate, government document or proof of eligibility.
        """
        donation = self._donations.get_donation(context.actor_id, donation_id)
        if donation is None:
            raise NotFoundError("donation not found", details={"donationId": donation_id})
        if donation.get("status") != DonationStatus.VERIFIED.value:
            raise ValidationError(
                "certificates are issued only for verified donations",
                details={"status": donation.get("status")},
            )
        user = self._identity.get_user(context.actor_id) or {}
        camp = self._camps.get_camp(donation["campId"]) or {}
        return {
            "certificateId": f"CERT-{donation_id}",
            "donorName": user.get("displayName", "Donor"),
            "donationId": donation_id,
            "campName": camp.get("name"),
            "donatedAt": donation.get("recordedAt"),
            "verifiedAt": donation.get("verifiedAt"),
            "units": donation.get("units"),
            "component": donation.get("component"),
            "documentType": "RECOGNITION_CERTIFICATE",
            "disclaimer": (
                "This is a recognition document issued by LifeLink. It is not a "
                "medical certificate, not a government document, and not proof of "
                "medical eligibility to donate."
            ),
        }

    # --- reminders ---

    def send_due_reminders(self, *, now: datetime, window_minutes: int = 10,
                           context=None) -> dict:
        """Scheduled reminder job (spec 5.5).

        Every precondition is re-checked immediately before each send, so a camp
        cancelled after a reminder was scheduled produces no reminder.
        """
        log = get_logger(__name__, context)
        sent = 0
        skipped = 0

        for offset_label, hours in (("24H", 24), ("2H", 2)):
            target_start_low = now + timedelta(hours=hours) - timedelta(minutes=window_minutes)
            target_start_high = now + timedelta(hours=hours) + timedelta(minutes=window_minutes)

            for camp in self._upcoming_camps_between(target_start_low, target_start_high):
                camp_id = camp["campId"]
                registrations = [
                    i
                    for i in self._camps.list_camp_partition(camp_id)
                    if i.get("entityType") == "REGISTRATION"
                ]
                for registration in registrations:
                    user_id = registration["userId"]
                    prefs = self._notifications.get_preferences(user_id)
                    scheduled_for = parse_iso(camp["startsAt"]) - timedelta(hours=hours)
                    dedupe = f"camp-reminder#{camp_id}#{offset_label}#{user_id}"

                    allowed = should_send_reminder(
                        camp_status=CampStatus(camp["status"]),
                        registration_status=self._registration_status(registration),
                        notifications_enabled=bool(prefs.get("campNotifications", True)),
                        consent_given=bool(prefs.get("consentGiven", False)),
                        already_sent=False,  # the dedupe marker is the real guard
                        scheduled_for=scheduled_for,
                        now=now,
                        tolerance_minutes=window_minutes * 2,
                    )
                    if not allowed:
                        skipped += 1
                        continue

                    outcome = self._notifications.notify(
                        user_id=user_id,
                        category="CAMP_REMINDER",
                        subject=f"Reminder: {camp['name']} in {hours} hours",
                        body=(
                            f"'{camp['name']}' starts at {camp['startsAt']}.\n"
                            f"Location: {camp.get('address')}, {camp.get('city')}\n\n"
                            "Please bring photo identification. Camp staff will assess "
                            "your eligibility on the day."
                        ),
                        now=now,
                        metadata={"campId": camp_id, "reminder": offset_label},
                        dedupe_key=dedupe,
                    )
                    if outcome.suppressed:
                        skipped += 1
                    else:
                        sent += 1

        log.info("reminder sweep complete", event="camp.reminders.swept",
                 sent=sent, skipped=skipped)
        return {"sent": sent, "skipped": skipped, "sweptAt": to_iso(now)}

    def notify_nearby_donors(self, *, camp_id: str, now: datetime,
                             candidate_user_ids: list[str], context=None) -> dict:
        """Announce an approved camp to opted-in donors.

        The caller supplies candidates (matched on each user's own notification
        radius, default 10 km per spec 5.4). Consent and category preferences are
        re-checked per user inside the notification service.
        """
        camp = self._require_camp(camp_id)
        if camp["status"] not in (CampStatus.UPCOMING.value, CampStatus.ONGOING.value):
            return {"notified": 0, "reason": "CAMP_NOT_ANNOUNCEABLE"}

        outcomes = self._notifications.notify_many(
            user_ids=candidate_user_ids,
            category="CAMP_ANNOUNCEMENT",
            subject=f"Blood donation camp near you: {camp['name']}",
            body=(
                f"'{camp['name']}' is scheduled for {camp['startsAt']} at "
                f"{camp.get('address')}, {camp.get('city')}.\n\n"
                "You can register in the LifeLink app."
            ),
            now=now,
            metadata={"campId": camp_id},
            dedupe_prefix=f"camp-announce#{camp_id}",
        )
        return {
            "campId": camp_id,
            "candidates": len(candidate_user_ids),
            "notified": sum(1 for o in outcomes if o.any_delivered),
            "suppressed": sum(1 for o in outcomes if o.suppressed),
        }

    # --- helpers ---

    def _require_camp(self, camp_id: str) -> dict:
        camp = self._camps.get_camp(camp_id)
        if camp is None:
            raise NotFoundError("camp not found", details={"campId": camp_id})
        return camp

    def _assert_camp_authority(self, context: RequestContext, camp: dict) -> None:
        """Organizers may manage only camps they are authorized to manage (spec 5.7)."""
        if "PLATFORM_ADMIN" in context.principal.roles:
            return
        if camp.get("organizerOrganizationId") != context.organization_id:
            raise ForbiddenError("this camp belongs to another organization")

    def _assert_camp_staff(self, context: RequestContext, camp_id: str, camp: dict) -> None:
        if "PLATFORM_ADMIN" in context.principal.roles:
            return
        if camp.get("organizerUserId") == context.actor_id:
            return
        if not self._camps.is_camp_staff(camp_id, context.actor_id):
            raise ForbiddenError(
                "you are not assigned to this camp",
                details={"rule": "STAFF_SCOPED_TO_CAMP"},
            )

    def _ledger_entries(self, user_id: str) -> list[LedgerEntry]:
        return [
            LedgerEntry(
                donation_id=row["donationId"],
                donor_id=row["donorId"],
                points=int(row["points"]),
                reason=row.get("reason", "VERIFIED_DONATION"),
                occurred_at=parse_iso(row["occurredAt"]),
            )
            for row in self._donations.list_ledger(user_id)
        ]

    def _last_verified_donation_at(self, user_id: str) -> datetime | None:
        verified = [
            parse_iso(d.get("verifiedAt"))
            for d in self._donations.list_donations(user_id)
            if d.get("status") == DonationStatus.VERIFIED.value and d.get("verifiedAt")
        ]
        return max(verified) if verified else None

    def _upcoming_camps_between(self, low: datetime, high: datetime) -> list[dict]:
        """Camps starting inside a window.

        The reminder job runs per organization rather than scanning every camp,
        which keeps this bounded. A production-scale system would use the
        GSI4-reminder index directly; that index is defined and is used by the
        scheduled worker.
        """
        from boto3.dynamodb.conditions import Key

        return [
            c
            for c in self._camps.query_all(
                key_condition=Key("GSI4PK").eq("REMINDER#WINDOW")
                & Key("GSI4SK").between(to_iso(low), to_iso(high)),
                index_name="GSI4-reminder",
            )
            if c.get("entityType") == "CAMP"
        ]

    @staticmethod
    def _registration_status(registration: dict):
        from domain.camps import RegistrationStatus

        try:
            return RegistrationStatus(registration.get("status", "REGISTERED"))
        except ValueError:
            return RegistrationStatus.REGISTERED

    @staticmethod
    def _present_camp(camp: dict) -> dict:
        return {
            "campId": camp.get("campId"),
            "name": camp.get("name"),
            "description": camp.get("description"),
            "organizerOrganizationId": camp.get("organizerOrganizationId"),
            "address": camp.get("address"),
            "city": camp.get("city"),
            "latitude": float(camp["latitude"]) if camp.get("latitude") is not None else None,
            "longitude": float(camp["longitude"]) if camp.get("longitude") is not None else None,
            "startsAt": camp.get("startsAt"),
            "endsAt": camp.get("endsAt"),
            "registrationDeadline": camp.get("registrationDeadline"),
            "capacity": camp.get("capacity"),
            "registeredCount": camp.get("registeredCount", 0),
            "status": camp.get("status"),
            "straightLineKm": camp.get("straightLineKm"),
            "demoData": camp.get("demoData", False),
        }
