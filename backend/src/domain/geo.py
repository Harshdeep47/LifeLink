"""Geospatial primitives: geohash encoding, neighbour cells, Haversine distance.

ADR-0004: discovery pre-filters by geohash cell (cheap, indexed) and then computes
exact distance (accurate). Querying only the centre cell is a classic correctness
bug -- a facility 500 m away can sit in an adjacent cell -- so neighbours are
always included. Spec 12.2 lists "facility at radius boundary" as a required case.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

_BASE32 = "0123456789bcdefghjkmnpqrstuvwxyz"
_DECODE = {ch: i for i, ch in enumerate(_BASE32)}

EARTH_RADIUS_KM = 6371.0088
MAX_SEARCH_RADIUS_KM = 100.0


@dataclass(frozen=True, slots=True)
class Coordinates:
    latitude: float
    longitude: float

    def __post_init__(self):
        if not (-90.0 <= self.latitude <= 90.0):
            raise ValueError(f"latitude {self.latitude} out of range")
        if not (-180.0 <= self.longitude <= 180.0):
            raise ValueError(f"longitude {self.longitude} out of range")


def encode_geohash(latitude: float, longitude: float, precision: int = 9) -> str:
    """Standard geohash encoding (base-32, interleaved lon/lat bits)."""
    if not (1 <= precision <= 12):
        raise ValueError("precision must be 1..12")
    lat_range = [-90.0, 90.0]
    lon_range = [-180.0, 180.0]
    out: list[str] = []
    bits = 0
    bit_count = 0
    even = True  # longitude first

    while len(out) < precision:
        if even:
            mid = (lon_range[0] + lon_range[1]) / 2
            if longitude > mid:
                bits = (bits << 1) | 1
                lon_range[0] = mid
            else:
                bits <<= 1
                lon_range[1] = mid
        else:
            mid = (lat_range[0] + lat_range[1]) / 2
            if latitude > mid:
                bits = (bits << 1) | 1
                lat_range[0] = mid
            else:
                bits <<= 1
                lat_range[1] = mid
        even = not even
        bit_count += 1
        if bit_count == 5:
            out.append(_BASE32[bits])
            bits = 0
            bit_count = 0
    return "".join(out)


def decode_geohash(geohash: str) -> tuple[float, float, float, float]:
    """Return the cell bounding box (lat_min, lat_max, lon_min, lon_max)."""
    lat_range = [-90.0, 90.0]
    lon_range = [-180.0, 180.0]
    even = True
    for ch in geohash.lower():
        if ch not in _DECODE:
            raise ValueError(f"invalid geohash character '{ch}'")
        value = _DECODE[ch]
        for mask in (16, 8, 4, 2, 1):
            bit = 1 if value & mask else 0
            target = lon_range if even else lat_range
            mid = (target[0] + target[1]) / 2
            if bit:
                target[0] = mid
            else:
                target[1] = mid
            even = not even
    return lat_range[0], lat_range[1], lon_range[0], lon_range[1]


def geohash_center(geohash: str) -> Coordinates:
    lat_min, lat_max, lon_min, lon_max = decode_geohash(geohash)
    return Coordinates((lat_min + lat_max) / 2, (lon_min + lon_max) / 2)


def neighbours(geohash: str) -> list[str]:
    """The eight surrounding cells at the same precision.

    Computed geometrically: step one cell width/height from the centre and re-encode.
    Simpler and less error-prone than the classic base-32 border/neighbour tables,
    and precision here is modest so the cost is irrelevant.
    """
    precision = len(geohash)
    lat_min, lat_max, lon_min, lon_max = decode_geohash(geohash)
    lat_step = lat_max - lat_min
    lon_step = lon_max - lon_min
    center = geohash_center(geohash)

    result: list[str] = []
    for d_lat in (1, 0, -1):
        for d_lon in (-1, 0, 1):
            if d_lat == 0 and d_lon == 0:
                continue
            lat = center.latitude + d_lat * lat_step
            lon = center.longitude + d_lon * lon_step
            if not (-90.0 <= lat <= 90.0):
                continue
            # Wrap longitude at the antimeridian.
            if lon > 180.0:
                lon -= 360.0
            elif lon < -180.0:
                lon += 360.0
            neighbour = encode_geohash(lat, lon, precision)
            if neighbour != geohash and neighbour not in result:
                result.append(neighbour)
    return result


MAX_SEARCH_CELLS = 150


def choose_precision(radius_km: float) -> int:
    """Pick a geohash precision whose cell size is comparable to the radius.

    Each cell costs one indexed query, so precision directly sets the fan-out of
    a search. Three tiers, each backed by its own GSI, with boundaries chosen so
    that the worst case in every tier stays well under MAX_SEARCH_CELLS:

        <= 3 km   precision 6  (~1.05 x 0.61 km cells)  worst case ~60 cells
        <= 20 km  precision 5  (~4.2 x 4.88 km cells)   worst case ~95 cells
        > 20 km   precision 4  (~33.8 x 19.5 km cells)  worst case ~71 cells

    The boundaries are deliberately lower than the cell size alone would
    suggest. Measured during integration testing, a 5 km search at precision 6
    needed 195 queries and a 100 km search at precision 5 needed 2,107 -- both
    untenable in general, and especially at this account's Lambda concurrency
    ceiling of 10.
    """
    if radius_km <= 3:
        return 6
    if radius_km <= 20:
        return 5
    return 4


def search_cells(latitude: float, longitude: float, radius_km: float) -> tuple[int, list[str]]:
    """Every cell that can contain a point within ``radius_km`` of the origin.

    Returns (precision, cells).

    This walks the bounding box of the search circle in cell-sized steps rather
    than returning only the centre cell's eight neighbours. The neighbour-only
    shortcut is correct only while the radius is smaller than one cell; beyond
    that it silently omits facilities that are genuinely in range, which in a
    blood search means a usable facility simply never appears. The cell set is
    always a superset of the true result, and exact Haversine filtering then
    removes the corners of the box.
    """
    if radius_km <= 0:
        raise ValueError("radius must be positive")
    if radius_km > MAX_SEARCH_RADIUS_KM:
        raise ValueError(f"radius exceeds maximum of {MAX_SEARCH_RADIUS_KM} km")

    precision = choose_precision(radius_km)
    center_hash = encode_geohash(latitude, longitude, precision)
    lat_min, lat_max, lon_min, lon_max = decode_geohash(center_hash)
    lat_step = lat_max - lat_min
    lon_step = lon_max - lon_min

    # Degrees of latitude/longitude spanned by the radius at this latitude.
    lat_degrees = radius_km / 110.574
    cos_lat = max(0.01, math.cos(math.radians(latitude)))
    lon_degrees = radius_km / (111.320 * cos_lat)

    lat_cells = int(math.ceil(lat_degrees / lat_step))
    lon_cells = int(math.ceil(lon_degrees / lon_step))

    cells: list[str] = [center_hash]
    seen = {center_hash}
    for i in range(-lat_cells, lat_cells + 1):
        for j in range(-lon_cells, lon_cells + 1):
            if i == 0 and j == 0:
                continue
            lat = latitude + i * lat_step
            lon = longitude + j * lon_step
            if not (-90.0 <= lat <= 90.0):
                continue
            if lon > 180.0:
                lon -= 360.0
            elif lon < -180.0:
                lon += 360.0

            # Skip cells whose nearest corner is still outside the circle --
            # these are the corners of the bounding box and can contain no
            # in-range point, so querying them would be pure waste.
            if not _cell_intersects_circle(
                lat, lon, precision, latitude, longitude, radius_km
            ):
                continue

            cell = encode_geohash(lat, lon, precision)
            if cell not in seen:
                seen.add(cell)
                cells.append(cell)

    if len(cells) > MAX_SEARCH_CELLS:
        # Defensive: the precision tiers keep this well under the limit, so
        # tripping it means a tier was mis-sized rather than a bad request.
        raise ValueError(
            f"search would require {len(cells)} cell queries "
            f"(limit {MAX_SEARCH_CELLS}); reduce the radius"
        )
    return precision, cells


def _cell_intersects_circle(
    cell_lat: float,
    cell_lon: float,
    precision: int,
    origin_lat: float,
    origin_lon: float,
    radius_km: float,
) -> bool:
    """Does the cell containing (cell_lat, cell_lon) reach within the radius?

    Uses the cell's closest corner, so the test never excludes a cell that
    contains an in-range point.
    """
    lat_min, lat_max, lon_min, lon_max = decode_geohash(
        encode_geohash(cell_lat, cell_lon, precision)
    )
    nearest_lat = min(max(origin_lat, lat_min), lat_max)
    nearest_lon = min(max(origin_lon, lon_min), lon_max)
    return (
        haversine_km(
            Coordinates(origin_lat, origin_lon), Coordinates(nearest_lat, nearest_lon)
        )
        <= radius_km
    )


def haversine_km(a: Coordinates, b: Coordinates) -> float:
    """Great-circle distance. This is STRAIGHT-LINE distance.

    Spec 4.5 forbids labelling it as road distance -- the API keeps
    ``straightLineKm`` and ``roadKm`` as separate fields for exactly this reason.
    """
    lat1, lon1 = math.radians(a.latitude), math.radians(a.longitude)
    lat2, lon2 = math.radians(b.latitude), math.radians(b.longitude)
    d_lat = lat2 - lat1
    d_lon = lon2 - lon1
    h = math.sin(d_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(d_lon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))


def within_radius(center: Coordinates, point: Coordinates, radius_km: float) -> bool:
    return haversine_km(center, point) <= radius_km
