# 1. Explain LifeLink in 30 Seconds

> LifeLink is a cloud platform that helps people find blood when they need it.
> Blood banks record their stock at batch level; the public can search nearby
> facilities filtered by blood group and component; hospitals can raise
> emergency requests that are matched against compatible stock; and donors can
> find camps and build a verified donation history.
>
> The design point I care most about is honesty about data. The system always
> shows two separate things about any stock figure — how recently it was
> updated, and whether a human independently verified it — and it never shows
> "zero" for a facility that simply has not reported. It is a coordination
> system, not a clinical one: it does not reserve blood and does not decide
> clinical urgency.

## 1.1 Why this answer works

It leads with the problem, not the technology. Nobody asked which AWS services
you used, and volunteering them first signals that the technology is the point
rather than the problem.

It names one distinctive design decision. That gives the interviewer something
to pull on, and the thread it opens — freshness versus verification — is one
you can talk about for twenty minutes.

It states a boundary. "Coordination, not clinical" pre-empts the question
"isn't this dangerous?" and shows you thought about scope before you thought
about code.

## 1.2 What to avoid

- Listing services. "It uses Lambda, DynamoDB, Cognito, SQS, S3, CloudFront…"
  tells an interviewer you can read a template.
- Claiming scale you do not have. It is a demonstration system with synthetic
  data, and saying so costs nothing.
- The word "simply". Nothing here is simple, and the word invites a question
  designed to prove it.

<!-- pagebreak -->

# 2. Explain LifeLink in 2 Minutes

> **The problem.** India collects enough blood in aggregate, but people still
> die waiting for it, because finding the right unit at the right time is a
> coordination problem. A hospital needs two units of O-negative packed cells
> in four hours; those units may exist eleven kilometres away and nobody knows.
>
> **What it does.** Seven capabilities. Blood banks maintain batch-level
> inventory with expiry, quarantine and audit history. The public searches
> nearby facilities, ranked by availability, data freshness, independent
> verification and distance. Donors register short-term alerts and are told
> when matching stock appears. Camps run end to end from approval through
> check-in to verified donation. Hospitals raise emergency requests that an
> authorized clinician certifies for priority, after which a deterministic
> matching engine routes them to facilities with compatible stock.
>
> **The architecture.** React frontend on CloudFront and S3. Python on Lambda
> behind an API Gateway HTTP API. DynamoDB with eleven tables, one per bounded
> context, and twenty-two secondary indexes because every query resolves to a
> key lookup — there are no scans on user-facing paths. Cognito for identity,
> SQS with dead-letter queues for asynchronous work, Amazon Location for maps
> and routing.
>
> **What I would want you to notice.** Three things. Availability, freshness
> and verification are three separate signals, never collapsed into one.
> Nothing is ever reserved, so there is no counter to double-count. And
> authorization reads roles and account status from the database on every
> request rather than trusting token claims, so suspending an account takes
> effect immediately.

## 2.1 The structure

Problem, capabilities, architecture, distinctive decisions. Four beats, roughly
thirty seconds each.

The fourth beat is the one that separates candidates. Most people describe
what they built; fewer say what they would want a reviewer to notice, which
demonstrates that you have an opinion about your own work.

<!-- pagebreak -->

# 3. Explain LifeLink in 5 Minutes

Add three things to the two-minute version: a worked example, a constraint you
designed around, and a bug you found.

## 3.1 The worked example

> Take an emergency request. A hospital staff member submits it: blood group,
> component, units, location, deadline, contact details, consent. It is created
> with **no** clinical priority — explicitly null. Nothing they can type sets
> it.
>
> An authorized hospital user then certifies it as Critical, Urgent or
> Scheduled. That endpoint re-checks that their hospital is currently verified,
> so a hospital suspended since the request was raised cannot certify it. The
> certification records who, their role, their organization and the timestamp.
>
> A dispatcher runs every minute. It reads pending requests from an index
> sorted by priority then creation time, recomputes an *effective* priority
> with aging so that a Scheduled request cannot wait forever, and processes a
> bounded batch. Crucially, aging writes a different field from the clinical
> priority — a scheduler that promoted a Scheduled request to Critical would
> have overruled a doctor.
>
> Matching looks up compatible donor groups in a versioned reference table. If
> the combination is not in the table it returns nothing rather than guessing.
> Facilities with eligible stock are notified. When a provider accepts, the
> system revalidates the stock first, then records an **offer** — it does not
> decrement anything, because nothing is reserved.

```diagram
type: sequence
title: The emergency flow, as you would draw it on a whiteboard
actor hosp Hospital staff
actor sys LifeLink
actor auth Authorizer
actor disp Dispatcher
actor bank Blood bank
msg hosp -> sys create request no priority
msg auth -> sys certify as urgent
msg disp -> sys recompute effective priority
msg disp -> bank notify matched providers
msg bank -> sys accept with units offered
msg sys -> sys revalidate stock before recording
msg sys -> hosp offer recorded not reserved
note Draw this one. It carries the three decisions worth talking about.
```

*Figure 3.1. The emergency flow, in the form worth drawing for an interviewer.*

## 3.2 The constraint

> The AWS account has a Lambda concurrency ceiling of ten, against a default of
> a thousand. That shaped the design: no function reserves concurrency, queue
> consumers cap their own parallelism at two, and the emergency dispatcher is
> one scheduled function rather than per-priority consumers.
>
> That last one is interesting because the specification independently warned
> that three SQS queues do not give you priority ordering — nothing coordinates
> three independent consumers. So the constraint and the correct design pointed
> the same way.

## 3.3 The bug

> The one I would mention is geohash coverage. Facility discovery queries
> geohash cells around the user. The first version queried the centre cell and
> its eight neighbours, which is correct only while the radius is smaller than
> one cell. A thirty-kilometre search returned two facilities when a third,
> twenty-six kilometres away, should have appeared.
>
> It was invisible: no error, no exception, just a usable blood bank that never
> showed up. Integration tests against seeded data with known distances found
> it.
>
> Fixing it created a second problem — covering the full bounding box made a
> hundred-kilometre search need two thousand one hundred cell queries. So I
> added a third geohash precision tier and retuned the boundaries. The test
> suite now asserts both properties: coverage at ten radii, and a bounded query
> count.

## 3.4 Why the bug belongs in the answer

Volunteering a bug is counter-intuitive and almost always lands well. It
demonstrates that you tested properly, that you understand *why* the bug was
hard to see, and that your fix was validated rather than hoped for. It also
pre-empts "what went wrong?" by answering it on your own terms.

<!-- pagebreak -->

# 4. Explain LifeLink in 10 Minutes

The ten-minute version is the five-minute version plus depth on whichever area
the interviewer leans toward. Prepare four tracks and pick one.

## 4.1 Track A — Data modelling

Eleven tables rather than one, and why. Thirty-nine access patterns enumerated
before any table existed. The composite sort key
`STATUS#<status>#<expiresAt>` that turns a filter into a range condition, so
ineligible stock is never even read. The sharded expiry index that prevents a
hot partition. Index projections chosen deliberately: `INCLUDE` with seven
attributes rather than `ALL`, because `KEYS_ONLY` would force a second read and
`ALL` would double storage.

## 4.2 Track B — Concurrency

Eight invariants, each enforced by the datastore rather than by convention.
Optimistic concurrency with a version attribute. The camp capacity transaction
that makes oversubscription impossible rather than unlikely. The ledger row
keyed on donation id so a replayed verification cannot double-credit. And the
bug where a version conflict was reported as a duplicate, so the retry path
never engaged — the code "worked" in that it raised, but raised the wrong
thing.

## 4.3 Track C — Security

Authorization in one decorator, five checks in a deliberate order. Roles read
from the database, not from token claims, which is what makes suspension
immediate. Organization scoping applied centrally so a handler author cannot
forget it. An audit table the application can write but physically cannot
modify, because the IAM grant omits `UpdateItem` and `DeleteItem`.

## 4.4 Track D — Honesty in the data model

The three-way distinction between available, none in stock, and not reported.
Freshness and verification as separate signals. Offers that are never summed
into secured supply. A compatibility table marked `UNREVIEWED_SYNTHETIC` whose
loader refuses to start without a review status. An SMS channel that raises
`CHANNEL_UNAVAILABLE` rather than pretending to send.

<!-- pagebreak -->

# 5. The Project Walkthrough for Professors

## 5.1 A fifteen-minute demonstration order

| Minute | Show | Say |
|---|---|---|
| 0–1 | Home page, demo banner | "Every record is synthetic. The banner cannot be dismissed, by design." |
| 1–4 | Search O-negative PRBC, 60 km | "Six facilities. Note one says *not reported* — that is different from zero." |
| 4–6 | Widen to 60 km, narrow to 10 km | "Radius correctness: Chandigarh appears at 57.7 km. An early bug hid it." |
| 6–8 | Facility detail, availability matrix | "Freshness and verification shown separately on every row." |
| 8–10 | Blood bank dashboard, deduct a unit | "Conditional write. Two staff cannot both take the last unit." |
| 10–12 | Hospital dashboard, certify priority | "Only an authorizer sees these buttons; the server enforces it anyway." |
| 12–13 | Sign in as `user-suspended-1` | "Valid token, correct role, every action refused." |
| 13–15 | Admin audit query | "Who did what, to what, when. Write-only in AWS." |

*Table 5.1. A demonstration that shows the design decisions, not just the
screens.*

## 5.2 Questions professors ask, and short answers

**"Is this real data?"** No. Every organization, facility, batch, camp and
request is synthetic, labelled with three marker fields, and the interface
shows a permanent banner. The coordinates are plausible Punjab locations; the
institutions at them are invented.

**"Could this be used clinically?"** Not as it stands, and the limiting factor
is not engineering. The blood compatibility reference has not been reviewed by
a qualified professional, and it is marked `UNREVIEWED_SYNTHETIC` everywhere it
appears. The system also deliberately makes no clinical decisions.

**"Did you deploy it?"** Yes — on 24 November 2026. Stack `lifelink-dev` is
live in `ap-southeast-2` with 66 resources, and the deployment was verified by
56 live checks against the running system. What I still do not claim is a
tested disaster-recovery capability or browser-verified workflows: no restore
has been rehearsed, and twelve browser checks remain outstanding.

**"How do you know it works?"** 657 backend tests and
294 frontend tests, with the end-to-end scenarios named after
the ten flows the specification requires. The numbers in the documentation are
produced by running the suites at build time, not typed in.

**"What is the weakest part?"** The absence of a reviewed compatibility
reference, followed by the fact that several operational claims are design
assumptions rather than measurements: LifeLink is deployed, but rollback and
restore have never been rehearsed, and the browser workflows have not been
independently verified by a person. All are in the known-limitations table.

## 5.3 Deliberately showing a refusal

The most persuasive two minutes of any demonstration is signing in as
`user-suspended-1` and watching every action fail with
`ACCOUNT_SUSPENDED`. It shows a security property working rather than
described, and it is the one test a token-trusting system cannot pass.

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
map rendering. 60 modules, 12750 lines.

**B22. What is the backend built with?**

Python 3.14.2 on AWS Lambda behind an API Gateway HTTP API.
43 modules, 12806 lines, with
58 routes behind a single function.

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
the data can be queried a second way. LifeLink has 24 of them
across 12 tables, each existing because some question needed
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

<!-- pagebreak -->

# 11. Intermediate Questions: Security

**I21. Where is authorization enforced?**

In one decorator, `@requires`, applied to every protected handler. Nothing else
performs authorization, so the rules live in one reviewable place and a route
that forgets to declare a permission fails a build-time audit rather than
silently going public.

**I22. What order are the checks in, and why?**

Token signature and claims; load the principal from the database; reject if the
account is not active; check the permission; compare the resource's owning
organization with the caller's. Account status comes before permission so a
suspended administrator gets `ACCOUNT_SUSPENDED` rather than a confusing
`FORBIDDEN` — the error should name the real reason.

**I23. Why read roles from the database rather than the token?**

Because a token is a snapshot. A role revoked thirty seconds ago would still
work for the remaining fifty-nine minutes of the token's life. Reading from the
database means a change takes effect on the very next request.

**I24. What is the cost of that?**

One read per request. It is mitigated by a short in-process cache with a
thirty-second TTL, which bounds the staleness explicitly rather than
accidentally.

**I25. Why not use an API Gateway JWT authorizer alone?**

It validates the token but knows nothing about account status or resource
ownership. It would happily admit a suspended user with a valid token. It is a
sensible outer layer but cannot be the only one.

**I26. How is an insecure direct object reference prevented?**

The ownership comparison lives in the decorator, not the handler. A handler
declares *how* to find the owning organization of the resource it touches —
`resource_owner=_facility_owner` — and the decorator does the comparison. A
handler author cannot forget a check they do not perform.

**I27. What does the cross-organization error say?**

"This resource belongs to another organization", without naming which one.
There is a test asserting the other organization's identifier appears in
neither the message nor the details, because an error message is an
information-disclosure channel.

**I28. How are audit records protected?**

The Lambda execution role is granted `PutItem` and `Query` on the audit table —
no `UpdateItem`, no `DeleteItem`. The application physically cannot rewrite
history. That is tamper *resistance*, not immutability: an account
administrator with sufficient IAM privileges could still alter it, and the
documentation says so rather than overclaiming.

**I29. How are logs prevented from leaking personal data?**

Redaction by key name at any nesting depth, applied by the formatter rather
than by each caller. The redacted set includes passwords and tokens, and also
email, phone, coordinates and date of birth — personal data that accumulates in
logs without anyone deciding it should.

**I30. What is PKCE and why is it used?**

Proof Key for Code Exchange. A browser cannot keep a client secret, so instead
it generates a random verifier, sends its hash with the authorization request,
and presents the verifier when exchanging the code. An intercepted
authorization code is useless without the verifier.

<!-- pagebreak -->

# 12. Intermediate Questions: Geospatial and Search

**I31. How does geospatial search work?**

Geohash encodes a latitude and longitude into a string where a shared prefix
means geographic proximity. Facilities store geohashes at three precisions,
each indexed. A search computes which cells cover the circle, queries those
cells, and then filters by exact Haversine distance.

**I32. Why not just compute distance for every facility?**

That is a scan. The geohash prefix is what makes proximity an indexed key query
rather than a full table read.

**I33. Why three precisions?**

Cell size must be comparable to the search radius. Too fine means many queries;
too coarse means reading far more candidates than needed. Precision 6 for up to
three kilometres, 5 up to twenty, 4 beyond that — each backed by its own index.

**I34. How were those boundaries chosen?**

By measurement. A five-kilometre search at precision 6 needed 195 cell queries;
a hundred-kilometre search at precision 5 needed 2,107. Both were untenable,
especially at a Lambda concurrency ceiling of 10. The
boundaries were moved until the worst case in every tier stayed under a
documented limit.

**I35. Why query neighbouring cells at all?**

Because a facility five hundred metres away can be in an adjacent cell. The
original implementation queried only the centre cell and its eight neighbours,
which is correct only while the radius is smaller than one cell — and silently
wrong beyond that.

**I36. How is the coverage property tested?**

By walking the circle at the search radius in five-degree steps and asserting
every bearing's cell is in the set, at ten different radii. Boundary points are
the hardest case and the ones the original code got wrong.

**I37. How are facilities ranked?**

Availability 30%, freshness 20%, distance 20%, quantity 15%, verification 15%.
The weights are configurable and validated to sum to 1.0. Every result carries
its component contributions and a human-readable explanation.

**I38. Can ranking surface expired stock?**

No. Eligibility is a hard filter applied while building the candidate list;
ranking only reorders survivors. No weighting, however tuned, can promote
something that never entered the list.

**I39. How does unknown availability rank?**

It scores zero on the availability axis — correctly, since it is not confirmed
supply — but the state travels to the response unchanged, so the interface
renders it as "not reported" rather than as unavailable.

**I40. Why is ranking deterministic?**

Ties break on distance, then on facility id. Without the final tie-break, two
facilities with identical scores could order differently between calls, which
makes results irreproducible and tests flaky.

<!-- pagebreak -->

# 13. Advanced Questions: Distributed Systems

Forty advanced questions across Chapters 13 to 18.

**A1. Why can you not have exactly-once delivery?**

Because the acknowledgement can be lost. If a consumer processes a message and
the acknowledgement fails, the broker cannot distinguish "processed but not
acknowledged" from "never processed", so it must redeliver. The achievable
property is at-least-once delivery with idempotent processing, which composes
to effectively-once *effects*.

**A2. What is the outbox pattern solving precisely?**

The dual-write problem. Two systems — a database and a message broker — cannot
be updated atomically without distributed transactions. The outbox turns two
writes into one by putting the message in the same database transaction, then
relays it asynchronously.

**A3. What does the outbox not solve?**

Ordering across aggregates, and duplicate publication. The relay may publish
the same row twice if it dies after sending but before marking it dispatched.
That is why consumers are idempotent.

**A4. How would you handle event ordering if it mattered?**

DynamoDB streams preserve order within a partition key. If strict ordering were
required per aggregate, the outbox partition key would be the aggregate id
rather than the event id. LifeLink does not need it: every consumer is
order-independent, which is a stronger property than being correctly ordered.

**A5. Explain eventual consistency in this system.**

Global secondary indexes are always eventually consistent. A write visible in
the base table may not yet appear through an index. LifeLink handles it three
ways: ignore it where it does not matter, use a strongly consistent base-table
read where it does, and let idempotency absorb it where it could cause
duplicate work.

**A6. Give a concrete example of the third.**

The dispatcher reads pending requests from an index. It may see a request it
already picked up in the previous cycle. That is harmless because the work is
idempotent and the status transition is conditional — the second attempt finds
the status has moved and does nothing.

**A7. What is the CAP trade-off here?**

DynamoDB chooses consistency and partition tolerance for base-table reads with
`ConsistentRead`, and availability for index reads. LifeLink leans on that
split deliberately: decisions that must not be stale use consistent base reads;
browsing uses indexes.

**A8. How do you prevent a hot partition?**

By choosing partition keys that distribute. The expiry sweep is the natural
hazard — "all batches expiring before now" wants one key — so it is sharded
across ten partitions by a hash of the batch id, each swept independently.

**A9. What is optimistic concurrency and when is it the wrong choice?**

Reading a version, computing a change, and writing conditionally on the version
being unchanged. It is wrong under high contention on a single item, where most
attempts fail and the retry traffic dominates. LifeLink's contention is low —
two staff editing one batch — so it is appropriate.

**A10. What would you use instead under high contention?**

Either a different data model that spreads the contention, or a queue that
serialises updates to the hot item. For stock on a single batch, the first is
usually better: if one batch is contended, the batch granularity is probably
wrong.

<!-- pagebreak -->

# 14. Advanced Questions: Scheduling and Fairness

**A11. Why do three SQS queues not give you priority?**

Because three event source mappings are three independent consumers. Nothing
coordinates them. Lambda will run the low-priority consumer while high-priority
messages wait, because each mapping polls its own queue on its own schedule.

**A12. Could you make it work with reserved concurrency?**

Partially, by starving the lower-priority consumers of concurrency. It is
fragile — the proportions have to be tuned and retuned — and on this account
impossible, because reserved concurrency is subtracted from a pool of
10.

**A13. How does the application-level dispatcher work?**

One function on a one-minute schedule reads pending work from an index sorted
by effective priority then creation time, recomputes aging, and processes a
bounded batch.

**A14. What is priority aging?**

Raising a long-waiting item's dispatch priority: one band per fifteen minutes
waited. It prevents starvation of the lowest band under sustained high-priority
load.

**A15. Why is aging dangerous in a clinical context, and how is that handled?**

Because promoting a Scheduled request to Critical, if those are the same field,
overrules a doctor. LifeLink stores two fields: `clinicalPriority`, written
only by the certification endpoint, and `effectivePriority`, written only by
the scheduler. A test asserts aging leaves the clinical priority unchanged.

**A16. What is the cost of the scheduler design?**

Up to sixty seconds of latency, and a single point of failure. The first is
acceptable for a workflow whose next steps are human and take minutes; a P1
request also triggers an out-of-band dispatch. The second is covered by an
alarm, and the handler deliberately re-raises on failure so the alarm fires.

**A17. How would you scale the dispatcher?**

Shard by region or by priority band with a coordinator, or move to a workflow
engine like Step Functions. At current volume neither is justified, and the
specification asks that Step Functions be used only where the value justifies
the complexity.

**A18. What is deadline-driven promotion?**

A request due within thirty minutes sorts as highest priority regardless of
band. It is scheduling, not clinical judgement, and it writes the same
scheduler-owned field.

**A19. How do you prevent the dispatcher processing the same request twice?**

Status transitions are conditional on the current status. Two overlapping
dispatcher runs mean one condition fails.

**A20. What happens to a request whose deadline passes mid-workflow?**

The dispatcher checks on each cycle and transitions it to `EXPIRED`. Providers
can no longer respond, because responses are refused for closed requests.

<!-- pagebreak -->

# 15. Advanced Questions: Data Modelling

**A21. Walk through designing the inventory access pattern.**

The question is "what eligible stock of group G, component C does facility F
have?" A naive design queries all batches at F and filters. Better: an index
keyed on `FACILITY#F#G#C` so the partition is already narrowed. Best: add
status and expiry to the sort key so a range condition excludes ineligible rows
during the read rather than after it.

**A22. Why `INCLUDE` rather than `ALL` or `KEYS_ONLY` on that index?**

`KEYS_ONLY` would force a base-table read per batch to get the unit count.
`ALL` would duplicate every attribute including audit metadata nobody reads on
that path. `INCLUDE` with the seven attributes the aggregation needs is the
smallest index that answers the question in one query.

**A23. How do you model a one-to-many relationship in DynamoDB?**

Share a partition. A camp's metadata, registrations and staff all live under
`CAMP#<id>` with different sort key prefixes, so one query returns the lot.
That is single-table design applied within a bounded context.

**A24. How does pagination work, and why cursors?**

Cursor-based: an opaque base64 encoding of DynamoDB's `LastEvaluatedKey` plus a
fingerprint of the query. Offset pagination would require reading and
discarding rows — a scan in disguise. The fingerprint means a cursor presented
against a different query is rejected rather than silently returning the wrong
result set.

**A25. Why does the audit table use a customer-managed KMS key?**

Because key usage is logged in CloudTrail. Anyone decrypting audit records
leaves a trace in a place they do not control through the application.

**A26. Which tables have no point-in-time recovery, and why?**

Idempotency, notifications and outbox. All are TTL-bound and reconstructible.
PITR on them would be spend with no recovery value, and leaving it off is a
decision rather than an oversight.

**A27. How does TTL interact with correctness?**

TTL deletion is eventual — AWS makes no promise about timing. Nothing in
LifeLink depends on a TTL having fired. Alert expiry is checked explicitly at
match time; TTL only reclaims storage.

**A28. What happens if a transaction exceeds its item limit?**

`TransactWriteItems` allows a hundred items. LifeLink's largest transaction is
three. If a future requirement needed more, the right answer would be to
reconsider the aggregate boundary rather than to batch transactions.

**A29. How would you migrate the schema?**

Additive changes are free — DynamoDB is schemaless per item. A breaking change
would need dual-writing both shapes, backfilling, switching reads, then
removing the old shape. The per-context tables limit a migration's blast radius
to one domain.

**A30. What is the biggest weakness of this data model?**

Dashboard aggregates are computed per request. At real scale that becomes slow,
and the correct answer is a materialised read model updated from the event
stream. It is recorded as future work rather than described as if it exists.

<!-- pagebreak -->

# 16. Advanced Questions: Security Design

**A31. A valid, unexpired, correctly signed token arrives from a suspended
account. What happens, and why is that hard?**

It is rejected with `ACCOUNT_SUSPENDED`. It is hard because every
cryptographic check passes — the token is genuinely valid. Only a system that
treats the token as proof of identity rather than proof of authority can
distinguish this case, which is why roles and account status are read from the
database on every request.

**A32. What is the attack this prevents?**

An insider whose access is revoked continues operating for up to the token
lifetime. With a one-hour access token that is a one-hour window during which
a dismissed administrator can still change inventory and the audit trail
records it as legitimate.

**A33. How would you make audit records genuinely immutable?**

Write them to an append-only store the application cannot address at all —
S3 Object Lock in compliance mode, or QLDB. Or hash-chain each record so
tampering is detectable even if possible. LifeLink does neither and says so:
it has tamper *resistance* via a write-only IAM grant, not immutability.

**A34. Why not just hash-chain the DynamoDB records?**

It is a reasonable improvement and would detect tampering. It does not prevent
it, and it introduces an ordering dependency on writes that currently have
none. It would be the next step if the threat model required detection.

**A35. What is the confused deputy problem, and where does it appear here?**

A privileged service is tricked into acting on an attacker's behalf. It appears
in the S3 bucket policy: the CloudFront service principal is shared across all
AWS accounts, so without an `AWS:SourceArn` condition naming this specific
distribution, any CloudFront distribution anywhere could read the bucket.

**A36. The browser needs map tiles. How do you avoid putting a key in it?**

A Cognito identity pool issues temporary credentials scoped to exactly four
read-only Amazon Location tile actions on one map resource. A browser holding
them cannot geocode, cannot route, and cannot read any data. Unauthenticated
identities are permitted so anonymous visitors still see a map.

**A37. Why is geocoding on the backend when tiles are not?**

Volume and exposure. Tiles are thousands of requests that would be slow and
expensive to proxy. Geocoding is low-volume, benefits from caching, and should
not be exposed as a free geocoding service to anyone who opens the page.

**A38. How do you prevent account enumeration?**

Cognito's `PreventUserExistenceErrors` is enabled, so sign-in failures do not
distinguish "no such user" from "wrong password". LifeLink's own errors are
written to avoid confirming existence — a cross-organization refusal does not
name the owning organization.

**A39. What is the threat model for the demo seeder?**

That someone runs it against production. Three independent guards: the
environment name must be local, dev or test; a local endpoint must be
configured; and the endpoint must not point at real AWS. One check is a typo
away from being bypassed.

**A40. What would a penetration tester find first?**

Probably the local development authentication path, if it were ever enabled
outside local. It is guarded by the environment variable, but a misconfigured
`LIFELINK_ENV` would accept self-signed tokens. The mitigation is that the
local verifier needs a public key file that does not exist in a deployment,
but defence in depth would add an explicit refusal.

<!-- pagebreak -->

# 17. Advanced Questions: Operational Reasoning

**A41. Lambda concurrency is ten. Walk me through the consequences.**

No function reserves concurrency, because reservation subtracts from the shared
pool. Queue consumers cap themselves at two concurrent executions each. The
dispatcher is one scheduled invocation rather than a consumer pool. API Gateway
throttles at ten requests per second so it sheds load cleanly before Lambda
starts throttling. Throttling is treated as expected: adaptive retries, partial
batch failures, and an alarm on the first occurrence.

**A42. Is that a good design or a workaround?**

Both, and honestly it improved the design. It forced explicit bounds on every
fan-out and ruled out a consumer topology that was independently wrong. A
generous quota would have hidden all of it.

**A43. How do you know the system is healthy?**

8 alarms, each corresponding to a condition worth waking
someone for: dead-letter queues non-empty, queue age, API errors, Lambda
throttles, p95 latency, DynamoDB throttles, and dispatcher failure. The
dashboard exists for after the page, not instead of it.

**A44. Which alarm matters most?**

Dispatcher failure. If it stops, emergency requests are not matched while every
other indicator looks healthy. The handler re-raises specifically so the error
metric fires.

**A45. A user says "it did not work". What do you do?**

Ask for the reference shown in the error panel — the correlation id. One query
returns the request, every log line it produced, the audit record if one was
written, and any background work it triggered.

**A46. How do you debug a message in the dead-letter queue?**

Read a sample, take the correlation id and event id, query logs for the five
failures, then classify: poison message or dependency failure. Poison messages
are deleted and raise a defect for the validation gap. Dependency failures are
fixed and then redriven. Never redrive before diagnosis.

**A47. What is your RPO and RTO?**

Design assumptions, not measurements: seconds of RPO from point-in-time
recovery, hours of RTO for a restore. LifeLink is deployed and PITR is enabled
on eight of twelve tables, but **no restore rehearsal has been performed**, so
the documentation marks those rows untested.

**A48. What happens in a regional outage?**

LifeLink is unavailable. The account is pinned to one region and cross-region
replication is not available on it. For a demonstration that is acceptable; for
a real emergency coordination service it would not be, and that framing is in
the limitations rather than glossed.

**A49. What is the monthly cost?**

About $0.40 in unavoidable fixed charges — a Secrets Manager
secret — with everything else inside free tiers at demonstration volume. Map
tiles and log ingestion are the two items that scale with use. The
documentation says explicitly that the application is not free to run.

**A50. How would you reduce it?**

Shorter log retention, which is already a parameter. Fewer map tile loads, for
which the list view is genuinely useful rather than only a fallback. And
avoiding the KMS key if a separate audit key were judged unnecessary — though
that trades a real security property for a dollar.

<!-- pagebreak -->

# 18. Advanced Questions: Testing and Quality

**A51. What is the difference between your unit and integration tests?**

Unit tests exercise pure domain functions with no I/O at all — no AWS, no
mocks, no clock patching, because time is injected. Integration tests run
against a real DynamoDB API surface via moto, so condition expressions,
transactions and index range queries genuinely execute.

**A52. Why does that distinction matter? Give an example.**

A mock-based test asserting "raises on a concurrent write" would have passed
the version-conflict bug. The code did raise — it raised `DuplicateError`
instead of `ConcurrentModificationError`, so the service's retry path never
engaged. Only a real condition expression shows that.

**A53. What other bugs did integration testing find?**

Four more. An unused expression placeholder causing `ValidationException` on
verification. Three further unused placeholders breaking camp check-in and
provider responses. `None` being stripped from expression values so any update
setting an optional field to null failed. And the camp reminder index never
being populated, so reminders would never have fired.

**A54. What do those have in common?**

Four of the five failed silently or with an error that pointed somewhere else.
That is the category of bug a fake cannot produce, because a fake does not
implement the behaviour that is being got wrong.

**A55. How do you test time-dependent logic?**

By injecting time. No domain function reads the clock, so a test passes a fixed
instant and asserts exact boundaries — 6.0 hours is Fresh, 6.1 is Aging. No
patching, no flakiness.

**A56. How do you test something that should never happen?**

Assert the refusal. A substantial share of the suite tests what the system
declines: a donor verifying their own donation, an organizer managing another
organization's camp, a suspended account acting, a provider responding twice.

**A57. What is a property test and where did you use one?**

A test that asserts a general property rather than specific cases. Geohash
coverage is asserted by walking the search circle in five-degree steps at ten
radii and checking every bearing's cell is in the query set — rather than
hoping the three cases someone thought of are representative.

**A58. What is not tested?**

Load, because at a concurrency ceiling of ten a load test measures the ceiling.
Restore procedures, which have never been rehearsed even though the stack is
deployed and PITR is enabled. Cognito itself, because local
development uses a different issuer. Accessibility beyond structure, because no
audit tool was run. Each is in the limitations table.

**A59. How do you know the documentation is accurate?**

The books are generated from the repository. Code listings are extracted at
build time by function name or anchor text; metrics come from running the
suites; the route tables are read from the live router. An anchor that no
longer matches fails the build.

**A60. Did that catch anything?**

Yes. A listing captioned "the audit IAM grant" was pulled by line number and,
after an unrelated edit shifted the file, was showing SQS queue configuration
instead. The build now warns on line-number includes and the anchor-based
selector replaced them.

<!-- pagebreak -->

# 19. Advanced Questions: Design Judgement

**A61. What would you do differently if you started again?**

Generate the CloudFormation table resources from the same Python schema
definitions the local bootstrap uses. They are currently declared twice and can
drift. It is the clearest remaining duplication in the project.

**A62. What is the most over-engineered part?**

Arguably the three geohash precision tiers for a dataset of eight facilities.
The justification is that the *bug* it fixes is real at any size and the fan-out
numbers are real; but a reviewer would be right to note that two tiers would
serve the current data.

**A63. What is the most under-engineered part?**

Dashboard aggregates computed per request. It works at demonstration scale and
would not at real scale. It is named as future work.

**A64. Why JavaScript rather than TypeScript on the frontend?**

The specification required consistent language use and warned against partial
TypeScript adoption. Given a choice I would use TypeScript throughout —
particularly for the API client, where the response envelopes are exactly the
kind of contract types catch errors in.

**A65. Why not use a framework like FastAPI?**

The specification discourages unnecessary frameworks and names it specifically.
An API Gateway proxy integration hands you a dictionary and wants one back; a
route table and path matching is the whole requirement. Adding a framework
would add a dependency, a cold-start cost and an adapter layer for no gain.

**A66. When would you add one?**

If request validation became complex enough to want schema-driven parsing, or
if the API needed OpenAPI-driven request validation at the edge. Neither is
true here, and the OpenAPI document is generated from the router rather than
the other way round.

**A67. Why no Step Functions?**

The emergency workflow is a state machine, but a slow one driven by human
responses over hours. A scheduled dispatcher with an explicit transition table
is simpler to reason about and cheaper. The specification asks for Step
Functions only where their value justifies the complexity.

**A68. When would Step Functions win?**

If the workflow needed long waits with timers, parallel branches with joins, or
compensation logic on failure. If LifeLink added multi-party confirmation with
timeouts and rollback, that would be the point.

**A69. Defend the reservation model, and explain how it avoids double-counting stock.**

Earlier versions of this project had no reservation model, and the defence of
that position was genuine: reserving appears to need a lock across
organizations that share no transaction boundary, and stock held for someone
who never arrives is stock denied to someone who would have come.

Both objections were answered rather than abandoned.

**On the lock.** No cross-organization lock is needed, because a reservation is
scoped to **one facility** — which is also the partition key. The hold and the
pool counter that governs it live in the same DynamoDB partition, so a single
conditional `TransactWriteItems` can write the hold and test the counter
together. The guarantee is not "nobody else can try" but "only one attempt can
win", which is weaker to state and sufficient in practice.

Say the ordering out loud, because getting it backwards is the classic way to
oversell:

1. read live eligible inventory,
2. read existing holds for the same pool,
3. ask the domain whether a hold is permissible — **advisory**,
4. attempt the atomic write, which re-checks the arithmetic as a condition —
   **decisive**.

Step 3 can say yes to two callers at once. Only step 4 decides. Treating step 3
as permission to write without the condition in step 4 is the bug.

**On stock held for an absentee.** Every hold has an explicit expiry, capped at
eight hours, and expiry is processed actively rather than by TTL. A reader uses
the *effective* status, so a hold whose time has passed stops holding units
immediately — before any sweep rewrites the row.

**On double-counting.** Note how the argument changed. It used to be
*structural*: there is no counter, so there is nothing to double-count. It is
now *transactional*: there is a counter, and it can only be changed atomically.
The second is a stronger claim, because it permits the feature while keeping
the invariant. Only `PENDING` and `CONFIRMED` hold units; `FULFILLED`
deliberately does not, because those units left the shelf and must not return
to availability.

What has **not** changed: an availability alert still holds nothing, and a
provider's `ACCEPTED` on an **emergency** request is still a willingness to
proceed rather than a claim on units. Three mechanisms, three different
answers.

**A70. What did implementing reservations actually require?**

A useful question to be asked, because the earlier edition of this book
predicted it: "a first-class entity with an expiry, held against a specific
batch with a conditional write, released automatically on timeout, and visible
to the owning facility so they could override it."

That is close to what was built, with two instructive differences.

**It is held against a *pool*, not a specific batch.** Holding batch
`abc-123` would be more precise and worse: the facility could not then issue
from a different batch of the same group and component without breaking the
hold, and batches are quarantined, withdrawn and expired routinely. The hold is
against (facility, group, component) with a counter, so the facility keeps
operational freedom while the quantity stays honest.

**The hard part was not the entity.** The domain module, the table and the
transaction were straightforward. What was missed, and stayed missed through
several sprints, was the **interface**: `GET /me/reservations` had no caller
anywhere in the frontend, and the decide and fulfil endpoints had no screen at
all. The feature was complete, authorized, tested — and unreachable. A
requester could place a hold and never find it again, while it kept holding
units out of everyone else's searches: invisible to its owner, consequential
for everyone else.

The lesson generalises, and is worth offering unprompted: a deployed, tested
endpoint that nothing calls is not a finished feature. Searching the frontend
for callers of each endpoint is a cheap check that would have found this
immediately.

<!-- pagebreak -->

# 20. Scenario Questions: Inventory and Concurrency

Thirty scenario questions across Chapters 20 to 25. Each describes a situation
and asks what the system does, and why.

**S1. Two staff members deduct the last unit at the same moment.**

Both read version 7 with one unit available. Both compute a new state. The
first write commits and moves the row to version 8. The second fails its
condition — version 7 no longer matches, and `availableUnits >= 1` would also
fail — and returns 409 `CONCURRENT_MODIFICATION`. The service re-reads, finds
zero units, and the domain layer raises `INSUFFICIENT_STOCK`. The second user
is told there is no stock, which is true.

**S2. An external hospital feed sends an update that is six hours old.**

Rejected with `STALE_UPDATE_REJECTED`, naming both the source timestamp and
the current `lastUpdatedAt`. A delayed update must not overwrite newer state,
and silently applying it would move a correct figure backwards.

**S3. The same feed sends an update with no timestamp at all.**

Also rejected, and treated as stale. A system that cannot say when it read the
stock does not get to overwrite a known-newer value.

**S4. A batch's expiry date is earlier than its collection date.**

Eligibility reports `INVALID_EXPIRY_DATE`, distinct from `BATCH_EXPIRED`. That
is incoherent data rather than old stock, and conflating them would hide a
data-quality problem the facility needs to fix.

**S5. A batch has no expiry date.**

Ineligible, with `MISSING_EXPIRY_DATE`. Creation refuses outright. The
specification is explicit that missing required dates must not silently produce
eligible stock.

**S6. Staff release a quarantined batch that expired while held.**

It transitions to `EXPIRED`, not `AVAILABLE`. Clearing a quarantine flag must
not resurrect stock that aged out during the hold.

**S7. The expiry sweep has not run for two hours.**

Nothing is wrong. Eligibility excludes anything past its expiry regardless of
stored status, so correctness never depends on the sweep. The sweep is
bookkeeping that makes the stored status agree with reality.

**S8. A facility has never reported inventory.**

Every cell of its availability matrix reads `UNKNOWN` with no unit count. No
inventory query runs at all, because querying and finding nothing would produce
`UNAVAILABLE`, which claims something the system does not know.

**S9. A facility reports it has zero O-negative.**

`UNAVAILABLE` with an explicit zero. Different from S8, rendered differently,
and leading a user to a different action.

**S10. An automated feed updates a batch every minute and nobody checks it.**

Freshness reads Fresh; verification reads Not verified. Both badges appear
together. That pairing is the single most important presentation rule in the
system.

<!-- pagebreak -->

# 21. Scenario Questions: Camps and Donors

**S11. Two donors claim the final seat simultaneously.**

Both pass the advisory capacity check. The transaction decides: one commits the
registration and the counter increment; the other's condition
`registeredCount < capacity` fails and the whole transaction is cancelled. The
second donor gets `CAPACITY_EXCEEDED`.

**S12. A donor registers twice.**

The conditional put on `REG#<userId>` fails and returns `DUPLICATE`. The
service also pre-checks so the message is friendly, but the condition is what
makes it impossible.

**S13. A camp is cancelled after fifty people registered.**

Cancellation transitions the camp and notifies every registered donor in the
same operation, with duplicate suppression keyed per camp and user. The
response reports how many were notified against how many were registered.

**S14. A reminder was scheduled for a camp that has since been cancelled.**

Not sent. The sweep re-checks camp status, registration status, notification
preference, consent, prior sends and schedule validity at send time, not at
schedule time.

**S15. The reminder job runs five hours late.**

Nothing is sent for that window. The schedule-drift tolerance refuses to emit
"starts in 2 hours" about something that started three hours ago.

**S16. A camp organizer donates at their own camp and tries to verify it.**

Refused with `SELF_VERIFICATION_FORBIDDEN`. They hold the permission; the
service checks `verifier_id != donor_id` independently of the permission
matrix. There is a test that grants the donor the staff role specifically to
prove this.

**S17. A donation verification event is delivered twice.**

The first commits the status change and the ledger entry. The second finds the
donation already `VERIFIED` and raises `INVALID_STATE_TRANSITION`; even if it
somehow reached the transaction, the ledger row's `attribute_not_exists`
condition would fail.

**S18. A donor's impact score disagrees with their ledger.**

The ledger wins. The score is always derived by summing ledger entries, so
recalculation is a read rather than a repair.

**S19. Staff try to record a donation for someone who never checked in.**

Refused with `ATTENDANCE_REQUIRED`. The four states are sequential, and each
step requires the previous one.

**S20. A donor who donated three weeks ago registers again.**

Registration succeeds — LifeLink does not block it — and the response carries
interval advice saying only twenty-one days have passed against a usual minimum
of ninety, and that they should speak to camp staff. The system reports elapsed
time; it does not assess fitness to donate.

<!-- pagebreak -->

# 22. Scenario Questions: Emergency Coordination

**S21. A hospital is suspended between raising a request and certifying it.**

Certification is refused with the organization status named. Verification is
re-checked at the moment of certification rather than cached from when the
request was created.

**S22. A hospital is suspended while its request is being matched.**

The dispatcher checks the requesting organization's status, halts matching,
and records a `MATCHING_HALTED_ORG_SUSPENDED` event against the request.

```diagram
type: flow
title: What aging changes and what it does not
node cert Hospital certifies clinical priority P3 style=domain
node store Stored in clinicalPriority immutable by the scheduler style=data
node wait Request waits sixty minutes style=external
node age Scheduler recomputes effectivePriority to P1 style=aws
node order Dispatched ahead of newer work style=domain
node same clinicalPriority is still P3 and is shown as such style=domain
```

*Figure 22.1. Aging moves dispatch order only. The clinical judgement is
untouched.*

**S23. A P3 request has been waiting an hour while P1 traffic continues.**

Aging has promoted its *effective* priority to the top band — one band per
fifteen minutes. Its *clinical* priority is still P3 and is unchanged. The
tracking page states both and explains that only the scheduling order moved.

**S24. Two providers each accept, each offering four units, for a request
needing four.**

Both offers are recorded in full. The tally reports two accepted and eight
units offered. Nothing is netted, because they may be describing the same
physical units, and nothing is reserved. The interface says so explicitly.

**S25. A provider accepts, but the stock has gone.**

The acceptance is refused. Stock is revalidated before an acceptance is
recorded, and the error names `STOCK_REVALIDATION_FAILED` with the current
eligible count.

**S26. A provider responds twice.**

The second fails the condition requiring the response row to still be
`AWAITING_RESPONSE`, and surfaces as a concurrency conflict rather than being
silently accepted.

**S27. An organization that was never notified tries to respond.**

Refused with `PROVIDER_NOT_NOTIFIED`. The placeholder row created at
notification time is what the submission conditions on, so a provider with no
row cannot respond at all.

**S28. A provider responds after the request was cancelled.**

Refused, because responses are rejected for requests in a terminal state. The
transition table has no edge out of `CANCELLED`.

**S29. The compatibility table has no entry for the requested combination.**

No candidates are returned, a `NO_COMPATIBILITY_REFERENCE` event is recorded,
and the response explains that no match was attempted — deliberately, because
the system does not infer compatibility. The rules version and review status
are included.

**S30. An O-negative patient needs red cells and the only nearby stock is A+.**

No match. O-negative recipients may receive only O-negative red cells. The
matching engine queries only compatible donor groups, so the A+ stock is never
considered, and there is a test asserting exactly this.

<!-- pagebreak -->

# 23. Ten Debugging Exercises

Each exercise gives a symptom. Work out the cause before reading on.

**D1. Every write to one table fails with `ValidationException` and no useful
detail.**

*Cause.* An expression attribute value is declared but not referenced by the
expression — or referenced but not declared. DynamoDB rejects the whole request
and does not name the placeholder.

*How to find it.* Compare the placeholders in the update expression with the
keys of `ExpressionAttributeValues`. In this project a script was written to
scan every repository method for the mismatch, which found three more
instances.

*Underlying bug here.* `None` values were being stripped from expression values
by a serialiser intended for items, where dropping null is correct.

**D2. A concurrent update returns "a record with this identity already exists".**

*Cause.* The condition failure is being translated to the wrong error. A
version check and a uniqueness check both raise
`ConditionalCheckFailedException`, and the code assumed the latter.

*Why it matters.* The retry path catches `ConcurrentModificationError`, so it
never engaged, and the user was told something untrue.

*Fix.* An explicit parameter saying what a condition failure means on each
call site.

**D3. A facility twenty-six kilometres away never appears in a thirty-kilometre
search.**

*Cause.* The geohash query covers only the centre cell and its eight
neighbours, which spans less than thirty kilometres at that precision.

*How to find it.* Seed data with known distances and assert against them. The
symptom is silence, so nothing surfaces without an expectation to violate.

**D4. After fixing D3, searches become very slow.**

*Cause.* Covering the full bounding box at the same precision produced 2,107
cell queries for a hundred-kilometre radius.

*Fix.* A coarser precision tier for large radii, boundaries retuned by
measurement, and a test asserting a bounded query count.

**D5. Camp reminders never arrive, but every reminder unit test passes.**

*Cause.* The sweep queries an index the camp was never written into. The
decision function is correct; the camp is not in the result set.

*Lesson.* Testing the decision is not testing the query that feeds it.

**D6. A component re-renders in an infinite loop.**

*Cause.* `setState` called during render rather than in an effect. The state
change re-renders, the condition still holds, and it sets state again.

*Fix.* Move it into `useEffect` with the right dependencies.

**D7. A search shows stale results after the user changes a filter.**

*Cause.* An earlier slow request resolved after a later fast one and
overwrote it.

*Fix.* An `AbortController` per request, cancelled when dependencies change.

**D8. The PDF build produces malformed output with unbalanced tags.**

*Cause.* Successive regex substitutions, where a later pass matches markup
inserted by an earlier one. A colour code like `'#7a0f1d'` looks exactly like a
string literal.

*Fix.* A single tokenising pass instead of chained substitutions.

**D9. A code listing in the documentation shows the wrong code entirely.**

*Cause.* The include was by line number, and an unrelated edit above the range
shifted it.

*Fix.* Anchor-based selectors that locate content by text, plus a build warning
on any remaining line-number include.

**D10. `import platform` resolves to the application package and breaks boto3.**

*Cause.* A package named `platform` on `sys.path` shadows the standard library
module that botocore imports.

*Fix.* Rename. The lesson is to check a package name against the standard
library before anything depends on it.

<!-- pagebreak -->

# 24. Ten Architecture Trade-off Discussions

Each is a decision where the alternative was genuinely defensible.

**T1. Eleven tables versus one.** Query efficiency against IAM-enforceable
isolation. Chose isolation; pay two calls for cross-domain reads.

**T2. Application dispatcher versus priority queues.** Simplicity against
correctness. Three queues do not produce priority ordering, so the apparently
simpler option does not actually work.

**T3. One Lambda versus fifty.** IAM granularity against cold starts and
concurrency. At a ceiling of ten, fifty functions would be harmful.

**T4. Optimistic concurrency versus atomic counters.** Simplicity against
expressiveness. A counter cannot say "never below zero" and loses the audit
pre-image.

**T5. Transactional outbox versus write-then-publish.** Cost against
durability. Double writes on event paths, in exchange for events that cannot
be lost.

**T6. Compatibility as data versus code.** Indirection against reviewability.
Swapping in a clinically reviewed table becomes a data change with a version
bump.

**T7. Facility-scoped reservations versus none at all.** Holding real supply
against the risk of holding it for someone who never arrives. Resolved by
scoping a hold to one facility — so no distributed lock is needed — and by
capping and actively expiring every hold.

**T8. HTTP API versus REST API.** Features against cost and latency. Nothing
in LifeLink needs a REST-only feature.

**T9. Server-side authorization versus a gateway authorizer.** One database
read per request against the ability to check account status and ownership.

**T10. moto versus DynamoDB Local.** Fidelity against availability. The Java
archive could not be downloaded; moto needs no download and the application
code is identical either way.

<!-- pagebreak -->

# 25. Twenty-Five Viva Questions

Short questions with short answers, of the kind asked rapidly in an oral
examination.

| # | Question | Answer |
|---|---|---|
| V1 | How many blood groups does the system support? | Eight |
| V2 | How many components? | Four |
| V3 | What is the Fresh threshold? | Six hours since update |
| V4 | What makes stock ineligible? | Expired, quarantined, withdrawn, zero units, or missing/invalid expiry |
| V5 | Who may certify clinical priority? | Hospital authorizer or hospital admin only |
| V6 | What is the default notification radius? | 10 km, extensible to 20 km |
| V7 | Does the radius limit camp search? | No. It limits notifications only |
| V8 | Points per verified donation? | 100 |
| V9 | Milestone thresholds? | 1, 3, 5, 10 verified donations |
| V10 | Can a donor verify their own donation? | No, enforced in the service layer |
| V11 | Which database? | DynamoDB, 12 tables |
| V12 | How many secondary indexes? | 24 |
| V13 | How many API routes? | 58 |
| V14 | How many permissions? | 39 across 10 roles |
| V15 | Which region? | ap-southeast-2 |
| V16 | Lambda runtime? | python3.14 on arm64 |
| V17 | Lambda concurrency limit on this account? | 10 |
| V18 | Why no reserved concurrency? | It subtracts from a pool of ten |
| V19 | How is a lost update prevented? | Conditional write on a version attribute |
| V20 | How is a camp prevented from oversubscribing? | A two-item DynamoDB transaction |
| V21 | What is the outbox pattern for? | Writing a domain change and its event atomically |
| V22 | What delivery guarantee does SQS give? | At least once |
| V23 | How many alarms are defined? | 8 |
| V24 | Is SMS implemented? | No. Blocked by SCP and account plan; it raises `CHANNEL_UNAVAILABLE` |
| V25 | Has it been deployed? | No. The template is validated only |

*Table 25.1. Rapid-fire viva questions.*

<!-- pagebreak -->

# 26. Mock Interview Round One: Backend Engineer

A forty-five minute round. Interviewer questions in bold, suggested answers
after, with notes on what is being assessed.

**"Walk me through your project in two minutes."**

Use the Chapter 2 answer. *Assessing: can you scope an explanation to the time
given.*

**"You said you use DynamoDB. Why not Postgres?"**

The access patterns were known in advance and are all key lookups. DynamoDB
gives predictable latency without capacity planning and costs nothing at rest.
Postgres would mean an RDS instance billed hourly whether or not anyone uses
it, plus patching and connection management from Lambda, which is its own
problem.

That said, if the application needed ad-hoc reporting queries, Postgres would
win easily. DynamoDB is the right answer when you know the questions in
advance and the wrong answer when you do not.

*Assessing: do you understand the trade-off, or did you pick the fashionable
option.*

**"Show me how you prevent two people taking the last unit of blood."**

Every batch carries a version. The write is conditional on that version being
unchanged and, for a deduction, on there being enough units. Two readers both
see version 7; the first write commits and moves it to 8; the second fails its
condition and returns 409. The service re-reads, recomputes from current state
and retries up to three times.

The re-read matters. Resubmitting the same computed change would fail
identically forever.

*Assessing: do you know what optimistic concurrency actually requires.*

**"What happens if the Lambda dies after the write but before publishing the
event?"**

It cannot, because the event is written in the same transaction as the domain
change. A DynamoDB stream picks up the outbox row afterwards. If the publisher
dies, the row stays pending and a reconciliation alarm surfaces it. The worst
case is publishing twice, which consumers absorb because they claim the event
id before doing anything.

*Assessing: have you thought about partial failure, or only the happy path.*

**"Your consumers are idempotent. What if the claim write succeeds but the
work fails?"**

The claim sits `IN_PROGRESS`. A later attempt within five minutes gets
`REQUEST_IN_PROGRESS`; after that the claim is considered stale and can be
retaken, because a crashed attempt must not block its own retry for the full
24-hour TTL.

*Assessing: depth. Most candidates stop at "we use an idempotency key".*

**"Tell me about a bug you found."**

Use the geohash story. *Assessing: do you test, and do you understand your own
failures.*

**"How would you add a reservation feature?"**

A reservation becomes a first-class entity with an expiry, held against a
specific batch with a conditional write so two reservations cannot claim the
same units, released automatically on timeout, and visible to the owning
facility so they can override it.

I deliberately did not build it, because holding stock for someone who never
arrives denies it to someone who would have come, and because reserving across
organizations that share no transaction boundary is a distributed locking
problem. If it were required I would want the expiry short and the override
prominent.

*Assessing: can you design something you have not built, and do you know why
you did not build it.*

<!-- pagebreak -->

# 27. Mock Interview Round Two: Cloud and Systems

**"Draw your architecture."**

Browser to CloudFront for static assets and directly to API Gateway for the
API. One Lambda behind the API handling all 58 routes.
DynamoDB with 12 tables. SQS with dead-letter queues for
asynchronous work, fed by a transactional outbox on a DynamoDB stream. Cognito
for identity. Amazon Location for maps and routing.

*Note: draw it, do not list it. An interviewer watching you place boxes learns
more than from a list.*

**"Why is the API not behind CloudFront?"**

Because caching blood availability would undermine the product. The entire
design turns on telling users how fresh a figure is, and a cache layer would
make that describe the cache rather than the facility.

**"Your Lambda concurrency limit is ten. Is that realistic?"**

It is the actual limit on the account, measured rather than assumed. It is not
realistic for production, and raising it is a quota request rather than a code
change. What it did was force explicit bounds everywhere — no reserved
concurrency, capped consumer parallelism, throttling treated as expected — and
rule out a per-priority consumer design that was independently wrong.

*Assessing: do you distinguish a constraint from a design, and can you say what
would change without it.*

**"Walk me through what happens when a message fails five times."**

It moves to a dead-letter queue with fourteen-day retention and an alarm fires
within five minutes. The runbook says to read a sample, take the correlation
id, query the five failures, and classify as poison message or dependency
failure. Poison messages get deleted and raise a defect for the validation gap.
Dependency failures get fixed, then redriven. Never redrive before diagnosis.

**"How do you know your system is healthy?"**

8 alarms, each mapped to a condition worth waking someone
for. The one I would name is dispatcher failure: if it stops, emergency
requests silently stop being matched while everything else looks fine, so that
handler re-raises on error specifically to make the alarm fire.

**"What is your disaster recovery story?"**

Point-in-time recovery with a 35-day window, versioned S3, and infrastructure
in version control. Within-region only, because the account cannot do
cross-region replication. And the RPO and RTO figures are design assumptions,
not measurements — the system is deployed, but **no restore rehearsal has ever
been run**. I would not claim a tested DR capability.

*Assessing: honesty. The temptation is to quote numbers.*

**"What does it cost?"**

About $0.40 a month fixed — a Secrets Manager secret, with no
customer-managed KMS key — and with
everything else inside free tiers at demonstration volume. The two items that
scale are map tiles and log ingestion. I would not say the application is free
to run.

<!-- pagebreak -->

# 28. Mock Interview Round Three: Senior and Design

**"Your system shows blood availability. What is the worst thing it could get
wrong?"**

Showing stock that is not there in a way the user trusts. There are three
variants and the design addresses each.

Showing expired or quarantined stock as available — prevented by eligibility
being a hard filter applied before ranking, and by the index sort key excluding
ineligible rows from the read entirely.

Showing a stale figure as if it were current — prevented by freshness
labelling, and by showing verification separately so a fresh-but-unverified
figure is visibly that.

Showing zero when the truth is unknown — prevented by a distinct `UNKNOWN`
state carried end to end. That one is subtle: it sends a user away from supply
that may exist.

*Assessing: can you reason about harm rather than about features.*

**"Suppose a facility's feed is systematically wrong — it reports units it does
not have. What does your design do?"**

Nothing automatic, and that is a gap. The system records freshness and whether
a human verified, but it does not detect a feed that is consistently
optimistic. I would add reconciliation: compare reported figures against
observed outcomes — accepted requests that then failed at collection — and
degrade a facility's verification standing or flag it for review.

That is a real limitation rather than something I would claim is handled.

*Assessing: will you concede a gap, and can you design the fix on your feet.*

**"Your matching engine uses a compatibility table you say is not clinically
reviewed. Is that responsible?"**

It is responsible *because* it says so. The alternative — shipping the same
table without the label — is what would not be. The loader refuses to start
without a review status, every response carries the version and the status, and
the interface repeats the disclaimer. The table cannot be mistaken for a
reviewed one.

What would make it clinically usable is a reviewed reference, which is a
process step rather than an engineering one, and it is the first item on the
future-work list.

**"Design the next version. What changes?"**

Three things in order of value. A reviewed compatibility reference, because
that is the one gap about safety rather than engineering. A materialised read
model for dashboard aggregates, which is the clearest scaling limit. And
generating the CloudFormation table resources from the same schema definitions
the local bootstrap uses, because they are currently declared twice.

I would also want a concurrency increase and a genuine load test, since at a
ceiling of ten any load test measures the ceiling.

**"What would you tell the next engineer on day one?"**

Read the architecture decision records first — seventeen of them, each with the
alternative that was rejected. Then read the domain layer, which is pure
functions and needs no AWS knowledge. Then read the tests, which are the
executable version of the rules.

And: time is always a parameter, errors return reasons rather than booleans,
and a large share of the test suite asserts what the system refuses to do. Those
three habits explain most of the code's shape.

<!-- pagebreak -->

# 29. Concepts: Idempotency

**What it means.** An operation that can be applied many times with the same
effect as applying it once.

**Why distributed systems need it.** Delivery is at-least-once. The
acknowledgement can be lost, so the sender must redeliver, so the receiver must
tolerate it.

**How LifeLink implements it.** A conditional put on a dedicated table keyed on
the operation's identity — a client-supplied header for REST calls, the event
id for queue messages. Three outcomes: fresh claim proceeds, completed claim
returns the stored result, in-progress claim is rejected unless stale.

**The subtlety.** Storing the *result* matters. Returning "already done"
without the original result forces the client to guess what happened.

**Where it is not enough.** Idempotency makes retries safe; it does not make
operations commutative. Two different operations on the same resource still
need concurrency control, which is what the version check provides.

<!-- pagebreak -->

# 30. Concepts: Optimistic Concurrency

**What it means.** Assume conflicts are rare. Read a version, compute, write
conditionally on the version being unchanged. On conflict, re-read and retry.

**Versus pessimistic locking.** A lock serialises access and guarantees
progress for the holder, at the cost of holding a resource and needing
timeouts and deadlock handling. DynamoDB offers no lock primitive, and
emulating one introduces failure modes worse than the problem.

**When it fails.** Under high contention on a single item, most attempts fail
and retry traffic dominates. The fix is usually a different data model: if one
item is contended, the granularity is probably wrong.

**The implementation detail people miss.** The retry must re-read and
recompute. Resubmitting the stale decision fails the same condition every time.

**In LifeLink.** A `version` integer on every batch, incremented on each write,
with the write conditional on the expected value and bounded retry in the
service.

<!-- pagebreak -->

# 31. Concepts: Eventual Consistency

**What it means.** A read may not reflect the most recent write, but will
eventually.

**Where it appears here.** DynamoDB global secondary indexes, always. There is
no consistent-read option for a GSI.

**Three strategies.** Ignore it where staleness is harmless — a facility search
missing a batch written fifty milliseconds ago is fine. Use a strongly
consistent base-table read where a decision depends on the latest value — the
re-read after a failed conditional write. Let idempotency absorb it where it
causes duplicate work — the dispatcher seeing a request it already handled.

**The anti-pattern.** Writing then immediately reading from an index and
assuming the write is visible. It usually works in testing, where volume is
low, and fails in production.

<!-- pagebreak -->

# 32. Concepts: The Dual-Write Problem

**What it is.** Updating two systems that cannot participate in one
transaction — a database and a message broker — with no way to make both
happen or neither.

**Why it matters.** The failure is silent. A crash between the two leaves the
data changed and the event missing, with no error anywhere.

**Solutions.** Two-phase commit, which brokers generally do not support and
which introduces a coordinator. Change data capture straight off the database,
which couples the event contract to the storage schema. Or the transactional
outbox, which writes the event into the database in the same transaction and
relays it asynchronously.

**What LifeLink chose, and why.** The outbox. Change data capture would mean a
column rename becomes a breaking change for every consumer; the outbox lets the
event shape be designed and versioned deliberately.

<!-- pagebreak -->

# 33. Concepts: Geospatial Indexing

**The problem.** Databases index one dimension well. Location is two.

**Geohash.** Interleave the bits of latitude and longitude and base-32 encode
them. A shared prefix means geographic proximity, so a prefix query becomes a
proximity query on an ordinary index.

**The two mistakes.** Querying only the cell containing the point, which misses
anything just across a grid line. And using one precision for every radius,
which either floods the query planner or reads far too many candidates.

**What LifeLink does.** Three precisions, chosen by radius; cells covering the
whole bounding box of the search circle; cells whose nearest corner is outside
the radius discarded; then exact Haversine filtering.

**Alternatives.** PostGIS with an R-tree if you have Postgres. S2 cells, which
handle polar distortion better than geohash. Neither is available or necessary
on DynamoDB at this scale.

<!-- pagebreak -->

# 34. Concepts: Least Privilege

**What it means.** Grant exactly the permissions required, and no more.

**Why it is usually done badly.** Because the broad grant works and the narrow
one requires knowing precisely what the code does. The temptation is one role
for everything.

**What it buys when done properly.** Boundaries the platform enforces. In
LifeLink the notification worker has no grant for the inventory table, so code
that reaches for it fails rather than quietly working.

**The clearest example.** The audit table is granted `PutItem` and `Query` and
nothing else, so "audit records cannot be modified" is a property of the
deployment rather than a promise in a document.

**Its limit.** It is resistance, not immutability. An account administrator can
still change things, and the documentation says so.

<!-- pagebreak -->

# 35. Concepts: Observability

**Three pillars, and what each answers.** Logs answer "what happened in this
request". Metrics answer "how is the system behaving overall". Traces answer
"where did the time go".

**Correlation is what makes them useful together.** One identifier generated at
the browser, propagated into every log line, audit record, outbox event and
queue message, so one query retrieves a user action and everything it caused.

**Structured over free text.** `event: "inventory.conflict.retry"` is
queryable and survives rewording. "Retrying because of conflict" does not.

**Redaction belongs in the formatter.** Relying on each caller to remember not
to log an email address is a plan that fails once.

**Alarms must be actionable.** An alarm nobody can act on gets ignored, and
then the ones that matter get ignored too. Every LifeLink alarm maps to a
runbook step.

<!-- pagebreak -->

# 36. Concepts: Failing Closed

**What it means.** When the system cannot determine the safe answer, it refuses
rather than guesses.

**Four instances in LifeLink.**

A batch with no expiry date is ineligible, not assumed fresh.

A compatibility combination absent from the reference returns `UNKNOWN`, and
`compatible_donor_groups` returns an empty tuple rather than every group.

An external update with no source timestamp is rejected as stale.

A facility that has reported nothing is `UNKNOWN`, never zero.

**The cost.** Each refusal is an occasion where the system could have been
helpful and was not. A batch with a missing expiry that is genuinely fine is
hidden.

**Why it is still right here.** The asymmetry of harm. Hiding usable stock
costs a phone call. Showing unusable stock as available costs a journey during
an emergency, and potentially more.

<!-- pagebreak -->

# 37. Concepts: Honest Interfaces

**The principle.** An interface should not imply a confidence the system does
not have.

**Three applications.**

*Unknown versus zero.* Different states, different rendering, different user
action.

*Updated versus verified.* Two badges, always together, because one without
the other misleads.

*Offer versus reservation.* An accepted response is willingness to proceed.
The word "reserved" never appears, the tally is never presented as secured
supply, and the interface says explicitly that offers are not added together.

**Where this is hardest.** At the moment of greatest user relief — an alert
firing to say stock is available two kilometres away. That is exactly when a
user assumes something has been set aside, and exactly where the notice is
repeated.

<!-- pagebreak -->

# 38. Code Walkthrough Exercises

Six exercises. Read the named file and answer without running anything.

**W1.** `backend/src/domain/eligibility.py` — why does the function return a
tuple of reasons rather than a boolean, and what would break if it returned a
boolean?

**W2.** `backend/src/domain/geo.py`, `search_cells` — what property does
`_cell_intersects_circle` preserve, and why is using the *nearest* corner
essential rather than the centre?

**W3.** `backend/src/repositories/dynamo.py` — explain why `to_dynamo` and
`to_expression_values` must differ, and what fails if you use the first for
expression values.

**W4.** `backend/src/appcore/auth.py`, `requires` — reorder the checks so that
the permission check comes before the account-status check. What user-visible
behaviour changes?

**W5.** `backend/src/domain/emergency.py`,
`compute_effective_priority` — what would break if this function wrote to
`clinical_priority` instead of returning a value?

**W6.** `backend/src/repositories/camp_repo.py`,
`register_atomically` — why is the capacity condition inside the transaction
rather than checked beforehand, given that the service already checks it?

<!-- pagebreak -->

# 39. Architecture Defence Questions

Questions designed to make you justify a decision under pressure.

**"Single-table design is the recommended DynamoDB pattern. You ignored it."**

Within a bounded context I did use it — a camp's metadata, registrations and
staff share a partition. Across contexts I did not, because the recommendation
optimises for query efficiency and I was optimising for enforceable isolation.
With separate tables, "this worker must not touch inventory" is an IAM policy.
With one table it is a convention. I would make the same call again, and I can
state what it costs: cross-domain reads take two calls.

**"Your dispatcher is a single point of failure."**

It is. It is also alarmed, idempotent, and deliberately re-raises on error so
the alarm fires. The alternative topology — per-priority consumers — does not
actually deliver priority ordering, so it trades a visible single point of
failure for an invisible correctness bug. If availability mattered more I would
shard the dispatcher by region with a coordinator.

**"Sixty seconds of scheduling latency in an emergency system is too slow."**

For the subsequent steps — a provider reading a notification, checking a
shelf, telephoning back — sixty seconds is not the bottleneck. A P1 request
also triggers an immediate out-of-band dispatch rather than waiting for the
tick. If the workflow became machine-to-machine the schedule would need to go.

**"Your reservations hold stock for people who may never turn up."**

They can, for at most the length of the hold. A hold is capped at ten units,
one per person per facility, group and component, and it expires — two hours
by default, eight at most — with expiry processed by a sweep rather than left
to DynamoDB TTL, so units return to availability promptly. The facility can
also decline, with a reason the requester sees.

No distributed lock is involved: a hold is scoped to one facility, which is
the partition key, so one conditional transaction writes the hold and tests
the counter together. And a hold is still not clinical approval — the API says
so with every reservation. See §52.3 for the long version.

**"Why should I believe your test numbers?"**

Because they are produced by running the suites during the documentation build
rather than typed in. The validation report records what was measured and when.
If a suite fails, the figure in the book says so.

<!-- pagebreak -->

# 40. Glossary and Revision Sheet

| Term | Meaning in LifeLink |
|---|---|
| Batch | One stock record with its own expiry, status and audit history |
| Eligible | Operationally usable: available, positive units, valid future expiry |
| Freshness | How recently the figure was updated: Fresh, Aging, Stale, Outdated |
| Verification | Whether a human independently confirmed the figure |
| UNKNOWN | Nothing reported — distinct from zero |
| Clinical priority | Hospital-certified urgency; P1, P2, P3 |
| Effective priority | Scheduler-owned dispatch order; never a clinical statement |
| Priority aging | Raising effective priority with waiting time to prevent starvation |
| Offer | A provider's willingness to proceed; not a reservation |
| Outbox | A table row written with a domain change and relayed as an event |
| Idempotency claim | A conditional put making a repeated operation a no-op |
| Geohash | Base-32 encoding of coordinates where a shared prefix means proximity |
| Correlation id | One identifier linking a request to everything it caused |
| Demo marker | `demoData`, `dataSource`, `environment` on every synthetic record |

*Table 40.1. Glossary.*

## 40.1 Numbers worth remembering

| Quantity | Value |
|---|---|
| Blood groups / components | 8 / 4 |
| Freshness thresholds | 6 / 24 / 48 hours |
| Points per verified donation | 100 |
| Milestones | 1, 3, 5, 10 |
| Default notification radius | 10 km, extensible to 20 |
| DynamoDB tables / indexes | 12 / 24 |
| API routes | 58 |
| Permissions / roles | 39 / 10 |
| Backend tests | 657 |
| All tests, backend plus frontend | 951 |
| CloudFormation resources / alarms | 59 / 8 |
| Lambda concurrency ceiling | 10 |
| Region | ap-southeast-2 |

*Table 40.2. Figures to have at hand.*

## 40.2 The five sentences worth memorising

1. "Freshness and verification are different things, and the system shows
   both."
2. "Not reported is different from zero, and the system shows the difference."
3. "Nothing is ever reserved, so there is no counter to double-count."
4. "Clinical priority is certified by a person; the scheduler writes a
   different field."
5. "Where the system cannot know, it says so rather than guessing."

Those five cover most of what distinguishes this project, and each one opens
into a detailed answer if an interviewer pulls on it.

## 40.3 Final advice

Lead with the problem. Name one decision you are proud of and one you would
change. Volunteer a bug — it is the single most credible thing you can do.
And when you do not know, say so: every chapter of these three books contains
sentences admitting what was not tested, not deployed or not available, and
that habit reads as competence rather than weakness.

<!-- pagebreak -->

# 41. System Design: Design LifeLink From Scratch

A common interview format: "design a blood availability platform." Forty-five
minutes, a whiteboard. This chapter is the answer worked through properly,
using LifeLink's actual decisions as the reference.

## 41.1 Minutes 0–5: scope before architecture

Resist drawing boxes. Ask questions.

**"Who are the users?"** Public searchers, donors, blood bank staff, hospital
clinicians, camp organisers, administrators. Six user classes with genuinely
different needs is a strong hint that role-based access control will be
central rather than incidental.

**"What is the read-to-write ratio?"** Overwhelmingly read. Thousands of
searches for every stock update. That pushes toward denormalised,
index-optimised storage and away from write-optimised designs.

**"How fresh must data be?"** This is the question that shapes everything. The
answer is not "as fresh as possible" but "accurately described". A six-hour-old
figure is usable if the user knows it is six hours old.

**"What is the consistency requirement?"** Strong for stock mutations, eventual
for browsing. Two people must not take the same last unit; a search missing a
batch written fifty milliseconds ago is harmless.

**"What must the system never do?"** Reserve blood it cannot hold, decide
clinical urgency, or present unknown as zero. Establishing the non-goals early
prevents a design that quietly assumes them.

## 41.2 Minutes 5–12: the data model

Start here, not with services. In a read-heavy system the data model determines
the architecture.

```diagram
type: layered
title: Entities and their ownership
layer Identity
node org Organizations users memberships style=domain
layer Supply
node fac Facilities directory and geo index style=domain
node inv Inventory batches and audit style=domain
layer Demand
node alert Availability alerts style=domain
node em Emergency requests and responses style=domain
layer Engagement
node camp Camps registrations staff style=domain
node don Donations and impact ledger style=domain
layer Platform
node plat Audit idempotency outbox notifications style=data
edge em -> inv
edge alert -> inv
edge fac -> inv
edge camp -> don
```

*Figure 41.1. Entities grouped by ownership. The arrows are the only places two
contexts touch.*

Now enumerate the access patterns before choosing a store. The crucial ones:

| Pattern | Frequency | Shape |
|---|---|---|
| Eligible stock at a facility for a group and component | Very high | Key lookup |
| Facilities near a point | Very high | Geospatial |
| A camp with its registrations | Medium | Partition read |
| Pending emergency requests in priority order | Every minute | Sorted index |
| Alerts waiting on a group near a cell | On every stock change | Reverse index |
| Audit for a resource | Rare | Key lookup |

*Table 41.1. The patterns that drive the design.*

Every one is a key lookup given the right key. That is the argument for a
key-value store. If the list had included "all requests where units > 5 and
deadline is tomorrow and the hospital is in Punjab", it would be the argument
against.

## 41.3 Minutes 12–20: the hard parts

An interviewer is waiting for you to reach these. Reach them yourself.

**Geospatial search in a key-value store.** Geohash. Explain the prefix
property, then immediately explain the neighbour problem, because that is the
part that shows you have implemented one rather than read about one.

**Concurrency on stock.** Optimistic concurrency with a version attribute and
a conditional write. Say explicitly that the retry must re-read.

**Priority with fairness.** Explain why queues do not give priority, then
aging, then the separation between clinical and effective priority. This is the
single best place to demonstrate judgement rather than knowledge.

**Events without losing them.** The dual-write problem and the outbox.

**Unknown versus zero.** Bring it up unprompted. It is a modelling decision
with a safety consequence, and most candidates never mention it.

## 41.4 Minutes 20–32: the architecture

Only now draw boxes, and derive each from something already said.

| Component | Derived from |
|---|---|
| CDN with static hosting | Read-heavy, global-ish, cacheable assets |
| Serverless compute | Bursty, mostly idle, no long-running process |
| Key-value store with secondary indexes | The access-pattern table |
| Managed identity provider | Six user classes, MFA, no password handling |
| Queue with dead letters | Asynchronous follow-up must not be lost |
| Scheduled worker | Priority dispatch and sweeps |
| Managed location service | Tiles, geocoding, routing from one provider |

*Table 41.2. Each component justified by an earlier requirement.*

## 41.5 Minutes 32–40: failure and scale

**What happens when the routing provider fails?** The facility list survives
and the response says directions are unavailable. Never substitute
straight-line distance for road distance.

**What happens when a queue consumer fails repeatedly?** Dead-letter queue,
alarm, diagnose before redriving.

**What is the first thing to break under load?** Compute concurrency, then
the geospatial fan-out on large radii, then dashboard aggregates.

**How would you scale the dispatcher?** Shard by region with a coordinator, or
move to a workflow engine. Say which signal would trigger the change.

## 41.6 Minutes 40–45: what you would not build

Ending on deliberate exclusions is stronger than ending on a feature list.

No cross-organization reservation locking, and why a facility-scoped hold
avoids needing it. No cache on availability data, and why. No search cluster,
because the queries are key lookups. No workflow engine, because the state
machine is slow and human-driven.

<!-- pagebreak -->

# 42. System Design: Adjacent Problems

Interviewers often pivot to a related system. Four pivots and how LifeLink's
decisions transfer.

## 42.1 "Now design organ donation matching"

**What transfers.** Compatibility as versioned reviewed data. Authority
separation — a clinician decides, the system coordinates. Audit of every
decision. The unknown-versus-zero distinction.

**What does not.** Organs are not fungible and not storable. There is no
inventory with expiry bands; there is a waiting list with a clinical priority
score. The matching becomes an allocation algorithm with fairness and medical
urgency inputs, which is a far heavier clinical responsibility — and the right
answer is that the system should implement a published allocation policy
verbatim rather than invent one.

**The trap.** Being asked to invent the allocation rule. Decline, and explain
that the rule must come from the medical authority that owns it.

## 42.2 "Design a vaccine cold-chain tracker"

**What transfers.** Batch-level records with expiry. Freshness of telemetry
separated from verification. Quarantine as a first-class status. The audit
trail.

**What is new.** Continuous sensor telemetry rather than discrete updates,
which changes the storage shape entirely — time-series rather than
key-value — and introduces excursion detection: a batch that exceeded a
temperature threshold for longer than a tolerance must be quarantined
automatically.

**The interesting question.** Who may release a batch from an automatic
quarantine? Same answer as LifeLink's verification: a specific authorized role,
audited.

## 42.3 "Design an ambulance dispatch system"

**What transfers.** Priority with fairness and the clinical-versus-effective
separation. Geospatial search. Provider response handling.

**What breaks.** Everything about timing. LifeLink's sixty-second dispatch
schedule is acceptable because the subsequent steps are human and slow.
Ambulance dispatch is seconds-sensitive and genuinely needs reservation —
an ambulance assigned to one call must not be assigned to another.

**The honest answer.** This is where you would build the reservation model
LifeLink deliberately does not have, because the resource is exclusive and the
assignment is authoritative.

## 42.4 "Design a hospital bed availability service"

**What transfers.** Almost all of it. Beds are inventory with states, freshness
matters identically, unknown-versus-zero matters identically, and capacity
conflicts need the same conditional writes.

**What is different.** Beds have occupancy rather than expiry, and the update
source is usually a hospital information system rather than manual entry,
which raises the ingestion-reliability question: what do you do with a feed
that goes silent?

**The answer worth giving.** Degrade the freshness label and eventually mark
the facility's inventory unknown, rather than continuing to show the last
figure as though it were current. Staleness must become visible, then become
honesty about ignorance.

<!-- pagebreak -->

# 43. Reading the Code: Six Guided Walkthroughs

The exercises in Chapter 38 asked questions. These work through the answers.

## 43.1 Why eligibility returns reasons

A boolean answers "can I offer this?" A reason list additionally answers "why
not?", which three different consumers need: the interface explains to a user,
the API returns machine-readable codes, and staff fixing records see every
problem at once rather than the first.

What would break with a boolean: the dashboard could not show
"missing expiry date" against a batch, so a facility would see stock
disappear from public view with no indication why.

## 43.2 Why the nearest corner, not the centre

`_cell_intersects_circle` asks whether a cell can contain any in-range point.
Using the cell centre would reject a cell whose centre is outside the radius
but whose near edge is inside — losing facilities. Using the nearest corner
guarantees the test never excludes a cell containing an in-range point, which
makes the cell set a superset of the true result.

The property to state: the filter may include cells with no matches (wasteful
but correct) and must never exclude a cell with a match (fast but wrong).

## 43.3 Why two serialisers

`to_dynamo` drops `None` because an item attribute that is null should be
absent — absent attributes do not consume storage and `attribute_exists` checks
behave intuitively.

`to_expression_values` preserves `None` because an update expression naming
`:reason` must be supplied `:reason`. Dropping it leaves the expression
referencing an undefined placeholder, and DynamoDB rejects the whole request
with a `ValidationException` that does not say which one.

Using the first for expression values is exactly the bug that broke four code
paths in this project.

## 43.4 Reordering the authorization checks

If the permission check ran before the account-status check, a suspended
administrator performing an action they are permitted to perform would receive
`FORBIDDEN` rather than `ACCOUNT_SUSPENDED`.

Both refuse, so security is unchanged. What changes is the user's ability to
understand and resolve the problem: `FORBIDDEN` suggests asking for a
permission they already have, while `ACCOUNT_SUSPENDED` points at the actual
issue. Error messages are part of the interface.

## 43.5 If aging wrote to clinical priority

A Scheduled transfusion request waiting thirty minutes would become Critical
in the record. The audit trail would show a priority change with no certifying
actor. A clinician reviewing the request would see a clinical judgement they
did not make, attributed to the system.

The scheduler would, in effect, have practised medicine. Returning a value that
the caller stores in a separate field is what keeps a fairness mechanism from
becoming a clinical one.

## 43.6 Why the capacity condition is inside the transaction

The service's pre-check reads the count and compares it to capacity. Between
that read and the write, another request can register. Both pass the check;
both write; the camp is oversubscribed.

The condition inside the transaction is evaluated atomically with the write, so
exactly one of two simultaneous requests commits. The pre-check remains because
it produces a clear error in the common case; the transaction is what makes the
guarantee.

The general principle: a check and a write that are not atomic are not a
guarantee, no matter how close together they are.

<!-- pagebreak -->

# 44. Questions to Ask the Interviewer

An interview is bidirectional, and the questions you ask reveal as much as the
answers you give.

## 44.1 About engineering practice

**"How do you decide what gets a test?"** The answer tells you whether testing
is a policy or a habit. "Everything" is as unhelpful as "when there's time".

**"What is your most recent production incident, and what changed after?"**
Teams that answer easily have blameless postmortems. Teams that hesitate
may not.

**"Where does this team's technical debt live?"** Everyone has some. A team
that can name theirs has thought about it.

## 44.2 About the work

**"What would I be doing in the first month?"** Vagueness here is a warning.

**"How does a change reach production?"** The number of steps and how many are
manual tells you more about day-to-day life than any description of culture.

**"Who decides what gets built?"** Clarity matters more than the answer.

## 44.3 Questions that are really statements

Avoid questions designed to show off knowledge — "do you use event sourcing?"
when you do not care. Interviewers notice, and the answer teaches you nothing.

<!-- pagebreak -->

# 45. Common Mistakes in Interviews About This Project

## 45.1 Leading with the service list

"It uses Lambda, DynamoDB, Cognito, SQS…" tells an interviewer you can read a
template. Lead with the problem and let the services arrive as consequences.

## 45.2 Claiming scale

It is a demonstration system with synthetic data, deployed but never
load-tested, with a
Lambda concurrency ceiling of 10. Saying so costs
nothing and buys credibility for everything else you claim.

## 45.3 Defending a decision you have not examined

If asked "why not Postgres?" and the honest answer is "I wanted to learn
DynamoDB", say that, then give the technical argument as well. An
unexamined justification collapses under one follow-up.

## 45.4 Hiding a bug

The geohash bug is the most interesting thing in this project. Hiding it
removes the strongest evidence that you test properly, and risks the
interviewer finding it.

## 45.5 Over-claiming test coverage

951 tests passing is a real number. "Fully tested" is not, and
invites the question "what is not tested?" — to which the honest answer is
load, restore procedures, Cognito itself and accessibility beyond structure.

## 45.6 Being vague about what is not implemented

SMS is not implemented. The compatibility table is not clinically reviewed.
The repository is ahead of the deployed site, so two screens exist in the code
and not on the live URL. Each of these, stated plainly, is a point in your favour.
Each discovered by the interviewer after you implied otherwise is a point
against.

## 45.7 Saying "simply"

Nothing in a system like this is simple, and the word invites a question
designed to prove it.

<!-- pagebreak -->

# 46. Frontend Interview Concepts

Questions a frontend interviewer will ask about this project, with answers
grounded in what was actually built.

**F1. Why is there exactly one module that calls `fetch`?**

Because the things that must happen on every request — the bearer token, the
correlation id, the idempotency key, error normalisation, abort handling —
cannot be forgotten if there is only one place they can be written. Thirty
components each calling `fetch` would mean thirty opportunities to omit one.

**F2. How do you stop a slow response overwriting a fast one?**

An `AbortController` per request, cancelled when the hook's dependencies
change. Without it, a user typing in a search box generates overlapping
requests, and an earlier slow response can land after a later fast one and
replace fresher results with staler ones. The symptom is intermittent and
maddening to reproduce.

**F3. What is the difference between your route guards and your authorization?**

The guards are usability. They keep a donor from clicking into a hospital
dashboard that would fail anyway. The server enforces authorization
independently on every request, which is why the guard's refusal message says
so explicitly — a user who edits the URL learns that nothing is gained.

**F4. Why bundle freshness and verification into one component?**

Because the specification requires them shown together, and separate
components make it easy to render one. `DataQuality` takes both and renders
both. A developer reaching for the convenient option gets the correct one.

**F5. How do you handle a component that throws?**

An error boundary around each routed view, so one failing panel does not blank
the application. React requires a class component for this, which is the one
remaining reason to write one.

**F6. Describe a React bug you fixed.**

Setting state during render to adopt a browser-provided geolocation. React
re-renders, the condition still holds, it sets state again — an infinite loop.
The fix is an effect keyed on the geolocation status.

**F7. How is accessibility handled?**

Visible focus rings everywhere, a skip link, semantic headings, labelled form
fields with `aria-describedby` for hints and errors, `aria-live` on
asynchronous regions, and no status conveyed by colour alone — every badge
carries a text label and a glyph. What has *not* been done is an audit with
assistive technology, and that is in the limitations.

**F8. Why code-split the dashboards?**

They are the heaviest and least-visited screens. A public visitor searching for
blood should not download the administrator dashboard. The production build
confirms them as separate chunks.

**F9. Why is MapLibre dynamically imported?**

It is 802 KB. With no map style configured — the local default — it is never
downloaded at all, and the facility list renders instead.

**F10. How do you test a presentation rule?**

Assert it. `renders UNKNOWN as "Not reported", never as a zero count` is a test
name, and the body checks both that the correct text appears and that
`0 units` does not. A rule that matters is a rule worth pinning.

<!-- pagebreak -->

# 47. Backend, Python and Lambda

**P1. Why is there no web framework?**

API Gateway hands a Lambda a dictionary and expects one back. A route table
and path matching is the entire requirement. A framework would add a
dependency, cold-start cost and an adapter layer for no capability gained.

**P2. What makes the domain layer testable?**

It has no I/O and does not read the clock. Every function takes `now` as a
parameter. The tests pass a fixed instant and assert exact boundaries with no
patching, which is why 566 unit tests run in under a second.

**P3. How do you keep a Lambda cold start small?**

A small dependency set, one function serving the whole API so warm containers
are reused widely, and the service object graph built once per container and
cached with `functools.lru_cache` rather than rebuilt per invocation.

**P4. Why `arm64`?**

Roughly 20% cheaper per millisecond at equivalent performance, and every
dependency publishes `aarch64` wheels. There is no downside at this
dependency footprint.

**P5. Why Python 3.14 specifically?**

It matches the local interpreter exactly, which removes an entire class of
"works on my machine" failure. It is generally available with support to June
2029. Python 3.15 exists but is in public preview and explicitly outside the
Lambda SLA.

**P6. How does the same code run locally and in Lambda?**

The local server builds an API Gateway-shaped event and calls the same router
the Lambda handler calls. Only the transport differs. There is no second
application that could drift.

**P7. What Python features does this code lean on?**

`StrEnum` for domain enumerations that serialise directly. Frozen slotted
dataclasses for immutable domain values. `Protocol` for structural interfaces
so adapters need no base class. `functools.lru_cache` for the container.
Modern union syntax throughout.

**P8. Why frozen dataclasses?**

A domain value that cannot be mutated cannot be mutated accidentally by a
caller. `apply_stock_operation` returns a new batch rather than modifying the
one it was given, so the pre-image is still available for the audit record.

**P9. How do you handle configuration?**

Environment variables set by the infrastructure template, read at module
import, with local defaults. No configuration is baked into code, and
`.env.example` documents every variable with placeholder values only.

**P10. What would you change about the Python?**

Add type checking in CI. The code is annotated throughout but nothing verifies
the annotations, so they are documentation rather than a guarantee.

<!-- pagebreak -->

# 48. REST API Design

**R1. What makes an API consistent?**

Predictability. Same resource naming, same status codes, same error shape,
same pagination mechanism, same idempotency mechanism everywhere. A client
developer should be able to guess the shape of an endpoint they have not read
about.

**R2. Why one response envelope?**

So a client writes one response handler. `{ data, meta?, correlationId }` on
success and `{ error: { code, message, details? } }` on failure. Every one of
the 58 operations uses it.

**R3. Why branch on a code rather than a message?**

The message is written for a human and may be reworded at any time. The code
is contract. A client matching on message text breaks the first time someone
improves the wording.

**R4. How do you decide between 400, 403, 404 and 409?**

400 means the request is malformed. 403 means it is well-formed and refused.
404 means the resource does not exist. 409 means the request conflicts with
current state — which is the interesting one, because it tells the client that
retrying *might* work, unlike the others.

**R5. Should a 403 ever be a 404?**

Sometimes. Returning 404 for a resource the caller may not see avoids
confirming it exists. LifeLink returns 403 with
`CROSS_ORGANIZATION_DENIED` but deliberately does not name the owning
organization, which gives a useful error without disclosure.

**R6. Why cursor pagination rather than offset?**

Offset requires the database to read and discard rows, which DynamoDB cannot
do efficiently and which produces inconsistent results when the underlying
data changes between pages. A cursor encodes position directly.

**R7. What is the fingerprint in the cursor for?**

So a cursor from one query presented against a different query is rejected
rather than silently returning results from the wrong set — a bug that is
nearly impossible to notice in testing.

**R8. How does idempotency work over HTTP?**

The client sends an `Idempotency-Key` header. The server claims it with a
conditional write before doing anything. A repeat with the same key returns the
stored result instead of repeating the effect.

**R9. Who generates the key?**

The client, because only the client knows that two requests are the same
logical operation. LifeLink's frontend generates one per mounted form, so a
double-click or a retry after a network blip cannot create two records.

**R10. How do you keep documentation accurate?**

Generate it. The OpenAPI document is produced from the live route table, so it
cannot describe an endpoint that does not exist, and a `--check` mode fails if
the committed file has drifted.

<!-- pagebreak -->

# 49. JWT, Cognito and Session Design

**J1. What is in a JWT?**

A header naming the algorithm and key id, a payload of claims, and a
signature. It is signed, not encrypted — anyone can read the claims, so
nothing secret belongs in them.

**J2. Why RS256 rather than HS256?**

Asymmetric signing means the verifier needs only the public key. With HS256 the
shared secret would have to exist everywhere a token is verified, and anyone
who can verify could also mint.

**J3. What do you verify?**

Signature against the key the `kid` names, issuer, expiry, the presence of a
subject, and that `token_use` is one you accept. Skipping any of them is a
vulnerability; skipping expiry is the classic one.

**J4. Why not verify audience?**

Cognito access tokens carry `client_id` rather than `aud`. Leaving `verify_aud`
enabled rejects every valid access token, and the common "fix" is to stop
checking the client at all. LifeLink disables the generic check and verifies
`client_id` explicitly.

**J5. What is the fundamental limitation of a JWT?**

It cannot be revoked. It is valid until it expires, by construction. Any
design that needs immediate revocation must check something else.

**J6. How does LifeLink handle that?**

By treating the token as proof of identity only. Roles and account status come
from the database on every request, so suspending an account takes effect on
the next request rather than at token expiry.

**J7. What does that cost, and how is it mitigated?**

One read per request, mitigated by a short in-process cache with a
thirty-second TTL. The staleness is bounded explicitly rather than
accidentally.

**J8. Where should a browser store a token?**

Neither option is perfect. `localStorage` is readable by any script, so a
cross-site scripting flaw exposes it. An httpOnly cookie resists that but
introduces cross-site request forgery, needing `SameSite` and a token. For a
development flow LifeLink uses `localStorage` and wraps every access in
try/catch for private-browsing contexts.

**J9. What is a refresh token for?**

Obtaining a new short-lived access token without re-authenticating. It lets
access tokens be short — one hour here — which bounds the damage from a leak,
while keeping the user signed in for thirty days.

**J10. What is PKCE protecting against?**

Authorization code interception. A public client cannot keep a secret, so
without PKCE an attacker who intercepts the code could exchange it. With PKCE
the exchange requires the verifier, which never left the browser that
generated it.

<!-- pagebreak -->

# 50. Maps, Geocoding and Routing

**M1. What does MapLibre actually do?**

Renders vector tiles in a browser. It does not supply tiles, geocode an
address or calculate a route. Conflating the renderer with the data behind it
is the most common mistake in map integrations.

**M2. Why can you not use the public OpenStreetMap tile servers?**

They run on donated infrastructure for development and light use. Pointing an
application at them breaches their usage policy and makes an operational
dependency of someone else's goodwill.

**M3. How does the browser fetch tiles without a key?**

A Cognito identity pool issues temporary credentials scoped to four read-only
tile actions on one map resource. A browser holding them cannot geocode,
cannot route and cannot read any data.

**M4. Why not proxy tiles through the backend?**

Volume. Tiles are thousands of small requests per session; proxying them
through Lambda would be slow, expensive and pointless, since the tiles are not
sensitive.

**M5. Then why proxy geocoding?**

Low volume, cacheable, and exposing it client-side turns the deployment into a
free geocoding service for anyone who opens the page.

**M6. What is the difference between straight-line and road distance?**

Straight-line is the direct distance between two points. Road distance is how
far you would drive, typically 20–40% further and sometimes much more. Showing
one labelled as the other is misleading in a way that matters when someone is
deciding where to drive.

**M7. What happens when routing fails?**

The response carries `routingAvailable: false` with a reason, and the road
distance and duration stay null. The straight-line figure is shown and
explicitly labelled as not a driving distance. Substituting one for the other
would be the convenient and wrong choice.

**M8. How do you test a map?**

The rendering, barely — it is a canvas. What you test is the fallback: with no
style configured, the component renders a facility list. Because that is the
local default, the fallback is exercised constantly rather than kept as
untested emergency code.

**M9. What is attribution and why does it matter?**

Tile providers require their data sources to be credited. It is a licence
condition, not a nicety, and MapLibre's attribution control is enabled.

**M10. Would you add a second routing provider?**

Only with a reason. The specification permits one as optional. A second
provider that cannot be verified end to end adds a failure mode without adding
reliability. The interface leaves the seam open, which is the point of having
an abstraction.

<!-- pagebreak -->

# 51. Cost and Capacity Reasoning

**C1. What does this system cost to run?**

About $0.40 a month in fixed charges — a Secrets Manager
secret at $0.40 — with everything else inside free tiers at demonstration
volume. The application is not free to run, and the documentation says so.

**C2. What scales with usage?**

Map tile loads and CloudWatch Logs ingestion, in that order. Both are easy to
overlook because neither appears in a functional requirement.

**C3. How do you control log cost?**

Retention as a template parameter defaulting to 30 days, and access logs that
exclude request bodies and query strings — which also happens to be the right
privacy decision.

**C4. Why on-demand DynamoDB rather than provisioned?**

Provisioned capacity requires predicting throughput for a system with no
traffic history and charges for idle capacity. On-demand costs more per
request and nothing at rest, which is the right shape for bursty, mostly-idle
usage.

**C5. When would you switch to provisioned?**

When traffic becomes predictable enough that reserved capacity is cheaper —
typically a sustained baseline. The crossover is around 15–20% utilisation of
provisioned capacity.

**C6. What was the most expensive decision you avoided?**

An always-on compute tier. A single small container running continuously costs
more per month than this entire architecture at demonstration volume.

**C7. How does the concurrency limit affect cost?**

It caps it, incidentally. Ten concurrent executions is also a ceiling on how
much Lambda time can be consumed per second, which makes a runaway bill
difficult.

**C8. What would you measure before optimising?**

Which endpoints dominate request count, which DynamoDB indexes dominate read
capacity, and the ratio of map tile loads to searches. Optimising without those
three numbers is guessing.

**C9. Is the free tier a reasonable basis for an architecture?**

For a demonstration, yes, and the design says which figures depend on it. For
production it is not, and the cost chapter separates fixed charges from
free-tier-covered ones precisely so the distinction survives.

**C10. What is the hidden cost in this design?**

Transactions. Every event-producing write is a transaction at double the write
cost. It is a deliberate trade for durability, and naming it is better than
discovering it on a bill.

<!-- pagebreak -->

# 52. The Five Hardest Questions, Answered at Length

Some questions deserve more than a paragraph. These five are the ones most
likely to separate a good answer from a memorised one.

## 52.1 "Why is showing zero worse than showing nothing?"

Begin with the user, not the data model.

A relative is standing in a hospital corridor with a phone. They need two units
of O-negative. The application lists six nearby facilities. Beside one it says
**0 units**.

They do not call that facility. Why would they? The system told them it has
none. They call the other five, find nothing, and widen the search.

Now suppose that facility has eleven units and simply has not connected its
inventory feed. The zero was never a measurement. It was the absence of a
measurement, rendered as though it were one.

The cost of that mistake is not a cosmetic inconsistency. It is a journey not
made to a facility that had what was needed.

**The modelling consequence.** `UNKNOWN` must be a distinct state, not a null
that gets coalesced. In LifeLink it is an enum value that travels from the
aggregation function through the service, the API response and into a visually
distinct badge reading "Not reported". The aggregation function takes an
explicit `inventory_known` flag, and when it is false no inventory query runs
at all — because querying and finding nothing would produce `UNAVAILABLE`,
which is a different claim.

**Why this is hard to get right.** Every layer offers a chance to lose it. A
database `NULL` coalesced to `0` in a query. A JSON serialiser omitting a null
field so the client's `?? 0` default applies. A UI component with
`units || 0`. A ranking function that treats the state as a number. Each is a
small, reasonable-looking line of code, and any one of them destroys the
distinction.

**What to say if pushed further.** The general principle is that absence of
evidence must not be encoded as evidence of absence, and the place this is
usually lost is at a type boundary where an optional becomes a default.

## 52.2 "Your scheduler changes priority. How is that not practising medicine?"

This is the sharpest question available about this system, and the answer is a
field name.

**The problem.** Strict priority starves the bottom. A steady arrival of
Critical and Urgent requests means a Scheduled request waits indefinitely.
That is a real harm even though no individual decision was wrong. The standard
remedy is aging: raise a waiting item's priority over time.

**Why the standard remedy is dangerous here.** If the field being raised is
the clinical priority, then after thirty minutes the system has recorded that
a Scheduled request is Critical. The audit trail shows a priority change with
no certifying clinician. A doctor reviewing the request sees a clinical
judgement attributed to them that they did not make.

**The resolution.** Two fields with two owners.

`clinicalPriority` is written only by the certification endpoint, which
requires an authorized hospital role, re-checks that the hospital is currently
verified, and records the actor, their role, their organization and the
timestamp. Nothing else in the system writes it.

`effectivePriority` is written only by the scheduler and means nothing beyond
dispatch order. It is recomputed freely and carries no clinical meaning.

**How it is enforced rather than intended.** `compute_effective_priority` is a
pure function that *returns* a value. It cannot mutate anything. The caller
stores it in a different field. A test asserts that a P3 request aged to
effective P1 still reports `clinicalPriority` as P3.

**The interface obligation.** When the two differ, the tracking page says so
explicitly: the clinical priority is unchanged and only the scheduling order
has moved. A user must not infer a clinical escalation from a queue position.

**The broader principle.** When a system automates something adjacent to a
human judgement, the automated value and the human value must be different
fields. Sharing one field means the automation can silently overwrite the
judgement, and no amount of care in the code prevents a future change from
doing exactly that.

## 52.3 "Reservations hold stock for someone who may never arrive. Defend that."

Take the question seriously rather than defending. An earlier edition of this
book answered the opposite question — "you have no reservations, isn't the
system useless?" — because the system had none. It now does, and the three
objections raised then were good ones. Each was answered rather than dropped,
and walking through that is a stronger answer than either position alone.

**What was conceded then.** A user could search, find four units eleven
kilometres away, drive there, and discover they were gone. A real failure of
the user's goal.

**The three objections, and what answers them.**

*The resource is not exclusive to the requester.* A blood bank serves
walk-ins, scheduled surgeries and other hospitals, so a hold removes units
from people physically present with an immediate need. **Answer:** holds are
small and short. One request may hold at most ten units; one person may hold
once per facility, group and component; the default hold is two hours and the
maximum is eight. A facility may also decline, with a reason the requester
sees. The hold is a short-lived courtesy, not a claim on supply.

*There is no shared transaction boundary.* The requester and the facility are
different organizations with different systems, so a reservation looks like a
distributed lock — timeouts, orphan detection, and a question about who may
break it. **Answer:** no distributed lock is needed, because a hold is scoped
to **one facility**, which is the DynamoDB partition key. The hold and the
counter governing it live in the same partition, so one conditional
`TransactWriteItems` writes the hold and tests the counter together. The
guarantee is not "nobody else can try" but "only one attempt can win" — weaker
to state, and sufficient.

*The failure mode is worse: unclaimed reservations deny stock to people who
would have arrived.* The sharpest objection. **Answer:** expiry, processed
actively rather than by DynamoDB TTL. TTL deletes within roughly 48 hours on a
best-effort basis, which would be useless here, so a sweep releases holds and
every read uses the *effective* status — a hold whose time has passed stops
holding units immediately, before any row is rewritten. An unclaimed hold
costs the system the length of the hold, not the life of the record.

**What is still true.** A reservation is **not** clinical approval, not a
cross-match and not a guarantee of release. The API returns that sentence with
every reservation, and the interface renders an accepted hold as "Accepted —
units held", never "approved". An availability **alert** still holds nothing,
and a provider's response to an **emergency** request is still an offer rather
than a claim on units. Three mechanisms, three different answers to "what does
this hold?" — and conflating them is the mistake this design works hardest to
prevent.

**The honest closing, and the part worth volunteering.** The hard part was not
the entity. The domain module, the table and the transaction were
straightforward. What was missed, and stayed missed for several sprints, was
the **interface**: the endpoint listing a user's own holds had no caller
anywhere in the frontend, and the endpoints for accepting and fulfilling a
request had no screen at all. The feature was complete, authorized and tested
— and unreachable. A requester could place a hold and never find it again,
while it kept holding units out of everyone else's searches.

A deployed, tested endpoint that nothing calls is not a finished feature.
Offering that unprompted is worth more than any defence of the design.

<!-- pagebreak -->

## 52.4 "Walk me through the hardest bug and what it taught you."

The geohash coverage bug, in full.

**The symptom.** A thirty-kilometre search from Patiala returned two
facilities. A third, in Rajpura, was 25.6 kilometres away and should have
appeared. No error, no exception, no log line — just a facility that was not
in the list.

**Why it existed.** The implementation queried the geohash cell containing the
search origin plus its eight neighbours. That covers a three-by-three block of
cells. At precision 5 each cell is roughly five kilometres across, so the block
spans about fifteen kilometres. Any radius larger than that silently returned
incomplete results.

The code was not wrong in an obvious way. Neighbour queries are the standard
geohash technique, and for small radii the implementation was correct. It was
correct in exactly the cases a developer tests by hand.

**How it was found.** Integration tests against seeded data with known
coordinates. The seeder places facilities at real Punjab locations, so the
distances between them are known quantities. A test asserting that a
thirty-kilometre search from Patiala finds Rajpura failed.

That is the argument for seeding realistic data rather than `facility-1` at
`(0, 0)` and `facility-2` at `(1, 1)`. Synthetic coordinates with no real
distances between them would have passed.

**The first fix, and the problem it created.** Covering the whole bounding box
of the search circle. Correct, and a hundred-kilometre search then required
**2,107 cell queries**. A five-kilometre search at the finer precision required
195. Each cell is one indexed query. At a Lambda concurrency ceiling of
10, a single search consuming a container for that
long would be felt by every other user.

**The real fix.** A third geohash precision tier, with boundaries chosen by
measurement rather than by cell size alone. Precision 6 up to three
kilometres, 5 up to twenty, 4 beyond — producing a worst case of seventy-nine
queries at any radius. Plus a refinement: cells whose nearest corner lies
outside the search radius are discarded, because they cannot contain an
in-range point.

**What the tests now assert.** Two properties, not two examples. Coverage is
checked by walking the search circle in five-degree steps at ten different
radii and confirming every bearing's cell is in the query set. Fan-out is
bounded by a constant that the tiers keep well clear of.

**What it taught me.** Three things.

*Silent failures need expectations to reveal them.* Nothing in the system
could have alarmed on this, because from the code's point of view nothing went
wrong. Only a test that knew what the answer should be could find it.

*Fixing correctness can break performance, and the fix is not done until both
are measured.* The intermediate state — correct and unusable — would have
passed a correctness review.

*The boundary cases are the whole problem.* Every bug in this story lives at a
boundary: the edge of a geohash cell, the edge of a precision tier. The tests
that matter are the ones that walk the boundary rather than sampling the
middle.

## 52.5 "How do you know your documentation is true?"

Because it is generated from the thing it describes.

**The mechanism.** Book sources contain directives rather than transcribed
content. ````python
def freshness_label(last_updated_at: datetime | None, now: datetime) -> FreshnessLabel:
    """Map age-since-update onto a freshness band.

    A missing or future-dated timestamp yields UNKNOWN rather than a flattering
    default -- spec 3.4 forbids invalid dates silently producing eligible stock.
    """
    if last_updated_at is None:
        return FreshnessLabel.UNKNOWN
    age = hours_between(last_updated_at, now)
    if age < 0:
        # Clock skew or bad data. Refuse to label it fresh.
        return FreshnessLabel.UNKNOWN
    if age <= FRESH_MAX_HOURS:
        return FreshnessLabel.FRESH
    if age <= AGING_MAX_HOURS:
        return FreshnessLabel.AGING
    if age <= STALE_MAX_HOURS:
        return FreshnessLabel.STALE
    return FreshnessLabel.OUTDATED
````
extracts that function from that file at build time. `951`
is replaced by a number produced by running the suite during the build.
`| Method | Path | Permission |
|---|---|---|
| `GET` | `/alerts` | `alert:manage:own` |
| `POST` | `/alerts` | `alert:create` |
| `DELETE` | `/alerts/{alertId}` | `alert:manage:own` |
| `GET` | `/alerts/{alertId}` | `alert:manage:own` |` reads the live router.

**What that guarantees.** A code listing cannot drift from the code, because
it is not a copy. A test count cannot be stale, because it is measured. An
endpoint cannot be documented that does not exist, because the OpenAPI
document is generated from the route table and a `--check` mode fails on
drift.

**What it does not guarantee.** That the prose is correct. A function can be
quoted accurately beneath a paragraph that misdescribes it. The mechanism
protects against staleness, not against being wrong.

**Where it already caught something.** A listing captioned "the audit IAM
grant" was pulled by line number. An unrelated edit shifted the file, and the
listing began showing SQS queue configuration under a caption about IAM. The
build now warns on every line-number include and anchor-based selectors
replaced them.

**And where the validation caught something.** The page-count target was
being met partly by blank pages — a chapter heading forced a page break and an
explicit marker forced another. The validator reported "every page has text"
because it counted the running header and footer. Measuring only the body
frame revealed the blanks, and the honest page count was substantially lower.

**The general point.** A documentation process that can fail loudly is worth
more than one that is carefully written. These three books are built by a
command that exits non-zero if a referenced function has been renamed, a fact
cannot be measured, a page is blank, content falls outside the margins, or the
contents page numbers drift between layout passes.

<!-- pagebreak -->

# 53. Rapid Revision: One Page Per Feature

## 53.1 Feature 1 — Inventory

Batch-level records, group and component tracked separately. Eligibility
computed dynamically and failing closed. Freshness in four bands from the
update time; verification tracked independently and never implied by an
update. Optimistic concurrency with a version attribute; stock can never go
negative. External ingestion rejects stale updates. Availability alerts are a
submodule, informational only, matched through a reverse index.

**One sentence:** *The authoritative record of what stock exists, and how much
you should trust each figure.*

## 53.2 Feature 2 — Location and discovery

Geohash at three precisions, cells covering the whole search circle, exact
Haversine filtering afterwards. Eligibility filters before ranking, so no
weighting can surface expired stock. Ranking is explainable and deterministic.
Straight-line and road distance are separate fields and never conflated.
Routing failure degrades to a list with contact details.

**One sentence:** *Finding the right facility, with an honest account of
distance and data quality.*

## 53.3 Feature 3 — Camps and donors

Six camp lifecycle states with an explicit transition table. Four distinct
donor states: registered, attended, donated, verified. A donor may never
verify their own donation. Capacity enforced by transaction, not by check.
Impact credited exactly once via a ledger row keyed on the donation id.
Reminders re-check five preconditions at send time.

**One sentence:** *Turning intention into a verified donation, with each step
recorded separately.*

## 53.4 Feature 4 — Emergency coordination

Requests created with no clinical priority. Certification restricted to
authorized hospital roles and re-checked against current verification status.
Deterministic matching against a versioned compatibility reference that fails
closed on unknown. Priority scheduling with aging, writing a field the
clinical priority never shares. Provider responses are offers, revalidated
against stock, never netted into supply.

**One sentence:** *Coordinating an urgent requirement without ever making a
clinical decision.*

## 53.5 Feature 5 — Frontend

One network client. One async-state component. Badges that carry the honesty
rules into the interface. Role-aware navigation that is explicitly usability
rather than security. A map whose fallback is the default path. Accessibility
by structure: focus rings, labels, no colour-only status.

**One sentence:** *An interface that refuses to imply confidence the system
does not have.*

## 53.6 Feature 6 — Security and monitoring

One authorization decorator, five checks in a deliberate order. Roles and
account status from the database, so suspension is immediate. Organization
scoping applied centrally. An audit table the application can write but not
modify. Structured logs with automatic redaction. Eight actionable alarms,
each mapped to a runbook step.

**One sentence:** *Authorization the platform enforces, and failures that are
visible.*

## 53.7 Feature 7 — Infrastructure

One SAM template, 59 resources, validated by two tools and
deployed by none. Single region by account constraint. Least-privilege IAM per
function. Everything parameterised by environment, with production seeding
refused by three independent guards.

**One sentence:** *A reproducible deployment that has been checked but not
run.*

<!-- pagebreak -->

# 54. The Closing Argument

If you have thirty seconds at the end of an interview to say why this project
is worth taking seriously, say this.

> Most student projects demonstrate that the happy path works. This one
> demonstrates what happens when it does not.
>
> It distinguishes "no stock" from "no information", because those lead a user
> to opposite actions. It separates how recently a figure was updated from
> whether anyone checked it, because an automated feed updating every minute
> proves nothing about accuracy. It refuses to reserve blood it cannot hold,
> and says so at every point where a user might assume otherwise. It lets a
> scheduler reorder work without ever touching a clinical judgement, by making
> them different fields with different owners.
>
> It has 657 backend tests and 294 frontend
> tests, and a substantial share of them assert what the system refuses to do.
> Five real bugs were found by testing against a real datastore rather than a
> mock, and four of those failed silently.
>
> Everything it has not done is written down: the compatibility reference has
> not been clinically reviewed, SMS is not implemented, the recovery figures
> are design assumptions rather than measurements, and the repository is ahead
> of what is deployed.
>
> The thing I would want you to take away is that the hard part was not the
> AWS. It was deciding, repeatedly, what the system should refuse to claim.

<!-- pagebreak -->

# 55. Twenty More Scenario Questions

Additional scenarios covering the platform and security edge cases.

**S31. A token is valid but the user record has been deleted.**

Authentication fails with "authenticated subject has no LifeLink account". The
directory lookup returns nothing, and the authenticator refuses rather than
constructing a principal from claims.

**S32. A user's role is changed while they have the dashboard open.**

The next request uses the new role, because roles are read from the database
per request. The open page may show controls they can no longer use; clicking
one returns 403. The UI is a hint, the server is the authority.

**S33. Two administrators suspend the same organization simultaneously.**

Both succeed. The write is idempotent in effect — the status ends as
`SUSPENDED` either way — and both are audited, so the record shows two
actions rather than hiding one.

**S34. A correlation id is supplied by the client.**

It is honoured, so a client can correlate its own logs with the server's. It
is not trusted for anything else; it is a logging key, not an identity.

**S35. A request arrives with a malformed Authorization header.**

`UNAUTHENTICATED` with a message naming the expected format. A missing header
is treated as anonymous; a malformed one is an error, because the caller
clearly intended to authenticate.

**S36. A client sends the same idempotency key for two genuinely different
requests.**

The second returns the first request's stored result. That is the client's
error, and the contract is explicit: the key identifies the operation. This is
why the frontend generates one key per mounted form rather than reusing one.

**S37. The idempotency table's TTL removes a claim mid-request.**

The claim write fails its not-exists condition, the subsequent read finds
nothing, and the code treats it as a fresh claim rather than erroring. That
race is handled explicitly in the claim function.

**S38. A notification is queued for a user who then withdraws consent.**

The consumer re-checks consent at send time, not at queue time, and the
outcome records `NO_CONSENT`. A queued notification is not a committed one.

**S39. SES rejects an email because the recipient is not verified.**

The delivery result records `FAILED` with the provider's reason. Nothing
claims the message was delivered. In sandbox this is the expected outcome for
most addresses, and it is a documented limitation rather than a bug.

**S40. A log line would contain a patient reference.**

The redaction set covers key names at any depth. Patient reference is a
free-text field the user is explicitly asked not to put identifying
information in, and the form says so. That is weaker than redaction and is
worth stating: the mitigation there is interface guidance, not enforcement.

**S41. An outbox row has been pending for an hour.**

The domain data is correct — the write was transactional. Only publication is
behind. Check the publisher's logs and the stream iterator age; the event is
not lost.

**S42. An event type has no route in the publisher.**

It is logged as a warning and marked dispatched, so it does not sit pending
forever and trigger the reconciliation alarm indefinitely. The warning is the
signal that a route is missing.

**S43. A queue consumer is throttled by the concurrency ceiling.**

The message returns to the queue after its visibility timeout and is retried.
The consumer's `MaximumConcurrency` of two is what prevents a backlog from
consuming the whole pool and starving the API.

**S44. DynamoDB throttles a write.**

The SDK retries with adaptive backoff. If it still fails, the error surfaces
as `RATE_LIMITED`, which the API client classifies as retryable. An alarm
fires if throttles exceed the threshold.

**S45. The dispatcher and a manual action transition the same request.**

One wins. The transition is conditional on the current status, so the loser
fails its condition rather than overwriting.

**S46. A camp organizer tries to assign staff from another organization.**

Permitted, and deliberately: a camp may use staff from elsewhere. What is
checked is that the assigning user owns the camp and that the assigned user
exists. The assigned person then has camp-scoped permissions for that camp
only.

**S47. A camp's capacity is reduced below its current registrations.**

Existing registrations stand. New ones are refused with `CAMP_FULL`, because
the check is `registeredCount >= capacity` rather than an exact comparison.

**S48. A donor cancels their registration after checking in.**

The cancellation is conditional on the registration still being `REGISTERED`,
so it fails. Attendance has already been recorded and cannot be withdrawn by
the donor.

**S49. The frontend receives a 500 with no detail.**

By design. The error panel shows the correlation id, which is enough for an
operator to retrieve the full detail from logs. Returning the exception message
would risk disclosing internals.

**S50. Someone runs the seeder with `LIFELINK_ENV=prod`.**

It refuses and exits non-zero before touching anything, printing why.

<!-- pagebreak -->

# 56. What Makes This Project Different

A candid assessment, for use when an interviewer asks you to compare it to
other student work.

## 56.1 What is genuinely unusual

**The refusals are tested.** A large share of the test suite asserts what the
system declines to do. Most projects test the happy path.

**Unknown is a first-class state.** Nearly every system of this kind collapses
"no data" into zero at some layer. Keeping them distinct end to end required a
decision at the domain, service, API and presentation layers.

**Two priority fields.** The separation between a hospital's clinical
judgement and the scheduler's ordering is not a common pattern, and it exists
because aging a clinical priority would be a safety problem.

**The documentation is generated.** Code listings are extracted at build time;
metrics come from running the suites. A renamed function breaks the book build.

**Bugs are recorded rather than quietly fixed.** Five appear in these books
with their symptom, cause and fix, because the interesting part of a project
is usually what went wrong.

## 56.2 What is ordinary

The AWS services are the obvious ones, chosen for the obvious reasons. The
React application is conventional. The DynamoDB access patterns are textbook
once the questions are enumerated. None of that is a criticism — the right
answer is usually the ordinary one — but none of it is distinguishing either.

## 56.3 What is weaker than it looks

**Operational history is thin.** The stack is deployed, but the alarms have
never fired in anger, no restore has been rehearsed and nothing has been
load-tested. Most operational claims are still about what the template creates
rather than what has been observed.

**The compatibility reference is not reviewed.** The engineering around it is
careful; the data is not authoritative, and that is the gap that matters most.

**Load behaviour is unknown.** A concurrency ceiling of
10 makes a load test measure the ceiling, so no
throughput figure exists.

**Accessibility is structural only.** Focus management, labels and
non-colour status indicators are in place. No audit with assistive technology
has been run.

## 56.4 How to present that honestly

Lead with what is unusual. Concede what is ordinary without apologising for
it. Volunteer what is weak before being asked.

The last of those is counter-intuitive and the most effective. An interviewer
who discovers a weakness you concealed discounts everything else you claimed.
An interviewer who hears it from you first tends to believe the rest.

<!-- pagebreak -->

# 57. Final Revision Sheet

## 57.1 If you remember nothing else

| Rule | Why it exists |
|---|---|
| Unknown is not zero | They lead a user to opposite actions |
| Updated is not verified | A feed proves recency, not accuracy |
| An offer is not a reservation | Nothing is held, so nothing can double-count |
| Clinical priority is not dispatch order | A scheduler must not overrule a clinician |
| Fail closed | Hiding usable stock costs a call; showing unusable stock costs a journey |

*Table 57.1. The five rules that explain most of the design.*

## 57.2 The numbers

657 backend tests (566 unit,
91 integration), 294 frontend tests,
all passing. 58 routes,
58 documented operations.
12 tables, 24 indexes.
39 permissions, 10 roles.
59 infrastructure resources, 8 alarms.
43 backend modules, 60 frontend
modules.

## 57.3 The five bugs

| Bug | Symptom | Found by |
|---|---|---|
| Geohash neighbour-only coverage | A facility 25.6 km away never appeared | Integration test with real distances |
| Unused expression placeholders | `ValidationException` naming nothing | Integration test |
| Version conflict as `DuplicateError` | Retry path never engaged | Integration test |
| `None` stripped from expression values | Any null-setting update failed | Integration test |
| Reminder index never populated | Reminders would never fire | Writing the limitations table |

*Table 57.2. Every bug worth discussing, and what found it.*

Four of five failed silently. All five were found by something other than
reading the code.

## 57.4 The sentence to end on

> The hard part was not the AWS. It was deciding, repeatedly, what the system
> should refuse to claim.

<!-- pagebreak -->

# 58. Whiteboard Drills

Six drills to practise aloud. Time yourself; each should take five minutes.

## 58.1 Drill one: draw the read path

Draw what happens when someone searches for O-negative packed red cells within
twenty kilometres.

**What a complete answer includes.** Browser to API Gateway. Lambda resolves
the search origin. Geohash precision chosen from the radius. Cells covering
the circle queried against the facilities index. Exact Haversine filtering.
For each surviving facility, an eligible-stock query against the inventory
index. Aggregation into an availability state. Ranking. Response with
explanations.

**What most people miss.** That eligibility filtering happens before ranking,
and that a facility with no reported inventory is carried through as unknown
rather than dropped or zeroed.

## 58.2 Drill two: draw the write path with its failure branch

Draw a stock deduction including what happens when it loses a race.

**What a complete answer includes.** Read with version. Domain decides the new
state. Transaction containing the conditional write, the audit record and the
outbox event. On condition failure: re-read, recompute, retry, bounded.

**What most people miss.** That the retry recomputes rather than resubmitting,
and that the audit and event are inside the transaction rather than after it.

## 58.3 Drill three: explain the two priorities

Explain why the system has `clinicalPriority` and `effectivePriority` to
someone who thinks it is duplication.

**The shape of the answer.** Start with the problem — starvation. Introduce the
standard remedy — aging. Then show why the remedy is dangerous if it writes the
clinical field, and only then introduce the second field as the resolution.

**What most people miss.** Leading with the solution. "We have two fields" is
not an argument; "aging a clinical priority would overrule a doctor" is.

## 58.4 Drill four: the dual-write problem

Explain why writing to a database and then publishing a message is unsafe,
without using the word "outbox" until the end.

**The shape of the answer.** Describe the crash window. Emphasise that the
failure is silent. Then name the options — two-phase commit, change data
capture, outbox — and say which was chosen and why.

## 58.5 Drill five: design the reservation feature

You decided not to build it. Design it anyway, in five minutes.

**What a complete answer includes.** A reservation entity with an expiry.
Conditional write against the specific batch so two cannot claim the same
units. Automatic release on timeout. Facility override. A short expiry. And a
statement about what it costs: stock held for someone who may not arrive.

## 58.6 Drill six: the bug

Tell the geohash story in three minutes, including both problems and both
fixes.

**What a complete answer includes.** The symptom and why it was invisible. The
cause. The first fix and the performance problem it created. The real fix.
What the tests now assert — properties rather than examples.

<!-- pagebreak -->

# 59. Answering Questions You Cannot Answer

Interviewers ask questions you do not know the answer to, deliberately. How
you handle that is often weighted more heavily than the questions you can
answer.

## 59.1 The structure of a good "I don't know"

**Say it plainly.** "I don't know" is a complete sentence and costs nothing.

**Say what you do know.** "I have not used Kinesis. I have used SQS, and my
understanding is that the difference is ordered, replayable streams with
multiple independent consumers versus a queue where a message is consumed
once. Is that the distinction that matters here?"

**Reason toward an answer.** "If I had to choose now, I would ask whether
multiple consumers need the same events. If yes, the stream. If no, the
queue."

**Offer to find out.** Genuinely, not as a formula.

## 59.2 What not to do

Do not guess confidently. An interviewer who knows the answer learns that your
confident statements cannot be trusted, which contaminates everything else you
said.

Do not deflect into something you do know. It is transparent and wastes the
remaining time.

Do not apologise repeatedly. One acknowledgement is enough.

## 59.3 Questions where "I don't know" is the right answer for this project

**"What is your p99 latency?"** Unknown. It is deployed, but nothing has been
load-tested, and at a concurrency ceiling of 10 a
measurement would mostly describe the ceiling.

**"How does it behave at a thousand requests per second?"** Unknown, and it
would throttle long before that. I can say what would break first and in what
order.

**"Is the compatibility data correct?"** I cannot certify it. It reflects
standard relationships from teaching material, it has not been reviewed by a
qualified professional for this deployment, and every response says so.

**"How long does a restore take?"** Unknown. The procedure is written from the
AWS documentation and has never been executed; PITR is enabled on the deployed
tables, but no restore has been rehearsed against them.

Each of those is a stronger answer than a number I would have had to invent.

<!-- pagebreak -->

# 60. Twenty Rapid-Fire Technical Questions

Short, specific, and the kind asked in a screening call.

| # | Question | Answer |
|---|---|---|
| Q1 | What is a conditional write? | A write that commits only if a condition on the item holds, evaluated atomically |
| Q2 | What does `attribute_not_exists` guarantee? | That the item is being created, not overwritten |
| Q3 | Why is a GSI eventually consistent? | It is maintained asynchronously after the base-table write |
| Q4 | What is a composite sort key? | Several attributes encoded into one sort key so a range condition can filter on them |
| Q5 | Difference between a filter and a key condition? | A filter runs after items are read and billed; a key condition runs during the read |
| Q6 | What is a hot partition? | One partition key receiving disproportionate traffic, throttling despite table capacity |
| Q7 | What is TTL in DynamoDB? | Automatic deletion of items past an epoch timestamp attribute, on a best-effort schedule |
| Q8 | What does `TransactWriteItems` guarantee? | All items commit or none do, across up to 100 items and multiple tables |
| Q9 | What is at-least-once delivery? | A message may be delivered more than once but never zero times |
| Q10 | What is a dead-letter queue? | Where a message goes after failing a configured number of receives |
| Q11 | What is visibility timeout? | How long a received message is hidden from other consumers before reappearing |
| Q12 | What is a cold start? | The latency of initialising a new execution environment before the handler runs |
| Q13 | What is reserved concurrency? | A guaranteed share of the account pool for one function, subtracted from the rest |
| Q14 | What does `kid` do in a JWT? | Names which key in the issuer's key set signed the token |
| Q15 | Why is a JWT not revocable? | It is self-contained and validated offline; nothing is consulted at verification |
| Q16 | What is PKCE? | A proof-of-possession exchange that lets a public client use the authorization code flow safely |
| Q17 | What is Origin Access Control? | A mechanism letting CloudFront read a private S3 bucket without making it public |
| Q18 | What is a geohash? | A base-32 encoding of coordinates where a shared prefix means geographic proximity |
| Q19 | What is the Haversine formula? | Great-circle distance between two points on a sphere |
| Q20 | What is the confused deputy problem? | A privileged service tricked into acting on an attacker's behalf |

*Table 60.1. Rapid-fire technical definitions.*

<!-- pagebreak -->

# 61. Closing: How to Use These Three Books

## 61.1 Reading order

**Book 1** for the architecture and the reasoning behind each AWS choice. Read
it once end to end; it is the one that makes the others make sense.

**Book 2** when you need to change something. It is a reference, organised by
the part of the system you are touching, with the real source in it.

**Book 3** in the week before an examination or interview. Work the question
banks aloud rather than reading them.

## 61.2 The three things worth internalising

**The design is organised around what the system refuses to claim.** Unknown
is not zero. Updated is not verified. An offer is not a reservation. Dispatch
order is not clinical priority. Each of those is a refusal, and together they
account for most of what is distinctive here.

**Correctness lives in the datastore, not in the code.** Eight invariants are
enforced by conditional writes and transactions. The domain layer produces good
error messages; the condition expression produces the guarantee.

**Testing against a real datastore found what review did not.** Five bugs,
four of them silent. That is the strongest single argument this project makes
about engineering practice.

## 61.3 A note on the honesty running through these books

Readers may notice how often these pages say that something was not done, not
tested or not available. That is deliberate and it is the point.

A technical book that reports only successes is a brochure. One that records
the bug it shipped, the validation check that did not work, the page count that
turned out to be inflated by blank pages, and the operational figures that were
never measured, is a document someone can actually rely on.

If you take one habit from this project, take that one.

<!-- pagebreak -->

# 62. Answers Backed by the Actual Code

An interviewer who asks "show me" deserves code rather than description. These
are the eight listings worth being able to talk through line by line, each
extracted from the repository.

## 62.1 The rule that keeps unknown from becoming zero

```python
if not inventory_known:
    return AvailabilitySummary(
        blood_group=blood_group,
        component=component,
        state=AvailabilityState.UNKNOWN,
        # Not 0. "We do not know" and "there are none" lead a user to
        # opposite actions: one calls the facility, the other does not.
        eligible_units=None,
        batch_count=0,
        freshness=FreshnessLabel.UNKNOWN,
        near_expiry_units=0,
        earliest_expiry=None,
```

*Listing 62.1. From `backend/src/domain/inventory.py`.*

**What to say about it.** The early return is the whole point. If the facility
has never reported, no aggregation runs at all — because aggregating an empty
list would produce zero eligible units and a state of `UNAVAILABLE`, which is
a claim the system is not entitled to make. The freshness is `UNKNOWN` for the
same reason: there is no update time to describe.

## 62.2 Eligibility that fails closed

```python
if expires_at is None:
    if require_expiry:
        reasons.append(REASON_MISSING_EXPIRY)
else:
    if collected_at is not None and expires_at <= collected_at:
        # Expiry before collection is incoherent data, not merely expired stock.
        reasons.append(REASON_INVALID_EXPIRY)
    elif expires_at <= now and REASON_EXPIRED not in reasons:
```

*Listing 62.2. From `backend/src/domain/eligibility.py`.*

**What to say about it.** Three branches, and the ordering matters. A missing
expiry is ineligible when expiry is required. An expiry earlier than the
collection date is flagged as *invalid* rather than merely expired, because
that is incoherent data a facility needs to fix. Only then is an ordinary
expiry check applied.

## 62.3 The conditional write

```python
condition = Attr("version").eq(expected_version)
if change.units_delta < 0:
    # Re-assert non-negativity at the storage layer.
    condition = condition & Attr("availableUnits").gte(abs(change.units_delta))

# A failed condition here is a version conflict, not a duplicate, so the
# caller gets ConcurrentModificationError and its retry path engages.
self.put(item, condition=condition, on_conflict="version")
```

*Listing 62.3. From `backend/src/repositories/inventory_repo.py`.*

**What to say about it.** Two conditions ANDed together. The version check
prevents a lost update. The units check prevents negative stock. The second is
redundant with the domain check that already ran, and that redundancy is
deliberate — between the read and the write, another request may have taken
the stock.

The `on_conflict="version"` argument is what makes the failure surface as a
retryable concurrency error rather than a duplicate.

## 62.4 The capacity transaction

```python
"ConditionExpression": (
    "attribute_exists(PK) AND registeredCount < :capacity "
    "AND #s IN (:upcoming, :ongoing)"
),
"ExpressionAttributeNames": {"#s": "status"},
"ExpressionAttributeValues": to_expression_values(
    {
        ":one": 1,
```

*Listing 62.4. From `backend/src/repositories/camp_repo.py`.*

**What to say about it.** The condition is evaluated inside the transaction,
atomically with the write. Three clauses: the camp exists, it is under
capacity, and it is in a state that accepts registrations. Two simultaneous
requests for the final seat cannot both satisfy it.

## 62.5 Exactly-once credit

```python
        "SK": f"LEDGER#{donation_id}",
        "entityType": "LEDGER_ENTRY",
        "donationId": donation_id,
        "donorId": donor_id,
        "points": points,
        "reason": "VERIFIED_DONATION",
        "occurredAt": timestamp,
        "verifiedBy": verifier_id,
    }
)
```

*Listing 62.5. From `backend/src/repositories/camp_repo.py`.*

**What to say about it.** The sort key *is* the idempotency mechanism. A
second verification of the same donation produces the same key, and
`attribute_not_exists(SK)` fails. There is no separate deduplication table and
no window in which a duplicate could slip through.

## 62.6 Priority aging that cannot overrule a clinician

```python
base = PRIORITY_ORDER[clinical_priority]

waited_minutes = max(0.0, (now - created_at).total_seconds() / 60.0)
bands_gained = int(waited_minutes // aging_interval_minutes)
effective = max(0, base - bands_gained)

if required_by is not None:
    minutes_left = (required_by - now).total_seconds() / 60.0
    if 0 < minutes_left <= DEADLINE_URGENCY_MINUTES:
        effective = 0

return ORDER_TO_PRIORITY[effective]


```

*Listing 62.6. From `backend/src/domain/emergency.py`.*

**What to say about it.** The function reads `clinical_priority` and returns a
new value. It is pure — it cannot mutate anything, so it cannot write back.
The caller stores the result in a different field. The separation is
structural rather than a matter of discipline.

## 62.7 The authorization checks, in order

```python
if not allow_anonymous and principal is ANONYMOUS:
    raise UnauthenticatedError("authentication required")

# A valid token from a suspended account must not act (spec 8.1).
if principal is not ANONYMOUS and not principal.is_active:
    raise AccountSuspendedError(
        "this account is not active",
        details={"accountStatus": principal.account_status},
    )

if permission is not None and not principal.has(permission):
    raise ForbiddenError(
        "you do not have permission to perform this action",
        details={"required": permission.value},
    )

if permission is not None and is_organization_scoped(permission) and resource_owner:
    owner_org = resource_owner(event, context)
```

*Listing 62.7. From `backend/src/appcore/auth.py`.*

**What to say about it.** Four refusals before the handler is reached.
Anonymous on a protected route. Inactive account — placed before the
permission check so the error names the real reason. Missing permission.
Wrong organization, with the error deliberately not naming the owner.

## 62.8 Geohash cell coverage

```python
lat_cells = int(math.ceil(lat_degrees / lat_step))
lon_cells = int(math.ceil(lon_degrees / lon_step))

cells: list[str] = [center_hash]
seen = {center_hash}
for i in range(-lat_cells, lat_cells + 1):
    for j in range(-lon_cells, lon_cells + 1):
        if i == 0 and j == 0:
            continue
        lat = latitude + i * lat_step
        lon = longitude + j * lon_step
        if not (-90.0 <= lat <= 90.0):
            continue
        if lon > 180.0:
            lon -= 360.0
        elif lon < -180.0:
            lon += 360.0

        # Skip cells whose nearest corner is still outside the circle --
        # these are the corners of the bounding box and can contain no
```

*Listing 62.8. From `backend/src/domain/geo.py`.*

**What to say about it.** The loop walks the bounding box of the search circle
in cell-sized steps. The intersection test discards corner cells that cannot
contain an in-range point. The hard ceiling on cell count is defensive: the
precision tiers keep the real figure well under it, so tripping it means a
tier was mis-sized rather than that a user asked for something unreasonable.

<!-- pagebreak -->

# 63. Tests Worth Quoting

Showing a test is often more persuasive than describing a behaviour.

## 63.1 The suspended-account test

```python
def test_suspended_account_is_blocked_despite_valid_token_and_role(self):
    """Spec 8.1: a valid JWT must not allow a suspended user to act.

    The role is correct and the organization matches -- only the account
    status differs, which is precisely the case that a token-only check
    would wave through.
    """
    p = principal(
        roles=(Role.BLOOD_BANK_ADMIN,), organization_id="org-1", status="SUSPENDED"
    )
    with pytest.raises(AccountSuspendedError):
        _write_inventory({"ownerOrg": "org-1"}, ctx(p))

def test_suspension_is_checked_before_permission(self):
```

*Listing 63.1. From `backend/tests/unit/test_authorization.py`.*

**Why it is the one to show.** Everything about the caller is correct except
the account status. A system that trusts token claims cannot pass this, and
the docstring says exactly why.

## 63.2 The self-verification test

```python
def test_being_staff_does_not_permit_self_verification(self):
    """Even a camp organiser who donated cannot sign off their own donation."""
    with pytest.raises(ForbiddenError):
        assert_can_verify_donation(
            verifier_id="organizer-7",
            donor_id="organizer-7",
            verifier_is_camp_staff=True,
            donation_status=DonationStatus.RECORDED,
        )

```

*Listing 63.2. From `backend/tests/unit/test_camps_and_impact.py`.*

**Why it is the one to show.** It grants the verifier the staff role
deliberately, so the test proves the rule holds even when the permission does.

## 63.3 The boundary table

```python
(6.0, FreshnessLabel.FRESH),       # inclusive upper bound of 0-6h
(6.1, FreshnessLabel.AGING),
(23.9, FreshnessLabel.AGING),
(24.0, FreshnessLabel.AGING),      # inclusive upper bound of >6-24h
```

*Listing 63.3. From `backend/tests/unit/test_freshness_and_eligibility.py`.*

**Why it is the one to show.** Every boundary tested from both sides. This is
only possible because time is injected rather than read.

## 63.4 The coverage property

```python
missed = []
for degrees in range(0, 360, 5):
    theta = math.radians(degrees)
    # Slightly inside the radius so the point is genuinely in range.
    lat = PATIALA.latitude + 0.999 * lat_degrees * math.sin(theta)
    lon = PATIALA.longitude + 0.999 * lon_degrees * math.cos(theta)
    cell = encode_geohash(lat, lon, precision)
    if cell not in covered:
        missed.append((degrees, cell))

assert not missed, (
    f"radius {radius_km}km missed {len(missed)} bearings, "
```

*Listing 63.4. From `backend/tests/unit/test_geo_coverage.py`.*

**Why it is the one to show.** It asserts a property across every bearing at
ten radii rather than sampling three cases someone thought of. The failure
message names the bearings that were missed.

## 63.5 The no-double-counting test

```python
def test_two_providers_accepting_do_not_reserve_the_same_units(self):
    """ADR-0017: offers are willingness, not reservations.

    Both offers are recorded in full. Nothing is netted off a shared counter,
    because no such counter exists -- which is what makes double-counting
    structurally impossible rather than merely avoided.
    """
    tally = tally_responses([
        {"responseType": ProviderResponseType.ACCEPTED, "unitsOffered": 5},
        {"responseType": ProviderResponseType.ACCEPTED, "unitsOffered": 5},
    ])
    assert tally.accepted == 2
    assert tally.units_offered == 10

```

*Listing 63.5. From `backend/tests/unit/test_emergency.py`.*

**Why it is the one to show.** The comment explains that double-counting is
structurally impossible rather than merely avoided, which is a stronger claim
and the one the design actually supports.

<!-- pagebreak -->

# 64. If You Have Five Minutes to Prepare

Read this page.

## 64.1 The pitch

A cloud platform for blood availability, discovery, donation and emergency
coordination. Seven features. React, Python on Lambda, DynamoDB, in one AWS
region. 657 backend tests passing. Deployed, with the
repository ahead of the deployed stack, and the documentation says so.

## 64.2 The five rules

Unknown is not zero. Updated is not verified. An offer is not a reservation.
Dispatch order is not clinical priority. Fail closed.

## 64.3 The bug

Geohash search queried the centre cell and its eight neighbours, which covers
about fifteen kilometres. A thirty-kilometre search silently missed a facility
25.6 kilometres away. Found by integration tests with real distances. Fixing
coverage caused a 2,107-query search, which needed a third precision tier.
Tests now assert both coverage and bounded fan-out.

## 64.4 The constraint

Lambda concurrency is 10, not
1000. No reserved concurrency, capped consumer
parallelism, one scheduled dispatcher rather than per-priority consumers, and
throttling treated as expected rather than exceptional.

## 64.5 The weakness

The blood compatibility reference has not been clinically reviewed. It is
marked `UNREVIEWED_SYNTHETIC`, the loader refuses to start without a review
status, and every response carries the disclaimer. That is the gap that
matters most, and it is a process gap rather than an engineering one.

## 64.6 The closing line

> The hard part was not the AWS. It was deciding, repeatedly, what the system
> should refuse to claim.