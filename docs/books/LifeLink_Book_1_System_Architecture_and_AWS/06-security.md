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
Manager costs $0.40 per secret per month. Together roughly $1.40 monthly — the
only unavoidable fixed cost in the entire architecture, and worth naming as such
in the cost chapter.

<!-- pagebreak -->

# 17. CloudWatch, CloudTrail and Observability

## 17.1 Structured logs

Every log line is JSON with a fixed envelope, emitted by a logger bound to the
request's correlation id so a caller cannot forget to include it.

{{include:backend/src/appcore/logging.py:class JsonFormatter}}

*Listing 17.1. The log formatter from `backend/src/appcore/logging.py`.*

## 17.2 Redaction is automatic, not remembered

The specification forbids sensitive information in logs. Relying on every
developer to remember that is a plan that fails once. LifeLink redacts by key
name at any nesting depth:

{{include:backend/src/appcore/logging.py:def redact}}

*Listing 17.2. Recursive redaction. A nested payload cannot smuggle a token
through by burying it.*

The redacted set includes the obvious (passwords, tokens, keys) and the
less obvious: email addresses, phone numbers, precise coordinates, dates of
birth. Those are personal data, and a log is a place personal data accumulates
without anyone deciding that it should.

## 17.3 Alarms that mean something

The template defines {{fact:cfn_alarms}} alarms. Each one corresponds to a
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

{{include:backend/src/handlers/workers.py:def dispatcher_handler}}

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

{{include:backend/src/repositories/inventory_repo.py:def apply_change_with_audit}}

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

{{include:backend/src/repositories/platform_repo.py:def claim}}

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

At a concurrency ceiling of {{fact:lambda_concurrency}} the problem is sharper
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

{{include:backend/src/domain/emergency.py:def compute_effective_priority}}

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
