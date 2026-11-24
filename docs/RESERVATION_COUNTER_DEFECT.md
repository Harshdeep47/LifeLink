# The reservation counter defect — post-mortem

**Found** 24 November 2026, 08:21 UTC, against the deployed API
**Fixed and deployed** 24 November 2026, 08:33 UTC (changeset `samcli-deploy1795508812`)
**Severity** high — overselling, and a confirmed hold that could not be closed
**Exploitable** no authentication bypass; reachable by any authenticated donor through the normal interface

A one-expression bug in `ReservationService._transition` that broke the single
invariant the reservation feature exists to protect. Recorded here in full
because the *way* it hid is more instructive than the bug.

---

## 1. Symptom

Cancelling a `CONFIRMED` reservation returned `400`:

```json
{"error":{"code":"VALIDATION_ERROR",
          "message":"this reservation changed while your request was in flight; please reload",
          "details":{"rule":"CONCURRENT_MODIFICATION"}}}
```

It reproduced every time, so it was not the race the message describes.

## 2. Root cause

`backend/src/services/reservation_service.py`:

```python
releases = reservation.status in HOLDING_STATES      # the bug
```

`HOLDING_STATES` is `{PENDING, CONFIRMED}` — the two states in which a
reservation holds units. The expression asks "**was** this holding units?"
when the question is "does it **stop** holding units?".

For `PENDING → CONFIRMED` the answer should be no — both states hold. The
expression said yes, so confirming a reservation decremented the pool counter.

| Step | Counter | Reservation says |
|---|---|---|
| create 1 unit | 0 → **1** | PENDING, holds 1 |
| provider confirms | 1 → **0** ← wrong | CONFIRMED, holds 1 |
| requester cancels | `0 - 1` refused by `heldUnits >= :units` | stuck |

## 3. Consequences

**(a) Overselling.** The pool counter is what the creation transaction tests.
With it wrongly at zero, a *second* requester could reserve units a confirmed
reservation still held. Both would believe they held the same unit. This is the
one outcome the counter exists to prevent, and the reason the feature uses a
conditional `TransactWriteItems` at all.

Reproduced in a test: against a fully-held pool, a second caller's request
succeeded where it must have been refused.

**(b) A confirmed hold could not be closed.** Cancel *and* fulfil both leave
the holding states, so both tried to decrement a counter already at zero. Both
refused with `CONCURRENT_MODIFICATION`. The provider workflow was broken at its
second step: a facility could accept a request and then never record issuing
the units.

**(c) The expiry sweep could not settle such a row either**, for the same
reason, so its stored status stayed `CONFIRMED` indefinitely.

**What was *not* affected.** Displayed availability was always correct.
`/facilities/{id}/availability` computes held units by reading the reservation
**rows** (`held_units()` over `list_for_pool`), not the counter, so users saw
the right `reservedUnits` throughout. The divergence was between what the UI
showed and what the *write path* would permit — which is why no amount of
looking at the screen would have revealed it.

## 4. Why the tests missed it

The most useful part of this post-mortem.

The repository layer was **correct and well covered**. Every existing test
calls `transition_atomically` directly and passes `release_units` **by hand**:

```python
# test_reservation_integration.py, before this defect was found
def test_confirming_keeps_the_hold(self, repo):
    repo.transition_atomically(reservation, confirmed, release_units=False)
```

That test *encodes the correct semantics*. It passed throughout, because it
supplies the right value itself. The service supplied the wrong one, and
`ReservationService` was **never constructed in any test** — 604 tests, and the
component that decides when to release held units had no coverage at all.

The lesson is general: a test that passes a collaborator's decision in as a
parameter verifies the collaborator, not the decision. The seam between a
service and its repository needs a test that exercises the *real* pair.

## 5. The fix

```python
# Units are released when the hold *stops* holding them -- that is, when it
# leaves the holding states. Not merely when it was holding them before.
releases = (
    reservation.status in HOLDING_STATES
    and updated.status not in HOLDING_STATES
)
```

Correct for every transition the state machine permits:

| Transition | Releases | Why |
|---|---|---|
| `PENDING → CONFIRMED` | **no** | both states hold units |
| `PENDING → REJECTED / CANCELLED / EXPIRED` | yes | hold ended |
| `CONFIRMED → CANCELLED / EXPIRED` | yes | hold ended |
| `CONFIRMED → FULFILLED` | yes | units left the shelf, so they are no longer *held* |

`FULFILLED` decrements the **held** counter without returning units to
availability — fulfilment records issuance; the stock itself is adjusted by an
explicit batch operation, which is why `eligibleUnits` is unchanged by a
fulfilment.

## 6. Regression tests

Six service-level tests in
`backend/tests/integration/test_reservation_integration.py`, class
`TestServiceDecidesWhenUnitsAreReleased`. They construct the **real**
`ReservationService` over the **real** repository and read the counter back.

**Four of the six failed before the fix and all six pass after** — run, not
assumed:

| Test | Before | After |
|---|---|---|
| `test_confirming_a_hold_does_not_release_its_units` | FAIL | pass |
| `test_a_confirmed_hold_can_still_be_cancelled` | FAIL | pass |
| `test_a_confirmed_hold_can_still_be_fulfilled` | FAIL | pass |
| `test_confirming_then_cancelling_frees_the_units_for_someone_else` | FAIL | pass |
| `test_rejecting_a_pending_hold_releases_its_units` | pass | pass |
| `test_cancelling_a_pending_hold_releases_its_units` | pass | pass |

The fourth is the overselling test, and it failed with
`DID NOT RAISE ConcurrentModificationError` — a second caller really did take
units that were already held.

## 7. Live verification after deployment

37 checks against the deployed API, all passing. Counters read **straight from
DynamoDB** and compared against what the API reported, at every step.

Facility `fac-patiala-1`, pool `A-/PRBC`, baseline 12 units:

| Path | heldUnits | unreserved |
|---|---|---|
| baseline | 0 | 12 |
| `PENDING` (hold 2) | 2 | 10 |
| `CONFIRMED` | **2** ← the fix | 10 |
| `FULFILLED` | 0 | 12 |
| `PENDING → CONFIRMED → CANCELLED` | 2 → 2 → 0 | 10 → 12 |
| `PENDING → CANCELLED` | 2 → 0 | 12 |

`heldUnits` equalled the API's `reservedUnits` at all ten checkpoints.

**Overselling, re-tested live** on `A+/PRBC` (3 units): a donor held all 3, a
*different* requester (platform admin) was refused with
`NO_UNRESERVED_STOCK` — not `ALREADY_HOLDING`, confirming it was the stock
check and not the one-hold-per-person rule — and succeeded immediately after
the hold was released.

## 8. Residue, deliberately not cleaned up

One row remains with a stale stored status: reservation
`01M86AA2WV2KDXR0B0ZKR80F18` (1 unit O-/PRBC at `fac-patiala-1`), created
during the investigation that found the defect.

* **stored** status `CONFIRMED`
* **effective** status `EXPIRED` (its `expiresAt`, 08:36:12, has passed)
* `holdsUnits: false`, and every pool counter is `0`

It holds nothing, and every read path uses the effective status, so it has no
user-visible effect. The expiry sweep cannot settle its stored value, because
settling it would decrement a counter already at zero — §3(c).

It was left alone on purpose: repairing it means hand-editing a production row,
which was out of scope. The honest state is a documented stale row, not a
quietly edited database. It is the only such row; the other eight reservation
rows are in terminal states.

## 9. What would have caught it sooner

1. **A test over the real service/repository pair.** The gap was exactly the
   seam. Now covered.
2. **An invariant check** comparing each pool counter with the sum of units
   held by its rows. Cheap, and it would have failed immediately. Recorded as
   future work in [KNOWN_LIMITATIONS](KNOWN_LIMITATIONS.md); not added in this
   session because it belongs in the maintenance sweep and would have needed a
   third deployment.
3. **Driving the whole workflow against a deployed environment.** Unit and
   integration tests both passed. The defect surfaced on the first real
   `confirm → cancel` sequence anyone had ever run.

## 10. Related

- [ADR-0018](ARCHITECTURE_DECISIONS.md#adr-0018) — reservations as the ordinary
  request workflow
- [DATABASE_DESIGN](DATABASE_DESIGN.md) — AP-45, the pool counter
- [REPOSITORY_VS_DEPLOYED](REPOSITORY_VS_DEPLOYED.md) — deployment state
- `backend/src/services/reservation_service.py` — the fix, with the rationale
  in a comment at the site
