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
Lambda concurrency ceiling of {{fact:lambda_concurrency}}. Saying so costs
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

{{fact:test_total}} tests passing is a real number. "Fully tested" is not, and
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
