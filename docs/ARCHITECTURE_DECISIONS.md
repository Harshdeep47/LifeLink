# LifeLink — Architecture Decision Records

Each ADR records a decision, the forces behind it, the alternatives rejected, and the consequences accepted. ADRs are immutable once accepted; a reversal is a new ADR that supersedes an old one.

**Status values:** Proposed · Accepted · Superseded · Rejected

| ADR | Title | Status |
|---|---|---|
| [0001](#adr-0001) | Domain-aligned DynamoDB tables rather than one single table | Accepted |
| [0002](#adr-0002) | Batch-level inventory with optimistic concurrency | Accepted |
| [0003](#adr-0003) | Separate `lastUpdatedAt` from `lastVerifiedAt` | Accepted |
| [0004](#adr-0004) | Geohash prefix pre-filter, then exact Haversine | Accepted |
| [0005](#adr-0005) | Transactional outbox for all cross-domain events | Accepted |
| [0006](#adr-0006) | Application-level priority dispatcher, not three SQS queues | Accepted |
| [0007](#adr-0007) | Authorization in a shared decorator, never in handlers | Accepted |
| [0008](#adr-0008) | Compatibility rules as versioned data, not code | Accepted |
| [0009](#adr-0009) | Idempotency via a dedicated table with conditional put | Accepted |
| [0010](#adr-0010) | Hexagonal layering: handlers → services → repositories → adapters | Accepted |
| [0011](#adr-0011) | Local development without Docker | Accepted |
| [0012](#adr-0012) | Amazon Location Service as tile source; MapLibre renders only | **Partly superseded by [0019](#adr-0019)** |
| [0013](#adr-0013) | Python 3.14 on Lambda, matching the local interpreter | Accepted |
| [0014](#adr-0014) | Design for a Lambda concurrency ceiling of 10 | Accepted |
| [0015](#adr-0015) | Email and in-app notifications only; SMS not implemented | Accepted |
| [0016](#adr-0016) | All timestamps stored as UTC ISO-8601; display in IST | Accepted |
| [0017](#adr-0017) | Availability alerts are informational, never reservations | **Partly superseded by [0018](#adr-0018)** |
| [0018](#adr-0018) | Temporary reservations are the ordinary request workflow; no second request entity | Accepted |
| [0019](#adr-0019) | OpenStreetMap raster tiles in the browser, because the account's SCP denies a Location API key | Accepted |

---

## ADR-0001 — Domain-aligned DynamoDB tables rather than one single table
<a name="adr-0001"></a>
**Status:** Accepted

### Context
DynamoDB guidance often favours single-table design: one table, overloaded keys, every entity sharing a keyspace, GSIs reused across entity types. It minimises round trips and is the "advanced" answer in interviews.

Against that, spec §10.1 requires strict domain ownership — Feature 1 owns inventory, Feature 3 owns camps, Feature 4 owns emergency requests — and says "do not duplicate business ownership across services". Spec §2.3 requires design around actual queries, explicitly not a relational schema translated blindly.

### Decision
Use **one table per bounded context**, each internally using composite keys and entity-type-overloaded sort keys where that serves real queries:

`lifelink-organizations` · `lifelink-facilities` · `lifelink-inventory` · `lifelink-alerts` · `lifelink-camps` · `lifelink-donations` · `lifelink-emergency` · `lifelink-notifications` · `lifelink-audit` · `lifelink-idempotency` · `lifelink-outbox`

Within a table, single-table techniques still apply: a camp and its registrations share a partition so they can be read together.

### Alternatives considered
- **One table for everything.** Rejected: it makes domain ownership a convention rather than a boundary. Any Lambda with table access can read any domain's data, so §10.1 and the least-privilege requirement of §8.2 become unenforceable at the IAM layer. It also makes per-domain capacity, TTL and backup policy impossible to tune separately.
- **One table per entity (relational style).** Rejected by §2.3 — it produces N round trips for naturally co-located reads like camp + registrations.

### Consequences
- **Positive:** IAM policies grant a function access to its own domain's table only, so organization isolation is enforced by the platform, not by code review. Per-table TTL (alerts expire, audit does not). Clearer teaching narrative for Book 1.
- **Negative:** Cross-domain reads need two calls — e.g. ranking facilities by availability reads `lifelink-facilities` then `lifelink-inventory`. Accepted: those are the integration points the spec wants explicit anyway.
- **Negative:** More tables to provision. Mitigated by SAM template loops; the 2,500-table quota is irrelevant at this scale.

---

## ADR-0002 — Batch-level inventory with optimistic concurrency
<a name="adr-0002"></a>
**Status:** Accepted

### Context
§3.3 forbids inventory as a single aggregate number and requires batches with expiry, quarantine and audit history. §3.3 also requires that available quantity can never go negative, and §12.1 requires concurrent-update safety.

### Decision
Each batch is one item in `lifelink-inventory` carrying a `version` integer. Every mutation is a `UpdateItem` with `ConditionExpression`:

```
attribute_exists(PK)
  AND #version = :expectedVersion
  AND availableUnits >= :deductUnits     -- deductions only
```

and `SET #version = :expectedVersion + 1`. A `ConditionalCheckFailedException` is surfaced as HTTP 409 with a machine-readable code; the caller re-reads and retries. Aggregate per-facility counts are **derived at read time** from eligible batches, never stored as an authoritative field (§3.4 forbids depending on a manually maintained aggregate).

### Alternatives considered
- **`ADD availableUnits :delta` atomic counter.** Rejected: atomic counters cannot express "never below zero" and lose the pre-image needed for the audit trail.
- **Pessimistic locking.** Rejected: DynamoDB has no lock primitive; emulating one adds a failure mode worse than the problem.
- **DynamoDB transactions for every write.** Rejected as the default: 2× cost and unnecessary for a single-item update. Reserved for genuinely multi-item invariants (ADR-0017).

### Consequences
- Lost updates are impossible; a concurrent deduction fails loudly rather than silently overwriting.
- Callers must handle 409. The API client implements bounded retry with jitter.
- Read-time aggregation costs a query per facility. Bounded by `Limit` and the eligibility filter; measured in Phase 10.

---

## ADR-0003 — Separate `lastUpdatedAt` from `lastVerifiedAt`
<a name="adr-0003"></a>
**Status:** Accepted

### Context
§3.5 is emphatic: an update is not a verification, and a recent automated API update must never imply independent human verification. This is the spec's central data-integrity claim — a blood bank's automated feed saying "12 units" is not the same as a person having confirmed it.

### Decision
Two independent, separately-written fields on every batch and facility: `lastUpdatedAt` (any write, including API ingestion) and `lastVerifiedAt` (set only by an authenticated human with a verification-capable role, via a distinct endpoint). Freshness labels derive **only** from `lastUpdatedAt`:

| Age of `lastUpdatedAt` | Label |
|---|---|
| 0–6 h | `FRESH` |
| >6–24 h | `AGING` |
| >24–48 h | `STALE` |
| >48 h | `OUTDATED` |

Verification state is a separate enum (`UNVERIFIED` / `VERIFIED` / `VERIFICATION_EXPIRED`) rendered as a distinct UI element. No code path writes both fields in one operation.

### Consequences
- The API returns both; the UI must show both. Surfacing "updated 5 minutes ago" next to "never independently verified" is the honest presentation the spec demands.
- Ranking (§4.4) weights them separately: freshness 20%, verification 15%.
- A unit test asserts no service method writes `lastVerifiedAt` outside the verification path.

---

## ADR-0004 — Geohash prefix pre-filter, then exact Haversine
<a name="adr-0004"></a>
**Status:** Accepted

### Context
§4.3 requires geospatial pre-filtering by geohash or bounding box followed by exact distance, and forbids unbounded scans for nearby discovery.

### Decision
Every facility and camp stores `geohash` (precision 9) plus `geohash5`, `geohash6`, `geohash7` as separate attributes. A GSI is keyed on the precision matching the search radius:

| Radius | Geohash precision | Cell size (approx) |
|---|---|---|
| ≤ 5 km | 6 | 1.2 km × 0.6 km |
| ≤ 20 km | 5 | 4.9 km × 4.9 km |
| ≤ 100 km | 4 | 39 km × 20 km |

Query the centre cell **and its eight neighbours** (critical: a facility 500 m away can sit in an adjacent cell), union the results, then compute exact Haversine distance and filter to the true radius. Distance from Haversine is labelled `straightLineKm` and is never presented as road distance (§4.5).

### Alternatives considered
- **Scan + filter.** Explicitly forbidden by §4.3.
- **Single geohash cell, no neighbours.** Rejected — the classic correctness bug; boundary facilities disappear. §12.2 lists "facility at radius boundary" as a required edge case, and there is a test for exactly this.
- **Amazon Location geofencing.** Rejected: designed for device tracking, not catalogue search, and adds cost without benefit.

### Consequences
- 9 parallel GSI queries per search. Each is small and bounded; they run concurrently in one Lambda.
- Precision changes with radius, so the GSI chosen varies per request — encapsulated in the repository layer.
- Very large radii (§12.2 "excessively large search radius") are capped at 100 km with a clear API error.

---

## ADR-0005 — Transactional outbox for all cross-domain events
<a name="adr-0005"></a>
**Status:** Accepted

### Context
§10.4 requires durable event creation, an outbox pattern where needed, idempotent consumers and replay. The hazard: writing to DynamoDB and then publishing to SQS is not atomic — a crash between the two silently loses the event (§12.1 "Lambda crash", "outbox write failure").

### Decision
Domain writes that must produce an event use `TransactWriteItems` to write **the domain item and an outbox item in one transaction**. A DynamoDB Stream on `lifelink-outbox` triggers a publisher Lambda that pushes to SQS and marks the outbox row dispatched. Consumers are idempotent (ADR-0009).

Every event carries: `eventId` (UUID), `eventType`, `eventVersion`, `occurredAt`, `correlationId`, `causationId`, `payload`.

### Alternatives considered
- **Write then publish.** Rejected: loses events on crash — the exact failure §12.1 requires us to handle.
- **DynamoDB Streams directly on domain tables.** Rejected: couples the event contract to the storage schema, so any attribute rename becomes a breaking event change. The outbox lets the event shape be designed deliberately and versioned (`eventVersion`).
- **EventBridge instead of SQS.** Deferred — SQS gives per-consumer DLQs and visibility-timeout retry semantics that match §10.4 more directly. Revisit if fan-out grows.

### Consequences
- At-least-once delivery, never zero. Duplicates are expected and handled — §10.4 forbids relying on exactly-once.
- Transactions cost 2× writes on event-producing paths. Accepted for correctness.
- The outbox table needs a reconciliation job for rows stuck undispatched; it is a documented runbook and an alarm.

---

## ADR-0006 — Application-level priority dispatcher, not three SQS queues
<a name="adr-0006"></a>
**Status:** Accepted

### Context
§6.6 warns directly: "Do not assume that creating three SQS queues automatically guarantees priority ordering", and requires a documented fairness mechanism preventing P3 starvation. ADR-0014's concurrency ceiling of 10 sharpens this — there is no spare capacity for per-priority reserved concurrency.

### Decision
One work queue plus a **dispatcher** Lambda on a 1-minute EventBridge schedule. The dispatcher queries `lifelink-emergency` by a GSI on `(status, effectivePriority)` and selects a batch using weighted fair queueing:

- Nominal share: P1 60%, P2 30%, P3 10%.
- **Priority aging:** `effectivePriority` rises one band for every 15 minutes a request waits beyond its target. This changes *scheduling order only* — the hospital-certified `clinicalPriority` field is immutable by this mechanism, satisfying §6.6's "fairness mechanisms must never change clinical priority".
- Deadline awareness: a request whose `requiredBy` is within 30 minutes jumps the batch regardless of band.

Two distinct fields: `clinicalPriority` (P1/P2/P3, hospital-certified, audit-logged, never machine-modified) and `effectivePriority` (scheduling only, derived, recomputed freely).

### Consequences
- P3 starvation is impossible by construction, and there is a test that asserts a P3 request waiting 60 minutes is dispatched ahead of a fresh P2.
- Up-to-60-second scheduling latency from the cron tick. Acceptable for a coordination system; documented. A P1 request also triggers an immediate out-of-band dispatch so criticals do not wait for the tick.
- The dispatcher is a single point of failure; it is idempotent and its failure raises an alarm.

---

## ADR-0007 — Authorization in a shared decorator, never in handlers
<a name="adr-0007"></a>
**Status:** Accepted

### Context
§8.1–§8.2 require that backend authorization be authoritative, that a valid JWT from a suspended account be rejected, and that cross-organization access and IDOR be prevented. Authorization scattered across handlers is how one forgotten check becomes a breach.

### Decision
A single `@requires(...)` decorator wraps every handler and performs, in order:

1. Verify the JWT signature against the Cognito JWKS (cached, with the `kid` checked).
2. Validate `iss`, `aud`, `token_use`, `exp`.
3. **Load the user from DynamoDB and check `accountStatus == ACTIVE`** — a valid token from a suspended user is rejected here. Roles come from the database record, not from token claims, so a role revoked mid-session takes effect on the next request (§12.5).
4. Check the required role or permission.
5. Resolve the target resource's `organizationId` and compare it to the caller's — this is the IDOR defence, applied centrally rather than per-handler.
6. Bind `correlationId`, `actorId` and `organizationId` into a request context available to the service layer.

Handlers receive an already-authorized context and contain no authorization logic.

### Alternatives considered
- **API Gateway Cognito authorizer alone.** Rejected: it validates the token but knows nothing about suspension, DB-held roles, or resource ownership. Used as an outer layer, never the only one.
- **Per-handler checks.** Rejected: unauditable, and one omission is a vulnerability.

### Consequences
- One DynamoDB read per request for the user record. Mitigated by a short in-process cache keyed on `sub` with a 30-second TTL — bounded staleness, documented.
- A test enumerates every route and asserts each is decorated; an undecorated route fails the build.

---

## ADR-0008 — Compatibility rules as versioned data, not code
<a name="adr-0008"></a>
**Status:** Accepted

### Context
§6.5 requires compatibility rules from a documented, medically reviewed reference, kept versioned and testable, and forbids the matching engine inventing compatibility. Phase 0 risk R-13 records that **no medically reviewed reference has been supplied for this project.**

### Decision
Compatibility lives in `backend/src/reference/compatibility/abo_rh_v1.json`, carrying `version`, `sourceCitation`, `reviewStatus` and `reviewedBy`. For this build, `reviewStatus` is **`UNREVIEWED_SYNTHETIC`** and `reviewedBy` is null. The loader refuses to start if `reviewStatus` is absent. Every API response derived from these rules carries a `compatibilityRulesVersion` and a disclaimer field.

The engine performs table lookup only — no inference, no similarity scoring, no fallback guess. An unknown combination returns `UNKNOWN`, never a default.

### Consequences
- Honest: the system never claims clinical validity it does not have. §1.5 forbids exactly that claim.
- Swapping in a reviewed reference is a data change plus a version bump, not a code change.
- A test asserts that a lookup miss returns `UNKNOWN` and never `COMPATIBLE`.

---

## ADR-0009 — Idempotency via a dedicated table with conditional put
<a name="adr-0009"></a>
**Status:** Accepted

### Context
§3.6, §6.2 and §10.4 require idempotency and duplicate-event detection; §12.x lists duplicate submissions and duplicate SQS delivery as required edge cases. At-least-once delivery (ADR-0005) makes duplicates routine, not exceptional.

### Decision
`lifelink-idempotency`: PK `idempotencyKey`, attributes `status` (`IN_PROGRESS`/`COMPLETED`), `responseHash`, `resultRef`, `expiresAt` (TTL, 24 h).

Flow: conditional `PutItem` with `attribute_not_exists(idempotencyKey)`.
- Succeeds → first execution; proceed, then mark `COMPLETED` with the stored result.
- Fails and existing row is `COMPLETED` → return the stored result, do not re-execute.
- Fails and existing row is `IN_PROGRESS` → return 409 `REQUEST_IN_PROGRESS`.

Keys: client-supplied `Idempotency-Key` header for mutating REST calls; for queue consumers, the `eventId` from the envelope.

### Consequences
- Duplicate work is impossible for any path that opts in; opting in is mandatory for all mutating endpoints and all consumers.
- TTL keeps the table small and costs nothing to maintain.
- A crashed in-flight request leaves `IN_PROGRESS` until TTL. Mitigated by a short stale-claim window (5 min) after which the claim may be retaken, with the behaviour documented and tested.

---

## ADR-0010 — Hexagonal layering: handlers → services → repositories → adapters
<a name="adr-0010"></a>
**Status:** Accepted

### Context
§2.2 requires clear separation between API handlers, business logic, persistence, integrations and background jobs, and forbids business logic living in the frontend. §13.1 requires unit-testable domain logic.

### Decision
Four layers, dependencies pointing inward only:

```
handlers/     Lambda entry points. Parse, validate shape, call a service, format the response.
              No business rules. No boto3.
services/     Business logic. Pure where possible. Depends on repository *interfaces*.
repositories/ Persistence. The only place DynamoDB types appear.
adapters/     External integrations (Location Service, SES, SQS) behind interfaces (§2.7).
```

Domain logic — expiry, freshness, eligibility, ranking, compatibility, impact scoring — is written as pure functions taking explicit values (including "now") and returning values. They are unit-tested with no AWS, no mocks, no clock patching.

### Consequences
- The §13.1 unit-test list maps one-to-one onto pure functions, so those tests are fast and deterministic.
- Swapping Amazon Location for another provider touches one adapter (§2.7 requires provider abstraction).
- More files and explicit wiring than a flat handler layout. Accepted: it is what makes Book 2's chapter structure coherent.

---

## ADR-0011 — Local development without Docker
<a name="adr-0011"></a>
**Status:** Accepted

### Context
§14 requires basic functionality demonstrable without deploying to AWS. Phase 0 found Docker absent but Java 26 present.

### Decision
- **DynamoDB Local** from the official Java JAR (`java -Djava.library.path=... -jar DynamoDBLocal.jar -sharedDb -port 8000`), started by a Python script.
- **Unit tests** use `moto` — no network, no emulator.
- **Integration tests** run against DynamoDB Local.
- **Cognito** has no local emulator; a `LocalAuthAdapter` issues RS256-signed JWTs from a locally generated dev keypair with the same claim shape as Cognito. The verification path is the same code in both modes, switched only by JWKS source. §14 warns against a mock that behaves differently from the real architecture — the token *issuer* differs; the *verifier* does not.
- **SES/SNS/SQS** locally write to a `.local-outbox/` directory and log; the adapter interface is identical to the AWS one.

### Consequences
- No Docker dependency; `python scripts/dev.py db-start` plus
  `create-tables` is the whole local datastore.
- Local auth is a genuine divergence and is documented prominently in `LOCAL_DEVELOPMENT.md` and `KNOWN_LIMITATIONS.md`. It is never presented as testing Cognito itself.

---

## ADR-0012 — Amazon Location Service as tile source; MapLibre renders only
<a name="adr-0012"></a>
**Status:** **Partly superseded by [ADR-0019](#adr-0019).** The server-side
half stands: geocoding and routing still go through the backend via Amazon
Location, and no provider credential reaches the browser. The *browser tile*
half did not survive contact with the account — `AWS::Location::APIKey` is
denied by the service control policy — so the deployed frontend renders
OpenStreetMap raster tiles. The body below is left as written; see ADR-0019
for what replaced it and why.

### Context
§2.7 states plainly that MapLibre is a renderer and does not supply tiles, geocoding or routing, and forbids treating public OSM tile servers as an unrestricted production service.

### Decision
Amazon Location Service supplies maps (tiles), places (geocoding/search) and routes (road distance + ETA) — all three confirmed available in `ap-southeast-2` during Phase 0. MapLibre GL JS renders only. Browser access to tiles uses a Cognito **identity pool** with a tightly scoped role, so no API key reaches the browser (§2.7, §7.4). Geocoding and routing go through the **backend**, keeping provider calls server-side and cacheable.

Attribution is rendered in the map UI as the provider's terms require. OpenRouteService is **not** adopted — §2.7 makes it optional, and a second provider that cannot be verified end-to-end adds risk without benefit. The `RoutingProvider` interface leaves the seam open.

### Consequences
- One provider, one bill, one failure mode. On routing failure the facility list and contact details survive (§4.5), and the UI says directions are unavailable rather than inventing a distance.
- Straight-line and road distance are distinct fields throughout the API so they can never be conflated.

---

## ADR-0013 — Python 3.14 on Lambda, matching the local interpreter
<a name="adr-0013"></a>
**Status:** Accepted

### Context
Phase 0 found local Python 3.14.2. Lambda supports `python3.14` (GA, Amazon Linux 2023, deprecation 2029-06-30). Python 3.15 exists but is **public preview** — explicitly not for production and outside the Lambda SLA.

### Decision
`python3.14` everywhere: local interpreter, virtualenv, SAM `Runtime`, CI. Architecture `arm64` (Graviton) for lower cost at identical capability.

### Consequences
- Exact local/cloud parity — a dependency that imports locally imports on Lambda.
- Longest support runway of any GA Python runtime.
- Any library without 3.14 wheels must be checked at install time; the dependency set is deliberately small (boto3, pydantic, and test tooling).

---

## ADR-0014 — Design for a Lambda concurrency ceiling of 10
<a name="adr-0014"></a>
**Status:** Accepted

### Context
Phase 0 measured `ConcurrentExecutions = 10` and `UnreservedConcurrentExecutions = 10` on this account — the AWS default is 1,000. User decision on 2026-11-15: design within the limit rather than assume it will be raised.

### Decision
- **No function sets reserved concurrency.** Reserving even 1 would subtract from the shared pool of 10 and could starve the API tier.
- SQS event source mappings use small batch sizes (≤5) and `MaximumConcurrency` of 2 per consumer, leaving headroom for synchronous API traffic.
- The priority dispatcher (ADR-0006) is a single scheduled invocation rather than per-priority consumers — this limit is a second, independent reason for that design.
- Throttling is treated as an expected condition: `429`/`ThrottlingException` is retried with jitter by consumers, and a CloudWatch alarm on `Throttles` is defined.
- Scaling chapters in Book 1 state this ceiling explicitly and describe what would change at 1,000.

### Consequences
- The documented architecture matches what this project can actually run — no fictional capacity claims (§1.5).
- Load testing beyond ~10 concurrent requests is not meaningful here and will be reported as NOT TESTED rather than estimated.
- Raising the quota later requires no code change, only the removal of a documented note.

---

## ADR-0015 — Email and in-app notifications only; SMS not implemented
<a name="adr-0015"></a>
**Status:** Accepted

### Context
Phase 0 confirmed `sms-voice:*` is denied by SCP `p-2cb1m8xd`, and AWS End User Messaging SMS is a Paid-Plan service unavailable on this FREE-plan project. SES is in sandbox: 200 messages/day, 1/second, verified recipients only.

### Decision
`NotificationChannel` is an interface with implementations `EmailChannel` (SES) and `InAppChannel` (DynamoDB + polling). `SmsChannel` is **not implemented** — not stubbed, not faked. Requesting SMS returns `CHANNEL_UNAVAILABLE` with a clear reason. Delivery status is recorded from the provider response; a queue write never counts as delivery (§10.3).

### Consequences
- Honest capability reporting; SMS appears as NOT IMPLEMENTED in the handover, never as working.
- Adding SMS later is one new class plus configuration.
- SES sandbox limits mean demo notifications reach only verified addresses — stated in the demo guide.

---

## ADR-0016 — All timestamps stored as UTC ISO-8601; display in IST
<a name="adr-0016"></a>
**Status:** Accepted

### Context
§3.4 requires a consistent timezone strategy for time-sensitive calculations; §12.1 lists "incorrect timezone" and §12.3 lists camp dates crossing timezone boundaries as required edge cases. The demo geography is Punjab/Chandigarh (IST, UTC+05:30, no daylight saving).

### Decision
- **Storage and transport:** UTC, ISO-8601 with explicit `Z` (`2026-11-15T09:30:00Z`). Never a naive datetime, never an epoch integer in a user-facing field.
- **Computation:** all expiry, freshness and deadline arithmetic in UTC, with "now" injected as a parameter — never `datetime.now()` inside domain logic (this is what makes ADR-0010's pure functions testable).
- **Display:** converted to `Asia/Kolkata` at the UI edge only, with the zone shown.
- A lint rule bans naive `datetime.now()` / `utcnow()` in `services/` and `domain/`.

### Consequences
- Time-dependent tests pass a fixed instant and are fully deterministic.
- IST has no DST, so the camp-scheduling edge case is simpler here than in general — documented as a scoping assumption rather than a solved general problem.

---

## ADR-0017 — Availability alerts are informational, never reservations
<a name="adr-0017"></a>
**Status:** **Partly superseded by [ADR-0018](#adr-0018).** The title still
holds exactly: an alert holds nothing, and that has never changed. But three
statements in the body below are now false — reservation *is* modelled, there
*is* a shared mutable counter, and the reservation workflow is no longer
"NOT IMPLEMENTED". The body is left unedited because an ADR records what was
decided at the time; ADR-0018 records what changed and why it does not
contradict the parts that still stand.

### Context
§3.7 states an alert "is not a reservation, allocation, clinical approval or guarantee", and §6.7 requires that provider responses not double-count stock and that multiple facilities cannot claim the same units as confirmed supply.

### Decision
- An alert match **never** writes to inventory. It reads eligible stock and notifies. No hold, no decrement, no soft lock.
- Stock is **revalidated** at every subsequent decision point — when an alert is opened, when a provider responds, and before any confirmation (§3.7, §6.7).
- Provider `ACCEPTED` records a *willingness to proceed* against the request, not a claim on units. The emergency request tracks `unitsOffered` per provider response; no path sums offers into a `unitsReserved` field, because reservation is not modelled in this system.
- Where a future reservation workflow would be needed, it is documented as NOT IMPLEMENTED rather than approximated.

### Consequences
- Double-counting is structurally impossible: there is no shared mutable counter to double-count.
- Users may act on an alert and find stock gone. That is the honest behaviour the spec mandates, and the UI says so explicitly at the point of action.
- A test asserts that two providers accepting the same request produce two independent offers and no inventory mutation.

---

## ADR-0018 — Temporary reservations are the ordinary request workflow; no second request entity
<a name="adr-0018"></a>
**Status:** Accepted · supersedes part of [ADR-0017](#adr-0017)

### Context

LifeLink needed an **ordinary** way to ask a blood bank for units: not an
emergency, not a watch-and-notify alert, just "I need two units of O-negative
at this facility". The requirement list for it was conventional — submission,
authenticated identity, group and component, quantity, facility, validation,
persistence, the requester's own history, a provider response, status tracking
and cancellation.

Three mechanisms already existed, and the distinctions between them are
load-bearing:

| Mechanism | What it does | What it holds |
|---|---|---|
| **Alert** | "Tell me if this appears nearby" | Nothing ([ADR-0017](#adr-0017)) |
| **Emergency request** | Fans out to matching providers; carries a clinical priority only a verified hospital may certify | Nothing |
| **Reservation** | Holds specific units at one facility for a bounded time | **Units, atomically** |

Read against that table, the ordinary-request requirement list *is* the
reservation lifecycle, field for field. A reservation already had submission,
an authenticated requester, group, component, units, facility, validation,
persistence, `GET /me/reservations`, a provider decision (`/decision`,
`/fulfil`), six tracked states and requester-only cancellation.

### Decision

**The ordinary request workflow is the reservation entity. No second request
entity was created.**

Specifically:

- A user asking a blood bank for units **places a reservation**. The API, the
  table, the state machine, the authorization and the audit trail are the ones
  that already existed.
- The two gaps were in the **interface**, not the model: `GET /me/reservations`
  had no caller anywhere in the frontend, and `decideReservation` /
  `fulfilReservation` had no screen. Both were closed by adding screens
  (`MyActivityPage`, `ReservationQueue`), with **no new endpoint, no new table
  and no schema change**.
- Emergency coordination stays separate, and the interface now says so: the
  navigation entry and the entry button read **"Emergency request"**, not
  "Request blood". A regression test asserts the label cannot drift back.
- Alerts stay separate and still hold nothing.

### Alternatives rejected

**A third `BloodRequest` entity with its own table, service and routes.**
Rejected on three grounds, in increasing order of weight:

1. **It would duplicate a working state machine.** Submission to provider
   decision to fulfilment to cancellation, with organization-scoped
   authorization and an audit trail, already existed and was tested. A parallel
   copy is a second place for the same invariant to be got wrong.
2. **Two kinds of claim on the same units is a correctness hazard.** The
   reservation table's pool counter is what makes overselling impossible. A
   second entity that also represented a claim would either need to share that
   counter — in which case it is a reservation under another name — or not, in
   which case the same unit can be promised twice. The reason reservations are
   atomic is precisely that nothing else may claim stock.
3. **It could not be deployed.** A new entity needs a new DynamoDB table, which
   is a new AWS resource. Creating one was outside what was permitted, so the
   honest outcome would have been an untested, undeployable, unreachable
   parallel system — strictly worse than the working one.

**Adding `requiredBy` and contact fields to a reservation.** Deferred, not
rejected. DynamoDB is schemaless for non-key attributes, so these are additive
whenever wanted. They were not added in the polishing pass because a backend
change could not be deployed, and widening the gap between repository and
running system for two optional fields was not worth it.

### Consequences

- **Accepted:** an ordinary request is always scoped to **one facility**. A
  reservation's partition key is the facility, so "preferred facility" is
  mandatory rather than optional. A user who does not care which facility uses
  search and ranking first, then reserves — which is the better journey anyway,
  because it shows them what is actually available before they commit.
- **Accepted:** an ordinary request therefore *holds units*, where a naive
  "request" might not. This is a feature rather than a side effect: it is what
  makes the answer mean anything. It is also why a hold is time-bounded, capped
  at 10 units, limited to one active hold per person per pool, and released on
  expiry — a request that sterilised supply indefinitely would be worse than no
  request at all.
- **Accepted:** the word "reservation" appears in the interface where some
  products would say "request". That is clearer, not vaguer: it tells the user
  something is being held for them and that it will expire.
- **Preserved:** every honesty rule. A reservation is explicitly **not**
  clinical approval, not a cross-match and not a guarantee of release, and the
  API returns that sentence with every reservation. `CONFIRMED` renders as
  "Accepted — units held", never "approved"; a test asserts the label contains
  none of *approv*, *cleared*, *match*, *safe* or *compatible*.
- **Preserved from ADR-0017:** an alert still holds nothing, and a provider's
  `ACCEPTED` on an **emergency** request is still a willingness to proceed
  rather than a claim on units. ADR-0018 changes neither.
- **Corrected from ADR-0017:** reservation *is* modelled, and there *is* a
  shared mutable counter. Double-counting is no longer prevented by the absence
  of a counter but by the **atomicity** of one — a conditional
  `TransactWriteItems` that re-checks the arithmetic at write time. The advisory
  domain check may tell two callers "allowed"; only one wins the transaction.
  That is a stronger guarantee than having no counter, because it permits the
  feature while keeping the invariant.
- **Still not implemented:** a facility-side screen for **emergency** provider
  responses. The reservation queue closed the reservation gap; the provider
  queue endpoint exists but has no screen.

### Where this lives

| Concern | File |
|---|---|
| Lifecycle, states, transitions, invariants (pure) | `backend/src/domain/reservations.py` |
| Orchestration, validation ordering, audit | `backend/src/services/reservation_service.py` |
| Atomic writes and the pool counter | `backend/src/repositories/reservation_repo.py` |
| Routes and permissions | `backend/src/handlers/api.py` |
| Requester's screen | `frontend/src/features/account/MyActivityPage.jsx` |
| Facility staff screen | `frontend/src/features/reservations/ReservationQueue.jsx` |
| Shared presentation logic | `frontend/src/features/reservations/reservationView.js` |

Access patterns: [DATABASE_DESIGN](DATABASE_DESIGN.md), AP-40 to AP-45.

---

## ADR-0019 — OpenStreetMap raster tiles in the browser, because the account SCP denies a Location API key
<a name="adr-0019"></a>
**Status:** Accepted · supersedes the browser-tile half of [ADR-0012](#adr-0012)

### Context

[ADR-0012](#adr-0012) decided that Amazon Location Service would supply map
tiles and that the browser would reach them through a Cognito **identity pool**
with a tightly scoped IAM role, so no API key reached the client. That
reasoning was sound and the resources were deployed: `lifelink-dev-map`, the
identity pool, and `MapReaderRole` granting four `geo:` tile actions and
nothing else.

It then failed for a reason no amount of design could fix: **`AWS::Location::APIKey`
is denied by the service control policy** on this account. That policy is
managed by AWS for this account type and is not ours to change.

### Decision

The browser renders **OpenStreetMap raster tiles**. The Amazon Location
identity-pool path stays deployed and documented, but unused by the shipped
frontend.

- The SCP denial was **not** retried or worked around. Attempting to bypass an
  account-level control is out of scope and would be the wrong instinct.
- OSM attribution is rendered in the map UI, as the OSM tile usage policy
  requires, and no tile prefetching is performed.
- **The server-side half of ADR-0012 is untouched.** Geocoding and routing
  still run through the backend against Amazon Location, so no provider
  credential reaches the browser and the original security property survives.

### Consequences

- **Accepted:** the basemap is a demonstration tile source, not a production
  one. The OSM policy does not permit heavy or commercial use, and this is
  recorded in [KNOWN_LIMITATIONS](KNOWN_LIMITATIONS.md). A production
  deployment would need either a Location API key, which requires the SCP to
  permit one, or a commercial tile provider.
- **Accepted:** a documentation hazard, which is the main reason this ADR is
  explicit. The identity pool, the role and the map resource all exist in the
  console and *look* like the live tile path. They are not. Anyone
  demonstrating IAM from the console must say that the browser currently takes
  the OSM route — [CLOUD_DEMONSTRATION_GUIDE](CLOUD_DEMONSTRATION_GUIDE.md) §5
  flags exactly this.
- **Retained:** `MapReaderRole` remains the clearest worked example in the
  project of Cognito and IAM doing their separate jobs — a user-pool JWT
  exchanged through an identity pool for temporary AWS credentials, scoped by a
  trust-policy condition. It is worth keeping and explaining for that reason
  alone, provided nobody claims the map on screen is served through it.
- **Cost:** no change. The Location resources cost nothing while they are not
  called.
