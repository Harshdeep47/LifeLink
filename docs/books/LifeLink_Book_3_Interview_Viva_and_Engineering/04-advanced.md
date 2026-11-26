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

{{fact:cfn_alarms}} alarms, each corresponding to a condition worth waking
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
