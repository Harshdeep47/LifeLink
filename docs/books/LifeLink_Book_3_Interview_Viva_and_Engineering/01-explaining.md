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

**"Did you deploy it?"** No. The infrastructure template is validated by
`cfn-lint` and `sam validate --lint` with no findings, and nothing has been
deployed. I have not claimed any production figures.

**"How do you know it works?"** {{fact:test_backend}} backend tests and
{{fact:test_frontend}} frontend tests, with the end-to-end scenarios named after
the ten flows the specification requires. The numbers in the documentation are
produced by running the suites at build time, not typed in.

**"What is the weakest part?"** The absence of a reviewed compatibility
reference, followed by the fact that nothing has been deployed so several
operational claims are design assumptions rather than measurements. Both are
in the known-limitations table.

## 5.3 Deliberately showing a refusal

The most persuasive two minutes of any demonstration is signing in as
`user-suspended-1` and watching every action fail with
`ACCOUNT_SUSPENDED`. It shows a security property working rather than
described, and it is the one test a token-trusting system cannot pass.
