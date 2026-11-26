# All Tables and Indexes — Reference

**REFERENCE ONLY.** Every table, every key, every index, every setting. Read
[01_DynamoDB_Data_Model.md](01_DynamoDB_Data_Model.md) first for the reasoning;
come here for the facts.

All values read from the live environment on 24 November 2026, region
`ap-southeast-2`, account `426150327442`.

---

## Settings common to all 12 tables

| Setting | Value |
|---|---|
| Partition key | `PK` (String) |
| Sort key | `SK` (String) |
| Billing mode | `PAY_PER_REQUEST` |
| Encryption | SSE-KMS, AWS-managed `alias/aws/dynamodb` (`95806067-…`) |
| Deletion protection | **disabled** |
| Status | `ACTIVE` |
| Local secondary indexes | **none on any table** |

**No LSIs anywhere.** An LSI must be created with the table and shares its
partition key; GSIs can be added later and use any key. Every access pattern
here needed a different partition key, so every index is a GSI.

---

## Summary table

| Table | Rows | Size | GSIs | TTL | PITR | Stream |
|---|---|---|---|---|---|---|
| `lifelink-dev-organizations` | 62 | 17,723 B | 1 | — | **ENABLED** | — |
| `lifelink-dev-facilities` | 16 | 12,310 B | **5** | — | **ENABLED** | — |
| `lifelink-dev-inventory` | **487** | 263,351 B | 2 | — | **ENABLED** | `NEW_AND_OLD_IMAGES` |
| `lifelink-dev-reservations` | 14 | 2,370 B | 2 | `purgeAtEpoch` | **ENABLED** | — |
| `lifelink-dev-camps` | 46 | 27,108 B | 4 | — | **ENABLED** | — |
| `lifelink-dev-donations` | 14 | 4,639 B | 1 | — | **ENABLED** | — |
| `lifelink-dev-emergency` | 59 | 28,923 B | 4 | — | **ENABLED** | — |
| `lifelink-dev-alerts` | 4 | 0 B* | 2 | `expiresAtEpoch` | disabled | — |
| `lifelink-dev-notifications` | 18 | 6,127 B | 1 | `expiresAtEpoch` | disabled | — |
| `lifelink-dev-audit` | 22 | 4,928 B | 1 | — | **ENABLED** | — |
| `lifelink-dev-outbox` | 0 | 0 B | 1 | `expiresAtEpoch` | disabled | `NEW_IMAGE` |
| `lifelink-dev-idempotency` | 0 | 0 B | 0 | `expiresAtEpoch` | disabled | — |
| **TOTAL** | **742** | **~367 KB** | **24** | 5 | 8 | 2 |

\* Sizes come from `DescribeTable` and refresh about every six hours, so a
recently-written table can report 0.

> **Row counts are live `Select=COUNT` scans.** The Console's item count comes
> from `DescribeTable`, refreshes roughly every **six hours**, and **differed on
> five tables** when checked: alerts (0 vs 4), audit (8 vs 22), emergency (85 vs
> 59), reservations (5 vs 14). **If the Console disagrees during a demo, that is
> why.**

---

## 1. `lifelink-dev-organizations` — 62 rows

Holds both organizations **and users**, which is why every authenticated
request reads this table.

| | |
|---|---|
| GSIs | 1 |
| `GSI1-status` | `GSI1PK` / `GSI1SK`, projection `ALL` |
| Answers | organizations awaiting verification |
| Used by | `GET /admin/organizations/pending` |
| Repository | `backend/src/repositories/identity_repo.py` |

**Why users live here:** a user is only meaningful in relation to an
organization — their role is scoped to it. Separating them would mean two reads
on every request instead of one.

---

## 2. `lifelink-dev-facilities` — 16 rows, 5 GSIs

The most heavily indexed table, because discovery is the most varied query.

| GSI | Keys | Projection | Answers |
|---|---|---|---|
| `GSI5-geo4` | `GSI5PK` / `GSI5SK` | `ALL` | facilities in a **precision-4** geohash cell (large radius) |
| `GSI1-geo5` | `GSI1PK` / `GSI1SK` | `ALL` | **precision-5** cell (medium radius) |
| `GSI2-geo6` | `GSI2PK` / `GSI2SK` | `ALL` | **precision-6** cell (small radius) |
| `GSI3-org` | `GSI3PK` / `GSI3SK` | `ALL` | facilities belonging to an organization |
| `GSI4-verification` | `GSI4PK` / `GSI4SK` | `ALL` | facilities by verification state |

**The three geohash tiers are chosen at query time** by
`domain/geo.py` `choose_precision(radius_km)`. One precision would be either
far too coarse for a 2 km search or far too fine for a 50 km one.

Repository: `backend/src/repositories/facility_repo.py`

---

## 3. `lifelink-dev-inventory` — 487 rows, the largest table

| GSI | Keys | Projection | Answers |
|---|---|---|---|
| `GSI1-group-component` | `GSI1PK` / `GSI1SK` | **`INCLUDE`**: `expiresAt`, `organizationId`, `lastVerifiedAt`, `status`, `availableUnits`, `lastUpdatedAt`, `batchId` | stock of a blood group + component across facilities |
| `GSI2-expiry` | `GSI2PK` / `GSI2SK` | **`KEYS_ONLY`** | batches by expiry date |

**The only two non-`ALL` projections in the whole database, and deliberately
so.** This is the biggest table, so its indexes are the ones where projection
cost actually matters:

- `GSI1-group-component` projects exactly the seven attributes the availability
  search renders — no more.
- `GSI2-expiry` is `KEYS_ONLY`, because the expiry sweep only needs to know
  *which* batches to fetch.

**Stream:** `NEW_AND_OLD_IMAGES` — a stock change is only meaningful with both
before and after values. "Stock changed" is useless; "stock went from 12 to 2"
is actionable.

Keys: `PK = FACILITY#<id>`, `SK = BATCH#<batchId>` — so a facility's batches
all share its partition.

Repository: `backend/src/repositories/inventory_repo.py`

---

## 4. `lifelink-dev-reservations` — 14 rows

**9 `RESERVATION` + 5 `RESERVATION_POOL` rows.**

| GSI | Projection | Answers |
|---|---|---|
| `GSI1-requester` | `ALL` | my reservations (`GET /me/reservations`) |
| `GSI2-expiry` | `ALL` | reservations due to expire (the maintenance sweep) |

**TTL attribute is `purgeAtEpoch`, not `expiresAtEpoch`** — and the difference
is deliberate. A reservation has a **business expiry** (the hold runs out) and
a **storage purge** much later. Using one attribute for both would delete the
record at the moment the user most wants to see that their hold expired.

Current state, verified:

| Status | Count |
|---|---|
| `CANCELLED` | 6 |
| `FULFILLED` | 1 |
| `EXPIRED` | 1 |
| `CONFIRMED` | 1 (**stale — see §1.15**) |
| `RESERVATION_POOL` rows | 5, **all with `heldUnits = 0`** |

**Every pool counter is zero — nothing is currently held.** That is the
healthy state and the first thing to check if a teacher asks whether the
counters are consistent.

Repository: `backend/src/repositories/reservation_repo.py`

---

## 5. `lifelink-dev-camps` — 46 rows, 4 GSIs

| GSI | Projection | Answers |
|---|---|---|
| `GSI1-geo` | `ALL` | camps near a location |
| `GSI2-user` | `ALL` | my registrations |
| `GSI3-organizer` | `ALL` | camps I organize (`GET /camps/mine`) |
| `GSI4-reminder` | `ALL` | camps needing reminders (the scheduled sweep) |

**Only one geohash tier here, against three for facilities.** Camp search uses
a single precision because camp searches are a narrower range of radii —
`effectiveRadiusKm` was 20 in the verified live search near Patiala.

Repository: `backend/src/repositories/camp_repo.py`

---

## 6. `lifelink-dev-donations` — 14 rows

| GSI | Projection | Answers |
|---|---|---|
| `GSI1-camp` | `ALL` | donations recorded at a camp |

Also served through `camp_repo.py`.

---

## 7. `lifelink-dev-emergency` — 59 rows, 4 GSIs

**Three entity types in one table**, verified by scan:

| `entityType` | Count |
|---|---|
| `REQUEST_EVENT` | **35** (10 seeded + 25 genuine) |
| `EMERGENCY_REQUEST` | **11** |
| `PROVIDER_RESPONSE` | **13** |

| GSI | Projection | Answers |
|---|---|---|
| `GSI1-dispatch` | `ALL` | requests awaiting dispatch (the dispatcher's query) |
| `GSI2-requester` | `ALL` | my organization's requests |
| `GSI3-provider` | `ALL` | requests awaiting my response (the provider queue) |
| `GSI4-deadline` | `ALL` | requests by deadline |

Keys — **the clearest example of the parent/child pattern in the database:**

| Entity | PK | SK |
|---|---|---|
| Request | `REQUEST#<id>` | `META` |
| Event | `REQUEST#<id>` | `EVENT#<iso>#<uuid8>` (application) or `EVENT#0000#seed0001` (seeder) |
| Response | `REQUEST#<id>` | `RESPONSE#<orgId>` |

**One `Query` on `PK = REQUEST#<id>` returns the request, every event and
every response, sorted.** A `begins_with(SK, "EVENT#")` condition narrows it to
the timeline.

**And the consequence:** `load_full_request` returns events in **sort-key**
order, which is why the seeded-duplication bug was visible as five
`REQUEST_CREATED` entries, and why §1.20's odd timeline ordering appears.

Repository: `backend/src/repositories/emergency_repo.py`

---

## 8. `lifelink-dev-alerts` — 4 rows

| GSI | Projection | Answers |
|---|---|---|
| `GSI1-user` | `ALL` | my alerts |
| `GSI2-match` | `ALL` | alerts matching newly posted stock |

TTL `expiresAtEpoch`. PITR **disabled** — alerts are short-lived by design.

**An alert never holds units** (ADR-0017). The frontend has a
`NotAReservationNotice` component whose only job is to say so.

Repository: `backend/src/repositories/alert_repo.py`

---

## 9. `lifelink-dev-notifications` — 18 rows

| GSI | Projection | Answers |
|---|---|---|
| `GSI1-status` | `ALL` | undelivered notifications |

TTL `expiresAtEpoch`. PITR disabled.

**In-app notifications work** — these 18 rows are served by
`GET /me/notifications`. Email is unconfigured (`SES_SENDER` empty) and SMS is
not implemented.

Repository: `backend/src/repositories/platform_repo.py`

---

## 10. `lifelink-dev-audit` — 22 rows

| GSI | Projection | Answers |
|---|---|---|
| `GSI1-actor` | `ALL` | actions by a user (`GET /admin/audit`) |

**No TTL. PITR enabled.** Audit records must not expire.

**The permission detail that makes this an audit trail:** the API role has
`dynamodb:PutItem` and `Query` on this table and **no `UpdateItem`, no
`DeleteItem`**. The maintenance role has `PutItem` **only**. So the
application can append audit records and read them back, and **cannot modify or
delete one** — enforced by IAM, not by convention.

**That is the single best thing to show about this table.**

---

## 11. `lifelink-dev-outbox` — 0 rows

| GSI | Projection | Answers |
|---|---|---|
| `GSI1-pending` | `ALL` | unpublished events |

**Stream: `NEW_IMAGE`** — the publisher only needs the new event, not the
previous state.

TTL `expiresAtEpoch`. PITR disabled.

**Zero rows is the correct steady state.** Rows are written in the same
transaction as a domain write, consumed by the stream, and expire by TTL. A
permanently non-empty outbox would mean the publisher was failing.

---

## 12. `lifelink-dev-idempotency` — 0 rows, 0 GSIs

**The only table with no index**, because it is only ever accessed by exact
key.

TTL `expiresAtEpoch`. PITR disabled.

Mechanism: a conditional put with `attribute_not_exists(PK)`. The second
attempt with the same idempotency key fails the condition, so a retried
request does not double-apply (ADR-0009).

**Zero rows is correct** — claims expire by TTL.

---

## 13. Why PITR is on 8 and off 4

| PITR enabled (8) | PITR disabled (4) |
|---|---|
| `organizations`, `facilities`, `inventory`, `reservations`, `camps`, `donations`, `emergency`, `audit` | `alerts`, `notifications`, `outbox`, `idempotency` |

**The four disabled tables are exactly the four with TTL and ephemeral
content.** Paying for continuous backups of records that delete themselves
within hours would be waste. The eight enabled tables hold records whose loss
would be unrecoverable.

**A deliberate cost/value trade-off — say so, rather than letting a teacher
assume four tables were forgotten.**

---

## 14. Quick CLI reference

```bash
P="--profile lifelink --region ap-southeast-2"

# List the tables
aws dynamodb list-tables $P

# One table's full configuration
aws dynamodb describe-table --table-name lifelink-dev-facilities $P

# TTL and PITR
aws dynamodb describe-time-to-live --table-name lifelink-dev-reservations $P
aws dynamodb describe-continuous-backups --table-name lifelink-dev-inventory $P

# An accurate row count (DescribeTable's count is ~6h stale)
aws dynamodb scan --table-name lifelink-dev-emergency --select COUNT $P

# One request plus all its events and responses
aws dynamodb query --table-name lifelink-dev-emergency \
  --key-condition-expression "PK = :pk" \
  --expression-attribute-values '{":pk":{"S":"REQUEST#demo-req-p1-1"}}' $P
```

**Every command above is read-only.** None modifies data.

---

## 15. Cross-references

- [01_DynamoDB_Data_Model.md](01_DynamoDB_Data_Model.md) — the reasoning
- [05_Database_Access_Patterns.md](05_Database_Access_Patterns.md) — query to index mapping
- [06_Concurrency_And_Data_Integrity.md](06_Concurrency_And_Data_Integrity.md)
- [../04_AWS_COMPLETE_GUIDE/06_DynamoDB.md](../04_AWS_COMPLETE_GUIDE/06_DynamoDB.md)
- [../09_PRACTICAL_AWS_DEMONSTRATIONS/04_Showing_DynamoDB_Records.md](../09_PRACTICAL_AWS_DEMONSTRATIONS/04_Showing_DynamoDB_Records.md)
- Original design rationale: `docs/DATABASE_DESIGN.md`
