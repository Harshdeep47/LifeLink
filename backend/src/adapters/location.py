"""Location providers: geocoding and routing (spec 2.7, 4.5 -- ADR-0012).

Provider abstractions exist so routing and geocoding are not welded to one
vendor. Amazon Location Service is the implementation; MapLibre renders only and
supplies none of this.

The non-negotiable behaviours, enforced by the types:

* Straight-line distance and road distance are different fields and are never
  conflated.
* A routing failure degrades to ``RouteResult(available=False)``. It never
  returns a guessed distance or ETA, because a fabricated ETA in an emergency
  workflow is worse than no ETA.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol

from domain.errors import ProviderUnavailableError
from domain.geo import Coordinates, haversine_km


@dataclass(frozen=True, slots=True)
class Place:
    label: str
    coordinates: Coordinates
    locality: str | None = None
    region: str | None = None
    postal_code: str | None = None
    country: str | None = None
    relevance: float | None = None


@dataclass(frozen=True, slots=True)
class RouteResult:
    """A routing answer, or an explicit statement that routing is unavailable.

    ``available=False`` carries ``unavailable_reason`` and leaves the distance
    and duration as None. Callers must handle that instead of defaulting.
    """

    available: bool
    road_km: float | None = None
    duration_minutes: float | None = None
    unavailable_reason: str | None = None
    provider: str | None = None

    @property
    def is_estimate_only(self) -> bool:
        return not self.available


class GeocodingProvider(Protocol):
    def search_text(self, query: str, *, near: Coordinates | None = None,
                    limit: int = 5) -> list[Place]:
        ...

    def reverse(self, coordinates: Coordinates) -> Place | None:
        ...


class RoutingProvider(Protocol):
    def route(self, origin: Coordinates, destination: Coordinates) -> RouteResult:
        ...


class AmazonLocationProvider:
    """Amazon Location Service: Places for geocoding, Routes for road routing.

    Verified available in ap-southeast-2 and on the account's FREE plan during
    Phase 0. Calls are made from the backend so no provider credential reaches
    the browser.
    """

    name = "amazon-location"

    def __init__(self, *, place_index: str | None = None, route_calculator: str | None = None,
                 client=None):
        self._place_index = place_index or os.environ.get("LOCATION_PLACE_INDEX", "")
        self._route_calculator = route_calculator or os.environ.get(
            "LOCATION_ROUTE_CALCULATOR", ""
        )
        self._client = client

    def _location(self):
        if self._client is None:
            import boto3

            self._client = boto3.client(
                "location", region_name=os.environ.get("AWS_REGION", "ap-southeast-2")
            )
        return self._client

    def search_text(self, query: str, *, near: Coordinates | None = None,
                    limit: int = 5) -> list[Place]:
        if not self._place_index:
            raise ProviderUnavailableError("no place index is configured")
        request: dict = {
            "IndexName": self._place_index,
            "Text": query,
            "MaxResults": limit,
        }
        if near is not None:
            request["BiasPosition"] = [near.longitude, near.latitude]
        try:
            response = self._location().search_place_index_for_text(**request)
        except Exception as exc:
            raise ProviderUnavailableError(f"geocoding failed: {exc}") from exc

        places: list[Place] = []
        for result in response.get("Results", []):
            place = result.get("Place", {})
            point = place.get("Geometry", {}).get("Point")
            if not point or len(point) != 2:
                continue
            places.append(
                Place(
                    label=place.get("Label", query),
                    # Amazon Location returns [longitude, latitude].
                    coordinates=Coordinates(point[1], point[0]),
                    locality=place.get("Municipality"),
                    region=place.get("Region"),
                    postal_code=place.get("PostalCode"),
                    country=place.get("Country"),
                    relevance=result.get("Relevance"),
                )
            )
        return places

    def reverse(self, coordinates: Coordinates) -> Place | None:
        if not self._place_index:
            raise ProviderUnavailableError("no place index is configured")
        try:
            response = self._location().search_place_index_for_position(
                IndexName=self._place_index,
                Position=[coordinates.longitude, coordinates.latitude],
                MaxResults=1,
            )
        except Exception as exc:
            raise ProviderUnavailableError(f"reverse geocoding failed: {exc}") from exc

        results = response.get("Results", [])
        if not results:
            return None
        place = results[0].get("Place", {})
        return Place(
            label=place.get("Label", "Unknown location"),
            coordinates=coordinates,
            locality=place.get("Municipality"),
            region=place.get("Region"),
            postal_code=place.get("PostalCode"),
            country=place.get("Country"),
        )

    def route(self, origin: Coordinates, destination: Coordinates) -> RouteResult:
        """Road distance and ETA, or an explicit unavailable result.

        Every failure mode -- no calculator configured, no route found, provider
        outage, rate limit -- becomes an unavailable result with a reason, never
        an invented number.
        """
        if not self._route_calculator:
            return RouteResult(
                available=False,
                unavailable_reason="NO_ROUTE_CALCULATOR_CONFIGURED",
                provider=self.name,
            )
        try:
            response = self._location().calculate_route(
                CalculatorName=self._route_calculator,
                DeparturePosition=[origin.longitude, origin.latitude],
                DestinationPosition=[destination.longitude, destination.latitude],
                TravelMode="Car",
                DepartNow=True,
            )
        except Exception as exc:
            message = str(exc)
            reason = "PROVIDER_ERROR"
            if "ThrottlingException" in message or "TooManyRequests" in message:
                reason = "RATE_LIMITED"
            elif "ResourceNotFoundException" in message:
                reason = "CALCULATOR_NOT_FOUND"
            elif "ValidationException" in message:
                reason = "INVALID_COORDINATES"
            return RouteResult(
                available=False, unavailable_reason=reason, provider=self.name
            )

        summary = response.get("Summary", {})
        distance = summary.get("Distance")
        duration = summary.get("DurationSeconds")
        if distance is None or duration is None:
            return RouteResult(
                available=False, unavailable_reason="ROUTE_NOT_FOUND", provider=self.name
            )
        return RouteResult(
            available=True,
            road_km=round(float(distance), 2),
            duration_minutes=round(float(duration) / 60.0, 1),
            provider=self.name,
        )


class NullRoutingProvider:
    """Used locally and when routing is intentionally disabled.

    Returns an honest unavailable result. It deliberately does NOT substitute
    straight-line distance for road distance -- callers already have the
    straight-line figure and must label it as such.
    """

    name = "none"

    def route(self, origin: Coordinates, destination: Coordinates) -> RouteResult:
        return RouteResult(
            available=False,
            unavailable_reason="ROUTING_DISABLED_IN_THIS_ENVIRONMENT",
            provider=self.name,
        )


class StaticGeocodingProvider:
    """Offline geocoder for local development and tests.

    Resolves a small set of known Punjab/Chandigarh place names so the local
    app is usable without AWS. Unknown queries return no results rather than a
    plausible-looking guess.
    """

    name = "static-local"

    PLACES: dict[str, tuple[float, float, str]] = {
        "patiala": (30.3398, 76.3869, "Patiala, Punjab, India"),
        "chandigarh": (30.7333, 76.7794, "Chandigarh, India"),
        "jalandhar": (31.3260, 75.5762, "Jalandhar, Punjab, India"),
        "ludhiana": (30.9010, 75.8573, "Ludhiana, Punjab, India"),
        "amritsar": (31.6340, 74.8723, "Amritsar, Punjab, India"),
        "mohali": (30.7046, 76.7179, "Mohali, Punjab, India"),
        "panchkula": (30.6942, 76.8606, "Panchkula, Haryana, India"),
        "rajpura": (30.4844, 76.5944, "Rajpura, Punjab, India"),
        "nabha": (30.3752, 76.1526, "Nabha, Punjab, India"),
        "sangrur": (30.2458, 75.8421, "Sangrur, Punjab, India"),
    }

    def search_text(self, query: str, *, near: Coordinates | None = None,
                    limit: int = 5) -> list[Place]:
        needle = query.strip().lower()
        matches = [
            Place(
                label=label,
                coordinates=Coordinates(lat, lon),
                locality=name.title(),
                region="Punjab/Chandigarh",
                country="IND",
                relevance=1.0 if needle == name else 0.7,
            )
            for name, (lat, lon, label) in self.PLACES.items()
            if needle and needle in name
        ]
        matches.sort(key=lambda p: -(p.relevance or 0))
        return matches[:limit]

    def reverse(self, coordinates: Coordinates) -> Place | None:
        best: tuple[float, str, tuple[float, float, str]] | None = None
        for name, (lat, lon, label) in self.PLACES.items():
            distance = haversine_km(coordinates, Coordinates(lat, lon))
            if best is None or distance < best[0]:
                best = (distance, name, (lat, lon, label))
        if best is None or best[0] > 50.0:
            return None
        _, name, (lat, lon, label) = best
        return Place(
            label=label,
            coordinates=coordinates,
            locality=name.title(),
            region="Punjab/Chandigarh",
            country="IND",
        )


def build_location_providers(*, local_mode: bool):
    """Wire geocoding and routing for the current environment."""
    if local_mode:
        return StaticGeocodingProvider(), NullRoutingProvider()
    provider = AmazonLocationProvider()
    return provider, provider
