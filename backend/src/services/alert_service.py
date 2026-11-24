"""Short-term blood availability alerts -- a submodule of Feature 1 (spec 3.7).

An alert expresses a need and gets notified when matching stock appears. It is
NOT a reservation, allocation, clinical approval or guarantee (ADR-0017), and the
language in every response says so at the point where a user might assume
otherwise.

Matching reads inventory through Feature 1 and facilities through Feature 2. It
revalidates stock at notification time, because stock that existed when the
batch event fired may already be gone.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from ulid import ULID

from appcore.context import RequestContext
from appcore.logging import get_logger
from domain.blood import AvailabilityState, parse_component, parse_group
from domain.clock import to_iso
from domain.errors import ForbiddenError, NotFoundError, ValidationError
from domain.geo import Coordinates, encode_geohash
from repositories.alert_repo import AlertStatus

MAX_ALERT_LIFETIME_HOURS = 72
DEFAULT_ALERT_RADIUS_KM = 15.0
MAX_ALERT_RADIUS_KM = 50.0

INFORMATIONAL_NOTICE = (
    "This alert is informational only. Stock is not reserved or held for you, "
    "is not clinically approved for your use, and may change or become "
    "unavailable at any time. Always confirm directly with the facility."
)


class AlertService:
    def __init__(self, *, alert_repository, facility_repository, inventory_repository,
                 notification_service, audit_repository):
        self._alerts = alert_repository
        self._facilities = facility_repository
        self._inventory = inventory_repository
        self._notifications = notification_service
        self._audit = audit_repository

    def create_alert(
        self,
        *,
        context: RequestContext,
        blood_group: str,
        component: str,
        required_units: int,
        latitude: float,
        longitude: float,
        now: datetime,
        radius_km: float = DEFAULT_ALERT_RADIUS_KM,
        required_by: datetime | None = None,
        notify_channels: list[str] | None = None,
    ) -> dict:
        log = get_logger(__name__, context)
        group = parse_group(blood_group)
        comp = parse_component(component)

        if required_units <= 0:
            raise ValidationError("required units must be at least one")
        if radius_km <= 0 or radius_km > MAX_ALERT_RADIUS_KM:
            raise ValidationError(
                f"search radius must be between 1 and {MAX_ALERT_RADIUS_KM} km",
                details={"maximum": MAX_ALERT_RADIUS_KM},
            )
        try:
            Coordinates(latitude, longitude)
        except ValueError as exc:
            raise ValidationError(str(exc)) from None

        max_expiry = now + timedelta(hours=MAX_ALERT_LIFETIME_HOURS)
        if required_by is None:
            expires_at = now + timedelta(hours=24)
        elif required_by <= now:
            raise ValidationError("the required-by deadline is already in the past")
        else:
            expires_at = min(required_by, max_expiry)

        alert_id = str(ULID())
        alert = self._alerts.create_alert(
            {
                "alertId": alert_id,
                "userId": context.actor_id,
                "bloodGroup": group.value,
                "component": comp.value,
                "requiredUnits": required_units,
                "latitude": latitude,
                "longitude": longitude,
                "radiusKm": radius_km,
                "requiredBy": to_iso(required_by),
                "expiresAt": to_iso(expires_at),
                "expiresAtEpoch": int(expires_at.timestamp()),
                "notifyChannels": notify_channels or ["IN_APP"],
                "isReservation": False,
            },
            now=now,
        )

        self._audit.record(
            actor_id=context.actor_id,
            actor_role=",".join(context.principal.roles),
            action="ALERT_CREATED",
            resource_type="ALERT",
            resource_id=alert_id,
            correlation_id=context.correlation_id,
            occurred_at=now,
            after={"bloodGroup": group.value, "component": comp.value,
                   "requiredUnits": required_units},
        )
        log.info("availability alert created", event="alert.created", alertId=alert_id)

        # Match immediately so a user with stock already nearby is told at once.
        matches = self.match_alert(alert_id=alert_id, now=now, context=context)

        return {
            **self._present(alert),
            "immediateMatches": matches.get("matches", []),
            "notice": INFORMATIONAL_NOTICE,
        }

    def list_my_alerts(self, *, context: RequestContext, active_only: bool = False) -> list[dict]:
        alerts = self._alerts.list_for_user(context.actor_id, active_only=active_only)
        return [self._present(a) for a in alerts]

    def get_alert(self, *, context: RequestContext, alert_id: str) -> dict:
        alert = self._alerts.get_alert(alert_id)
        if alert is None:
            raise NotFoundError("alert not found", details={"alertId": alert_id})
        # Alerts are personal; ownership is checked here because the resource is
        # user-scoped rather than organization-scoped.
        if alert["userId"] != context.actor_id and "PLATFORM_ADMIN" not in context.principal.roles:
            raise ForbiddenError("this alert belongs to another user")
        return {
            **self._present(alert),
            "matches": self._alerts.list_matches(alert_id),
            "notice": INFORMATIONAL_NOTICE,
        }

    def cancel_alert(self, *, context: RequestContext, alert_id: str, now: datetime) -> dict:
        alert = self._alerts.get_alert(alert_id)
        if alert is None:
            raise NotFoundError("alert not found", details={"alertId": alert_id})
        if alert["userId"] != context.actor_id:
            raise ForbiddenError("this alert belongs to another user")
        if alert.get("status") != AlertStatus.ACTIVE.value:
            raise ValidationError(
                f"alert is already {alert.get('status')}",
                details={"status": alert.get("status")},
            )

        self._alerts.set_status(
            alert_id, status=AlertStatus.CANCELLED, now=now, reason="cancelled by user"
        )
        self._audit.record(
            actor_id=context.actor_id,
            actor_role=",".join(context.principal.roles),
            action="ALERT_CANCELLED",
            resource_type="ALERT",
            resource_id=alert_id,
            correlation_id=context.correlation_id,
            occurred_at=now,
        )
        return {"alertId": alert_id, "status": AlertStatus.CANCELLED.value}

    def match_alert(self, *, alert_id: str, now: datetime, context=None) -> dict:
        """Find facilities with eligible stock for one alert and notify once each.

        Stock is revalidated here rather than trusted from whatever event
        triggered the match, so a batch consumed in the meantime does not
        produce a notification about stock that no longer exists.
        """
        log = get_logger(__name__, context)
        alert = self._alerts.get_alert(alert_id)
        if alert is None:
            raise NotFoundError("alert not found", details={"alertId": alert_id})

        if alert.get("status") != AlertStatus.ACTIVE.value:
            return {"alertId": alert_id, "matches": [], "skipped": "ALERT_NOT_ACTIVE"}

        required_by = alert.get("requiredBy")
        if required_by:
            from domain.clock import parse_iso

            if parse_iso(required_by) <= now:
                self._alerts.set_status(
                    alert_id, status=AlertStatus.DEADLINE_PASSED, now=now,
                    reason="required-by deadline passed",
                )
                return {"alertId": alert_id, "matches": [], "skipped": "DEADLINE_PASSED"}

        group = parse_group(alert["bloodGroup"])
        comp = parse_component(alert["component"])
        required_units = int(alert["requiredUnits"])

        nearby = self._facilities.find_nearby(
            latitude=float(alert["latitude"]),
            longitude=float(alert["longitude"]),
            radius_km=float(alert.get("radiusKm", DEFAULT_ALERT_RADIUS_KM)),
        )

        matches: list[dict] = []
        for facility in nearby:
            facility_id = facility["facilityId"]
            if not facility.get("inventoryKnown"):
                continue  # unknown is not a match
            if self._alerts.has_recent_match(alert_id, facility_id):
                continue  # duplicate suppression

            from domain.inventory import summarise_availability

            batches = self._inventory.list_eligible_batches(facility_id, group, comp, now=now)
            summary = summarise_availability(
                batches=batches,
                blood_group=group,
                component=comp,
                requested_units=required_units,
                now=now,
                inventory_known=True,
            )
            if summary.state not in (AvailabilityState.AVAILABLE, AvailabilityState.PARTIAL):
                continue

            self._alerts.record_match_notification(
                alert_id=alert_id,
                facility_id=facility_id,
                units=summary.eligible_units,
                now=now,
                availability_state=summary.state.value,
            )
            matches.append(
                {
                    "facilityId": facility_id,
                    "facilityName": facility.get("name"),
                    "availability": summary.state.value,
                    "eligibleUnits": summary.eligible_units,
                    "requiredUnits": required_units,
                    "straightLineKm": facility.get("straightLineKm"),
                    "freshness": summary.freshness.value,
                    "isReservation": False,
                }
            )

        if matches:
            partial = any(m["availability"] == AvailabilityState.PARTIAL.value for m in matches)
            headline = (
                f"Partial match for {group.value} {comp.value}"
                if partial
                else f"{group.value} {comp.value} available nearby"
            )
            body_lines = [
                f"{len(matches)} facility/facilities near you report eligible "
                f"{group.value} {comp.value} stock.",
                "",
            ]
            for m in matches[:5]:
                body_lines.append(
                    f"- {m['facilityName']}: {m['eligibleUnits']} unit(s), "
                    f"{m['straightLineKm']} km (straight-line), data {m['freshness'].lower()}"
                )
            body_lines += ["", INFORMATIONAL_NOTICE]

            self._notifications.notify(
                user_id=alert["userId"],
                category="ALERT_MATCH",
                subject=headline,
                body="\n".join(body_lines),
                now=now,
                metadata={"alertId": alert_id, "matchCount": len(matches)},
                # One notification per alert per facility set, per hour.
                dedupe_key=f"alert-match#{alert_id}#{now.strftime('%Y%m%d%H')}",
            )
            log.info("alert matched", event="alert.matched",
                     alertId=alert_id, matchCount=len(matches))

        return {"alertId": alert_id, "matches": matches, "notice": INFORMATIONAL_NOTICE}

    def match_on_stock_change(self, *, facility_id: str, blood_group: str, component: str,
                              now: datetime, context=None) -> dict:
        """Reverse lookup: stock changed here -- who was waiting for it?

        Uses the alert match index (AP-10) so this is a bounded query rather than
        a scan over every open alert.
        """
        facility = self._facilities.get_facility(facility_id)
        if facility is None:
            return {"matched": 0, "reason": "FACILITY_NOT_FOUND"}

        geohash5 = encode_geohash(float(facility["latitude"]), float(facility["longitude"]), 5)
        group = parse_group(blood_group)
        comp = parse_component(component)

        candidates = self._alerts.find_matching_alerts(
            geohash5=geohash5, blood_group=group, component=comp, now=now
        )
        notified = 0
        for alert in candidates:
            outcome = self.match_alert(
                alert_id=alert["alertId"], now=now, context=context
            )
            if outcome.get("matches"):
                notified += 1
        return {"candidates": len(candidates), "notified": notified}

    def expire_due_alerts(self, *, now: datetime, context=None) -> dict:
        """TTL reaps rows, but statuses still need to settle for user-visible history."""
        return {
            "note": (
                "Alert expiry is primarily handled by DynamoDB TTL on expiresAtEpoch. "
                "This sweep exists for status accuracy in a user's alert history."
            ),
            "sweptAt": to_iso(now),
        }

    @staticmethod
    def _present(alert: dict) -> dict:
        return {
            "alertId": alert.get("alertId"),
            "userId": alert.get("userId"),
            "bloodGroup": alert.get("bloodGroup"),
            "component": alert.get("component"),
            "requiredUnits": alert.get("requiredUnits"),
            "radiusKm": alert.get("radiusKm"),
            "requiredBy": alert.get("requiredBy"),
            "expiresAt": alert.get("expiresAt"),
            "status": alert.get("status"),
            "createdAt": alert.get("createdAt"),
            "isReservation": False,
        }
