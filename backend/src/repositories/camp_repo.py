"""Camps, registrations, attendance, donations and the impact ledger.

Two invariants here are enforced by DynamoDB transactions rather than by
application checks, because an application check cannot survive two concurrent
requests:

* A camp can never exceed capacity, even if the last seat is claimed twice at
  the same instant.
* A verified donation credits the impact ledger exactly once, even if the
  verification event is delivered twice.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from boto3.dynamodb.conditions import Attr, Key

from domain.clock import to_iso
from domain.errors import CapacityExceededError, DuplicateError
from domain.geo import encode_geohash

from .dynamo import (
    DynamoRepository,
    Tables,
    clean,
    table_name,
    to_dynamo,
    to_expression_values,
    transact_write,
)

#: Camps carry a single precision-5 geohash index, so discovery cannot be
#: widened beyond the span that precision covers without an unacceptable number
#: of queries. Reported to callers as effectiveRadiusKm.
CAMP_SEARCH_MAX_RADIUS_KM = 20.0


def _camp_pk(camp_id: str) -> str:
    return f"CAMP#{camp_id}"


class CampRepository(DynamoRepository):
    logical_table = Tables.CAMPS

    # --- camps ---

    def get_camp(self, camp_id: str) -> dict | None:
        return self.get(_camp_pk(camp_id), "META")

    def create_camp(self, camp: dict) -> dict:
        item = self._with_indexes(camp)
        self.put(item, condition=Attr("PK").not_exists())
        return item

    @staticmethod
    def _with_indexes(camp: dict) -> dict:
        lat = float(camp["latitude"])
        lon = float(camp["longitude"])
        starts_at = camp["startsAt"]
        item = dict(camp)
        item.update(
            {
                "PK": _camp_pk(camp["campId"]),
                "SK": "META",
                "entityType": "CAMP",
                "geohash5": encode_geohash(lat, lon, 5),
                "GSI1PK": f"GEO#{encode_geohash(lat, lon, 5)}",
                # Sorting by status then start time lets one range query fetch
                # upcoming camps near a point without a filter expression.
                "GSI1SK": f"{camp.get('status', 'UPCOMING')}#{starts_at}",
                "GSI3PK": f"ORG#{camp['organizerOrganizationId']}",
                "GSI3SK": f"CAMP#{starts_at}#{camp['campId']}",
                # Reminder sweep index. Populated here rather than by callers,
                # because a camp that is missing from this index silently never
                # produces reminders -- and nothing else would reveal that.
                "GSI4PK": "REMINDER#WINDOW",
                "GSI4SK": starts_at,
            }
        )
        return item

    def list_camp_partition(self, camp_id: str) -> list[dict]:
        """Camp metadata, registrations and staff in a single query (AP-16)."""
        items, _ = self.query_partition(_camp_pk(camp_id))
        return items

    def find_nearby_upcoming(
        self, *, latitude: float, longitude: float, radius_km: float, now: datetime
    ) -> list[dict]:
        from domain.geo import Coordinates, haversine_km, search_cells

        # Camps are indexed at ONE geohash precision (5, see _with_indexes),
        # unlike facilities which carry three indexes and can be searched at
        # whatever precision the radius calls for.
        #
        # search_cells coarsens to precision 4 beyond 20 km, and a precision-4
        # cell never matches a precision-5 key, so a wider search previously
        # found *nothing at all* -- including camps at the search origin. The
        # 20 km cap that used to be here was hiding that, badly: it kept the
        # precision aligned but left the distance filter using the full radius,
        # so a 100 km search silently returned only the camps within 20 km.
        #
        # Covering 100 km with precision-5 cells would need roughly 1,600
        # queries, so the real fix is a second, coarser camp geo index. Until
        # that exists the cap stays -- but it is now reported to the caller as
        # effectiveRadiusKm rather than being applied invisibly. Recorded in
        # docs/KNOWN_LIMITATIONS.md.
        effective_radius = min(radius_km, CAMP_SEARCH_MAX_RADIUS_KM)
        _, cells = search_cells(latitude, longitude, effective_radius)
        origin = Coordinates(latitude, longitude)
        found: dict[str, dict] = {}

        for cell in cells:
            items = self.query_all(
                key_condition=Key("GSI1PK").eq(f"GEO#{cell}"),
                index_name="GSI1-geo",
            )
            for item in items:
                if item.get("entityType") != "CAMP":
                    continue
                if item.get("status") not in ("UPCOMING", "ONGOING"):
                    continue
                camp_id = item.get("campId")
                if not camp_id or camp_id in found:
                    continue
                try:
                    point = Coordinates(float(item["latitude"]), float(item["longitude"]))
                except (KeyError, TypeError, ValueError):
                    continue
                distance = haversine_km(origin, point)
                if distance <= effective_radius:
                    enriched = dict(item)
                    enriched["straightLineKm"] = round(distance, 2)
                    found[camp_id] = enriched

        return sorted(found.values(), key=lambda c: c["straightLineKm"])

    def list_by_organizer(self, organization_id: str) -> list[dict]:
        return self.query_all(
            key_condition=Key("GSI3PK").eq(f"ORG#{organization_id}"),
            index_name="GSI3-organizer",
        )

    def set_status(self, camp_id: str, *, status: str, starts_at: str, actor_id: str,
                   now: datetime, reason: str | None = None) -> dict:
        return self.update(
            pk=_camp_pk(camp_id),
            sk="META",
            update_expression=(
                "SET #s = :s, GSI1SK = :gsi1sk, statusChangedBy = :by, "
                "statusChangedAt = :at, statusReason = :reason"
            ),
            expression_values={
                ":s": status,
                ":gsi1sk": f"{status}#{starts_at}",
                ":by": actor_id,
                ":at": to_iso(now),
                ":reason": reason,
            },
            expression_names={"#s": "status"},
            condition=Attr("PK").exists(),
        )

    # --- registration ---

    def get_registration(self, camp_id: str, user_id: str) -> dict | None:
        return self.get(_camp_pk(camp_id), f"REG#{user_id}")

    def register_atomically(
        self,
        *,
        camp_id: str,
        user_id: str,
        capacity: int,
        now: datetime,
        registration: dict,
    ) -> dict:
        """Create the registration and increment the counter in one transaction.

        Two concurrent requests for the final seat cannot both succeed: the
        capacity condition is evaluated inside the transaction, so exactly one
        commits and the other is cancelled. A plain read-check-write would let
        both through.
        """
        camps_table = table_name(self.logical_table)
        item = {
            "PK": _camp_pk(camp_id),
            "SK": f"REG#{user_id}",
            "GSI2PK": f"USER#{user_id}",
            "GSI2SK": f"REG#{now.isoformat()}#{camp_id}",
            "entityType": "REGISTRATION",
            "campId": camp_id,
            "userId": user_id,
            "registeredAt": to_iso(now),
            "status": "REGISTERED",
            "attendanceStatus": "NOT_ATTENDED",
            **registration,
        }

        operations = [
            {
                "Put": {
                    "TableName": camps_table,
                    "Item": to_dynamo(clean(item)),
                    # Duplicate registration is impossible, not merely unlikely.
                    "ConditionExpression": "attribute_not_exists(SK)",
                }
            },
            {
                "Update": {
                    "TableName": camps_table,
                    "Key": to_dynamo({"PK": _camp_pk(camp_id), "SK": "META"}),
                    "UpdateExpression": "SET registeredCount = registeredCount + :one",
                    "ConditionExpression": (
                        "attribute_exists(PK) AND registeredCount < :capacity "
                        "AND #s IN (:upcoming, :ongoing)"
                    ),
                    "ExpressionAttributeNames": {"#s": "status"},
                    "ExpressionAttributeValues": to_expression_values(
                        {
                            ":one": 1,
                            ":capacity": capacity,
                            ":upcoming": "UPCOMING",
                            ":ongoing": "ONGOING",
                        }
                    ),
                }
            },
        ]

        try:
            transact_write(operations)
        except Exception as exc:
            existing = self.get_registration(camp_id, user_id)
            if existing is not None:
                raise DuplicateError(
                    "you are already registered for this camp",
                    details={"campId": camp_id},
                ) from exc
            raise CapacityExceededError(
                "this camp is full or no longer accepting registrations",
                details={"campId": camp_id},
            ) from exc

        return item

    def cancel_registration(self, *, camp_id: str, user_id: str, now: datetime) -> dict:
        """Cancel and free the seat atomically."""
        camps_table = table_name(self.logical_table)
        operations = [
            {
                "Update": {
                    "TableName": camps_table,
                    "Key": to_dynamo({"PK": _camp_pk(camp_id), "SK": f"REG#{user_id}"}),
                    "UpdateExpression": "SET #s = :cancelled, cancelledAt = :at",
                    "ConditionExpression": "#s = :registered",
                    "ExpressionAttributeNames": {"#s": "status"},
                    "ExpressionAttributeValues": to_expression_values(
                        {
                            ":cancelled": "CANCELLED_BY_USER",
                            ":registered": "REGISTERED",
                            ":at": to_iso(now),
                        }
                    ),
                }
            },
            {
                "Update": {
                    "TableName": camps_table,
                    "Key": to_dynamo({"PK": _camp_pk(camp_id), "SK": "META"}),
                    "UpdateExpression": "SET registeredCount = registeredCount - :one",
                    "ConditionExpression": "registeredCount > :zero",
                    "ExpressionAttributeValues": to_expression_values({":one": 1, ":zero": 0}),
                }
            },
        ]
        transact_write(operations)
        return {"campId": camp_id, "userId": user_id, "status": "CANCELLED_BY_USER"}

    def list_registrations_for_user(self, user_id: str, *, limit: int = 50) -> list[dict]:
        items, _ = self.query(
            key_condition=Key("GSI2PK").eq(f"USER#{user_id}")
            & Key("GSI2SK").begins_with("REG#"),
            index_name="GSI2-user",
            limit=limit,
            scan_forward=False,
        )
        return items

    def check_in(self, *, camp_id: str, user_id: str, actor_id: str, now: datetime) -> dict:
        """Attendance is a separate state from registration (spec 5.3)."""
        return self.update(
            pk=_camp_pk(camp_id),
            sk=f"REG#{user_id}",
            update_expression=(
                "SET attendanceStatus = :checked, checkedInAt = :at, checkedInBy = :by, "
                "#s = :status"
            ),
            # Only placeholders the expression actually references may be
            # declared; the condition below builds its own.
            expression_values={
                ":checked": "CHECKED_IN",
                ":at": to_iso(now),
                ":by": actor_id,
                ":status": "CHECKED_IN",
            },
            expression_names={"#s": "status"},
            # Idempotent: a double check-in is refused rather than overwriting.
            condition=Attr("attendanceStatus").ne("CHECKED_IN"),
        )

    # --- staff ---

    def assign_staff(self, *, camp_id: str, user_id: str, assigned_by: str,
                     now: datetime, permissions: list[str] | None = None) -> dict:
        item = {
            "PK": _camp_pk(camp_id),
            "SK": f"STAFF#{user_id}",
            "entityType": "CAMP_STAFF",
            "campId": camp_id,
            "userId": user_id,
            "assignedBy": assigned_by,
            "assignedAt": to_iso(now),
            "permissions": permissions or ["CHECKIN", "VERIFY_DONATION"],
        }
        self.put(item)
        return item

    def is_camp_staff(self, camp_id: str, user_id: str) -> bool:
        """Staff are scoped to the camp they were assigned to (spec 5.7)."""
        return self.get(_camp_pk(camp_id), f"STAFF#{user_id}") is not None


class DonationRepository(DynamoRepository):
    logical_table = Tables.DONATIONS

    def get_donation(self, user_id: str, donation_id: str) -> dict | None:
        return self.get(f"USER#{user_id}", f"DONATION#{donation_id}")

    def record_donation(self, donation: dict, *, now: datetime) -> dict:
        item = {
            "PK": f"USER#{donation['donorId']}",
            "SK": f"DONATION#{donation['donationId']}",
            "GSI1PK": f"CAMP#{donation['campId']}",
            "GSI1SK": f"DONATION#{donation['donationId']}",
            "entityType": "DONATION",
            "status": "RECORDED",
            "recordedAt": to_iso(now),
            **donation,
        }
        self.put(item, condition=Attr("SK").not_exists())
        return item

    def verify_donation_and_credit(
        self,
        *,
        donor_id: str,
        donation_id: str,
        verifier_id: str,
        points: int,
        now: datetime,
    ) -> dict:
        """Verify the donation and write the ledger entry in one transaction.

        The ledger row is keyed on the donation id with a not-exists condition,
        so a replayed verification event cannot credit twice. This is the
        mechanism behind the spec's "credited exactly once" acceptance criterion.
        """
        donations_table = table_name(self.logical_table)
        timestamp = to_iso(now)

        operations = [
            {
                "Update": {
                    "TableName": donations_table,
                    "Key": to_dynamo({"PK": f"USER#{donor_id}", "SK": f"DONATION#{donation_id}"}),
                    "UpdateExpression": (
                        "SET #s = :verified, verifiedBy = :by, verifiedAt = :at"
                    ),
                    "ConditionExpression": "attribute_exists(SK) AND #s = :recorded",
                    "ExpressionAttributeNames": {"#s": "status"},
                    "ExpressionAttributeValues": to_expression_values(
                        {
                            ":verified": "VERIFIED",
                            ":recorded": "RECORDED",
                            ":by": verifier_id,
                            ":at": timestamp,
                        }
                    ),
                }
            },
            {
                "Put": {
                    "TableName": donations_table,
                    "Item": to_dynamo(
                        clean(
                            {
                                "PK": f"USER#{donor_id}",
                                "SK": f"LEDGER#{donation_id}",
                                "entityType": "LEDGER_ENTRY",
                                "donationId": donation_id,
                                "donorId": donor_id,
                                "points": points,
                                "reason": "VERIFIED_DONATION",
                                "occurredAt": timestamp,
                                "verifiedBy": verifier_id,
                            }
                        )
                    ),
                    "ConditionExpression": "attribute_not_exists(SK)",
                }
            },
        ]

        transact_write(operations)
        return {
            "donationId": donation_id,
            "donorId": donor_id,
            "status": "VERIFIED",
            "pointsAwarded": points,
            "verifiedAt": timestamp,
        }

    def list_donations(self, user_id: str, *, limit: int = 100) -> list[dict]:
        items, _ = self.query_partition(
            f"USER#{user_id}", sk_prefix="DONATION#", limit=limit, scan_forward=False
        )
        return items

    def list_ledger(self, user_id: str, *, limit: int = 500) -> list[dict]:
        items, _ = self.query_partition(f"USER#{user_id}", sk_prefix="LEDGER#", limit=limit)
        return items

    def list_camp_donations(self, camp_id: str) -> list[dict]:
        return self.query_all(
            key_condition=Key("GSI1PK").eq(f"CAMP#{camp_id}"),
            index_name="GSI1-camp",
        )


def reminder_windows(starts_at: datetime) -> list[tuple[str, datetime]]:
    """The reminder schedule from spec 5.5."""
    return [
        ("24H", starts_at - timedelta(hours=24)),
        ("2H", starts_at - timedelta(hours=2)),
    ]
