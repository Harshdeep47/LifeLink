"""All HTTP handlers and the route table.

Handlers are thin by design (ADR-0010): parse, call a service, format. They hold
no business rules, so the rules stay testable without HTTP and reviewable in one
place. Authorization is declared by the ``@requires`` decorator on each handler
and re-stated in the route table for the audit test.
"""
from __future__ import annotations

from appcore.auth import requires
from appcore.context import RequestContext
from appcore.environment import environment_name
from appcore.rbac import Permission
from appcore.responses import clamp_page_size, created, paginated, success
from domain.blood import BloodGroup, Component
from domain.clock import now_utc
from domain.errors import ValidationError
from domain.geo import Coordinates
from services.container import get_services

from .router import (
    Router,
    parse_body,
    parse_iso_param,
    path_param,
    query_params,
    require_float,
    require_int,
)

# --------------------------------------------------------------------------
# Resource-owner resolvers. These are how organization isolation is applied
# centrally: each scoped handler says how to find the owning organization of
# the resource it touches, and the decorator does the comparison.
# --------------------------------------------------------------------------


def _facility_owner(event: dict, context: RequestContext) -> str | None:
    facility_id = (event.get("pathParameters") or {}).get("facilityId")
    if not facility_id:
        return None
    facility = get_services().repos.facilities.get_facility(facility_id)
    return (facility or {}).get("organizationId")


def _camp_owner(event: dict, context: RequestContext) -> str | None:
    camp_id = (event.get("pathParameters") or {}).get("campId")
    if not camp_id:
        return None
    camp = get_services().repos.camps.get_camp(camp_id)
    return (camp or {}).get("organizerOrganizationId")


def _caller_org(event: dict, context: RequestContext) -> str | None:
    """For create-style actions where the resource does not exist yet."""
    return context.organization_id


# --------------------------------------------------------------------------
# Health and metadata
# --------------------------------------------------------------------------


def health(event: dict, context: RequestContext) -> dict:
    import os

    return success(
        {
            "status": "ok",
            "environment": environment_name(),
            "region": os.environ.get("AWS_REGION", "ap-southeast-2"),
            "time": now_utc().isoformat().replace("+00:00", "Z"),
            "demoEnvironment": os.environ.get("LIFELINK_DEMO", "true").lower() == "true",
        },
        correlation_id=context.correlation_id,
    )


def reference_data(event: dict, context: RequestContext) -> dict:
    """Enumerations and reference metadata the frontend needs."""
    from domain.blood import ALL_COMPONENTS, ALL_GROUPS
    from domain.compatibility import get_reference
    from domain.impact import MILESTONE_LABELS, MILESTONE_THRESHOLDS, POINTS_PER_VERIFIED_DONATION
    from domain.ranking import DEFAULT_WEIGHTS

    ref = get_reference()
    return success(
        {
            "bloodGroups": [g.value for g in ALL_GROUPS],
            "components": [c.value for c in ALL_COMPONENTS],
            "freshnessBands": [
                {"label": "FRESH", "description": "Updated within 6 hours"},
                {"label": "AGING", "description": "Updated 6 to 24 hours ago"},
                {"label": "STALE", "description": "Updated 24 to 48 hours ago"},
                {"label": "OUTDATED", "description": "Updated more than 48 hours ago"},
                {"label": "UNKNOWN", "description": "No update time recorded"},
            ],
            "rankingWeights": {
                "availability": DEFAULT_WEIGHTS.availability,
                "quantity": DEFAULT_WEIGHTS.quantity,
                "freshness": DEFAULT_WEIGHTS.freshness,
                "verification": DEFAULT_WEIGHTS.verification,
                "distance": DEFAULT_WEIGHTS.distance,
            },
            "impact": {
                "pointsPerVerifiedDonation": POINTS_PER_VERIFIED_DONATION,
                "milestones": [
                    {"name": MILESTONE_LABELS[m], "verifiedDonations": t}
                    for m, t in MILESTONE_THRESHOLDS.items()
                ],
            },
            "compatibility": {
                "rulesVersion": ref.version,
                "reviewStatus": ref.review_status,
                "disclaimer": ref.disclaimer,
            },
            "notificationDefaults": {"radiusKm": 10, "extendedRadiusKm": 20},
        },
        correlation_id=context.correlation_id,
    )


# --------------------------------------------------------------------------
# Feature 2 -- discovery (public)
# --------------------------------------------------------------------------


@requires(Permission.FACILITY_READ, allow_anonymous=True)
def search_facilities(event: dict, context: RequestContext) -> dict:
    params = query_params(event)
    outcome = get_services().discovery.search_facilities(
        latitude=require_float(params, "lat"),
        longitude=require_float(params, "lon"),
        radius_km=require_float(params, "radiusKm", default=10.0),
        blood_group=params.get("bloodGroup"),
        component=params.get("component"),
        requested_units=require_int(params, "units", default=1),
        only_available=params.get("onlyAvailable", "").lower() == "true",
        min_freshness=params.get("minFreshness"),
        verified_only=params.get("verifiedOnly", "").lower() == "true",
        limit=clamp_page_size(params.get("limit")),
        now=now_utc(),
        context=context,
    )
    return success(outcome, correlation_id=context.correlation_id)


@requires(Permission.FACILITY_READ, allow_anonymous=True)
def get_facility(event: dict, context: RequestContext) -> dict:
    detail = get_services().discovery.get_facility_detail(
        facility_id=path_param(event, "facilityId"), now=now_utc()
    )
    return success(detail, correlation_id=context.correlation_id)


@requires(Permission.INVENTORY_READ_PUBLIC, allow_anonymous=True)
def facility_availability(event: dict, context: RequestContext) -> dict:
    params = query_params(event)
    from domain.blood import parse_component, parse_group

    groups = [parse_group(g) for g in (params.get("bloodGroup") or "").split(",") if g]
    components = [parse_component(c) for c in (params.get("component") or "").split(",") if c]
    outcome = get_services().inventory.facility_availability(
        facility_id=path_param(event, "facilityId"),
        now=now_utc(),
        groups=groups or None,
        components=components or None,
        requested_units=require_int(params, "units", default=1),
    )
    return success(outcome, correlation_id=context.correlation_id)


@requires(Permission.FACILITY_READ, allow_anonymous=True)
def geocode(event: dict, context: RequestContext) -> dict:
    params = query_params(event)
    near = None
    if params.get("lat") and params.get("lon"):
        near = Coordinates(require_float(params, "lat"), require_float(params, "lon"))
    outcome = get_services().discovery.geocode(
        query=params.get("q", ""), near=near, limit=require_int(params, "limit", default=5)
    )
    return success(outcome, correlation_id=context.correlation_id)


@requires(Permission.FACILITY_READ, allow_anonymous=True)
def route_to_facility(event: dict, context: RequestContext) -> dict:
    params = query_params(event)
    outcome = get_services().discovery.route_to_facility(
        origin=Coordinates(require_float(params, "lat"), require_float(params, "lon")),
        facility_id=path_param(event, "facilityId"),
    )
    return success(outcome, correlation_id=context.correlation_id)


# --------------------------------------------------------------------------
# Feature 1 -- inventory (blood bank)
# --------------------------------------------------------------------------


@requires(Permission.INVENTORY_READ_DETAILED, resource_owner=_facility_owner)
def list_batches(event: dict, context: RequestContext) -> dict:
    params = query_params(event)
    batches, next_key = get_services().inventory.list_batches(
        facility_id=path_param(event, "facilityId"),
        now=now_utc(),
        limit=clamp_page_size(params.get("limit")),
    )
    from appcore.responses import encode_cursor

    return paginated(
        batches,
        next_cursor=encode_cursor(next_key, "batches"),
        correlation_id=context.correlation_id,
    )


@requires(Permission.INVENTORY_WRITE, resource_owner=_facility_owner)
def create_batch(event: dict, context: RequestContext) -> dict:
    body = parse_body(event)
    facility_id = path_param(event, "facilityId")
    facility = get_services().repos.facilities.get_facility(facility_id) or {}
    batch = get_services().inventory.create_batch(
        context=context,
        facility_id=facility_id,
        organization_id=facility.get("organizationId", context.organization_id or ""),
        blood_group=body.get("bloodGroup", ""),
        component=body.get("component", ""),
        units=require_int(body, "units"),
        collected_at=parse_iso_param(body.get("collectedAt"), "collectedAt"),
        expires_at=parse_iso_param(body.get("expiresAt"), "expiresAt"),
        now=now_utc(),
        source=body.get("source", "MANUAL"),
    )
    return created(batch, correlation_id=context.correlation_id,
                   location=f"/facilities/{facility_id}/batches/{batch['batchId']}")


@requires(Permission.INVENTORY_READ_DETAILED, resource_owner=_facility_owner)
def get_batch(event: dict, context: RequestContext) -> dict:
    batch = get_services().inventory.get_batch(
        facility_id=path_param(event, "facilityId"),
        batch_id=path_param(event, "batchId"),
        now=now_utc(),
    )
    return success(batch, correlation_id=context.correlation_id)


@requires(Permission.INVENTORY_WRITE, resource_owner=_facility_owner)
def adjust_batch(event: dict, context: RequestContext) -> dict:
    body = parse_body(event)
    batch = get_services().inventory.adjust_stock(
        context=context,
        facility_id=path_param(event, "facilityId"),
        batch_id=path_param(event, "batchId"),
        operation=body.get("operation", ""),
        units=body.get("units"),
        reason=body.get("reason"),
        source=body.get("source", "MANUAL"),
        now=now_utc(),
    )
    return success(batch, correlation_id=context.correlation_id)


@requires(Permission.INVENTORY_VERIFY, resource_owner=_facility_owner)
def verify_batch(event: dict, context: RequestContext) -> dict:
    body = parse_body(event)
    batch = get_services().inventory.verify_inventory(
        context=context,
        facility_id=path_param(event, "facilityId"),
        batch_id=path_param(event, "batchId"),
        note=body.get("note"),
        now=now_utc(),
    )
    return success(batch, correlation_id=context.correlation_id)


@requires(Permission.INVENTORY_READ_DETAILED, resource_owner=_facility_owner)
def batch_audit(event: dict, context: RequestContext) -> dict:
    history = get_services().inventory.audit_history(batch_id=path_param(event, "batchId"))
    return success(history, correlation_id=context.correlation_id)


@requires(Permission.INVENTORY_INGEST_API, resource_owner=_facility_owner)
def ingest_inventory(event: dict, context: RequestContext) -> dict:
    body = parse_body(event)
    batch = get_services().inventory.ingest_external_update(
        context=context,
        facility_id=path_param(event, "facilityId"),
        batch_id=body.get("batchId", ""),
        units=require_int(body, "units"),
        source_timestamp=parse_iso_param(body.get("sourceTimestamp"), "sourceTimestamp"),
        source_system=body.get("sourceSystem", "UNKNOWN"),
        now=now_utc(),
    )
    return success(batch, correlation_id=context.correlation_id)



# --------------------------------------------------------------------------
# Feature 1 -- temporary reservations
#
# Additive capability. A reservation is a time-limited hold on specific units,
# which is a different thing from an availability alert (which holds nothing)
# and from a provider's ACCEPTED response to an emergency request (which also
# holds nothing). Both of those remain unchanged. A hold is never clinical
# approval; see domain/reservations.py.
# --------------------------------------------------------------------------


@requires(Permission.RESERVATION_CREATE)
def request_reservation(event: dict, context: RequestContext) -> dict:
    facility_id = path_param(event, "facilityId")
    body = parse_body(event)
    reservation = get_services().reservations.request_reservation(
        facility_id=facility_id,
        blood_group=BloodGroup(body.get("bloodGroup", "")),
        component=Component(body.get("component", "")),
        units=require_int(body, "units"),
        requester_user_id=context.principal.user_id,
        hold_minutes=body.get("holdMinutes"),
        now=now_utc(),
        correlation_id=context.correlation_id,
    )
    return created(reservation, correlation_id=context.correlation_id)


@requires(Permission.RESERVATION_MANAGE_OWN)
def list_my_reservations(event: dict, context: RequestContext) -> dict:
    items = get_services().reservations.list_mine(
        context.principal.user_id, now=now_utc()
    )
    return success(items, correlation_id=context.correlation_id)


@requires(Permission.RESERVATION_MANAGE_OWN)
def cancel_reservation(event: dict, context: RequestContext) -> dict:
    body = parse_body(event)
    reservation = get_services().reservations.cancel(
        facility_id=path_param(event, "facilityId"),
        blood_group=BloodGroup(body.get("bloodGroup", "")),
        component=Component(body.get("component", "")),
        reservation_id=path_param(event, "reservationId"),
        actor_user_id=context.principal.user_id,
        now=now_utc(),
        correlation_id=context.correlation_id,
    )
    return success(reservation, correlation_id=context.correlation_id)


@requires(Permission.RESERVATION_MANAGE, resource_owner=_facility_owner)
def list_facility_reservations(event: dict, context: RequestContext) -> dict:
    items = get_services().reservations.list_for_facility(
        path_param(event, "facilityId"), now=now_utc()
    )
    return success(items, correlation_id=context.correlation_id)


@requires(Permission.RESERVATION_MANAGE, resource_owner=_facility_owner)
def decide_reservation(event: dict, context: RequestContext) -> dict:
    body = parse_body(event)
    decision = (body.get("decision") or "").upper()
    if decision not in ("CONFIRM", "REJECT"):
        raise ValidationError(
            "decision must be CONFIRM or REJECT",
            details={"rule": "UNKNOWN_RESERVATION_DECISION"},
        )
    reservation = get_services().reservations.decide(
        facility_id=path_param(event, "facilityId"),
        blood_group=BloodGroup(body.get("bloodGroup", "")),
        component=Component(body.get("component", "")),
        reservation_id=path_param(event, "reservationId"),
        approve=decision == "CONFIRM",
        reason=body.get("reason"),
        actor_user_id=context.principal.user_id,
        actor_organization_id=context.principal.organization_id,
        now=now_utc(),
        correlation_id=context.correlation_id,
    )
    return success(reservation, correlation_id=context.correlation_id)


@requires(Permission.RESERVATION_MANAGE, resource_owner=_facility_owner)
def fulfil_reservation(event: dict, context: RequestContext) -> dict:
    body = parse_body(event)
    reservation = get_services().reservations.fulfil(
        facility_id=path_param(event, "facilityId"),
        blood_group=BloodGroup(body.get("bloodGroup", "")),
        component=Component(body.get("component", "")),
        reservation_id=path_param(event, "reservationId"),
        actor_user_id=context.principal.user_id,
        actor_organization_id=context.principal.organization_id,
        now=now_utc(),
        correlation_id=context.correlation_id,
    )
    return success(reservation, correlation_id=context.correlation_id)


# --------------------------------------------------------------------------
# Feature 1 -- availability alerts
# --------------------------------------------------------------------------


@requires(Permission.ALERT_CREATE)
def create_alert(event: dict, context: RequestContext) -> dict:
    body = parse_body(event)
    alert = get_services().alerts.create_alert(
        context=context,
        blood_group=body.get("bloodGroup", ""),
        component=body.get("component", ""),
        required_units=require_int(body, "requiredUnits"),
        latitude=require_float(body, "latitude"),
        longitude=require_float(body, "longitude"),
        radius_km=require_float(body, "radiusKm", default=15.0),
        required_by=parse_iso_param(body.get("requiredBy"), "requiredBy"),
        notify_channels=body.get("notifyChannels"),
        now=now_utc(),
    )
    return created(alert, correlation_id=context.correlation_id)


@requires(Permission.ALERT_MANAGE_OWN)
def list_alerts(event: dict, context: RequestContext) -> dict:
    params = query_params(event)
    alerts = get_services().alerts.list_my_alerts(
        context=context, active_only=params.get("activeOnly", "").lower() == "true"
    )
    return success(alerts, correlation_id=context.correlation_id)


@requires(Permission.ALERT_MANAGE_OWN)
def get_alert(event: dict, context: RequestContext) -> dict:
    alert = get_services().alerts.get_alert(
        context=context, alert_id=path_param(event, "alertId")
    )
    return success(alert, correlation_id=context.correlation_id)


@requires(Permission.ALERT_MANAGE_OWN)
def cancel_alert(event: dict, context: RequestContext) -> dict:
    outcome = get_services().alerts.cancel_alert(
        context=context, alert_id=path_param(event, "alertId"), now=now_utc()
    )
    return success(outcome, correlation_id=context.correlation_id)


# --------------------------------------------------------------------------
# Feature 3 -- camps
# --------------------------------------------------------------------------


@requires(Permission.CAMP_READ, allow_anonymous=True)
def search_camps(event: dict, context: RequestContext) -> dict:
    params = query_params(event)
    outcome = get_services().camps.search_camps(
        latitude=require_float(params, "lat"),
        longitude=require_float(params, "lon"),
        radius_km=require_float(params, "radiusKm", default=20.0),
        now=now_utc(),
    )
    return success(outcome, correlation_id=context.correlation_id)


@requires(Permission.CAMP_READ, allow_anonymous=True)
def get_camp(event: dict, context: RequestContext) -> dict:
    camp = get_services().camps.get_camp(
        camp_id=path_param(event, "campId"), now=now_utc(), context=context
    )
    return success(camp, correlation_id=context.correlation_id)


@requires(Permission.CAMP_CREATE, resource_owner=_caller_org)
def create_camp(event: dict, context: RequestContext) -> dict:
    body = parse_body(event)
    camp = get_services().camps.create_camp(
        context=context,
        name=body.get("name", ""),
        description=body.get("description", ""),
        latitude=require_float(body, "latitude"),
        longitude=require_float(body, "longitude"),
        address=body.get("address", ""),
        city=body.get("city", ""),
        starts_at=parse_iso_param(body.get("startsAt"), "startsAt"),
        ends_at=parse_iso_param(body.get("endsAt"), "endsAt"),
        capacity=require_int(body, "capacity"),
        registration_deadline=parse_iso_param(
            body.get("registrationDeadline"), "registrationDeadline"
        ),
        now=now_utc(),
    )
    return created(camp, correlation_id=context.correlation_id)


@requires(Permission.CAMP_APPROVE)
def approve_camp(event: dict, context: RequestContext) -> dict:
    body = parse_body(event)
    outcome = get_services().camps.approve_camp(
        context=context,
        camp_id=path_param(event, "campId"),
        approve=bool(body.get("approve", True)),
        reason=body.get("reason"),
        now=now_utc(),
    )
    return success(outcome, correlation_id=context.correlation_id)


@requires(Permission.CAMP_MANAGE, resource_owner=_camp_owner)
def cancel_camp(event: dict, context: RequestContext) -> dict:
    body = parse_body(event)
    outcome = get_services().camps.cancel_camp(
        context=context,
        camp_id=path_param(event, "campId"),
        reason=body.get("reason", "cancelled by organizer"),
        now=now_utc(),
    )
    return success(outcome, correlation_id=context.correlation_id)


@requires(Permission.CAMP_MANAGE, resource_owner=_camp_owner)
def list_organizer_camps(event: dict, context: RequestContext) -> dict:
    camps = get_services().camps.list_organizer_camps(context=context)
    return success(camps, correlation_id=context.correlation_id)


@requires(Permission.CAMP_STAFF_ASSIGN, resource_owner=_camp_owner)
def assign_camp_staff(event: dict, context: RequestContext) -> dict:
    body = parse_body(event)
    outcome = get_services().camps.assign_staff(
        context=context,
        camp_id=path_param(event, "campId"),
        user_id=body.get("userId", ""),
        now=now_utc(),
    )
    return success(outcome, correlation_id=context.correlation_id)


@requires(Permission.REGISTRATION_CREATE)
def register_for_camp(event: dict, context: RequestContext) -> dict:
    outcome = get_services().camps.register(
        context=context, camp_id=path_param(event, "campId"), now=now_utc()
    )
    return created(outcome, correlation_id=context.correlation_id)


@requires(Permission.REGISTRATION_MANAGE_OWN)
def cancel_registration(event: dict, context: RequestContext) -> dict:
    outcome = get_services().camps.cancel_registration(
        context=context, camp_id=path_param(event, "campId"), now=now_utc()
    )
    return success(outcome, correlation_id=context.correlation_id)


@requires(Permission.REGISTRATION_MANAGE_OWN)
def my_registrations(event: dict, context: RequestContext) -> dict:
    return success(
        get_services().camps.my_registrations(context=context),
        correlation_id=context.correlation_id,
    )


@requires(Permission.CAMP_CHECKIN, resource_owner=_camp_owner)
def check_in_donor(event: dict, context: RequestContext) -> dict:
    body = parse_body(event)
    outcome = get_services().camps.check_in(
        context=context,
        camp_id=path_param(event, "campId"),
        donor_id=body.get("donorId", ""),
        now=now_utc(),
    )
    return success(outcome, correlation_id=context.correlation_id)


@requires(Permission.DONATION_RECORD, resource_owner=_camp_owner)
def record_donation(event: dict, context: RequestContext) -> dict:
    body = parse_body(event)
    outcome = get_services().camps.record_donation(
        context=context,
        camp_id=path_param(event, "campId"),
        donor_id=body.get("donorId", ""),
        blood_group=body.get("bloodGroup", ""),
        component=body.get("component", "WHOLE_BLOOD"),
        units=require_int(body, "units", default=1),
        now=now_utc(),
    )
    return created(outcome, correlation_id=context.correlation_id)


@requires(Permission.DONATION_VERIFY, resource_owner=_camp_owner)
def verify_donation(event: dict, context: RequestContext) -> dict:
    body = parse_body(event)
    outcome = get_services().camps.verify_donation(
        context=context,
        camp_id=path_param(event, "campId"),
        donor_id=body.get("donorId", ""),
        donation_id=body.get("donationId", ""),
        now=now_utc(),
    )
    return success(outcome, correlation_id=context.correlation_id)


# --------------------------------------------------------------------------
# Feature 3 -- donor profile
# --------------------------------------------------------------------------


@requires(Permission.REGISTRATION_MANAGE_OWN)
def donor_profile(event: dict, context: RequestContext) -> dict:
    return success(
        get_services().camps.donor_profile(context=context, now=now_utc()),
        correlation_id=context.correlation_id,
    )


@requires(Permission.REGISTRATION_MANAGE_OWN)
def donation_history(event: dict, context: RequestContext) -> dict:
    return success(
        get_services().camps.donation_history(context=context),
        correlation_id=context.correlation_id,
    )


@requires(Permission.REGISTRATION_MANAGE_OWN)
def donation_certificate(event: dict, context: RequestContext) -> dict:
    return success(
        get_services().camps.certificate_data(
            context=context, donation_id=path_param(event, "donationId")
        ),
        correlation_id=context.correlation_id,
    )


# --------------------------------------------------------------------------
# Feature 4 -- emergency
# --------------------------------------------------------------------------


# allow_anonymous: someone seeking blood in an emergency must not be asked to
# create an account first. The request lands in VERIFICATION_PENDING because
# the service derives verification state from the caller's organization, and an
# anonymous caller has none -- so a public request can never arrive
# pre-certified. Certification remains a separate permission held only by an
# authorizing clinician at a verified hospital.
@requires(Permission.EMERGENCY_CREATE, allow_anonymous=True)
def create_emergency_request(event: dict, context: RequestContext) -> dict:
    body = parse_body(event)
    outcome = get_services().emergency.create_request(
        context=context,
        blood_group=body.get("bloodGroup", ""),
        component=body.get("component", ""),
        required_units=require_int(body, "requiredUnits"),
        latitude=require_float(body, "latitude"),
        longitude=require_float(body, "longitude"),
        required_by=parse_iso_param(body.get("requiredBy"), "requiredBy"),
        contact_name=body.get("contactName", ""),
        contact_phone=body.get("contactPhone", ""),
        patient_reference=body.get("patientReference"),
        requesting_institution=body.get("requestingInstitution"),
        consent_given=bool(body.get("consentGiven", False)),
        notes=body.get("notes"),
        now=now_utc(),
    )
    return created(outcome, correlation_id=context.correlation_id)


@requires(Permission.EMERGENCY_READ_OWN)
def get_emergency_request(event: dict, context: RequestContext) -> dict:
    return success(
        get_services().emergency.get_request(
            context=context, request_id=path_param(event, "requestId")
        ),
        correlation_id=context.correlation_id,
    )


@requires(Permission.EMERGENCY_READ_OWN)
def list_emergency_requests(event: dict, context: RequestContext) -> dict:
    return success(
        get_services().emergency.list_my_requests(context=context),
        correlation_id=context.correlation_id,
    )


@requires(Permission.EMERGENCY_CERTIFY_PRIORITY, resource_owner=_caller_org)
def certify_priority(event: dict, context: RequestContext) -> dict:
    body = parse_body(event)
    outcome = get_services().emergency.certify_priority(
        context=context,
        request_id=path_param(event, "requestId"),
        priority_label=body.get("priority", ""),
        justification=body.get("justification"),
        now=now_utc(),
    )
    return success(outcome, correlation_id=context.correlation_id)


@requires(Permission.EMERGENCY_RESPOND, resource_owner=_caller_org)
def respond_to_request(event: dict, context: RequestContext) -> dict:
    body = parse_body(event)
    outcome = get_services().emergency.submit_response(
        context=context,
        request_id=path_param(event, "requestId"),
        response_type=body.get("responseType", ""),
        units_offered=require_int(body, "unitsOffered", default=0),
        note=body.get("note"),
        now=now_utc(),
    )
    return success(outcome, correlation_id=context.correlation_id)


@requires(Permission.EMERGENCY_RESPOND, resource_owner=_caller_org)
def provider_queue(event: dict, context: RequestContext) -> dict:
    return success(
        get_services().emergency.list_provider_queue(context=context),
        correlation_id=context.correlation_id,
    )


@requires(Permission.EMERGENCY_CANCEL)
def cancel_emergency_request(event: dict, context: RequestContext) -> dict:
    body = parse_body(event)
    outcome = get_services().emergency.cancel_request(
        context=context,
        request_id=path_param(event, "requestId"),
        reason=body.get("reason", "cancelled by requester"),
        now=now_utc(),
    )
    return success(outcome, correlation_id=context.correlation_id)


@requires(Permission.EMERGENCY_CERTIFY_PRIORITY, resource_owner=_caller_org)
def confirm_availability(event: dict, context: RequestContext) -> dict:
    outcome = get_services().emergency.confirm_availability(
        context=context, request_id=path_param(event, "requestId"), now=now_utc()
    )
    return success(outcome, correlation_id=context.correlation_id)


# --------------------------------------------------------------------------
# Feature 6 -- notifications, admin
# --------------------------------------------------------------------------


@requires(Permission.ALERT_MANAGE_OWN)
def get_notification_preferences(event: dict, context: RequestContext) -> dict:
    return success(
        get_services().notifications.get_preferences(context.actor_id),
        correlation_id=context.correlation_id,
    )


@requires(Permission.ALERT_MANAGE_OWN)
def update_notification_preferences(event: dict, context: RequestContext) -> dict:
    body = parse_body(event)
    return success(
        get_services().notifications.save_preferences(context.actor_id, body),
        correlation_id=context.correlation_id,
    )


@requires(Permission.ALERT_MANAGE_OWN)
def list_notifications(event: dict, context: RequestContext) -> dict:
    return success(
        get_services().notifications.list_for_user(context.actor_id),
        correlation_id=context.correlation_id,
    )


@requires(Permission.HOSPITAL_VERIFY)
def set_organization_status(event: dict, context: RequestContext) -> dict:
    body = parse_body(event)
    outcome = get_services().repos.identity.set_organization_status(
        path_param(event, "organizationId"),
        status=body.get("status", ""),
        actor_id=context.actor_id,
        now=now_utc(),
        reason=body.get("reason"),
    )
    get_services().repos.audit.record(
        actor_id=context.actor_id,
        actor_role=",".join(context.principal.roles),
        action="ORGANIZATION_STATUS_CHANGED",
        resource_type="ORGANIZATION",
        resource_id=path_param(event, "organizationId"),
        correlation_id=context.correlation_id,
        occurred_at=now_utc(),
        after={"status": body.get("status")},
        metadata={"reason": body.get("reason")},
    )
    return success(
        {"organizationId": outcome.get("organizationId"), "status": outcome.get("status")},
        correlation_id=context.correlation_id,
    )


@requires(Permission.USER_MANAGE)
def set_account_status(event: dict, context: RequestContext) -> dict:
    body = parse_body(event)
    outcome = get_services().repos.identity.set_account_status(
        path_param(event, "userId"),
        status=body.get("status", ""),
        actor_id=context.actor_id,
        now=now_utc(),
    )
    get_services().repos.audit.record(
        actor_id=context.actor_id,
        actor_role=",".join(context.principal.roles),
        action="ACCOUNT_STATUS_CHANGED",
        resource_type="USER",
        resource_id=path_param(event, "userId"),
        correlation_id=context.correlation_id,
        occurred_at=now_utc(),
        after={"accountStatus": body.get("status")},
    )
    return success(
        {"userId": outcome.get("userId"), "accountStatus": outcome.get("accountStatus")},
        correlation_id=context.correlation_id,
    )


@requires(Permission.ORG_READ)
def list_pending_organizations(event: dict, context: RequestContext) -> dict:
    return success(
        get_services().repos.identity.list_by_status("PENDING_VERIFICATION"),
        correlation_id=context.correlation_id,
    )


@requires(Permission.AUDIT_READ)
def read_audit(event: dict, context: RequestContext) -> dict:
    params = query_params(event)
    repo = get_services().repos.audit
    if params.get("actorId"):
        records = repo.history_for_actor(params["actorId"])
    elif params.get("resourceType") and params.get("resourceId"):
        records = repo.history_for_resource(params["resourceType"], params["resourceId"])
    else:
        from domain.errors import ValidationError

        raise ValidationError(
            "provide actorId, or resourceType with resourceId",
            details={"reason": "audit cannot be scanned without a key"},
        )
    return success(records, correlation_id=context.correlation_id)


@requires(Permission.PROFILE_MANAGE_OWN)
def whoami(event: dict, context: RequestContext) -> dict:
    profile = get_services().repos.identity.get_user(context.principal.user_id) or {}
    pending = profile.get("pendingOrganizationRequest")
    return success(
        {
            "userId": context.principal.user_id,
            "displayName": context.principal.display_name,
            "email": profile.get("email"),
            "roles": list(context.principal.roles),
            "organizationId": context.principal.organization_id,
            "accountStatus": context.principal.account_status,
            "permissions": sorted(p.value for p in context.principal.permissions),
            # Lets the interface show "pending verification" rather than
            # leaving an institutional applicant wondering.
            "pendingOrganizationRequest": pending,
        },
        correlation_id=context.correlation_id,
    )


@requires(Permission.PROFILE_MANAGE_OWN)
def update_my_profile(event: dict, context: RequestContext) -> dict:
    """Edit one's own display name. Nothing else.

    Deliberately narrow. A general profile-update endpoint that accepted a
    dictionary and merged it would be a role-escalation vector the moment
    someone posted {"roles": ["PLATFORM_ADMIN"]}. Only displayName is read
    from the body; roles, organizationId and accountStatus are never writable
    here and are changed only by an administrator through their own audited
    endpoints.
    """
    body = parse_body(event)
    display_name = (body.get("displayName") or "").strip()
    if not display_name:
        raise ValidationError(
            "displayName is required",
            details={"rule": "DISPLAY_NAME_REQUIRED"},
        )
    if len(display_name) > 80:
        raise ValidationError(
            "displayName cannot exceed 80 characters",
            details={"rule": "DISPLAY_NAME_TOO_LONG"},
        )

    updated = get_services().repos.identity.update_display_name(
        user_id=context.principal.user_id,
        display_name=display_name,
        now=now_utc(),
    )
    return success(
        {"userId": updated["userId"], "displayName": updated["displayName"]},
        correlation_id=context.correlation_id,
    )


@requires(Permission.PROFILE_MANAGE_OWN)
def request_organization_access(event: dict, context: RequestContext) -> dict:
    """Record a request for an institutional role. Grants nothing.

    This is the safe half of account-type selection. A user may *ask* to be
    recognised as a blood bank, hospital or camp organizer; the request is
    stored as PENDING and an administrator verifies it through the existing
    approval path.

    What this must never do, and does not: assign a role, attach an
    organization, or change account status. Until an administrator acts, the
    caller's permissions are exactly what they were, so every
    organization-scoped check still refuses.
    """
    body = parse_body(event)
    requested = (body.get("requestedType") or "").strip().upper()
    allowed = {"BLOOD_BANK", "HOSPITAL", "CAMP_ORGANIZER"}
    if requested not in allowed:
        raise ValidationError(
            f"requestedType must be one of: {', '.join(sorted(allowed))}",
            details={"rule": "UNKNOWN_REQUESTED_TYPE"},
        )

    organization_name = (body.get("organizationName") or "").strip()
    if not organization_name:
        raise ValidationError(
            "organizationName is required",
            details={"rule": "ORGANIZATION_NAME_REQUIRED"},
        )

    record = get_services().repos.identity.record_organization_request(
        user_id=context.principal.user_id,
        requested_type=requested,
        organization_name=organization_name,
        contact_detail=(body.get("contactDetail") or "").strip() or None,
        note=(body.get("note") or "").strip() or None,
        now=now_utc(),
    )

    get_services().repos.audit.record(
        actor_id=context.principal.user_id,
        actor_role=None,
        action="ORGANIZATION_ACCESS_REQUESTED",
        resource_type="USER",
        resource_id=context.principal.user_id,
        correlation_id=context.correlation_id,
        occurred_at=now_utc(),
        metadata={"requestedType": requested, "organizationName": organization_name},
    )

    return created(
        {
            "pendingOrganizationRequest": record,
            "notice": (
                "Your request has been recorded and is pending verification by "
                "an administrator. Your account keeps its current access until "
                "then."
            ),
        },
        correlation_id=context.correlation_id,
    )


# --------------------------------------------------------------------------
# Route table
# --------------------------------------------------------------------------


def build_router() -> Router:
    r = Router()

    r.add("GET", "/health", health, allow_anonymous=True, summary="Service health")
    r.add("GET", "/reference", reference_data, allow_anonymous=True,
          summary="Enumerations and reference metadata")
    r.add("PATCH", "/me", update_my_profile,
          permission=Permission.PROFILE_MANAGE_OWN,
          summary="Update my display name (display name only)")
    r.add("POST", "/me/organization-request", request_organization_access,
          permission=Permission.PROFILE_MANAGE_OWN,
          summary="Request an institutional role; pending until verified")
    r.add("GET", "/me", whoami, permission=Permission.PROFILE_MANAGE_OWN,
          summary="Current principal and effective permissions")

    # Feature 2 -- discovery
    r.add("GET", "/facilities", search_facilities, permission=Permission.FACILITY_READ,
          allow_anonymous=True, summary="Search facilities by location and availability")
    r.add("GET", "/facilities/{facilityId}", get_facility, permission=Permission.FACILITY_READ,
          allow_anonymous=True, summary="Facility detail")
    r.add("GET", "/facilities/{facilityId}/availability", facility_availability,
          permission=Permission.INVENTORY_READ_PUBLIC, allow_anonymous=True,
          summary="Availability matrix for a facility")
    r.add("GET", "/facilities/{facilityId}/route", route_to_facility,
          permission=Permission.FACILITY_READ, allow_anonymous=True,
          summary="Road route and ETA to a facility")
    r.add("GET", "/geocode", geocode, permission=Permission.FACILITY_READ,
          allow_anonymous=True, summary="Address and place search")

    # Feature 1 -- inventory
    r.add("GET", "/facilities/{facilityId}/batches", list_batches,
          permission=Permission.INVENTORY_READ_DETAILED, summary="List stock batches")
    r.add("POST", "/facilities/{facilityId}/batches", create_batch,
          permission=Permission.INVENTORY_WRITE, summary="Create a stock batch")
    r.add("GET", "/facilities/{facilityId}/batches/{batchId}", get_batch,
          permission=Permission.INVENTORY_READ_DETAILED, summary="Get one batch")
    r.add("POST", "/facilities/{facilityId}/batches/{batchId}/adjust", adjust_batch,
          permission=Permission.INVENTORY_WRITE, summary="Add, deduct, correct or quarantine")
    r.add("POST", "/facilities/{facilityId}/batches/{batchId}/verify", verify_batch,
          permission=Permission.INVENTORY_VERIFY, summary="Record independent verification")
    r.add("GET", "/facilities/{facilityId}/batches/{batchId}/audit", batch_audit,
          permission=Permission.INVENTORY_READ_DETAILED, summary="Batch audit history")
    r.add("POST", "/facilities/{facilityId}/inventory/ingest", ingest_inventory,
          permission=Permission.INVENTORY_INGEST_API, summary="External API ingestion")

    # Feature 1 -- temporary reservations
    r.add("POST", "/facilities/{facilityId}/reservations", request_reservation,
          permission=Permission.RESERVATION_CREATE,
          summary="Request a temporary hold on eligible units")
    r.add("GET", "/me/reservations", list_my_reservations,
          permission=Permission.RESERVATION_MANAGE_OWN,
          summary="List my reservations")
    r.add("DELETE", "/facilities/{facilityId}/reservations/{reservationId}",
          cancel_reservation, permission=Permission.RESERVATION_MANAGE_OWN,
          summary="Cancel my reservation and release the units")
    r.add("GET", "/facilities/{facilityId}/reservations",
          list_facility_reservations, permission=Permission.RESERVATION_MANAGE,
          summary="List reservation requests against this facility")
    r.add("POST", "/facilities/{facilityId}/reservations/{reservationId}/decision",
          decide_reservation, permission=Permission.RESERVATION_MANAGE,
          summary="Confirm or reject a reservation request")
    r.add("POST", "/facilities/{facilityId}/reservations/{reservationId}/fulfil",
          fulfil_reservation, permission=Permission.RESERVATION_MANAGE,
          summary="Record that reserved units were issued")

    # Feature 1 -- alerts
    r.add("POST", "/alerts", create_alert, permission=Permission.ALERT_CREATE,
          summary="Create a short-term availability alert")
    r.add("GET", "/alerts", list_alerts, permission=Permission.ALERT_MANAGE_OWN,
          summary="List my alerts")
    r.add("GET", "/alerts/{alertId}", get_alert, permission=Permission.ALERT_MANAGE_OWN,
          summary="Alert detail and matches")
    r.add("DELETE", "/alerts/{alertId}", cancel_alert, permission=Permission.ALERT_MANAGE_OWN,
          summary="Cancel an alert")

    # Feature 3 -- camps
    r.add("GET", "/camps", search_camps, permission=Permission.CAMP_READ,
          allow_anonymous=True, summary="Search camps near a location")
    r.add("POST", "/camps", create_camp, permission=Permission.CAMP_CREATE,
          summary="Create a camp")
    r.add("GET", "/camps/mine", list_organizer_camps, permission=Permission.CAMP_MANAGE,
          summary="Camps organized by my organization")
    r.add("GET", "/camps/{campId}", get_camp, permission=Permission.CAMP_READ,
          allow_anonymous=True, summary="Camp detail")
    r.add("POST", "/camps/{campId}/approve", approve_camp, permission=Permission.CAMP_APPROVE,
          summary="Approve or reject a camp")
    r.add("POST", "/camps/{campId}/cancel", cancel_camp, permission=Permission.CAMP_MANAGE,
          summary="Cancel a camp and notify registrants")
    r.add("POST", "/camps/{campId}/staff", assign_camp_staff,
          permission=Permission.CAMP_STAFF_ASSIGN, summary="Assign camp staff")
    r.add("POST", "/camps/{campId}/register", register_for_camp,
          permission=Permission.REGISTRATION_CREATE, summary="Register for a camp")
    r.add("DELETE", "/camps/{campId}/register", cancel_registration,
          permission=Permission.REGISTRATION_MANAGE_OWN, summary="Cancel my registration")
    r.add("POST", "/camps/{campId}/checkin", check_in_donor, permission=Permission.CAMP_CHECKIN,
          summary="Check a donor in (attendance)")
    r.add("POST", "/camps/{campId}/donations", record_donation,
          permission=Permission.DONATION_RECORD, summary="Record a donation")
    r.add("POST", "/camps/{campId}/donations/verify", verify_donation,
          permission=Permission.DONATION_VERIFY, summary="Verify a donation and credit impact")

    # Feature 3 -- donor
    r.add("GET", "/me/registrations", my_registrations,
          permission=Permission.REGISTRATION_MANAGE_OWN, summary="My camp registrations")
    r.add("GET", "/me/donor-profile", donor_profile,
          permission=Permission.REGISTRATION_MANAGE_OWN, summary="Impact score and milestones")
    r.add("GET", "/me/donations", donation_history,
          permission=Permission.REGISTRATION_MANAGE_OWN, summary="My donation history")
    r.add("GET", "/me/donations/{donationId}/certificate", donation_certificate,
          permission=Permission.REGISTRATION_MANAGE_OWN, summary="Recognition certificate")

    # Feature 4 -- emergency
    r.add("POST", "/emergency-requests", create_emergency_request,
          permission=Permission.EMERGENCY_CREATE, summary="Create an emergency request")
    r.add("GET", "/emergency-requests", list_emergency_requests,
          permission=Permission.EMERGENCY_READ_OWN, summary="My organization's requests")
    r.add("GET", "/emergency-requests/provider-queue", provider_queue,
          permission=Permission.EMERGENCY_RESPOND, summary="Requests awaiting my response")
    r.add("GET", "/emergency-requests/{requestId}", get_emergency_request,
          permission=Permission.EMERGENCY_READ_OWN, summary="Request detail and timeline")
    r.add("POST", "/emergency-requests/{requestId}/certify", certify_priority,
          permission=Permission.EMERGENCY_CERTIFY_PRIORITY,
          summary="Certify clinical priority (authorized hospital roles only)")
    r.add("POST", "/emergency-requests/{requestId}/respond", respond_to_request,
          permission=Permission.EMERGENCY_RESPOND, summary="Submit a provider response")
    r.add("POST", "/emergency-requests/{requestId}/confirm", confirm_availability,
          permission=Permission.EMERGENCY_CERTIFY_PRIORITY, summary="Confirm availability")
    r.add("POST", "/emergency-requests/{requestId}/cancel", cancel_emergency_request,
          permission=Permission.EMERGENCY_CANCEL, summary="Cancel a request")

    # Feature 6 -- notifications and admin
    r.add("GET", "/me/notification-preferences", get_notification_preferences,
          permission=Permission.ALERT_MANAGE_OWN, summary="Get notification preferences")
    r.add("PUT", "/me/notification-preferences", update_notification_preferences,
          permission=Permission.ALERT_MANAGE_OWN, summary="Update notification preferences")
    r.add("GET", "/me/notifications", list_notifications,
          permission=Permission.ALERT_MANAGE_OWN, summary="My in-app notifications")
    r.add("GET", "/admin/organizations/pending", list_pending_organizations,
          permission=Permission.ORG_READ, summary="Organizations awaiting verification")
    r.add("POST", "/admin/organizations/{organizationId}/status", set_organization_status,
          permission=Permission.HOSPITAL_VERIFY, summary="Verify or suspend an organization")
    r.add("POST", "/admin/users/{userId}/status", set_account_status,
          permission=Permission.USER_MANAGE, summary="Suspend or reinstate a user")
    r.add("GET", "/admin/audit", read_audit, permission=Permission.AUDIT_READ,
          summary="Read audit records by actor or resource")

    return r


ROUTER = build_router()


def lambda_handler(event: dict, lambda_context=None) -> dict:
    """API Gateway proxy entrypoint."""
    return ROUTER.dispatch(event, authenticator=get_services().authenticator)
