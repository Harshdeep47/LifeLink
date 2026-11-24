"""Short-term blood availability alerts (spec 3.7 -- a submodule of Feature 1).

An alert is informational. It never reserves, allocates or holds stock
(ADR-0017). The reverse index here is what makes "stock just arrived -- who was
waiting for it?" a bounded query rather than a scan over every open alert.
"""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from boto3.dynamodb.conditions import Attr, Key

from domain.blood import BloodGroup, Component
from domain.clock import to_iso
from domain.geo import encode_geohash

from .dynamo import DynamoRepository, Tables


class AlertStatus(StrEnum):
    ACTIVE = "ACTIVE"
    MATCHED = "MATCHED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    DEADLINE_PASSED = "DEADLINE_PASSED"


def _pk(alert_id: str) -> str:
    return f"ALERT#{alert_id}"


def match_key(geohash5: str, group: str, component: str) -> str:
    return f"MATCH#{geohash5}#{group}#{component}"


class AlertRepository(DynamoRepository):
    logical_table = Tables.ALERTS

    def get_alert(self, alert_id: str) -> dict | None:
        return self.get(_pk(alert_id), "META")

    def create_alert(self, alert: dict, *, now: datetime) -> dict:
        lat = float(alert["latitude"])
        lon = float(alert["longitude"])
        geohash5 = encode_geohash(lat, lon, 5)
        expires_at = alert["expiresAt"]

        item = {
            "PK": _pk(alert["alertId"]),
            "SK": "META",
            "entityType": "AVAILABILITY_ALERT",
            "status": AlertStatus.ACTIVE.value,
            "createdAt": to_iso(now),
            "geohash5": geohash5,
            "GSI1PK": f"USER#{alert['userId']}",
            "GSI1SK": f"{AlertStatus.ACTIVE.value}#{to_iso(now)}",
            # Reverse index: alerts waiting on this group+component near this cell.
            "GSI2PK": match_key(geohash5, alert["bloodGroup"], alert["component"]),
            "GSI2SK": f"{AlertStatus.ACTIVE.value}#{expires_at}",
            # TTL reaps expired alerts without a sweep job.
            "expiresAtEpoch": alert.get("expiresAtEpoch"),
            **alert,
        }
        self.put(item, condition=Attr("PK").not_exists())
        return item

    def list_for_user(self, user_id: str, *, active_only: bool = False,
                      limit: int = 50) -> list[dict]:
        condition = Key("GSI1PK").eq(f"USER#{user_id}")
        if active_only:
            condition = condition & Key("GSI1SK").begins_with(f"{AlertStatus.ACTIVE.value}#")
        items, _ = self.query(
            key_condition=condition, index_name="GSI1-user", limit=limit, scan_forward=False
        )
        return items

    def find_matching_alerts(
        self,
        *,
        geohash5: str,
        blood_group: BloodGroup,
        component: Component,
        now: datetime,
        limit: int = 100,
    ) -> list[dict]:
        """Active alerts for this group+component in this cell whose deadline has
        not yet passed.

        The sort key is ``ACTIVE#<expiresAt>``, so the range condition excludes
        expired alerts without a filter expression and without reading them.
        """
        lower = f"{AlertStatus.ACTIVE.value}#{to_iso(now)}"
        upper = f"{AlertStatus.ACTIVE.value}#9999-12-31T23:59:59Z"
        items, _ = self.query(
            key_condition=Key("GSI2PK").eq(match_key(geohash5, blood_group.value, component.value))
            & Key("GSI2SK").between(lower, upper),
            index_name="GSI2-match",
            limit=limit,
        )
        return items

    def set_status(self, alert_id: str, *, status: AlertStatus, now: datetime,
                   reason: str | None = None) -> dict:
        """Terminal statuses drop out of both indexes so they stop matching."""
        expression = (
            "SET #s = :s, statusUpdatedAt = :at, statusReason = :reason "
            "REMOVE GSI2PK, GSI2SK"
        )
        if status == AlertStatus.ACTIVE:
            expression = "SET #s = :s, statusUpdatedAt = :at, statusReason = :reason"

        return self.update(
            pk=_pk(alert_id),
            sk="META",
            update_expression=expression,
            expression_values={":s": status.value, ":at": to_iso(now), ":reason": reason},
            expression_names={"#s": "status"},
            condition=Attr("PK").exists(),
        )

    def record_match_notification(
        self, *, alert_id: str, facility_id: str, units: int, now: datetime,
        availability_state: str
    ) -> dict:
        """Append a match record.

        Stored for duplicate suppression and for the user's history. Explicitly
        marked as informational so no downstream reader can mistake it for a
        reservation.
        """
        item = {
            "PK": _pk(alert_id),
            "SK": f"MATCH#{to_iso(now)}#{facility_id}",
            "entityType": "ALERT_MATCH",
            "alertId": alert_id,
            "facilityId": facility_id,
            "unitsAtMatchTime": units,
            "availabilityState": availability_state,
            "matchedAt": to_iso(now),
            "isReservation": False,
            "notice": "Informational only. Stock is not held and may change at any time.",
        }
        self.put(item)
        return item

    def list_matches(self, alert_id: str, *, limit: int = 50) -> list[dict]:
        items, _ = self.query_partition(
            _pk(alert_id), sk_prefix="MATCH#", limit=limit, scan_forward=False
        )
        return items

    def has_recent_match(self, alert_id: str, facility_id: str) -> bool:
        """Duplicate suppression: has this alert already been matched to this facility?"""
        matches = self.list_matches(alert_id, limit=20)
        return any(m.get("facilityId") == facility_id for m in matches)
