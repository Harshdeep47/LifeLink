"""Emergency requests, provider responses and lifecycle events.

The request, its responses and its transition history share one partition, so
loading a request for tracking is a single query. State transitions are written
with a condition on the current status, which makes the transition table in the
domain layer enforceable rather than advisory.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from boto3.dynamodb.conditions import Attr, Key

from domain.clock import to_iso
from domain.emergency import ClinicalPriority, RequestStatus

from .dynamo import DynamoRepository, Tables, clean, table_name, to_dynamo, transact_write

ACTIVE_DISPATCH_STATUSES = (
    RequestStatus.HOSPITAL_CERTIFIED.value,
    RequestStatus.MATCHING_INITIATED.value,
)


def _pk(request_id: str) -> str:
    return f"REQUEST#{request_id}"


class EmergencyRepository(DynamoRepository):
    logical_table = Tables.EMERGENCY

    # --- requests ---

    def get_request(self, request_id: str) -> dict | None:
        return self.get(_pk(request_id), "META")

    def get_request_consistent(self, request_id: str) -> dict | None:
        return self.get_consistent(_pk(request_id), "META")

    def load_full_request(self, request_id: str) -> dict | None:
        """Request, responses and events in one query (AP-25)."""
        items = self.query_partition(_pk(request_id))[0]
        if not items:
            return None
        meta = next((i for i in items if i["SK"] == "META"), None)
        if meta is None:
            return None
        return {
            **meta,
            "responses": [i for i in items if i["SK"].startswith("RESPONSE#")],
            "events": sorted(
                (i for i in items if i["SK"].startswith("EVENT#")),
                key=lambda e: e["SK"],
            ),
        }

    def create_request(self, request: dict, *, now: datetime) -> dict:
        request_id = request["requestId"]
        status = request.get("status", RequestStatus.REQUEST_CREATED.value)
        priority = request.get("effectivePriority", ClinicalPriority.P3.value)
        created = to_iso(now)

        item = {
            "PK": _pk(request_id),
            "SK": "META",
            "entityType": "EMERGENCY_REQUEST",
            "status": status,
            "createdAt": created,
            "GSI1PK": f"DISPATCH#{status}",
            "GSI1SK": f"{priority}#{created}",
            "GSI2PK": f"ORG#{request.get('requesterOrganizationId', 'NONE')}",
            "GSI2SK": f"REQUEST#{created}#{request_id}",
            "GSI4PK": "ACTIVE",
            "GSI4SK": request.get("requiredBy") or "9999-12-31T23:59:59Z",
            **request,
        }
        self.put(item, condition=Attr("PK").not_exists())
        self.append_event(
            request_id=request_id,
            event_type="REQUEST_CREATED",
            actor_id=request.get("createdBy", "system"),
            now=now,
            detail={"status": status},
        )
        return item

    def transition(
        self,
        *,
        request_id: str,
        from_status: RequestStatus,
        to_status: RequestStatus,
        actor_id: str,
        now: datetime,
        effective_priority: str | None = None,
        extra: dict | None = None,
        reason: str | None = None,
    ) -> dict:
        """Move a request to a new status, conditional on it still being in the old one.

        The condition is what prevents two concurrent workers from both advancing
        the same request, and what makes a late provider response unable to
        revive a cancelled request.
        """
        created = None
        set_parts = ["#s = :to", "statusUpdatedAt = :at", "statusUpdatedBy = :by"]
        # Every placeholder here must appear in the update expression. The
        # from-status guard lives in the ConditionExpression below, which builds
        # its own placeholders, so it must not be declared here.
        values: dict = {
            ":to": to_status.value,
            ":at": to_iso(now),
            ":by": actor_id,
        }
        names = {"#s": "status"}

        if to_status.value in ACTIVE_DISPATCH_STATUSES:
            existing = self.get_request(request_id)
            created = (existing or {}).get("createdAt") or to_iso(now)
            priority = effective_priority or (existing or {}).get(
                "effectivePriority", ClinicalPriority.P3.value
            )
            set_parts += ["GSI1PK = :gsi1pk", "GSI1SK = :gsi1sk"]
            values[":gsi1pk"] = f"DISPATCH#{to_status.value}"
            values[":gsi1sk"] = f"{priority}#{created}"
        else:
            # Terminal and non-dispatchable states leave the dispatch index so the
            # dispatcher never has to filter them out.
            pass

        if reason:
            set_parts.append("statusReason = :reason")
            values[":reason"] = reason

        for key, value in (extra or {}).items():
            placeholder = f":x_{key}"
            set_parts.append(f"{key} = {placeholder}")
            values[placeholder] = value

        expression = "SET " + ", ".join(set_parts)
        if to_status.value not in ACTIVE_DISPATCH_STATUSES:
            expression += " REMOVE GSI1PK, GSI1SK"

        updated = self.update(
            pk=_pk(request_id),
            sk="META",
            update_expression=expression,
            expression_values=values,
            expression_names=names,
            condition=Attr("status").eq(from_status.value),
        )

        self.append_event(
            request_id=request_id,
            event_type=f"TRANSITION_{to_status.value}",
            actor_id=actor_id,
            now=now,
            detail={"from": from_status.value, "to": to_status.value, "reason": reason},
        )
        return updated

    def certify_priority(
        self,
        *,
        request_id: str,
        clinical_priority: ClinicalPriority,
        actor_id: str,
        actor_role: str,
        organization_id: str,
        now: datetime,
    ) -> dict:
        """Record a hospital-certified clinical priority.

        Writes ``clinicalPriority`` plus the certifying actor, role, organization
        and timestamp. Nothing else in the system writes this field -- the
        scheduler only ever writes ``effectivePriority`` (ADR-0006).
        """
        return self.update(
            pk=_pk(request_id),
            sk="META",
            update_expression=(
                "SET clinicalPriority = :p, effectivePriority = :p, "
                "certifiedBy = :by, certifiedByRole = :role, "
                "certifyingOrganizationId = :org, certifiedAt = :at"
            ),
            expression_values={
                ":p": clinical_priority.value,
                ":by": actor_id,
                ":role": actor_role,
                ":org": organization_id,
                ":at": to_iso(now),
            },
            condition=Attr("PK").exists(),
        )

    def update_effective_priority(
        self, *, request_id: str, effective_priority: str, created_at: str, status: str
    ) -> dict:
        """Scheduler-only field. Never touches clinicalPriority."""
        return self.update(
            pk=_pk(request_id),
            sk="META",
            update_expression="SET effectivePriority = :p, GSI1SK = :sk",
            expression_values={
                ":p": effective_priority,
                ":sk": f"{effective_priority}#{created_at}",
            },
            condition=Attr("status").eq(status),
        )

    # --- dispatch queries ---

    def list_dispatchable(self, *, status: str, limit: int = 25) -> list[dict]:
        """Pending requests ordered by effective priority then age (AP-26)."""
        items, _ = self.query(
            key_condition=Key("GSI1PK").eq(f"DISPATCH#{status}"),
            index_name="GSI1-dispatch",
            limit=limit,
            scan_forward=True,
        )
        return items

    def list_overdue(self, *, now: datetime, limit: int = 50) -> list[dict]:
        items, _ = self.query(
            key_condition=Key("GSI4PK").eq("ACTIVE") & Key("GSI4SK").lt(to_iso(now)),
            index_name="GSI4-deadline",
            limit=limit,
        )
        return items

    def list_for_organization(self, organization_id: str, *, limit: int = 50) -> list[dict]:
        items, _ = self.query(
            key_condition=Key("GSI2PK").eq(f"ORG#{organization_id}"),
            index_name="GSI2-requester",
            limit=limit,
            scan_forward=False,
        )
        return items

    def list_for_provider(self, organization_id: str, *, limit: int = 50) -> list[dict]:
        items, _ = self.query(
            key_condition=Key("GSI3PK").eq(f"PROVIDER#{organization_id}"),
            index_name="GSI3-provider",
            limit=limit,
            scan_forward=False,
        )
        return items

    # --- provider responses ---

    def record_provider_notification(
        self, *, request_id: str, provider_org_id: str, facility_id: str, now: datetime
    ) -> dict:
        """A provider has been asked to respond. Creates the response placeholder."""
        item = {
            "PK": _pk(request_id),
            "SK": f"RESPONSE#{provider_org_id}",
            "GSI3PK": f"PROVIDER#{provider_org_id}",
            "GSI3SK": f"PENDING#{to_iso(now)}#{request_id}",
            "entityType": "PROVIDER_RESPONSE",
            "requestId": request_id,
            "providerOrganizationId": provider_org_id,
            "facilityId": facility_id,
            "responseType": None,
            "notifiedAt": to_iso(now),
            "status": "AWAITING_RESPONSE",
        }
        self.put(item)
        return item

    def submit_response(
        self,
        *,
        request_id: str,
        provider_org_id: str,
        response_type: str,
        units_offered: int,
        actor_id: str,
        now: datetime,
        note: str | None = None,
    ) -> dict:
        """Record a provider's response.

        ``unitsOffered`` is a statement of willingness, not a reservation -- it
        never decrements inventory (ADR-0017). Two providers may each offer the
        same count and both are recorded in full; nothing nets them against a
        shared counter because no such counter exists.

        The condition ensures a provider cannot respond twice, and that a
        provider who was never notified cannot respond at all.
        """
        updated = self.update(
            pk=_pk(request_id),
            sk=f"RESPONSE#{provider_org_id}",
            update_expression=(
                "SET responseType = :t, unitsOffered = :u, respondedAt = :at, "
                "respondedBy = :by, #s = :status, note = :note, GSI3SK = :gsi3sk"
            ),
            expression_values={
                ":t": response_type,
                ":u": units_offered,
                ":at": to_iso(now),
                ":by": actor_id,
                ":status": "RESPONDED",
                ":note": note,
                ":gsi3sk": f"RESPONDED#{to_iso(now)}#{request_id}",
            },
            expression_names={"#s": "status"},
            condition=Attr("SK").exists() & Attr("status").eq("AWAITING_RESPONSE"),
        )
        self.append_event(
            request_id=request_id,
            event_type="PROVIDER_RESPONDED",
            actor_id=actor_id,
            now=now,
            detail={
                "providerOrganizationId": provider_org_id,
                "responseType": response_type,
                "unitsOffered": units_offered,
            },
        )
        return updated

    def list_responses(self, request_id: str) -> list[dict]:
        items, _ = self.query_partition(_pk(request_id), sk_prefix="RESPONSE#")
        return items

    # --- lifecycle events ---

    def append_event(
        self, *, request_id: str, event_type: str, actor_id: str, now: datetime,
        detail: dict | None = None
    ) -> dict:
        event_id = str(uuid.uuid4())[:8]
        item = {
            "PK": _pk(request_id),
            "SK": f"EVENT#{to_iso(now)}#{event_id}",
            "entityType": "REQUEST_EVENT",
            "eventType": event_type,
            "actorId": actor_id,
            "occurredAt": to_iso(now),
            "detail": detail or {},
        }
        self.put(item)
        return item

    def create_request_with_outbox(self, request: dict, outbox_item: dict, *,
                                   now: datetime) -> dict:
        """Create a request and its creation event atomically (ADR-0005)."""
        request_id = request["requestId"]
        status = request.get("status", RequestStatus.REQUEST_CREATED.value)
        priority = request.get("effectivePriority", ClinicalPriority.P3.value)
        created = to_iso(now)
        item = {
            "PK": _pk(request_id),
            "SK": "META",
            "entityType": "EMERGENCY_REQUEST",
            "status": status,
            "createdAt": created,
            "GSI1PK": f"DISPATCH#{status}",
            "GSI1SK": f"{priority}#{created}",
            "GSI2PK": f"ORG#{request.get('requesterOrganizationId', 'NONE')}",
            "GSI2SK": f"REQUEST#{created}#{request_id}",
            "GSI4PK": "ACTIVE",
            "GSI4SK": request.get("requiredBy") or "9999-12-31T23:59:59Z",
            **request,
        }
        transact_write(
            [
                {
                    "Put": {
                        "TableName": table_name(self.logical_table),
                        "Item": to_dynamo(clean(item)),
                        "ConditionExpression": "attribute_not_exists(PK)",
                    }
                },
                {
                    "Put": {
                        "TableName": table_name(Tables.OUTBOX),
                        "Item": to_dynamo(clean(outbox_item)),
                    }
                },
            ]
        )
        return item
