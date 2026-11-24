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
API. One Lambda behind the API handling all {{fact:route_count}} routes.
DynamoDB with {{fact:table_count}} tables. SQS with dead-letter queues for
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

{{fact:cfn_alarms}} alarms, each mapped to a condition worth waking someone
for. The one I would name is dispatcher failure: if it stops, emergency
requests silently stop being matched while everything else looks fine, so that
handler re-raises on error specifically to make the alarm fire.

**"What is your disaster recovery story?"**

Point-in-time recovery with a 35-day window, versioned S3, and infrastructure
in version control. Within-region only, because the account cannot do
cross-region replication. And the RPO and RTO figures are design assumptions,
not measurements — nothing has been deployed, so no restore rehearsal has been
run. I would not claim a tested DR capability.

*Assessing: honesty. The temptation is to quote numbers.*

**"What does it cost?"**

About $1.40 a month fixed — a KMS key and a Secrets Manager secret — with
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
| DynamoDB tables / indexes | {{fact:table_count}} / {{fact:gsi_count}} |
| API routes | {{fact:route_count}} |
| Permissions / roles | {{fact:permission_count}} / {{fact:role_count}} |
| Backend tests | {{fact:test_backend}} |
| All tests, backend plus frontend | {{fact:test_total}} |
| CloudFormation resources / alarms | {{fact:cfn_resources}} / {{fact:cfn_alarms}} |
| Lambda concurrency ceiling | {{fact:lambda_concurrency}} |
| Region | {{fact:aws_region}} |

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
