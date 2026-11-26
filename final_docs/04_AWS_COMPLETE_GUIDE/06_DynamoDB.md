# DynamoDB

The database. 12 tables, 24 global secondary indexes, 742 rows of
demonstration data, all in `ap-southeast-2`.

---

## 1. What DynamoDB is

**Simple version.** A managed NoSQL key-value and document database. You give
it a key, it gives you an item, in single-digit milliseconds, at any scale.

**The analogy, and where it breaks.** It is like a gigantic dictionary: look up
a key, get a value. The analogy breaks exactly where the interesting part
begins — a dictionary cannot answer "which entries are near Patiala", and
neither can DynamoDB unless you designed an index for it in advance.

**Mechanism.** Items are distributed across partitions by a hash of the
**partition key**. A request for a known key goes straight to one partition,
which is why performance does not degrade as the table grows. Within a
partition, items are sorted by **sort key**, so a range query on the sort key is
cheap.

**Why LifeLink uses it:**

| Reason | Detail |
|---|---|
| Access patterns are known | Our queries were designed before the tables were |
| No capacity planning | On-demand absorbs spikes; nothing idles |
| Cost at demo scale | 742 rows and low traffic costs effectively nothing |
| Serverless fit | No connection pool. Lambda can open and close freely — a relational database's connection limits are a genuine problem for Lambda |

**That last point is the strongest technical argument** and the one most people
miss. A relational database has a connection limit; Lambda can scale to many
concurrent executions each wanting a connection. You end up needing RDS Proxy
to fix a problem DynamoDB does not have.

---

## 2. DynamoDB versus RDS — the comparison teachers ask for

| | DynamoDB | RDS (PostgreSQL/MySQL) |
|---|---|---|
| Model | key-value / document | relational |
| Query language | API operations | SQL |
| Joins | **none** — the application joins | native |
| Ad-hoc queries | **hard** — needs an index | easy |
| Scaling | automatic, unlimited | vertical, then read replicas |
| Connections | **stateless HTTPS** | connection pool, limited |
| Schema | per-item, flexible | fixed, migrations |
| Billing | per request or provisioned | per instance-hour, **running or not** |
| Cost when idle | **~$0** | the instance bill continues |
| Transactions | up to 100 items | full ACID |

### When RDS would have been the better choice

**Say this if asked, because the balanced answer is more convincing than
advocacy:**

> "If we needed ad-hoc reporting — 'average time between an emergency request
> and the first provider response, grouped by district, for last quarter' —
> that's one SQL query against Postgres and a genuine problem in DynamoDB,
> because we'd have to have designed an index for it in advance or scan the
> whole table. We accepted that: we designed 24 indexes up front for the
> queries we knew about, and anything we didn't anticipate is expensive.
>
> The things that pushed us to DynamoDB were the connection model and the idle
> cost. Lambda can scale to many concurrent executions, and each one wanting a
> database connection is a real problem with RDS — you end up adding RDS Proxy
> to solve it. DynamoDB is stateless HTTPS, so there's nothing to pool. And an
> RDS instance bills by the hour whether anyone uses it; ours costs nothing when
> idle."

---

## 3. The 12 tables

All: partition key `PK`, sort key `SK`, `PAY_PER_REQUEST`, SSE-KMS with
`alias/aws/dynamodb`, deletion protection **off**.

| Table | Live rows | GSIs | TTL | PITR | Stream |
|---|---|---|---|---|---|
| `lifelink-dev-organizations` | 62 | 1 | — | yes | — |
| `lifelink-dev-facilities` | 16 | **5** | — | yes | — |
| `lifelink-dev-inventory` | **487** | 2 | — | yes | **NEW_AND_OLD_IMAGES** |
| `lifelink-dev-reservations` | 14 | 2 | `purgeAtEpoch` | yes | — |
| `lifelink-dev-camps` | 46 | 4 | — | yes | — |
| `lifelink-dev-donations` | 14 | 1 | — | yes | — |
| `lifelink-dev-emergency` | 59 | 4 | — | yes | — |
| `lifelink-dev-alerts` | 4 | 2 | `expiresAtEpoch` | no | — |
| `lifelink-dev-notifications` | 18 | 1 | `expiresAtEpoch` | no | — |
| `lifelink-dev-audit` | 22 | 1 | — | yes | — |
| `lifelink-dev-outbox` | 0 | 1 | `expiresAtEpoch` | no | **NEW_IMAGE** |
| `lifelink-dev-idempotency` | 0 | 0 | `expiresAtEpoch` | no | — |

**Row counts are live `Select=COUNT` scans.** The Console's item count comes
from `DescribeTable`, refreshes roughly every **six hours**, and **differed on
five tables** when checked. If the Console disagrees with reality during a
demo, that is why — and explaining it calmly is far better than looking
confused.

### Why 12 domain tables instead of one

ADR-0001. Single-table design is *a* DynamoDB best practice, for a specific
reason: co-locating related items minimises round trips. Two things pushed the
other way here:

1. **IAM scoping.** One table per domain lets each Lambda role have a separate
   policy per table. That is how the dispatcher ends up genuinely unable to
   write inventory. With one table, every role would need access to everything
   in it.
2. **Comprehensibility.** A small team reasoning about `lifelink-dev-inventory`
   is doing something easier than reasoning about overloaded keys in a single
   table.

**The honest cost:** cross-domain reads are explicit application-level joins.

---

## 4. Keys and why they are shaped that way

| Entity | PK | SK |
|---|---|---|
| Facility | `FACILITY#<id>` | `META` |
| Inventory batch | `FACILITY#<id>` | `BATCH#<batchId>` |
| Emergency request | `REQUEST#<id>` | `META` |
| Request event | `REQUEST#<id>` | `EVENT#<iso>#<uuid8>` |
| Provider response | `REQUEST#<id>` | `RESPONSE#<orgId>` |
| Reservation pool | facility + group + component | `POOL` |

**The pattern: a parent and its children share a partition key.** Everything
about request `X` — the request itself, its events, and every provider response
— is in one partition. One `Query` with `PK = REQUEST#X` returns the whole
object graph in one request, sorted. A `begins_with(SK, "EVENT#")` condition
narrows it to the timeline.

**Why prefix the keys at all?** `FACILITY#abc` rather than `abc` makes the item
type self-describing, prevents a collision between a facility id and a camp id,
and makes a scan's output readable during debugging.

**The consequence that caused a real bug:** `load_full_request` returns events
in **sort-key** order. The seeder originally built its event sort key from the
run clock, so every seed run created a **new** key rather than overwriting —
and five runs left five `REQUEST_CREATED` events on each demo request, all
rendered on the tracking page. See
[../05_DATABASE_AND_DATA/04_Database_Seeding_Workflow.md](../05_DATABASE_AND_DATA/04_Database_Seeding_Workflow.md).

---

## 5. Global secondary indexes — all 24

A **GSI** is a second view of the table with a different partition and sort
key, maintained automatically. It is what makes a query possible that the main
key cannot answer.

| Table | GSI | Answers |
|---|---|---|
| `facilities` | `GSI5-geo4` | facilities in a coarse geohash cell |
| | `GSI1-geo5` | medium geohash cell |
| | `GSI2-geo6` | fine geohash cell |
| | `GSI3-org` | facilities belonging to an organization |
| | `GSI4-verification` | facilities by verification state |
| `inventory` | `GSI1-group-component` | stock of a blood group + component across facilities |
| | `GSI2-expiry` | batches by expiry date |
| `emergency` | `GSI1-dispatch` | requests awaiting dispatch |
| | `GSI2-requester` | my organization's requests |
| | `GSI3-provider` | requests awaiting my response |
| | `GSI4-deadline` | requests by deadline |
| `camps` | `GSI1-geo` | camps near a location |
| | `GSI2-user` | my registrations |
| | `GSI3-organizer` | camps I organize |
| | `GSI4-reminder` | camps needing reminders |
| `reservations` | `GSI1-requester` | my reservations |
| | `GSI2-expiry` | reservations to expire |
| `alerts` | `GSI1-user` | my alerts |
| | `GSI2-match` | alerts matching new stock |
| `organizations` | `GSI1-status` | organizations pending verification |
| `donations` | `GSI1-camp` | donations at a camp |
| `notifications` | `GSI1-status` | undelivered notifications |
| `audit` | `GSI1-actor` | actions by a user |
| `outbox` | `GSI1-pending` | unpublished events |

### Projections — where the cost control is

| GSI | Projection |
|---|---|
| `inventory.GSI1-group-component` | **`INCLUDE`** with 7 attributes: `expiresAt`, `organizationId`, `lastVerifiedAt`, `status`, `availableUnits`, `lastUpdatedAt`, `batchId` |
| `inventory.GSI2-expiry` | **`KEYS_ONLY`** |
| the other 22 | `ALL` |

**Why this matters.** A GSI stores a copy of the projected attributes, and you
pay for that storage and for the writes that maintain it. `inventory` is the
biggest table at 487 rows, so its two indexes are the ones worth trimming:

- `GSI1-group-component` projects exactly the seven attributes the availability
  search renders — no more.
- `GSI2-expiry` is `KEYS_ONLY`, because the expiry sweep only needs to know
  *which* batches to fetch.

**The trade-off to state:** a `KEYS_ONLY` or `INCLUDE` index that is missing an
attribute you need forces a second read back to the table. So the projection
list is a decision, not a default — and getting it wrong in either direction
costs either storage or latency.

---

## 6. Query, Scan, GetItem — and what LifeLink uses

| Operation | Cost | Where we use it |
|---|---|---|
| `GetItem` | cheapest — one item by full key | user lookup on every request, facility detail |
| `Query` | efficient — one partition, optional sort-key range | everything else in the request path |
| `BatchGetItem` | several `GetItem`s in one call | cross-domain fetches |
| `TransactWriteItems` | up to 100 items, all-or-nothing | reservations, the outbox |
| **`Scan`** | **reads the whole table** | **operator tooling only** — never in the request path |

**"Do you ever scan?"** — in `scripts/seed_cloud.py` and
`scripts/dedupe_request_events.py`, both tools a human runs by hand, where
reading a whole small table once is entirely appropriate. **In the API, never.**
Every read is a `GetItem` or a `Query` against a key or an index. That is what
the 24 GSIs are for.

---

## 7. The geohash search — the best DynamoDB story in the project

**The problem.** "Find blood banks within 20 km of me" is a question DynamoDB
cannot answer. There is no geospatial index.

**The solution,** in `backend/src/domain/geo.py`:

1. **Encode** each facility's latitude and longitude as a **geohash** — a
   string where a shared prefix means geographic proximity.
2. **Index** the prefix as a GSI partition key.
3. On search, `choose_precision(radius_km)` picks precision 4, 5 or 6.
4. `search_cells(lat, lon, radius_km)` returns the geohash cells covering the
   circle.
5. Query each cell by index.
6. **Filter the union with `haversine_km`** down to the true circle.

```python
EARTH_RADIUS_KM = 6371.0088
MAX_SEARCH_RADIUS_KM = 100.0
```

**Why step 6 is essential.** Geohash cells are rectangles and they
**over-cover** the circle. Without the haversine filter, a search for 20 km
would return facilities at 28 km in the corner of a cell. The index narrows the
candidates; the formula gives the correct answer.

**Why three precisions.** A geohash cell has a fixed size per precision. One
precision is either far too coarse for a 2 km search — returning much of Punjab
— or far too fine for a 50 km one, needing hundreds of cell queries. Choosing
by radius keeps the query count small at every scale.

**The guard:** `search_cells` raises if the radius exceeds 100 km, so an
unbounded request cannot turn into a table scan.

### Say this
> "DynamoDB can't do 'within twenty kilometres of here', so we built it with
> geohashes. A geohash turns a coordinate into a short string where a shared
> prefix means things are near each other, so we index the prefix and query it
> like any other key.
>
> A search converts the circle into the set of geohash cells covering it,
> queries those cells, and then filters the results with the haversine formula.
> That second step matters: the cells are rectangles that over-cover the circle,
> so without it a twenty-kilometre search would return something twenty-eight
> kilometres away in the corner of a cell. The index narrows the candidates and
> the formula gives the right answer.
>
> We keep three indexes at precision four, five and six and pick one by radius,
> because with a single precision you'd either return half of Punjab for a
> two-kilometre search or need hundreds of queries for a fifty-kilometre one."

---

## 8. Concurrency and data integrity

Full treatment:
[../05_DATABASE_AND_DATA/06_Concurrency_And_Data_Integrity.md](../05_DATABASE_AND_DATA/06_Concurrency_And_Data_Integrity.md).

| Mechanism | Where | Protects |
|---|---|---|
| **Conditional write** on `version` | `inventory_repo.py` | two staff editing the same batch |
| **`TransactWriteItems`** | `reservation_repo.py` | reservation + pool counter move together |
| **Condition on available units** | `reservation_repo.py` | overselling |
| **Conditional put** `attribute_not_exists` | `platform_repo.py` | double-applying a retried request |

Verified live: a second requester against a fully-held pool is refused with
`NO_UNRESERVED_STOCK`, and all three reservation transition paths were checked
with counters read **directly from DynamoDB**.

---

## 9. Console demonstration

```
DynamoDB -> Tables  ->  12 tables prefixed lifelink-dev-
```

| Step | What to show |
|---|---|
| 1 | The table list — 12 tables, one naming convention |
| 2 | `lifelink-dev-facilities` -> **Explore table items** -> 16 facilities with `PK = FACILITY#...` |
| 3 | **Indexes** tab -> five GSIs, including the three geohash tiers |
| 4 | `lifelink-dev-inventory` -> Indexes -> note `GSI2-expiry` is `KEYS_ONLY` |
| 5 | **Backups** tab -> PITR enabled |
| 6 | **Additional settings** -> encryption with `aws/dynamodb`; TTL on the four tables that have it |
| 7 | **Exports and streams** -> the stream on `inventory` |
| 8 | `lifelink-dev-emergency` -> filter `PK = REQUEST#demo-req-p1-1` -> the request, its events and responses **in one partition** |

Step 8 is the one that makes the key design click for an audience.

**Do not** use "Create item", "Edit", or "Delete" during a demonstration.
Hand-edited data cannot be reproduced by re-seeding.

---

## 10. Spoken answers

### 20–30 seconds
> "Twelve DynamoDB tables in on-demand billing mode, with 24 global secondary
> indexes between them. Every table has the same key structure — a partition key
> and a sort key — and related items share a partition, so one query gets an
> emergency request plus all its events and provider responses together.
> Everything's encrypted at rest with KMS, and point-in-time recovery is on for
> the eight tables holding durable records."

### 1–2 minutes
> "We chose DynamoDB over a relational database for two main reasons. The first
> is the connection model: Lambda scales to many concurrent executions, and each
> one wanting a database connection is a real problem with RDS — you end up
> adding RDS Proxy to fix it. DynamoDB is stateless HTTPS, so there's nothing to
> pool. The second is idle cost — an RDS instance bills by the hour whether
> anyone uses it; ours costs effectively nothing.
>
> The price we pay is that queries have to be designed in advance. That's why we
> have 24 indexes. If someone asked me for a report we hadn't anticipated —
> average time from emergency request to first response, by district, last
> quarter — that's one SQL statement in Postgres and genuinely awkward here.
>
> The design choice I'd defend hardest is using twelve domain tables instead of
> one single table. Single-table is the usual DynamoDB advice, and it does
> minimise round trips. But separate tables let us give each Lambda role a
> policy scoped to exactly the tables it needs — which is how our dispatcher
> ends up able to read inventory and physically unable to write it. With one
> table, every role would need access to everything in it."

---

## 11. Follow-up questions

**"What happens if a partition gets too hot?"**
> DynamoDB adaptive capacity redistributes throughput towards a hot partition
> automatically, and on-demand mode scales. Our realistic hot partition is a
> single busy facility's inventory, since batches share the facility's partition
> key — a facility with thousands of batches would be worth splitting by adding
> a time component to the key. At 487 rows total it is not a problem yet, and
> there is an alarm on inventory throttles if it becomes one.

**"Why is PITR off on four tables?"**
> Those four — alerts, notifications, outbox, idempotency — all have TTL set and
> hold data that deletes itself within hours. Paying for continuous backups of
> self-deleting records would be waste. The eight tables with PITR hold records
> whose loss would be unrecoverable.

**"What's the biggest limitation you hit?"**
> No joins, and no ad-hoc querying. Every cross-domain read is an explicit
> second call in application code — the authorization check alone does a user
> lookup on every request. And the 400 KB item size limit shaped the design:
> request events are separate items rather than a growing list on the request,
> which turned out to be right for other reasons too, since it makes the
> timeline queryable.

**"The Console shows a different item count than you said."**
> That's expected. `DescribeTable`'s item count is approximate and refreshes
> about every six hours. The accurate number comes from a `Select=COUNT` scan —
> when I checked, five of the twelve tables disagreed with the Console.

---

## 12. Cross-references

- [../05_DATABASE_AND_DATA/01_DynamoDB_Data_Model.md](../05_DATABASE_AND_DATA/01_DynamoDB_Data_Model.md)
- [../05_DATABASE_AND_DATA/02_All_Tables_And_Indexes.md](../05_DATABASE_AND_DATA/02_All_Tables_And_Indexes.md)
- [../05_DATABASE_AND_DATA/05_Database_Access_Patterns.md](../05_DATABASE_AND_DATA/05_Database_Access_Patterns.md)
- [../09_PRACTICAL_AWS_DEMONSTRATIONS/04_Showing_DynamoDB_Records.md](../09_PRACTICAL_AWS_DEMONSTRATIONS/04_Showing_DynamoDB_Records.md)
- [../09_PRACTICAL_AWS_DEMONSTRATIONS/CONFIGURATION_WALKTHROUGHS.md](../09_PRACTICAL_AWS_DEMONSTRATIONS/CONFIGURATION_WALKTHROUGHS.md) §C
