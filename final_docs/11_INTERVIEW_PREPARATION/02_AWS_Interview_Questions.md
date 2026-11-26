# Level 2 — AWS Service Questions

Service-specific questions, each anchored in LifeLink's real configuration.

---

## S3

### Q1. S3 storage classes — which would you use?

| Class | Use |
|---|---|
| **Standard** | frequent access — **ours** |
| Standard-IA | infrequent, instant retrieval |
| Intelligent-Tiering | unknown access patterns |
| Glacier Instant / Flexible / Deep Archive | archival, increasing retrieval delay |

**LifeLink:** Standard, for a few megabytes of frontend bundle accessed on every
cold cache. Intelligent-Tiering would add a monitoring charge per object for no
benefit at this size.

### Q2. How do you make a bucket private but the website public?

**LifeLink's actual answer:** all four Block Public Access settings on, ACLs
disabled (`BucketOwnerEnforced`), and a bucket policy granting `s3:GetObject`
to the CloudFront service principal **conditioned on our distribution's ARN**.

**The demonstration:** the plain S3 object URL returns **Access Denied**; the
CloudFront URL returns the site. Same file.

### Q3. SSE-S3 versus SSE-KMS, and what are Bucket Keys?

| | SSE-S3 | SSE-KMS |
|---|---|---|
| Key management | S3 | KMS |
| Cost | free | key + per-request |
| Audit trail | no | **CloudTrail per use** |
| Revocable | no | **yes** — disable the key |

**S3 Bucket Keys** reduce SSE-KMS request costs: normally S3 calls KMS once per
object operation; a Bucket Key makes S3 derive per-object keys from a
short-lived bucket-level key, cutting KMS requests by up to 99%. **New objects
only**, and not supported for DSSE-KMS.

**LifeLink — the honest answer:** both buckets use **SSE-S3**, Bucket Keys are
**disabled**, and enabling them would save **nothing** because we make no KMS
requests from S3. Independent proof: `alias/aws/s3` has no key behind it in the
account. Our KMS usage is **DynamoDB**.

### Q4. What's the lifecycle rule nobody thinks of?

**Aborting incomplete multipart uploads.** An abandoned upload leaves parts you
are **billed for but cannot see** in the object listing.

**LifeLink:** the uploads bucket aborts them after 7 days.

---

## CloudFront

### Q5. OAC versus OAI?

**OAI** is legacy; it does not support SSE-KMS or all HTTP methods. **OAC** is
current and signs origin requests with SigV4. **LifeLink uses OAC**
(`E2QR15L70UVPZT`).

### Q6. How do you make a single-page app's deep links work?

**Custom error responses mapping 403 and 404 to `/index.html` with status
200.**

**And the detail that shows understanding:** it must catch **403**, not just
404 — with Block Public Access on and no `s3:ListBucket`, S3 returns 403 for a
missing key rather than admitting it does not exist. Handling only 404 leaves
deep links broken.

### Q7. What is cache invalidation and when do you need it?

Uploading to S3 does **not** change what users see; CloudFront serves its
cached copy until the TTL expires.

**LifeLink:** the deploy script creates an invalidation. But only `index.html`
really needs it — Vite content-hashes asset filenames, so a new build produces
new filenames and stale JavaScript cannot be served.

### Q8. What's missing from your CloudFront setup?

**Volunteer it:** no WAF, access logging disabled, and `MinimumProtocolVersion:
TLSv1` because that is what the default CloudFront certificate allows. A custom
domain with an ACM certificate — **requested in `us-east-1`**, which catches
people out — would let us require TLS 1.2.

---

## Lambda

### Q9. What is a cold start and how do you reduce it?

The first invocation in a new execution environment pays for creating the
micro-VM, loading the runtime and importing modules.

| Mitigation | LifeLink |
|---|---|
| Provisioned concurrency | **not used** — bills continuously, and would consume part of a pool of 10 |
| SnapStart | **not available for Python** |
| Smaller package | 8.6 MB; the heaviest import is `cryptography`, which is not optional |
| **One function for all routes** | **used** — it stays warm across every route |

### Q10. How does Lambda memory affect performance?

**Memory allocates CPU proportionally**, so it is effectively a speed dial. More
memory on a CPU-bound function can make it **cheaper**, because you pay
GB-milliseconds and the milliseconds drop.

**LifeLink:** 512 MB is where this workload stopped getting faster.

### Q11. Why is your timeout 29 seconds?

**Because API Gateway's integration timeout is 30 and it is a hard ceiling on
an HTTP API.** If the function could run to 30, the gateway would give up first
and return a bare 504 with no correlation id. At 29 the function fails first and
the client gets our own error envelope.

### Q12. How do you handle a concurrency limit?

**LifeLink's limit is 10, not 1000, and the whole response is visible:**

| Mechanism | Value |
|---|---|
| API stage throttle | 10 req/s, burst 20 |
| SQS event source `MaximumConcurrency` | **2** each |
| Timeout | 29 s |
| One function, not 58 | — |
| Reserved concurrency | **deliberately not set** |

**On reserved concurrency:** reserving for one function **removes it from the
shared pool** for everyone else. With 10 total, reserving 3 leaves 7 for
everything. We capped at the event sources instead, which is where a backlog
can drive unbounded scaling.

### Q13. Why arm64, and what did it cost you?

Graviton is cheaper for identical work. The cost is a real build constraint: the
package must contain arm64 Linux wheels, so **`sam build` cannot be used on our
Windows host** — it would install a Windows binary of `cryptography`, which
cannot load on the function. `scripts/build_lambda_package.py` fetches
`manylinux2014_aarch64` wheels explicitly.

---

## DynamoDB

### Q14. Partition key, sort key, GSI, LSI?

| | |
|---|---|
| **Partition key** | hashed to choose a partition |
| **Sort key** | orders items within a partition; enables range queries |
| **GSI** | a different partition **and** sort key; can be added later; **always eventually consistent** |
| **LSI** | same partition key, different sort key; **must be created with the table** |

**LifeLink:** 24 GSIs, **zero LSIs** — every access pattern needed a different
partition key.

### Q15. On-demand versus provisioned capacity?

| | On-demand | Provisioned |
|---|---|---|
| Billing | per request | per capacity-hour |
| Idle cost | **$0** | the full bill |
| Spikes | absorbed | throttled if under-provisioned |
| Cost per request | ~6–7x higher | lower |

**LifeLink:** on-demand, because demo traffic is spiky and unpredictable. At
steady high volume, provisioned with auto-scaling would be substantially
cheaper — that is the honest crossover.

### Q16. How do you do a radius search in DynamoDB?

**You cannot, directly — there is no geospatial index.**

**LifeLink:** geohash the coordinates, index the prefix, convert the circle into
covering cells, query each cell, then **filter with haversine** to the true
circle. Three index tiers at precision 4/5/6, chosen by radius.

**The essential detail:** cells are rectangles that **over-cover** the circle.
Without the haversine filter, a 20 km search returns a facility at 28 km in a
corner. **The index narrows the candidates; the formula gives the answer.**

### Q17. Strong versus eventual consistency?

| Read | Consistency |
|---|---|
| `GetItem` default | eventual |
| `GetItem` `ConsistentRead=True` | strong, 2x cost |
| `Query` on a table | can be strong |
| **`Query` on a GSI** | **always eventual — no option** |

**LifeLink's design consequence:** the reservation pool counter is **never read
from an index**. It is read and written by exact key inside a transaction,
because a stale counter at the moment of decision would permit overselling.

**That is the right answer to "what about eventual consistency?"** — not "it's
fine", but "here is where it would have mattered."

### Q18. How do you prevent lost updates?

**Conditional writes.** `LifeLink`: batch rows carry a `version`, and updates
are conditioned on it; the loser gets `409 CONCURRENT_MODIFICATION`, which the
UI offers to retry after re-reading.

For reservations, `TransactWriteItems` so the reservation row and the pool
counter move together, conditioned on available units.

### Q19. What is a DynamoDB Stream and what would you use it for?

A time-ordered change log, consumable by Lambda. View types: `KEYS_ONLY`,
`NEW_IMAGE`, `OLD_IMAGE`, `NEW_AND_OLD_IMAGES`.

**LifeLink uses two, with different view types for a reason:**

| Table | View | Why |
|---|---|---|
| `outbox` | `NEW_IMAGE` | the publisher only needs the new event |
| `inventory` | `NEW_AND_OLD_IMAGES` | "stock changed" is useless; "12 to 2" is actionable |

---

## Cognito

### Q20. User pool versus identity pool?

| | User pool | Identity pool |
|---|---|---|
| Gives you | an identity in **your app** — JWTs | an identity in **AWS IAM** — temporary credentials |
| For | "is this a signed-in donor?" | "may this browser call a geo API directly?" |

**LifeLink:** user pool used; identity pool **deployed and unused** — it was for
browser map tiles (ADR-0012), superseded by ADR-0019.

### Q21. Access token versus ID token?

**The access token authorizes API calls** and carries `client_id` and scopes.
**The ID token describes the user** and carries `aud` and profile claims.

**The LifeLink detail:** the audience lives in **different claims** — an access
token has `client_id` and no `aud`; an ID token has `aud` and no `client_id`.
Code checking only one silently fails to validate the other type. That was a
real bug; reverting the fix fails 3 of 23 tests.

### Q22. Why PKCE?

Because a browser client is **public** — no secret. PKCE binds the code exchange
to the browser that started it: it sends `SHA256(verifier)` up front and the
original verifier at exchange. An intercepted code is useless.

**And why the code is exposed at all:** it arrives as a **query parameter** on
the redirect, so it can land in browser history or a log. PKCE is precisely the
mitigation for that.

### Q23. Why not use Cognito groups for roles?

**Revocation.** A group in a one-hour token stays effective for up to an hour.
**LifeLink** reads the role from DynamoDB on every request, so revocation
applies on the **next** request — verified live with a suspended account holding
a valid token.

Also: a role here is organization-scoped, which a flat group cannot express.

---

## IAM

### Q24. Role versus user?

A **user** is a long-lived identity with credentials; a **role** is assumed
temporarily for short-lived credentials.

**LifeLink: 9 roles, 0 users, 0 access keys.** No long-lived credential exists
to leak — the most common cause of AWS compromise.

### Q25. Trust policy versus permissions policy?

**Two policies answering different questions:** the trust policy says **who may
assume** the role; the permissions policy says **what it may do**.

**People forget the trust policy, and it is the more security-critical half.**
LifeLink's federated `MapReaderRole` has a condition pinning it to our identity
pool's `aud` — without it, **any** Cognito identity pool in **any** AWS account
could assume it. That is the confused-deputy problem.

### Q26. How does policy evaluation work?

1. **Explicit `Deny` anywhere** -> denied. Nothing overrides it.
2. Organizations **SCP** allows it? If not -> denied.
3. An `Allow`? If not -> **denied by default**.

**LifeLink hit step 1 for real:** the account's SCP denies creating an
`AWS::Location::APIKey`, regardless of our IAM permissions. That forced
ADR-0019 and is why the basemap is OpenStreetMap.

### Q27. Is `Resource: "*"` ever acceptable?

**Only when the resource cannot be named, and then it must be constrained by a
condition.**

**LifeLink has exactly one:** `kms:GenerateDataKey` and `kms:Decrypt`, because
DynamoDB's AWS-managed key ARN is not knowable at template time — constrained by
`"kms:ViaService": "dynamodb.ap-southeast-2.amazonaws.com"`, so it can only be
used **through DynamoDB**.

**Never say "it's safe because it's just KMS."**

---

## API Gateway, SQS, EventBridge

### Q28. HTTP API versus REST API?

HTTP API: ~70% cheaper, lower latency, built-in JWT authorizer. REST API adds
request validation, mapping templates, API keys/usage plans, caching, **WAF
integration** and private endpoints.

**LifeLink uses HTTP API** and does not need what REST adds — validation is
business-level in handlers, no transformation (straight proxy), Cognito instead
of API keys. **The one real loss is WAF**, which would attach at CloudFront
instead.

### Q29. SQS versus SNS?

**SQS stores a message until a consumer processes it** (point-to-point,
pull). **SNS fans a message to all subscribers immediately and stores nothing**
(pub/sub, push).

**LifeLink:** SQS for work that must happen; SNS for alarm notifications.

### Q30. Why is your visibility timeout 180 s for a 29 s function?

Because it must comfortably exceed the function's maximum runtime. If it
expired first, the message would become visible again and be processed **twice
concurrently**. 180 s is over six times the timeout — too generous merely
delays a retry; too short causes duplicate concurrent processing.

### Q31. What is a dead-letter queue, and why 14-day retention?

A destination for messages that fail repeatedly — **LifeLink: after 5 receives.**

**14 days rather than the main queues' 4**, because a DLQ exists for a **human**
to investigate, and four days could expire over a long weekend.

### Q32. EventBridge Scheduler versus Rules?

Scheduler is purpose-built: one-time schedules, timezones with daylight-saving
handling, flexible time windows, a built-in retry policy and DLQ target. Rules
do scheduling as a side effect of event matching.

**LifeLink uses Scheduler — two schedules, zero Rules.** Different Console
page, which is worth knowing.

---

## Cross-references

- [../05_DATABASE_AND_DATA/01_DynamoDB_Data_Model.md](../05_DATABASE_AND_DATA/01_DynamoDB_Data_Model.md)
- [../08_SECURITY_AND_RELIABILITY/06_Security_And_Threat_Scenarios.md](../08_SECURITY_AND_RELIABILITY/06_Security_And_Threat_Scenarios.md)
- [../04_AWS_COMPLETE_GUIDE/](../04_AWS_COMPLETE_GUIDE/)
