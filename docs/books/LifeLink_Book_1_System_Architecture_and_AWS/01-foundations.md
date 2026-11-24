# 1. The Problem LifeLink Addresses

## 1.1 A coordination failure, not a supply failure

India collects a large volume of blood every year. People still die waiting for
it. The gap between those two statements is rarely a shortage in the aggregate;
far more often it is a coordination failure in the particular. A hospital in
Patiala needs two units of O-negative packed red cells within four hours. Those
units may well exist eleven kilometres away. Nobody at the hospital knows that,
and nobody at the blood bank knows they are needed.

The attendant making phone calls faces a specific set of obstacles:

- There is no single place to see what nearby facilities hold.
- Where a number is published, it is often hours or days old, and nothing says
  which.
- A facility that has not published anything looks identical to a facility that
  has published a zero.
- Telephoning takes minutes per facility, and the list of facilities to try is
  itself unknown.
- Compatibility rules are not something a frightened relative should be
  improvising at a counter.

LifeLink exists to compress that search. It is a coordination system: it helps
the right people find each other and exchange accurate information quickly. It
is emphatically not a clinical system, and the distinction runs through every
design decision in this book.

:::key The single most important sentence in this book
LifeLink shows what facilities have **reported**. It does not reserve blood, does
not decide clinical urgency, and does not certify that any unit is suitable for
any patient. Those are decisions for qualified professionals working with
validated laboratory procedures.
:::

## 1.2 What the system actually does

Seven capabilities, which the remainder of this book treats as the system's
feature set:

1. **Blood bank inventory management.** Facilities record stock at the level of
   individual batches, each with its own expiry, status and audit history.
2. **Location services and navigation.** Users discover nearby facilities,
   filtered and ranked by availability, data freshness, verification and
   distance.
3. **Donation camps and donor engagement.** Camps are organised, approved,
   staffed and run; donors register, attend, donate and accrue verified
   recognition.
4. **Smart emergency coordination.** Urgent requirements are raised, assigned a
   hospital-certified clinical priority, matched against compatible stock, and
   routed to providers who respond.
5. **Frontend architecture and user experience.** A responsive, accessible web
   application that works under pressure.
6. **Security, authentication and monitoring.** Identity, role-based access
   control, organization isolation, audit and observability.
7. **Cloud infrastructure and deployment architecture.** The AWS design that
   carries all of the above, expressed as infrastructure code.

Features 5, 6 and 7 are not documentation chapters attached to the "real"
features. They are the parts a reviewer is most likely to find missing in a
student project, and they receive the same treatment as the functional modules.

## 1.3 Who uses it

| Role | What they do | What they must not be able to do |
|---|---|---|
| Public visitor | Search facilities and camps, read availability | See privileged dashboards or contact details |
| Donor | Create availability alerts, register for camps, track verified donations | Verify their own donation |
| Blood bank staff | Update stock, quarantine batches | Correct records or mark stock independently verified |
| Blood bank admin | All staff actions plus corrections, verification and API ingestion | Touch another organization's inventory |
| Hospital staff | Raise emergency requests, track them | Certify clinical priority |
| Hospital authorizer | Certify clinical priority | Certify for a hospital they do not belong to |
| Camp organizer | Create and manage camps, assign staff, verify donations | Gain any blood bank inventory permission |
| Camp staff | Check donors in, record and verify donations | Act on a camp they are not assigned to |
| Platform administrator | Verify organizations, suspend accounts, read audit | Bypass organization scoping without it being audited |

*Table 1.1. Roles and the boundaries that define them. The right-hand column is
the more interesting one: a role is defined as much by what it is refused as by
what it is granted.*

## 1.4 Functional requirements

Stated as capabilities the system must have, each traceable to a feature:

- **FR-1** Record blood stock at batch granularity, with group and component
  tracked independently, never as a single aggregate number.
- **FR-2** Compute eligibility dynamically from status, expiry and quantity,
  failing closed when data is missing or incoherent.
- **FR-3** Report data freshness and independent verification as two separate,
  simultaneously visible signals.
- **FR-4** Discover facilities near a point, filtered by group, component,
  availability, freshness and verification, ranked by a documented and
  explainable formula.
- **FR-5** Let a user register a short-term need and be notified when matching
  stock appears, without that registration constituting a reservation.
- **FR-6** Run the camp lifecycle from proposal through approval, registration,
  attendance, donation and independent verification.
- **FR-7** Credit donor recognition exactly once per verified donation.
- **FR-8** Raise emergency requests whose clinical priority is certified only by
  authorized hospital personnel, with the actor recorded.
- **FR-9** Match requests to facilities using versioned, medically-reviewable
  compatibility reference data, never inference.
- **FR-10** Schedule emergency work by priority with a fairness mechanism that
  prevents starvation and never alters clinical priority.
- **FR-11** Enforce authorization server-side on every request, including
  account status and resource ownership.
- **FR-12** Audit every privileged operation with actor, action, resource and
  time.

## 1.5 Non-functional requirements

| Requirement | Target | How it is met | Verified? |
|---|---|---|---|
| Correctness under concurrency | No lost updates, no oversubscription, no double credit | Conditional writes and DynamoDB transactions | Yes, by integration tests |
| Honest data presentation | Unknown never rendered as zero | Separate `UNKNOWN` state carried end to end | Yes, by unit and UI tests |
| Authorization completeness | No endpoint unprotected | Single decorator plus a route-table audit test | Yes, {{fact:route_count}} routes checked |
| Observability | Every failure visible | Structured logs, correlation ids, {{fact:cfn_alarms}} alarms | Partially: deployed and defined, never fired in anger |
| Local runnability | Full stack without AWS | moto-backed local stack, local token issuer | Yes |
| Accessibility | Keyboard navigable, no colour-only status | Focus rings, text labels and glyphs on every badge | Partially: basic checks only |
| Latency | API p95 under 3 seconds | Indexed queries only, bounded fan-out | Not measured; deployed but never load-tested |
| Scalability | Graceful under throttling | Adaptive retries, bounded consumer concurrency | Not load-tested; see 1.6 |

*Table 1.2. Non-functional requirements and their honest verification status.*

The final column matters. Several rows say "not measured", and this book does
not quietly convert a design intention into a claimed result.

## 1.6 The constraints this project was actually built under

Most architecture documents describe an idealised environment. This one does
not, because the real constraints shaped the design in ways a reader should be
able to see.

The AWS project used for LifeLink is account `{{fact:aws_account}}` in region
`{{fact:aws_region}}`, on the **{{fact:aws_plan}}** plan, measured on
{{fact:measured_on}}. Three constraints follow from that and are referenced
repeatedly in later chapters:

:::warning Lambda concurrency is 10, not 1000
The account's concurrent-execution ceiling is **{{fact:lambda_concurrency}}**,
against an AWS default of {{fact:lambda_concurrency_default}}. This is not a
hypothetical. It rules out reserved concurrency entirely, caps queue-consumer
parallelism, and is one of two independent reasons the emergency dispatcher is
an application-level scheduler rather than a set of priority queues.
:::

**Single region.** Every regional resource lives in `{{fact:aws_region}}`.
Cross-region replication, multi-region KMS keys and latency-based routing are
unavailable. Disaster recovery is therefore a within-region story, and
Chapter 24 says so plainly rather than describing a multi-region design that
cannot be built here.

**Service availability.** Amazon SES is in {{fact:ses_mode}}. SMS is denied
outright by a service control policy and is unavailable on this plan. The
notification subsystem is built with pluggable channels and SMS is reported as
NOT IMPLEMENTED rather than stubbed to look functional.

## 1.7 How to read this book

Chapters 2 to 6 establish the shape of the system. Chapters 7 to 20 take each
AWS service in turn and answer the same ten questions about it. Chapters 21 to
30 deal with cross-cutting concerns: security boundaries, event-driven design,
failure, recovery, cost, scale, and the trade-offs that were accepted.

Code listings in this book are extracted from the repository at build time. If
a listing says it comes from `backend/src/domain/freshness.py`, that is where it
came from, and it is the current content of that file.

<!-- pagebreak -->

# 2. The Seven-Feature Architecture

## 2.1 Features as ownership boundaries

A feature list is usually a product artefact. Here it is also an architectural
one: each feature owns a bounded context, and ownership means exactly one part
of the system is authoritative for a given kind of data.

```diagram
type: layered
title: Feature ownership and the dependencies between features
layer Experience
node f5 Feature 5 Frontend and UX style=domain
layer Coordination
node f4 Feature 4 Emergency coordination style=domain
node f3 Feature 3 Camps and donors style=domain
layer Discovery
node f2 Feature 2 Location and discovery style=domain
layer Source of truth
node f1 Feature 1 Inventory and alerts style=domain
layer Platform
node f6 Feature 6 Security and monitoring style=aws
node f7 Feature 7 Cloud infrastructure style=aws
edge f5 -> f4
edge f5 -> f3
edge f5 -> f2
edge f4 -> f2
edge f4 -> f1
edge f2 -> f1
edge f3 -> f6
```

*Figure 2.1. Features 1 to 5 form a dependency stack; Features 6 and 7 are
platform concerns that every other feature sits on.*

The arrows all point downward or inward, and that is deliberate. Feature 1 does
not know Feature 4 exists. Feature 2 reads inventory through Feature 1's
interface but keeps no stock records of its own. Feature 4 consumes both but
owns neither.

## 2.2 Domain ownership, stated precisely

| Feature | Owns | Reads from | Never does |
|---|---|---|---|
| 1 — Inventory | Batches, stock operations, availability alerts | Facilities (for geocoding a match) | Decide clinical suitability |
| 2 — Location | Facility directory, geospatial index, ranking | Inventory via Feature 1 | Keep its own stock numbers |
| 3 — Camps | Camps, registrations, attendance, donations, impact ledger | Identity | Touch inventory |
| 4 — Emergency | Requests, certifications, provider responses, dispatch | Inventory, facilities, compatibility reference | Set clinical priority itself |
| 5 — Frontend | Presentation and interaction | Everything, through the API | Hold business rules |
| 6 — Security | Identity, roles, audit, observability | Everything | Be optional on any path |
| 7 — Infrastructure | Deployment topology and IaC | — | Be created by hand |

*Table 2.1. What each feature owns, reads and refuses.*

The row that most often gets violated in systems of this kind is Feature 2.
It is tempting to let the discovery service cache availability numbers for
speed. LifeLink does not, because a cached stock figure immediately becomes a
second source of truth that can disagree with the first, and in this domain a
disagreement about blood availability is not a cosmetic bug.

## 2.3 Why availability alerts live inside Feature 1

Short-term availability alerts look superficially like a separate feature: they
have their own table, their own lifecycle and their own notifications. They are
deliberately treated as a submodule of Feature 1.

The reason is ownership. An alert is a standing question about inventory —
"tell me when O-negative packed red cells appear near Patiala." Answering it
requires reading eligible stock, applying the same eligibility rules, and
respecting the same freshness semantics. If alerts were their own feature they
would need their own copy of those rules, and two copies of an eligibility rule
is one copy too many.

## 2.4 System boundaries

```diagram
type: layered
title: What is inside the system and what is not
layer People
node public Public visitor style=user
node donor Donor style=user
node staff Institution staff style=user
layer LifeLink
node web Web application style=domain
node api API and domain services style=domain
node data Owned data stores style=data
layer External
node loc Amazon Location Service style=external
node ses Email delivery style=external
node feeds Institutional inventory feeds style=external
edge public -> web
edge donor -> web
edge staff -> web
edge web -> api
edge api -> data
edge api -> loc
edge api -> ses
edge feeds -> api
```

*Figure 2.2. System boundary. External providers supply capabilities, never
authority: a mapping provider can tell LifeLink where an address is, but cannot
make an organization a verified blood bank.*

That last point deserves emphasis because it is a common and consequential
error. A business listing in a map provider's database is not evidence that an
institution operates a licensed blood bank. LifeLink maintains its own facility
directory with its own verification state, set only by an administrator.

## 2.5 The request path, end to end

```diagram
type: sequence
title: A public availability search, from click to answer
actor browser Browser
actor cdn CloudFront
actor api API Gateway
actor fn Lambda handler
actor fac Facilities table
actor inv Inventory table
msg browser -> cdn load application
msg browser -> api GET /facilities
msg api -> fn invoke
msg fn -> fac geohash cell queries
msg fac -> fn candidate facilities
msg fn -> inv eligible stock per facility
msg inv -> fn batches
msg fn -> browser ranked results with explanations
note Eligibility filtering happens before ranking, so no weighting can surface expired stock.
```

*Figure 2.3. The read path for the application's most-used endpoint.*

Chapter 6 walks this sequence in detail. The property worth noticing now is the
ordering: eligibility is a hard filter applied first, and ranking only ever
reorders what survived it.

## 2.6 Technology choices at a glance

| Layer | Choice | One-line reason |
|---|---|---|
| Frontend | React {{fact:frontend_modules}} modules, Vite | Component model suits role-varying dashboards; Vite keeps the dev loop fast |
| Map rendering | MapLibre GL JS | Open renderer with no vendor lock on tiles |
| Backend | Python {{fact:python_version}} on AWS Lambda | Same language locally and in cloud; no servers to operate |
| API | Amazon API Gateway HTTP API | Lower cost and latency than REST API; no REST-only feature needed |
| Database | Amazon DynamoDB, {{fact:table_count}} tables, {{fact:gsi_count}} indexes | Predictable latency; access patterns known in advance |
| Identity | Amazon Cognito | Managed OIDC; no password handling in application code |
| Async | Amazon SQS with dead-letter queues | Per-consumer retry semantics and visible failure |
| Location | Amazon Location Service | Maps, geocoding and routing from one provider, server-side |
| IaC | AWS SAM and CloudFormation | Reproducible; {{fact:cfn_resources}} resources in one template |

*Table 2.2. Technology choices. Each is argued properly in its own chapter.*
