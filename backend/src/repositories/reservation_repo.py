"""Reservation persistence, and the atomicity that prevents overselling.

The domain module decides *what* should happen. This module decides *whether
the write wins*, which is the only question that actually prevents two callers
holding the same units.

The hard part, stated plainly: there is no single item whose value is "units
not yet reserved". Eligible units live on batch rows; holds live on reservation
rows. A read-then-write over two row sets is a race, and the window is exactly
as long as the network round trip.

Three mechanisms close it:

1.  **A per-pool counter row.** One item per
    (facility, group, component) carries ``heldUnits``. A new hold increments it
    under a condition that the result cannot exceed the eligible total. That
    condition is evaluated by DynamoDB, so two concurrent holds cannot both
    pass it -- one gets ``ConditionalCheckFailedException`` and is told the
    stock went.

2.  **One transaction per hold.** The reservation row and the counter increment
    are written in a single ``TransactWriteItems``. Either both land or neither
    does, so a counter can never be incremented without a reservation to
    justify it, and a reservation can never exist without being counted.

3.  **An idempotency key on creation.** The reservation row is written with
    ``attribute_not_exists(SK)``, so a retried request -- a double click, a
    client retry after a timeout -- cannot produce two holds.

Release is the same transaction in reverse, conditioned on the reservation
still being in a holding state, so a hold cannot be released twice and
decrement the counter twice.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from boto3.dynamodb.conditions import Key

from domain.blood import BloodGroup, Component
from domain.clock import parse_iso, to_iso
from domain.errors import ConcurrentModificationError, DuplicateError
from domain.reservations import (
    HOLDING_STATES,
    Reservation,
    ReservationStatus,
)

from .dynamo import (
    DynamoRepository,
    Tables,
    table_name,
    to_dynamo,
    to_expression_values,
    transact_write,
)

#: How long a released reservation row is kept before TTL removes it. Long
#: enough that the audit trail and a user's own history remain readable.
PURGE_AFTER_DAYS = 30


def _pool_sk(blood_group: BloodGroup, component: Component) -> str:
    return f"POOL#{blood_group.value}#{component.value}"


def _reservation_sk(
    blood_group: BloodGroup, component: Component, reservation_id: str
) -> str:
    return f"RES#{blood_group.value}#{component.value}#{reservation_id}"


def reservation_to_item(reservation: Reservation) -> dict:
    expires = reservation.expires_at
    return {
        "PK": f"FACILITY#{reservation.facility_id}",
        "SK": _reservation_sk(
            reservation.blood_group, reservation.component, reservation.reservation_id
        ),
        "entityType": "RESERVATION",
        "reservationId": reservation.reservation_id,
        "facilityId": reservation.facility_id,
        "organizationId": reservation.organization_id,
        "requesterUserId": reservation.requester_user_id,
        "bloodGroup": reservation.blood_group.value,
        "component": reservation.component.value,
        "units": reservation.units,
        "status": reservation.status.value,
        "createdAt": to_iso(reservation.created_at),
        "expiresAt": to_iso(expires),
        "releasedAt": to_iso(reservation.released_at),
        "decidedByUserId": reservation.decided_by_user_id,
        "decisionReason": reservation.decision_reason,
        "version": reservation.version,
        # "My reservations", newest first.
        "GSI1PK": f"USER#{reservation.requester_user_id}",
        "GSI1SK": to_iso(reservation.created_at),
        # The expiry sweep queries only holding states, so it never scans.
        "GSI2PK": f"RESSTATUS#{reservation.status.value}",
        "GSI2SK": to_iso(expires),
        # Cleanup only. Never the release mechanism -- see the table comment.
        "purgeAtEpoch": int((expires + timedelta(days=PURGE_AFTER_DAYS)).timestamp()),
    }


def item_to_reservation(item: dict) -> Reservation:
    return Reservation(
        reservation_id=item["reservationId"],
        facility_id=item["facilityId"],
        organization_id=item.get("organizationId", ""),
        requester_user_id=item["requesterUserId"],
        blood_group=BloodGroup(item["bloodGroup"]),
        component=Component(item["component"]),
        units=int(item["units"]),
        status=ReservationStatus(item["status"]),
        created_at=parse_iso(item["createdAt"]),
        expires_at=parse_iso(item["expiresAt"]),
        released_at=parse_iso(item.get("releasedAt")),
        decided_by_user_id=item.get("decidedByUserId"),
        decision_reason=item.get("decisionReason"),
        version=int(item.get("version", 1)),
    )


class ReservationRepository(DynamoRepository):
    logical_table = Tables.RESERVATIONS

    # --- reads ---

    def list_for_pool(
        self, facility_id: str, blood_group: BloodGroup, component: Component
    ) -> list[Reservation]:
        """Every reservation for one facility/group/component.

        A key condition, not a filter: the sort key encodes group and
        component, so DynamoDB returns only the rows wanted rather than
        reading the facility's whole partition and discarding most of it.
        """
        prefix = f"RES#{blood_group.value}#{component.value}#"
        items = self.query_all(
            key_condition=Key("PK").eq(f"FACILITY#{facility_id}")
            & Key("SK").begins_with(prefix),
        )
        return [item_to_reservation(i) for i in items]

    def list_for_user(self, user_id: str, *, limit: int = 50) -> list[Reservation]:
        items = self.query_all(
            key_condition=Key("GSI1PK").eq(f"USER#{user_id}"),
            index_name="GSI1-requester",
            max_items=limit,
        )
        # Newest first. Sorted here rather than with a reverse query because
        # query_all pages forward; the result set per user is small.
        items.sort(key=lambda i: i.get("createdAt") or "", reverse=True)
        return [item_to_reservation(i) for i in items]

    def list_for_facility(self, facility_id: str, *, limit: int = 100) -> list[Reservation]:
        items = self.query_all(
            key_condition=Key("PK").eq(f"FACILITY#{facility_id}")
            & Key("SK").begins_with("RES#"),
            max_items=limit,
        )
        return [item_to_reservation(i) for i in items]

    def get(self, facility_id: str, blood_group: BloodGroup,
            component: Component, reservation_id: str) -> Reservation | None:
        item = super().get(
            f"FACILITY#{facility_id}",
            _reservation_sk(blood_group, component, reservation_id),
        )
        return item_to_reservation(item) if item else None

    def due_for_expiry(self, now: datetime, *, limit: int = 100) -> list[Reservation]:
        """Holds whose expiry has passed, by status, newest expiry last.

        Queried per holding status over GSI2, so this is two bounded queries
        rather than a scan. Expiry is processed actively because TTL is
        best-effort within ~48 hours and units must be released promptly.
        """
        found: list[Reservation] = []
        for status in sorted(s.value for s in HOLDING_STATES):
            items = self.query_all(
                key_condition=Key("GSI2PK").eq(f"RESSTATUS#{status}")
                & Key("GSI2SK").lt(to_iso(now)),
                index_name="GSI2-expiry",
                max_items=limit,
            )
            found.extend(item_to_reservation(i) for i in items)
        return found

    def held_units_for_pool(
        self, facility_id: str, blood_group: BloodGroup, component: Component
    ) -> int:
        """The counter's view of held units.

        Authoritative for the conditional write. Readers that need correctness
        between sweeps should use ``domain.reservations.held_units`` over
        ``list_for_pool``, which treats an expired-but-unprocessed hold as
        released; this counter is only decremented when a release is processed.
        """
        item = super().get(f"FACILITY#{facility_id}", _pool_sk(blood_group, component))
        return int((item or {}).get("heldUnits", 0))

    # --- writes ---

    def create_atomically(
        self,
        reservation: Reservation,
        *,
        eligible_units: int,
    ) -> Reservation:
        """Create a hold, or refuse because the units went to someone else.

        One transaction, two items:

        *   the reservation row, conditioned on ``attribute_not_exists(SK)`` so
            a retry cannot create a second hold;
        *   the pool counter, incremented under a condition that the new total
            cannot exceed ``eligible_units``.

        The counter condition is what makes this safe. Two callers can both
        pass ``validate_request`` in the domain, because that runs against a
        snapshot; only one can satisfy the condition here. The loser receives
        ``ConcurrentModificationError`` and is told the stock was taken, rather
        than being handed a hold on units that do not exist.
        """
        item = reservation_to_item(reservation)
        pool_key = {
            "PK": f"FACILITY#{reservation.facility_id}",
            "SK": _pool_sk(reservation.blood_group, reservation.component),
        }

        try:
            transact_write(
                [
                    {
                        "Put": {
                            "TableName": table_name(self.logical_table),
                            "Item": to_dynamo(item),
                            "ConditionExpression": "attribute_not_exists(SK)",
                        }
                    },
                    {
                        "Update": {
                            "TableName": table_name(self.logical_table),
                            "Key": to_dynamo(pool_key),
                            "UpdateExpression": (
                                "SET heldUnits = if_not_exists(heldUnits, :zero) + :units,"
                                " entityType = :type, facilityId = :facility,"
                                " bloodGroup = :group, component = :component,"
                                " updatedAt = :now"
                            ),
                            # The whole point: held units after this increment
                            # must still fit inside what the facility actually
                            # has. Evaluated by DynamoDB, so it cannot race.
                            "ConditionExpression": (
                                "attribute_not_exists(heldUnits)"
                                " OR heldUnits <= :headroom"
                            ),
                            "ExpressionAttributeValues": to_expression_values(
                                {
                                    ":zero": 0,
                                    ":units": reservation.units,
                                    ":headroom": eligible_units - reservation.units,
                                    ":type": "RESERVATION_POOL",
                                    ":facility": reservation.facility_id,
                                    ":group": reservation.blood_group.value,
                                    ":component": reservation.component.value,
                                    ":now": to_iso(reservation.created_at),
                                }
                            ),
                        }
                    },
                ]
            )
        except ConcurrentModificationError:
            # A cancelled transaction does not say *which* condition failed in a
            # way the generic translator can use, and the two causes need
            # different answers:
            #
            #   - the Put's attribute_not_exists(SK) failed  -> this is a retry
            #     of a request that already succeeded;
            #   - the counter's headroom condition failed    -> someone else
            #     took the units.
            #
            # Telling a user who double-clicked that the stock was taken would
            # be simply wrong, so we re-read to find out which happened. Same
            # approach as camp_repo's registration path.
            existing = self.get(
                reservation.facility_id,
                reservation.blood_group,
                reservation.component,
                reservation.reservation_id,
            )
            if existing is not None:
                raise DuplicateError(
                    "this reservation has already been created",
                    details={"reservationId": reservation.reservation_id},
                ) from None
            raise
        return reservation

    def transition_atomically(
        self,
        reservation: Reservation,
        updated: Reservation,
        *,
        release_units: bool,
    ) -> Reservation:
        """Write a state change, releasing held units when the hold ends.

        Conditioned on the reservation still being in the state we read and at
        the version we read, so a hold cannot be released twice -- which would
        decrement the counter twice and silently invent available units.
        """
        items: list[dict] = [
            {
                "Update": {
                    "TableName": table_name(self.logical_table),
                    "Key": to_dynamo(
                        {
                            "PK": f"FACILITY#{reservation.facility_id}",
                            "SK": _reservation_sk(
                                reservation.blood_group,
                                reservation.component,
                                reservation.reservation_id,
                            ),
                        }
                    ),
                    "UpdateExpression": (
                        "SET #st = :new, version = :newver, releasedAt = :released,"
                        " decidedByUserId = :actor, decisionReason = :reason,"
                        " GSI2PK = :gsi2pk"
                    ),
                    # Both guards matter: the status guard stops a double
                    # release, the version guard stops a lost update.
                    "ConditionExpression": "#st = :old AND version = :oldver",
                    "ExpressionAttributeNames": {"#st": "status"},
                    "ExpressionAttributeValues": to_expression_values(
                        {
                            ":new": updated.status.value,
                            ":old": reservation.status.value,
                            ":newver": updated.version,
                            ":oldver": reservation.version,
                            ":released": to_iso(updated.released_at),
                            ":actor": updated.decided_by_user_id,
                            ":reason": updated.decision_reason,
                            ":gsi2pk": f"RESSTATUS#{updated.status.value}",
                        }
                    ),
                }
            }
        ]

        if release_units:
            items.append(
                {
                    "Update": {
                        "TableName": table_name(self.logical_table),
                        "Key": to_dynamo(
                            {
                                "PK": f"FACILITY#{reservation.facility_id}",
                                "SK": _pool_sk(
                                    reservation.blood_group, reservation.component
                                ),
                            }
                        ),
                        "UpdateExpression": "SET heldUnits = heldUnits - :units",
                        # Never let the counter go negative. If it would, the
                        # counter and the rows have diverged and the right
                        # answer is to refuse loudly, not to clamp quietly.
                        "ConditionExpression": "heldUnits >= :units",
                        "ExpressionAttributeValues": to_expression_values(
                            {":units": reservation.units}
                        ),
                    }
                }
            )

        transact_write(items)
        return updated


__all__ = [
    "PURGE_AFTER_DAYS",
    "ReservationRepository",
    "item_to_reservation",
    "reservation_to_item",
]
