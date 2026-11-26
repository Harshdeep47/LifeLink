<!-- pagebreak -->

# 21. Security Boundaries

## 21.1 The authorization decorator

Every protected route is wrapped by one decorator. Nothing else performs
authorization, which means the rules live in one reviewable place and a route
that forgets to declare a permission fails a test rather than silently going
public.

{{include:backend/src/appcore/auth.py:def requires}}

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

{{include:backend/tests/unit/test_authorization.py:def test_suspended_account_is_blocked_despite_valid_token_and_role}}

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

{{include:backend/tests/unit/test_authorization.py:def test_decorator_marks_the_handler_as_protected}}

*Listing 21.4. The decorator records metadata so the route table can be
audited.*

A build-time check walks all {{fact:route_count}} routes and asserts each one
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

{{include:backend/src/services/inventory_service.py:anchor:attempt = 0:12}}

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

{{include:backend/src/services/emergency_service.py:def _revalidate_stock}}

*Listing 23.1. Stock revalidation from
`backend/src/services/emergency_service.py`. Called at every subsequent
decision point, not once at matching time.*

## 23.5 What is not reliable, stated plainly

- **No multi-region failover.** A regional outage is an outage.
- **No automated recovery testing in CI.** Restore procedures are documented
  and were exercised manually; they are not continuously verified.
- **No load testing.** With a concurrency ceiling of
  {{fact:lambda_concurrency}} a load test would measure the ceiling, not the
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
| One region for all regional resources | Everything in {{fact:aws_region}} |
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

The concurrency ceiling of {{fact:lambda_concurrency}} was initially an
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
