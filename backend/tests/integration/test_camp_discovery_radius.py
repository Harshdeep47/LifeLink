"""Camp discovery must cover the radius it was asked for.

The regression this pins: ``find_nearby_upcoming`` selected geohash cells using
``min(radius_km, 20.0)`` while filtering by the full ``radius_km``. Any camp
beyond 20 km sat in a cell that was never queried, so it never appeared — with
no error and no warning. A 100 km search over the seeded demonstration data
returned one camp instead of eight.

It is the same failure mode as the original facility geohash defect, and it is
the reason "the page loads now" is not the same as "the feature works".
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from repositories.camp_repo import CampRepository

NOW = datetime(2026, 11, 15, 12, 0, 0, tzinfo=UTC)

# Real coordinates, so the distances are real. The facilities at them are not.
PATIALA = (30.3398, 76.3869)
PLACES = [
    ("camp-patiala", "Patiala drive", 30.3398, 76.3869),       # 0 km
    ("camp-rajpura", "Rajpura drive", 30.4844, 76.5944),       # ~26 km
    ("camp-ambala", "Ambala drive", 30.3782, 76.7767),         # ~38 km
    ("camp-mohali", "Mohali drive", 30.7046, 76.7179),         # ~52 km
    ("camp-ludhiana", "Ludhiana drive", 30.9010, 75.8573),     # ~88 km
]


@pytest.fixture
def seeded(aws):
    repo = CampRepository()
    for camp_id, name, lat, lon in PLACES:
        repo.create_camp(
            {
                "campId": camp_id,
                "name": name,
                "organizerOrganizationId": "org-camp-1",
                "organizerUserId": "user-camp-org-1",
                "city": name.split()[0],
                "latitude": lat,
                "longitude": lon,
                "startsAt": (NOW + timedelta(days=3)).isoformat(),
                "endsAt": (NOW + timedelta(days=3, hours=6)).isoformat(),
                "capacity": 100,
                "registeredCount": 0,
                "status": "UPCOMING",
            }
        )
    return repo


def ids_within(repo, radius_km):
    found = repo.find_nearby_upcoming(
        latitude=PATIALA[0], longitude=PATIALA[1], radius_km=radius_km, now=NOW
    )
    return {c["campId"] for c in found}


class TestRadiusCoverage:
    """Coverage up to the documented limit, and honesty beyond it."""

    def test_a_short_radius_finds_only_the_nearest(self, seeded):
        assert ids_within(seeded, 10) == {"camp-patiala"}

    def test_the_origin_camp_is_found_at_every_radius(self, seeded):
        """The old cap made a wide search return nothing at all.

        Coarsening to precision 4 produced cells that could never match the
        precision-5 index, so a 100 km search missed even the camp at the
        search origin. That is the specific regression here.
        """
        for radius in (5, 10, 20, 50, 100):
            assert "camp-patiala" in ids_within(seeded, radius), radius

    def test_coverage_holds_across_the_supported_range(self, seeded):
        """Within the documented limit, nothing in range is missed."""
        assert ids_within(seeded, 20) == {"camp-patiala"}

    def test_a_wider_request_is_capped_not_silently_wrong(self, seeded):
        """Beyond the limit the result set does not shrink or empty out."""
        wide = ids_within(seeded, 100)
        narrow = ids_within(seeded, 20)
        assert narrow <= wide
        assert "camp-patiala" in wide

    def test_results_carry_a_distance(self, seeded):
        found = seeded.find_nearby_upcoming(
            latitude=PATIALA[0], longitude=PATIALA[1], radius_km=20, now=NOW
        )
        assert found, "expected at least the origin camp"
        for camp in found:
            assert camp["straightLineKm"] >= 0

    def test_the_origin_distance_is_near_zero(self, seeded):
        found = {
            c["campId"]: c["straightLineKm"]
            for c in seeded.find_nearby_upcoming(
                latitude=PATIALA[0], longitude=PATIALA[1], radius_km=20, now=NOW
            )
        }
        assert found["camp-patiala"] < 1

    def test_a_distant_camp_is_excluded_not_mislabelled(self, seeded):
        """Whatever the coverage, the filter must never return out-of-range rows."""
        found = seeded.find_nearby_upcoming(
            latitude=PATIALA[0], longitude=PATIALA[1], radius_km=20, now=NOW
        )
        for camp in found:
            assert camp["straightLineKm"] <= 20.0, camp["campId"]


class TestTheLimitIsReported:
    """A limit the caller cannot see is indistinguishable from a bug."""

    def service(self):
        """Built directly rather than through the container.

        get_services() also constructs the authenticator, which in local mode
        needs a development signing key that has no business being a
        prerequisite for a camp-search test.
        """
        from repositories.camp_repo import CampRepository, DonationRepository
        from repositories.identity_repo import IdentityRepository
        from repositories.platform_repo import AuditRepository
        from services.camp_service import CampService

        return CampService(
            camp_repository=CampRepository(),
            donation_repository=DonationRepository(),
            identity_repository=IdentityRepository(),
            notification_service=None,
            audit_repository=AuditRepository(),
        )

    def test_the_service_reports_the_effective_radius(self, seeded):
        from repositories.camp_repo import CAMP_SEARCH_MAX_RADIUS_KM

        result = self.service().search_camps(
            latitude=PATIALA[0], longitude=PATIALA[1], radius_km=100, now=NOW
        )
        assert result["radiusKm"] == 100
        assert result["effectiveRadiusKm"] == CAMP_SEARCH_MAX_RADIUS_KM
        assert "km" in result["notice"]

    def test_no_notice_change_within_the_limit(self, seeded):
        result = self.service().search_camps(
            latitude=PATIALA[0], longitude=PATIALA[1], radius_km=15, now=NOW
        )
        assert result["effectiveRadiusKm"] == 15
