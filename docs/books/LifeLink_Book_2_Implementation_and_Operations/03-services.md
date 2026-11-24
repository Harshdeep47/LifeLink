<!-- pagebreak -->

# 8. The Inventory Service

## 8.1 Composing a decision with a write

A service method is usually three steps: read current state, ask the domain
layer what the new state should be, write it conditionally.

{{include:backend/src/services/inventory_service.py:def adjust_stock}}

*Listing 8.1. Stock adjustment from
`backend/src/services/inventory_service.py`.*

```diagram
type: sequence
title: A stock deduction that loses a race and recovers
actor client Dashboard
actor svc Inventory service
actor dom Domain layer
actor ddb DynamoDB
msg client -> svc deduct two units
msg svc -> ddb read batch version seven
msg svc -> dom apply stock operation
msg dom -> svc new state version eight
msg svc -> ddb transaction conditional on version seven
msg ddb -> svc condition failed another writer committed
msg svc -> ddb re-read batch version eight
msg svc -> dom recompute from current state
msg svc -> ddb transaction conditional on version eight
msg ddb -> svc committed
msg svc -> client new batch state
note Recomputing is essential. Resubmitting the first decision would fail forever.
```

*Figure 8.1. The retry loop recovering from a concurrent write.*

## 8.2 The retry loop, in detail

The loop re-reads inside each attempt. That is the part people get wrong:
retrying the *same* computed change would fail the same condition forever,
because the condition is on the version that has already moved.

The audit item and the outbox event are constructed inside the loop too, so
they describe the attempt that actually commits rather than the first one that
did not.

After three retries the service gives up and lets `ConcurrentModificationError`
propagate to a 409. That is better than looping: a batch under constant
contention is a situation a human should see.

## 8.3 Availability for a whole facility

{{include:backend/src/services/inventory_service.py:def facility_availability}}

*Listing 8.2. The availability matrix.*

Note `inventory_known` being read from the facility record and passed through.
When it is false, no inventory query runs at all and every cell returns
`UNKNOWN`. Querying and finding nothing would produce `UNAVAILABLE`, which
means something different.

## 8.4 External ingestion

{{include:backend/src/services/inventory_service.py:def ingest_external_update}}

*Listing 8.3. External API ingestion.*

Two protections. A stale update — one whose source timestamp predates the
stored `lastUpdatedAt` — is rejected with a named rule rather than applied. And
the update is routed through `adjust_stock` with a source of `API:<system>`,
so it updates `lastUpdatedAt` and never touches `lastVerifiedAt`.

## 8.5 The presentation layer

{{include:backend/src/services/inventory_service.py:def _present_batch}}

*Listing 8.4. Batch presentation.*

Four fields are always emitted together: `lastUpdatedAt`, `freshness`,
`lastVerifiedAt` and `verificationStatus`. Returning freshness without
verification would let a client render one and not the other, which is the
conflation the whole design exists to prevent.

<!-- pagebreak -->

# 9. The Discovery Service

## 9.1 Filter, then rank — never the other way round

{{include:backend/src/services/discovery_service.py:def search_facilities}}

*Listing 9.1. Facility search from
`backend/src/services/discovery_service.py`.*

Eligibility filtering happens while building the candidate list. Ranking runs
afterwards on survivors only. No weighting, however it is tuned, can surface an
expired or quarantined batch, because such batches never enter the list.

## 9.2 Ranking is explainable

{{include:backend/src/domain/ranking.py:def score_facility}}

*Listing 9.2. Scoring from `backend/src/domain/ranking.py`.*

Each result carries its component contributions and a human-readable
explanation. The specification requires explaining ranking factors to the user,
and a bare score explains nothing.

| Factor | Weight | Rationale |
|---|---|---|
| Availability | 30% | The dominant question |
| Inventory freshness | 20% | Stale data is weak evidence |
| Distance | 20% | Travel time matters in an emergency |
| Quantity | 15% | Partial beats none, full beats partial |
| Independent verification | 15% | Human confirmation is worth something |

*Table 9.1. Default weights, matching the specification's proposal. The weights
are configurable and validated to sum to 1.0.*

## 9.3 Routing never guesses

{{include:backend/src/services/discovery_service.py:def route_to_facility}}

*Listing 9.3. Routing with honest degradation.*

Straight-line distance is always present and always labelled. Road distance
appears only when a provider returned one. When it did not, the response says
so, names the reason, and warns that the figure shown is not a driving
distance.

<!-- pagebreak -->

# 10. The Alert Service

## 10.1 An alert is a standing question

{{include:backend/src/services/alert_service.py:def create_alert}}

*Listing 10.1. Alert creation from `backend/src/services/alert_service.py`.*

Creating an alert immediately attempts a match, because a user whose need is
already satisfiable should be told now rather than when stock next changes.

```diagram
type: sequence
title: Stock arrives and a waiting alert is matched
actor staff Blood bank staff
actor api API
actor out Outbox
actor pub Publisher
actor worker Work worker
actor alerts Alert index
actor donor Donor
msg staff -> api add batch
msg api -> out transaction batch and event
msg out -> pub stream delivers event
msg pub -> worker queue message
msg worker -> alerts query match index for this cell and group
msg alerts -> worker waiting alerts
msg worker -> api revalidate stock now
msg worker -> donor notify with informational notice
note The worker revalidates rather than trusting the event, because stock may already have gone.
```

*Figure 10.1. From a stock addition to a donor notification.*

## 10.2 Matching revalidates

{{include:backend/src/services/alert_service.py:def match_alert}}

*Listing 10.2. Alert matching.*

The match re-reads eligible stock rather than trusting whatever event triggered
it. Between a stock-change event being published and a worker processing it,
the stock may already have gone.

Three guards before any notification: the alert must still be active, its
deadline must not have passed, and the facility must not already have been
matched to this alert.

## 10.3 The reverse lookup

{{include:backend/src/services/alert_service.py:def match_on_stock_change}}

*Listing 10.3. Finding alerts waiting on a facility's stock.*

This is what the `GSI2-match` index exists for. The question "stock arrived
here — who was waiting?" becomes a key query on
`MATCH#<geohash5>#<group>#<component>` rather than a scan over every open
alert.

## 10.4 The word "reservation" appears, in the negative

`INFORMATIONAL_NOTICE` is a module-level constant used in every alert response
and every match notification. Centralising it means the wording cannot drift
between the API and the email, and a reviewer can check one string.

<!-- pagebreak -->

# 11. The Camp Service

## 11.1 Four states, four methods

`register` → `check_in` → `record_donation` → `verify_donation`. Each is a
separate authorized action with its own audit record, and each refuses if the
previous one has not happened.

{{include:backend/src/services/camp_service.py:def record_donation}}

*Listing 11.1. Recording a donation requires prior check-in.*

```diagram
type: sequence
title: The four camp states, each a separate authorized action
actor donor Donor
actor staff Camp staff
actor api API
actor camps Camps table
actor ledger Donations and ledger
msg donor -> api register
msg api -> camps transaction registration and capacity
msg staff -> api check in donor
msg api -> camps attendance recorded
msg staff -> api record donation
msg api -> ledger donation status recorded
msg staff -> api verify donation
msg api -> ledger transaction verified and ledger entry
note Each arrow is refused unless the previous one happened, and a donor may not perform the last.
```

*Figure 11.1. Registration, attendance, donation and verification as four
distinct records.*

## 11.2 Self-verification is refused in the service, not only in the policy

{{include:backend/src/domain/camps.py:def assert_can_verify_donation}}

*Listing 11.2. The rule from `backend/src/domain/camps.py`.*

Holding `donation:verify` is necessary but not sufficient. A camp organiser who
donated at their own camp has the permission and is refused anyway, and there
is a test that grants the donor the staff role specifically to prove the
refusal still holds.

## 11.3 Exactly-once credit

{{include:backend/src/services/camp_service.py:def verify_donation}}

*Listing 11.3. Verification and crediting.*

The service reads the ledger before and after so it can report newly crossed
milestones without re-announcing old ones. The exactly-once property itself is
enforced one layer down, by a transaction whose ledger row is keyed on the
donation id with a not-exists condition.

## 11.4 Reminders re-check everything

{{include:backend/src/domain/camps.py:def should_send_reminder}}

*Listing 11.4. The five re-checks.*

A reminder scheduled yesterday for a camp cancelled this morning must not be
sent. Every precondition is evaluated at send time, not at schedule time, and
the schedule-drift tolerance means a job that fires hours late does not emit a
"starts in 2 hours" message about something that started already.

<!-- pagebreak -->

# 12. The Emergency Service

## 12.1 A new request has no priority

{{include:backend/src/services/emergency_service.py:def create_request}}

*Listing 12.1. Request creation from
`backend/src/services/emergency_service.py`.*

`clinicalPriority` is explicitly `None`. Nothing the requester submits can set
it. The response says so and names the next step.

Duplicate submissions are caught by a fingerprint of actor, group, component,
quantity and rounded coordinates. Rounding to three decimal places means GPS
jitter does not defeat the check while a genuinely different location still
produces a different fingerprint.

## 12.2 Certification re-checks the hospital

{{include:backend/src/services/emergency_service.py:def certify_priority}}

*Listing 12.2. Priority certification.*

Four checks before the write: the caller belongs to an organization, that
organization exists, it is a hospital, and it is *currently* verified. The last
is why a hospital suspended after the request was raised cannot certify it.

## 12.3 Matching uses the reference table

{{include:backend/src/services/emergency_service.py:def run_matching}}

*Listing 12.3. The matching engine.*

Compatible donor groups come from `compatible_donor_groups`, which reads the
versioned JSON reference. When the lookup yields nothing the engine records a
`NO_COMPATIBILITY_REFERENCE` event and returns no candidates, along with the
rules version and review status.

Candidates are ordered deterministically: identical blood group first, then
rank score, then distance. Determinism matters because a matching engine that
returns different results for identical inputs cannot be audited.

## 12.4 Responses are offers

{{include:backend/src/services/emergency_service.py:def submit_response}}

*Listing 12.4. Provider response handling.*

Before an acceptance is recorded, stock is revalidated. If it has gone, the
acceptance is refused with the current figure and a named rule, rather than
recorded against stock that no longer exists.

Nothing in this method decrements inventory, and it touches no reservation
counter — which is why two providers accepting the same request is recorded as
two independent offers rather than eight units of secured supply.

Be precise about this in a viva. A reservation counter *does* exist, for
temporary reservations (ADR-0018), and it is updated atomically. The point is
that the **emergency response path deliberately does not use it**: an offer is
a willingness to proceed, not a claim on units.
