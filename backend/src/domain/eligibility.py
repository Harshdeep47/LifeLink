"""Operational eligibility of a stock batch (spec 3.4).

LifeLink filters *operationally* ineligible stock. It does not and cannot certify
clinical suitability -- release decisions belong to qualified personnel. Every
eligibility result therefore carries explicit reasons, so the UI can explain the
decision rather than presenting an opaque verdict.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .blood import BatchStatus


@dataclass(frozen=True, slots=True)
class EligibilityResult:
    eligible: bool
    reasons: tuple[str, ...] = field(default_factory=tuple)

    def with_reason(self, reason: str) -> EligibilityResult:
        return EligibilityResult(False, self.reasons + (reason,))


# Reason codes are part of the API contract.
REASON_EXPIRED = "BATCH_EXPIRED"
REASON_QUARANTINED = "BATCH_QUARANTINED"
REASON_WITHDRAWN = "BATCH_WITHDRAWN"
REASON_CONSUMED = "BATCH_CONSUMED"
REASON_NO_UNITS = "NO_UNITS_AVAILABLE"
REASON_MISSING_EXPIRY = "MISSING_EXPIRY_DATE"
REASON_INVALID_EXPIRY = "INVALID_EXPIRY_DATE"
REASON_NEGATIVE_UNITS = "NEGATIVE_UNITS"


def evaluate_batch_eligibility(
    *,
    status: BatchStatus | str,
    available_units: int | None,
    expires_at: datetime | None,
    collected_at: datetime | None,
    now: datetime,
    require_expiry: bool = True,
) -> EligibilityResult:
    """Decide whether a batch may be presented as available stock.

    Fails closed: anything ambiguous is ineligible. Spec 3.4 is explicit that
    invalid or missing dates must not silently produce eligible stock.
    """
    reasons: list[str] = []

    status = BatchStatus(status) if not isinstance(status, BatchStatus) else status

    if status == BatchStatus.QUARANTINED:
        reasons.append(REASON_QUARANTINED)
    elif status == BatchStatus.WITHDRAWN:
        reasons.append(REASON_WITHDRAWN)
    elif status == BatchStatus.CONSUMED:
        reasons.append(REASON_CONSUMED)
    elif status == BatchStatus.EXPIRED:
        reasons.append(REASON_EXPIRED)

    if available_units is None or available_units < 0:
        reasons.append(REASON_NEGATIVE_UNITS)
    elif available_units == 0:
        reasons.append(REASON_NO_UNITS)

    if expires_at is None:
        if require_expiry:
            reasons.append(REASON_MISSING_EXPIRY)
    else:
        if collected_at is not None and expires_at <= collected_at:
            # Expiry before collection is incoherent data, not merely expired stock.
            reasons.append(REASON_INVALID_EXPIRY)
        elif expires_at <= now and REASON_EXPIRED not in reasons:
            reasons.append(REASON_EXPIRED)

    return EligibilityResult(eligible=not reasons, reasons=tuple(reasons))


def is_near_expiry(expires_at: datetime | None, now: datetime, within_hours: float = 48.0) -> bool:
    """Near-expiry stock is still eligible but is flagged so staff can prioritise it."""
    if expires_at is None:
        return False
    remaining = (expires_at - now).total_seconds() / 3600.0
    return 0 < remaining <= within_hours
