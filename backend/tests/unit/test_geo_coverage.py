"""Geohash cell coverage: the search cell set must never omit an in-range point.

This is the regression suite for a real bug found during integration testing:
returning only the centre cell and its eight neighbours silently dropped
facilities that were genuinely inside a larger search radius. In a blood search
that failure is invisible -- the user simply never sees a usable facility -- so
the property is asserted directly here rather than inferred.
"""
from __future__ import annotations

import math

import pytest

from domain.geo import (
    MAX_SEARCH_CELLS,
    Coordinates,
    choose_precision,
    encode_geohash,
    haversine_km,
    search_cells,
)

pytestmark = pytest.mark.unit

PATIALA = Coordinates(30.3398, 76.3869)
CHANDIGARH = Coordinates(30.7333, 76.7794)
RAJPURA = Coordinates(30.4844, 76.5944)
JALANDHAR = Coordinates(31.3260, 75.5762)


class TestCoverageProperty:
    """The cell set must be a superset of every in-range point."""

    @pytest.mark.parametrize("radius_km", [1, 3, 5, 10, 15, 20, 30, 50, 75, 100])
    def test_cell_set_covers_every_point_on_the_radius_boundary(self, radius_km):
        """Walk the circle at the search radius; each point's cell must be covered.

        Points exactly on the boundary are the hardest case and the ones a
        neighbour-only cell set gets wrong.
        """
        precision, cells = search_cells(PATIALA.latitude, PATIALA.longitude, radius_km)
        covered = set(cells)

        lat_degrees = radius_km / 110.574
        lon_degrees = radius_km / (111.320 * math.cos(math.radians(PATIALA.latitude)))

        missed = []
        for degrees in range(0, 360, 5):
            theta = math.radians(degrees)
            # Slightly inside the radius so the point is genuinely in range.
            lat = PATIALA.latitude + 0.999 * lat_degrees * math.sin(theta)
            lon = PATIALA.longitude + 0.999 * lon_degrees * math.cos(theta)
            cell = encode_geohash(lat, lon, precision)
            if cell not in covered:
                missed.append((degrees, cell))

        assert not missed, (
            f"radius {radius_km}km missed {len(missed)} bearings, "
            f"e.g. {missed[:3]}"
        )

    @pytest.mark.parametrize("radius_km", [2, 8, 25, 60])
    def test_cell_set_covers_interior_points(self, radius_km):
        precision, cells = search_cells(PATIALA.latitude, PATIALA.longitude, radius_km)
        covered = set(cells)
        lat_degrees = radius_km / 110.574
        lon_degrees = radius_km / (111.320 * math.cos(math.radians(PATIALA.latitude)))

        for fraction in (0.1, 0.4, 0.7, 0.95):
            for degrees in range(0, 360, 30):
                theta = math.radians(degrees)
                lat = PATIALA.latitude + fraction * lat_degrees * math.sin(theta)
                lon = PATIALA.longitude + fraction * lon_degrees * math.cos(theta)
                assert encode_geohash(lat, lon, precision) in covered


class TestRealWorldPairs:
    """Named demo-geography pairs, which is how the bug was actually noticed."""

    def test_rajpura_is_covered_from_patiala_at_30km(self):
        distance = haversine_km(PATIALA, RAJPURA)
        assert distance < 30, f"test premise: Rajpura should be under 30km, got {distance}"
        precision, cells = search_cells(PATIALA.latitude, PATIALA.longitude, 30)
        rajpura_cell = encode_geohash(RAJPURA.latitude, RAJPURA.longitude, precision)
        assert rajpura_cell in cells

    def test_chandigarh_is_covered_from_patiala_at_70km(self):
        distance = haversine_km(PATIALA, CHANDIGARH)
        assert distance < 70
        precision, cells = search_cells(PATIALA.latitude, PATIALA.longitude, 70)
        assert encode_geohash(CHANDIGARH.latitude, CHANDIGARH.longitude, precision) in cells

    def test_jalandhar_is_beyond_the_maximum_radius_from_patiala(self):
        """Documents a real limit rather than asserting a convenient fiction.

        Patiala to Jalandhar is about 135 km, past the 100 km ceiling, so a
        single search cannot span both. A user in Patiala must search from a
        Jalandhar-centred origin instead.
        """
        distance = haversine_km(PATIALA, JALANDHAR)
        assert distance > 100, f"expected over 100km, got {distance:.1f}km"

    def test_jalandhar_is_covered_from_its_own_origin(self):
        precision, cells = search_cells(JALANDHAR.latitude, JALANDHAR.longitude, 10)
        assert encode_geohash(JALANDHAR.latitude, JALANDHAR.longitude, precision) in cells

    def test_jalandhar_is_not_covered_from_patiala_at_5km(self):
        """Coverage must be a superset, not everything -- a tight search stays tight."""
        precision, cells = search_cells(PATIALA.latitude, PATIALA.longitude, 5)
        assert encode_geohash(JALANDHAR.latitude, JALANDHAR.longitude, precision) not in cells


class TestPrecisionAndBounds:
    def test_small_radius_uses_finer_precision(self):
        assert choose_precision(1) == 6
        assert choose_precision(3) == 6

    def test_medium_radius_uses_precision_five(self):
        assert choose_precision(3.1) == 5
        assert choose_precision(20) == 5

    def test_large_radius_uses_coarser_precision(self):
        assert choose_precision(20.1) == 4
        assert choose_precision(100) == 4

    def test_only_indexed_precisions_are_ever_returned(self):
        """Three geo indexes exist; the planner must not ask for a fourth."""
        for radius in (0.5, 1, 5, 5.5, 10, 25, 26, 50, 100):
            precision, _ = search_cells(PATIALA.latitude, PATIALA.longitude, radius)
            assert precision in (4, 5, 6)

    def test_centre_cell_is_always_first(self):
        precision, cells = search_cells(PATIALA.latitude, PATIALA.longitude, 25)
        assert cells[0] == encode_geohash(PATIALA.latitude, PATIALA.longitude, precision)

    def test_cells_are_unique(self):
        _, cells = search_cells(PATIALA.latitude, PATIALA.longitude, 40)
        assert len(cells) == len(set(cells))

    @pytest.mark.parametrize("radius_km", [1, 5, 10, 25, 50, 100])
    def test_cell_count_stays_bounded_at_every_radius(self, radius_km):
        """Fan-out must stay small -- each cell costs one indexed query.

        This is the test that caught a 2,107-cell search before the
        precision-4 tier existed.
        """
        _, cells = search_cells(PATIALA.latitude, PATIALA.longitude, radius_km)
        assert len(cells) <= MAX_SEARCH_CELLS, (
            f"radius {radius_km}km needs {len(cells)} cell queries"
        )

    def test_small_radius_produces_a_small_cell_set(self):
        _, cells = search_cells(PATIALA.latitude, PATIALA.longitude, 1)
        assert len(cells) <= 25

    def test_radius_above_maximum_is_rejected(self):
        with pytest.raises(ValueError):
            search_cells(PATIALA.latitude, PATIALA.longitude, 101)

    def test_works_near_the_equator_and_at_high_latitude(self):
        """Longitude degrees shrink with latitude; coverage must still hold."""
        for lat in (0.0, 45.0, 60.0, -33.87):
            precision, cells = search_cells(lat, 10.0, 25)
            lat_degrees = 25 / 110.574
            lon_degrees = 25 / (111.320 * math.cos(math.radians(lat)))
            for degrees in (0, 90, 180, 270):
                theta = math.radians(degrees)
                point_lat = lat + 0.99 * lat_degrees * math.sin(theta)
                point_lon = 10.0 + 0.99 * lon_degrees * math.cos(theta)
                assert encode_geohash(point_lat, point_lon, precision) in cells
