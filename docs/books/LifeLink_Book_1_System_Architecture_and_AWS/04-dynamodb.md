<!-- pagebreak -->

# 10. DynamoDB Fundamentals

Before the LifeLink data model makes sense, five DynamoDB properties need to be
clear, because every design decision in the next chapter is a response to one
of them.

## 10.1 The five properties that shape everything

**1. You query by key, not by predicate.** A `Query` must supply an exact
partition key. It may add a condition on the sort key. It cannot say "find rows
where expiry is soon" without a key that already organises rows that way. This
is why LifeLink has {{fact:gsi_count}} secondary indexes: each one exists
because some question needed a different key.

**2. A `Scan` reads the whole table.** It is not a slow query; it is a different
operation with unbounded cost. LifeLink forbids scans on user-facing paths. The
two places that scan — demo data wiping and dataset validation — are offline
maintenance jobs, and one of them logs that it scanned.

**3. Writes can be conditional.** `PutItem`, `UpdateItem` and `DeleteItem`
accept a `ConditionExpression` evaluated atomically at the item. This single
feature is how LifeLink prevents lost updates, negative stock, duplicate
registration and double credit, without any lock.

**4. Transactions span items, at a price.** `TransactWriteItems` commits up to
100 items atomically across tables, at twice the write cost. LifeLink uses it
only where an invariant genuinely spans items.

**5. Secondary indexes are eventually consistent.** Always. A write visible in
the base table may not yet be visible through a GSI. Any design that assumes
otherwise is wrong, and Section 11.7 explains where LifeLink absorbs that.

## 10.2 Partition keys and heat

A partition key determines physical placement. A key that concentrates traffic
creates a hot partition and throttles regardless of table-level capacity.

LifeLink's expiry sweep is the natural hot-key hazard: "find batches expiring
before now" wants a single key. The design shards it:

{{include:backend/src/repositories/inventory_repo.py:def expiry_shard}}

*Listing 10.1. Expiry sharding from `backend/src/repositories/inventory_repo.py`.
Ten shards, each swept independently.*

## 10.3 Composite sort keys do filtering for free

The most useful DynamoDB technique in this codebase is encoding several
attributes into a sort key so a range condition replaces a filter expression.

A filter expression is applied *after* items are read and billed. A sort-key
condition is applied *during* the read. For eligible-stock lookup the
difference is between reading every batch at a facility and reading only the
available, unexpired ones.

```
GSI1PK = FACILITY#<id>#<group>#<component>
GSI1SK = STATUS#<status>#<expiresAt>
```

A query for `GSI1SK between "STATUS#AVAILABLE#<now>"` and
`"STATUS#AVAILABLE#9999-..."` returns exactly the available, unexpired batches.
Quarantined, withdrawn and expired rows sort under different status prefixes
and are never read at all — they cannot leak into an availability answer by
accident, because the index never hands them over.

{{include:backend/src/repositories/inventory_repo.py:def list_eligible_batches}}

*Listing 10.2. The eligible-stock query. The comment explains the property that
makes it safe, not just what the code does.*

## 10.4 Capacity mode

Every table uses `PAY_PER_REQUEST`. Provisioned capacity would require
predicting throughput for a system with no traffic history, and would charge
for idle capacity. On-demand costs more per request but nothing at rest, which
matches a demonstration workload exactly.

<!-- pagebreak -->

# 11. The LifeLink Data Model

## 11.1 Why eleven tables rather than one

Single-table design is the conventional advice for DynamoDB, and LifeLink
deliberately does not follow it at the top level. The reasoning is recorded as
ADR-0001 and is worth restating, because it is the design's most contestable
decision.

| Consideration | Single table | Table per context | Winner here |
|---|---|---|---|
| Cross-entity reads in one query | Excellent | Needs two calls | Single table |
| IAM-enforced domain isolation | Impossible | Natural | **Per context** |
| Per-domain TTL policy | Awkward | Trivial | **Per context** |
| Per-domain backup policy | All or nothing | Independent | **Per context** |
| Blast radius of a bad migration | Whole system | One domain | **Per context** |
| Teaching clarity | Poor | Good | **Per context** |

*Table 11.1. The trade-off, made explicitly.*

The deciding factor is the second row. With one table, "Feature 3 must not
touch inventory" is a code-review convention. With separate tables it is an IAM
policy, and the platform enforces it whether or not anyone is paying attention.

Single-table techniques are still used *within* a context. A camp's metadata,
its registrations and its staff assignments share one partition, so an organiser
dashboard loads in a single query.

## 11.2 Access patterns

Thirty-nine access patterns were enumerated before any table was created. The
full catalogue is in `docs/DATABASE_DESIGN.md`; this is the structure.

| Feature | Patterns | Index used | Any scans? |
|---|---|---|---|
| Inventory | 7 | Base table, GSI1 group-component, GSI2 expiry | None |
| Availability alerts | 4 | GSI1 user, GSI2 match | None |
| Facilities | 4 | Three geohash GSIs, org GSI, verification GSI | None |
| Camps and donors | 9 | Base partition, geo, user, organizer, reminder | None |
| Emergency | 6 | Dispatch, requester, provider, deadline | None |
| Platform | 9 | Base, actor, delivery status, pending outbox | None |

*Table 11.2. Access patterns by feature. Every one resolves to a key query.*

## 11.3 The inventory table in detail

```diagram
type: layered
title: Inventory table and its two indexes
layer Base table
node base PK FACILITY id and SK BATCH id style=data
layer Index one
node gsi1 GSI1 group and component with status and expiry sort style=data
layer Index two
node gsi2 GSI2 sharded expiry sweep keys only style=data
layer Consumers
node avail Availability queries style=domain
node sweep Scheduled expiry sweep style=domain
node audit Batch audit history style=domain
edge base -> gsi1
edge base -> gsi2
edge gsi1 -> avail
edge gsi2 -> sweep
edge base -> audit
```

*Figure 11.1. One base table, two purpose-built indexes, three consumers.*

The index projections are chosen rather than defaulted:

- **GSI1** projects `INCLUDE` with exactly the seven attributes availability
  aggregation needs. `KEYS_ONLY` would force a base-table read per batch;
  `ALL` would double storage for attributes nobody reads on that path.
- **GSI2** projects `KEYS_ONLY`. The sweep only needs to know which batches to
  look at, and then reads them properly.

## 11.4 The emergency table and priority ordering

The dispatch index demonstrates a technique worth noticing:

```
GSI1PK = DISPATCH#<status>
GSI1SK = <effectivePriority>#<createdAt>
```

Querying that index in ascending sort order returns requests in priority order,
and FIFO within a priority band, with no sorting in application code. Priority
aging — raising a long-waiting request's dispatch priority — is implemented by
rewriting one attribute, which re-sorts the item in the index automatically.

Crucially, `effectivePriority` is a *different field* from `clinicalPriority`.
The scheduler writes the former and never the latter. Chapter 18 explains why
that separation is not merely tidy but a safety property.

## 11.5 Concurrency invariants and how each is enforced

| Invariant | Mechanism | Fails how |
|---|---|---|
| Stock never negative | `availableUnits >= :needed` condition | 409 `INSUFFICIENT_STOCK` |
| No lost inventory update | `version = :expected` condition | 409 `CONCURRENT_MODIFICATION` |
| No duplicate registration | `attribute_not_exists(SK)` | 409 `DUPLICATE` |
| Camp never oversubscribed | Transaction: registration put **and** counter update with capacity condition | 409 `CAPACITY_EXCEEDED` |
| Impact credited exactly once | Transaction: donation update **and** ledger put keyed on donation id | Transaction cancelled |
| No duplicate event processing | Idempotency claim keyed on event id | Second delivery is a no-op |
| Event never lost on crash | Outbox row in the same transaction as the domain write | Cannot occur |
| Stale update cannot overwrite | Source timestamp compared to stored | 400 with `STALE_UPDATE_REJECTED` |

*Table 11.3. Eight invariants, each enforced by the datastore rather than by
convention.*

The camp capacity row deserves a worked example because read-check-write is the
intuitive and wrong approach.

```diagram
type: sequence
title: Two donors claim the final seat at the same instant
actor a Donor A
actor b Donor B
actor svc Camp service
actor ddb DynamoDB
msg a -> svc register
msg b -> svc register
msg svc -> ddb A transaction put registration and increment under capacity
msg svc -> ddb B transaction put registration and increment under capacity
msg ddb -> svc A committed
msg ddb -> svc B cancelled condition failed
msg svc -> b capacity exceeded
note Both passed the advisory pre-check. Only the transaction decides.
```

*Figure 11.2. The capacity transaction. The service performs a friendly
pre-check for a good error message, but the transaction is authoritative.*

{{include:backend/src/repositories/camp_repo.py:def register_atomically}}

*Listing 11.1. The capacity transaction from
`backend/src/repositories/camp_repo.py`.*

## 11.6 Pagination

Cursor-based throughout. The cursor is an opaque base64 encoding of DynamoDB's
`LastEvaluatedKey` **plus a fingerprint of the query that produced it**. A
cursor presented against a different query is rejected rather than silently
producing wrong results.

Offset pagination is not offered. DynamoDB cannot do it efficiently, and
emulating it would mean reading and discarding rows — a scan wearing a disguise.

## 11.7 Living with eventual consistency

GSIs are eventually consistent, always. LifeLink handles that in three ways.

**Where it does not matter, it is ignored.** A facility search that misses a
batch written 50 milliseconds ago is not a problem; the data is seconds old by
nature.

**Where it matters, a strongly consistent base-table read is used.** Re-reading
a batch after a failed conditional write uses `ConsistentRead`, because the
retry must see the value that beat it.

**Where it could cause duplicate work, idempotency absorbs it.** The dispatcher
reads a GSI and may see a request it has already picked up. That is harmless:
the work is idempotent, so the second attempt is a no-op.

## 11.8 Retention, backup and recovery

| Data | Retention | PITR | Reasoning |
|---|---|---|---|
| Audit | 7 years (assumed, pending legal review) | Yes, CMK-encrypted | Regulatory posture |
| Donations and ledger | Indefinite while the account lives | Yes | Donor's own record |
| Inventory | Indefinite; status transitions, no deletion | Yes | Historical traceability |
| Camps and emergency | Indefinite | Yes | Audit and dispute resolution |
| Alerts | TTL at the alert's expiry | No | Short-lived by nature |
| Notifications | TTL at 90 days | No | Reconstructible |
| Idempotency | TTL at 24 hours | No | Reconstructible by definition |
| Outbox | TTL at 7 days after dispatch | No | Transient |

*Table 11.4. Retention and recovery by data class.*

Three tables deliberately have no point-in-time recovery. That is not an
oversight: PITR on a TTL-bound, fully reconstructible table is spend with no
recovery value.

## 11.9 What the data model does not do

Stated so no reader infers capability that is absent:

- **No allocation or clinical-release model.** A reservation holds units for a
  bounded time; it is not a cross-match, not clinical approval and not a
  guarantee of release, and those stay with qualified staff. Temporary
  reservations themselves *are* modelled — see ADR-0018 and §28.7. An earlier
  edition said "no reservation or allocation model", which was true then.
- **No cross-region replication.** Unavailable on this account.
- **No analytics or read-model store.** Dashboard aggregates are computed per
  request. At real scale this would need a projection, and that is recorded as
  future work rather than described as if it exists.
- **No real institutional data path.** Only verified onboarding or authorized
  staff updates may introduce real data. Everything currently in the system is
  synthetic and labelled as such.
