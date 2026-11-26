# Database Access Patterns

Every query the application makes, which index serves it, and why. This is the
document that shows the 24 indexes were designed rather than accumulated.

---

## 1. The rule

**Every read in the request path is a `GetItem` or a `Query`.** There is no
`Scan` in the API.

| Operation | Cost | Used in the API? |
|---|---|---|
| `GetItem` | cheapest — one item by full key | **yes** |
| `Query` | one partition, optional sort-key range | **yes** |
| `BatchGetItem` | several `GetItem`s in one call | yes |
| `TransactWriteItems` | up to 100 items, all-or-nothing | yes (writes) |
| **`Scan`** | **reads the whole table** | **never** |

**Scans exist only in operator tooling** — `seed_cloud.py` counting rows for
its preview, and `dedupe_request_events.py`. Both are run by a human, once,
against small tables, where reading the whole thing is entirely appropriate.

**Say this:**
> "Every read in the API is either a GetItem by key or a Query against a key or
> an index — there's no scan anywhere in the request path. That's what the 24
> indexes are for. We do scan in two operator scripts, but those are tools a
> human runs by hand against small tables, which is a completely different cost
> profile from a request path."

---

## 2. The access pattern table

### Authentication and authorization — on every single request

| Pattern | Operation | Table / index |
|---|---|---|
| Load the calling user's role, organization and status | **`GetItem`** | `organizations` |

**This is the most frequent operation in the system** — once per authenticated
request. It is a `GetItem` by exact key, which is the cheapest read DynamoDB
offers, and it is the price of reading roles from stored state rather than from
the token. A few milliseconds buys immediate revocation.

### Feature 2 — Discovery

| Pattern | Operation | Table / index |
|---|---|---|
| Facilities within a radius | `Query` x N cells | `facilities` / **`GSI5-geo4`**, **`GSI1-geo5`** or **`GSI2-geo6`** by radius |
| Facility detail | `GetItem` | `facilities` |
| Availability matrix for a facility | `Query` | `inventory` (`PK = FACILITY#<id>`, `begins_with(SK, "BATCH#")`) |
| Stock of a group + component across facilities | `Query` | `inventory` / **`GSI1-group-component`** |
| Facilities of an organization | `Query` | `facilities` / **`GSI3-org`** |
| Facilities by verification state | `Query` | `facilities` / **`GSI4-verification`** |

**The geohash search is the only multi-query read in the API** — one `Query`
per covering cell, then a haversine filter in application code. The number of
cells is bounded by `choose_precision`, which is exactly why three tiers exist.

### Feature 1 — Inventory

| Pattern | Operation | Table / index |
|---|---|---|
| List a facility's batches | `Query` | `inventory` (`begins_with(SK, "BATCH#")`) |
| One batch | `GetItem` | `inventory` |
| Batch audit history | `Query` | `audit` / **`GSI1-actor`** |
| Batches nearing expiry | `Query` | `inventory` / **`GSI2-expiry`** (`KEYS_ONLY`) |
| Create / adjust / verify a batch | `UpdateItem` with `ConditionExpression` on `version` | `inventory` |

**`GSI2-expiry` is `KEYS_ONLY` on purpose:** the expiry sweep only needs to
know *which* batches to fetch, then reads those by key. Projecting every
attribute would cost storage and write throughput for data the sweep discards.

### Feature 2/1 — Reservations

| Pattern | Operation | Table / index |
|---|---|---|
| My reservations | `Query` | `reservations` / **`GSI1-requester`** |
| A facility's reservation queue | `Query` | `reservations` (facility partition) |
| Request a hold | **`TransactWriteItems`** | `reservations` — row + pool counter |
| Decide / cancel / fulfil | `TransactWriteItems` | `reservations` |
| Reservations due to expire | `Query` | `reservations` / **`GSI2-expiry`** |

### Feature 3 — Camps and donors

| Pattern | Operation | Table / index |
|---|---|---|
| Camps near a location | `Query` | `camps` / **`GSI1-geo`** |
| Camp detail | `GetItem` | `camps` |
| My registrations | `Query` | `camps` / **`GSI2-user`** |
| Camps I organize | `Query` | `camps` / **`GSI3-organizer`** |
| Camps needing reminders | `Query` | `camps` / **`GSI4-reminder`** |
| Donations at a camp | `Query` | `donations` / **`GSI1-camp`** |
| My donation history | `Query` | `donations` |

### Feature 4 — Emergency coordination

| Pattern | Operation | Table / index |
|---|---|---|
| **Request + all events + all responses** | **one `Query`** | `emergency` (`PK = REQUEST#<id>`) |
| Just the timeline | `Query` | `emergency` (`begins_with(SK, "EVENT#")`) |
| My organization's requests | `Query` | `emergency` / **`GSI2-requester`** |
| Requests awaiting my response | `Query` | `emergency` / **`GSI3-provider`** |
| Requests awaiting dispatch | `Query` | `emergency` / **`GSI1-dispatch`** |
| Requests by deadline | `Query` | `emergency` / **`GSI4-deadline`** |
| Append an event | `PutItem` | `emergency` |

**The first row is the best demonstration of the key design.** A request, its
entire timeline and every provider response come back in **one** query,
already sorted, because they share a partition key. No joins.

### Feature 6 — Account, notifications, administration

| Pattern | Operation | Table / index |
|---|---|---|
| My alerts | `Query` | `alerts` / **`GSI1-user`** |
| Alerts matching new stock | `Query` | `alerts` / **`GSI2-match`** |
| My notifications | `Query` | `notifications` |
| Undelivered notifications | `Query` | `notifications` / **`GSI1-status`** |
| Organizations pending verification | `Query` | `organizations` / **`GSI1-status`** |
| Audit by actor | `Query` | `audit` / **`GSI1-actor`** |
| Unpublished outbox events | `Query` | `outbox` / **`GSI1-pending`** |
| Claim an idempotency key | `PutItem` with `attribute_not_exists(PK)` | `idempotency` |

---

## 3. Every index justified

**The exercise that proves the indexes were designed:** each of the 24 maps to
at least one pattern above.

| Table | GSIs | All justified? |
|---|---|---|
| `facilities` | 5 | yes — 3 geohash tiers, org, verification |
| `emergency` | 4 | yes — dispatch, requester, provider, deadline |
| `camps` | 4 | yes — geo, user, organizer, reminder |
| `inventory` | 2 | yes — group+component, expiry |
| `reservations` | 2 | yes — requester, expiry |
| `alerts` | 2 | yes — user, match |
| `organizations` | 1 | yes — pending verification |
| `donations` | 1 | yes — by camp |
| `notifications` | 1 | yes — undelivered |
| `audit` | 1 | yes — by actor |
| `outbox` | 1 | yes — pending |
| `idempotency` | **0** | correct — only ever accessed by exact key |

**`idempotency` having zero indexes is itself a design signal:** it is only
ever read by the exact key the client supplied, so an index would be pure cost.

---

## 4. The expensive patterns, named honestly

| Pattern | Cost | Why it is acceptable |
|---|---|---|
| Geohash search | **N queries** (one per cell) | N is bounded by `choose_precision`; radius capped at 100 km |
| User lookup per request | 1 extra `GetItem` | the price of immediate role revocation |
| Reservation write | `TransactWriteItems` (2 items) | correctness is worth more than one write unit |
| Writes to `facilities` | propagate to **5 indexes** | 16 rows, written rarely |
| Writes to `inventory` | propagate to 2 indexes | mitigated by `KEYS_ONLY` / `INCLUDE` projections |

### The pattern that would be genuinely expensive — and is not implemented

**"Average time from emergency request to first provider response, by
district, for last quarter."**

No index serves it. Options would be a full scan of the `emergency` table, a
new GSI designed for it, or exporting to S3 and querying with Athena.

**Say this when asked about reporting:**
> "That's the honest weakness of the design. A query we didn't anticipate is
> expensive, and that one in particular — aggregating across requests by
> district and time — isn't served by any index. In Postgres it's one SQL
> statement. Here I'd either add a GSI designed for it, or export to S3 and
> query it with Athena, which is the normal answer for analytics on DynamoDB.
> Trying to do it live against the table would mean a scan."

---

## 5. Consistency

| | Behaviour |
|---|---|
| `GetItem` default | **eventually consistent** |
| `GetItem` with `ConsistentRead=True` | strongly consistent, costs 2x |
| `Query` on a table | can be strongly consistent |
| **`Query` on a GSI** | **always eventually consistent — no option** |
| `TransactWriteItems` | fully atomic |

**The consequence that matters:** a GSI read is **always** eventually
consistent. A row written a moment ago may not yet appear in an index query.

**Where this is handled:** the reservation counter is never read from an index.
The pool row is read and written by its exact key inside a transaction, so the
counter cannot be stale at the moment it matters.

**That is the right answer to "what about eventual consistency?"** — not "it's
fine", but "here is where it would have mattered and here is what we did about
it."

---

## 6. Finding the code for any pattern

```bash
# All DynamoDB operations
grep -rn "transact_write_items\|put_item\|update_item\|\.query(\|get_item" backend/src/repositories/

# Which code uses a given index
grep -rn "GSI1-geo5\|IndexName" backend/src/repositories/

# Every conditional write
grep -rn "ConditionExpression" backend/src/

# Confirm there is no scan in the request path
grep -rn "\.scan(" backend/src/        # expect no results
grep -rn "\.scan(" scripts/            # expect the two operator tools
```

**That last pair of commands is a good live demonstration** — it proves the
claim rather than asserting it.

---

## 7. Spoken answers

### 20–30 seconds
> "Every read in the API is a GetItem by key or a Query against a key or an
> index — there's no scan in the request path at all, which is what the 24
> indexes are for. The pattern I'd point to is the emergency request: because
> the request, its events and its provider responses all share a partition key,
> one query returns the whole thing already sorted. No joins."

### 1–2 minutes
> "We designed the queries before the tables, so each of the 24 indexes maps to
> a specific access pattern. The facilities table has five — three geohash
> precisions for different search radii, one for an organization's facilities,
> and one for verification state. The emergency table has four — requests
> awaiting dispatch, my organization's requests, requests awaiting my response,
> and requests by deadline. The idempotency table has none, because it's only
> ever read by the exact key the client supplied, so an index would be pure cost.
>
> Two patterns worth calling out. The most frequent operation in the whole
> system is a single GetItem on the organizations table, because we load the
> user's role from the database on every authenticated request rather than
> trusting the token. That's the cheapest read DynamoDB offers, and it buys
> immediate role revocation.
>
> And the one genuine weakness: a GSI read is always eventually consistent,
> with no option to force strong consistency. That would matter for our
> reservation counters — so we never read the counter from an index. The pool
> row is read and written by exact key inside a transaction, which is strongly
> consistent."

---

## 8. Cross-references

- [01_DynamoDB_Data_Model.md](01_DynamoDB_Data_Model.md)
- [02_All_Tables_And_Indexes.md](02_All_Tables_And_Indexes.md)
- [06_Concurrency_And_Data_Integrity.md](06_Concurrency_And_Data_Integrity.md)
- [../03_REPOSITORY_AND_CODE/05_Database_Code_Locations.md](../03_REPOSITORY_AND_CODE/05_Database_Code_Locations.md)
- Original: `docs/DATABASE_DESIGN.md`
