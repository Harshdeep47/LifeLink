# Architecture Decisions

LifeLink records its design decisions as **ADRs** — Architecture Decision
Records. Each one states the context, the decision, and the consequences. The
full text is in `docs/ARCHITECTURE_DECISIONS.md`; this document summarises all
nineteen and explains the five that matter most in a viva.

**What an ADR is, and why it impresses.** An ADR is a short document written
*at the time* a decision is made, recording why. It matters because six months
later nobody remembers whether something was a careful trade-off or an
accident — and a teacher asking "why did you do it this way?" is really asking
whether you knew you had a choice.

---

## 1. All nineteen decisions

| ADR | Decision | Status |
|---|---|---|
| 0001 | Domain-aligned DynamoDB tables rather than one single table | Accepted |
| 0002 | Batch-level inventory with optimistic concurrency | Accepted |
| 0003 | Separate `lastUpdatedAt` from `lastVerifiedAt` | Accepted |
| 0004 | Geohash prefix pre-filter, then exact Haversine | Accepted |
| 0005 | Transactional outbox for all cross-domain events | Accepted |
| 0006 | Application-level priority dispatcher, not three SQS queues | Accepted |
| 0007 | Authorization in a shared decorator, never in handlers | Accepted |
| 0008 | Compatibility rules as versioned data, not code | Accepted |
| 0009 | Idempotency via a dedicated table with conditional put | Accepted |
| 0010 | Hexagonal layering: handlers -> services -> repositories -> adapters | Accepted |
| 0011 | Local development without Docker | Accepted |
| 0012 | Amazon Location Service as tile source; MapLibre renders only | **Partly superseded by 0019** |
| 0013 | Python 3.14 on Lambda, matching the local interpreter | Accepted |
| 0014 | Design for a Lambda concurrency ceiling of 10 | Accepted |
| 0015 | Email and in-app notifications only; SMS not implemented | Accepted |
| 0016 | All timestamps stored as UTC ISO-8601; display in IST | Accepted |
| 0017 | Availability alerts are informational, never reservations | **Partly superseded by 0018** |
| 0018 | Temporary reservations are the ordinary request workflow; no second request entity | Accepted |
| 0019 | OpenStreetMap raster tiles in the browser, because the account's SCP denies a Location API key | Accepted |

**Note the two superseded entries.** Decisions that were later revised are
marked, not deleted. That is the correct practice: the record of what you
believed and why you changed your mind is the valuable part.

---

## 2. The five that matter most

### ADR-0014 — Design for a Lambda concurrency ceiling of 10

**Context.** The default AWS account concurrency limit is 1000. This account's
limit is **10**, verified live (`ConcurrentExecutions: 10`).

**Decision.** Treat 10 as a hard design constraint rather than something to
request an increase for.

**Consequences, all visible in the deployed configuration:**

| Mechanism | Deployed value | Why |
|---|---|---|
| API stage throttle | 10 req/s, burst 20 | shed load at the gateway, not by exhausting Lambda |
| SQS event source mapping `MaximumConcurrency` | **2** on both queues | consumers cannot starve the API function |
| Lambda timeout | 29 s | fails before API Gateway's 30 s integration timeout, so the error is ours |
| One API function, not 58 | — | 58 functions competing for 10 slots would be worse |
| Deferred work to queues | — | keeps request-path concurrency short-lived |

**This is the single best architectural story in the project**, because the
constraint is unusual, the response is coherent, and every part of it is
visible in the live configuration.

### ADR-0018 — Temporary reservations *are* the ordinary request workflow

**Context.** The system needs a way for a hospital to say "I want these units".
The obvious design is a `BloodRequest` entity. Emergency coordination already
exists as a separate workflow.

**Decision.** There is **no second request entity**. An ordinary request *is* a
temporary reservation: a hold on specific units with a countdown, which a
blood bank accepts, rejects, or lets expire.

**Why this is better, not just simpler.** A "request" that does not hold units
is an expression of interest, and two hospitals can both be told yes for the
same units. A reservation holds the units, so the system cannot oversell. The
honesty rule is explicit: **an offer is not a reservation.**

**What to say if asked "where is your blood request feature?"**
> "Ordinary requests are implemented as temporary reservations — that's ADR-0018.
> A request that doesn't hold anything can be granted twice, so instead of a
> separate request entity we hold the units with a counter and a countdown. The
> emergency workflow is deliberately separate, because an emergency is a
> broadcast to many providers, not a hold on one."

**Do not describe a separate ordinary blood request entity. It does not exist.**

### ADR-0019 — OpenStreetMap tiles in the browser

**Context.** ADR-0012 chose Amazon Location for tiles, with browser access via
a Cognito identity pool and a tightly scoped role, so no API key would reach
the browser.

**What happened.** MapLibre cannot sign SigV4 requests itself, so Location
tiles need a credential. Creating an `AWS::Location::APIKey` was attempted and
**refused by the account's service control policy**:

```
Access denied for operation 'AWS::Location::APIKey'
```

**Decision.** Render OpenStreetMap standard raster tiles, which need no
credential. Keep geocoding and routing **server-side** through Amazon Location.

**Verified consequences:**
- The map, place index and route calculator **all exist and work** — I called
  `get-map-style-descriptor` and `search-place-index-for-text` successfully.
- `MapReaderRole` and the identity pool are **deployed but never used**.
- OSM obligations are met: attribution displayed, attribution control left on,
  zoom capped, no prefetching.

**The precise phrasing matters:** "Amazon Location is blocked" is **wrong**.
"The browser tile path is blocked because API keys are denied in this account"
is **right**.

### ADR-0007 — Authorization in a shared decorator, never in handlers

**Decision.** `@requires(...)` is the only place authorization happens, with
five checks in a fixed order.

**Consequence that makes it checkable.** Every route declares its permission in
the route table, and a test enumerates the table and fails the build if any
route lacks authorization metadata. That turns "we didn't forget any endpoint"
from a claim into a property.

**The trade-off to acknowledge:** a central decorator cannot express
record-level rules that depend on the record's contents. Those live in the
services, so authorization is *mostly* but not *entirely* in one place.
Organization scoping is the general case that was lifted into the decorator
because it is the IDOR defence.

### ADR-0005 — Transactional outbox for all cross-domain events

**Context.** Writing a record and then publishing an event has two failure
modes: the write commits and the publish fails (lost event), or the publish
succeeds and the write rolls back (event for something that never happened).

**Decision.** Write the record and its outbound event in **one**
`TransactWriteItems` into the `outbox` table. A DynamoDB Stream on that table
drives the publisher.

**Consequences.** Events are at-least-once, so consumers must be idempotent —
which is why the `idempotency` table exists (ADR-0009). The publisher has 3
retries, bisects a failing batch, reports partial batch failures, and sends
unprocessable records to the work DLQ.

---

## 3. Decisions about things that were *not* used

| What | ADR / reason |
|---|---|
| **Step Functions** | Not used, and no ADR rejects it by name. The evidence is the template: zero occurrences. ADR-0006 is the closest relevant decision — it chose an application-level priority dispatcher over multiple SQS queues. **Do not claim an ADR rejects Step Functions; cite the template instead.** |
| Three SQS priority queues | ADR-0006 — one application-level dispatcher reads ranked candidates instead |
| Single-table DynamoDB design | ADR-0001 — domain-aligned tables are easier to reason about and to scope IAM per table |
| Docker for local development | ADR-0011 |
| FastAPI / Mangum | A route table is all a proxy integration needs; the same table drives local and deployed |
| SMS notifications | ADR-0015, and blocked by the SCP |
| OpenRouteService as a second routing provider | ADR-0012 — a second provider that cannot be verified end to end adds risk without benefit |

> **A correction worth repeating.** Earlier in this project's history, ADR-0006
> was mistakenly cited as rejecting Step Functions. It does not mention them.
> The honest evidence that Step Functions is unused is the infrastructure
> template itself. If you are asked, say: "We don't use Step Functions — you
> can check the template, there are none. Scheduling is EventBridge Scheduler."

---

## 4. Spoken answers

### 20–30 seconds

> "We kept nineteen architecture decision records. The most important is
> ADR-0014: our account's Lambda concurrency limit is ten instead of the usual
> thousand, so we designed around it — the API throttles at ten requests a
> second, each queue consumer is capped at two concurrent executions, and the
> Lambda timeout is twenty-nine seconds so it fails before API Gateway does.
> The second most important is ADR-0018: ordinary blood requests *are*
> temporary reservations, because a request that doesn't hold units can be
> granted to two hospitals at once."

### 1–2 minutes

> "ADRs are short records written when a decision is made, saying what the
> context was, what we chose, and what it costs. Two of ours are marked
> superseded rather than deleted, which I think is the point of the practice —
> the record of changing your mind is the useful part.
>
> ADR-0012 is the clearest example. We planned to use Amazon Location for map
> tiles, with the browser getting credentials from a Cognito identity pool so
> no API key would be exposed. Then we found that MapLibre can't sign AWS
> requests itself, and creating a Location API key is denied by our account's
> service control policy. So ADR-0019 superseded the browser half: the basemap
> is now OpenStreetMap raster tiles, which need no credential, while geocoding
> and routing still go through Amazon Location server-side. The identity pool
> role is still deployed but unused — leftover from the superseded decision.
>
> I'd rather show that history than pretend we planned OpenStreetMap from the
> start, because the constraint we hit is real and the response to it was
> reasonable."

---

## 5. Follow-up questions

**"Did you write these before or after you built it?"**
> Mostly at the time of the decision, which is why two are marked superseded —
> we wrote 0012 believing Amazon Location tiles would work, hit the SCP, and
> wrote 0019 rather than quietly editing 0012. The ones that read as
> retrospective are the ones where reality forced a change.

**"ADR-0001 rejects single-table design, but single-table is the DynamoDB best
practice. Were you wrong?"**
> It is *a* best practice, for a specific reason: it minimises round trips by
> co-locating related items. Our access patterns are mostly within one domain
> at a time, so the round-trip saving is small, and two things pushed the other
> way — a domain-aligned table lets us scope each IAM policy to exactly one
> table, which is how we got genuinely least-privilege roles, and it is far
> easier for a small team to reason about. The honest cost is that
> cross-domain reads are explicit application-level joins. At much larger
> scale, or with heavily cross-domain access, single-table would win.

**"Why is a concurrency limit of 10 an architecture decision rather than a
support ticket?"**
> Because on a FREE-plan account it is not negotiable, and designing for the
> limit you actually have is more honest than designing for one you hope to
> get. It also produced a better system: shedding load at the gateway and
> capping queue consumers are things you *should* do anyway, and the limit
> forced us to be explicit about them.

---

## 6. Cross-references

- Full ADR text: `docs/ARCHITECTURE_DECISIONS.md`
- Concurrency in practice: [../04_AWS_COMPLETE_GUIDE/05_AWS_Lambda.md](../04_AWS_COMPLETE_GUIDE/05_AWS_Lambda.md)
- Reservations: [../06_FEATURE_IMPLEMENTATION/05_Temporary_Reservations.md](../06_FEATURE_IMPLEMENTATION/05_Temporary_Reservations.md)
- Maps: [../07_MAPS_AND_INTEGRATIONS/02_Map_Rendering_And_Tiles.md](../07_MAPS_AND_INTEGRATIONS/02_Map_Rendering_And_Tiles.md)
- Authorization: [../08_SECURITY_AND_RELIABILITY/02_IAM_Authorization_Flow.md](../08_SECURITY_AND_RELIABILITY/02_IAM_Authorization_Flow.md)
