# LifeLink — DynamoDB Data Model and Access Patterns

Derived from the application's actual queries, per spec §2.3. Design rationale is in [ADR-0001](ARCHITECTURE_DECISIONS.md#adr-0001) (domain-aligned tables), [ADR-0002](ARCHITECTURE_DECISIONS.md#adr-0002) (optimistic concurrency) and [ADR-0004](ARCHITECTURE_DECISIONS.md#adr-0004) (geohash).

**Global conventions**

| Convention | Rule |
|---|---|
| Billing | `PAY_PER_REQUEST` — unpredictable demo load, no capacity planning, no idle cost |
| Encryption | SSE with an AWS-managed KMS key; customer-managed key for `lifelink-audit` |
| PITR | Enabled on all tables holding durable domain state; disabled on `lifelink-idempotency` (TTL-bound, reconstructible) |
| Timestamps | UTC ISO-8601 with `Z` ([ADR-0016](ARCHITECTURE_DECISIONS.md#adr-0016)) |
| Soft delete | Domain records are never hard-deleted; `status` transitions instead. TTL applies only to idempotency, outbox (dispatched) and expired alerts |
| Demo marking | Every seeded item carries `demoData: true`, `dataSource: SYNTHETIC`, `environment: DEVELOPMENT` (§11.3) |
| Scans | Forbidden on user-facing paths. Permitted only in offline maintenance jobs, which must log their use |

---

## 1. Access pattern catalogue

Every query the application performs, with the index that serves it. **No pattern resolves to a Scan.**

### Feature 1 — Inventory

| # | Access pattern | Table | Index | Key condition |
|---|---|---|---|---|
| AP-01 | Get batch by id | `inventory` | base | `PK=FACILITY#<fid>`, `SK=BATCH#<bid>` |
| AP-02 | List all batches at a facility | `inventory` | base | `PK=FACILITY#<fid>`, `SK begins_with BATCH#` |
| AP-03 | Eligible batches by group + component at a facility | `inventory` | `GSI1-group-component` | `GSI1PK=FACILITY#<fid>#<group>#<component>`, `GSI1SK > STATUS#AVAILABLE#<now>` |
| AP-04 | Batches expiring before T (sweep) | `inventory` | `GSI2-expiry` | `GSI2PK=EXPIRY_SHARD#<0-9>`, `GSI2SK < <iso>` |
| AP-05 | Batch audit history | `inventory` | base | `PK=BATCH#<bid>`, `SK begins_with AUDIT#` |
| AP-06 | Availability summary for a facility | derived | — | AP-03 per (group, component), aggregated in memory |
| AP-07 | Deduct / add / quarantine units | `inventory` | base | Conditional `UpdateItem` on version + non-negative |

`GSI1SK` is `STATUS#<status>#<expiresAt>`, so a single range condition filters to available, unexpired stock without a filter expression. Expired or quarantined batches sort outside the queried range and are never read as eligible (§3.4).

AP-04 shards by `hash(batchId) % 10` to avoid a hot partition on the expiry sweep.

### Feature 1 — Availability alerts

| # | Access pattern | Table | Index | Key condition |
|---|---|---|---|---|
| AP-08 | Get alert by id | `alerts` | base | `PK=ALERT#<aid>`, `SK=META` |
| AP-09 | A user's active alerts | `alerts` | `GSI1-user` | `GSI1PK=USER#<uid>`, `GSI1SK begins_with ACTIVE#` |
| AP-10 | Active alerts matching a group+component in a geocell | `alerts` | `GSI2-match` | `GSI2PK=MATCH#<geohash5>#<group>#<component>`, `GSI2SK > ACTIVE#<now>` |
| AP-11 | Expire alerts past deadline | `alerts` | TTL + `GSI2` | TTL on `expiresAt` |

AP-10 is the reverse-index that makes "stock arrived → who was waiting?" a query rather than a scan. When a batch becomes available, the ingestion worker computes the facility's `geohash5` and queries AP-10 directly.

### Feature 1 — Temporary reservations

Added after [ADR-0018](ARCHITECTURE_DECISIONS.md#adr-0018). This is the
**ordinary request workflow** — a user asking a blood bank for units places a
reservation. There is no separate blood-request entity; see that ADR for why.

| # | Access pattern | Table | Index | Key condition |
|---|---|---|---|---|
| AP-40 | Holds against one pool (facility + group + component) | `reservations` | base | `PK=FACILITY#<fid>`, `SK begins_with RES#<group>#<component>#` |
| AP-41 | Every hold at a facility (staff queue) | `reservations` | base | `PK=FACILITY#<fid>`, `SK begins_with RES#` |
| AP-42 | Get one hold | `reservations` | base | `PK=FACILITY#<fid>`, `SK=RES#<group>#<component>#<rid>` |
| AP-43 | A user's own holds, newest first | `reservations` | `GSI1-requester` | `GSI1PK=USER#<uid>`, `GSI1SK=<createdAt>` |
| AP-44 | Holds whose time has passed (expiry sweep) | `reservations` | `GSI2-expiry` | `GSI2PK=RESSTATUS#<status>`, `GSI2SK < <now>` |
| AP-45 | Units currently held for a pool (counter) | `reservations` | base | `PK=FACILITY#<fid>`, `SK=POOL#<group>#<component>` |

AP-45 is the item that makes overselling impossible. It is not a cache of
AP-40 — it is the value a conditional `TransactWriteItems` tests and updates in
the same transaction that writes the hold, so two callers racing for the last
units cannot both succeed.

Because the **write** path tests this counter while **display** computes held
units from the rows (AP-40), the two must never diverge. They did once, on
24 November 2026: a service-layer bug decremented the counter when a hold was
confirmed, so the screen showed units reserved while the write path would let
another caller take them. Fixed the same day, with the seam now covered by
tests — [RESERVATION_COUNTER_DEFECT](RESERVATION_COUNTER_DEFECT.md). Nothing
yet *asserts* that the counter and the rows agree; that check is recorded as
future work in [KNOWN_LIMITATIONS](KNOWN_LIMITATIONS.md) §1.16.

AP-44 queries **only the two holding states**, so the sweep is two bounded
queries rather than a scan. Expiry is processed actively rather than left to
TTL: DynamoDB TTL deletes within roughly 48 hours on a best-effort basis, which
would leave units held long after the hold ended. That is a correctness
problem, not a tidiness one, so `purgeAtEpoch` exists for cleanup only and is
**never** the release mechanism.

Group and component are part of the sort key, which is why every mutating call
(`cancel`, `decision`, `fulfil`) must carry `bloodGroup` and `component` in its
body — omitting one yields "no such reservation" rather than a validation
error, so the frontend centralises it in one helper.

### Feature 2 — Facilities and location

| # | Access pattern | Table | Index | Key condition |
|---|---|---|---|---|
| AP-12 | Get facility by id | `facilities` | base | `PK=FACILITY#<fid>`, `SK=META` |
| AP-13 | Facilities near a point | `facilities` | `GSI1-geo5` / `GSI2-geo6` | `GSIxPK=GEO#<prefix>` — centre cell + 8 neighbours |
| AP-14 | Facilities owned by an organization | `facilities` | `GSI3-org` | `GSI3PK=ORG#<oid>` |
| AP-15 | Facilities by verification status (admin) | `facilities` | `GSI4-verification` | `GSI4PK=VERIFICATION#<status>` |

### Feature 3 — Camps, donors, impact

| # | Access pattern | Table | Index | Key condition |
|---|---|---|---|---|
| AP-16 | Get camp + its registrations in one query | `camps` | base | `PK=CAMP#<cid>` (SK `META`, `REG#<uid>`, `STAFF#<uid>`) |
| AP-17 | Upcoming camps near a point | `camps` | `GSI1-geo` | `GSI1PK=GEO#<geohash5>`, `GSI1SK > UPCOMING#<now>` |
| AP-18 | A user's registrations | `camps` | `GSI2-user` | `GSI2PK=USER#<uid>`, `GSI2SK begins_with REG#` |
| AP-19 | Camps by organizer | `camps` | `GSI3-organizer` | `GSI3PK=ORG#<oid>` |
| AP-20 | Duplicate-registration check | `camps` | base | Conditional put on `PK=CAMP#<cid>`, `SK=REG#<uid>` |
| AP-21 | Camps needing a reminder in window | `camps` | `GSI4-reminder` | `GSI4PK=REMINDER#<24H\|2H>`, `GSI4SK` between now and now+5min |
| AP-22 | A donor's donation records | `donations` | base | `PK=USER#<uid>`, `SK begins_with DONATION#` |
| AP-23 | A donor's impact ledger | `donations` | base | `PK=USER#<uid>`, `SK begins_with LEDGER#` |
| AP-24 | Donations at a camp | `donations` | `GSI1-camp` | `GSI1PK=CAMP#<cid>` |

AP-16 is the single-table technique applied *within* a bounded context: camp metadata, registrations and staff assignments share a partition, so an organizer dashboard loads in one query.

AP-20 is the concurrency defence for §12.3 "concurrent final-seat registration" — see §3 below.

### Feature 4 — Emergency coordination

| # | Access pattern | Table | Index | Key condition |
|---|---|---|---|---|
| AP-25 | Get request + responses + transitions | `emergency` | base | `PK=REQUEST#<rid>` (SK `META`, `RESPONSE#<oid>`, `EVENT#<ts>`) |
| AP-26 | Dispatcher: pending by effective priority | `emergency` | `GSI1-dispatch` | `GSI1PK=DISPATCH#<status>`, `GSI1SK=<effectivePriority>#<createdAt>` |
| AP-27 | Requests raised by an organization | `emergency` | `GSI2-requester` | `GSI2PK=ORG#<oid>` |
| AP-28 | Requests routed to a provider | `emergency` | `GSI3-provider` | `GSI3PK=PROVIDER#<oid>`, `GSI3SK begins_with PENDING#` |
| AP-29 | Requests past deadline | `emergency` | `GSI4-deadline` | `GSI4PK=ACTIVE`, `GSI4SK < <now>` |
| AP-30 | Duplicate-request fingerprint check | `idempotency` | base | Conditional put on fingerprint |

`GSI1SK` sorting on `effectivePriority#createdAt` gives the dispatcher FIFO *within* a priority band for free, and priority aging (ADR-0006) works by rewriting `effectivePriority` — which re-sorts the item in the index with no extra machinery.

### Platform

| # | Access pattern | Table | Index | Key condition |
|---|---|---|---|---|
| AP-31 | Get user profile + roles | `organizations` | base | `PK=USER#<sub>`, `SK=PROFILE` |
| AP-32 | Organization members | `organizations` | base | `PK=ORG#<oid>`, `SK begins_with MEMBER#` |
| AP-33 | Notification preferences | `notifications` | base | `PK=USER#<uid>`, `SK=PREFERENCES` |
| AP-34 | A user's in-app notifications | `notifications` | base | `PK=USER#<uid>`, `SK begins_with NOTIF#` (descending) |
| AP-35 | Notification delivery status | `notifications` | `GSI1-status` | `GSI1PK=DELIVERY#<status>` |
| AP-36 | Audit by resource | `audit` | base | `PK=RESOURCE#<type>#<id>`, `SK=<ts>#<eventId>` |
| AP-37 | Audit by actor | `audit` | `GSI1-actor` | `GSI1PK=ACTOR#<uid>` |
| AP-38 | Idempotency lookup | `idempotency` | base | `PK=<idempotencyKey>` |
| AP-39 | Undispatched outbox rows | `outbox` | `GSI1-pending` | `GSI1PK=PENDING`, `GSI1SK=<occurredAt>` |

---

## 2. Table definitions

### `lifelink-inventory`

| Attribute | Type | Notes |
|---|---|---|
| `PK` | S | `FACILITY#<fid>` or `BATCH#<bid>` (audit rows) |
| `SK` | S | `BATCH#<bid>` or `AUDIT#<ts>#<eventId>` |
| `batchId` | S | ULID — sortable by creation |
| `facilityId`, `organizationId` | S | `organizationId` is the isolation key checked by ADR-0007 |
| `bloodGroup` | S | `A+ A- B+ B- AB+ AB- O+ O-` |
| `component` | S | `WHOLE_BLOOD PRBC FFP PLATELETS` — stored separately from group (§3.2) |
| `availableUnits` | N | Never negative; enforced by condition expression |
| `status` | S | `AVAILABLE QUARANTINED EXPIRED WITHDRAWN CONSUMED` |
| `collectedAt`, `processedAt`, `expiresAt` | S | ISO-8601 UTC; `expiresAt` nullable but then status cannot be `AVAILABLE` (§3.4) |
| `lastUpdatedAt`, `updateSource` | S | Any write ([ADR-0003](ARCHITECTURE_DECISIONS.md#adr-0003)) |
| `lastVerifiedAt`, `verifiedBy`, `verificationStatus` | S | Human verification only |
| `quarantineReason`, `restrictions` | S/L | |
| `version` | N | Optimistic concurrency |
| `demoData`, `dataSource`, `environment` | BOOL/S | |

**GSI1-group-component** — PK `FACILITY#<fid>#<group>#<component>`, SK `STATUS#<status>#<expiresAt>`, projection: `INCLUDE` (`availableUnits`, `batchId`, `lastUpdatedAt`, `verificationStatus`).
Keys-only would force a second read per batch for ranking; a full projection would double storage. `INCLUDE` carries exactly the five attributes ranking needs.

**GSI2-expiry** — PK `EXPIRY_SHARD#<0-9>`, SK `<expiresAt>`, projection `KEYS_ONLY`. The sweep only needs keys, then reads the batch to transition it.

### `lifelink-reservations`

One partition per facility, so every hold against a facility — and the pool
counter that governs them — lives together and can be read or transacted in
one place.

| Attribute | Type | Notes |
|---|---|---|
| `PK` | S | `FACILITY#<fid>` |
| `SK` | S | `RES#<group>#<component>#<rid>` for a hold, `POOL#<group>#<component>` for the counter |
| `reservationId` | S | ULID |
| `facilityId`, `organizationId` | S | `organizationId` is the isolation key checked by [ADR-0007](ARCHITECTURE_DECISIONS.md#adr-0007); it is what makes a cross-organization decision a 403 |
| `requesterUserId` | S | Only this user may cancel |
| `bloodGroup`, `component` | S | **Part of the sort key.** Every mutating call must carry both |
| `units` | N | 1 to 10; one request may not sterilise a facility's stock |
| `status` | S | `PENDING CONFIRMED REJECTED CANCELLED EXPIRED FULFILLED` |
| `createdAt`, `expiresAt`, `releasedAt` | S | ISO-8601 UTC. `expiresAt` is always set — a hold without an end is not a hold |
| `decidedByUserId`, `decisionReason` | S | The reason is shown to the requester |
| `version` | N | Optimistic concurrency, as elsewhere |
| `purgeAtEpoch` | N | TTL, 30 days after expiry. **Cleanup only, never the release mechanism** |

**Only `PENDING` and `CONFIRMED` hold units.** That one sentence is the
invariant the whole module protects, and `FULFILLED` is deliberately not among
them: the units left the shelf, so they are consumed rather than returned to
availability.

**GSI1-requester** — PK `USER#<uid>`, SK `<createdAt>`, projection `ALL`.
Serves "my reservations" newest-first without reading each facility partition.

**GSI2-expiry** — PK `RESSTATUS#<status>`, SK `<expiresAt>`, projection `ALL`.
Partitioning by status means the sweep queries only the two states that hold
units.

#### Effective versus stored status

A hold whose `expiresAt` has passed holds nothing **immediately**, whether or
not a sweep has rewritten the row. Availability calculations and every display
use the effective reading, so an unprocessed expiry cannot keep units held. The
API returns both — `status` (effective) and `storedStatus` (raw) — and the
interface says so when they differ, rather than hiding a stale row behind a
live-looking label.

### `lifelink-camps`

Single partition per camp holds metadata, registrations and staff (AP-16).

| `SK` pattern | Item |
|---|---|
| `META` | Camp record: name, organizer, location, geohashes, `startsAt`/`endsAt`, `capacity`, `registeredCount`, `status`, `registrationDeadline` |
| `REG#<uid>` | Registration: `registeredAt`, `status`, `checkedInAt`, `attendanceStatus` |
| `STAFF#<uid>` | Staff assignment with scoped permissions |

Lifecycle: `PENDING_APPROVAL → UPCOMING → ONGOING → COMPLETED`, with `CANCELLED` and `REJECTED` as terminal branches (§5.2). Invalid transitions are rejected by a transition table in the service layer, not by ad-hoc `if` statements.

### `lifelink-emergency`

| `SK` pattern | Item |
|---|---|
| `META` | Request: group, component, units, location, `requiredBy`, `clinicalPriority`, `effectivePriority`, `status`, `hospitalVerificationState` |
| `RESPONSE#<oid>` | Provider response: `ACCEPTED REJECTED INSUFFICIENT_STOCK NEEDS_CLARIFICATION`, `unitsOffered`, `respondedAt` |
| `EVENT#<ts>#<uuid8>` | Lifecycle transition with actor and reason (§6.8 audit trail), written by `append_event`. Append-only: the uuid suffix keeps two events at the same instant distinct |
| `EVENT#<nnnn>#seed0001` | A **synthetic** seeded event. The ordinal is deterministic so re-seeding overwrites rather than accumulates, and it sorts before any ISO timestamp so a seeded creation event stays first in the timeline. `occurredAt` still carries a realistic time, and that is what the API returns. See [KNOWN_LIMITATIONS](KNOWN_LIMITATIONS.md) §1.19 |

`clinicalPriority` is immutable except via the certification endpoint, which requires `HOSPITAL_AUTHORIZER` and writes an audit record. `effectivePriority` is scheduler-owned and freely rewritten ([ADR-0006](ARCHITECTURE_DECISIONS.md#adr-0006)).

### `lifelink-audit`

Append-only. PK `RESOURCE#<type>#<id>`, SK `<timestamp>#<eventId>`. Every item carries `actorId`, `actorRole`, `action`, `resourceType`, `resourceId`, `correlationId`, `before`/`after` where meaningful, `occurredAt`.

Tamper resistance within the platform's means (§8.4): the Lambda execution role is granted `dynamodb:PutItem` only — no `UpdateItem`, no `DeleteItem` — so the application physically cannot alter or remove an audit record. PITR is on and a customer-managed KMS key is used. This is *resistance*, not immutability, and is described that way in the documentation rather than overclaimed.

### `lifelink-idempotency` and `lifelink-outbox`

Both carry a TTL attribute (`expiresAt`). Outbox rows are deleted 7 days after dispatch; undispatched rows never expire and are alarmed on. Idempotency rows expire after 24 h.

---

## 3. Concurrency and consistency

| Invariant | Mechanism | Required by |
|---|---|---|
| Stock never negative | `ConditionExpression: availableUnits >= :n` | §3.3 |
| No lost inventory update | Version check on every write ([ADR-0002](ARCHITECTURE_DECISIONS.md#adr-0002)) | §12.1 |
| No duplicate registration | Conditional put on `SK=REG#<uid>` | §5.3, §12.3 |
| Camp never oversubscribed | `TransactWriteItems`: put registration (condition: not exists) **+** update camp (condition: `registeredCount < capacity`). Both succeed or neither does | §12.3 concurrent final seat |
| Donation credited exactly once | `TransactWriteItems`: donation record (condition: not exists) **+** ledger entry **+** counter increment | §5.6, §19 "credited exactly once" |
| Donor cannot self-verify | Service asserts `verifierId != donorId` **and** verifier holds `CAMP_STAFF`/`CAMP_ORGANIZER` for that camp | §5.3 |
| No duplicate event processing | Idempotency table keyed on `eventId` ([ADR-0009](ARCHITECTURE_DECISIONS.md#adr-0009)) | §10.4 |
| Event never lost on crash | Transactional outbox ([ADR-0005](ARCHITECTURE_DECISIONS.md#adr-0005)) | §12.1 |
| Stale update cannot overwrite newer | Reject if incoming `sourceTimestamp < stored lastUpdatedAt` | §3.6 |
| No double-counted stock | A reservation pool counter updated inside a conditional `TransactWriteItems`, so two callers racing for the last units cannot both win ([ADR-0018](ARCHITECTURE_DECISIONS.md#adr-0018)) | §6.7 |
| An offer is not a claim on units | A provider's `ACCEPTED` on an **emergency** request records willingness and still writes no counter ([ADR-0017](ARCHITECTURE_DECISIONS.md#adr-0017)) | §6.7 |

Reads are eventually consistent by default. Strongly consistent reads are used only where a read-after-write decision follows immediately: re-reading a batch after a failed conditional write, and revalidating stock before a provider confirmation. GSIs are *always* eventually consistent — so the dispatcher tolerates seeing a request it has already picked up, which the idempotency layer absorbs.

---

## 4. Pagination, retention and recovery

**Pagination** — cursor-based throughout. The opaque `nextCursor` is a base64url JSON of the `LastEvaluatedKey` plus a query fingerprint; a cursor presented against a different query is rejected rather than silently misinterpreted. Default page 20, maximum 100. Offset pagination is not offered — DynamoDB cannot do it efficiently and faking it would mean a scan.

**Retention** — audit 7 years (regulatory posture, documented as an assumption pending legal review); donation records indefinite while the account lives; alerts via TTL at `expiresAt`; precise user coordinates never stored, only the derived geohash at the precision needed (§4.2 data minimisation).

**Backup and recovery** — PITR on all domain tables (35-day window); on-demand backup before any schema-affecting deployment; restore procedure documented and *tested* in Phase 10, because §9.5 forbids claiming an untested DR capability. Cross-Region replication is **not available** on this account and is documented as a regional limitation, not an omission.

---

## 5. What this design does not do

Stated here so no reader infers capability that is absent:

- **No allocation or clinical-release model.** A reservation holds units for a bounded
  time; it is not a cross-match, not clinical approval and not a guarantee of release.
  Those remain decisions for qualified staff outside this system. Temporary
  reservations themselves **are** modelled — see
  [ADR-0018](ARCHITECTURE_DECISIONS.md#adr-0018) and `lifelink-reservations` above.
  This line previously read "no reservation or allocation model", which was true
  when written and is no longer.
- **No cross-Region replication.** Blocked by the account's single-Region constraint.
- **No DAX / caching tier.** DAX is unsupported on this plan; in-process caching only.
- **No analytics store.** Dashboard aggregates are computed per request; at real scale this would need a read model, which is noted as future work.
- **No real institutional data path.** Only verified onboarding or authorized staff updates may introduce real data (§11.3); the seeded dataset is synthetic and labelled.
