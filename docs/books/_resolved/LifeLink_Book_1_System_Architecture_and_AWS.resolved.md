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
| Authorization completeness | No endpoint unprotected | Single decorator plus a route-table audit test | Yes, 58 routes checked |
| Observability | Every failure visible | Structured logs, correlation ids, 8 alarms | Partially: deployed and defined, never fired in anger |
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

The AWS project used for LifeLink is account `426150327442` in region
`ap-southeast-2`, on the **FREE** plan, measured on
2026-11-15. Three constraints follow from that and are referenced
repeatedly in later chapters:

:::warning Lambda concurrency is 10, not 1000
The account's concurrent-execution ceiling is **10**,
against an AWS default of 1000. This is not a
hypothetical. It rules out reserved concurrency entirely, caps queue-consumer
parallelism, and is one of two independent reasons the emergency dispatcher is
an application-level scheduler rather than a set of priority queues.
:::

**Single region.** Every regional resource lives in `ap-southeast-2`.
Cross-region replication, multi-region KMS keys and latency-based routing are
unavailable. Disaster recovery is therefore a within-region story, and
Chapter 24 says so plainly rather than describing a multi-region design that
cannot be built here.

**Service availability.** Amazon SES is in sandbox (200 messages/day, 1 per second, verified recipients only). SMS is denied
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
| Frontend | React 60 modules, Vite | Component model suits role-varying dashboards; Vite keeps the dev loop fast |
| Map rendering | MapLibre GL JS | Open renderer with no vendor lock on tiles |
| Backend | Python 3.14.2 on AWS Lambda | Same language locally and in cloud; no servers to operate |
| API | Amazon API Gateway HTTP API | Lower cost and latency than REST API; no REST-only feature needed |
| Database | Amazon DynamoDB, 12 tables, 24 indexes | Predictable latency; access patterns known in advance |
| Identity | Amazon Cognito | Managed OIDC; no password handling in application code |
| Async | Amazon SQS with dead-letter queues | Per-consumer retry semantics and visible failure |
| Location | Amazon Location Service | Maps, geocoding and routing from one provider, server-side |
| IaC | AWS SAM and CloudFormation | Reproducible; 59 resources in one template |

*Table 2.2. Technology choices. Each is argued properly in its own chapter.*

<!-- pagebreak -->

# 3. Architecture Overview

## 3.1 The whole system on one page

```diagram
type: layered
title: LifeLink deployed architecture
layer Client
node browser Browser React and MapLibre style=user
layer Edge
node cf CloudFront distribution style=aws
node s3f S3 frontend bucket style=aws
layer Identity
node cognito Cognito user pool style=aws
node idp Identity pool for map tiles style=aws
layer API
node apigw API Gateway HTTP API style=aws
layer Compute
node api API function style=aws
node disp Priority dispatcher style=aws
node work Queue workers style=aws
node maint Scheduled maintenance style=aws
layer Messaging
node sqs SQS work and notification queues style=aws
node dlq Dead letter queues style=aws
layer Data
node ddb DynamoDB eleven tables style=data
node s3u S3 private uploads style=data
layer Integrations
node loc Amazon Location Service style=external
node ses Amazon SES style=external
layer Operations
node cw CloudWatch logs metrics alarms style=aws
node ct CloudTrail style=aws
edge browser -> cf
edge cf -> s3f
edge browser -> apigw
edge browser -> cognito
edge apigw -> api
edge api -> ddb
edge api -> sqs
edge api -> loc
edge sqs -> work
edge work -> ses
edge disp -> ddb
edge maint -> ddb
edge sqs -> dlq
edge api -> cw
```

*Figure 3.1. The deployed architecture. Every regional resource sits in
ap-southeast-2; CloudFront is global and is administered through
`us-east-1`, which the account's rules permit.*

This diagram describes the design expressed in
`infrastructure/template.yaml` — 1490 lines defining
59 resources. It has been validated by `cfn-lint` and
`cfn-lint`, and it **has been deployed** — stack `lifelink-dev`, live since
15 November 2026. What remains true is that the repository is ahead of the
deployed stack. That distinction is
maintained throughout this book.

## 3.2 Reading the diagram

Three properties are worth drawing out before the detail chapters.

**The browser talks to two things, not one.** Static assets come from
CloudFront in front of a private S3 bucket. API calls go directly to API
Gateway. Putting the API behind the same distribution would add a cache layer
in front of data whose freshness is the entire point of the product.

**Nothing reaches DynamoDB except Lambda.** There is no direct browser access
to data, no public table, and no credential in the client that could permit one.
The single exception is map tiles, where a Cognito identity pool issues
temporary credentials scoped to four read-only Amazon Location actions and
nothing else.

**Asynchronous work is genuinely asynchronous.** The API never waits on email
delivery or alert matching. It writes a durable event and returns. Chapter 22
explains the transactional outbox that makes that safe.

## 3.3 Synchronous and asynchronous paths

| Path | Trigger | Latency budget | Failure behaviour |
|---|---|---|---|
| Facility search | User request | Sub-second | Error surfaced to user with retry |
| Stock adjustment | Staff action | Sub-second | 409 on conflict; client re-reads |
| Alert matching | Stock change event | Seconds to a minute | Retried, then dead-lettered and alarmed |
| Notification delivery | Queued event | Seconds to a minute | Retried five times, then dead-lettered |
| Emergency dispatch | One-minute schedule | Up to 60 seconds | Alarmed; P1 also triggers out-of-band |
| Expiry sweep | Ten-minute schedule | Minutes | Partial failure reported, others continue |

*Table 3.1. Latency budgets and failure behaviour by path.*

The up-to-60-second dispatch latency is a real cost of the scheduler design and
is stated rather than hidden. For a coordination system where the subsequent
human steps take minutes, it is acceptable; Chapter 28 revisits whether it
would remain so at higher volume.

## 3.4 The data layer at a glance

Eleven tables, one per bounded context, with 24 global secondary
indexes between them.

| Table | Holds | Indexes | Notable |
|---|---|---|---|
| `organizations` | Users, organizations, memberships | 1 | Source of truth for authorization |
| `facilities` | Facility directory | 5 | Three geohash precisions |
| `inventory` | Batches and their audit history | 2 | Status-and-expiry composite sort key |
| `alerts` | Availability alerts | 2 | Reverse match index; TTL |
| `camps` | Camps, registrations, staff | 4 | One partition per camp |
| `donations` | Donations and impact ledger | 1 | Ledger keyed on donation id |
| `emergency` | Requests, responses, events | 4 | Dispatch index sorts by priority |
| `notifications` | Preferences, messages, markers | 1 | TTL |
| `audit` | Append-only audit trail | 1 | Write-only IAM; customer-managed key |
| `idempotency` | Request and event claims | 0 | TTL; no PITR by design |
| `outbox` | Transactional outbox | 1 | DynamoDB stream to publisher |

*Table 3.2. The eleven tables. Chapter 11 covers the data model properly.*

## 3.5 What is deliberately absent

An architecture is defined partly by what it refuses to include.

- **No cache tier.** DynamoDB Accelerator is unavailable on this plan, and more
  importantly, caching availability data works against the product's purpose.
- **No search cluster.** Discovery is geospatial and attribute-filtered, which
  indexed DynamoDB queries handle. OpenSearch would add operational weight for
  no benefit at this scale.
- **No Step Functions.** The specification permits them where their value
  justifies the complexity. The emergency workflow is a state machine, but it is
  a slow one driven by human responses over hours, so a scheduled dispatcher
  plus an explicit transition table is simpler and easier to reason about.
- **No API Gateway REST API.** The HTTP API variant is cheaper and faster;
  nothing in LifeLink needs request validators, usage plans or WAF integration
  at the API tier.
- **No container orchestration.** There is no long-running process to run.

:::note On resisting the urge to add services
A reviewer sometimes reads a long AWS service list as evidence of sophistication.
It is at least as often evidence of unexamined choices. Each service in this
design earns its place in its own chapter, and the ones above were considered
and rejected for stated reasons.
:::

<!-- pagebreak -->

# 4. System Boundaries and Domain Ownership

## 4.1 Why boundaries are enforced, not merely documented

A boundary that exists only in a diagram decays. LifeLink enforces its domain
boundaries at the level where they cannot be accidentally crossed: separate
DynamoDB tables with separate IAM grants.

The practical consequence is visible in the infrastructure template. The
notification worker's policy grants it access to the notifications and
idempotency tables and read access to organizations. It has no grant for the
inventory table at all. If someone later writes code in that worker that
touches inventory, it does not quietly work — it fails with an access denial.

```yaml
NotificationWorker:
  Type: AWS::Serverless::Function
  Properties:
    Policies:
      - DynamoDBCrudPolicy: { TableName: !Ref NotificationsTable }
      - DynamoDBCrudPolicy: { TableName: !Ref IdempotencyTable }
      - DynamoDBReadPolicy: { TableName: !Ref OrganizationsTable }
```

*Listing 4.1. Least privilege as a boundary enforcement mechanism, from
`infrastructure/template.yaml`.*

## 4.2 The audit table's write-only grant

The clearest example of this principle is the audit trail. The specification
asks for audit records that are "tamper-resistant within the chosen
architecture." LifeLink implements that by granting the application `PutItem`
and `Query` on the audit table — and nothing else.

```yaml
# Audit is WRITE-ONLY on purpose: no UpdateItem, no DeleteItem, so the
# application physically cannot rewrite history (spec 8.4).
- Statement:
    - Effect: Allow
      Action: ['dynamodb:PutItem', 'dynamodb:Query']
      Resource:
        - !GetAtt AuditTable.Arn
        - !Sub '${AuditTable.Arn}/index/*'
    - Effect: Allow
      Action: ['kms:GenerateDataKey', 'kms:Decrypt']
```

*Listing 4.2. The audit grant, from `infrastructure/template.yaml`. No
`UpdateItem`, no `DeleteItem`: the application cannot rewrite history even if
its code tried to.*

This is resistance, not immutability. An account administrator with sufficient
IAM privileges could still alter the table. The documentation says exactly that
rather than overclaiming, and Chapter 21 discusses what genuine immutability
would require.

## 4.3 Cross-feature interfaces

Where features must interact, they do so through a service interface rather
than a shared table.

| Interaction | Mechanism | Why not direct |
|---|---|---|
| Discovery needs availability | `InventoryService.facility_availability` | Keeps eligibility rules in one place |
| Emergency needs eligible stock | `DiscoveryService.find_facilities_with_stock` | Reuses ranking and filtering |
| Alerts need stock changes | Outbox event consumed by a worker | Decouples write path from match path |
| Camps need identity | `IdentityRepository` read | Authorization is platform-owned |
| Everything needs audit | `AuditRepository.record` | One format, one write path |

*Table 4.1. The interfaces between features.*

## 4.4 A worked example of ownership

Consider the question "how many units of O-negative PRBC are available at
facility X?" Four parts of the system might plausibly answer it. Only one does.

```diagram
type: flow
title: Who answers an availability question
node ui Browser asks the API style=user
node disc Discovery service receives the search style=domain
node inv Inventory service computes availability style=domain
node repo Inventory repository queries the eligible-stock index style=data
node dom Domain layer applies eligibility and freshness rules style=domain
node ans One authoritative answer returns style=domain
```

*Figure 4.1. Every availability answer travels the same path, so there is
exactly one implementation of the rules that produce it.*

The discovery service does not compute availability. It asks the inventory
service, which asks its repository, which queries an index whose sort key
already excludes ineligible stock, and then applies the domain rules. Any other
arrangement would eventually produce two answers to the same question.

<!-- pagebreak -->

# 5. The AWS Account, Region and Environment Model

## 5.1 The account this was built in

| Property | Value | Source |
|---|---|---|
| Account | `426150327442` | `sts:GetCallerIdentity` |
| Region | `ap-southeast-2` | `~/.aws/config` and live AZ query |
| Plan | FREE | `freetier:GetAccountPlanState` |
| Identity | `AccountFullAccessRole` via social sign-in | STS |
| Measured | 2026-11-15 | Phase 0 discovery |

*Table 5.1. The account, verified rather than assumed.*

Phase 0 of this project deliberately re-verified values that were already
"known." The specification warned that the region might have changed; it had
not, but checking cost two minutes and would have saved days if it had.

## 5.2 Why single-region is a design input

The account is pinned to one region. That is not a limitation to be worked
around; it is a parameter the design must respect honestly.

What it rules out:

- DynamoDB global tables and cross-region S3 replication
- Multi-region KMS keys
- Route 53 latency-based, geolocation and failover routing
- CloudFormation StackSets
- Lambda@Edge

What it means in practice: LifeLink's recovery story is within-region, built on
point-in-time recovery and redeployable infrastructure. A regional outage is an
outage. Chapter 24 states the resulting RPO and RTO assumptions and marks the
untested parts as untested.

:::warning A design that cannot be built is not a design
It would be easy to write a chapter describing active-active multi-region
deployment with Route 53 failover. It would also be fiction for this project.
The architecture documented here is the one that the account can actually run.
:::

## 5.3 Environment model

Three environments, distinguished by a single template parameter.

| Environment | Table removal | Demo seeding | PITR | Purpose |
|---|---|---|---|---|
| `local` | n/a | Permitted and expected | n/a | Developer machine, no AWS |
| `dev` | Delete on stack removal | Permitted | Enabled | First AWS deployment target |
| `prod` | Retain | **Refused by the seeder** | Enabled | Production-ready configuration |

*Table 5.2. Environment differences.*

The seeding guard is worth showing, because "do not seed demo data into
production" is the kind of rule that is usually a comment rather than a control:

```python
def guard_environment() -> None:
    """Refuse to seed anything that might be production (spec 11.3)."""
    env = os.environ.get("LIFELINK_ENV", "local").lower()
    if env not in ("local", "dev", "development", "test"):
        print(f"REFUSING TO SEED: LIFELINK_ENV is '{env}'.")
        print("Synthetic demo data must never be seeded into staging or production.")
        raise SystemExit(2)
    endpoint = os.environ.get("DYNAMODB_ENDPOINT", "")
    if env in ("local", "test") and not endpoint:
        print("REFUSING TO SEED: local mode requires DYNAMODB_ENDPOINT to be set.")
        print("This prevents a local seed run from writing to real AWS tables.")
        raise SystemExit(2)
    if endpoint and "amazonaws.com" in endpoint:
        print("REFUSING TO SEED: DYNAMODB_ENDPOINT points at real AWS.")
        raise SystemExit(2)
```

*Listing 5.1. The production seeding guard from `scripts/seed_demo.py`. It
refuses on the environment name, refuses if the local endpoint is missing, and
refuses if the endpoint points at real AWS.*

Three independent conditions, because a single check is one typo away from
being bypassed.

## 5.4 Configuration by environment

Configuration reaches the application through Lambda environment variables set
by the template, never through values baked into code.

| Variable | Purpose | Local value |
|---|---|---|
| `LIFELINK_ENV` | Switches local adapters and seeding guards | `local` |
| `LIFELINK_TABLE_PREFIX` | Table namespacing per environment | `lifelink` |
| `DYNAMODB_ENDPOINT` | Points at the local DynamoDB-compatible endpoint | `http://localhost:8000` |
| `COGNITO_USER_POOL_ID` | Token verification | unset locally |
| `LOCATION_PLACE_INDEX` | Geocoding resource | unset locally |
| `SES_SENDER` | Verified sender address | unset locally |
| `WORK_QUEUE_URL` | Outbox routing target | unset locally |

*Table 5.3. Environment variables. A complete list with examples lives in
`docs/ENVIRONMENT_VARIABLES.md` and `.env.example`.*

<!-- pagebreak -->

# 6. Frontend to Backend Request Flow

## 6.1 An authenticated write, step by step

The facility search in Figure 2.3 is the most frequent path. The most
instructive one is an authenticated write, because it exercises authentication,
authorization, concurrency control, audit and eventing together.

```diagram
type: sequence
title: Deducting a unit of stock
actor ui Blood bank dashboard
actor api API function
actor auth Authorization decorator
actor idn Organizations table
actor svc Inventory service
actor inv Inventory table
msg ui -> api POST adjust with bearer token
msg api -> auth build request context
msg auth -> idn load principal by subject
msg idn -> auth roles status organization
msg auth -> svc authorized context
msg svc -> inv read batch and version
msg svc -> inv transaction update audit outbox
msg inv -> svc committed or condition failed
msg svc -> ui new batch state or 409
note Roles come from the database, not the token, so a revoked role applies on the next request.
```

*Figure 6.1. An authenticated stock deduction.*

## 6.2 What happens at each step

**1. The browser sends the request.** The API client attaches the bearer token,
a correlation id and, for mutating calls, an idempotency key. It is the only
place in the frontend that performs network access, so these headers cannot be
forgotten by an individual screen.

**2. The router matches a route.** The route table is a list of method, path
pattern, handler and declared permission. A request to an unknown path returns
404; a known path with the wrong method returns 405 rather than a misleading
404.

**3. The authorization decorator runs.** This is the security core and
Chapter 21 covers it fully. In outline: verify the token signature and claims,
load the user from the database, reject if the account is not active, check the
permission, then compare the resource's owning organization with the caller's.

**4. The handler parses and delegates.** Handlers are thin. They convert an
HTTP event into typed arguments, call one service method and format the result.

**5. The service applies domain rules.** The inventory service reads the current
batch, calls a pure domain function to decide the new state, and refuses
outright if that state would be invalid.

**6. The repository writes conditionally.** The write asserts the version has
not changed and, for deductions, that sufficient units remain. A concurrent
writer fails this condition.

**7. Audit and event are written in the same transaction.** Not afterwards: in
the same `TransactWriteItems` call, so a crash cannot produce a stock change
with no audit record or no event.

## 6.3 Where the response shape is decided

Every response uses one envelope, produced in `backend/src/appcore/responses.py`:

```python
def success(data: Any, *, status: int = 200, correlation_id: str | None = None,
            meta: dict | None = None) -> dict:
    payload: dict[str, Any] = {"data": data}
    if meta:
        payload["meta"] = meta
    if correlation_id:
        payload["correlationId"] = correlation_id
    return {
        "statusCode": status,
        "headers": dict(JSON_HEADERS),
        "body": _body(payload),
    }
```

*Listing 6.1. The success envelope. Errors use a parallel shape carrying a
stable `code`.*

Clients branch on `error.code`, never on the message. The message is written for
a human and may be reworded; the code is part of the contract.

## 6.4 Correlation across the whole path

A correlation id is generated by the browser, accepted by the API if supplied,
and attached to every log line, audit record and queued event for that request.

```diagram
type: flow
title: One correlation id across a request and its consequences
node a Browser generates web-uuid style=user
node b API logs every line with it style=aws
node c Audit record stores it style=data
node d Outbox event carries it style=data
node e Queue message preserves it style=aws
node f Worker logs under the same id style=aws
```

*Figure 6.2. Following a single user action across synchronous and asynchronous
work.*

When a user reports that something did not work, the correlation id shown in the
error panel is enough to retrieve the whole story, including the background work
their action triggered.

<!-- pagebreak -->

# 7. Amazon Cognito and Identity

Each AWS service chapter answers the same ten questions: what it is, why
LifeLink uses it, how it works, where it sits, what configuration matters, what
secures it, what can fail, how failure is handled, what it costs, and what
simpler alternative was considered.

## 7.1 What Cognito is

A managed identity provider. It stores user accounts, handles sign-up, sign-in,
password recovery and multi-factor authentication, and issues signed JSON Web
Tokens that other services can verify without calling back to it.

## 7.2 Why LifeLink uses it

Because writing authentication is a way to introduce vulnerabilities, not a way
to demonstrate skill. Password hashing, reset-token expiry, enumeration
resistance, MFA enrolment and token rotation are all solved problems with
well-understood failure modes, and all of them are easy to get subtly wrong.

The specification also asks for OAuth 2.0 and OIDC flows including
Authorization Code with PKCE. Cognito provides those directly.

## 7.3 How it works here

```diagram
type: sequence
title: Authorization Code with PKCE
actor browser Browser
actor cognito Cognito managed login
actor api LifeLink API
actor db Organizations table
msg browser -> cognito redirect with code challenge
msg cognito -> browser authorization code
msg browser -> cognito exchange code and verifier
msg cognito -> browser access and id tokens
msg browser -> api request with bearer token
msg api -> cognito fetch JWKS once and cache
msg api -> db load roles and account status
msg db -> api authoritative principal
note The browser never holds a client secret, which is why PKCE exists.
```

*Figure 7.1. The sign-in flow. The code-plus-verifier exchange means an
intercepted authorization code is useless without the verifier.*

The step that matters most for LifeLink's security model is the last one. The
token proves *who* the caller is. It does **not** decide *what they may do*:

```python
@dataclass
class Authenticator:
    """Turns a raw Authorization header into a Principal."""

    verifier: TokenVerifier
    directory: UserDirectory
    #: Creates a minimal profile for a verified subject we have not seen.
    #: Optional so tests and the local path can omit it; when absent, an
    #: unknown subject is refused exactly as before.
    provisioner: Callable[..., object] | None = None

    def authenticate(self, authorization_header: str | None) -> Principal:
        if not authorization_header:
            return ANONYMOUS
        parts = authorization_header.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            raise UnauthenticatedError("Authorization header must be 'Bearer <token>'")

        claims = self.verifier.verify(parts[1])
        subject = claims.get("sub")
        if not subject:
            raise UnauthenticatedError("token has no subject claim")

        # Authoritative state comes from our own store, not from the token.
        principal = self.directory.get_principal(subject)

        if principal is None:  # noqa: SIM102 - the inner condition has its own rationale below
            # A valid token from a user pool account we have never seen. This
            # used to be a dead end -- "authenticated subject has no LifeLink
            # account" -- which anyone who signed up through Cognito hit on
            # their very first request, with nothing in the product able to
            # fix it.
            #
            # Provision a minimal profile instead: DONOR role, no
            # organization. The role assignment is the security property here.
            # A hospital or blood bank role would reach other organizations'
            # data, so those are never self-assigned; they are granted by an
            # administrator after verification. No organization means every
            # organization-scoped check refuses by construction.
            #
            # Only ever reached for a token this service has already verified
            # against the pool's keys, so the subject is genuine.
            if self.provisioner is not None:
                self.provisioner(
                    user_id=subject,
                    email=claims.get("email"),
                    display_name=claims.get("name") or claims.get("username"),
                )
                principal = self.directory.get_principal(subject)

        if principal is None:
            raise UnauthenticatedError("authenticated subject has no LifeLink account")
        return principal
```

*Listing 7.1. The authenticator, from `backend/src/appcore/auth.py`. Note the
final step: the principal is loaded from the database, not constructed from
token claims.*

## 7.4 Where it sits

Cognito is consulted at two moments: interactively, when a user signs in; and
programmatically, when the API fetches the JSON Web Key Set to verify a
signature. The JWKS is cached, so steady-state request handling makes no call
to Cognito at all.

## 7.5 Configuration that matters

| Setting | Value | Why |
|---|---|---|
| `GenerateSecret` | `false` | A browser cannot keep a secret; PKCE replaces it |
| `AllowedOAuthFlows` | `code` | Implicit flow puts tokens in the URL |
| Password minimum | 12 characters, mixed classes | Longer beats complex, so both |
| `AccessTokenValidity` | 1 hour | Short enough to limit a leaked token |
| `RefreshTokenValidity` | 30 days | Balances convenience against revocation lag |
| `PreventUserExistenceErrors` | `ENABLED` | Stops account enumeration via error text |
| `EnableTokenRevocation` | `true` | Allows immediate sign-out everywhere |
| MFA | `OPTIONAL`, TOTP | Required by policy for privileged roles |
| `AttributesRequireVerificationBeforeUpdate` | `[email]` | Stops silent account takeover by email change |

*Table 7.1. Cognito configuration and the reasoning behind each value.*

## 7.6 What secures it

Tokens are RS256-signed; LifeLink verifies the signature against the pool's
JWKS, checks the issuer, the expiry and the `token_use` claim, and rejects
anything that fails. The `kid` header selects the key, and an unknown `kid`
triggers exactly one JWKS refresh rather than a fetch per request.

## 7.7 What can fail

| Failure | Effect | Handling |
|---|---|---|
| Cognito unavailable | New sign-ins fail | Existing valid tokens continue to work until expiry |
| JWKS fetch fails | Token verification fails | Cached keys are used; failure returns 401, logged |
| Token expired | Request rejected | 401 with `UNAUTHENTICATED`; client refreshes |
| Token valid, account suspended | Request rejected | 403 `ACCOUNT_SUSPENDED` — the database decides |
| Role changed mid-session | Next request uses the new role | Roles read per request, not from the token |

*Table 7.2. Cognito failure modes.*

The third and fourth rows are the interesting pair. A system that trusts token
claims cannot distinguish them: both present a valid, unexpired, correctly
signed token. LifeLink can, because it treats the token as proof of identity
only.

## 7.8 Cost

Cognito's free tier covers 50,000 monthly active users for user pools. For a
demonstration system the cost is effectively zero. Advanced security features
are chargeable and are not enabled.

## 7.9 The alternative considered

**Hand-rolled authentication with JWTs signed by the application.** Rejected.
It would require implementing password storage, reset flows, MFA and revocation,
each a well-known source of vulnerabilities, in exchange for no capability
LifeLink needs.

**An API Gateway JWT authorizer alone.** Partially adopted — it is a sensible
outer layer — but rejected as the only mechanism, because it cannot check
account status or resource ownership. It would happily admit a suspended user.

<!-- pagebreak -->

# 8. Amazon API Gateway

## 8.1 What it is

A managed front door for APIs: TLS termination, routing, throttling, access
logging and integration with Lambda, without running a load balancer or web
server.

## 8.2 Why LifeLink uses it, and which variant

API Gateway offers REST APIs and HTTP APIs. LifeLink uses the **HTTP API**.

| Consideration | REST API | HTTP API | LifeLink needs it? |
|---|---|---|---|
| Cost per million requests | Higher | ~70% lower | Yes, cost matters |
| Latency overhead | Higher | Lower | Yes |
| Request validators | Yes | No | No — validation is in the handler |
| Usage plans and API keys | Yes | No | No — no third-party API consumers |
| AWS WAF integration | Yes | No | Not at this tier |
| Private endpoints | Yes | No | No |

*Table 8.1. Why the HTTP API variant was chosen.*

Nothing LifeLink does needs a REST-only feature. Choosing the more expensive
variant anyway would be paying for capability that no part of the design uses.

## 8.3 How it works here

One proxy route sends everything to a single Lambda function, which does its own
routing. That is a deliberate choice over defining 50 separate API Gateway
routes and 50 functions.

| Approach | Cold starts | IAM granularity | Template size | Chosen |
|---|---|---|---|---|
| One function per route | ~50 cold-start surfaces | Per-route policies | Very large | No |
| One proxy function | One warm container serves all | One policy set | Compact | **Yes** |

*Table 8.2. Routing granularity.*

At a concurrency ceiling of 10, fifty separate
functions would be actively harmful: each has its own cold-start cost and its
own share of a pool that cannot stretch. One function keeps containers warm
across the whole API surface.

The trade-off is coarser IAM. The single API function holds the union of
permissions its routes need. That is mitigated by authorization being enforced
in the application on every request, and by the audit table's write-only grant.

## 8.4 Configuration that matters

```yaml
DefaultRouteSettings:
  DetailedMetricsEnabled: true
  # Below the account's Lambda ceiling of 10, so API Gateway sheds load
  # before Lambda starts throttling.
  ThrottlingBurstLimit: 20
```

*Listing 8.1. Throttling, set below the Lambda ceiling on purpose.*

The throttle is set to 10 requests per second with a burst of 20 — at or below
the account's concurrency ceiling. API Gateway therefore sheds load with a clean
429 before Lambda starts throttling, which produces a better client experience
and a clearer signal in metrics.

Access logging deliberately excludes request bodies and query strings, both of
which can carry personal data.

## 8.5 What can fail, and how it is handled

| Failure | Status | Handling |
|---|---|---|
| Throttle exceeded | 429 | Client backs off; `isRetryable` is true in the API client |
| Lambda timeout | 504 | Handler timeout is 29s, inside the gateway's limit |
| Handler raises | 500 | Error is logged with correlation id; no internals leak |
| Unknown path | 404 | Distinguished from 405 for a known path, wrong method |

*Table 8.3. API Gateway failure handling.*

## 8.6 Cost and alternatives

HTTP API costs roughly $1.00 per million requests in this region. A demo
workload sits inside the free tier.

**Application Load Balancer with Lambda targets** was considered. It costs a
fixed hourly charge whether or not traffic arrives, which is the wrong shape for
bursty, low-volume usage. **Lambda function URLs** were considered and rejected:
no throttling, no access logging, and no central place to apply CORS.

<!-- pagebreak -->

# 9. AWS Lambda

## 9.1 What it is

Managed compute that runs a function in response to an event, with no server to
provision, and billing by millisecond of execution.

## 9.2 Why LifeLink uses it

The workload is bursty and mostly idle. A demonstration system that nobody is
using should cost nothing, and a facility search arriving at 3am should still be
served. That is precisely the shape Lambda suits.

## 9.3 The functions

| Function | Trigger | Purpose | Timeout |
|---|---|---|---|
| `api` | API Gateway | All 58 routes | 29s |
| `notification-worker` | SQS | Deliver queued notifications | 29s |
| `work-worker` | SQS | Alert matching on stock change | 29s |
| `outbox-publisher` | DynamoDB stream | Publish outbox rows to SQS | 29s |
| `dispatcher` | EventBridge, 1 minute | Priority scheduling for emergencies | 29s |
| `maintenance` | EventBridge, 10 minutes | Expiry sweep, reminders | 300s |

*Table 9.1. The six Lambda functions.*

## 9.4 Runtime and architecture

Runtime `python3.14` on `arm64`. Two reasons for each.

The runtime matches the local interpreter exactly (3.14.2),
which removes an entire category of "works on my machine" failure: a dependency
that imports locally imports in Lambda. Python 3.14 is generally available with
support to June 2029; Python 3.15 exists but is in public preview and is
explicitly outside the Lambda SLA, so it is not used.

Graviton (`arm64`) is roughly 20% cheaper per millisecond at equivalent
performance for this kind of workload, and every dependency LifeLink uses
publishes `aarch64` wheels.

## 9.5 The concurrency ceiling, and designing within it

:::warning This is the single most consequential constraint in the project
The account permits 10 concurrent executions in total,
across every function. The AWS default is
1000.
:::

Four design decisions follow directly:

**No function reserves concurrency.** Reserved concurrency is subtracted from
the shared pool. Reserving two for the dispatcher would leave eight for
everything else, including the synchronous API tier that a user is waiting on.

**Queue consumers cap their own parallelism.** Each SQS event source sets
`MaximumConcurrency: 2` and a batch size of 5. Without that, a backlog of
messages would consume the entire pool and the API would start returning 429s
while a background job drained.

**The dispatcher is one scheduled invocation, not a pool of consumers.** This
reinforces the conclusion Chapter 18 reaches on other grounds.

**Throttling is an expected condition, not an exception.** The DynamoDB client
uses adaptive retries, SQS consumers report partial batch failures so only the
failed messages return, and a CloudWatch alarm fires on the first throttle.

```python
def _resource():
    endpoint = os.environ.get("DYNAMODB_ENDPOINT")
    region = os.environ.get("AWS_REGION", "ap-southeast-2")
    kwargs: dict[str, Any] = {
        "region_name": region,
        # Retries matter at this account's concurrency ceiling (ADR-0014):
        # throttling is an expected condition, not an exceptional one.
        "config": Config(retries={"max_attempts": 5, "mode": "adaptive"}),
    }
    if endpoint:
        kwargs["endpoint_url"] = endpoint
        kwargs.setdefault("aws_access_key_id", os.environ.get("AWS_ACCESS_KEY_ID", "local"))
        kwargs.setdefault("aws_secret_access_key", os.environ.get("AWS_SECRET_ACCESS_KEY", "local"))
    return boto3.resource("dynamodb", **kwargs)


```

*Listing 9.1. Adaptive retries configured in `backend/src/repositories/dynamo.py`,
with the reasoning recorded where a future reader will see it.*

## 9.6 Cold starts

A Python Lambda with boto3 and a handful of pure-Python dependencies typically
cold-starts in a few hundred milliseconds. LifeLink reduces the frequency and
cost of that:

- One function serves the whole API, so warm containers are reused widely.
- The service object graph is built once per container and cached with
  `functools.lru_cache`, not rebuilt per invocation.
- MapLibre and other heavy frontend assets are, of course, not in the Lambda
  package at all.
- SnapStart is not used: it is not available for Python runtimes.

## 9.7 What can fail

| Failure | Handling |
|---|---|
| Throttled | 429 to client; alarm fires; consumers retry with backoff |
| Timeout | 504; the 29s limit sits inside API Gateway's |
| Unhandled exception | Generic 500 to the client, full detail to logs |
| Crash mid-transaction | DynamoDB transaction either committed or did not |
| Crash after commit, before publish | Impossible: the outbox row is in the transaction |

*Table 9.2. Lambda failure modes.*

The last two rows are the payoff from the transactional outbox, and Chapter 22
explains the mechanism.

## 9.8 Cost

The free tier covers 1 million requests and 400,000 GB-seconds monthly. At 512 MB
and an assumed 200 ms average duration, that is roughly 4 million invocations of
headroom. A demonstration workload costs nothing.

## 9.9 Alternatives considered

**Fargate or ECS.** Rejected: a container running continuously costs money while
idle, and there is no long-running process to host.

**EC2.** Rejected for the same reason, with added patching and capacity
management.

**Lambda@Edge.** Unavailable on this account, and not needed — there is no
request-time logic that must run at the edge.

<!-- pagebreak -->

# 10. DynamoDB Fundamentals

Before the LifeLink data model makes sense, five DynamoDB properties need to be
clear, because every design decision in the next chapter is a response to one
of them.

## 10.1 The five properties that shape everything

**1. You query by key, not by predicate.** A `Query` must supply an exact
partition key. It may add a condition on the sort key. It cannot say "find rows
where expiry is soon" without a key that already organises rows that way. This
is why LifeLink has 24 secondary indexes: each one exists
because some question needed a different key.

**2. A `Scan` reads the whole table.** It is not a slow query; it is a different
operation with unbounded cost. LifeLink forbids scans on user-facing paths. The
two places that scan — demo data wiping and dataset validation — are offline
maintenance jobs, and one of them logs that it scanned.

**3. Writes can be conditional.** `PutItem`, `UpdateItem` and `DeleteItem`
accept a `ConditionExpression` evaluated atomically at the item. This single
feature is how LifeLink prevents lost updates, negative stock, duplicate
registration and double credit, without any lock.

**4. Transactions span items, at a price.** `TransactWriteItems` commits up to
100 items atomically across tables, at twice the write cost. LifeLink uses it
only where an invariant genuinely spans items.

**5. Secondary indexes are eventually consistent.** Always. A write visible in
the base table may not yet be visible through a GSI. Any design that assumes
otherwise is wrong, and Section 11.7 explains where LifeLink absorbs that.

## 10.2 Partition keys and heat

A partition key determines physical placement. A key that concentrates traffic
creates a hot partition and throttles regardless of table-level capacity.

LifeLink's expiry sweep is the natural hot-key hazard: "find batches expiring
before now" wants a single key. The design shards it:

```python
def expiry_shard(batch_id: str) -> int:
    """Spread the expiry sweep across partitions so it cannot create a hot key."""
    digest = hashlib.sha256(batch_id.encode()).digest()
    return digest[0] % EXPIRY_SHARDS
```

*Listing 10.1. Expiry sharding from `backend/src/repositories/inventory_repo.py`.
Ten shards, each swept independently.*

## 10.3 Composite sort keys do filtering for free

The most useful DynamoDB technique in this codebase is encoding several
attributes into a sort key so a range condition replaces a filter expression.

A filter expression is applied *after* items are read and billed. A sort-key
condition is applied *during* the read. For eligible-stock lookup the
difference is between reading every batch at a facility and reading only the
available, unexpired ones.

```
GSI1PK = FACILITY#<id>#<group>#<component>
GSI1SK = STATUS#<status>#<expiresAt>
```

A query for `GSI1SK between "STATUS#AVAILABLE#<now>"` and
`"STATUS#AVAILABLE#9999-..."` returns exactly the available, unexpired batches.
Quarantined, withdrawn and expired rows sort under different status prefixes
and are never read at all — they cannot leak into an availability answer by
accident, because the index never hands them over.

```python
def list_eligible_batches(
    self, facility_id: str, group: BloodGroup, component: Component, *, now: datetime
) -> list[Batch]:
    """Query AVAILABLE batches that have not yet expired.

    The range condition does the filtering: because GSI1SK is
    ``STATUS#<status>#<expiry>``, everything from ``STATUS#AVAILABLE#<now>``
    upward is available stock expiring in the future. Quarantined, expired
    and withdrawn rows sort under different status prefixes and are never
    read -- they cannot leak into an availability answer by accident.
    """
    lower = f"STATUS#{BatchStatus.AVAILABLE.value}#{to_iso(now)}"
    upper = f"STATUS#{BatchStatus.AVAILABLE.value}#9999-12-31T23:59:59Z"
    condition = Key("GSI1PK").eq(
        _gsi1_pk(facility_id, group.value, component.value)
    ) & Key("GSI1SK").between(lower, upper)

    items = self.query_all(key_condition=condition, index_name="GSI1-group-component")
    # The index projection is partial, so hydrate from the base table only
    # what we actually need for aggregation.
    return [
        Batch(
            batch_id=i["batchId"],
            facility_id=facility_id,
            organization_id=i.get("organizationId", ""),
            blood_group=group,
            component=component,
            available_units=int(i["availableUnits"]),
            status=BatchStatus(i["status"]),
            collected_at=None,
            expires_at=parse_iso(i.get("expiresAt")),
            last_updated_at=parse_iso(i["lastUpdatedAt"]),
            last_verified_at=parse_iso(i.get("lastVerifiedAt")),
            update_source="INDEX",
            version=0,
        )
        for i in items
    ]
```

*Listing 10.2. The eligible-stock query. The comment explains the property that
makes it safe, not just what the code does.*

## 10.4 Capacity mode

Every table uses `PAY_PER_REQUEST`. Provisioned capacity would require
predicting throughput for a system with no traffic history, and would charge
for idle capacity. On-demand costs more per request but nothing at rest, which
matches a demonstration workload exactly.

<!-- pagebreak -->

# 11. The LifeLink Data Model

## 11.1 Why eleven tables rather than one

Single-table design is the conventional advice for DynamoDB, and LifeLink
deliberately does not follow it at the top level. The reasoning is recorded as
ADR-0001 and is worth restating, because it is the design's most contestable
decision.

| Consideration | Single table | Table per context | Winner here |
|---|---|---|---|
| Cross-entity reads in one query | Excellent | Needs two calls | Single table |
| IAM-enforced domain isolation | Impossible | Natural | **Per context** |
| Per-domain TTL policy | Awkward | Trivial | **Per context** |
| Per-domain backup policy | All or nothing | Independent | **Per context** |
| Blast radius of a bad migration | Whole system | One domain | **Per context** |
| Teaching clarity | Poor | Good | **Per context** |

*Table 11.1. The trade-off, made explicitly.*

The deciding factor is the second row. With one table, "Feature 3 must not
touch inventory" is a code-review convention. With separate tables it is an IAM
policy, and the platform enforces it whether or not anyone is paying attention.

Single-table techniques are still used *within* a context. A camp's metadata,
its registrations and its staff assignments share one partition, so an organiser
dashboard loads in a single query.

## 11.2 Access patterns

Thirty-nine access patterns were enumerated before any table was created. The
full catalogue is in `docs/DATABASE_DESIGN.md`; this is the structure.

| Feature | Patterns | Index used | Any scans? |
|---|---|---|---|
| Inventory | 7 | Base table, GSI1 group-component, GSI2 expiry | None |
| Availability alerts | 4 | GSI1 user, GSI2 match | None |
| Facilities | 4 | Three geohash GSIs, org GSI, verification GSI | None |
| Camps and donors | 9 | Base partition, geo, user, organizer, reminder | None |
| Emergency | 6 | Dispatch, requester, provider, deadline | None |
| Platform | 9 | Base, actor, delivery status, pending outbox | None |

*Table 11.2. Access patterns by feature. Every one resolves to a key query.*

## 11.3 The inventory table in detail

```diagram
type: layered
title: Inventory table and its two indexes
layer Base table
node base PK FACILITY id and SK BATCH id style=data
layer Index one
node gsi1 GSI1 group and component with status and expiry sort style=data
layer Index two
node gsi2 GSI2 sharded expiry sweep keys only style=data
layer Consumers
node avail Availability queries style=domain
node sweep Scheduled expiry sweep style=domain
node audit Batch audit history style=domain
edge base -> gsi1
edge base -> gsi2
edge gsi1 -> avail
edge gsi2 -> sweep
edge base -> audit
```

*Figure 11.1. One base table, two purpose-built indexes, three consumers.*

The index projections are chosen rather than defaulted:

- **GSI1** projects `INCLUDE` with exactly the seven attributes availability
  aggregation needs. `KEYS_ONLY` would force a base-table read per batch;
  `ALL` would double storage for attributes nobody reads on that path.
- **GSI2** projects `KEYS_ONLY`. The sweep only needs to know which batches to
  look at, and then reads them properly.

## 11.4 The emergency table and priority ordering

The dispatch index demonstrates a technique worth noticing:

```
GSI1PK = DISPATCH#<status>
GSI1SK = <effectivePriority>#<createdAt>
```

Querying that index in ascending sort order returns requests in priority order,
and FIFO within a priority band, with no sorting in application code. Priority
aging — raising a long-waiting request's dispatch priority — is implemented by
rewriting one attribute, which re-sorts the item in the index automatically.

Crucially, `effectivePriority` is a *different field* from `clinicalPriority`.
The scheduler writes the former and never the latter. Chapter 18 explains why
that separation is not merely tidy but a safety property.

## 11.5 Concurrency invariants and how each is enforced

| Invariant | Mechanism | Fails how |
|---|---|---|
| Stock never negative | `availableUnits >= :needed` condition | 409 `INSUFFICIENT_STOCK` |
| No lost inventory update | `version = :expected` condition | 409 `CONCURRENT_MODIFICATION` |
| No duplicate registration | `attribute_not_exists(SK)` | 409 `DUPLICATE` |
| Camp never oversubscribed | Transaction: registration put **and** counter update with capacity condition | 409 `CAPACITY_EXCEEDED` |
| Impact credited exactly once | Transaction: donation update **and** ledger put keyed on donation id | Transaction cancelled |
| No duplicate event processing | Idempotency claim keyed on event id | Second delivery is a no-op |
| Event never lost on crash | Outbox row in the same transaction as the domain write | Cannot occur |
| Stale update cannot overwrite | Source timestamp compared to stored | 400 with `STALE_UPDATE_REJECTED` |

*Table 11.3. Eight invariants, each enforced by the datastore rather than by
convention.*

The camp capacity row deserves a worked example because read-check-write is the
intuitive and wrong approach.

```diagram
type: sequence
title: Two donors claim the final seat at the same instant
actor a Donor A
actor b Donor B
actor svc Camp service
actor ddb DynamoDB
msg a -> svc register
msg b -> svc register
msg svc -> ddb A transaction put registration and increment under capacity
msg svc -> ddb B transaction put registration and increment under capacity
msg ddb -> svc A committed
msg ddb -> svc B cancelled condition failed
msg svc -> b capacity exceeded
note Both passed the advisory pre-check. Only the transaction decides.
```

*Figure 11.2. The capacity transaction. The service performs a friendly
pre-check for a good error message, but the transaction is authoritative.*

```python
def register_atomically(
    self,
    *,
    camp_id: str,
    user_id: str,
    capacity: int,
    now: datetime,
    registration: dict,
) -> dict:
    """Create the registration and increment the counter in one transaction.

    Two concurrent requests for the final seat cannot both succeed: the
    capacity condition is evaluated inside the transaction, so exactly one
    commits and the other is cancelled. A plain read-check-write would let
    both through.
    """
    camps_table = table_name(self.logical_table)
    item = {
        "PK": _camp_pk(camp_id),
        "SK": f"REG#{user_id}",
        "GSI2PK": f"USER#{user_id}",
        "GSI2SK": f"REG#{now.isoformat()}#{camp_id}",
        "entityType": "REGISTRATION",
        "campId": camp_id,
        "userId": user_id,
        "registeredAt": to_iso(now),
        "status": "REGISTERED",
        "attendanceStatus": "NOT_ATTENDED",
        **registration,
    }

    operations = [
        {
            "Put": {
                "TableName": camps_table,
                "Item": to_dynamo(clean(item)),
                # Duplicate registration is impossible, not merely unlikely.
                "ConditionExpression": "attribute_not_exists(SK)",
            }
        },
        {
            "Update": {
                "TableName": camps_table,
                "Key": to_dynamo({"PK": _camp_pk(camp_id), "SK": "META"}),
                "UpdateExpression": "SET registeredCount = registeredCount + :one",
                "ConditionExpression": (
                    "attribute_exists(PK) AND registeredCount < :capacity "
                    "AND #s IN (:upcoming, :ongoing)"
                ),
                "ExpressionAttributeNames": {"#s": "status"},
                "ExpressionAttributeValues": to_expression_values(
                    {
                        ":one": 1,
                        ":capacity": capacity,
                        ":upcoming": "UPCOMING",
                        ":ongoing": "ONGOING",
                    }
                ),
            }
        },
    ]

    try:
        transact_write(operations)
    except Exception as exc:
        existing = self.get_registration(camp_id, user_id)
        if existing is not None:
            raise DuplicateError(
                "you are already registered for this camp",
                details={"campId": camp_id},
            ) from exc
        raise CapacityExceededError(
            "this camp is full or no longer accepting registrations",
            details={"campId": camp_id},
        ) from exc

    return item
```

*Listing 11.1. The capacity transaction from
`backend/src/repositories/camp_repo.py`.*

## 11.6 Pagination

Cursor-based throughout. The cursor is an opaque base64 encoding of DynamoDB's
`LastEvaluatedKey` **plus a fingerprint of the query that produced it**. A
cursor presented against a different query is rejected rather than silently
producing wrong results.

Offset pagination is not offered. DynamoDB cannot do it efficiently, and
emulating it would mean reading and discarding rows — a scan wearing a disguise.

## 11.7 Living with eventual consistency

GSIs are eventually consistent, always. LifeLink handles that in three ways.

**Where it does not matter, it is ignored.** A facility search that misses a
batch written 50 milliseconds ago is not a problem; the data is seconds old by
nature.

**Where it matters, a strongly consistent base-table read is used.** Re-reading
a batch after a failed conditional write uses `ConsistentRead`, because the
retry must see the value that beat it.

**Where it could cause duplicate work, idempotency absorbs it.** The dispatcher
reads a GSI and may see a request it has already picked up. That is harmless:
the work is idempotent, so the second attempt is a no-op.

## 11.8 Retention, backup and recovery

| Data | Retention | PITR | Reasoning |
|---|---|---|---|
| Audit | 7 years (assumed, pending legal review) | Yes, CMK-encrypted | Regulatory posture |
| Donations and ledger | Indefinite while the account lives | Yes | Donor's own record |
| Inventory | Indefinite; status transitions, no deletion | Yes | Historical traceability |
| Camps and emergency | Indefinite | Yes | Audit and dispute resolution |
| Alerts | TTL at the alert's expiry | No | Short-lived by nature |
| Notifications | TTL at 90 days | No | Reconstructible |
| Idempotency | TTL at 24 hours | No | Reconstructible by definition |
| Outbox | TTL at 7 days after dispatch | No | Transient |

*Table 11.4. Retention and recovery by data class.*

Three tables deliberately have no point-in-time recovery. That is not an
oversight: PITR on a TTL-bound, fully reconstructible table is spend with no
recovery value.

## 11.9 What the data model does not do

Stated so no reader infers capability that is absent:

- **No allocation or clinical-release model.** A reservation holds units for a
  bounded time; it is not a cross-match, not clinical approval and not a
  guarantee of release, and those stay with qualified staff. Temporary
  reservations themselves *are* modelled — see ADR-0018 and §28.7. An earlier
  edition said "no reservation or allocation model", which was true then.
- **No cross-region replication.** Unavailable on this account.
- **No analytics or read-model store.** Dashboard aggregates are computed per
  request. At real scale this would need a projection, and that is recorded as
  future work rather than described as if it exists.
- **No real institutional data path.** Only verified onboarding or authorized
  staff updates may introduce real data. Everything currently in the system is
  synthetic and labelled as such.

<!-- pagebreak -->

# 12. Amazon S3 and CloudFront

## 12.1 What they are

S3 is durable object storage. CloudFront is a content delivery network that
caches at edge locations and terminates TLS close to the user.

## 12.2 Why LifeLink uses them

The frontend is a static bundle: HTML, JavaScript, CSS. Serving it from a web
server would mean operating a web server. S3 stores it, CloudFront distributes
it, and neither needs patching.

LifeLink uses two buckets with different purposes and different policies:

| Bucket | Contents | Public? | Versioning | Lifecycle |
|---|---|---|---|---|
| `frontend` | Built static assets | No — CloudFront only | Yes | Expire old versions after 30 days |
| `uploads` | Private user files | No — presigned URLs only | Yes | Abort incomplete uploads after 7 days |

*Table 12.1. The two buckets.*

## 12.3 Origin Access Control, not public read

The frontend bucket blocks all public access. CloudFront reaches it through
Origin Access Control, and the bucket policy permits exactly one principal —
the CloudFront service — and only when the request comes from this specific
distribution:

```yaml
FrontendBucketPolicy:
  Type: AWS::S3::BucketPolicy
  Properties:
    Bucket: !Ref FrontendBucket
    PolicyDocument:
      Version: '2012-10-17'
      Statement:
        - Effect: Allow
          Principal: { Service: cloudfront.amazonaws.com }
          Action: 's3:GetObject'
          Resource: !Sub '${FrontendBucket.Arn}/*'
          Condition:
            StringEquals:
              'AWS:SourceArn': !Sub 'arn:aws:cloudfront::${AWS::AccountId}:distribution/${FrontendDistribution}'

FrontendDistribution:
```

*Listing 12.1. The bucket policy. The `AWS:SourceArn` condition is the part
that matters: without it, any CloudFront distribution in any account could read
the bucket.*

## 12.4 Single-page application routing

A React application with client-side routing has a problem on static hosting: a
direct request for `/camps/abc123` asks S3 for an object that does not exist.
S3 returns 403 (because the bucket blocks listing) and the user sees an error
instead of the application.

The distribution maps 403 and 404 to `/index.html` with a 200 status and a
10-second cache, so deep links load the application, which then routes
client-side.

## 12.5 Cache strategy

The AWS managed `CachingOptimized` policy is used for static assets. This is
safe because Vite emits content-hashed filenames: `index-OxJqrZe4.js` changes
whenever its contents change, so a long cache lifetime never serves stale code.
`index.html` itself is the exception and is short-cached.

The API is deliberately **not** behind CloudFront. Caching a blood availability
response would directly undermine the product's purpose, and the freshness
labelling that the whole design turns on would start describing the cache rather
than the facility.

## 12.6 What can fail

| Failure | Effect | Handling |
|---|---|---|
| Origin unreachable | Cached assets still served | CloudFront serves from edge |
| Distribution misconfigured | Application does not load | Caught at deployment validation |
| Presigned URL expires | Upload or download fails | Short expiry by design; client requests a new one |
| Bucket policy wrong | 403 on every asset | `AWS:SourceArn` condition is template-managed |

*Table 12.2. S3 and CloudFront failure modes.*

## 12.7 Cost

S3 storage for a built frontend is a few megabytes — fractions of a cent.
CloudFront's free tier covers 1 TB of transfer monthly. `PriceClass_100`
restricts edge locations to the cheaper regions, which is appropriate for a
system whose users are in one country.

## 12.8 Alternatives

**S3 static website hosting** without CloudFront was considered and rejected:
it requires public bucket access, offers no TLS on a custom domain, and
provides no SPA fallback routing. **AWS Amplify Hosting** would work and is
simpler, but hides the CloudFront and S3 configuration that this project is
partly meant to demonstrate.

<!-- pagebreak -->

# 13. Amazon SQS and Dead-Letter Queues

## 13.1 What it is

A managed message queue with at-least-once delivery, configurable visibility
timeouts, and automatic redrive to a dead-letter queue after a configured number
of failed receives.

## 13.2 Why LifeLink uses it

Three things must happen after a stock change: the response must return
quickly, waiting donors must be matched, and notifications must be delivered.
Only the first is the user's concern. SQS decouples the other two from the
request.

## 13.3 Queue topology

```diagram
type: layered
title: Queues, consumers and dead letters
layer Producers
node api API function style=aws
node pub Outbox publisher style=aws
layer Queues
node work Work queue style=aws
node notif Notification queue style=aws
layer Consumers
node wkw Work worker alert matching style=aws
node nw Notification worker delivery style=aws
layer Failure
node wdlq Work dead letter queue style=external
node ndlq Notification dead letter queue style=external
layer Operations
node alarm CloudWatch alarms on both DLQs style=aws
edge api -> work
edge pub -> work
edge pub -> notif
edge work -> wkw
edge notif -> nw
edge work -> wdlq
edge notif -> ndlq
edge wdlq -> alarm
edge ndlq -> alarm
```

*Figure 13.1. Two queues, two consumers, two dead-letter queues, both alarmed.*

## 13.4 Configuration that matters

| Setting | Value | Reasoning |
|---|---|---|
| Visibility timeout | 180s | Six times the 29s consumer timeout, per AWS guidance |
| `maxReceiveCount` | 5 | Enough for transient failures, not so many that a poison message churns |
| DLQ retention | 14 days | The maximum: a human needs time to investigate |
| Batch size | 5 | Small, so one bad message blocks little |
| `MaximumConcurrency` | 2 | Leaves room in a pool of 10 |
| `FunctionResponseTypes` | `ReportBatchItemFailures` | Only failed messages return to the queue |
| Encryption | SQS-managed SSE | At rest, no key management overhead |

*Table 13.1. SQS settings and why each value was chosen.*

The partial-batch-failure setting deserves emphasis. Without it, one failing
message in a batch of five causes all five to be retried, including the four
that succeeded — which at best duplicates work and at worst, without
idempotency, duplicates effects.

```python
def notification_handler(event: dict, lambda_context=None) -> dict:
    """Send queued notifications.

    A queue write is not a delivery (spec 10.3), so this is where delivery
    actually happens and where its real status is recorded.
    """
    now = now_utc()
    services = get_services()
    failures: list[dict] = []

    for record in event.get("Records", []):
        message = _parse_record(record)
        correlation_id = message.get("correlationId") or new_correlation_id()
        log = get_logger(__name__, system_context(correlation_id))
        event_id = message.get("eventId", "")

        try:
            if not _claim(event_id, "notify", now):
                log.info("duplicate notification suppressed",
                         event="worker.notify.duplicate", eventId=event_id)
                continue

            payload = message.get("payload", message)
            outcome = services.notifications.notify(
                user_id=payload["userId"],
                category=payload.get("category", "ACCOUNT_NOTICE"),
                subject=payload.get("subject", "LifeLink notification"),
                body=payload.get("body", ""),
                now=now,
                metadata=payload.get("metadata"),
                dedupe_key=payload.get("dedupeKey"),
            )
            _complete(event_id, "notify", outcome.to_dict(), now)
            log.info("notification processed", event="worker.notify.done",
                     delivered=outcome.any_delivered, suppressed=outcome.suppressed)
        except Exception as exc:
            log.exception("notification failed", event="worker.notify.failed",
                          error=str(exc)[:300])
            failures.append({"itemIdentifier": record.get("messageId", "")})

    return {"batchItemFailures": failures}
```

*Listing 13.1. A consumer that reports partial failures, from
`backend/src/handlers/workers.py`. Note the duplicate check before any work and
the per-message failure collection.*

## 13.5 At-least-once is not a defect

SQS guarantees at-least-once delivery. A message *will* occasionally arrive
twice. Treating that as an error to be eliminated is the wrong instinct; the
correct response is to make consumers idempotent, which LifeLink does with a
claim keyed on the event id.

:::key Design for duplicates, not against them
Every consumer in LifeLink asks "have I already done this?" before doing
anything. A duplicate delivery is logged at info level as a suppressed
duplicate, not as a failure, because it is normal operation.
:::

## 13.6 What can fail

| Failure | Effect | Handling |
|---|---|---|
| Consumer raises | Message returns after visibility timeout | Retried up to 5 times |
| Message fails 5 times | Moved to DLQ | Alarm fires within 5 minutes |
| Consumer throttled | Message returns | Retried; concurrency cap limits the blast |
| Backlog grows | Oldest-message age rises | Alarm at 5 minutes |
| Poison message | Isolated by partial batch failure | Reaches DLQ alone, not with its batch |

*Table 13.2. Queue failure modes.*

## 13.7 Cost

The free tier covers 1 million requests monthly. SQS is one of the cheapest
services in the design.

## 13.8 Alternatives

**EventBridge event bus** was considered. It has better routing and schema
support, but SQS gives per-consumer dead-letter queues and visibility-timeout
retry semantics that match the specification's requirements more directly. The
outbox makes switching later a change in one publisher, not a redesign.

**Step Functions** would model the emergency workflow explicitly. Chapter 3
explains why it was not adopted.

<!-- pagebreak -->

# 14. Notifications with SNS and SES

## 14.1 What they are

SNS is pub/sub messaging, used here for operational alarms. SES is an email
sending service, used for user notifications.

## 14.2 The channel model

The specification requires a reusable notification subsystem supporting user
preferences and consent. LifeLink implements channels behind an interface:

| Channel | Implementation | Status |
|---|---|---|
| In-app | DynamoDB record the dashboard reads | Implemented |
| Email | Amazon SES | Implemented, sandbox-limited |
| SMS | — | **NOT IMPLEMENTED** |
| Local file | Writes to `.local-outbox/` | Local development only |

*Table 14.1. Notification channels and their honest status.*

## 14.3 Why SMS is absent

:::warning SMS is not implemented, and is not pretending to be
AWS End User Messaging SMS is a Paid-Plan service, and this account's service
control policy denies `sms-voice:*` outright. Phase 0 verified this by calling
`sns:GetSMSAttributes` and receiving an explicit deny naming the policy.

LifeLink therefore has an `UnavailableSmsChannel` whose only behaviour is to
raise `CHANNEL_UNAVAILABLE` with the reason. It does not silently succeed, and
it does not log a pretend send.
:::

```python
class UnavailableSmsChannel:
    """SMS is deliberately not implemented (ADR-0015).

    This class exists so that requesting SMS produces a clear, honest refusal
    instead of a silent no-op that would look like success in the audit trail.
    """

    channel = Channel.SMS

    def send(self, message: Message, *, now: datetime) -> DeliveryResult:
        raise ChannelUnavailableError(
            "SMS delivery is not available for this deployment",
            details={
                "reason": "AWS End User Messaging SMS is a Paid-Plan service and is "
                "denied by the account's service control policy.",
                "implemented": False,
                "alternatives": [Channel.EMAIL.value, Channel.IN_APP.value],
            },
        )
```

*Listing 14.1. A channel that refuses honestly, from
`backend/src/adapters/notifications.py`.*

This is a small piece of code making a large point. The alternative — a stub
that logs "SMS sent" — would produce an audit trail and a delivery-status record
that both lie.

## 14.4 Queueing is not delivery

The specification states that a notification must not be claimed as delivered
merely because it reached a queue. The type system carries that distinction:

```python
@dataclass(frozen=True, slots=True)
class DeliveryResult:
    channel: Channel
    status: DeliveryStatus
    detail: str | None = None
    provider_message_id: str | None = None

    @property
    def delivered(self) -> bool:
        """True only when the provider accepted it. QUEUED is not delivered."""
        return self.status == DeliveryStatus.SENT
```

*Listing 14.2. `QUEUED` and `SENT` are different states, and `delivered` is true
only for the latter.*

## 14.5 Consent and suppression

Before any send, the notification service checks consent, then the category
preference, then a durable duplicate-suppression marker. A suppressed
notification returns an outcome explaining which check stopped it, rather than
failing silently or sending anyway.

| Outcome | Meaning |
|---|---|
| `NO_CONSENT` | The user has never consented; nothing is sent |
| `CATEGORY_OPTED_OUT` | Consented generally, opted out of this category |
| `NO_CHANNELS_SELECTED` | Consented but selected no delivery channel |
| `DUPLICATE_SUPPRESSED` | An identical notification was already sent |

*Table 14.2. Suppression reasons, all reported rather than inferred.*

## 14.6 The SES sandbox

The account's SES is in sandbox (200 messages/day, 1 per second, verified recipients only). For a demonstration this is
adequate, and the limitation is recorded in the known-limitations document
rather than worked around. Production access is a separate request with its own
review.

## 14.7 Cost

SES costs $0.10 per thousand emails after a free allowance. SNS alarm
notifications are effectively free at this volume.

<!-- pagebreak -->

# 15. Amazon Location Service and Map Rendering

## 15.1 What MapLibre is not

MapLibre GL JS is a renderer. It draws vector tiles in a browser. It does not
supply tiles, does not geocode an address, and does not calculate a route.
Conflating the renderer with the data behind it is the most common mistake in
map integrations, and it leads directly to the second most common one:

:::warning Public OpenStreetMap tile servers are not a production tile service
They are run on donated infrastructure for development and light use. Pointing
an application at them is a breach of their usage policy and an operational
dependency on someone else's goodwill. LifeLink does not do it.
:::

## 15.2 What Amazon Location Service provides

Three distinct resources, all verified available in ap-southeast-2 and on
the FREE plan during Phase 0:

| Resource | Purpose | Used by |
|---|---|---|
| Map | Vector tiles and style descriptor | Browser, via scoped credentials |
| Place index | Forward and reverse geocoding | Backend only |
| Route calculator | Road distance and travel time | Backend only |

*Table 15.1. The three Location resources.*

## 15.3 Why tiles go direct and geocoding does not

```diagram
type: layered
title: Two different paths to one provider
layer Browser
node ml MapLibre renderer style=user
layer Credentials
node idp Cognito identity pool temporary credentials style=aws
layer Backend
node api API function style=aws
layer Provider
node tiles Location map tiles style=external
node places Location places and routes style=external
edge ml -> idp
edge idp -> tiles
edge ml -> api
edge api -> places
```

*Figure 15.1. Tiles are fetched directly by the browser using scoped temporary
credentials; geocoding and routing go through the backend.*

Tiles must go direct, because proxying thousands of tile requests through
Lambda would be slow and expensive. The identity pool issues credentials scoped
to exactly four read-only tile actions — `GetMapTile`,
`GetMapStyleDescriptor`, `GetMapSprites`, `GetMapGlyphs` — and nothing else. A
browser holding them cannot geocode, cannot route, and cannot read any other
resource.

Geocoding and routing go through the backend because they are lower-volume,
benefit from caching, and should not be exposed to arbitrary client-side use.

## 15.4 Straight-line distance is never presented as road distance

The specification is explicit, and the type system enforces it:

```python
@dataclass(frozen=True, slots=True)
class RouteResult:
    """A routing answer, or an explicit statement that routing is unavailable.

    ``available=False`` carries ``unavailable_reason`` and leaves the distance
    and duration as None. Callers must handle that instead of defaulting.
    """

    available: bool
    road_km: float | None = None
    duration_minutes: float | None = None
    unavailable_reason: str | None = None
    provider: str | None = None

    @property
    def is_estimate_only(self) -> bool:
        return not self.available
```

*Listing 15.1. A routing result that can say "unavailable" without inventing a
number.*

When routing fails, `RouteResult(available=False)` carries a reason and leaves
distance and duration as `None`. Callers cannot accidentally use a missing
value, and the API response says directions are unavailable instead of
substituting the straight-line figure.

## 15.5 Graceful degradation

The specification requires that a mapping or routing failure must not break
facility discovery. LifeLink degrades in three stages:

1. **Routing fails** — the facility list, distances and contact details all
   survive; the response says directions are unavailable.
2. **Geocoding fails** — place search returns no results with
   `providerAvailable: false`, and the user can enter coordinates directly.
3. **Tiles fail** — the map component renders a usable facility list instead of
   an empty grey rectangle.

In the local environment there is no configured map style at all, so the list
fallback is the *default* path and is exercised constantly rather than being
untested emergency code.

## 15.6 Cost

Amazon Location charges per request: roughly $0.04 per thousand geocoding
requests and $0.50 per thousand map tile loads in this region, with a free tier
for the first months. Map tiles are the dominant cost in any real usage, which
is one more reason the list fallback is a first-class path rather than an
apology.

## 15.7 Alternatives

**OpenRouteService** is permitted by the specification as an optional secondary
routing provider. It was not adopted: a second provider that cannot be verified
end to end in this environment adds a failure mode without adding reliability.
The `RoutingProvider` interface leaves the seam open, which is the point of
having the abstraction.

**Google Maps Platform** would work and has excellent data quality, but
introduces a second vendor relationship, a separate billing arrangement and an
API key that must be kept out of the browser.

<!-- pagebreak -->

# 16. KMS and Secrets Manager

## 16.1 Encryption at rest

Every DynamoDB table and both S3 buckets are encrypted at rest. For most
tables this uses AWS-managed keys, which cost nothing and require no
management. One table is different.

| Resource | Key | Why |
|---|---|---|
| Ten DynamoDB tables | AWS-managed | Adequate; no separate key policy needed |
| `audit` table | Customer-managed, rotating | Separate key policy and separate audit trail of key use |
| S3 buckets | SSE-S3 (AES256) | Adequate for static assets and uploads |

*Table 16.1. Encryption by resource.*

The audit table gets a customer-managed key because key usage is itself logged
in CloudTrail. Anyone decrypting audit records leaves a trace in a place they do
not control through the application.

The key is explicitly single-region. Multi-region keys are unavailable on this
account, and a design that assumed them could not be deployed.

## 16.2 Secrets Manager

One secret is defined: credentials for external institutional inventory feeds
and any secondary routing provider.

What is deliberately **not** in Secrets Manager:

- Database credentials — DynamoDB uses IAM, so there are none.
- The Cognito client secret — there isn't one; the browser client uses PKCE.
- Map provider keys — the browser gets scoped temporary credentials instead.

That is three categories of secret that do not exist because of earlier design
choices. The cheapest secret to manage is the one you never created.

## 16.3 Local development keys

Local development signs its own JWTs with an RSA keypair in `.local-keys/`.
The directory is gitignored and contains a README stating that the keys are for
local use only. Generating them is a script command, so no key is ever committed
or shared.

## 16.4 Cost

A customer-managed KMS key costs $1 per month plus request charges. Secrets
Manager costs $0.40 per secret per month. In the deployed stack **no
customer-managed KMS key was created** — all three KMS keys are AWS-managed and
therefore free — so the $0.40 secret is the only unavoidable fixed cost in the
entire architecture, and worth naming as such in the cost chapter.

<!-- pagebreak -->

# 17. CloudWatch, CloudTrail and Observability

## 17.1 Structured logs

Every log line is JSON with a fixed envelope, emitted by a logger bound to the
request's correlation id so a caller cannot forget to include it.

```python
class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC)
            .isoformat()
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in ("correlation_id", "actor_id", "organization_id", "event", "duration_ms"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        extra = getattr(record, "context", None)
        if extra:
            payload["context"] = redact(extra)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)
```

*Listing 17.1. The log formatter from `backend/src/appcore/logging.py`.*

## 17.2 Redaction is automatic, not remembered

The specification forbids sensitive information in logs. Relying on every
developer to remember that is a plan that fails once. LifeLink redacts by key
name at any nesting depth:

```python
def redact(value: Any, _depth: int = 0) -> Any:
    """Recursively redact sensitive keys. Depth-limited to avoid pathological input."""
    if _depth > 12:
        return "[TRUNCATED_DEPTH]"
    if isinstance(value, dict):
        return {
            k: (REDACTED if _is_sensitive(str(k)) else redact(v, _depth + 1))
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(v, _depth + 1) for v in value]
    if isinstance(value, str) and len(value) > MAX_STRING_LENGTH:
        return value[:MAX_STRING_LENGTH] + "...[TRUNCATED]"
    return value
```

*Listing 17.2. Recursive redaction. A nested payload cannot smuggle a token
through by burying it.*

The redacted set includes the obvious (passwords, tokens, keys) and the
less obvious: email addresses, phone numbers, precise coordinates, dates of
birth. Those are personal data, and a log is a place personal data accumulates
without anyone deciding that it should.

## 17.3 Alarms that mean something

The template defines 8 alarms. Each one corresponds to a
condition an operator would want to be woken for, which is the test the
specification sets.

| Alarm | Fires when | Why it matters |
|---|---|---|
| Work DLQ not empty | Any message reaches the DLQ | Something failed five times |
| Notification DLQ not empty | Any message reaches the DLQ | Users are not being told things |
| Work queue age | Oldest message over 5 minutes | First sign of a backlog |
| API errors | More than 5 in 5 minutes | Something is broken for users |
| Lambda throttles | Any throttle | The concurrency ceiling has been hit |
| API p95 latency | Over 3 seconds | Degradation before outage |
| DynamoDB throttles | More than 5 in 5 minutes | Capacity or hot-key problem |
| Dispatcher failure | Any error | **Emergency requests stop being matched** |

*Table 17.1. The eight alarms and what each one actually means.*

The last is the most serious condition in the system. If the dispatcher stops,
emergency requests sit uncertified and unmatched while everything else looks
healthy. The handler therefore re-raises on failure specifically so the Lambda
error metric fires:

```python
def dispatcher_handler(event: dict, lambda_context=None) -> dict:
    """Priority dispatcher (ADR-0006), on a one-minute schedule.

    Recomputes effective priority with aging so P3 cannot starve, then processes
    in priority-then-FIFO order. Hospital-certified clinical priority is never
    modified here.
    """
    context = system_context()
    log = get_logger(__name__, context)
    services = get_services()
    now = now_utc()

    try:
        outcome = services.emergency.run_dispatcher(context=context, now=now, batch_size=10)
        expired = services.emergency.expire_overdue(context=context, now=now)
        log.info("dispatcher complete", event="scheduler.dispatch.done",
                 processed=len(outcome.get("processed", [])),
                 aged=len(outcome.get("priorityAged", [])),
                 expired=expired.get("expired", 0))
        return {"statusCode": 200, "dispatch": outcome, "expiry": expired}
    except Exception as exc:
        log.exception("dispatcher failed", event="scheduler.dispatch.failed",
                      error=str(exc)[:300])
        # Re-raised so the Lambda error metric fires its alarm. A silently
        # failing dispatcher means emergency requests stop being matched.
        raise
```

*Listing 17.3. The dispatcher deliberately fails loudly.*

## 17.4 The dashboard

Five widgets: API invocations and errors, latency percentiles, queue depth and
age, DynamoDB capacity and throttles, and background worker errors. Each
corresponds to an alarm, so the dashboard is where an operator looks *after*
being paged, not a decoration.

## 17.5 CloudTrail

Enabled in production for management-event auditing. It answers a different
question from the application audit table: CloudTrail records who changed the
*infrastructure*, the audit table records who changed the *data*.

## 17.6 Correlation across boundaries

A correlation id generated in the browser survives into the API log, the audit
record, the outbox event, the queue message and the worker log. One identifier
retrieves the complete story of a user action including the background work it
caused — which is the difference between debugging a distributed system and
guessing about one.

## 17.7 Cost

Logs are the component most likely to produce a surprising bill. Ingestion is
roughly $0.50 per GB in this region, and storage accrues. The template sets
retention to 30 days by default as a parameter, and access logs exclude request
bodies, which are the bulkiest and most sensitive field.

<!-- pagebreak -->

# 18. Event-Driven Architecture

## 18.1 The problem with write-then-publish

The obvious way to publish an event is to write to the database and then send
a message:

```python
# This is the anti-pattern, shown deliberately.
repository.save(batch)          # committed
queue.send(stock_changed_event) # may never happen
```

*Listing 18.1. What LifeLink does not do.*

If the process dies between those lines — a Lambda timeout, a throttle, an
instance recycle — the data changed and nobody downstream will ever know.
Waiting donors are never matched. The failure is silent: no error, no retry, no
alarm, just an event that does not exist.

## 18.2 The transactional outbox

LifeLink writes the event **in the same DynamoDB transaction** as the domain
change:

```diagram
type: sequence
title: Transactional outbox
actor svc Inventory service
actor ddb DynamoDB
actor stream DynamoDB stream
actor pub Outbox publisher
actor sqs SQS
actor worker Alert worker
msg svc -> ddb transaction batch audit outbox
msg ddb -> svc committed atomically
msg ddb -> stream new outbox row
msg stream -> pub invoke
msg pub -> sqs send message
msg pub -> ddb mark dispatched
msg sqs -> worker deliver
note If the publisher dies the row stays pending, and the reconciliation alarm finds it.
```

*Figure 18.1. The outbox pattern. The event cannot be lost, because it was
committed with the data.*

```python
def apply_change_with_audit(
    self,
    change: StockChange,
    *,
    expected_version: int,
    audit_item: dict,
    outbox_item: dict | None = None,
) -> Batch:
    """Stock change, audit row and (optionally) an outbox event, atomically.

    ADR-0005: writing the event in the same transaction is what stops a crash
    between the update and the publish from losing the event entirely.
    """
    from .dynamo import transact_write

    batch = change.batch
    table = table_name(self.logical_table)

    condition_expression = "#v = :expected"
    values: dict[str, Any] = {":expected": expected_version}
    if change.units_delta < 0:
        condition_expression += " AND availableUnits >= :needed"
        values[":needed"] = abs(change.units_delta)

    operations: list[dict] = [
        {
            "Put": {
                "TableName": table,
                "Item": to_dynamo(clean(batch_to_item(batch))),
                "ConditionExpression": condition_expression,
                "ExpressionAttributeNames": {"#v": "version"},
                "ExpressionAttributeValues": to_expression_values(values),
            }
        },
        {"Put": {"TableName": table, "Item": to_dynamo(clean(audit_item))}},
    ]
    if outbox_item is not None:
        operations.append(
            {
                "Put": {
                    "TableName": table_name(Tables.OUTBOX),
                    "Item": to_dynamo(clean(outbox_item)),
                }
            }
        )

    transact_write(operations)
    return batch
```

*Listing 18.2. The three-item transaction from
`backend/src/repositories/inventory_repo.py`: domain write, audit record and
outbox event, all or nothing.*

## 18.3 What this buys, and what it costs

**Buys:** the event is as durable as the data. A crash at any point either
leaves nothing changed or leaves both the change and its event. There is no
window in which they disagree.

**Costs:** transactions are twice the write cost, and delivery is at-least-once
rather than exactly-once. The second is not really a cost — exactly-once is not
available in a distributed system and designs that assume it are wrong — but it
does mean every consumer must be idempotent.

## 18.4 Event schema and versioning

Every event carries the same envelope:

| Field | Purpose |
|---|---|
| `eventId` | Idempotency key for consumers |
| `eventType` | Routing and handling |
| `eventVersion` | Schema evolution |
| `occurredAt` | When the domain change happened |
| `correlationId` | Links back to the originating request |
| `causationId` | The event that caused this one, where applicable |
| `aggregateId` | The entity the event concerns |
| `payload` | Type-specific data |

*Table 18.1. The event envelope.*

Because the outbox row is written by application code rather than derived from
the storage schema, the event contract is designed deliberately. A DynamoDB
stream straight off a domain table would couple the event shape to the column
names, so renaming an attribute would silently become a breaking change for
every consumer.

## 18.5 Idempotent consumers

```python
def claim(self, key: str, *, now: datetime, operation: str) -> dict | None:
    """Try to claim a key.

    Returns None when the claim succeeded (first execution). Returns the
    stored record when the work was already done, so the caller can replay
    the original result instead of repeating a side effect.
    """
    expires = now + timedelta(hours=IDEMPOTENCY_TTL_HOURS)
    item = {
        "PK": key,
        "SK": "CLAIM",
        "status": "IN_PROGRESS",
        "operation": operation,
        "claimedAt": to_iso(now),
        "expiresAtEpoch": int(expires.timestamp()),
    }
    try:
        self.put(item, condition=Attr("PK").not_exists())
        return None
    except Exception:
        existing = self.get_consistent(key, "CLAIM")
        if existing is None:
            # The row vanished between the failed put and this read (TTL).
            # Treat as a fresh claim rather than failing the request.
            self.put(item)
            return None

        if existing.get("status") == "COMPLETED":
            return existing

        claimed_at = existing.get("claimedAt")
        if claimed_at:
            from domain.clock import parse_iso

            age = (now - parse_iso(claimed_at)).total_seconds() / 60.0
            if age > STALE_CLAIM_MINUTES:
                # The previous attempt almost certainly died. Retake it.
                self.put(item)
                return None

        raise RequestInProgressError(
            "an identical request is currently being processed",
            details={"idempotencyKey": key},
        ) from None
```

*Listing 18.3. The idempotency claim from
`backend/src/repositories/platform_repo.py`.*

Three outcomes, each handled distinctly: a fresh claim proceeds, a completed
claim returns the stored result without re-executing, and an in-progress claim
is rejected — unless it is stale, in which case it is retaken, because a crashed
request must not block its own retry until TTL expiry.

<!-- pagebreak -->

# 19. Priority Scheduling and Fairness

## 19.1 Why three queues do not give priority

The intuitive design for P1/P2/P3 is three SQS queues. The specification warns
against it, and the warning is correct.

Three queues with three event source mappings give three *independent*
consumers. Nothing coordinates them. Lambda will happily run the P3 consumer
while P1 messages wait, because each mapping polls its own queue on its own
schedule. Priority emerges only if consumers are starved of concurrency in
proportion — which is not something SQS or Lambda offers a control for.

At a concurrency ceiling of 10 the problem is sharper
still: three consumers at two concurrent executions each would consume 60% of
the entire account's capacity before the API tier gets any.

## 19.2 An application-level dispatcher

One scheduled function, running every minute, that reads pending work in
priority order from an index and processes a bounded batch.

```diagram
type: flow
title: Dispatcher cycle
node read Read pending requests from the dispatch index style=data
node age Recompute effective priority with aging style=domain
node sort Sort by effective priority then creation time style=domain
node batch Process a bounded batch style=domain
node expire Expire anything past its deadline style=domain
```

*Figure 19.1. One cycle of the priority dispatcher.*

## 19.3 Preventing P3 starvation

Strict priority starves the bottom. A steady arrival of P1 and P2 work means a
P3 request waits forever, which for a scheduled transfusion request is a real
harm even though no individual decision was wrong.

LifeLink ages waiting requests: one priority band per fifteen minutes waited.
A P3 request becomes P2 after fifteen minutes and P1 after thirty.

```python
def compute_effective_priority(
    *,
    clinical_priority: ClinicalPriority,
    created_at: datetime,
    required_by: datetime | None,
    now: datetime,
    aging_interval_minutes: int = AGING_INTERVAL_MINUTES,
) -> ClinicalPriority:
    """Scheduling priority only -- never written back onto ``clinical_priority``.

    Two documented fairness mechanisms:
      * Aging: one band per aging interval spent waiting, so P3 cannot starve.
      * Deadline urgency: a request due within 30 minutes sorts as P1.
    """
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

*Listing 19.1. Priority aging from `backend/src/domain/emergency.py`.*

## 19.4 The separation that makes aging safe

:::key Fairness must never change clinical priority
A scheduler that promotes a Scheduled request to Critical after thirty minutes
has, if those are the same field, just overruled a doctor.
:::

LifeLink stores two fields:

| Field | Written by | Meaning |
|---|---|---|
| `clinicalPriority` | Hospital authorizer, via the certification endpoint only | The clinical judgement |
| `effectivePriority` | The scheduler, freely | Dispatch ordering only |

*Table 19.1. Two priorities, two owners.*

The certification endpoint is the only code path that writes
`clinicalPriority`, and it records the actor, their role, their organization
and the timestamp. The dispatcher writes `effectivePriority` and nothing else.
A test asserts that aging a P3 request leaves its clinical priority unchanged.

The user interface carries the distinction too: when the two differ, the
request tracking page states that the clinical priority is unchanged and only
the scheduling order has moved.

## 19.5 Deadline awareness

A request due within thirty minutes is dispatched as P1 regardless of band.
This is deadline-driven ordering, not a clinical judgement, and it is subject to
the same separation: it changes `effectivePriority` only.

<!-- pagebreak -->

# 20. IAM and Least Privilege

## 20.1 The principle, applied concretely

Every Lambda function receives exactly the permissions its job requires. The
template expresses this per function rather than sharing one role, which makes
each function's data access reviewable in isolation.

| Function | Can write | Can read | Cannot touch |
|---|---|---|---|
| `api` | All domain tables, audit (put only) | All domain tables | Nothing it does not route to |
| `notification-worker` | Notifications, idempotency | Organizations | Inventory, camps, emergency |
| `work-worker` | Alerts, idempotency | Inventory, facilities, organizations | Emergency, donations |
| `outbox-publisher` | Outbox | Outbox | Every domain table |
| `dispatcher` | Emergency, notifications | Inventory, facilities, organizations | Camps, donations, audit |
| `maintenance` | Inventory, camps, alerts, emergency | Organizations | — |

*Table 20.1. What each function can reach. The right-hand column is the one
that makes the boundary real.*

## 20.2 The audit grant

Covered in Chapter 4, and worth restating as the cleanest example of IAM
expressing an invariant: the application is granted `PutItem` and `Query` on the
audit table and nothing else. "Audit records cannot be modified" stops being a
promise in documentation and becomes a property of the deployment.

## 20.3 The browser's credentials

The identity pool role is the tightest policy in the system: four read-only
Amazon Location tile actions, scoped to one map resource. A browser holding
these credentials — and any user can obtain them, since unauthenticated
identities are permitted so that anonymous visitors see a map — cannot read any
data, cannot geocode, and cannot route.

## 20.4 Confused deputy protection

The frontend bucket policy permits the CloudFront service principal, but only
when `AWS:SourceArn` matches this specific distribution. Without that condition
any CloudFront distribution in any AWS account could read the bucket, because
the service principal is shared across all of them.

## 20.5 Human access

Human IAM is managed by the AWS account's own arrangements. LifeLink does not
create IAM users, does not assign roles to individuals, and does not need to:
application users are Cognito identities, which is a separate system entirely.

<!-- pagebreak -->

# 21. Security Boundaries

## 21.1 The authorization decorator

Every protected route is wrapped by one decorator. Nothing else performs
authorization, which means the rules live in one reviewable place and a route
that forgets to declare a permission fails a test rather than silently going
public.

```python
def requires(
    permission: Permission | None = None,
    *,
    resource_owner: ResourceOwnerResolver | None = None,
    allow_anonymous: bool = False,
):
    """Wrap a handler with authentication, permission and organization checks.

    ``resource_owner`` is how IDOR is prevented: the handler declares how to find
    the owning organization of the thing being touched, and the comparison happens
    here rather than inside the handler where it can be forgotten.
    """

    def decorator(handler: Callable[[dict, RequestContext], dict]):
        @functools.wraps(handler)
        def wrapper(event: dict, context: RequestContext) -> dict:
            principal = context.principal

            # A protected route must still refuse a bad token. If
            # build_context captured a failure, surface it here with its
            # original reason -- "token has expired" is far more useful to a
            # client than a generic "authentication required".
            if not allow_anonymous and context.auth_error is not None:
                raise context.auth_error

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
                if owner_org is not None:
                    if principal.organization_id is None:
                        raise CrossOrganizationError(
                            "this action requires organization membership"
                        )
                    if owner_org != principal.organization_id:
                        # Deliberately does not reveal which organization owns it.
                        raise CrossOrganizationError(
                            "this resource belongs to another organization"
                        )

            return handler(event, context)

        wrapper.__lifelink_permission__ = permission  # type: ignore[attr-defined]
        wrapper.__lifelink_protected__ = True  # type: ignore[attr-defined]
        wrapper.__lifelink_allows_anonymous__ = allow_anonymous  # type: ignore[attr-defined]
        return wrapper

    return decorator
```

*Listing 21.1. The authorization decorator from `backend/src/appcore/auth.py`.*

## 21.2 The order of checks, and why it is that order

```diagram
type: flow
title: Authorization pipeline
node tok Verify token signature issuer and expiry style=aws
node load Load the principal from the database style=data
node act Reject if the account is not active style=domain
node perm Check the declared permission style=domain
node org Compare resource owner to caller organization style=domain
node ctx Hand an authorized context to the handler style=domain
```

*Figure 21.1. Five checks, in a deliberate order.*

**Token before anything else**, because an unverified token tells you nothing.

**Database load before permission check**, because roles come from stored state.
A role revoked thirty seconds ago must not still work for the remaining
fifty-nine minutes of a token's life.

**Account status before permission**, so a suspended administrator receives
`ACCOUNT_SUSPENDED` rather than a confusing `FORBIDDEN`. The error a user sees
should describe the actual reason.

**Organization scoping last**, because it needs the resolved resource and is
the most expensive check.

## 21.3 The suspended-account case

This is the test that distinguishes a real authorization system from a
token-checking one:

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
```

*Listing 21.2. From `backend/tests/unit/test_authorization.py`. The role is
correct and the organization matches; only the account status differs.*

A system that trusts token claims cannot pass this test, because the token is
valid, unexpired and correctly signed.

## 21.4 Preventing insecure direct object references

An IDOR is the bug where changing an identifier in a URL returns someone else's
data. It is prevented here by making the ownership comparison part of the
decorator rather than the handler's responsibility. A handler declares how to
find the owning organization of the thing it touches:

```python
@requires(Permission.INVENTORY_WRITE, resource_owner=_facility_owner)
def create_batch(event, context):
    ...
```

*Listing 21.3. A handler declaring its ownership resolver.*

The handler itself never compares organizations. It cannot forget to.

## 21.5 Errors that do not leak

The cross-organization error says "this resource belongs to another
organization" and does not name which one. A test asserts that the other
organization's identifier appears in neither the message nor the details,
because an error message is an information disclosure channel.

Unhandled exceptions return a generic 500 with a correlation id. The detail
goes to the log.

## 21.6 The route audit

```python
def test_decorator_marks_the_handler_as_protected(self):
    """Used by the route audit test to prove no endpoint is left undecorated."""
    assert getattr(_write_inventory, "__lifelink_protected__", False) is True
    assert _write_inventory.__lifelink_permission__ is Permission.INVENTORY_WRITE
```

*Listing 21.4. The decorator records metadata so the route table can be
audited.*

A build-time check walks all 58 routes and asserts each one
either declares a permission or is explicitly marked anonymous. "No endpoint
was left unprotected" is therefore a checked property rather than an assurance.

<!-- pagebreak -->

# 22. Failure Handling

## 22.1 A taxonomy

| Class | Example | Strategy |
|---|---|---|
| Expected and recoverable | Concurrent modification | Re-read, recompute, retry with a bound |
| Expected and terminal | Insufficient stock | Clear 409 with a machine-readable code |
| Transient infrastructure | DynamoDB throttle | Adaptive retry in the SDK |
| Provider failure | Routing unavailable | Degrade and say so |
| Poison input | Malformed queue message | Partial batch failure, then DLQ |
| Programming error | Unhandled exception | Generic 500, full detail logged, alarm |

*Table 22.1. Failure classes and the strategy for each.*

The distinction between the first two rows matters. A concurrent modification
is worth retrying because the next attempt may well succeed. Insufficient stock
is not — retrying will fail identically, so the client is told clearly and
immediately.

## 22.2 Retry with a bound

```python
attempt = 0
while True:
    attempt += 1
    batch = self._inventory.get_batch(facility_id, batch_id)
    if batch is None:
        raise NotFoundError("batch not found", details={"batchId": batch_id})

    expected_version = batch.version
    change = apply_stock_operation(
        batch=batch, operation=op, units=units, now=now, source=source, reason=reason
    )

```

*Listing 22.1. Bounded retry in `backend/src/services/inventory_service.py`.*

Two properties worth noting. The retry **re-reads and recomputes** rather than
resubmitting the stale decision — resubmitting would just fail the same
condition. And it gives up after a bound rather than looping, so the caller is
never told a stale result succeeded.

## 22.3 Degradation rather than failure

Three degradation paths, all exercised routinely rather than kept for
emergencies:

| Component fails | What still works | What the user sees |
|---|---|---|
| Routing provider | Discovery, distances, contact details | "Road directions are unavailable" |
| Geocoding | Coordinate entry, saved locations | "Enter coordinates manually" |
| Map tiles | The entire facility list | A list instead of a map |
| Notifications | Everything else | Delivery status shows the failure |

*Table 22.2. Degradation paths.*

## 22.4 Failing closed

Where ambiguity could mislead, LifeLink refuses rather than guesses:

- A batch with no expiry date is **ineligible**, not assumed fresh.
- A compatibility combination not in the reference table is **UNKNOWN**, which
  matches nothing — the empty tuple, not "all groups."
- An external update with no source timestamp is **rejected** as stale, because
  a system that cannot say when it read something does not get to overwrite a
  known-newer value.
- A facility that has reported nothing is **UNKNOWN**, never zero.

Each of these could have been written the convenient way. Each would have made
the system quietly wrong in a situation where being wrong matters.

<!-- pagebreak -->

# 23. Reliability Engineering

## 23.1 Assume the message arrives twice

Every consumer begins by asking whether it has already handled this event. The
answer is stored durably, keyed on the event id, with a TTL. A duplicate is
logged as a suppressed duplicate at info level, because it is expected traffic
and not an incident.

## 23.2 Assume the function dies at the worst moment

The outbox pattern means there is no moment at which a crash loses an event.
Enumerate the possibilities:

| Crash point | State afterwards | Recovery |
|---|---|---|
| Before the transaction | Nothing changed | Client retries |
| During the transaction | Nothing changed — it is atomic | Client retries |
| After commit, before stream delivery | Data and outbox row both exist | Stream delivers later |
| During publishing | Row still marked pending | Reconciliation finds it |
| After publish, before marking dispatched | Message sent, row pending | Republished; consumer deduplicates |

*Table 23.1. Every crash point, and why none loses an event.*

The last row is the one that justifies idempotent consumers: the only remaining
failure mode is a duplicate, and duplicates are handled.

## 23.3 Assume the datastore pushes back

DynamoDB throttles. At this account's scale it is unlikely, but the client is
configured for it with adaptive retry mode, and a throttle alarm exists so the
condition is visible rather than merely absorbed.

## 23.4 Assume stock disappears between decisions

An emergency provider accepts a request, and by the time they do, the stock has
gone. LifeLink revalidates before recording an acceptance:

```python
def _revalidate_stock(self, *, facility_id: str, blood_group, component,
                      required_units: int, now: datetime) -> dict:
    from domain.inventory import summarise_availability

    batches = self._inventory.list_eligible_batches(
        facility_id, blood_group, component, now=now
    )
    summary = summarise_availability(
        batches=batches,
        blood_group=blood_group,
        component=component,
        requested_units=required_units,
        now=now,
        inventory_known=True,
    )
    # eligible_units is None only when inventory is unreported, which
    # cannot happen here because inventory_known=True is passed above.
    # Guarded anyway, and guarded towards "not sufficient": an unknown
    # quantity must never satisfy a stock requirement.
    units = summary.eligible_units
    return {
        "sufficient": units is not None and units >= required_units,
        "eligibleUnits": units,
        "availability": summary.state.value,
    }
```

*Listing 23.1. Stock revalidation from
`backend/src/services/emergency_service.py`. Called at every subsequent
decision point, not once at matching time.*

## 23.5 What is not reliable, stated plainly

- **No multi-region failover.** A regional outage is an outage.
- **No automated recovery testing in CI.** Restore procedures are documented
  and were exercised manually; they are not continuously verified.
- **No load testing.** With a concurrency ceiling of
  10 a load test would measure the ceiling, not the
  system. The figure is therefore unmeasured, and this book does not estimate
  one.

<!-- pagebreak -->

# 24. Backup, Recovery and Regional Limits

## 24.1 What is protected, and how

| Data | Mechanism | Window |
|---|---|---|
| Domain tables | Point-in-time recovery | 35 days, any second |
| Audit | PITR plus customer-managed key | 35 days |
| S3 frontend | Versioning | 30 days of old versions |
| S3 uploads | Versioning | Indefinite |
| Infrastructure | CloudFormation template in version control | Redeployable |
| Demo data | Deterministic seed script | Regenerable exactly |

*Table 24.1. Protection by data class.*

## 24.2 RPO and RTO, as assumptions

:::warning These are design assumptions, not tested figures
The specification forbids claiming a disaster recovery capability that has not
been tested. The numbers below describe what the configuration should deliver.
LifeLink is deployed and point-in-time recovery is enabled on eight of the
twelve tables, but **a full restore rehearsal has never been performed**.
:::

| Scenario | RPO (design) | RTO (design) | Tested? |
|---|---|---|---|
| Accidental table deletion | Seconds (PITR) | Hours (restore and repoint) | No |
| Corrupt data from a bad deploy | Seconds (PITR) | Hours | No |
| Stack deleted | Zero for retained tables | Under an hour to redeploy | No |
| Regional outage | Not recoverable in-region | Unbounded | N/A |
| Frontend bad release | Zero | Minutes (restore prior version) | No |

*Table 24.2. Recovery assumptions, with their verification status.*

## 24.3 The regional limitation, stated once more

Cross-region replication is unavailable on this account. There is no warm
standby, no global table, no cross-region backup copy. A regional failure means
LifeLink is unavailable until the region recovers.

For a demonstration system that is acceptable. For a system coordinating
emergency blood supply it would not be, and the honest framing is that
production readiness for that use case requires either an account without this
constraint or an explicit, accepted risk decision.

<!-- pagebreak -->

# 25. Cost Engineering

## 25.1 What actually costs money

| Service | Free tier | Beyond it | LifeLink's exposure |
|---|---|---|---|
| Lambda | 1M requests, 400k GB-s monthly | $0.20/M + duration | Negligible |
| DynamoDB on-demand | 25 GB storage | $1.25/M writes, $0.25/M reads | Low; indexed access only |
| API Gateway HTTP | 1M requests (12 months) | ~$1.00/M | Negligible |
| S3 | 5 GB | $0.025/GB/month | Pennies |
| CloudFront | 1 TB transfer monthly | $0.085/GB | Negligible |
| Cognito | 50k monthly active users | $0.0055/MAU | Zero |
| SQS | 1M requests monthly | $0.40/M | Negligible |
| SES | 3k messages (12 months) | $0.10/k | Negligible |
| **Amazon Location** | Limited free tier | **~$0.50/k map tiles** | **The dominant variable cost** |
| **KMS** | — | **$1/month per key** | **Fixed** |
| **Secrets Manager** | — | **$0.40/month per secret** | **Fixed** |
| CloudWatch Logs | 5 GB ingestion | $0.50/GB | Grows silently |

*Table 25.1. Cost structure. The bold rows are the ones worth watching.*

## 25.2 The honest summary

:::warning This application is not free to run, but it is credited
Measured for 1–25 November 2026: **$0.1628 gross usage**, **−$0.1628
credits**, **$0.00 net payable**. A full month projects to roughly
**$0.45–$0.50 gross**, still $0.00 net while FREE-plan credits last.

The only recurring charge is the **Secrets Manager secret at $0.40 per
month** — 70% of gross usage, and **never accessed**. The anticipated $1.00
KMS charge was never incurred: no customer-managed key was created. Everything
else sits inside free tiers. Note that about 11% of gross usage came from
*inspecting* the system — Cost Explorer bills $0.01 per request — and billing
data can lag 24 hours.
:::

The account carries 120 USD of credits expiring 2027-05-15, which comfortably
covers a demonstration deployment. That is a fact about this account, not a
property of the architecture.

## 25.3 Decisions taken for cost

- HTTP API rather than REST API: roughly 70% cheaper per request.
- `arm64` rather than `x86_64`: roughly 20% cheaper per millisecond.
- On-demand DynamoDB: nothing at rest, which suits an idle demo.
- `PriceClass_100` on CloudFront: cheaper edge locations only.
- `INCLUDE` rather than `ALL` index projections: less storage, fewer reads.
- Log retention as a parameter defaulting to 30 days.
- The map list fallback is a genuine feature, not just a failure path — it is
  also the cheapest way to render results.

## 25.4 Controls

The template provisions an SNS alarm topic. AWS Budgets and spend limits are
configured in AWS Settings rather than in this template, because on this
account plan that is where they live.

<!-- pagebreak -->

# 26. Scaling and Performance

## 26.1 What scales naturally

Lambda, DynamoDB on-demand, SQS, S3 and CloudFront all scale horizontally
without intervention. No part of LifeLink holds state in a process, so there is
nothing that needs sticky sessions or coordinated restarts.

## 26.2 What does not

**The concurrency ceiling.** Ten concurrent executions is the binding
constraint, and no amount of architecture improves it. Raising it is a quota
request, not a code change.

**The dispatcher.** One scheduled function processing a bounded batch per minute
has a throughput ceiling. At current batch sizes that is roughly 600 requests
per hour, which is far beyond demonstration needs and far below a national
service.

**Geospatial fan-out.** A radius search issues one query per geohash cell. The
precision tiers bound this, but it is linear in area.

| Radius | Precision | Cell queries |
|---|---|---|
| 0.5 km | 6 | 5 |
| 3 km | 6 | 58 |
| 10 km | 5 | 26 |
| 20 km | 5 | 79 |
| 60 km | 4 | 29 |
| 100 km | 4 | 65 |

*Table 26.1. Measured query fan-out by radius. These are real numbers from the
implementation, not estimates.*

## 26.3 How that table came to exist

The first implementation queried the centre geohash cell and its eight
neighbours. That is correct only while the search radius is smaller than one
cell. Integration testing against seeded data exposed the bug: a 30 km search
from Patiala returned two facilities when Rajpura, 25.6 km away, should have
appeared.

The fix — covering the whole bounding box of the search circle — exposed a
second problem. A 100 km search then needed **2,107 cell queries**, and a 5 km
search needed 195. Both were untenable, and at a concurrency ceiling of ten,
dramatically so.

The resolution was a third precision tier and retuned boundaries, producing
Table 26.1. The test suite now asserts both properties: coverage at ten radii,
and a bounded cell count.

:::key Why this story is in an architecture book
The failure mode was invisible. No error, no exception, no alarm — a usable
blood bank simply never appeared in results. It was found by testing against
real seeded data with known distances, which is the argument for integration
tests that unit tests with fakes cannot make.
:::

## 26.4 What would change at ten times the scale

| Pressure | First symptom | Response |
|---|---|---|
| More concurrent users | Lambda throttles | Request a quota increase |
| More facilities per area | Larger cell result sets | Tighter precision tiers |
| More emergency requests | Dispatch latency rises | Shorter schedule or larger batch |
| More notifications | SES rate limit | Production access, then batching |
| Dashboard aggregates | Slow reads | A materialised read model |

*Table 26.2. Scaling pressures in the order they would appear.*

<!-- pagebreak -->

# 27. Regional Constraints in Practice

## 27.1 The rules this account operates under

| Rule | Consequence for LifeLink |
|---|---|
| One region for all regional resources | Everything in ap-southeast-2 |
| CloudFront permitted via `us-east-1` | Frontend distribution is fine |
| No Lambda@Edge | No edge compute; none needed |
| No CloudFormation StackSets | Single-account, single-region deploys |
| No cross-region replication | Within-region recovery only |
| No multi-region KMS keys | Audit key is single-region |
| No Route 53 geo or latency routing | Simple DNS only, if a domain is added |

*Table 27.1. Account rules and their effect.*

## 27.2 Service availability was verified, not assumed

Phase 0 checked every service in the design two ways: a live read-only API call
in-region, and the published Free Tier supported-services list. All twenty
services the design uses are available on both counts, including Amazon
Location Service, which was the largest single risk to Feature 2.

The one capability that failed this check was SMS, and Chapter 14 covers how
that was handled.

<!-- pagebreak -->

# 28. Architecture Alternatives and Trade-offs

Ten decisions, each with the alternative that was genuinely considered.

## 28.1 Eleven tables rather than one

Covered in Chapter 11. The deciding factor was IAM-enforceable domain
isolation. **Cost:** cross-domain reads need two calls.

## 28.2 Application dispatcher rather than priority queues

Covered in Chapter 19. Three queues do not produce priority ordering.
**Cost:** up to 60 seconds of scheduling latency.

## 28.3 One Lambda rather than fifty

Covered in Chapter 8. Fifty functions at a ceiling of ten would be actively
harmful. **Cost:** coarser IAM at the API tier, mitigated by in-application
authorization and the write-only audit grant.

## 28.4 Optimistic concurrency rather than atomic counters

An `ADD availableUnits :delta` counter is simpler and atomic. It cannot express
"never below zero", and it loses the pre-image the audit trail needs.
**Cost:** callers must handle 409.

## 28.5 Transactional outbox rather than write-then-publish

Covered in Chapter 18. **Cost:** double write cost on event-producing paths,
plus a reconciliation job.

## 28.6 Compatibility as data rather than code

Rules live in a versioned JSON file with a review status, not in `if`
statements. Swapping in a reviewed reference becomes a data change.
**Cost:** a loader and a validation step.

## 28.7 Facility-scoped reservations rather than cross-organization locking

An earlier edition of this chapter was titled "No reservation model", and the
reasoning given was that reservations would require distributed locking across
organizations sharing no transaction boundary. The objection was real; the
conclusion was wrong, and this is the trade-off that replaced it.

A reservation is scoped to **one facility**, which is also the DynamoDB
partition key. The hold and the pool counter that governs it therefore live in
the same partition, so one conditional `TransactWriteItems` writes the hold and
tests the counter together. No cross-organization lock is needed: the guarantee
is not "nobody else can try" but "only one attempt can win".

**Cost:** an ordinary request is always tied to a single facility — there is no
"reserve two units somewhere nearby". A user who does not care which facility
searches first and then reserves, which is the better journey anyway. And
because a hold genuinely removes units from other searches, every hold carries
a capped expiry and is released actively rather than by TTL, so stock held for
someone who never arrives returns to availability on its own.

See ADR-0018. An availability **alert** still holds nothing, and a provider's
response to an **emergency** request is still an offer rather than a claim.

## 28.8 HTTP API rather than REST API

Covered in Chapter 8. **Cost:** no request validators or usage plans, neither
of which is needed.

## 28.9 Server-side authorization rather than a JWT authorizer alone

A gateway authorizer cannot see account status or resource ownership.
**Cost:** one database read per request, mitigated by a short in-process cache.

## 28.10 moto rather than DynamoDB Local for local development

The Java JAR could not be downloaded in the build environment. moto in server
mode speaks the same DynamoDB API over HTTP with no download and no Docker, and
the application code and boto3 client are unchanged. **Cost:** a dependency
that is a test tool being used as a development service, which is documented.

<!-- pagebreak -->

# 29. Full Architecture Walkthrough

## 29.1 Following one emergency request end to end

```diagram
type: sequence
title: An emergency request from creation to provider response
actor staff Hospital staff
actor api API function
actor em Emergency table
actor out Outbox
actor auth Hospital authorizer
actor disp Dispatcher
actor inv Inventory
actor prov Provider
msg staff -> api create request with consent
msg api -> em transaction request and outbox event
msg api -> staff awaiting certification no priority
msg auth -> api certify as urgent
msg api -> em clinical priority with actor and time
msg disp -> em read pending by effective priority
msg disp -> inv find compatible eligible stock
msg disp -> prov notify matched providers
msg prov -> api accept with units offered
msg api -> inv revalidate stock before accepting
msg api -> em record offer not reservation
note Nine steps, five of which can refuse, and none of which moves a unit of blood.
```

*Figure 29.1. The emergency workflow in full.*

## 29.2 What each step guarantees

1. **Creation** requires consent and validates every field. Duplicate
   submissions are caught by a fingerprint of actor, group, component, quantity
   and rounded location.
2. **No priority is assigned.** The request explicitly carries
   `clinicalPriority: null`.
3. **Certification** re-checks that the hospital is currently verified. A
   hospital suspended since the request was raised cannot certify it.
4. **Dispatch** recomputes effective priority with aging, then processes in
   priority-then-FIFO order.
5. **Matching** reads compatible donor groups from the versioned reference. An
   unknown combination yields no candidates rather than a guess.
6. **Provider notification** goes only to organizations that own a matched
   facility.
7. **Response** is refused if the provider was never notified, if they have
   already responded, or if the request is closed.
8. **Acceptance** revalidates stock. If it has gone, the acceptance is refused
   with the current figure.
9. **Recording** stores an offer. No counter is decremented, nothing is held.

## 29.3 Where a reviewer should look first

| Question | File |
|---|---|
| How is eligibility decided? | `backend/src/domain/eligibility.py` |
| How is freshness separated from verification? | `backend/src/domain/freshness.py` |
| How is authorization enforced? | `backend/src/appcore/auth.py` |
| How is the RBAC matrix defined? | `backend/src/appcore/rbac.py` |
| How are lost updates prevented? | `backend/src/repositories/inventory_repo.py` |
| How is capacity enforced? | `backend/src/repositories/camp_repo.py` |
| How is priority fairness implemented? | `backend/src/domain/emergency.py` |
| What does the infrastructure look like? | `infrastructure/template.yaml` |

*Table 29.1. A reading order for the source.*

<!-- pagebreak -->

# 30. Lessons and Future Work

## 30.1 What the constraints taught

The concurrency ceiling of 10 was initially an
irritation. It turned out to improve the design: it ruled out a per-queue
consumer topology that the specification independently warned against, forced
explicit bounds on every fan-out, and made throttling a designed-for condition
rather than an afterthought. A generous quota would have hidden all three.

## 30.2 What testing found that review did not

Four real bugs were found by integration tests running against a genuine
DynamoDB API surface, none of which a fake repository would have caught:

| Bug | Symptom | Why a fake would have missed it |
|---|---|---|
| Unused expression placeholder | `ValidationException` on verification | A fake ignores expression syntax |
| Version conflict reported as duplicate | Retry path never triggered | A fake does not enforce conditions |
| Three more unused placeholders | Camp check-in and provider response failed | Same |
| `None` stripped from expression values | Any update setting an optional field to null failed | A fake serialises differently |

*Table 30.1. Bugs found by integration testing.*

The second is the most interesting. The code "worked" — it raised an error on a
concurrent write. But it raised `DuplicateError` rather than
`ConcurrentModificationError`, so the service's retry logic never engaged and
the user would have been told a record already existed. A unit test with a mock
would have asserted "raises on conflict" and passed.

The geohash coverage bug described in Chapter 26 belongs in the same category.

## 30.3 Known limitations

| Limitation | Status |
|---|---|
| Deployed to AWS, but the repository is ahead of it | Live since 15 November 2026; later work is undeployed |
| Compatibility reference not clinically reviewed | Marked `UNREVIEWED_SYNTHETIC` throughout |
| SMS not implemented | Blocked by SCP and account plan |
| SES sandbox | Verified recipients only |
| No load testing | Meaningless at a ceiling of 10 |
| No restore rehearsal | Never rehearsed, though PITR is enabled |
| Local auth is not Cognito | Documented divergence; verifier path is shared |
| No read model for dashboards | Aggregates computed per request |
| Accessibility partially verified | Structural work done, no audit tool run |

*Table 30.2. Known limitations, each stated rather than omitted.*

## 30.4 What would come next

**In order of value, not of ease:**

1. **A reviewed compatibility reference.** Everything else is engineering; this
   is the one gap that is about clinical safety.
2. **Deploy to the development environment** and exercise the restore
   procedure, converting several "design assumption" rows into measured ones.
3. **Request a concurrency increase** and run a genuine load test.
4. **SES production access**, making notifications real.
5. **A read model** for dashboard aggregates.
6. **An accessibility audit** with assistive technology, not just structure.

## 30.5 A closing note on honesty

This book contains a substantial number of sentences saying that something was
not done, not tested or not available. That is deliberate. The specification
this project was built to asks repeatedly that limitations be disclosed rather
than hidden, and a technical book that reports only successes is not a useful
engineering document — it is marketing with diagrams.

Every measured figure in these pages was produced by running something. Every
code listing was extracted from the repository at build time. Where a number is
absent, it is because it was not measured, and that is said rather than
estimated.