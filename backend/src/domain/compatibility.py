"""Blood compatibility lookup (spec 6.5).

ADR-0008: the rules are versioned *data*, not code. This module only performs
table lookup. It never infers, never scores similarity, and never guesses.

A combination absent from the table resolves to UNKNOWN -- which the matching
engine treats as "do not match", not as "probably fine". The loader refuses to
start if the reference file lacks a review status, so an unreviewed table can
never be mistaken for a reviewed one.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from .blood import BloodGroup, Component
from .errors import ValidationError

REFERENCE_DIR = Path(__file__).resolve().parent.parent / "reference" / "compatibility"
DEFAULT_REFERENCE = "abo_rh_v1.json"


class CompatibilityVerdict(StrEnum):
    COMPATIBLE = "COMPATIBLE"
    INCOMPATIBLE = "INCOMPATIBLE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class CompatibilityResult:
    verdict: CompatibilityVerdict
    rules_version: str
    review_status: str
    identical_preferred: bool
    requires_clinical_review: bool
    disclaimer: str

    @property
    def is_match(self) -> bool:
        """Only an explicit COMPATIBLE counts. UNKNOWN never matches."""
        return self.verdict == CompatibilityVerdict.COMPATIBLE


@dataclass(frozen=True, slots=True)
class CompatibilityReference:
    version: str
    review_status: str
    reviewed_by: str | None
    source_citation: str
    disclaimer: str
    rules: dict[str, dict[str, list[str]]]
    identical_preferred: frozenset[str]

    def compatible_donor_groups(
        self, recipient: BloodGroup, component: Component
    ) -> tuple[str, ...] | None:
        """Donor groups acceptable for this recipient, or None if not in the table."""
        by_component = self.rules.get(component.value)
        if by_component is None:
            return None
        donors = by_component.get(recipient.value)
        if donors is None:
            return None
        return tuple(donors)


def _load_reference(filename: str) -> CompatibilityReference:
    path = REFERENCE_DIR / filename
    if not path.is_file():
        raise ValidationError(
            f"compatibility reference '{filename}' not found",
            details={"searched": str(path)},
        )
    data = json.loads(path.read_text(encoding="utf-8"))

    # Fail fast rather than silently treating an unlabelled table as authoritative.
    for required in ("version", "reviewStatus", "rules", "disclaimer"):
        if required not in data:
            raise ValidationError(
                f"compatibility reference is missing required field '{required}'",
                details={"file": filename},
            )

    return CompatibilityReference(
        version=data["version"],
        review_status=data["reviewStatus"],
        reviewed_by=data.get("reviewedBy"),
        source_citation=data.get("sourceCitation", ""),
        disclaimer=data["disclaimer"],
        rules=data["rules"],
        identical_preferred=frozenset(data.get("identicalPreferred", [])),
    )


@lru_cache(maxsize=4)
def get_reference(filename: str = DEFAULT_REFERENCE) -> CompatibilityReference:
    return _load_reference(filename)


def check_compatibility(
    *,
    recipient_group: BloodGroup,
    donor_group: BloodGroup,
    component: Component,
    reference: CompatibilityReference | None = None,
) -> CompatibilityResult:
    """Table lookup only. No inference of any kind."""
    ref = reference or get_reference()
    donors = ref.compatible_donor_groups(recipient_group, component)

    identical_preferred = component.value in ref.identical_preferred
    is_identical = recipient_group == donor_group

    if donors is None:
        verdict = CompatibilityVerdict.UNKNOWN
    elif donor_group.value in donors:
        verdict = CompatibilityVerdict.COMPATIBLE
    else:
        verdict = CompatibilityVerdict.INCOMPATIBLE

    requires_review = (
        verdict == CompatibilityVerdict.COMPATIBLE
        and identical_preferred
        and not is_identical
    )

    return CompatibilityResult(
        verdict=verdict,
        rules_version=ref.version,
        review_status=ref.review_status,
        identical_preferred=identical_preferred,
        requires_clinical_review=requires_review,
        disclaimer=ref.disclaimer,
    )


def compatible_donor_groups(
    *,
    recipient_group: BloodGroup,
    component: Component,
    reference: CompatibilityReference | None = None,
) -> tuple[BloodGroup, ...]:
    """Groups the matching engine may search for. Empty tuple when UNKNOWN.

    Returning empty rather than "all groups" on an unknown combination is the
    fail-closed behaviour the spec requires.
    """
    ref = reference or get_reference()
    donors = ref.compatible_donor_groups(recipient_group, component)
    if donors is None:
        return ()
    return tuple(BloodGroup(g) for g in donors)
