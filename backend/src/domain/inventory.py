"""Inventory batch operations and availability aggregation (spec Part 3).

Pure functions over batch state. The repository performs the actual conditional
writes; these functions decide *what* the new state should be and refuse to
produce an invalid one, so the rules are testable without a database.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum

from .blood import AvailabilityState, BatchStatus, BloodGroup, Component, FreshnessLabel
from .eligibility import evaluate_batch_eligibility, is_near_expiry
from .errors import InsufficientStockError, InvalidStateTransitionError, ValidationError
from .freshness import freshness_label, verification_status


class StockOperation(StrEnum):
    ADD = "ADD"
    DEDUCT = "DEDUCT"
    CORRECT = "CORRECT"
    QUARANTINE = "QUARANTINE"
    RELEASE_QUARANTINE = "RELEASE_QUARANTINE"
    WITHDRAW = "WITHDRAW"
    EXPIRE = "EXPIRE"


@dataclass(frozen=True, slots=True)
class Batch:
    batch_id: str
    facility_id: str
    organization_id: str
    blood_group: BloodGroup
    component: Component
    available_units: int
    status: BatchStatus
    collected_at: datetime | None
    expires_at: datetime | None
    last_updated_at: datetime
    last_verified_at: datetime | None
    update_source: str
    version: int
    quarantine_reason: str | None = None


@dataclass(frozen=True, slots=True)
class StockChange:
    """The decided outcome of an operation, ready for a conditional write."""

    batch: Batch
    units_delta: int
    operation: StockOperation
    previous_units: int
    previous_status: BatchStatus
    reason: str | None


def apply_stock_operation(
    *,
    batch: Batch,
    operation: StockOperation,
    units: int | None,
    now: datetime,
    source: str,
    reason: str | None = None,
) -> StockChange:
    """Compute the post-operation batch, refusing to produce an invalid state.

    Never allows a negative available quantity -- the spec forbids it outright,
    and the repository re-asserts it in a condition expression so a concurrent
    writer cannot slip past this check.
    """
    if operation in (StockOperation.ADD, StockOperation.DEDUCT, StockOperation.CORRECT):
        if units is None:
            raise ValidationError(f"{operation.value} requires a unit count")
        if units < 0:
            raise ValidationError("unit count cannot be negative")
        if operation != StockOperation.CORRECT and units == 0:
            raise ValidationError(f"{operation.value} requires a non-zero unit count")

    previous_units = batch.available_units
    previous_status = batch.status
    new_units = previous_units
    new_status = batch.status
    quarantine_reason = batch.quarantine_reason

    if operation == StockOperation.ADD:
        if batch.status != BatchStatus.AVAILABLE:
            raise InvalidStateTransitionError(
                f"cannot add units to a {batch.status.value} batch",
                details={"status": batch.status.value},
            )
        new_units = previous_units + units  # type: ignore[operator]

    elif operation == StockOperation.DEDUCT:
        if batch.status != BatchStatus.AVAILABLE:
            raise InvalidStateTransitionError(
                f"cannot deduct units from a {batch.status.value} batch",
                details={"status": batch.status.value},
            )
        if units > previous_units:  # type: ignore[operator]
            raise InsufficientStockError(
                f"cannot deduct {units} units; only {previous_units} available",
                details={"requested": units, "available": previous_units},
            )
        new_units = previous_units - units  # type: ignore[operator]
        if new_units == 0:
            new_status = BatchStatus.CONSUMED

    elif operation == StockOperation.CORRECT:
        # A correction sets an absolute value and is only for authorised staff
        # fixing a data error. It is audited distinctly from add/deduct.
        new_units = units  # type: ignore[assignment]
        if new_units == 0 and batch.status == BatchStatus.AVAILABLE:
            new_status = BatchStatus.CONSUMED
        elif new_units > 0 and batch.status == BatchStatus.CONSUMED:
            new_status = BatchStatus.AVAILABLE

    elif operation == StockOperation.QUARANTINE:
        if batch.status not in (BatchStatus.AVAILABLE,):
            raise InvalidStateTransitionError(
                f"cannot quarantine a {batch.status.value} batch"
            )
        if not reason:
            raise ValidationError("quarantine requires a reason")
        new_status = BatchStatus.QUARANTINED
        quarantine_reason = reason

    elif operation == StockOperation.RELEASE_QUARANTINE:
        if batch.status != BatchStatus.QUARANTINED:
            raise InvalidStateTransitionError("batch is not quarantined")
        # Releasing never resurrects expired stock.
        if batch.expires_at is not None and batch.expires_at <= now:
            new_status = BatchStatus.EXPIRED
        else:
            new_status = BatchStatus.AVAILABLE
        quarantine_reason = None

    elif operation == StockOperation.WITHDRAW:
        if batch.status in (BatchStatus.CONSUMED, BatchStatus.WITHDRAWN):
            raise InvalidStateTransitionError(
                f"cannot withdraw a {batch.status.value} batch"
            )
        new_status = BatchStatus.WITHDRAWN

    elif operation == StockOperation.EXPIRE:
        if batch.expires_at is None or batch.expires_at > now:
            raise InvalidStateTransitionError("batch has not reached its expiry time")
        new_status = BatchStatus.EXPIRED

    if new_units < 0:
        raise InsufficientStockError("operation would produce negative stock")

    updated = replace(
        batch,
        available_units=new_units,
        status=new_status,
        quarantine_reason=quarantine_reason,
        last_updated_at=now,
        update_source=source,
        version=batch.version + 1,
    )

    return StockChange(
        batch=updated,
        units_delta=new_units - previous_units,
        operation=operation,
        previous_units=previous_units,
        previous_status=previous_status,
        reason=reason,
    )


def is_stale_update(incoming_source_timestamp: datetime | None, stored_last_updated: datetime) -> bool:
    """Reject a delayed external update that would overwrite newer state (spec 3.6).

    A missing source timestamp is treated as stale: an external system that cannot
    say when its reading was taken must not be allowed to clobber a known-newer one.
    """
    if incoming_source_timestamp is None:
        return True
    return incoming_source_timestamp < stored_last_updated


@dataclass(frozen=True, slots=True)
class AvailabilitySummary:
    blood_group: BloodGroup
    component: Component
    state: AvailabilityState
    #: ``None`` -- never 0 -- when ``state`` is UNKNOWN.
    #:
    #: This was an ``int`` defaulting to 0 for an unreported facility, which
    #: quietly broke the system's first rule in one of two code paths: the
    #: search endpoint special-cased it and returned null, while the
    #: per-facility availability matrix published a 0. A client reading the
    #: matrix would show "0 units" for a facility that has never reported
    #: anything, which is the exact misreading the rule exists to prevent.
    #: Making the type admit None pushes the distinction into every caller
    #: rather than trusting each one to remember it.
    eligible_units: int | None
    batch_count: int
    freshness: FreshnessLabel
    near_expiry_units: int
    earliest_expiry: datetime | None


def summarise_availability(
    *,
    batches: list[Batch],
    blood_group: BloodGroup,
    component: Component,
    requested_units: int,
    now: datetime,
    inventory_known: bool = True,
) -> AvailabilitySummary:
    """Aggregate eligible stock for one (group, component) at one facility.

    ``inventory_known=False`` means this facility has never reported inventory.
    That produces UNKNOWN -- never zero. The spec is explicit that unknown must
    not be silently converted, because "we have no data" and "they have none"
    lead a user to completely different actions.
    """
    relevant = [
        b for b in batches if b.blood_group == blood_group and b.component == component
    ]

    if not inventory_known:
        return AvailabilitySummary(
            blood_group=blood_group,
            component=component,
            state=AvailabilityState.UNKNOWN,
            # Not 0. "We do not know" and "there are none" lead a user to
            # opposite actions: one calls the facility, the other does not.
            eligible_units=None,
            batch_count=0,
            freshness=FreshnessLabel.UNKNOWN,
            near_expiry_units=0,
            earliest_expiry=None,
        )

    eligible_units = 0
    near_expiry_units = 0
    expiries: list[datetime] = []
    newest_update: datetime | None = None
    eligible_batches = 0

    for b in relevant:
        result = evaluate_batch_eligibility(
            status=b.status,
            available_units=b.available_units,
            expires_at=b.expires_at,
            collected_at=b.collected_at,
            now=now,
        )
        if not result.eligible:
            continue
        eligible_batches += 1
        eligible_units += b.available_units
        if b.expires_at is not None:
            expiries.append(b.expires_at)
            if is_near_expiry(b.expires_at, now):
                near_expiry_units += b.available_units
        if newest_update is None or b.last_updated_at > newest_update:
            newest_update = b.last_updated_at

    if eligible_units == 0:
        state = AvailabilityState.UNAVAILABLE
    elif requested_units > 0 and eligible_units < requested_units:
        state = AvailabilityState.PARTIAL
    else:
        state = AvailabilityState.AVAILABLE

    # Freshness of the summary reflects the most recently updated relevant batch.
    # If nothing is eligible we still report the freshness of the underlying data
    # so the user can tell "stale data" apart from "genuinely none in stock".
    if newest_update is None and relevant:
        newest_update = max(b.last_updated_at for b in relevant)

    return AvailabilitySummary(
        blood_group=blood_group,
        component=component,
        state=state,
        eligible_units=eligible_units,
        batch_count=eligible_batches,
        freshness=freshness_label(newest_update, now),
        near_expiry_units=near_expiry_units,
        earliest_expiry=min(expiries) if expiries else None,
    )


def facility_verification_status(batches: list[Batch], now: datetime):
    """Most recent independent verification across a facility's batches."""
    verified_times = [b.last_verified_at for b in batches if b.last_verified_at is not None]
    latest = max(verified_times) if verified_times else None
    return verification_status(latest, now)
