# DynamoDB Data Model

**Why** the database is shaped the way it is. For the raw facts, see
[02_All_Tables_And_Indexes.md](02_All_Tables_And_Indexes.md).

---

## 1. The one idea you must understand

**DynamoDB only answers questions you designed for in advance.**

A relational database lets you ask anything with SQL, and you pay in query
performance. DynamoDB makes you decide the questions first, and you pay in
flexibility — but every question you *did* design for is answered in
single-digit milliseconds at any scale.

So the design process runs **backwards** from how you would design a relational
schema:

| Relational | DynamoDB |
|---|---|
| 1. Model the entities | 1. **List the queries** |
| 2. Normalise | 2. Design keys to serve them |
| 3. Write queries | 3. Add an index per query the keys cannot serve |
| 4. Add indexes where slow | 4. Accept that an unplanned query is expensive |

**Say this if asked how you designed the database:**
> "Backwards from how you'd do it relationally. With DynamoDB you list the
> queries first, then design keys to serve them, because the database only
> answers what you designed for. We ended up with 24 indexes, and that number is
> the honest cost of the approach — each one exists for a specific query. The
> flip side is that a query we didn't anticipate is genuinely expensive."

---

## 2. Decision one: twelve domain tables, not one

**ADR-0001.** Single-table design is *a* DynamoDB best practice, and we did not
follow it. Be ready to defend that.

**The case for single-table:** co-locating related items in one partition means
one round trip can fetch a parent and its children across entity types.

**Why we chose otherwise:**

| Reason | Detail |
|---|---|
| **IAM scoping** | One table per domain lets each Lambda role have a **separate policy per table**. That is how the dispatcher ends up genuinely unable to write inventory. With one table, every role would need access to everything in it |
| **Comprehensibility** | A small team reasoning about `lifelink-dev-inventory` is doing something easier than reasoning about overloaded keys in a shared table |
| **Blast radius** | A mistake in one domain's key design cannot corrupt another's |

**The honest cost:** cross-domain reads are explicit application-level joins.
The authorization check alone does a user lookup on `organizations` for every
single request.

**The first reason is the strong one** — it is a concrete security property,
not a preference. Lead with it.

> "Single-table is the usual advice and it does minimise round trips. We went
> with twelve domain tables mainly for a security reason: it lets us give each
> Lambda role a policy scoped to exactly the tables it needs. That's how our
> dispatcher can read inventory to rank blood banks and be physically unable to
> modify it. With one table, every role would need access to everything in it.
> The cost is that cross-domain reads are explicit joins in application code."

---

## 3. Decision two: parent and children share a partition

Every table uses `PK` + `SK`. Related items share the partition key and are
distinguished by a **structured** sort key.

```
PK = REQUEST#demo-req-p1-1
   SK = META                                  <- the request
   SK = EVENT#0000#seed0001                   <- a seeded event
   SK = EVENT#2026-11-16T14:10:20Z#c07d7f6f   <- a genuine event
   SK = RESPONSE#org-bb-patiala-1             <- a provider response
```

**What this buys:** one `Query` on `PK` returns the whole object graph, sorted.
`begins_with(SK, "EVENT#")` narrows it to the timeline. No joins, no second
round trip.

**Why prefix the keys** (`FACILITY#abc` rather than `abc`): the item type
becomes self-describing, a facility id cannot collide with a camp id, and a
scan's output is readable when debugging.

### The consequence that caused a real bug

`load_full_request` returns events in **sort-key order**. The seeder built its
event sort key from the run clock, so each run created a **new** key instead of
overwriting — five runs left five `REQUEST_CREATED` events on each demo
request, all rendered on the tracking page.

**The lesson:** in DynamoDB, **the sort key is the ordering and the identity at
once**. Deciding what varies in a sort key is deciding both what sorts first
and what counts as the same item. See
[03_Synthetic_Data_Generation.md](03_Synthetic_Data_Generation.md) §5.

---

## 4. Decision three: three geohash tiers

**The problem.** "Blood banks within 20 km of me" is not a question DynamoDB
can answer. There is no geospatial index.

**The solution** (ADR-0004), in `backend/src/domain/geo.py`:

```
1. encode_geohash(lat, lon)        -> a string whose prefix means proximity
2. index the prefix as a GSI partition key
3. choose_precision(radius_km)     -> 4, 5 or 6
4. search_cells(lat, lon, radius)  -> the cells covering the circle
5. Query each cell by index
6. haversine_km(...)               -> filter the union to the TRUE circle
```

**Step 6 is not optional.** Geohash cells are rectangles that **over-cover**
the circle. Without the haversine filter, a 20 km search would return a
facility 28 km away in the corner of a cell. The index narrows the candidates;
the formula gives the correct answer.

**Why three precisions:**

| Precision | Cell size | Suits |
|---|---|---|
| 4 | ~39 x 20 km | large radius |
| 5 | ~4.9 x 4.9 km | medium |
| 6 | ~1.2 x 0.6 km | small |

A single precision is either far too coarse for a 2 km search — returning much
of Punjab — or far too fine for a 50 km one, needing hundreds of cell queries.

**The guard:** `MAX_SEARCH_RADIUS_KM = 100.0`, and `search_cells` raises above
it. An unbounded request cannot become a table scan.

---

## 5. Decision four: two separate timestamp axes

**ADR-0003, and it is the clearest expression of the honesty rules in the data
model.**

| Attribute | Means |
|---|---|
| `lastUpdatedAt` | someone **typed a number** |
| `lastVerifiedAt` | someone **independently checked** it |

They drive **two separate badges** with **two separate thresholds**:

| | Thresholds |
|---|---|
| Freshness (from `lastUpdatedAt`) | `FRESH` <= 6 h, `AGING` <= 24 h, `STALE` <= 48 h, `OUTDATED` > 48 h |
| Verification (from `lastVerifiedAt`) | valid for **72 h** |

**Why not one quality score?** Because data can be recently updated and long
unverified, and collapsing them hides exactly the distinction that matters.
`inventory:write` and `inventory:verify` are even separate *permissions*, so
updating and verifying are different acts of trust.

### Two layers, and the rule between them

There is a facility-level **rollup** (`inventoryLastUpdatedAt`,
`inventoryLastVerifiedAt`) and **per-batch** timestamps.

| Situation | Behaviour |
|---|---|
| `/find` listing | **both badges come from the rollup** |
| Search filtered by group **and** component | batch data may override **freshness** |
| Any situation | **verification is NEVER overridden by batch data** |

**That last rule is deliberate.** Letting one freshly verified batch make a
whole facility look verified would be a false claim about the other batches.

---

## 6. Decision five: `UNKNOWN` is a value, not a missing number

Availability states: `UNKNOWN`, `NOT_STOCKED`, `UNAVAILABLE`, `PARTIAL`,
`AVAILABLE`.

| State | Means | Renders as |
|---|---|---|
| `UNKNOWN` | never reported | **"Not reported"**, no number |
| `NOT_STOCKED` | does not carry this component at all | "Not stocked" |
| `UNAVAILABLE` | carries it, has none | "None in stock" |
| `PARTIAL` / `AVAILABLE` | has some | the count |

**`UNKNOWN` and `UNAVAILABLE` are different facts that lead a doctor to
opposite actions:** "not reported" means phone them; "none in stock" means do
not. Rendering `UNKNOWN` as 0 would be a lie with clinical consequences.

Enforced at five levels — domain, repository, API, frontend, and **40 tests**
in `backend/tests/unit/test_unknown_is_not_zero.py`.

**40 tests for one rule looks excessive until you consider the consequence.**

---

## 7. Decision six: the transactional outbox

**ADR-0005.** "Write to the database, then publish an event" has two failure
modes:

1. Write commits, publish fails -> **event lost**
2. Publish succeeds, write rolls back -> **event for something that never
   happened**

**The fix:** write the domain record and its outbox row in **one**
`TransactWriteItems`. A DynamoDB Stream on the outbox table drives the
publisher.

**The consequence:** delivery is **at-least-once**, so consumers must be
idempotent — which is why the `idempotency` table exists (ADR-0009), with a
conditional put on `attribute_not_exists(PK)`.

---

## 8. Decision seven: the reservation pool counter

**The hardest correctness problem in the project.** Two hospitals must not be
able to reserve the same units.

**Design:** a `RESERVATION_POOL` row per facility + blood group + component,
carrying a `heldUnits` counter. A reservation and the counter move together in
one transaction, conditioned on the pool still having enough unreserved units:

```
Put    reservation row    ConditionExpression: attribute_not_exists(PK)
Update pool heldUnits     ConditionExpression: heldUnits + :units <= availableUnits
```

If the condition fails, **neither** write happens. Verified live: the second
concurrent requester receives `NO_UNRESERVED_STOCK`.

### The defect this design still allowed

The condition deciding whether a transition **releases** held units originally
asked *"was this reservation holding units?"* instead of *"does it stop holding
units?"*. Both are true when confirming a `PENDING` hold — so **confirming a
reservation released its own hold**, permitting overselling.

```python
releases = (
    reservation.status in HOLDING_STATES
    and updated.status not in HOLDING_STATES   # <- the missing half
)
```

Six regression tests were added; **four failed against the old code.** All
three transition paths were then verified live with counters read **directly
from DynamoDB**.

**The honest conclusion:** a good schema and 900+ passing tests did not catch
this. The data model was right; the state-transition logic above it was wrong.
Two of the four live defects in this project were invisible to the test suite.

---

## 9. What the model does badly

**Volunteer these. A balanced answer beats advocacy.**

| Weakness | Reality |
|---|---|
| **No ad-hoc queries** | "Average time from request to first response, by district, last quarter" is one SQL statement and genuinely awkward here |
| **24 indexes to maintain** | Every write propagates to every index on that table. `facilities` has five |
| **Explicit joins** | Every cross-domain read is a second call in application code |
| **400 KB item limit** | Shaped the design — events are separate items rather than a growing list. That turned out right anyway, since it makes the timeline queryable |
| **Hot partition risk** | A facility's batches share its partition key. A facility with thousands of batches would need a time component in the key |
| **`ItemCount` is approximate** | Refreshes ~every 6 hours; five tables disagreed with reality when checked |

---

## 10. Spoken answers

### 20–30 seconds
> "Twelve tables, one per domain, all with the same partition-key-plus-sort-key
> structure. Related items share a partition — an emergency request, all its
> events and all its provider responses have the same partition key, so one
> query fetches the whole thing sorted. We have 24 global secondary indexes,
> because DynamoDB only answers questions you designed for, so we listed the
> queries first and built an index for each one the keys couldn't serve."

### 1–2 minutes
> "The design process runs backwards from relational. You list the queries
> first, then design keys to serve them, because the database only answers what
> you planned for. That's why we have 24 indexes — each one exists for a
> specific query, and that number is the honest cost of the approach.
>
> Two decisions I'd defend. First, twelve domain tables rather than the
> single-table design DynamoDB usually recommends. The reason is security:
> separate tables let us scope each Lambda role's policy to exactly the tables
> it needs, which is how our dispatcher can read inventory and be physically
> unable to write it. With one table, every role would need access to everything
> in it.
>
> Second, we keep two separate timestamps on every stock record — when it was
> last updated and when it was last independently verified — with two different
> thresholds and two separate badges. Collapsing them into one quality score
> would hide the distinction that matters, because data can be freshly typed and
> long unverified. Updating and verifying are even separate permissions.
>
> The thing the model handles badly is ad-hoc reporting. If you asked me for
> average response time by district last quarter, that's one SQL query in
> Postgres and genuinely awkward here."

---

## 11. Follow-up questions

**"Why not use single-table design properly?"**
> Mainly the IAM reason — per-table policies are how we got genuinely
> least-privilege roles. Also comprehensibility for a small team. The cost is
> explicit cross-domain joins in application code; the authorization check alone
> reads the organizations table on every request. At much larger scale, or with
> heavily cross-domain access patterns, single-table would win on round trips.

**"How do you handle a schema change?"**
> DynamoDB is schemaless per item, so adding an attribute needs no migration —
> old items simply lack it, and the code treats a missing attribute as unknown
> rather than as zero, which is the same honesty rule again. A change that
> needs a **new index** is the real work: you add the GSI, wait for it to
> backfill, then start querying it. A change to a **key** is the hard case, and
> it means writing new items and migrating old ones.

**"What's your most complex query?"**
> Facility discovery. It picks a geohash precision from the radius, generates
> the covering cells, queries one of three GSIs per cell, filters the union with
> haversine to the true circle, labels each result's freshness and verification
> from the rollup timestamps, and ranks by distance, availability and freshness
> together. It's the one place where the index design, the domain logic and the
> honesty rules all meet.

---

## 12. Cross-references

- [02_All_Tables_And_Indexes.md](02_All_Tables_And_Indexes.md) — the facts
- [05_Database_Access_Patterns.md](05_Database_Access_Patterns.md)
- [06_Concurrency_And_Data_Integrity.md](06_Concurrency_And_Data_Integrity.md)
- [../04_AWS_COMPLETE_GUIDE/06_DynamoDB.md](../04_AWS_COMPLETE_GUIDE/06_DynamoDB.md)
- [../03_REPOSITORY_AND_CODE/05_Database_Code_Locations.md](../03_REPOSITORY_AND_CODE/05_Database_Code_Locations.md)
- Original: `docs/DATABASE_DESIGN.md`, `docs/ARCHITECTURE_DECISIONS.md`
