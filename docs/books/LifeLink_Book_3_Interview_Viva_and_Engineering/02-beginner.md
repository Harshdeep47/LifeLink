<!-- pagebreak -->

# 6. Beginner Questions: The Problem and the Shape

Thirty beginner questions across Chapters 6 to 10. These establish that you
understand what you built before anyone probes how.

**B1. What problem does LifeLink solve?**

Finding blood is a coordination problem rather than a supply problem. Stock
often exists nearby and nobody knows. LifeLink lets facilities publish stock,
lets people search it with an honest indication of how trustworthy each figure
is, and coordinates emergency requests between hospitals and blood banks.

**B2. Who are the users?**

Public visitors who search; donors who create alerts, attend camps and build a
verified donation history; blood bank staff and admins who maintain inventory;
hospital staff who raise emergency requests and authorizers who certify their
clinical priority; camp organizers and camp staff; and platform administrators
who verify organizations and read the audit trail.

**B3. What are the seven features?**

Inventory management; location services and discovery; donation camps and donor
engagement; emergency coordination; frontend architecture; security,
authentication and monitoring; and cloud infrastructure. The last three are
platform features, not documentation.

**B4. Why is "availability alerts" not an eighth feature?**

Because it owns no data of its own. An alert is a standing question about
inventory, and answering it needs the same eligibility and freshness rules. A
separate feature would need a second copy of those rules, and two copies of an
eligibility rule is one too many.

**B5. What are the eight blood groups?**

A+, A−, B+, B−, AB+, AB−, O+ and O−. The system tracks all eight.

**B6. What are the four components?**

Whole blood, packed red blood cells, fresh frozen plasma and platelets. Group
and component are tracked independently, because not every facility stocks
every component.

**B7. What is a batch?**

An individual stock record with its own identifier, blood group, component,
unit count, collection date, expiry, status, quarantine information and audit
history. The specification forbids modelling inventory as a single aggregate
number, because an aggregate cannot express that half of it expires tomorrow.

**B8. What statuses can a batch have?**

`AVAILABLE`, `QUARANTINED`, `EXPIRED`, `WITHDRAWN` and `CONSUMED`.

**B9. What does "eligible" mean?**

Operationally usable: available status, positive unit count, a valid expiry in
the future, and no quarantine or withdrawal. It is explicitly **not** a
clinical judgement — LifeLink filters operationally ineligible stock but cannot
certify clinical suitability.

**B10. What are the freshness labels?**

Fresh within six hours, Aging from six to twenty-four, Stale from
twenty-four to forty-eight, Outdated beyond that. Unknown when there is no
timestamp, or when the timestamp is in the future, which indicates clock skew
rather than exceptional freshness.

<!-- pagebreak -->

# 7. Beginner Questions: The Honesty Rules

**B11. What is the difference between "updated" and "verified"?**

An update is any write, including one from an automated hospital feed. A
verification is a person confirming the recorded figures. A batch can be
updated every minute and still never have been verified by anyone. LifeLink
tracks them in two separate fields and shows two separate badges.

**B12. Why does that distinction matter?**

Because freshness alone is misleading. A number that is thirty seconds old
sounds authoritative, but if it came from a feed nobody has checked against the
shelf, its age says nothing about its accuracy.

**B13. What is the difference between "none in stock" and "not reported"?**

"None in stock" means the facility reported its inventory and currently has
none of what you need. "Not reported" means it has published nothing at all.
A user seeing zero does not call. A user seeing "not reported" calls and may
find supply.

**B14. How is that enforced in the code?**

`AvailabilityState.UNKNOWN` is a distinct enum value carried from the domain
layer through the service, the API response and into a visually distinct badge.
The aggregation function takes an `inventory_known` flag, and when it is false
no query runs at all — querying and finding nothing would produce
`UNAVAILABLE`, which means something different.

**B15. Is an availability alert a reservation?**

No. An alert is informational only: nothing is held, allocated or clinically
approved. The system says so in the API response, in the notification body and
on the screen.

Be careful with the next sentence, because the honest answer has two halves.
LifeLink *does* have reservations — they are a separate feature, described in
B16 — but an **alert** is not one and never writes to inventory. Three
mechanisms, three different answers to "what does this hold?":

| Mechanism | Holds |
|---|---|
| Availability alert | Nothing |
| Provider response to an emergency request | Nothing — a willingness to proceed |
| Temporary reservation | **Units, atomically** |

**B16. How does the reservation feature work, and why is it the ordinary way to ask for blood?**

A reservation holds specific units at one facility for a bounded time. Placing
one *is* the ordinary request workflow: there is no separate "blood request"
entity, which is [ADR-0018](#) and worth saying out loud, because an examiner
may expect two systems and find one.

Four properties make it safe to hold real supply:

1. **Atomic.** The pool counter is updated inside a conditional
   `TransactWriteItems` that re-checks the arithmetic at write time. Two
   callers racing for the last two units both pass the advisory domain check;
   only one wins the transaction.
2. **Bounded.** Every hold carries an explicit expiry, capped at eight hours,
   and one person may hold once per facility, group and component. A hold that
   sterilised supply indefinitely would be worse than no hold at all.
3. **Released actively.** Expiry is processed by a sweep, not by DynamoDB TTL,
   because TTL deletes within roughly 48 hours on a best-effort basis. A hold
   must stop holding the moment it expires, so reads use the *effective*
   status rather than the stored row.
4. **Not clinical.** A reservation is not a cross-match, not clinical approval
   and not a guarantee of release. The API returns that sentence with every
   reservation, and the interface renders `CONFIRMED` as "Accepted — units
   held", never "approved".

The earlier objection — that holding stock for someone who never arrives
denies it to someone who would have come — was real, and the expiry is the
answer to it. The hold lapses and the units return to availability.

**B17. Can LifeLink decide a request is critical?**

No. Clinical priority is certified only by an authorized hospital role, and the
certification records who, their role, their organization and when. A new
request carries `clinicalPriority: null` and nothing the requester submits can
change that.

**B18. What is the Impact Score?**

A non-monetary recognition metric: one hundred points per *verified* donation.
It is deliberately not awarded for registering or attending, and the
documentation and interface both state that it does not indicate medical
eligibility.

**B19. What are the milestones?**

First Drop at one verified donation, Life Saver at three, Community Hero at
five, Legacy Donor at ten.

**B20. Can a donor verify their own donation?**

No, and the rule is enforced in the service layer rather than only in the
permission matrix. A camp organizer who donated at their own camp holds the
verify permission and is still refused. There is a test that grants the donor
the staff role specifically to prove the refusal holds.

<!-- pagebreak -->

# 8. Beginner Questions: Technology

**B21. What is the frontend built with?**

React with Vite, in JavaScript rather than TypeScript, with MapLibre GL JS for
map rendering. {{fact:frontend_modules}} modules, {{fact:frontend_lines}} lines.

**B22. What is the backend built with?**

Python {{fact:python_version}} on AWS Lambda behind an API Gateway HTTP API.
{{fact:backend_modules}} modules, {{fact:backend_lines}} lines, with
{{fact:route_count}} routes behind a single function.

```diagram
type: layered
title: The stack, as a beginner answer
layer Client
node ui React and MapLibre style=user
layer Delivery
node cdn CloudFront and S3 style=aws
layer API
node gw API Gateway HTTP API style=aws
layer Compute
node fn Lambda Python style=aws
layer Data
node db DynamoDB style=data
layer Supporting
node cog Cognito style=aws
node q SQS and dead letter queues style=aws
node loc Amazon Location style=external
edge ui -> cdn
edge ui -> gw
edge gw -> fn
edge fn -> db
edge fn -> q
edge fn -> loc
edge ui -> cog
```

*Figure 8.1. The stack in one picture.*

**B23. Why DynamoDB rather than a relational database?**

The access patterns were known in advance and are all key lookups. DynamoDB
gives predictable single-digit-millisecond latency, scales without capacity
planning, and costs nothing at rest on on-demand billing. A relational database
would mean managing a server or paying for an idle instance.

**B24. What is a partition key?**

The attribute DynamoDB hashes to decide which physical partition an item lives
on. Every query must supply one exactly. It is why the data model is organised
around the questions the application asks rather than around normalised
entities.

**B25. What is a sort key?**

The second part of a composite primary key. It orders items within a partition
and supports range conditions — `begins_with`, `between`, `greater than` —
which is what makes composite sort keys so useful.

**B26. What is a global secondary index?**

An alternative key structure over the same table, maintained automatically, so
the data can be queried a second way. LifeLink has {{fact:gsi_count}} of them
across {{fact:table_count}} tables, each existing because some question needed
a different key.

**B27. Why is scanning forbidden?**

A scan reads every item in the table and bills for all of it. It is not a slow
query, it is an unbounded operation. LifeLink forbids scans on user-facing
paths; the two places that scan are offline maintenance jobs, and one logs that
it scanned.

**B28. What is Lambda?**

Managed compute that runs a function in response to an event, billed by
millisecond, with no server to provision. It suits a workload that is bursty
and mostly idle.

**B29. What is Cognito used for?**

User identity: sign-up, sign-in, password recovery, MFA, and issuing signed
JWTs. LifeLink verifies the signature but reads roles and account status from
its own database, so the token proves who you are and the database decides what
you may do.

**B30. What is SQS used for?**

Decoupling. When stock changes, the API writes a durable event and returns
immediately. Alert matching and notification delivery happen asynchronously on
queue consumers, each with a dead-letter queue and an alarm.

<!-- pagebreak -->

# 9. Intermediate Questions: Data and Concurrency

Forty intermediate questions across Chapters 9 to 13.

**I1. Why eleven tables rather than single-table design?**

The conventional advice is one table, and for query efficiency it is right.
The deciding factor here was IAM. With separate tables, "the notification
worker must not touch inventory" is an IAM policy the platform enforces. With
one table it is a code-review convention. Separate tables also allow per-domain
TTL and backup policy, and limit the blast radius of a bad migration.

Single-table techniques are still used *within* a context: a camp's metadata,
registrations and staff share one partition.

**I2. What is the cost of that choice?**

Cross-domain reads need two calls. Ranking facilities by availability reads the
facilities table and then the inventory table. That is accepted because those
are the integration points the design wants to be explicit anyway.

**I3. Explain the inventory sort key.**

`GSI1SK` is `STATUS#<status>#<expiresAt>`. A range condition from
`STATUS#AVAILABLE#<now>` upward returns exactly the available, unexpired
batches. Quarantined and expired rows sort under different prefixes and are
never read, so they cannot leak into an availability answer by accident.

**I4. Why not use a filter expression instead?**

A filter is applied after items are read and billed. A sort-key condition is
applied during the read. For a facility with a hundred batches of which ten are
eligible, the difference is reading ten items instead of a hundred.

**I5. How is a lost update prevented?**

Every batch carries a `version`. Writes are conditional on that version being
unchanged, and deductions additionally require `availableUnits >= :needed`. A
concurrent writer fails the condition and gets a 409, after which the service
re-reads, recomputes and retries up to three times.

**I6. Why re-read rather than just retry?**

Because the condition is on the version that has already moved. Resubmitting
the same computed change would fail identically forever. The retry must
recompute from current state.

**I7. What happens after three retries?**

The error propagates as a 409. Looping indefinitely would hide a batch under
constant contention, which is a situation a human should see.

**I8. How is camp oversubscription prevented?**

A `TransactWriteItems` that puts the registration with
`attribute_not_exists(SK)` and increments the counter with
`registeredCount < :capacity`. Both succeed or neither does. A read-check-write
would let two simultaneous requests both pass the check.

**I9. Why is the service's capacity check not enough?**

It is advisory. Between reading the count and writing the registration another
request can take the last seat. The check exists to produce a good error
message; the transaction is authoritative.

**I10. How is exactly-once donation credit enforced?**

The ledger row's sort key is `LEDGER#<donationId>` written with
`attribute_not_exists(SK)` inside a transaction with the donation status
update. A replayed verification cannot create a second entry for the same
donation.

<!-- pagebreak -->

# 10. Intermediate Questions: Events and Reliability

**I11. What is the transactional outbox and why use it?**

Writing to the database and then publishing a message is not atomic. A crash
between them loses the event silently — no error, no retry, just downstream
work that never happens. The outbox writes the event *in the same transaction*
as the domain change, and a DynamoDB stream publishes it afterwards.

```diagram
type: sequence
title: Why write-then-publish loses events and the outbox does not
actor svc Service
actor db Database
actor mq Message broker
actor con Consumer
msg svc -> db write domain change committed
msg svc -> mq publish event
note A crash between those two steps loses the event with no error anywhere.
msg svc -> db transaction domain change and outbox row
msg db -> mq stream relays the outbox row
msg mq -> con deliver at least once
note With the outbox the worst case is a duplicate, which consumers absorb.
```

*Figure 10.1. The dual-write problem and its resolution.*

**I12. What does that cost?**

Double write cost on event-producing paths, plus at-least-once delivery rather
than exactly-once. The second is not really a cost, since exactly-once is not
available in a distributed system.

**I13. Why not put a stream directly on the domain table?**

It would couple the event contract to the storage schema. Renaming an attribute
would silently become a breaking change for every consumer. The outbox lets the
event shape be designed deliberately and versioned.

**I14. How do consumers handle duplicates?**

Every consumer claims the event id in an idempotency table using a conditional
put before doing anything. A completed claim returns the stored result without
re-executing. Duplicates are logged at info level as suppressed, because they
are normal operation rather than failures.

**I15. What if a consumer dies mid-work?**

The claim sits `IN_PROGRESS`. A stale-claim window of five minutes lets a later
attempt retake it; without that, a crashed request would block its own retry
for the full 24-hour TTL.

**I16. What is `ReportBatchItemFailures`?**

It lets an SQS consumer return only the messages that failed rather than
failing the whole batch. Without it, one bad message in a batch of five returns
all five, re-running four that already succeeded.

**I17. What happens to a message that always fails?**

After five receives it moves to a dead-letter queue with fourteen-day
retention, and an alarm fires within five minutes. The runbook says to diagnose
before redriving, because a poison message will simply fail five more times.

**I18. Why is the visibility timeout 180 seconds?**

Six times the 29-second consumer timeout, per AWS guidance. A timeout shorter
than the processing time would make a message reappear while it was still being
handled.

**I19. How is an event lost if the publisher dies?**

It is not. The outbox row remains with `dispatched: false`. The stream retries,
and a pending-rows alarm surfaces anything stuck. The worst outcome is a
duplicate publish, which consumers absorb.

**I20. What is a correlation id used for?**

One identifier generated in the browser, attached to every log line, audit
record, outbox event and queue message for that request. It retrieves the whole
story of a user action including the background work it caused.
