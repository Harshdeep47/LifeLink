"""Facility directory and geospatial discovery.

LifeLink owns its facility directory (spec 4.3). A map provider returning a
business listing does not make something a verified blood bank, so verification
state lives here and is only ever set by an administrator.
"""
from __future__ import annotations

from typing import Any

from boto3.dynamodb.conditions import Attr, Key

from domain.geo import Coordinates, encode_geohash, haversine_km, search_cells

from .dynamo import DynamoRepository, Tables


def _pk(facility_id: str) -> str:
    return f"FACILITY#{facility_id}"


class FacilityRepository(DynamoRepository):
    logical_table = Tables.FACILITIES

    def get_facility(self, facility_id: str) -> dict | None:
        return self.get(_pk(facility_id), "META")

    def get_many(self, facility_ids: list[str]) -> dict[str, dict]:
        """Fetch several facilities. Small N by construction (one search page)."""
        result: dict[str, dict] = {}
        for fid in facility_ids:
            item = self.get_facility(fid)
            if item:
                result[fid] = item
        return result

    def create_facility(self, facility: dict) -> dict:
        item = self._with_indexes(facility)
        self.put(item, condition=Attr("PK").not_exists())
        return item

    def upsert_facility(self, facility: dict) -> dict:
        item = self._with_indexes(facility)
        self.put(item)
        return item

    @staticmethod
    def _with_indexes(facility: dict) -> dict:
        """Derive geohash and index attributes from the facility's coordinates.

        Only the geohash precisions actually queried are stored -- the spec warns
        against keeping precise user coordinates unnecessarily, and the same
        restraint applies to anything derived from location.
        """
        lat = float(facility["latitude"])
        lon = float(facility["longitude"])
        item = dict(facility)
        item.update(
            {
                "PK": _pk(facility["facilityId"]),
                "SK": "META",
                "entityType": "FACILITY",
                "geohash": encode_geohash(lat, lon, 9),
                "geohash4": encode_geohash(lat, lon, 4),
                "geohash5": encode_geohash(lat, lon, 5),
                "geohash6": encode_geohash(lat, lon, 6),
                "GSI1PK": f"GEO#{encode_geohash(lat, lon, 5)}",
                "GSI1SK": f"FACILITY#{facility['facilityId']}",
                "GSI2PK": f"GEO#{encode_geohash(lat, lon, 6)}",
                "GSI2SK": f"FACILITY#{facility['facilityId']}",
                "GSI5PK": f"GEO#{encode_geohash(lat, lon, 4)}",
                "GSI5SK": f"FACILITY#{facility['facilityId']}",
                "GSI3PK": f"ORG#{facility['organizationId']}",
                "GSI3SK": f"FACILITY#{facility['facilityId']}",
                "GSI4PK": f"VERIFICATION#{facility.get('verificationStatus', 'UNVERIFIED')}",
                "GSI4SK": f"FACILITY#{facility['facilityId']}",
            }
        )
        return item

    def find_nearby(
        self, *, latitude: float, longitude: float, radius_km: float, max_results: int = 200
    ) -> list[dict]:
        """Geohash pre-filter across the centre cell and its eight neighbours,
        then exact Haversine distance (ADR-0004).

        Querying only the centre cell would silently drop facilities just across
        a grid line, which is why the neighbour set is not optional.
        """
        precision, cells = search_cells(latitude, longitude, radius_km)
        # One index per precision tier. The cell set already covers the whole
        # search circle, so there is no widening fallback and no silent gap.
        index, pk_attr = {
            6: ("GSI2-geo6", "GSI2PK"),
            5: ("GSI1-geo5", "GSI1PK"),
            4: ("GSI5-geo4", "GSI5PK"),
        }[precision]

        origin = Coordinates(latitude, longitude)
        seen: set[str] = set()
        results: list[dict] = []

        for cell in cells:
            items = self.query_all(
                key_condition=Key(pk_attr).eq(f"GEO#{cell}"),
                index_name=index,
                max_items=max_results,
            )
            for item in items:
                fid = item.get("facilityId")
                if not fid or fid in seen:
                    continue
                seen.add(fid)
                try:
                    point = Coordinates(float(item["latitude"]), float(item["longitude"]))
                except (KeyError, TypeError, ValueError):
                    # A facility with broken coordinates is skipped rather than
                    # crashing the search (spec 12.2: incorrect facility coordinates).
                    continue
                distance = haversine_km(origin, point)
                if distance <= radius_km:
                    enriched = dict(item)
                    enriched["straightLineKm"] = round(distance, 2)
                    results.append(enriched)

        results.sort(key=lambda f: f["straightLineKm"])
        return results[:max_results]

    def list_by_organization(self, organization_id: str) -> list[dict]:
        return self.query_all(
            key_condition=Key("GSI3PK").eq(f"ORG#{organization_id}"),
            index_name="GSI3-org",
        )

    def list_by_verification(self, status: str) -> list[dict]:
        return self.query_all(
            key_condition=Key("GSI4PK").eq(f"VERIFICATION#{status}"),
            index_name="GSI4-verification",
        )

    def set_verification(self, facility_id: str, *, status: str, actor_id: str,
                         verified_at: str) -> dict:
        return self.update(
            pk=_pk(facility_id),
            sk="META",
            update_expression=(
                "SET verificationStatus = :s, verifiedBy = :by, verifiedAt = :at, "
                "GSI4PK = :gsi"
            ),
            expression_values={
                ":s": status,
                ":by": actor_id,
                ":at": verified_at,
                ":gsi": f"VERIFICATION#{status}",
            },
        )

    def touch_inventory_timestamp(self, facility_id: str, *, updated_at: str) -> dict[str, Any]:
        """Record that this facility's inventory was updated.

        Deliberately does not touch ``lastVerifiedAt`` -- see ADR-0003.
        """
        return self.update(
            pk=_pk(facility_id),
            sk="META",
            update_expression="SET inventoryLastUpdatedAt = :at, inventoryKnown = :known",
            expression_values={":at": updated_at, ":known": True},
        )
