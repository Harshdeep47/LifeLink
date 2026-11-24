"""Availability-aware facility ranking (spec 4.4).

Two rules the spec is emphatic about, both enforced structurally here:

1. Hard eligibility overrides the score. An ineligible facility is excluded, not
   ranked low -- so no weighting can ever float expired or quarantined stock to
   the top.
2. UNKNOWN stays UNKNOWN. Missing inventory is never coerced to zero (which would
   look like "we checked and there is none") nor to available.

The score is explainable: every result carries its component contributions so the
UI can show why something ranked where it did. It is not a clinical recommendation.
"""
from __future__ import annotations

from dataclasses import dataclass

from .blood import AvailabilityState, FreshnessLabel, VerificationStatus
from .freshness import freshness_score, verification_score


@dataclass(frozen=True, slots=True)
class RankingWeights:
    """The spec's proposed initial weighting. Configurable; must sum to 1.0."""

    availability: float = 0.30
    quantity: float = 0.15
    freshness: float = 0.20
    verification: float = 0.15
    distance: float = 0.20

    def __post_init__(self):
        total = (
            self.availability
            + self.quantity
            + self.freshness
            + self.verification
            + self.distance
        )
        if abs(total - 1.0) > 1e-9:
            raise ValueError(f"ranking weights must sum to 1.0, got {total}")


DEFAULT_WEIGHTS = RankingWeights()


@dataclass(frozen=True, slots=True)
class RankingInput:
    facility_id: str
    availability: AvailabilityState
    eligible_units: int | None
    requested_units: int
    freshness: FreshnessLabel
    verification: VerificationStatus
    distance_km: float
    search_radius_km: float


@dataclass(frozen=True, slots=True)
class RankedFacility:
    facility_id: str
    score: float
    availability: AvailabilityState
    components: dict[str, float]
    explanation: list[str]


def _availability_score(state: AvailabilityState) -> float:
    return {
        AvailabilityState.AVAILABLE: 1.0,
        AvailabilityState.PARTIAL: 0.5,
        AvailabilityState.UNAVAILABLE: 0.0,
        # UNKNOWN scores zero on this axis but is NOT treated as "none in stock";
        # the state itself is carried through to the response untouched.
        AvailabilityState.UNKNOWN: 0.0,
    }[state]


def _quantity_score(eligible: int | None, requested: int) -> float:
    if eligible is None or requested <= 0:
        return 0.0
    return min(1.0, eligible / requested)


def _distance_score(distance_km: float, radius_km: float) -> float:
    """Linear decay to the edge of the search radius. Nearer is better."""
    if radius_km <= 0:
        return 0.0
    return max(0.0, min(1.0, 1.0 - (distance_km / radius_km)))


def score_facility(item: RankingInput, weights: RankingWeights = DEFAULT_WEIGHTS) -> RankedFacility:
    availability = _availability_score(item.availability)
    quantity = _quantity_score(item.eligible_units, item.requested_units)
    fresh = freshness_score(item.freshness)
    verified = verification_score(item.verification)
    distance = _distance_score(item.distance_km, item.search_radius_km)

    components = {
        "availability": round(availability * weights.availability, 4),
        "quantity": round(quantity * weights.quantity, 4),
        "freshness": round(fresh * weights.freshness, 4),
        "verification": round(verified * weights.verification, 4),
        "distance": round(distance * weights.distance, 4),
    }
    total = round(sum(components.values()), 4)

    explanation: list[str] = []
    if item.availability == AvailabilityState.UNKNOWN:
        explanation.append("Inventory for this facility is unknown, not zero.")
    elif item.availability == AvailabilityState.PARTIAL:
        explanation.append(
            f"Partial stock: {item.eligible_units} of {item.requested_units} units."
        )
    if item.freshness in (FreshnessLabel.STALE, FreshnessLabel.OUTDATED):
        explanation.append(f"Inventory data is {item.freshness.value.lower()}.")
    if item.verification == VerificationStatus.UNVERIFIED:
        explanation.append("No independent verification on record.")
    explanation.append(f"{item.distance_km:.1f} km straight-line distance.")

    return RankedFacility(
        facility_id=item.facility_id,
        score=total,
        availability=item.availability,
        components=components,
        explanation=explanation,
    )


def rank_facilities(
    items: list[RankingInput], weights: RankingWeights = DEFAULT_WEIGHTS
) -> list[RankedFacility]:
    """Rank already-eligibility-filtered facilities, best first.

    Callers must filter out hard-ineligible facilities BEFORE calling this.
    Ties break on distance, then id, so ordering is deterministic and testable.
    """
    scored = [score_facility(i, weights) for i in items]
    by_id = {i.facility_id: i for i in items}
    scored.sort(key=lambda r: (-r.score, by_id[r.facility_id].distance_km, r.facility_id))
    return scored
