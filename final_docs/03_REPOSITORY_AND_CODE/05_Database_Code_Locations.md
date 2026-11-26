# Database Code Locations

Where every database concern lives in the code. Use this when a teacher says
"show me where you write to the database".

---

## 1. The three places a table is described

A single table appears in three files, each for a different reason.

| File | Why it exists | What it controls |
|---|---|---|
| `infrastructure/template.yaml` | **The deployed truth.** CloudFormation creates the table | keys, GSIs, billing mode, TTL, streams, PITR, encryption |
| `backend/src/repositories/schema.py` | **The test and local-dev truth.** Creates matching tables against moto and the local server | keys, GSIs, attribute definitions |
| `backend/src/repositories/*_repo.py` | **The access truth.** The queries actually issued | key construction, conditions, projections |

**If asked "isn't that duplication?"** — yes, and it is deliberate. The
template cannot create tables for a unit test, and a test cannot deploy to
AWS. The integration tests are what catch a mismatch between the two: they run
against `schema.py`-created tables using the same repository code that runs in
production, so a schema divergence shows up as a failing query, not as a
surprise after deployment.

---

## 2. Table to repository map

| Table | Repository | Service |
|---|---|---|
| `lifelink-dev-organizations` | `identity_repo.py` | all (user lookup on every request) |
| `lifelink-dev-facilities` | `facility_repo.py` | `discovery_service.py` |
| `lifelink-dev-inventory` | `inventory_repo.py` | `inventory_service.py` |
| `lifelink-dev-reservations` | `reservation_repo.py` | `reservation_service.py` |
| `lifelink-dev-camps` | `camp_repo.py` | `camp_service.py` |
| `lifelink-dev-donations` | `camp_repo.py` | `camp_service.py` |
| `lifelink-dev-emergency` | `emergency_repo.py` | `emergency_service.py` |
| `lifelink-dev-alerts` | `alert_repo.py` | `alert_service.py` |
| `lifelink-dev-notifications` | `platform_repo.py` | `notification_service.py` |
| `lifelink-dev-audit` | `platform_repo.py` | all (writes) |
| `lifelink-dev-outbox` | `platform_repo.py` | all (writes) |
| `lifelink-dev-idempotency` | `platform_repo.py` | all (writes) |

Note `platform_repo.py` owns the four cross-cutting tables — audit, outbox,
idempotency, notifications — because they are written by every feature rather
than belonging to one.

---

## 3. Where each kind of operation lives

### Key construction

All in the repositories. The pattern is a prefixed partition key and a
structured sort key:

| Entity | PK | SK |
|---|---|---|
| Facility | `FACILITY#<id>` | `META` |
| Inventory batch | `FACILITY#<id>` | `BATCH#<batchId>` |
| Emergency request | `REQUEST#<id>` | `META` |
| Request event | `REQUEST#<id>` | `EVENT#<iso>#<uuid8>` |
| Provider response | `REQUEST#<id>` | `RESPONSE#<orgId>` |
| Reservation | `RESERVATION#<id>` or facility-scoped | `META` |
| Reservation pool | facility + group + component | `POOL` |

**Why structured sort keys?** Because a `Query` on the partition key with a
`begins_with` condition on the sort key fetches exactly one kind of child
record. `PK = REQUEST#x` and `SK begins_with EVENT#` returns that request's
timeline in sort-key order with one query and no filtering.

**And a consequence to know:** the timeline is returned in **sort-key** order,
which is why the seeded-event duplication bug was visible as five
`REQUEST_CREATED` entries — each seed run created a new sort key instead of
overwriting.

### Queries using a GSI

`facility_repo.py` holds the most interesting one — three geohash tiers:

| GSI | Precision | Used when |
|---|---|---|
| `GSI5-geo4` | 4 | large radius |
| `GSI1-geo5` | 5 | medium radius |
| `GSI2-geo6` | 6 | small radius |

`domain/geo.py` `choose_precision(radius_km)` picks the tier, `search_cells`
produces the cell list, the repository queries each cell, and
`haversine_km` filters the union down to the true circle.

**Why three tiers instead of one?** A geohash cell has a fixed size, so one
precision is either far too coarse for a 2 km search (returning most of
Punjab) or far too fine for a 50 km one (requiring hundreds of queries).
Picking the tier by radius keeps the number of queries small at every scale.

### Conditional writes

| Where | Condition | Protects against |
|---|---|---|
| `inventory_repo.py` | `version = :expected` | two staff editing the same batch |
| `reservation_repo.py` | `heldUnits + :units <= availableUnits` | overselling |
| `platform_repo.py` (idempotency) | `attribute_not_exists(PK)` | double-applying a retried request |
| `dedupe_request_events.py` | `entityType = :t AND demoData = :d AND attribute_exists(PK)` | deleting a row that changed since it was read |

### Transactions

`reservation_repo.py` is the main user of `TransactWriteItems`: the
reservation row and the pool counter commit together or not at all.

The transactional outbox also uses it — a domain write and its outbox row go in
one transaction, so an event cannot exist for a write that rolled back.

### Scans

Scans are **rare and deliberate**. A full-table scan appears in:

- `scripts/seed_cloud.py` — counting existing rows for the preview
- `scripts/dedupe_request_events.py` — an operator tool, run by hand
- nowhere in the request path

If asked "do you ever scan?": in operator tooling, yes, and that is
appropriate for a tool a human runs once. In the API, no — every read is a
`GetItem` or a `Query` against a key or an index. That is what the 24 GSIs are
for.

---

## 4. TTL — which attribute, on which table

| Table | TTL attribute | What expires |
|---|---|---|
| `lifelink-dev-reservations` | `purgeAtEpoch` | old reservation records |
| `lifelink-dev-alerts` | `expiresAtEpoch` | short-term availability alerts |
| `lifelink-dev-notifications` | `expiresAtEpoch` | delivered notifications |
| `lifelink-dev-idempotency` | `expiresAtEpoch` | idempotency claims |
| `lifelink-dev-outbox` | `expiresAtEpoch` | published events |

**Note `reservations` uses `purgeAtEpoch`, not `expiresAtEpoch`.** That is
deliberate and worth explaining: a reservation has a *business* expiry (the
hold runs out, and the record must survive so the user can see it expired) and
a *storage* purge much later. Using the same attribute for both would delete
the record at the moment the user most wants to see what happened.

**TTL is not instant.** DynamoDB deletes expired items within about 48 hours,
so an expired item can still be read. Every query that cares filters on the
business expiry rather than trusting TTL — which is also why
`reservationView.js` has `isStaleHold()`.

---

## 5. Where "unknown is not zero" is enforced

This honesty rule touches four layers, which makes it a good demonstration of
how a principle is actually upheld:

| Layer | File | Enforcement |
|---|---|---|
| Domain | `domain/inventory.py` | `UNKNOWN` is a distinct availability state, not a 0 |
| Repository | `inventory_repo.py` | a missing attribute is never coerced to 0 |
| API | `handlers/api.py` | `availability: "UNKNOWN"` with `eligibleUnits: null` |
| Frontend | `components/StatusBadges.jsx`, `components/mapData.js` | renders "Not reported" with no number |
| Tests | `backend/tests/unit/test_unknown_is_not_zero.py` | **40 tests** |

40 tests for one rule looks excessive until you consider the consequence: a
doctor told "0 units" stops calling that blood bank, while "not reported"
means phone them. The two lead to opposite actions.

---

## 6. Finding database code — practical commands

```bash
# Every DynamoDB call in the backend
grep -rn "transact_write_items\|put_item\|update_item\|query\|get_item" backend/src/repositories/

# Where a specific table is used
grep -rn "facilities" backend/src/repositories/

# Every conditional write
grep -rn "ConditionExpression" backend/src/

# Every transaction
grep -rn "transact_write_items" backend/src/

# Table and GSI definitions in the template
grep -n "AWS::DynamoDB::Table" -A 5 infrastructure/template.yaml

# GSI names
grep -n "IndexName" infrastructure/template.yaml
```

---

## 7. Spoken answers

### 20–30 seconds

> "All database access goes through the repository layer — one module per table
> group, under `backend/src/repositories/`. Nothing above that layer writes
> DynamoDB directly. The tables are defined in two places for two different
> reasons: `infrastructure/template.yaml` creates them in AWS, and
> `repositories/schema.py` creates matching ones for the integration tests, so
> the tests run against the real table shape."

### 1–2 minutes

> "The part I'd show is `facility_repo.py` and the geohash search, because it's
> where the database shape and the business need meet.
>
> DynamoDB can't answer 'which facilities are within 20 kilometres of this
> point'. It can only answer 'give me items whose partition key equals this
> value'. So we encode each facility's location as a geohash — a short string
> where a shared prefix means geographic proximity — and index it. A search
> converts the circle into a set of geohash cells, queries those cells, and
> then filters the results with the haversine formula to get the true circle,
> because the cells over-cover it.
>
> We keep three indexes at precision four, five and six, and
> `choose_precision` picks one based on the radius. With a single precision
> you'd either return half of Punjab for a 2 km search or need hundreds of
> queries for a 50 km one."

---

## 8. Follow-up questions

**"If you have 24 indexes, isn't that expensive?"**
> Each GSI is billed for its own writes, so a write to the facilities table
> costs more because it propagates to five indexes. That is the trade-off for
> being able to query by three geohash precisions, by organization, and by
> verification state without a scan. Two of the inventory indexes keep the
> cost down deliberately — `GSI2-expiry` is `KEYS_ONLY`, and
> `GSI1-group-component` is `INCLUDE` with seven named attributes rather than
> `ALL`.

**"What happens if a GSI is still backfilling?"**
> A newly created index is unavailable until it finishes backfilling, and a
> query against it fails. In practice this only bites on a fresh deployment of
> a new index. All 24 of ours are `ACTIVE`.

**"Why is the outbox table empty?"**
> Because it is working. Rows are written, consumed by the stream, and expire
> by TTL. A permanently non-empty outbox would mean the publisher was failing.
> The same is true of the idempotency table.

---

## 9. Cross-references

- [../05_DATABASE_AND_DATA/01_DynamoDB_Data_Model.md](../05_DATABASE_AND_DATA/01_DynamoDB_Data_Model.md)
- [../05_DATABASE_AND_DATA/02_All_Tables_And_Indexes.md](../05_DATABASE_AND_DATA/02_All_Tables_And_Indexes.md)
- [../05_DATABASE_AND_DATA/05_Database_Access_Patterns.md](../05_DATABASE_AND_DATA/05_Database_Access_Patterns.md)
- [../05_DATABASE_AND_DATA/06_Concurrency_And_Data_Integrity.md](../05_DATABASE_AND_DATA/06_Concurrency_And_Data_Integrity.md)
- Original design rationale: `docs/DATABASE_DESIGN.md`
