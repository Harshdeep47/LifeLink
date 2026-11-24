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
{{fact:aws_region}}; CloudFront is global and is administered through
`us-east-1`, which the account's rules permit.*

This diagram describes the design expressed in
`infrastructure/template.yaml` — {{fact:cfn_lines}} lines defining
{{fact:cfn_resources}} resources. It has been validated by `cfn-lint` and
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

Eleven tables, one per bounded context, with {{fact:gsi_count}} global secondary
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

{{include:infrastructure/template.yaml:anchor:# Audit is WRITE-ONLY on purpose:10}}

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
| Account | `{{fact:aws_account}}` | `sts:GetCallerIdentity` |
| Region | `{{fact:aws_region}}` | `~/.aws/config` and live AZ query |
| Plan | {{fact:aws_plan}} | `freetier:GetAccountPlanState` |
| Identity | `AccountFullAccessRole` via social sign-in | STS |
| Measured | {{fact:measured_on}} | Phase 0 discovery |

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

{{include:scripts/seed_demo.py:def guard_environment}}

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

{{include:backend/src/appcore/responses.py:def success}}

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
