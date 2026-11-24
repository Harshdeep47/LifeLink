"""Geospatial filtering and availability-aware ranking.

Covers spec 4.3, 4.4 and the location edge cases -- in particular the boundary
case that a naive single-cell geohash query gets wrong.
"""
from __future__ import annotations

import pytest

from domain.blood import AvailabilityState, FreshnessLabel, VerificationStatus
from domain.geo import (
    Coordinates,
    decode_geohash,
    encode_geohash,
    haversine_km,
    neighbours,
    search_cells,
    within_radius,
)
from domain.ranking import RankingInput, RankingWeights, rank_facilities, score_facility

pytestmark = pytest.mark.unit

# Real coordinates from the demo geography (spec 11.1).
PATIALA = Coordinates(30.3398, 76.3869)
CHANDIGARH = Coordinates(30.7333, 76.7794)
JALANDHAR = Coordinates(31.3260, 75.5762)


class TestGeohash:
    def test_encoding_is_stable_and_correct_length(self):
        assert encode_geohash(PATIALA.latitude, PATIALA.longitude, 6) == "ttqkd5"
        assert len(encode_geohash(PATIALA.latitude, PATIALA.longitude, 9)) == 9

    def test_decode_bounding_box_contains_original_point(self):
        gh = encode_geohash(PATIALA.latitude, PATIALA.longitude, 7)
        lat_min, lat_max, lon_min, lon_max = decode_geohash(gh)
        assert lat_min <= PATIALA.latitude <= lat_max
        assert lon_min <= PATIALA.longitude <= lon_max

    def test_longer_prefix_is_contained_in_shorter(self):
        p9 = encode_geohash(PATIALA.latitude, PATIALA.longitude, 9)
        p5 = encode_geohash(PATIALA.latitude, PATIALA.longitude, 5)
        assert p9.startswith(p5)

    def test_invalid_character_is_rejected(self):
        with pytest.raises(ValueError):
            decode_geohash("abc!")

    def test_coordinates_out_of_range_are_rejected(self):
        with pytest.raises(ValueError):
            Coordinates(91.0, 0.0)
        with pytest.raises(ValueError):
            Coordinates(0.0, 181.0)


class TestNeighbourCells:
    def test_there_are_exactly_eight_neighbours(self):
        assert len(neighbours("ttqkd")) == 8

    def test_centre_cell_is_not_its_own_neighbour(self):
        assert "ttqkd" not in neighbours("ttqkd")

    def test_search_covers_the_whole_circle_not_just_the_neighbours(self):
        """A 20km search needs more than one cell ring at precision 5.

        Returning exactly nine cells would mean the radius was being ignored;
        see tests/unit/test_geo_coverage.py for the coverage property itself.
        """
        precision, cells = search_cells(PATIALA.latitude, PATIALA.longitude, 20)
        assert precision == 5
        assert len(cells) > 9
        assert cells[0] == encode_geohash(PATIALA.latitude, PATIALA.longitude, 5)

    def test_precision_coarsens_as_radius_grows(self):
        assert search_cells(PATIALA.latitude, PATIALA.longitude, 3)[0] == 6
        assert search_cells(PATIALA.latitude, PATIALA.longitude, 15)[0] == 5
        assert search_cells(PATIALA.latitude, PATIALA.longitude, 80)[0] == 4

    def test_excessive_radius_is_rejected(self):
        """Spec 12.2 lists 'excessively large search radius' as a required case."""
        with pytest.raises(ValueError):
            search_cells(PATIALA.latitude, PATIALA.longitude, 5000)

    def test_zero_or_negative_radius_is_rejected(self):
        with pytest.raises(ValueError):
            search_cells(PATIALA.latitude, PATIALA.longitude, 0)

    def test_neighbour_search_finds_point_just_across_a_cell_boundary(self):
        """The bug a single-cell query would cause.

        Pick a point, then step a tiny distance so it lands in a different cell.
        The neighbour set must still cover it, or nearby facilities vanish from
        results purely because of where a grid line happens to fall.
        """
        precision = 6
        base = encode_geohash(PATIALA.latitude, PATIALA.longitude, precision)
        lat_min, lat_max, lon_min, lon_max = decode_geohash(base)

        # A point just outside the eastern edge of the cell.
        just_outside = Coordinates(PATIALA.latitude, lon_max + 1e-6)
        other_cell = encode_geohash(just_outside.latitude, just_outside.longitude, precision)

        assert other_cell != base, "test point should be in a different cell"
        assert other_cell in neighbours(base)


class TestHaversine:
    def test_known_distance_patiala_to_chandigarh(self):
        # Ground truth is roughly 58 km straight-line.
        assert 55.0 < haversine_km(PATIALA, CHANDIGARH) < 61.0

    def test_distance_is_symmetric(self):
        assert haversine_km(PATIALA, JALANDHAR) == pytest.approx(
            haversine_km(JALANDHAR, PATIALA)
        )

    def test_distance_to_self_is_zero(self):
        assert haversine_km(PATIALA, PATIALA) == pytest.approx(0.0, abs=1e-9)

    def test_within_radius_boundary(self):
        d = haversine_km(PATIALA, CHANDIGARH)
        assert within_radius(PATIALA, CHANDIGARH, d + 0.001) is True
        assert within_radius(PATIALA, CHANDIGARH, d - 0.001) is False


def _rank_input(
    facility_id: str,
    *,
    availability=AvailabilityState.AVAILABLE,
    eligible_units=10,
    requested_units=5,
    freshness=FreshnessLabel.FRESH,
    verification=VerificationStatus.VERIFIED,
    distance_km=5.0,
    radius=20.0,
) -> RankingInput:
    return RankingInput(
        facility_id=facility_id,
        availability=availability,
        eligible_units=eligible_units,
        requested_units=requested_units,
        freshness=freshness,
        verification=verification,
        distance_km=distance_km,
        search_radius_km=radius,
    )


class TestRankingWeights:
    def test_default_weights_match_the_specification(self):
        w = RankingWeights()
        assert (w.availability, w.quantity, w.freshness, w.verification, w.distance) == (
            0.30, 0.15, 0.20, 0.15, 0.20
        )

    def test_weights_must_sum_to_one(self):
        with pytest.raises(ValueError):
            RankingWeights(availability=0.9, quantity=0.9, freshness=0.9,
                           verification=0.9, distance=0.9)


class TestRanking:
    def test_perfect_facility_scores_one(self):
        result = score_facility(
            _rank_input("f1", distance_km=0.0, eligible_units=100, requested_units=5)
        )
        assert result.score == pytest.approx(1.0)

    def test_fresher_data_outranks_stale_data_all_else_equal(self):
        fresh = _rank_input("fresh", freshness=FreshnessLabel.FRESH)
        stale = _rank_input("stale", freshness=FreshnessLabel.OUTDATED)
        ranked = rank_facilities([stale, fresh])
        assert ranked[0].facility_id == "fresh"

    def test_verified_outranks_unverified_all_else_equal(self):
        verified = _rank_input("v", verification=VerificationStatus.VERIFIED)
        unverified = _rank_input("u", verification=VerificationStatus.UNVERIFIED)
        ranked = rank_facilities([unverified, verified])
        assert ranked[0].facility_id == "v"

    def test_nearer_outranks_farther_all_else_equal(self):
        near = _rank_input("near", distance_km=1.0)
        far = _rank_input("far", distance_km=18.0)
        ranked = rank_facilities([far, near])
        assert ranked[0].facility_id == "near"

    def test_unknown_availability_is_labelled_unknown_in_the_result(self):
        """Ranking may score it zero, but it must not be relabelled as unavailable."""
        result = score_facility(_rank_input("u", availability=AvailabilityState.UNKNOWN))
        assert result.availability is AvailabilityState.UNKNOWN
        assert any("unknown, not zero" in e for e in result.explanation)

    def test_partial_availability_is_explained(self):
        result = score_facility(
            _rank_input("p", availability=AvailabilityState.PARTIAL,
                        eligible_units=2, requested_units=10)
        )
        assert any("Partial stock: 2 of 10" in e for e in result.explanation)

    def test_score_components_sum_to_total(self):
        result = score_facility(_rank_input("f"))
        assert sum(result.components.values()) == pytest.approx(result.score)

    def test_ranking_is_deterministic_for_identical_inputs(self):
        a = _rank_input("alpha")
        b = _rank_input("beta")
        first = [r.facility_id for r in rank_facilities([a, b])]
        second = [r.facility_id for r in rank_facilities([b, a])]
        assert first == second

    def test_every_result_carries_an_explanation(self):
        """Spec 4.4: explain ranking factors to the user."""
        for result in rank_facilities([_rank_input("a"), _rank_input("b", distance_km=9.0)]):
            assert result.explanation
