"""Feature 1 -- blood bank inventory management.

Feature 1 owns the authoritative inventory records (spec 3.1). Every other module
reads stock through this service; nothing else maintains competing stock numbers.

The service composes pure domain decisions with transactional persistence:
the domain decides what the new state should be and refuses invalid states, the
repository commits it under a condition that re-asserts the same invariants.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from ulid import ULID

from appcore.context import RequestContext
from appcore.logging import get_logger
from domain.blood import (
    ALL_COMPONENTS,
    ALL_GROUPS,
    BatchStatus,
    BloodGroup,
    Component,
    parse_component,
    parse_group,
)
from domain.clock import to_iso
from domain.eligibility import evaluate_batch_eligibility, is_near_expiry
from domain.errors import ConcurrentModificationError, NotFoundError, ValidationError
from domain.freshness import freshness_label, verification_status
from domain.inventory import (
    Batch,
    StockOperation,
    apply_stock_operation,
    is_stale_update,
    summarise_availability,
)
from repositories.inventory_repo import EXPIRY_SHARDS, expiry_shard

MAX_UNITS_PER_BATCH = 500


class InventoryService:
    def __init__(
        self,
        *,
        inventory_repository,
        facility_repository,
        audit_repository,
        outbox_repository,
        idempotency_repository,
        reservation_service=None,
    ):
        self._inventory = inventory_repository
        self._facilities = facility_repository
        self._audit = audit_repository
        self._outbox = outbox_repository
        self._idempotency = idempotency_repository
        # Optional so existing tests construct this service unchanged, and so
        # availability still works if reservations are not wired. When absent,
        # reservedUnits is 0 and unreservedUnits equals eligibleUnits -- the
        # behaviour before reservations existed.
        self._reservations = reservation_service

    # --- reads ---

    def get_batch(self, *, facility_id: str, batch_id: str, now: datetime) -> dict:
        batch = self._inventory.get_batch(facility_id, batch_id)
        if batch is None:
            raise NotFoundError("batch not found", details={"batchId": batch_id})
        return self._present_batch(batch, now)

    def list_batches(self, *, facility_id: str, now: datetime, limit: int = 100,
                     start_key: dict | None = None) -> tuple[list[dict], dict | None]:
        batches, next_key = self._inventory.list_batches(
            facility_id, limit=limit, start_key=start_key
        )
        return [self._present_batch(b, now) for b in batches], next_key

    def facility_availability(
        self,
        *,
        facility_id: str,
        now: datetime,
        groups: list[BloodGroup] | None = None,
        components: list[Component] | None = None,
        requested_units: int = 1,
    ) -> dict:
        """Availability matrix for one facility.

        ``inventoryKnown`` is read from the facility record. A facility that has
        never reported inventory yields UNKNOWN for every combination, never
        zero -- the distinction the spec insists on.
        """
        facility = self._facilities.get_facility(facility_id)
        if facility is None:
            raise NotFoundError("facility not found", details={"facilityId": facility_id})

        inventory_known = bool(facility.get("inventoryKnown", False))
        groups = groups or list(ALL_GROUPS)
        components = components or list(ALL_COMPONENTS)

        matrix: list[dict] = []
        for group in groups:
            for component in components:
                batches = (
                    self._inventory.list_eligible_batches(facility_id, group, component, now=now)
                    if inventory_known
                    else []
                )
                summary = summarise_availability(
                    batches=batches,
                    blood_group=group,
                    component=component,
                    requested_units=requested_units,
                    now=now,
                    inventory_known=inventory_known,
                )
                # Reserved units are deducted so a held unit is not offered
                # twice. reservedUnits is reported alongside, because a user
                # who can see *why* a figure dropped trusts it more than one
                # who just sees a smaller number.
                reserved = 0
                free = summary.eligible_units
                if self._reservations is not None and inventory_known:
                    free, reserved = self._reservations.adjust_availability(
                        facility_id, group, component, summary.eligible_units, now=now
                    )
                matrix.append(
                    {
                        "bloodGroup": group.value,
                        "component": component.value,
                        "availability": summary.state.value,
                        "eligibleUnits": summary.eligible_units,
                        "reservedUnits": reserved,
                        # None when the facility has never reported: unknown
                        # minus a hold is still unknown, not zero.
                        "unreservedUnits": free,
                        "batchCount": summary.batch_count,
                        "freshness": summary.freshness.value,
                        "nearExpiryUnits": summary.near_expiry_units,
                        "earliestExpiry": to_iso(summary.earliest_expiry),
                    }
                )

        last_updated = facility.get("inventoryLastUpdatedAt")
        last_verified = facility.get("inventoryLastVerifiedAt")
        from domain.clock import parse_iso

        return {
            "facilityId": facility_id,
            "facilityName": facility.get("name"),
            "inventoryKnown": inventory_known,
            # Separate concepts, separately reported (ADR-0003).
            "inventoryLastUpdatedAt": last_updated,
            "inventoryFreshness": freshness_label(parse_iso(last_updated), now).value,
            "inventoryLastVerifiedAt": last_verified,
            "verificationStatus": verification_status(parse_iso(last_verified), now).value,
            "availability": matrix,
            "disclaimer": (
                "Availability is reported by the facility and is not a clinical "
                "guarantee or a reservation. Confirm with the facility before travelling."
            ),
            "demoData": facility.get("demoData", False),
        }

    def audit_history(self, *, batch_id: str, limit: int = 50) -> list[dict]:
        return self._inventory.get_audit_history(batch_id, limit=limit)

    # --- writes ---

    def create_batch(
        self,
        *,
        context: RequestContext,
        facility_id: str,
        organization_id: str,
        blood_group: str,
        component: str,
        units: int,
        collected_at: datetime | None,
        expires_at: datetime | None,
        now: datetime,
        source: str = "MANUAL",
        demo: bool = False,
    ) -> dict:
        log = get_logger(__name__, context)
        group = parse_group(blood_group)
        comp = parse_component(component)

        if units <= 0:
            raise ValidationError("a new batch must have at least one unit")
        if units > MAX_UNITS_PER_BATCH:
            raise ValidationError(
                f"a single batch cannot exceed {MAX_UNITS_PER_BATCH} units",
                details={"maximum": MAX_UNITS_PER_BATCH},
            )
        if expires_at is None:
            raise ValidationError(
                "an expiry date is required",
                details={
                    "reason": "stock without an expiry date cannot be presented as eligible"
                },
            )
        if collected_at is not None and expires_at <= collected_at:
            raise ValidationError("expiry must be after the collection date")
        if expires_at <= now:
            raise ValidationError("cannot create a batch that has already expired")

        batch = Batch(
            batch_id=str(ULID()),
            facility_id=facility_id,
            organization_id=organization_id,
            blood_group=group,
            component=comp,
            available_units=units,
            status=BatchStatus.AVAILABLE,
            collected_at=collected_at,
            expires_at=expires_at,
            last_updated_at=now,
            # Creation is an update, never a verification (ADR-0003).
            last_verified_at=None,
            update_source=source,
            version=1,
        )

        self._inventory.create_batch(batch)
        self._facilities.touch_inventory_timestamp(facility_id, updated_at=to_iso(now))
        self._audit.record(
            actor_id=context.actor_id,
            actor_role=",".join(context.principal.roles),
            action="INVENTORY_BATCH_CREATED",
            resource_type="BATCH",
            resource_id=batch.batch_id,
            organization_id=organization_id,
            correlation_id=context.correlation_id,
            occurred_at=now,
            after={"units": units, "bloodGroup": group.value, "component": comp.value},
        )
        self._emit_stock_event(batch, context, now, "InventoryBatchCreated", units)
        log.info("inventory batch created", event="inventory.batch.created",
                 batchId=batch.batch_id, units=units)
        return self._present_batch(batch, now)

    def adjust_stock(
        self,
        *,
        context: RequestContext,
        facility_id: str,
        batch_id: str,
        operation: str,
        units: int | None,
        now: datetime,
        reason: str | None = None,
        source: str = "MANUAL",
        max_retries: int = 3,
    ) -> dict:
        """Apply a stock operation with optimistic concurrency and bounded retry.

        A concurrent writer causes the conditional write to fail; we re-read and
        recompute rather than retrying the stale decision, then give up with a
        409 so the caller is never told a stale result succeeded.
        """
        log = get_logger(__name__, context)
        try:
            op = StockOperation(operation.strip().upper())
        except ValueError:
            raise ValidationError(
                f"unknown stock operation '{operation}'",
                details={"allowed": [o.value for o in StockOperation]},
            ) from None

        attempt = 0
        while True:
            attempt += 1
            batch = self._inventory.get_batch(facility_id, batch_id)
            if batch is None:
                raise NotFoundError("batch not found", details={"batchId": batch_id})

            expected_version = batch.version
            change = apply_stock_operation(
                batch=batch, operation=op, units=units, now=now, source=source, reason=reason
            )

            audit_item = self._audit.build_item(
                actor_id=context.actor_id,
                actor_role=",".join(context.principal.roles),
                action=f"INVENTORY_{op.value}",
                resource_type="BATCH",
                resource_id=batch_id,
                organization_id=batch.organization_id,
                correlation_id=context.correlation_id,
                occurred_at=now,
                before={"units": change.previous_units, "status": change.previous_status.value},
                after={"units": change.batch.available_units, "status": change.batch.status.value},
                metadata={"reason": reason, "source": source},
            )
            audit_item = {
                **audit_item,
                "PK": f"BATCH#{batch_id}",
                "SK": f"AUDIT#{to_iso(now)}#{audit_item['eventId']}",
            }

            outbox_item = self._outbox.build_event(
                event_type="InventoryStockChanged",
                payload={
                    "batchId": batch_id,
                    "facilityId": facility_id,
                    "bloodGroup": batch.blood_group.value,
                    "component": batch.component.value,
                    "unitsDelta": change.units_delta,
                    "availableUnits": change.batch.available_units,
                    "status": change.batch.status.value,
                    "operation": op.value,
                },
                correlation_id=context.correlation_id,
                occurred_at=now,
                aggregate_id=batch_id,
            )

            try:
                updated = self._inventory.apply_change_with_audit(
                    change,
                    expected_version=expected_version,
                    audit_item=audit_item,
                    outbox_item=outbox_item,
                )
            except ConcurrentModificationError:
                if attempt > max_retries:
                    log.warning(
                        "giving up after concurrent modification",
                        event="inventory.conflict.exhausted",
                        batchId=batch_id, attempts=attempt,
                    )
                    raise
                log.info("retrying after concurrent modification",
                         event="inventory.conflict.retry", batchId=batch_id, attempt=attempt)
                continue

            self._facilities.touch_inventory_timestamp(facility_id, updated_at=to_iso(now))
            log.info("stock adjusted", event="inventory.stock.adjusted",
                     batchId=batch_id, operation=op.value, delta=change.units_delta)
            return self._present_batch(updated, now)

    def verify_inventory(
        self, *, context: RequestContext, facility_id: str, batch_id: str, now: datetime,
        note: str | None = None
    ) -> dict:
        """Record an independent human verification.

        The only path that writes ``lastVerifiedAt``. It deliberately does not
        change stock numbers: verifying is asserting that the recorded figures
        were checked, not changing them.
        """
        batch = self._inventory.get_batch(facility_id, batch_id)
        if batch is None:
            raise NotFoundError("batch not found", details={"batchId": batch_id})

        self._inventory.record_verification(
            facility_id=facility_id,
            batch_id=batch_id,
            verified_at=now,
            verified_by=context.actor_id,
            expected_version=batch.version,
        )
        self._facilities.update(
            pk=f"FACILITY#{facility_id}",
            sk="META",
            update_expression="SET inventoryLastVerifiedAt = :at, inventoryVerifiedBy = :by",
            expression_values={":at": to_iso(now), ":by": context.actor_id},
        )
        self._audit.record(
            actor_id=context.actor_id,
            actor_role=",".join(context.principal.roles),
            action="INVENTORY_VERIFIED",
            resource_type="BATCH",
            resource_id=batch_id,
            organization_id=batch.organization_id,
            correlation_id=context.correlation_id,
            occurred_at=now,
            metadata={"note": note},
        )
        refreshed = self._inventory.get_batch(facility_id, batch_id)
        return self._present_batch(refreshed, now)

    def ingest_external_update(
        self,
        *,
        context: RequestContext,
        facility_id: str,
        batch_id: str,
        units: int,
        source_timestamp: datetime | None,
        source_system: str,
        now: datetime,
    ) -> dict:
        """Apply an external institutional API update (spec 3.6).

        Rejects a delayed update that would overwrite newer state, and never
        implies verification -- an automated feed updates ``lastUpdatedAt`` only.
        """
        log = get_logger(__name__, context)
        batch = self._inventory.get_batch(facility_id, batch_id)
        if batch is None:
            raise NotFoundError("batch not found", details={"batchId": batch_id})

        if is_stale_update(source_timestamp, batch.last_updated_at):
            log.warning("rejected stale external update", event="inventory.ingest.stale",
                        batchId=batch_id, sourceSystem=source_system)
            raise ValidationError(
                "this update is older than the current inventory state and was rejected",
                details={
                    "sourceTimestamp": to_iso(source_timestamp),
                    "currentLastUpdatedAt": to_iso(batch.last_updated_at),
                    "rule": "STALE_UPDATE_REJECTED",
                },
            )

        return self.adjust_stock(
            context=context,
            facility_id=facility_id,
            batch_id=batch_id,
            operation=StockOperation.CORRECT.value,
            units=units,
            now=now,
            reason=f"external update from {source_system}",
            source=f"API:{source_system}",
        )

    def sweep_expired(self, *, context: RequestContext, now: datetime,
                      shard: int | None = None) -> dict:
        """Transition batches past their expiry. Scheduled job.

        Sharded so the sweep never hammers one partition. Eligibility already
        treats an expired batch as ineligible, so this is bookkeeping rather
        than a correctness guard -- the status just catches up with reality.
        """
        shards = [shard] if shard is not None else list(range(EXPIRY_SHARDS))
        transitioned = 0
        failures = 0
        for s in shards:
            for key in self._inventory.list_expiring_before(now, shard=s):
                try:
                    pk = key.get("PK", "")
                    sk = key.get("SK", "")
                    fid = pk.removeprefix("FACILITY#")
                    bid = sk.removeprefix("BATCH#")
                    batch = self._inventory.get_batch(fid, bid)
                    if batch is None or batch.status != BatchStatus.AVAILABLE:
                        continue
                    self.adjust_stock(
                        context=context,
                        facility_id=fid,
                        batch_id=bid,
                        operation=StockOperation.EXPIRE.value,
                        units=None,
                        now=now,
                        reason="automatic expiry sweep",
                        source="SYSTEM",
                    )
                    transitioned += 1
                except Exception:
                    failures += 1
        return {"transitioned": transitioned, "failures": failures, "shards": shards}

    # --- presentation ---

    def _present_batch(self, batch: Batch, now: datetime) -> dict:
        eligibility = evaluate_batch_eligibility(
            status=batch.status,
            available_units=batch.available_units,
            expires_at=batch.expires_at,
            collected_at=batch.collected_at,
            now=now,
        )
        return {
            "batchId": batch.batch_id,
            "facilityId": batch.facility_id,
            "organizationId": batch.organization_id,
            "bloodGroup": batch.blood_group.value,
            "component": batch.component.value,
            "availableUnits": batch.available_units,
            "status": batch.status.value,
            "collectedAt": to_iso(batch.collected_at),
            "expiresAt": to_iso(batch.expires_at),
            "nearExpiry": is_near_expiry(batch.expires_at, now),
            "eligible": eligibility.eligible,
            "ineligibleReasons": list(eligibility.reasons),
            # These four are always reported together and never merged.
            "lastUpdatedAt": to_iso(batch.last_updated_at),
            "freshness": freshness_label(batch.last_updated_at, now).value,
            "lastVerifiedAt": to_iso(batch.last_verified_at),
            "verificationStatus": verification_status(batch.last_verified_at, now).value,
            "updateSource": batch.update_source,
            "version": batch.version,
            "quarantineReason": batch.quarantine_reason,
        }

    def _emit_stock_event(self, batch: Batch, context: RequestContext, now: datetime,
                          event_type: str, units_delta: int) -> None:
        self._outbox.append(
            self._outbox.build_event(
                event_type=event_type,
                payload={
                    "batchId": batch.batch_id,
                    "facilityId": batch.facility_id,
                    "bloodGroup": batch.blood_group.value,
                    "component": batch.component.value,
                    "availableUnits": batch.available_units,
                    "unitsDelta": units_delta,
                },
                correlation_id=context.correlation_id,
                occurred_at=now,
                aggregate_id=batch.batch_id,
            )
        )


def default_expiry_for(component: Component, collected_at: datetime) -> datetime:
    """Conventional shelf life, used only to pre-fill forms.

    These are operational defaults for a demo dataset, not clinical standards,
    and the user must confirm the expiry date on every batch.
    """
    shelf_life = {
        Component.WHOLE_BLOOD: timedelta(days=35),
        Component.PRBC: timedelta(days=42),
        Component.FFP: timedelta(days=365),
        Component.PLATELETS: timedelta(days=5),
    }
    return collected_at + shelf_life[component]


__all__ = ["InventoryService", "default_expiry_for", "expiry_shard"]
