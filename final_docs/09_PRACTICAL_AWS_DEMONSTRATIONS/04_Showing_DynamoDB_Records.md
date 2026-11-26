# Showing DynamoDB Records

"Show me the database." The demonstration, the records to open, and the
Console gotcha to get ahead of.

---

## 1. The sequence

```
DynamoDB -> Tables -> filter "lifelink"     (12 tables)
```

| # | Show | Say |
|---|---|---|
| 1 | the 12-table list | "twelve tables, one naming convention, one per domain" |
| 2 | `lifelink-dev-facilities` -> **Explore table items** | "16 facilities, every key prefixed `FACILITY#`" |
| 3 | the same table -> **Indexes** | "five GSIs — three are geohash tiers for different search radii" |
| 4 | `lifelink-dev-emergency` -> filter `PK = REQUEST#demo-req-p1-1` | **the best moment — see §3** |
| 5 | `lifelink-dev-inventory` -> Indexes | "`GSI2-expiry` is `KEYS_ONLY` — deliberate, this is our biggest table" |
| 6 | **Backups** tab | "PITR on, for the eight tables holding durable records" |
| 7 | **Additional settings** | encryption with `aws/dynamodb`; TTL where it exists |
| 8 | **Exports and streams** | "the stream on inventory uses NEW_AND_OLD_IMAGES" |

---

## 2. Get ahead of the item-count gotcha

**Say this BEFORE anyone notices:**

> "One thing to flag: the item count you see in the Console comes from
> `DescribeTable`, and it's **approximate** — it refreshes roughly every six
> hours. When I checked with an actual count scan, **five of the twelve tables
> disagreed**. So if the number on screen doesn't match what I quote, that's
> why, not because I'm making it up."

| Table | Console said | Actual |
|---|---|---|
| `alerts` | 0 | **4** |
| `audit` | 8 | **22** |
| `emergency` | 85 | **59** |
| `reservations` | 5 | **14** |

**Pre-empting this turns a potential stumble into a point of expertise.**

```bash
# The accurate way
aws dynamodb scan --table-name lifelink-dev-emergency --select COUNT \
  --profile lifelink --region ap-southeast-2
```

---

## 3. The record to open — the key design, visible

```
DynamoDB -> lifelink-dev-emergency -> Explore table items
  -> Filter:  PK = REQUEST#demo-req-p1-1
```

You get the request **and its events and its provider responses**, all in one
result:

```
PK = REQUEST#demo-req-p1-1
   SK = META                                  <- the request
   SK = EVENT#0000#seed0001                   <- a seeded event
   SK = EVENT#2026-11-16T14:10:20Z#c07d7f6f   <- a GENUINE event
   SK = RESPONSE#org-bb-patiala-1             <- a provider response
```

**Say this:**
> "This is the key design in one screen. Everything about this request — the
> request itself, every event in its timeline, and every provider response —
> shares one partition key. So a single query returns the whole object graph,
> already sorted, with no joins. The sort key prefix tells you the item type,
> and `begins_with(SK, 'EVENT#')` narrows it to just the timeline.
>
> Look at the two event keys. One is `EVENT#0000#seed0001` — that's the seeder,
> deterministic so re-seeding overwrites. The other ends in a random uuid
> fragment — that's the application, append-only, because real history has to
> accumulate. Two writers with two opposite correct behaviours, and getting that
> wrong was a real bug we fixed."

**This is the single most instructive record in the database.**

---

## 4. The reservation pool — the counters

```
DynamoDB -> lifelink-dev-reservations -> Explore table items
```

**14 rows: 9 `RESERVATION` + 5 `RESERVATION_POOL`.**

**Open a `RESERVATION_POOL` row and point at `heldUnits`:**

> "This counter is how we stop two hospitals reserving the same units. Creating
> a reservation writes the reservation row and updates this counter in a single
> DynamoDB transaction, conditioned on `heldUnits` plus the requested units not
> exceeding what's available. All five pools currently read zero, which is the
> healthy state — nothing is held right now.
>
> And this counter is where we found our worst bug. Confirming a reservation used
> to *release* its own hold, which allows overselling. Nine hundred passing
> tests didn't catch it; the first live run of confirm-then-cancel did."

Statuses to point out: 6 `CANCELLED`, 1 `FULFILLED`, 1 `EXPIRED`, and **1
`CONFIRMED` that is stale** (§1.15) — holds nothing, and the UI displays it as
expired because `isStaleHold()` compares the clock to the status.

---

## 5. The indexes

```
DynamoDB -> lifelink-dev-facilities -> Indexes
```

| Index | Say |
|---|---|
| `GSI5-geo4`, `GSI1-geo5`, `GSI2-geo6` | "three geohash precisions. We pick one from the search radius — a single precision is either far too coarse for a 2 km search or needs hundreds of queries for 50 km" |
| `GSI3-org` | "facilities belonging to an organization — this is what makes a scoped list a query rather than a filter" |
| `GSI4-verification` | "facilities by verification state, for the `verifiedOnly` filter" |

Then `lifelink-dev-inventory -> Indexes`:

| Index | Projection | Say |
|---|---|---|
| `GSI1-group-component` | **`INCLUDE`**, 7 attributes | "exactly the attributes the availability search renders, no more" |
| `GSI2-expiry` | **`KEYS_ONLY`** | "the expiry sweep only needs to know *which* batches to fetch, then reads them by key" |

**Say this:**
> "These are the only two non-`ALL` projections in the whole database, and
> that's deliberate — inventory is our biggest table at 487 rows, so its indexes
> are where projection cost actually matters. Every GSI stores a copy of the
> projected attributes, and you pay for that storage and for the writes
> maintaining it."

---

## 6. The settings tabs

### Backups

| | |
|---|---|
| PITR **enabled** | `organizations`, `facilities`, `inventory`, `reservations`, `camps`, `donations`, `emergency`, `audit` |
| PITR **disabled** | `alerts`, `notifications`, `outbox`, `idempotency` |

**Say this before being asked:**
> "Point-in-time recovery is on for the eight tables holding durable records and
> off for four. That's deliberate, not an oversight: those four are exactly the
> four with TTL set — they hold data that deletes itself within hours. Paying
> for continuous backups of self-deleting records would be waste.
>
> And a PITR restore always creates a **new** table — it's a recovery tool, not
> an undo button."

### Additional settings

| Setting | Value |
|---|---|
| Encryption | **SSE-KMS**, AWS-managed `alias/aws/dynamodb` |
| TTL | `reservations`: **`purgeAtEpoch`**; the other three: `expiresAtEpoch` |
| Capacity mode | **On-demand** |
| **Deletion protection** | **Off** |

**On the TTL attribute name:**
> "Notice reservations uses `purgeAtEpoch` rather than `expiresAtEpoch`. That's
> deliberate — a reservation has a business expiry, when the hold runs out, and
> a storage purge much later. Using one attribute for both would delete the
> record at the exact moment the user most wants to see that their hold
> expired."

**On deletion protection, don't defend it:**
> "It's off on all twelve, which is a demo trade-off — it blocks a stack delete
> and this environment gets rebuilt. In production I'd turn it on for every
> table holding real records, because it's free and the failure it prevents is
> unrecoverable."

### Exports and streams

| Table | Stream |
|---|---|
| `inventory` | **`NEW_AND_OLD_IMAGES`** |
| `outbox` | **`NEW_IMAGE`** |

> "Different view types on purpose. The outbox publisher only needs the new
> event, so `NEW_IMAGE` is enough. Inventory needs both images, because a change
> event is only meaningful with before and after — 'stock changed' is useless;
> 'stock went from 12 to 2' is actionable."

---

## 7. The empty tables are not a problem

| Table | Rows | Why zero is correct |
|---|---|---|
| `outbox` | **0** | rows are written in a transaction, consumed by the stream, and expire by TTL. A permanently non-empty outbox would mean the publisher was failing |
| `idempotency` | **0** | claims expire by TTL |

**Say this if asked:**
> "Both are empty, and that's the correct steady state rather than a sign
> nothing works. The outbox is written and drained continuously — if it were
> permanently full, the publisher would be broken. Same for idempotency claims;
> they expire."

---

## 8. Do not

| Action | Why |
|---|---|
| **Create item / Edit / Delete item** | hand-edited production data cannot be reproduced by re-seeding |
| Change capacity mode | template-controlled |
| Toggle PITR or TTL | template-controlled |
| Enable deletion protection | would block a stack teardown |
| Create an on-demand backup | harmless but pointless |

**Explore table items is read-only as long as you only read.** Open items,
filter, scroll. Do not click the action buttons.

---

## 9. Questions and answers

**"Why 12 tables instead of one?"**
> Single-table design is the usual DynamoDB advice and it does minimise round
> trips. We went with domain tables mainly for a security reason: separate
> tables let us scope each Lambda role's policy to exactly the tables it needs.
> That's how our dispatcher can read inventory and be physically unable to write
> it. With one table, every role would need access to everything in it. The cost
> is that cross-domain reads are explicit joins in application code.

**"Can you show me a query rather than a scan?"**
> Yes — Explore table items lets you choose Query and give a partition key.
> `PK = REQUEST#demo-req-p1-1` is the one to use, because it returns a request
> with all its events and responses. That's a query against one partition, which
> is what every read in our API does; there's no scan anywhere in the request
> path.

**"What's the largest table?"**
> Inventory, at 487 rows and about 260 KB — eight blood groups times several
> components times multiple batches with different expiry dates. It's also the
> only table where we trimmed index projections, for exactly that reason.

**"How much does this cost?"**
> Effectively nothing. On-demand billing with 742 rows and low traffic sits well
> inside the free tier, and the AWS-managed KMS key is free. A customer-managed
> key would be about a dollar a month per key.

---

## 10. Cross-references

- [CONFIGURATION_WALKTHROUGHS.md](CONFIGURATION_WALKTHROUGHS.md) §C
- [../05_DATABASE_AND_DATA/02_All_Tables_And_Indexes.md](../05_DATABASE_AND_DATA/02_All_Tables_And_Indexes.md)
- [../05_DATABASE_AND_DATA/01_DynamoDB_Data_Model.md](../05_DATABASE_AND_DATA/01_DynamoDB_Data_Model.md)
- [../04_AWS_COMPLETE_GUIDE/06_DynamoDB.md](../04_AWS_COMPLETE_GUIDE/06_DynamoDB.md)
