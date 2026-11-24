"""Feature 2 -- location services, facility discovery and navigation.

Discovery is availability-aware: it reads stock through Feature 1's inventory
records rather than keeping its own. Three behaviours the spec requires and this
service guarantees:

* Hard eligibility filters run BEFORE ranking, so no weighting can surface
  ineligible stock.
* UNKNOWN inventory stays UNKNOWN all the way to the response.
* A routing failure never breaks discovery -- the list and contact details
  survive, and the response says directions are unavailable instead of
  substituting a straight-line figure.
"""
from __future__ import annotations

from datetime import datetime

from appcore.logging import get_logger
from domain.blood import AvailabilityState, BloodGroup, Component, parse_component, parse_group
from domain.clock import parse_iso, to_iso
from domain.errors import NotFoundError, ProviderUnavailableError, ValidationError
from domain.freshness import freshness_label, verification_status
from domain.geo import MAX_SEARCH_RADIUS_KM, Coordinates
from domain.inventory import summarise_availability
from domain.ranking import DEFAULT_WEIGHTS, RankingInput, RankingWeights, rank_facilities

DEFAULT_RADIUS_KM = 10.0


class DiscoveryService:
    def __init__(self, *, facility_repository, inventory_repository, geocoder, router,
                 reservation_service=None):
        self._facilities = facility_repository
        self._inventory = inventory_repository
        self._geocoder = geocoder
        self._router = router
        # Optional, and attached after construction by the container: held
        # units must be deducted here too, or search would offer units the
        # facility availability view already shows as reserved. Without this
        # the two endpoints disagree, and the one users actually look at is
        # the one that is wrong.
        self._reservations = reservation_service

    # --- facility discovery ---

    def search_facilities(
        self,
        *,
        latitude: float,
        longitude: float,
        now: datetime,
        radius_km: float = DEFAULT_RADIUS_KM,
        blood_group: str | None = None,
        component: str | None = None,
        requested_units: int = 1,
        only_available: bool = False,
        min_freshness: str | None = None,
        verified_only: bool = False,
        weights: RankingWeights | None = None,
        limit: int = 20,
        context=None,
    ) -> dict:
        log = get_logger(__name__, context)

        if radius_km <= 0:
            raise ValidationError("radius must be greater than zero")
        if radius_km > MAX_SEARCH_RADIUS_KM:
            raise ValidationError(
                f"radius cannot exceed {MAX_SEARCH_RADIUS_KM} km",
                details={"maximum": MAX_SEARCH_RADIUS_KM},
            )
        try:
            Coordinates(latitude, longitude)
        except ValueError as exc:
            raise ValidationError(str(exc)) from None

        group = parse_group(blood_group) if blood_group else None
        comp = parse_component(component) if component else None
        if (group is None) != (comp is None):
            raise ValidationError(
                "blood group and component must be supplied together",
                details={"reason": "availability is only meaningful for a specific pair"},
            )

        nearby = self._facilities.find_nearby(
            latitude=latitude, longitude=longitude, radius_km=radius_km
        )
        log.info("facility search", event="discovery.search",
                 radiusKm=radius_km, candidates=len(nearby))

        enriched: list[dict] = []
        ranking_inputs: list[RankingInput] = []

        for facility in nearby:
            facility_id = facility["facilityId"]
            inventory_known = bool(facility.get("inventoryKnown", False))
            last_updated = parse_iso(facility.get("inventoryLastUpdatedAt"))
            last_verified = parse_iso(facility.get("inventoryLastVerifiedAt"))
            fresh = freshness_label(last_updated, now)
            verified = verification_status(last_verified, now)

            if verified_only and verified.value != "VERIFIED":
                continue
            if min_freshness and not self._meets_freshness(fresh.value, min_freshness):
                continue

            availability = AvailabilityState.UNKNOWN
            eligible_units: int | None = None
            reserved_units = 0

            if group is not None and comp is not None:
                if inventory_known:
                    batches = self._inventory.list_eligible_batches(
                        facility_id, group, comp, now=now
                    )
                    summary = summarise_availability(
                        batches=batches,
                        blood_group=group,
                        component=comp,
                        requested_units=requested_units,
                        now=now,
                        inventory_known=True,
                    )
                    availability = summary.state
                    eligible_units = summary.eligible_units
                    if summary.freshness.value != "UNKNOWN":
                        fresh = summary.freshness

                    # Deduct temporary holds. A reserved unit must not be
                    # offered to the next searcher, and the state is
                    # recomputed from what is left rather than kept from the
                    # pre-deduction figure: holding the last 2 of 2 units
                    # makes the facility UNAVAILABLE, not AVAILABLE.
                    if self._reservations is not None:
                        free, held = self._reservations.adjust_availability(
                            facility_id, group, comp, eligible_units, now=now
                        )
                        reserved_units = held
                        if free is not None and held > 0:
                            eligible_units = free
                            if free <= 0:
                                availability = AvailabilityState.UNAVAILABLE
                            elif requested_units > 0 and free < requested_units:
                                availability = AvailabilityState.PARTIAL
                            else:
                                availability = AvailabilityState.AVAILABLE
                else:
                    # Never fabricate a zero for a facility that has not reported.
                    availability = AvailabilityState.UNKNOWN

                if only_available and availability not in (
                    AvailabilityState.AVAILABLE,
                    AvailabilityState.PARTIAL,
                ):
                    continue

            record = {
                "facilityId": facility_id,
                "name": facility.get("name"),
                "facilityType": facility.get("facilityType"),
                "address": facility.get("address"),
                "city": facility.get("city"),
                "latitude": float(facility["latitude"]),
                "longitude": float(facility["longitude"]),
                # Labelled unambiguously: this is NOT road distance.
                "straightLineKm": facility.get("straightLineKm"),
                "roadKm": None,
                "etaMinutes": None,
                "routingAvailable": False,
                "availability": availability.value,
                # Net of temporary holds; reservedUnits says how many were
                # deducted, so a user can see why a figure changed.
                "eligibleUnits": eligible_units,
                "reservedUnits": reserved_units,
                "inventoryKnown": inventory_known,
                "inventoryLastUpdatedAt": facility.get("inventoryLastUpdatedAt"),
                "freshness": fresh.value,
                "inventoryLastVerifiedAt": facility.get("inventoryLastVerifiedAt"),
                "verificationStatus": verified.value,
                "facilityVerificationStatus": facility.get("verificationStatus", "UNVERIFIED"),
                "contactPhone": facility.get("contactPhone"),
                "operatingHours": facility.get("operatingHours"),
                "demoData": facility.get("demoData", False),
            }
            enriched.append(record)
            ranking_inputs.append(
                RankingInput(
                    facility_id=facility_id,
                    availability=availability,
                    eligible_units=eligible_units,
                    requested_units=requested_units,
                    freshness=fresh,
                    verification=verified,
                    distance_km=float(facility.get("straightLineKm") or 0.0),
                    search_radius_km=radius_km,
                )
            )

        ranked = rank_facilities(ranking_inputs, weights or DEFAULT_WEIGHTS)
        by_id = {r["facilityId"]: r for r in enriched}
        ordered: list[dict] = []
        for entry in ranked[:limit]:
            record = by_id[entry.facility_id]
            record["rankScore"] = entry.score
            record["rankComponents"] = entry.components
            record["rankExplanation"] = entry.explanation
            ordered.append(record)

        return {
            "origin": {"latitude": latitude, "longitude": longitude},
            "radiusKm": radius_km,
            "bloodGroup": group.value if group else None,
            "component": comp.value if comp else None,
            "requestedUnits": requested_units,
            "totalCandidates": len(nearby),
            "results": ordered,
            "rankingWeights": {
                "availability": (weights or DEFAULT_WEIGHTS).availability,
                "quantity": (weights or DEFAULT_WEIGHTS).quantity,
                "freshness": (weights or DEFAULT_WEIGHTS).freshness,
                "verification": (weights or DEFAULT_WEIGHTS).verification,
                "distance": (weights or DEFAULT_WEIGHTS).distance,
            },
            "notice": (
                "Distances shown are straight-line unless a road distance is given. "
                "Ranking is an operational aid, not a clinical recommendation."
            ),
        }

    @staticmethod
    def _meets_freshness(actual: str, minimum: str) -> bool:
        order = {"FRESH": 0, "AGING": 1, "STALE": 2, "OUTDATED": 3, "UNKNOWN": 4}
        return order.get(actual, 4) <= order.get(minimum.upper(), 4)

    def get_facility_detail(self, *, facility_id: str, now: datetime) -> dict:
        facility = self._facilities.get_facility(facility_id)
        if facility is None:
            raise NotFoundError("facility not found", details={"facilityId": facility_id})
        last_updated = parse_iso(facility.get("inventoryLastUpdatedAt"))
        last_verified = parse_iso(facility.get("inventoryLastVerifiedAt"))
        return {
            "facilityId": facility_id,
            "name": facility.get("name"),
            "facilityType": facility.get("facilityType"),
            "organizationId": facility.get("organizationId"),
            "address": facility.get("address"),
            "city": facility.get("city"),
            "state": facility.get("state"),
            "latitude": float(facility["latitude"]),
            "longitude": float(facility["longitude"]),
            "contactPhone": facility.get("contactPhone"),
            "operatingHours": facility.get("operatingHours"),
            "verificationStatus": facility.get("verificationStatus", "UNVERIFIED"),
            "inventoryKnown": bool(facility.get("inventoryKnown", False)),
            "inventoryLastUpdatedAt": facility.get("inventoryLastUpdatedAt"),
            "freshness": freshness_label(last_updated, now).value,
            "inventoryLastVerifiedAt": facility.get("inventoryLastVerifiedAt"),
            "verificationFreshness": verification_status(last_verified, now).value,
            "demoData": facility.get("demoData", False),
        }

    # --- geocoding and routing ---

    def geocode(self, *, query: str, near: Coordinates | None = None,
                limit: int = 5) -> dict:
        if not query or not query.strip():
            raise ValidationError("a search term is required")
        try:
            places = self._geocoder.search_text(query, near=near, limit=limit)
        except ProviderUnavailableError as exc:
            return {
                "query": query,
                "results": [],
                "providerAvailable": False,
                "reason": exc.message,
                "notice": "Address search is temporarily unavailable. Enter coordinates manually.",
            }
        return {
            "query": query,
            "providerAvailable": True,
            "results": [
                {
                    "label": p.label,
                    "latitude": p.coordinates.latitude,
                    "longitude": p.coordinates.longitude,
                    "locality": p.locality,
                    "region": p.region,
                    "relevance": p.relevance,
                }
                for p in places
            ],
        }

    def route_to_facility(self, *, origin: Coordinates, facility_id: str) -> dict:
        """Road route and ETA, degrading honestly when routing is unavailable.

        The straight-line figure is always returned and always labelled as such.
        A failed route yields ``routingAvailable: false`` with a reason -- never a
        fabricated road distance (spec 2.7, 4.5).
        """
        facility = self._facilities.get_facility(facility_id)
        if facility is None:
            raise NotFoundError("facility not found", details={"facilityId": facility_id})

        from domain.geo import haversine_km

        destination = Coordinates(float(facility["latitude"]), float(facility["longitude"]))
        straight_line = round(haversine_km(origin, destination), 2)

        result = self._router.route(origin, destination)
        payload = {
            "facilityId": facility_id,
            "facilityName": facility.get("name"),
            "straightLineKm": straight_line,
            "routingAvailable": result.available,
            "provider": result.provider,
        }
        if result.available:
            payload.update({"roadKm": result.road_km, "etaMinutes": result.duration_minutes})
        else:
            payload.update(
                {
                    "roadKm": None,
                    "etaMinutes": None,
                    "unavailableReason": result.unavailable_reason,
                    "notice": (
                        "Road directions are unavailable right now. The distance shown "
                        "is straight-line only and does not reflect road travel."
                    ),
                }
            )
        return payload

    def find_facilities_with_stock(
        self,
        *,
        latitude: float,
        longitude: float,
        radius_km: float,
        blood_group: BloodGroup,
        component: Component,
        required_units: int,
        now: datetime,
    ) -> list[dict]:
        """Used by the emergency matching engine and alert matcher.

        Returns only facilities with genuinely eligible stock -- UNKNOWN is
        excluded here because matching must not route a request at a facility
        whose inventory is simply unreported.
        """
        outcome = self.search_facilities(
            latitude=latitude,
            longitude=longitude,
            now=now,
            radius_km=radius_km,
            blood_group=blood_group.value,
            component=component.value,
            requested_units=required_units,
            only_available=True,
            limit=50,
        )
        return [
            r
            for r in outcome["results"]
            if r["availability"] in (AvailabilityState.AVAILABLE.value,
                                     AvailabilityState.PARTIAL.value)
        ]


__all__ = ["DiscoveryService", "DEFAULT_RADIUS_KM", "to_iso"]
