"""Feature 4 -- smart emergency coordination.

A coordination system, not a clinical decision system. The design keeps that
distinction enforceable:

* Only an authorized hospital role may certify clinical priority, and the
  certifying actor, role, organization and timestamp are recorded every time.
* The matching engine performs table lookup against a versioned compatibility
  reference and never infers compatibility.
* Hospital verification is re-checked at every sensitive step, so a hospital
  suspended mid-workflow immediately loses privileged capability.
* Provider acceptance is willingness, not a reservation. No code path nets
  offers against a shared counter, so stock cannot be double-counted.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from ulid import ULID

from appcore.context import RequestContext
from appcore.logging import get_logger
from domain.blood import parse_component, parse_group
from domain.clock import parse_iso, to_iso
from domain.compatibility import check_compatibility, compatible_donor_groups, get_reference
from domain.emergency import (
    ClinicalPriority,
    HospitalVerificationState,
    ProviderResponseType,
    RequestStatus,
    assert_transition,
    compute_effective_priority,
    is_expired,
    parse_priority_label,
    tally_responses,
)
from domain.errors import (
    ForbiddenError,
    NotFoundError,
    ValidationError,
)
from domain.geo import Coordinates
from repositories.identity_repo import OrganizationStatus, OrganizationType

MAX_UNITS_PER_REQUEST = 50
DEFAULT_MATCH_RADIUS_KM = 25.0
MAX_PROVIDERS_PER_REQUEST = 5

# Raising or responding to an emergency request still holds nothing. That is
# unchanged by the reservation feature, and worth keeping precise: temporary
# reservations are a separate, explicit action against a specific facility's
# stock (domain/reservations.py), not something an emergency request does
# implicitly. Saying "does not reserve stock" flatly would now be wrong, since
# the system can hold units; saying this flow does not is correct.
COORDINATION_NOTICE = (
    "LifeLink coordinates requests between institutions. It does not make "
    "clinical decisions, and raising or answering a request does not itself "
    "hold any units or guarantee fulfilment. Qualified professionals remain "
    "responsible for all clinical and release decisions."
)


class EmergencyService:
    def __init__(
        self,
        *,
        emergency_repository,
        identity_repository,
        facility_repository,
        inventory_repository,
        notification_service,
        audit_repository,
        outbox_repository,
        idempotency_repository,
        discovery_service,
    ):
        self._emergency = emergency_repository
        self._identity = identity_repository
        self._facilities = facility_repository
        self._inventory = inventory_repository
        self._notifications = notification_service
        self._audit = audit_repository
        self._outbox = outbox_repository
        self._idempotency = idempotency_repository
        self._discovery = discovery_service

    # --- request creation ---

    def create_request(
        self,
        *,
        context: RequestContext,
        blood_group: str,
        component: str,
        required_units: int,
        latitude: float,
        longitude: float,
        required_by: datetime | None,
        contact_name: str,
        contact_phone: str,
        now: datetime,
        patient_reference: str | None = None,
        requesting_institution: str | None = None,
        consent_given: bool = False,
        notes: str | None = None,
    ) -> dict:
        log = get_logger(__name__, context)
        group = parse_group(blood_group)
        comp = parse_component(component)

        if not consent_given:
            raise ValidationError(
                "consent is required before a request can be submitted",
                details={"field": "consentGiven"},
            )
        if required_units <= 0 or required_units > MAX_UNITS_PER_REQUEST:
            raise ValidationError(
                f"required units must be between 1 and {MAX_UNITS_PER_REQUEST}",
                details={"maximum": MAX_UNITS_PER_REQUEST},
            )
        if not contact_name.strip() or not contact_phone.strip():
            raise ValidationError("a contact name and phone number are required")
        if required_by is not None and required_by <= now:
            raise ValidationError("the required-by deadline is already in the past")
        try:
            Coordinates(latitude, longitude)
        except ValueError as exc:
            raise ValidationError(str(exc)) from None

        # Duplicate suppression by fingerprint (spec 6.2).
        fingerprint = self._fingerprint(
            actor_id=context.actor_id,
            group=group.value,
            component=comp.value,
            units=required_units,
            latitude=latitude,
            longitude=longitude,
        )
        idempotency_key = context.idempotency_key or f"emergency#{fingerprint}"
        existing = self._idempotency.claim(
            idempotency_key, now=now, operation="emergency.create"
        )
        if existing is not None:
            return {**existing.get("result", {}), "deduplicated": True}

        organization_id = context.organization_id
        verification_state = HospitalVerificationState.PENDING_VERIFICATION
        if organization_id:
            org = self._identity.get_organization(organization_id)
            if org and org.get("organizationType") == OrganizationType.HOSPITAL.value:
                verification_state = self._map_org_status(org.get("status"))

        request_id = str(ULID())
        # A new request carries NO clinical priority. It stays uncertified until
        # an authorized hospital actor certifies it (spec 6.4).
        payload = {
            "requestId": request_id,
            "bloodGroup": group.value,
            "component": comp.value,
            "requiredUnits": required_units,
            "latitude": latitude,
            "longitude": longitude,
            "requiredBy": to_iso(required_by),
            "contactName": contact_name.strip(),
            "contactPhone": contact_phone.strip(),
            "patientReference": patient_reference,
            "requestingInstitution": requesting_institution,
            "requesterOrganizationId": organization_id,
            "createdBy": context.actor_id,
            "consentGiven": True,
            "consentRecordedAt": to_iso(now),
            "notes": notes,
            "status": RequestStatus.REQUEST_CREATED.value,
            "clinicalPriority": None,
            "effectivePriority": ClinicalPriority.P3.value,
            "hospitalVerificationState": verification_state.value,
            "fingerprint": fingerprint,
        }

        outbox_item = self._outbox.build_event(
            event_type="EmergencyRequestCreated",
            payload={
                "requestId": request_id,
                "bloodGroup": group.value,
                "component": comp.value,
                "requiredUnits": required_units,
            },
            correlation_id=context.correlation_id,
            occurred_at=now,
            aggregate_id=request_id,
        )
        self._emergency.create_request_with_outbox(payload, outbox_item, now=now)

        self._emergency.transition(
            request_id=request_id,
            from_status=RequestStatus.REQUEST_CREATED,
            to_status=RequestStatus.VERIFICATION_PENDING,
            actor_id=context.actor_id,
            now=now,
        )

        self._audit.record(
            actor_id=context.actor_id,
            actor_role=",".join(context.principal.roles),
            action="EMERGENCY_REQUEST_CREATED",
            resource_type="EMERGENCY_REQUEST",
            resource_id=request_id,
            organization_id=organization_id,
            correlation_id=context.correlation_id,
            occurred_at=now,
            after={"bloodGroup": group.value, "requiredUnits": required_units},
        )

        result = {
            "requestId": request_id,
            "status": RequestStatus.VERIFICATION_PENDING.value,
            "clinicalPriority": None,
            "hospitalVerificationState": verification_state.value,
            "notice": COORDINATION_NOTICE,
            "nextStep": (
                "Awaiting hospital certification of clinical priority by an "
                "authorized hospital user."
            ),
        }
        self._idempotency.complete(idempotency_key, result=result, now=now)
        log.info("emergency request created", event="emergency.created", requestId=request_id)
        return result

    # --- hospital certification ---

    def certify_priority(
        self, *, context: RequestContext, request_id: str, priority_label: str,
        now: datetime, justification: str | None = None
    ) -> dict:
        """Certify clinical priority. Authorized hospital roles only.

        Re-checks hospital verification at the moment of certification, so a
        hospital suspended after the request was raised cannot certify it.
        """
        log = get_logger(__name__, context)
        request = self._require_request(request_id)
        priority = parse_priority_label(priority_label)

        if context.organization_id is None:
            raise ForbiddenError("priority certification requires hospital membership")

        org = self._identity.get_organization(context.organization_id)
        if org is None:
            raise ForbiddenError("certifying organization not found")
        if org.get("organizationType") != OrganizationType.HOSPITAL.value:
            raise ForbiddenError(
                "only a hospital may certify clinical priority",
                details={"organizationType": org.get("organizationType")},
            )
        if org.get("status") != OrganizationStatus.VERIFIED.value:
            # Spec 6.3: a suspended or unverified hospital loses this capability.
            raise ForbiddenError(
                "this hospital is not currently verified and cannot certify priority",
                details={"organizationStatus": org.get("status")},
            )

        current = RequestStatus(request["status"])
        if current != RequestStatus.VERIFICATION_PENDING:
            raise ValidationError(
                f"a request in state {current.value} cannot be certified",
                details={"status": current.value},
            )

        self._emergency.certify_priority(
            request_id=request_id,
            clinical_priority=priority,
            actor_id=context.actor_id,
            actor_role=",".join(context.principal.roles),
            organization_id=context.organization_id,
            now=now,
        )
        self._emergency.transition(
            request_id=request_id,
            from_status=current,
            to_status=RequestStatus.HOSPITAL_CERTIFIED,
            actor_id=context.actor_id,
            now=now,
            effective_priority=priority.value,
            extra={"hospitalVerificationState": HospitalVerificationState.VERIFIED.value},
        )
        self._audit.record(
            actor_id=context.actor_id,
            actor_role=",".join(context.principal.roles),
            action="EMERGENCY_PRIORITY_CERTIFIED",
            resource_type="EMERGENCY_REQUEST",
            resource_id=request_id,
            organization_id=context.organization_id,
            correlation_id=context.correlation_id,
            occurred_at=now,
            after={"clinicalPriority": priority.value},
            metadata={"justification": justification},
        )
        log.info("priority certified", event="emergency.certified",
                 requestId=request_id, priority=priority.value)
        return {
            "requestId": request_id,
            "clinicalPriority": priority.value,
            "status": RequestStatus.HOSPITAL_CERTIFIED.value,
            "certifiedBy": context.actor_id,
            "certifiedAt": to_iso(now),
            "notice": (
                "Clinical priority was certified by authorized hospital personnel. "
                "LifeLink does not determine clinical urgency."
            ),
        }

    # --- matching ---

    def run_matching(self, *, context: RequestContext, request_id: str, now: datetime,
                     radius_km: float = DEFAULT_MATCH_RADIUS_KM) -> dict:
        """Deterministic, explainable matching (spec 6.5).

        Compatible donor groups come from the versioned reference table. An
        UNKNOWN combination yields no candidates rather than a guess.
        """
        log = get_logger(__name__, context)
        request = self._require_request(request_id)
        current = RequestStatus(request["status"])

        if current in (RequestStatus.CANCELLED, RequestStatus.EXPIRED,
                       RequestStatus.RESOLVED):
            return {"requestId": request_id, "skipped": current.value}

        required_by = parse_iso(request.get("requiredBy"))
        if is_expired(required_by, now):
            self._expire(request_id, current, now, actor_id="system")
            return {"requestId": request_id, "skipped": RequestStatus.EXPIRED.value}

        # Re-check the requesting hospital has not been suspended mid-workflow.
        requester_org = request.get("requesterOrganizationId")
        if requester_org:
            org = self._identity.get_organization(requester_org)
            if org and org.get("status") == OrganizationStatus.SUSPENDED.value:
                self._emergency.append_event(
                    request_id=request_id,
                    event_type="MATCHING_HALTED_ORG_SUSPENDED",
                    actor_id="system",
                    now=now,
                    detail={"organizationId": requester_org},
                )
                return {"requestId": request_id, "skipped": "REQUESTER_SUSPENDED"}

        if current == RequestStatus.HOSPITAL_CERTIFIED:
            self._emergency.transition(
                request_id=request_id,
                from_status=current,
                to_status=RequestStatus.MATCHING_INITIATED,
                actor_id=context.actor_id,
                now=now,
                effective_priority=request.get("effectivePriority"),
            )
            current = RequestStatus.MATCHING_INITIATED

        recipient_group = parse_group(request["bloodGroup"])
        component = parse_component(request["component"])
        reference = get_reference()
        donor_groups = compatible_donor_groups(
            recipient_group=recipient_group, component=component, reference=reference
        )

        if not donor_groups:
            self._emergency.append_event(
                request_id=request_id,
                event_type="NO_COMPATIBILITY_REFERENCE",
                actor_id="system",
                now=now,
                detail={"bloodGroup": recipient_group.value, "component": component.value},
            )
            return {
                "requestId": request_id,
                "candidates": [],
                "reason": "NO_COMPATIBILITY_DATA",
                "compatibilityRulesVersion": reference.version,
                "notice": (
                    "No compatibility rule exists for this combination, so no "
                    "match was attempted. This is deliberate: the system does "
                    "not infer compatibility."
                ),
            }

        candidates: list[dict] = []
        for donor_group in donor_groups:
            facilities = self._discovery.find_facilities_with_stock(
                latitude=float(request["latitude"]),
                longitude=float(request["longitude"]),
                radius_km=radius_km,
                blood_group=donor_group,
                component=component,
                required_units=int(request["requiredUnits"]),
                now=now,
            )
            verdict = check_compatibility(
                recipient_group=recipient_group,
                donor_group=donor_group,
                component=component,
                reference=reference,
            )
            for facility in facilities:
                candidates.append(
                    {
                        "facilityId": facility["facilityId"],
                        "facilityName": facility["name"],
                        "organizationId": None,
                        "donorBloodGroup": donor_group.value,
                        "availability": facility["availability"],
                        "eligibleUnits": facility["eligibleUnits"],
                        "straightLineKm": facility["straightLineKm"],
                        "freshness": facility["freshness"],
                        "verificationStatus": facility["verificationStatus"],
                        "rankScore": facility.get("rankScore"),
                        "isIdenticalGroup": donor_group == recipient_group,
                        "requiresClinicalReview": verdict.requires_clinical_review,
                    }
                )

        # Deterministic ordering: identical group first, then rank, then distance.
        candidates.sort(
            key=lambda c: (
                not c["isIdenticalGroup"],
                -(c.get("rankScore") or 0),
                c["straightLineKm"],
            )
        )
        selected = candidates[:MAX_PROVIDERS_PER_REQUEST]

        for candidate in selected:
            facility = self._facilities.get_facility(candidate["facilityId"])
            provider_org = (facility or {}).get("organizationId")
            if not provider_org:
                continue
            candidate["organizationId"] = provider_org
            self._emergency.record_provider_notification(
                request_id=request_id,
                provider_org_id=provider_org,
                facility_id=candidate["facilityId"],
                now=now,
            )
            self._notify_provider(
                provider_org=provider_org,
                request=request,
                candidate=candidate,
                now=now,
                request_id=request_id,
            )

        if selected:
            self._emergency.transition(
                request_id=request_id,
                from_status=RequestStatus.MATCHING_INITIATED,
                to_status=RequestStatus.PROVIDERS_NOTIFIED,
                actor_id=context.actor_id,
                now=now,
                effective_priority=request.get("effectivePriority"),
                extra={"providersNotifiedCount": len(selected)},
            )

        log.info("matching complete", event="emergency.matched",
                 requestId=request_id, candidates=len(candidates), notified=len(selected))

        return {
            "requestId": request_id,
            "compatibilityRulesVersion": reference.version,
            "compatibilityReviewStatus": reference.review_status,
            "compatibleDonorGroups": [g.value for g in donor_groups],
            "candidatesConsidered": len(candidates),
            "providersNotified": len(selected),
            "candidates": selected,
            "notice": COORDINATION_NOTICE,
            "compatibilityDisclaimer": reference.disclaimer,
        }

    def _notify_provider(self, *, provider_org: str, request: dict, candidate: dict,
                         now: datetime, request_id: str) -> None:
        members = self._identity.list_members(provider_org)
        user_ids = [m["userId"] for m in members]
        priority = request.get("clinicalPriority") or "UNCERTIFIED"
        self._notifications.notify_many(
            user_ids=user_ids,
            category="PROVIDER_REQUEST",
            subject=f"[{priority}] Blood request: {request['bloodGroup']} {request['component']}",
            body=(
                f"A request for {request['requiredUnits']} unit(s) of "
                f"{request['bloodGroup']} {request['component']} has been routed to "
                f"{candidate['facilityName']}.\n\n"
                f"Required by: {request.get('requiredBy') or 'not specified'}\n"
                f"Compatible donor group offered: {candidate['donorBloodGroup']}\n\n"
                "Please respond in the LifeLink hospital dashboard.\n\n"
                + COORDINATION_NOTICE
            ),
            now=now,
            metadata={"requestId": request_id, "facilityId": candidate["facilityId"]},
            dedupe_prefix=f"provider-request#{request_id}",
        )

    # --- provider responses ---

    def submit_response(
        self,
        *,
        context: RequestContext,
        request_id: str,
        response_type: str,
        units_offered: int = 0,
        now: datetime,
        note: str | None = None,
    ) -> dict:
        """Record a provider's response.

        Revalidates stock before accepting an ACCEPTED response, so a provider
        cannot accept against stock that has already gone. The response records
        willingness only -- it never reserves units (ADR-0017).
        """
        log = get_logger(__name__, context)
        request = self._require_request(request_id)
        current = RequestStatus(request["status"])

        try:
            kind = ProviderResponseType(response_type.strip().upper())
        except ValueError:
            raise ValidationError(
                f"unknown response type '{response_type}'",
                details={"allowed": [r.value for r in ProviderResponseType]},
            ) from None

        if current in (RequestStatus.CANCELLED, RequestStatus.EXPIRED, RequestStatus.RESOLVED):
            # Spec 12.4: a late response must not revive a closed request.
            raise ValidationError(
                f"this request is {current.value} and no longer accepts responses",
                details={"status": current.value},
            )

        if context.organization_id is None:
            raise ForbiddenError("responding requires organization membership")

        # A provider may only respond for its own organization (spec 12.4).
        placeholder = self._emergency.get(
            f"REQUEST#{request_id}", f"RESPONSE#{context.organization_id}"
        )
        if placeholder is None:
            raise ForbiddenError(
                "your organization was not asked to respond to this request",
                details={"rule": "PROVIDER_NOT_NOTIFIED"},
            )

        if kind == ProviderResponseType.ACCEPTED:
            if units_offered <= 0:
                raise ValidationError("an accepted response must offer at least one unit")
            revalidated = self._revalidate_stock(
                facility_id=placeholder["facilityId"],
                blood_group=parse_group(request["bloodGroup"]),
                component=parse_component(request["component"]),
                required_units=units_offered,
                now=now,
            )
            if not revalidated["sufficient"]:
                log.warning("stock disappeared before acceptance",
                            event="emergency.stock.vanished", requestId=request_id)
                raise ValidationError(
                    "the stock backing this acceptance is no longer available",
                    details={
                        "rule": "STOCK_REVALIDATION_FAILED",
                        "eligibleUnitsNow": revalidated["eligibleUnits"],
                        "unitsOffered": units_offered,
                    },
                )

        self._emergency.submit_response(
            request_id=request_id,
            provider_org_id=context.organization_id,
            response_type=kind.value,
            units_offered=units_offered,
            actor_id=context.actor_id,
            now=now,
            note=note,
        )

        if current == RequestStatus.PROVIDERS_NOTIFIED:
            self._emergency.transition(
                request_id=request_id,
                from_status=current,
                to_status=RequestStatus.RESPONSES_RECEIVED,
                actor_id=context.actor_id,
                now=now,
                effective_priority=request.get("effectivePriority"),
            )

        self._audit.record(
            actor_id=context.actor_id,
            actor_role=",".join(context.principal.roles),
            action="EMERGENCY_PROVIDER_RESPONDED",
            resource_type="EMERGENCY_REQUEST",
            resource_id=request_id,
            organization_id=context.organization_id,
            correlation_id=context.correlation_id,
            occurred_at=now,
            after={"responseType": kind.value, "unitsOffered": units_offered},
        )

        responses = self._emergency.list_responses(request_id)
        tally = tally_responses([r for r in responses if r.get("responseType")])

        return {
            "requestId": request_id,
            "responseType": kind.value,
            "unitsOffered": units_offered,
            "tally": {
                "accepted": tally.accepted,
                "rejected": tally.rejected,
                "insufficient": tally.insufficient,
                "needsClarification": tally.clarification,
                "totalUnitsOffered": tally.units_offered,
            },
            "notice": (
                "An accepted response means the provider is willing to proceed. "
                "It is not a reservation, allocation or guarantee of fulfilment."
            ),
        }

    def _revalidate_stock(self, *, facility_id: str, blood_group, component,
                          required_units: int, now: datetime) -> dict:
        from domain.inventory import summarise_availability

        batches = self._inventory.list_eligible_batches(
            facility_id, blood_group, component, now=now
        )
        summary = summarise_availability(
            batches=batches,
            blood_group=blood_group,
            component=component,
            requested_units=required_units,
            now=now,
            inventory_known=True,
        )
        # eligible_units is None only when inventory is unreported, which
        # cannot happen here because inventory_known=True is passed above.
        # Guarded anyway, and guarded towards "not sufficient": an unknown
        # quantity must never satisfy a stock requirement.
        units = summary.eligible_units
        return {
            "sufficient": units is not None and units >= required_units,
            "eligibleUnits": units,
            "availability": summary.state.value,
        }

    # --- lifecycle ---

    def cancel_request(self, *, context: RequestContext, request_id: str, reason: str,
                       now: datetime) -> dict:
        request = self._require_request(request_id)
        current = RequestStatus(request["status"])

        if request.get("createdBy") != context.actor_id and (
            request.get("requesterOrganizationId") != context.organization_id
            and "PLATFORM_ADMIN" not in context.principal.roles
        ):
            raise ForbiddenError("this request belongs to another requester")

        assert_transition(current, RequestStatus.CANCELLED)
        self._emergency.transition(
            request_id=request_id,
            from_status=current,
            to_status=RequestStatus.CANCELLED,
            actor_id=context.actor_id,
            now=now,
            reason=reason,
        )
        self._audit.record(
            actor_id=context.actor_id,
            actor_role=",".join(context.principal.roles),
            action="EMERGENCY_REQUEST_CANCELLED",
            resource_type="EMERGENCY_REQUEST",
            resource_id=request_id,
            organization_id=request.get("requesterOrganizationId"),
            correlation_id=context.correlation_id,
            occurred_at=now,
            metadata={"reason": reason},
        )
        return {"requestId": request_id, "status": RequestStatus.CANCELLED.value}

    def confirm_availability(self, *, context: RequestContext, request_id: str,
                             now: datetime) -> dict:
        """Mark that availability has been confirmed with a provider.

        Stock is revalidated once more here, as spec 6.7 requires before any
        later confirmation or reservation workflow. Confirming availability
        records that a human confirmation took place; it does not itself hold
        units. A hold is a separate, explicit reservation.
        """
        request = self._require_request(request_id)
        current = RequestStatus(request["status"])
        assert_transition(current, RequestStatus.AVAILABILITY_CONFIRMED)

        accepted = [
            r for r in self._emergency.list_responses(request_id)
            if r.get("responseType") == ProviderResponseType.ACCEPTED.value
        ]
        if not accepted:
            raise ValidationError(
                "no provider has accepted this request",
                details={"rule": "NO_ACCEPTED_RESPONSE"},
            )

        revalidation = []
        for response in accepted:
            revalidation.append(
                {
                    "facilityId": response["facilityId"],
                    **self._revalidate_stock(
                        facility_id=response["facilityId"],
                        blood_group=parse_group(request["bloodGroup"]),
                        component=parse_component(request["component"]),
                        required_units=int(response.get("unitsOffered") or 0),
                        now=now,
                    ),
                }
            )

        self._emergency.transition(
            request_id=request_id,
            from_status=current,
            to_status=RequestStatus.AVAILABILITY_CONFIRMED,
            actor_id=context.actor_id,
            now=now,
        )
        return {
            "requestId": request_id,
            "status": RequestStatus.AVAILABILITY_CONFIRMED.value,
            "revalidation": revalidation,
            "notice": (
                "Availability was confirmed at this moment in time. Stock is not "
                "held and must be confirmed again at collection."
            ),
        }

    def resolve_request(self, *, context: RequestContext, request_id: str, outcome: str,
                        now: datetime) -> dict:
        request = self._require_request(request_id)
        current = RequestStatus(request["status"])
        assert_transition(current, RequestStatus.RESOLVED)
        self._emergency.transition(
            request_id=request_id,
            from_status=current,
            to_status=RequestStatus.RESOLVED,
            actor_id=context.actor_id,
            now=now,
            extra={"resolutionOutcome": outcome},
        )
        return {"requestId": request_id, "status": RequestStatus.RESOLVED.value,
                "outcome": outcome}

    def _expire(self, request_id: str, current: RequestStatus, now: datetime,
                actor_id: str) -> None:
        if current in (RequestStatus.CANCELLED, RequestStatus.EXPIRED, RequestStatus.RESOLVED):
            return
        self._emergency.transition(
            request_id=request_id,
            from_status=current,
            to_status=RequestStatus.EXPIRED,
            actor_id=actor_id,
            now=now,
            reason="required-by deadline passed",
        )

    # --- dispatcher (ADR-0006) ---

    def run_dispatcher(self, *, context: RequestContext, now: datetime,
                       batch_size: int = 10) -> dict:
        """Priority dispatcher with aging-based fairness.

        Recomputes ``effectivePriority`` for waiting requests, then processes in
        priority-then-FIFO order. ``clinicalPriority`` is never modified here --
        fairness must not alter clinical urgency.
        """
        log = get_logger(__name__, context)
        processed: list[dict] = []
        aged: list[dict] = []

        pending = self._emergency.list_dispatchable(
            status=RequestStatus.HOSPITAL_CERTIFIED.value, limit=batch_size * 3
        )

        for request in pending:
            clinical = request.get("clinicalPriority")
            if not clinical:
                continue
            created_at = parse_iso(request["createdAt"])
            required_by = parse_iso(request.get("requiredBy"))

            effective = compute_effective_priority(
                clinical_priority=ClinicalPriority(clinical),
                created_at=created_at,
                required_by=required_by,
                now=now,
            )
            if effective.value != request.get("effectivePriority"):
                self._emergency.update_effective_priority(
                    request_id=request["requestId"],
                    effective_priority=effective.value,
                    created_at=request["createdAt"],
                    status=request["status"],
                )
                aged.append(
                    {
                        "requestId": request["requestId"],
                        "clinicalPriority": clinical,  # unchanged
                        "effectivePriority": effective.value,
                    }
                )
            request["effectivePriority"] = effective.value

        pending.sort(
            key=lambda r: (
                {"P1": 0, "P2": 1, "P3": 2}.get(r.get("effectivePriority", "P3"), 2),
                r.get("createdAt", ""),
            )
        )

        for request in pending[:batch_size]:
            try:
                result = self.run_matching(
                    context=context, request_id=request["requestId"], now=now
                )
                processed.append(
                    {
                        "requestId": request["requestId"],
                        "effectivePriority": request.get("effectivePriority"),
                        "providersNotified": result.get("providersNotified", 0),
                    }
                )
            except Exception as exc:
                log.exception("dispatch failed", event="emergency.dispatch.failed",
                              requestId=request["requestId"], error=str(exc)[:200])

        log.info("dispatcher run complete", event="emergency.dispatch.complete",
                 considered=len(pending), processed=len(processed), aged=len(aged))
        return {
            "considered": len(pending),
            "processed": processed,
            "priorityAged": aged,
            "fairnessNote": (
                "Priority aging changes dispatch order only. Hospital-certified "
                "clinical priority is never modified by the scheduler."
            ),
        }

    def expire_overdue(self, *, context: RequestContext, now: datetime) -> dict:
        expired = 0
        for request in self._emergency.list_overdue(now=now):
            current = RequestStatus(request["status"])
            if current in (RequestStatus.CANCELLED, RequestStatus.EXPIRED,
                           RequestStatus.RESOLVED):
                continue
            try:
                self._expire(request["requestId"], current, now, actor_id="system")
                expired += 1
            except Exception:
                continue
        return {"expired": expired, "sweptAt": to_iso(now)}

    # --- reads ---

    def get_request(self, *, context: RequestContext, request_id: str) -> dict:
        full = self._emergency.load_full_request(request_id)
        if full is None:
            raise NotFoundError("request not found", details={"requestId": request_id})

        is_requester = full.get("createdBy") == context.actor_id or (
            full.get("requesterOrganizationId")
            and full.get("requesterOrganizationId") == context.organization_id
        )
        is_provider = any(
            r.get("providerOrganizationId") == context.organization_id
            for r in full.get("responses", [])
        )
        if not (is_requester or is_provider or "PLATFORM_ADMIN" in context.principal.roles):
            raise ForbiddenError("you do not have access to this request")

        tally = tally_responses([r for r in full.get("responses", []) if r.get("responseType")])
        payload = {
            "requestId": full["requestId"],
            "bloodGroup": full["bloodGroup"],
            "component": full["component"],
            "requiredUnits": full["requiredUnits"],
            "requiredBy": full.get("requiredBy"),
            "status": full["status"],
            "clinicalPriority": full.get("clinicalPriority"),
            "effectivePriority": full.get("effectivePriority"),
            "hospitalVerificationState": full.get("hospitalVerificationState"),
            "certifiedBy": full.get("certifiedBy"),
            "certifiedAt": full.get("certifiedAt"),
            "createdAt": full.get("createdAt"),
            "responses": [
                {
                    "providerOrganizationId": r.get("providerOrganizationId"),
                    "facilityId": r.get("facilityId"),
                    "responseType": r.get("responseType"),
                    "unitsOffered": r.get("unitsOffered"),
                    "respondedAt": r.get("respondedAt"),
                    "isReservation": False,
                }
                for r in full.get("responses", [])
            ],
            "timeline": [
                {
                    "eventType": e.get("eventType"),
                    "occurredAt": e.get("occurredAt"),
                    "actorId": e.get("actorId"),
                    "detail": e.get("detail"),
                }
                for e in full.get("events", [])
            ],
            "tally": {
                "accepted": tally.accepted,
                "rejected": tally.rejected,
                "insufficient": tally.insufficient,
                "needsClarification": tally.clarification,
                "totalUnitsOffered": tally.units_offered,
            },
            "notice": COORDINATION_NOTICE,
        }
        # Contact details are only for parties who need to act on them.
        if is_requester or is_provider:
            payload["contactName"] = full.get("contactName")
            payload["contactPhone"] = full.get("contactPhone")
        return payload

    def list_my_requests(self, *, context: RequestContext) -> list[dict]:
        if context.organization_id:
            return self._emergency.list_for_organization(context.organization_id)
        return []

    def list_provider_queue(self, *, context: RequestContext) -> list[dict]:
        if context.organization_id is None:
            return []
        return self._emergency.list_for_provider(context.organization_id)

    # --- helpers ---

    def _require_request(self, request_id: str) -> dict:
        request = self._emergency.get_request(request_id)
        if request is None:
            raise NotFoundError("request not found", details={"requestId": request_id})
        return request

    @staticmethod
    def _map_org_status(status: str | None) -> HospitalVerificationState:
        mapping = {
            OrganizationStatus.VERIFIED.value: HospitalVerificationState.VERIFIED,
            OrganizationStatus.REJECTED.value: HospitalVerificationState.REJECTED,
            OrganizationStatus.SUSPENDED.value: HospitalVerificationState.SUSPENDED,
        }
        return mapping.get(status or "", HospitalVerificationState.PENDING_VERIFICATION)

    @staticmethod
    def _fingerprint(*, actor_id: str, group: str, component: str, units: int,
                     latitude: float, longitude: float) -> str:
        """Fingerprint for duplicate detection.

        Coordinates are rounded so a few metres of GPS jitter does not defeat
        duplicate detection, but a genuinely different location still produces a
        different fingerprint.
        """
        import hashlib

        raw = f"{actor_id}|{group}|{component}|{units}|{latitude:.3f}|{longitude:.3f}"
        return hashlib.sha256(raw.encode()).hexdigest()[:24]


__all__ = ["EmergencyService", "COORDINATION_NOTICE", "timedelta"]
