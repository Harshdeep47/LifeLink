"""Blood groups and components.

Spec 3.2: all eight groups, four components, represented *separately*. A facility
is not assumed to stock every component.
"""
from __future__ import annotations

from enum import StrEnum


class BloodGroup(StrEnum):
    A_POS = "A+"
    A_NEG = "A-"
    B_POS = "B+"
    B_NEG = "B-"
    AB_POS = "AB+"
    AB_NEG = "AB-"
    O_POS = "O+"
    O_NEG = "O-"


class Component(StrEnum):
    WHOLE_BLOOD = "WHOLE_BLOOD"
    PRBC = "PRBC"
    FFP = "FFP"
    PLATELETS = "PLATELETS"


class BatchStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    QUARANTINED = "QUARANTINED"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"
    CONSUMED = "CONSUMED"


class VerificationStatus(StrEnum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    VERIFICATION_EXPIRED = "VERIFICATION_EXPIRED"


class FreshnessLabel(StrEnum):
    FRESH = "FRESH"
    AGING = "AGING"
    STALE = "STALE"
    OUTDATED = "OUTDATED"
    UNKNOWN = "UNKNOWN"


class AvailabilityState(StrEnum):
    """Spec 4.4: unknown must stay UNKNOWN -- never silently coerced to zero."""

    AVAILABLE = "AVAILABLE"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"
    UNKNOWN = "UNKNOWN"


ALL_GROUPS: tuple[BloodGroup, ...] = tuple(BloodGroup)
ALL_COMPONENTS: tuple[Component, ...] = tuple(Component)


def parse_group(value: str) -> BloodGroup:
    from .errors import ValidationError

    try:
        return BloodGroup(value.strip().upper())
    except ValueError:
        raise ValidationError(
            f"unknown blood group '{value}'",
            details={"allowed": [g.value for g in BloodGroup]},
        ) from None


def parse_component(value: str) -> Component:
    from .errors import ValidationError

    try:
        return Component(value.strip().upper())
    except ValueError:
        raise ValidationError(
            f"unknown component '{value}'",
            details={"allowed": [c.value for c in Component]},
        ) from None
