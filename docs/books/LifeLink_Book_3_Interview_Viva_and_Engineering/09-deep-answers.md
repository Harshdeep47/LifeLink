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
{{fact:lambda_concurrency}}, a single search consuming a container for that
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
content. `{{include:backend/src/domain/freshness.py:def freshness_label}}`
extracts that function from that file at build time. `{{fact:test_total}}`
is replaced by a number produced by running the suite during the build.
`{{routes:alert}}` reads the live router.

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

One SAM template, {{fact:cfn_resources}} resources, validated by two tools and
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
> It has {{fact:test_backend}} backend tests and {{fact:test_frontend}} frontend
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
