# Configuration Walkthroughs

**This is the document for "show me where you configured it."**

Every significant LifeLink configuration, with its real deployed value, the
exact Console path to inspect it, why it is set that way, what happens if you
change it, and a spoken answer.

All values were read from the live environment on **24 November 2026**.

---

## How to use this document

Each configuration follows the same structure:

- **What it does** — plain language
- **Mechanism** — how it works technically
- **Deployed value** — the real current setting
- **Where in code** — the template resource and property
- **INSPECT** — read-only Console path, safe during an evaluation
- **MODIFY** — how it *would* be changed, and the risks
- **Say this** — a spoken answer

### The golden rule for an evaluation

> **Inspect, do not modify.** Every setting below is controlled by
> `infrastructure/template.yaml`. Changing it in the Console creates **drift**:
> the live resource no longer matches the code that defines it, and the next
> deployment will either overwrite your change or fail confusingly. If a
> teacher asks you to change something, the correct answer is "I'd change it in
> the template and redeploy — let me show you the line."

### Four terms a teacher may test

| Term | Meaning |
|---|---|
| **Current deployed configuration** | What AWS actually has right now |
| **Infrastructure-as-code configuration** | What `template.yaml` says it should be |
| **Manually modified configuration** | Someone clicked it in the Console |
| **Configuration drift** | The first two no longer agree |

LifeLink has **one known divergence**, documented in §C4: four Lambda log
groups were auto-created by AWS and were never in the template at all, so they
do not have the 30-day retention the template sets. That is not drift in
CloudFormation's strict sense — it is an **IaC coverage gap**, which is a
sharper and more interesting answer.

---

# SECTION A — S3

## A1. Default encryption (and the S3 Bucket Keys question)

**This is the configuration most likely to be asked about in detail. Read it
carefully, because the honest answer is not the flattering one.**

| | |
|---|---|
| **What it does** | Encrypts every object at rest automatically |
| **Mechanism** | S3 encrypts each object with a data key before writing to disk, and decrypts on read. With **SSE-S3**, S3 manages the keys entirely. With **SSE-KMS**, each operation calls AWS KMS |
| **Deployed value** | **`SSEAlgorithm: AES256` (SSE-S3)** on **both** buckets |
| **S3 Bucket Keys** | **`BucketKeyEnabled: false`** on both buckets |
| **Customer-managed KMS key** | **None.** No KMS key is involved in S3 at all |
| **Also reported** | `BlockedEncryptionTypes: [SSE-C]` |

### INSPECT (read-only)

```
AWS Console -> S3 -> Buckets -> lifelink-dev-frontend-426150327442
  -> Properties tab
  -> "Default encryption" section
```

You will see **Server-side encryption with Amazon S3 managed keys (SSE-S3)**
and **Bucket Key: Disabled**.

CLI equivalent:
```bash
aws s3api get-bucket-encryption \
  --bucket lifelink-dev-frontend-426150327442 --profile lifelink
```

### The Bucket Keys answer

**Do not claim Bucket Keys were enabled. They are disabled — and on this
project, enabling them would save nothing.**

| Question | Verified answer |
|---|---|
| Are Bucket Keys enabled? | **No**, `BucketKeyEnabled: false` |
| Is SSE-KMS in use on S3? | **No**, SSE-S3 (AES256) |
| Would enabling them reduce cost? | **No.** Bucket Keys reduce **KMS request** costs. With SSE-S3 there are no KMS requests to reduce |
| Independent proof | **`alias/aws/s3` has no target key in this account** — S3 has never used SSE-KMS here |
| Do they apply to existing objects? | **No.** Only to objects written *after* the change |
| Is it in CloudFormation? | The SSE-S3 setting is. Bucket Keys are not configured either way |

**What S3 Bucket Keys actually are, for the explanation:** when a bucket uses
SSE-KMS, S3 normally calls KMS **once per object operation** — every upload and
every download. At scale that is both slow and expensive, because KMS charges
per request. A Bucket Key makes S3 ask KMS for a short-lived **bucket-level
key** and then derive per-object keys from it locally, cutting KMS requests by
up to **99%**.

**Its limitations:** it only helps with SSE-KMS, it is not supported for
DSSE-KMS, the KMS key must be symmetric and in the same Region as the bucket,
and it applies only to new objects — existing objects keep their original
encryption until rewritten (S3 Batch Operations can rewrite them).

### Where KMS *is* used in LifeLink

| Service | Key | Type |
|---|---|---|
| **DynamoDB** (all 12 tables) | `alias/aws/dynamodb` = `95806067-…` | **AWS-managed** (`KeyManager: AWS`) |
| Secrets Manager | `alias/aws/secretsmanager` | AWS-managed |
| Lambda | `alias/aws/lambda` | AWS-managed |
| S3 | **none** | — |

So the KMS story is a **DynamoDB** story, not an S3 story. Redirect the
question there and you will be both accurate and well-informed.

### MODIFY (do not do this during an evaluation)

To switch the uploads bucket to SSE-KMS with Bucket Keys:

```
S3 -> bucket -> Properties -> Default encryption -> Edit
  -> Encryption type: "AWS Key Management Service key (SSE-KMS)"
  -> choose a symmetric KMS key in ap-southeast-2
  -> Bucket Key: Enable
  -> Save changes
```

| Risk | Assessment |
|---|---|
| Downtime | **No** |
| Data loss | **No** — existing objects are untouched and still readable |
| Security change | **Yes** — every reader now needs `kms:Decrypt` on that key |
| Added cost | **Yes** — KMS key storage plus request charges. Bucket Keys reduce the request part, they do not remove it |
| Correct method | Change `BucketEncryption` in `infrastructure/template.yaml` and redeploy, **not** the Console |

### Say this

**30 seconds:**
> "Both buckets use SSE-S3 — AWS manages the keys and encrypts every object
> automatically, with no KMS involved. S3 Bucket Keys are disabled, and on this
> project they'd make no difference, because they only reduce KMS request costs
> and we don't use SSE-KMS on S3. Our KMS usage is in DynamoDB, where all twelve
> tables are encrypted with the AWS-managed `aws/dynamodb` key."

**1–2 minutes:** add the mechanism —
> "The reason Bucket Keys exist is that with SSE-KMS, S3 calls KMS once per
> object operation — every upload and every download. That's a per-request
> charge and extra latency. A Bucket Key makes S3 fetch a short-lived
> bucket-level key and derive per-object keys locally, which cuts KMS requests
> by up to about 99 percent. It only applies to new objects, though, so existing
> objects keep their original encryption until they're rewritten.
>
> I can show you independently that we never used SSE-KMS on S3: the
> `alias/aws/s3` KMS alias in our account has no key behind it at all. If it had
> ever been used, AWS would have created that key automatically."

---

## A2. S3 Block Public Access

| | |
|---|---|
| **What it does** | Prevents the bucket from ever becoming publicly readable |
| **Mechanism** | Four independent switches that override any ACL or bucket policy that would grant public access |
| **Deployed value** | **All four `true`** on both buckets |
| **Template** | `AWS::S3::Bucket` -> `PublicAccessBlockConfiguration` |

The four settings: `BlockPublicAcls`, `IgnorePublicAcls`, `BlockPublicPolicy`,
`RestrictPublicBuckets`.

### INSPECT
```
S3 -> lifelink-dev-frontend-426150327442 -> Permissions tab
  -> "Block public access (bucket settings)"
```
All four read **On**.

### Why, when it is a public website?

**This is the best question in this section.** The website is public, but the
**bucket** is not. CloudFront reaches S3 using an **Origin Access Control**,
which signs its requests with SigV4, and the bucket policy accepts only
requests from that distribution.

So there are two layers: nothing can make the bucket public, and the only
identity allowed to read it is our CloudFront distribution.

### Say this
> "The site is public but the bucket isn't. All four Block Public Access
> settings are on, so even a misconfigured policy couldn't expose it.
> CloudFront reads the bucket through an Origin Access Control — it signs its
> requests, and the bucket policy only accepts requests from our specific
> distribution. If you fetched the S3 URL directly you'd get Access Denied; only
> the CloudFront URL works."

| Risk of disabling | |
|---|---|
| Downtime | No |
| Data loss | No |
| **Security** | **Severe** — the bucket could be made world-readable, and S3 bills for public downloads |

---

## A3. Object Ownership — ACLs disabled

| | |
|---|---|
| **Deployed value** | **`BucketOwnerEnforced`** |
| **What it means** | ACLs are **disabled entirely**; access is controlled only by policies |
| **Why** | ACLs are a legacy mechanism that predates IAM. Disabling them removes an entire category of accidental exposure, and AWS has made it the default for new buckets |

**INSPECT:** `S3 -> bucket -> Permissions -> "Object Ownership"` reads
**Bucket owner enforced**.

---

## A4. Versioning (frontend bucket)

| | |
|---|---|
| **Deployed value** | **`Enabled`** |
| **What it does** | Keeps every version of an object; overwrites and deletes become new versions |
| **Why here** | A bad frontend deployment can be rolled back to the previous bundle, and an accidental `aws s3 rm` is recoverable |
| **Cost** | You pay for every version. With a few megabytes of static files this is negligible — on a large data bucket it would not be |

**INSPECT:** `S3 -> bucket -> Properties -> "Bucket Versioning"`.

### Say this
> "Versioning is on for the frontend bucket, so every deployment keeps the
> previous bundle and a bad deploy or an accidental delete is recoverable. It's
> cheap here because the bundle is a few megabytes. There's no lifecycle rule
> expiring old versions, which would matter if this were a large or
> frequently-written bucket — that's a fair criticism of the setup."

---

## A5. No static website hosting

| | |
|---|---|
| **Deployed value** | **Not configured** — `GetBucketWebsite` returns `NoSuchWebsiteConfiguration` |
| **Why not** | S3 static website hosting requires a **public** bucket and serves over **HTTP only**. CloudFront + OAC gives HTTPS, caching, and a private bucket |

**This is a deliberate choice worth stating**, because a teacher may expect to
see website hosting enabled and ask why it is not.

### Say this
> "We deliberately didn't use S3 static website hosting. That feature needs the
> bucket to be public and only serves plain HTTP. Using CloudFront with an
> Origin Access Control instead gives us HTTPS with an AWS certificate, global
> caching, and a bucket that stays completely private."

---

## A6. Lifecycle rule (uploads bucket)

| | |
|---|---|
| **Deployed value** | Rule `AbortIncompleteUploads` — aborts incomplete multipart uploads after **7 days** |
| **Why** | An abandoned multipart upload leaves parts in the bucket that **you are billed for but cannot see** in the object listing. This is a classic hidden AWS cost |

**INSPECT:** `S3 -> lifelink-dev-uploads-426150327442 -> Management tab
-> "Lifecycle rules"`.

### Say this
> "The uploads bucket has one lifecycle rule that aborts incomplete multipart
> uploads after seven days. If a large upload fails halfway, the uploaded parts
> stay in the bucket and you're charged for them, but they don't appear in the
> object list — so it's storage you pay for and can't see. The rule cleans them
> up automatically."

---

# SECTION B — CloudFront

## B1. Origin and Origin Access Control

| | |
|---|---|
| **Distribution** | `E236QHMFXHDEDL` -> `https://d324z37do52g8f.cloudfront.net` |
| **Origin** | `lifelink-dev-frontend-426150327442.s3.ap-southeast-2.amazonaws.com` |
| **OAC** | `E2QR15L70UVPZT` |
| **Origin path** | empty |
| **Legacy OAI** | **not used** |

**Mechanism:** the OAC makes CloudFront sign its origin requests with SigV4.
The bucket policy grants `s3:GetObject` to the CloudFront service principal
with a condition restricting it to this distribution's ARN.

**OAC versus the older OAI:** OAI is the legacy mechanism and does not support
SSE-KMS or all HTTP methods. OAC is the current recommendation. Using OAC is a
small but real "we read the current documentation" signal.

**INSPECT:**
```
CloudFront -> Distributions -> E236QHMFXHDEDL -> Origins tab -> the S3 origin
  -> "Origin access" shows "Origin access control settings"
```

---

## B2. Viewer protocol policy — redirect-to-https

| | |
|---|---|
| **Deployed value** | **`redirect-to-https`** |
| **Mechanism** | A plain HTTP request gets a `301` to the `https://` URL |
| **Alternatives** | `allow-all` (insecure), `https-only` (rejects HTTP outright rather than redirecting) |

**INSPECT:** `CloudFront -> distribution -> Behaviors -> Default (*) -> Edit`
(view only) -> **Viewer protocol policy**.

### Say this
> "Any plain HTTP request is redirected to HTTPS with a 301, so credentials and
> tokens never travel unencrypted. We chose redirect over https-only because a
> redirect still works for someone who types the bare domain, whereas
> https-only would just fail."

---

## B3. Custom error responses — the SPA routing fix

| | |
|---|---|
| **Deployed value** | **403 -> `/index.html` with status 200**, TTL 10 s. **404 -> `/index.html` with status 200**, TTL 10 s |

**This is the most interesting CloudFront setting in the project**, because its
effect is visible and its absence would be a bug a teacher could find.

**The problem it solves.** React Router resolves `/facilities/fac-123` in the
browser. But if a user pastes that URL directly, CloudFront asks S3 for an
object literally named `facilities/fac-123` — which does not exist. S3 returns
403 (because listing is denied, so S3 cannot even say "404"), and the user
would see an error page instead of the app.

Mapping both 403 and 404 to `/index.html` with **status 200** means the React
app loads and then routes the path itself.

**Why 403 and not just 404?** Because with Block Public Access and no
`s3:ListBucket` permission, S3 answers **403** for a missing key — it will not
confirm whether the object exists. Handling only 404 would leave deep links
broken.

**Why TTL 10 seconds?** So a genuinely new file appears quickly rather than
being masked by a cached error.

**INSPECT:** `CloudFront -> distribution -> "Error pages" tab`.

### Say this
> "Both 403 and 404 are mapped to index.html with a 200 status. That's what
> makes deep links work in a single-page app: if you paste a facility URL,
> CloudFront looks for a file with that name in S3, doesn't find one, and
> without this setting you'd get an error page. Instead it serves index.html and
> React Router resolves the path in the browser. It has to catch 403 as well as
> 404, because with public access blocked S3 returns 403 for a missing object
> rather than admitting it doesn't exist."

---

## B4. Cache policy, compression and allowed methods

| Setting | Deployed value |
|---|---|
| Cache policy | `658327ea-f89d-4fab-a63d-7e88639e58f6` — AWS managed **CachingOptimized** |
| Compress objects automatically | **true** |
| Allowed methods | **`GET, HEAD, OPTIONS` only** |
| HTTP version | `http2and3` |
| IPv6 | enabled |
| Default root object | `index.html` |

**Why `CachingOptimized`?** It caches based on the URL path only, ignoring
cookies, query strings and most headers — correct for immutable static assets.
Vite emits content-hashed filenames (`index-AW8_zfLM.js`), so a new build
produces a new filename and the cache never serves stale code.

**Why only three methods?** The distribution serves static files. There is
nothing to POST to. Allowing write methods would be surface area for no
benefit — API calls go directly to API Gateway, not through CloudFront.

### Say this
> "We use the AWS managed CachingOptimized policy, which keys the cache on the
> path alone. That works because Vite puts a content hash in every filename, so
> a new build produces new filenames and stale code can't be served. Only GET,
> HEAD and OPTIONS are allowed, because this distribution only serves static
> files — the API is a separate endpoint."

---

## B5. Price class, certificate, and the two gaps

| Setting | Deployed value | Comment |
|---|---|---|
| Price class | **`PriceClass_100`** | Cheapest set of edge locations: North America, Europe, and some Asian locations |
| Alternate domain names | **none** | Using the `*.cloudfront.net` domain |
| Certificate | **CloudFront default** | `MinimumProtocolVersion: TLSv1` |
| **WAF** | **none** (`WebACLId: ""`) | `NOT-IMPLEMENTED` |
| **Standard logging** | **disabled** | real gap |

**Be honest about the last three:**

- **`MinimumProtocolVersion: TLSv1`** comes with the default CloudFront
  certificate. Using a custom domain with ACM would allow
  `TLSv1.2_2021`, which is better practice. We do not have a custom domain.
- **No WAF.** For a public demonstration site with synthetic data this is
  defensible, but a production system handling health-adjacent data should
  have rate-based rules and AWS Managed Rules at minimum.
- **No access logging.** CloudFront can log every request to S3 or
  CloudWatch; we do not. API Gateway access logging *is* enabled, so API
  traffic is logged — only static-file requests are not.

### Say this
> "Price class 100 keeps cost down by using only the cheaper edge locations.
> Two honest gaps: there's no WAF attached, and CloudFront access logging is
> off. For a demo site with synthetic data that's a reasonable trade, but for
> production I'd add rate-based WAF rules and turn logging on. Also, our minimum
> TLS version is 1.0 because that's what the default CloudFront certificate
> allows — with a custom domain and an ACM certificate we could require TLS 1.2."

---

## B6. Invalidation — the deployment step people forget

**Not a stored setting, but the operation a teacher may ask about.**

Uploading a new file to S3 does **not** update what users see. CloudFront keeps
serving its cached copy until the TTL expires or the path is invalidated.

```bash
aws cloudfront create-invalidation \
  --distribution-id E236QHMFXHDEDL --paths "/*" --profile lifelink
```

`scripts/deploy_frontend.py` does this automatically. The most recent
deployment's invalidation was `I76XJI99TM91I1THIOYYR9BXFN`, status
**Completed**.

**INSPECT:** `CloudFront -> distribution -> "Invalidations" tab` — the history
is visible, which is a nice way to prove a deployment happened.

**Why `index.html` still updates promptly:** content-hashed asset filenames
change every build, so only `index.html` itself needs invalidating. Using
`/*` is simply the safe default, and the first 1,000 invalidation paths per
month are free.

---

# SECTION C — DynamoDB

## C1. Encryption at rest

| | |
|---|---|
| **Deployed value** | **SSE-KMS** on all 12 tables, using `alias/aws/dynamodb` |
| **Key** | `95806067-…`, `KeyManager: AWS`, `SYMMETRIC_DEFAULT` |
| **Key type** | **AWS-managed**, not customer-managed |

**The three DynamoDB encryption options:**

| Option | Key | Cost | Control |
|---|---|---|---|
| AWS owned | AWS's own key, not in your account | free | none |
| **AWS managed** (ours) | `aws/dynamodb` in your account | free | visible in KMS, auditable in CloudTrail |
| Customer managed | your own CMK | ~$1/month + requests | full — you can revoke it |

**Why AWS-managed?** It is free, it appears in your KMS console so it is
auditable, and you do not have to manage a key policy. A customer-managed key
would let you revoke access and set your own rotation, at about a dollar a
month plus request charges — worth it for regulated data, not for synthetic
demonstration data.

**INSPECT:**
```
DynamoDB -> Tables -> lifelink-dev-facilities
  -> "Additional settings" tab -> "Encryption" section
```
Or in KMS: `KMS -> AWS managed keys -> aws/dynamodb`.

### Say this
> "All twelve tables are encrypted at rest with KMS, using the AWS-managed
> `aws/dynamodb` key. We chose AWS-managed over customer-managed because it's
> free and still auditable — it appears in our KMS console and every use is
> logged in CloudTrail. A customer-managed key would let us revoke access and
> control rotation ourselves, which matters for regulated data, but it costs
> about a dollar a month per key plus request charges and our data is synthetic."

**This is also where the `Resource: "*"` in our IAM policies comes from** — see
[../04_AWS_COMPLETE_GUIDE/08_IAM_Complete_Guide.md](../04_AWS_COMPLETE_GUIDE/08_IAM_Complete_Guide.md).

---

## C2. Point-in-time recovery — enabled on 8 of 12

| PITR enabled (8) | PITR disabled (4) |
|---|---|
| `organizations`, `facilities`, `inventory`, `reservations`, `camps`, `donations`, `emergency`, `audit` | `alerts`, `notifications`, `outbox`, `idempotency` |

**What PITR does:** continuous backups allowing restore to any second in the
retention window (1–35 days). A restore always creates a **new table** — it
never overwrites the original.

**Why the split?** The four disabled tables hold **ephemeral** data that all
have TTL set. Paying for continuous backups of records that delete themselves
within hours would be waste. The eight enabled tables hold records whose loss
would be unrecoverable.

**That is a deliberate cost/value trade-off, and saying so out loud is much
better than letting a teacher assume you forgot four tables.**

**INSPECT:**
```
DynamoDB -> Tables -> lifelink-dev-inventory -> "Backups" tab
  -> "Point-in-time recovery (PITR)" section
```

| Risk of enabling on the other four | |
|---|---|
| Downtime | No |
| Data loss | No |
| Cost | Yes — charged per GB of backup storage |

### Say this
> "Point-in-time recovery is on for the eight tables holding durable records —
> facilities, inventory, reservations, emergency requests, and so on — and off
> for the four ephemeral ones: alerts, notifications, the outbox and the
> idempotency table. Those four all have TTL set, so their rows delete
> themselves within hours. Paying for continuous backups of self-deleting data
> would be waste. And a PITR restore always creates a new table, so it's a
> recovery tool, not an undo button."

---

## C3. Billing mode, TTL, streams, deletion protection

### Billing mode: PAY_PER_REQUEST on all 12

**Why on-demand rather than provisioned?** Demonstration traffic is spiky and
unpredictable. Provisioned capacity means guessing a number, paying for it
whether used or not, and being throttled when you guess low. On-demand costs
nothing when idle and absorbs a spike automatically. The trade-off is that
on-demand costs roughly 6–7x more **per request** — so a steady, predictable,
high-volume workload should be provisioned.

**INSPECT:** `DynamoDB -> table -> Overview tab -> "Capacity mode"`.

### TTL: enabled on 4 tables

| Table | Attribute |
|---|---|
| `reservations` | **`purgeAtEpoch`** |
| `alerts`, `notifications`, `outbox`, `idempotency` | `expiresAtEpoch` |

**Mechanism:** a numeric attribute holding a Unix epoch timestamp. DynamoDB
deletes the item **within about 48 hours** of that time, at no cost in write
capacity.

**Two things to know:** TTL is **not instant**, so application code must still
filter on business expiry rather than trusting the item to be gone. And
`reservations` deliberately uses a *different* attribute name, because a
reservation's business expiry (the hold runs out) is much earlier than its
storage purge — a user must still be able to see that their hold expired.

**INSPECT:** `DynamoDB -> table -> "Additional settings" tab
-> "Time to Live (TTL)"`.

### Streams: enabled on 2 tables

| Table | View type | Consumer |
|---|---|---|
| `inventory` | `NEW_AND_OLD_IMAGES` | — |
| `outbox` | `NEW_IMAGE` | `lifelink-dev-outbox-publisher` |

**Why different view types?** The outbox publisher only needs the new event, so
`NEW_IMAGE` is enough. Inventory uses `NEW_AND_OLD_IMAGES` because a change
event is only meaningful with the before and after values — "stock changed" is
useless; "stock went from 12 to 2" is actionable.

**INSPECT:** `DynamoDB -> table -> "Exports and streams" tab`.

### Deletion protection: DISABLED on all 12 — a known gap

| | |
|---|---|
| **Deployed value** | `DeletionProtectionEnabled: false` on all 12 |
| **What it does** | Blocks `DeleteTable` until explicitly turned off |
| **Why off here** | This is a demonstration environment that gets re-seeded and torn down; deletion protection blocks a stack delete |
| **Honest position** | In production it should be **on** for every table holding real records |

**Do not defend this as a good choice. Call it a demo trade-off.**

### Say this
> "Deletion protection is off on all twelve tables. That's a deliberate demo
> trade-off — it blocks a CloudFormation stack delete, and this environment gets
> rebuilt. For production I'd turn it on for every table holding real records,
> because it's free and the failure it prevents is unrecoverable."

---

## C4. CloudWatch log retention — the real IaC coverage gap

**Found while writing this documentation. Report it; do not hide it.**

| Log group | Retention |
|---|---|
| `/aws/apigateway/lifelink-dev` | **30 days** |
| `/aws/lambda/lifelink-dev-api` | **30 days** |
| `/aws/lambda/lifelink-dev-dispatcher` | **Never expire** |
| `/aws/lambda/lifelink-dev-maintenance` | **Never expire** |
| `/aws/lambda/lifelink-dev-outbox-publisher` | **Never expire** |
| `/aws/lambda/lifelink-dev-work-worker` | **Never expire** |
| `/aws/lambda/lifelink-dev-notification-worker` | **does not exist** — never invoked |

**Why:** the template declares `LogRetentionDays: 30` and creates **two** log
groups explicitly. The other four were **auto-created by Lambda** on first
invocation, and a log group AWS creates implicitly defaults to never
expiring. The template's retention setting cannot apply to a resource the
template does not declare.

**Consequence:** the dispatcher runs every minute and has accumulated about
8 MB of logs that will never be deleted. Small now, unbounded later.

**The fix (not applied — engineering freeze):** declare an
`AWS::Logs::LogGroup` for each function in the template with
`RetentionInDays: !Ref LogRetentionDays`, or use SAM's logging configuration.

**INSPECT:**
```
CloudWatch -> Log groups -> filter "lifelink"
  -> the "Retention" column
```

### Say this — this is a strong answer, not a weak one
> "Here's a gap I found while documenting rather than while building. Our
> template sets thirty-day log retention, and it works — but only for the two
> log groups the template actually declares. The other four Lambda log groups
> were created automatically by AWS on first invocation, so the template never
> touched them, and an implicitly created log group defaults to never expiring.
> The dispatcher runs every minute and has about eight megabytes that will never
> be deleted.
>
> It's not drift in CloudFormation's sense, because those resources were never
> in the stack at all — it's an infrastructure-as-code coverage gap, which is a
> different and more common problem. The fix is to declare a log group per
> function in the template."

---

# SECTION D — Cognito

## D1. Password policy

| Setting | Deployed value |
|---|---|
| Minimum length | **12** |
| Require uppercase | yes |
| Require lowercase | yes |
| Require numbers | yes |
| **Require symbols** | **yes** |
| Temporary password validity | 3 days |

**INSPECT:**
```
Cognito -> User pools -> lifelink-dev (ap-southeast-2_Z91jyFm1d)
  -> "Sign-in" / "Authentication" -> Password policy
```

### The story to tell

The deployed pool required 12 characters with a symbol, while **three places
in the frontend told users "at least 8 characters"** and none mentioned a
symbol. Users following the on-screen rules were rejected by Cognito with an
unhelpful error.

The fix: one shared module, `frontend/src/auth/passwordPolicy.js`, **plus a
test that reads `infrastructure/template.yaml`** and asserts the UI matches the
deployed policy. 49 tests cover it.

**Live proof:** Cognito refuses `Password1` with `InvalidPasswordException` —
the exact password the old frontend would have accepted.

### Say this
> "Twelve characters with upper, lower, a number and a symbol. We found a real
> bug here: three screens said eight characters and didn't mention symbols, so
> users were being rejected after following our own instructions. We fixed it
> with one shared module — and then wrote a test that reads the CloudFormation
> template and asserts the UI matches the deployed policy, so they can't drift
> apart again. That's the fix I'm happiest with, because it fixes the class of
> bug rather than the instance."

---

## D2. App client — public, no secret, PKCE

| Setting | Deployed value |
|---|---|
| Client id | `5hp4pm3ictvetfupddvl41pnf` |
| Client secret | **none** |
| OAuth flows | **`code`** (Authorization Code) |
| Scopes | `email`, `openid`, `profile` |
| Identity providers | `COGNITO` only |
| Explicit auth flows | `ALLOW_USER_SRP_AUTH`, `ALLOW_REFRESH_TOKEN_AUTH`, `ALLOW_ADMIN_USER_PASSWORD_AUTH` |
| Access / ID token validity | **1 hour** |
| Refresh token validity | **30 days** |
| Token revocation | **enabled** |
| `PreventUserExistenceErrors` | **ENABLED** |
| Callback URL | `https://d324z37do52g8f.cloudfront.net/auth/callback` |
| Logout URL | `https://d324z37do52g8f.cloudfront.net/` |

**INSPECT:** `Cognito -> user pool -> "App clients" -> lifelink-dev-web`.

### Three settings worth explaining

**No client secret.** A browser application cannot keep a secret — anyone can
read the JavaScript. So the client is **public**, and **PKCE** replaces the
secret: the app generates a random verifier, sends its hash when starting
login, and presents the original verifier when exchanging the code. An
intercepted authorization code is useless without the verifier.

**`PreventUserExistenceErrors: ENABLED`.** Without it, Cognito returns
`UserNotFoundException` for an unknown email and `NotAuthorizedException` for a
wrong password — which lets an attacker **enumerate valid email addresses**.
With it, both return the same generic error.

**`ADMIN_USER_PASSWORD_AUTH` is enabled, and that deserves honesty.** It lets a
backend authenticate a user with a raw password via an admin API. It is used
for **non-production test scripting** — provisioning and verifying demo logins.
It is not used by the browser, which uses the hosted UI and SRP. In a
production pool it should be disabled.

### Say this
> "One app client, and it's a public client with no secret — a browser app can't
> keep a secret, so instead we use Authorization Code with PKCE. The app
> generates a random verifier, sends only its hash when it starts the login, and
> presents the original when exchanging the code, which means an intercepted
> code is useless to anyone else.
>
> `PreventUserExistenceErrors` is on, so a wrong password and an unknown email
> return the same error — otherwise you could enumerate valid email addresses.
>
> One thing I'd change for production: `ADMIN_USER_PASSWORD_AUTH` is enabled,
> which we use for test scripting against demo accounts. It isn't used by the
> browser, but in a production pool I'd turn it off."

---

## D3. Token validity — the trade-off

| Token | Validity | Why |
|---|---|---|
| Access | 1 hour | short enough to limit a stolen token, long enough to avoid constant refreshes |
| ID | 1 hour | same |
| Refresh | 30 days | the user stays signed in across sessions |

**The trade-off to articulate:** roles are **not** read from the token, so a
one-hour access token does not mean a revoked role takes an hour to take
effect. The backend reloads the user record from DynamoDB on **every request**,
so a revoked role applies on the next request. The token lifetime only affects
how long a *stolen* token stays usable.

**Token revocation is enabled**, so a refresh token can be invalidated
explicitly on sign-out.

**INSPECT:** `Cognito -> user pool -> App clients -> lifelink-dev-web
-> "Authentication flow session duration" and token expiration settings`.

---

## D4. No groups, no custom attributes — the key design point

| | |
|---|---|
| **Cognito groups** | **zero** |
| **Custom attributes** | **zero** (only `sub` and `email`) |
| **Where roles live** | the `lifelink-dev-organizations` DynamoDB table |

**INSPECT:** `Cognito -> user pool -> "Groups" tab` — empty. And
`-> "Sign-up" -> Attributes` — no `custom:` attributes.

### Why not Cognito groups?

**This is a genuine design question and a good answer.**

1. **Immediate revocation.** A group membership baked into a one-hour token
   stays effective for up to an hour. A role in DynamoDB, read per request,
   is revoked instantly.
2. **Organization scoping.** A role is not global — a blood bank admin has
   authority over *their* facility. That needs a role plus an organization id
   plus a relationship, which is a record, not a flag.
3. **Account status.** Suspension must take effect immediately, which again
   means reading stored state.

**Cost:** one extra DynamoDB read per request. A few milliseconds.

### Say this
> "There are no Cognito groups and no custom attributes — all authorization data
> is in DynamoDB and read on every request. That's deliberate. If a role were a
> claim in the token, revoking someone's access would take up to an hour,
> because that's the token lifetime. Reading it from the database means a
> revoked role applies on the very next request. It also handles organization
> scoping, which a flat group can't express: a blood bank admin has authority
> over their own facility, not over blood banks in general. The cost is one
> extra read per request."

---

## D5. MFA, account recovery, and the hosted domain

| Setting | Deployed value | Comment |
|---|---|---|
| MFA | **OPTIONAL** | users may enable it; not enforced |
| Account recovery | verified email only | |
| Sign-in | email as username, email auto-verified | |
| Hosted domain | `lifelink-dev-426150327442` | `...auth.ap-southeast-2.amazoncognito.com` |
| User pool tier | **ESSENTIALS** | |
| Deletion protection | **INACTIVE** | |
| Lambda triggers | **none** | |
| Users | 11 |

**Honest note on MFA:** optional means effectively off for most users. For a
system touching health-adjacent coordination, required MFA for institutional
roles (blood bank and hospital admins) would be the right production setting.
Say that rather than presenting OPTIONAL as a considered security posture.

> **Privacy:** the 11 users include two real personal email addresses. **Do not
> read them aloud or screenshot them.** Demo accounts use the
> `@demo.lifelink.invalid` domain — `.invalid` is a reserved TLD that can never
> resolve, which is itself a nice detail: the demo addresses cannot
> accidentally email a real person.

---

# SECTION E — API Gateway (HTTP API)

## E1. Throttling — the concurrency defence

| Setting | Deployed value |
|---|---|
| `ThrottlingRateLimit` | **10 requests/second** |
| `ThrottlingBurstLimit` | **20** |
| `DetailedMetricsEnabled` | **true** |
| Per-route overrides | none |

**Why exactly 10?** Because the account's **Lambda concurrent execution limit
is 10**. Throttling at the gateway means excess load is rejected cheaply with a
429 instead of exhausting the Lambda pool and failing requests that are already
in flight.

**This is the single best "we understood our constraints" answer in the
project.** The number is not arbitrary — it is derived.

**INSPECT:** `API Gateway -> APIs -> the HTTP API -> Stages -> dev
-> "Default route throttling"`.

### Say this
> "Ten requests a second with a burst of twenty. That number comes directly
> from our Lambda concurrency limit, which is ten rather than the usual
> thousand on this account. Throttling at the gateway means excess traffic gets
> a cheap 429 instead of exhausting the Lambda pool and breaking requests that
> are already running. Shedding load at the edge is better than failing in the
> middle."

---

## E2. CORS

```json
{"AllowOrigins": ["https://d324z37do52g8f.cloudfront.net",
                  "http://localhost:5173", "http://127.0.0.1:5173"],
 "AllowMethods": ["GET","POST","PUT","PATCH","DELETE","OPTIONS"],
 "AllowHeaders": ["content-type","authorization","idempotency-key","x-correlation-id"],
 "ExposeHeaders": ["x-correlation-id"], "MaxAge": 600}
```

Covered in
[../02_SYSTEM_ARCHITECTURE/03_Frontend_To_Backend_Communication.md](../02_SYSTEM_ARCHITECTURE/03_Frontend_To_Backend_Communication.md).

**INSPECT:** `API Gateway -> the HTTP API -> "CORS"`.

**The deployment hazard:** `CorsAllowOrigins` is a stack parameter. Omit it on
a deployment and the CloudFront origin drops out of the list, breaking every
API call from the live site while the API itself stays healthy.

---

## E3. Routes, authorizers and integration

| Setting | Deployed value |
|---|---|
| Routes | **2**: `ANY /{proxy+}`, `ANY /` |
| Authorization type | **`NONE`** on both |
| **Authorizers** | **none** |
| Integration | `AWS_PROXY`, payload format **2.0**, timeout **30000 ms** |
| `DisableExecuteApiEndpoint` | false |
| Stage | `dev`, `AutoDeploy: true` |

**INSPECT:** `API Gateway -> the HTTP API -> Routes` (two entries) and
`-> Authorization` (empty).

**Expect the question "why no Cognito authorizer?"** The answer is in
[../02_SYSTEM_ARCHITECTURE/01_Complete_System_Architecture.md](../02_SYSTEM_ARCHITECTURE/01_Complete_System_Architecture.md)
§Layer 4: authorization needs the role and account status from DynamoDB, so an
authorizer would solve only a third of the problem and split the logic.

**Why is the integration timeout 30 s but the Lambda timeout 29 s?** So the
function fails **first**. If the Lambda ran longer, the gateway would give up
and return a bare 504 with no correlation id. At 29 s the application
returns its own error with a traceable id.

---

## E4. Access logging

| | |
|---|---|
| **Destination** | `/aws/apigateway/lifelink-dev` |
| **Format** | JSON: `requestId`, `ip`, `requestTime`, `method`, `routeKey`, `status`, `latency`, `integrationError` |
| **Retention** | 30 days |

**Why JSON rather than the default text format?** Because CloudWatch Logs
Insights can query JSON fields directly:

```
fields @timestamp, status, latency, routeKey
| filter status >= 400
| sort @timestamp desc
```

**INSPECT:** `API Gateway -> the HTTP API -> Stages -> dev -> "Logging"`.

---

# SECTION F — Lambda

## F1. Runtime, architecture, memory, timeout

All six functions are identical:

| Setting | Value |
|---|---|
| Runtime | **`python3.14`** |
| Architecture | **`arm64`** (Graviton) |
| Memory | **512 MB** |
| Timeout | **29 s** |
| Tracing | **Active** (X-Ray) |
| Layers | none |
| SnapStart | `None` / `Off` |
| Reserved concurrency | **not set** |
| Dead-letter config | none |
| Log format | Text |
| Code SHA256 | `Em9NdRR2EmRe/VAOdAq+iKsydKmXuiDqnZNKVkVT94g=` (shared) |

**INSPECT:** `Lambda -> Functions -> lifelink-dev-api -> Configuration tab
-> "General configuration"`.

### Why these values

**`arm64`:** Graviton is cheaper for the same capability. The catch is that the
deployment package must contain arm64 Linux wheels — which is exactly why
`sam build` cannot be used on a Windows machine. It would install a Windows
binary of `cryptography`, and RS256 token verification would fail to load.
`scripts/build_lambda_package.py` fetches `manylinux2014_aarch64` wheels
instead.

**512 MB:** Lambda allocates CPU in proportion to memory, so memory is really a
speed dial. 512 MB is where this workload stopped getting faster — below it,
JSON and crypto work slows down; above it, you pay for capacity that idles.

**29 s:** just under API Gateway's 30 s integration timeout, so the function
fails first and the error is ours.

**No reserved concurrency:** with only 10 concurrent executions available
account-wide, reserving any for one function would starve the others. Instead
the *queue consumers* are capped at the event-source level — see F3.

### Say this
> "All six functions are Python 3.14 on arm64 with 512 megabytes and a
> 29-second timeout. arm64 because Graviton is cheaper for the same work.
> 512 megabytes because Lambda scales CPU with memory, so it's really a speed
> dial — that's where this workload stopped getting faster. And 29 seconds
> deliberately, because API Gateway gives up at 30: we want the function to fail
> first so the error comes from our code with a correlation id, rather than a
> bare gateway 504."

---

## F2. Environment variables — and no secrets

API function, 12 variables:

```
LIFELINK_ENV=dev
LIFELINK_TABLE_PREFIX=lifelink-dev
COGNITO_USER_POOL_ID=ap-southeast-2_Z91jyFm1d
COGNITO_CLIENT_ID=5hp4pm3ictvetfupddvl41pnf
CORS_ALLOW_ORIGINS=https://d324z37do52g8f.cloudfront.net,http://localhost:5173,http://127.0.0.1:5173
WORK_QUEUE_URL=https://sqs.ap-southeast-2.amazonaws.com/426150327442/lifelink-dev-work
NOTIFICATION_QUEUE_URL=https://sqs.ap-southeast-2.amazonaws.com/426150327442/lifelink-dev-notifications
LOCATION_PLACE_INDEX=lifelink-dev-places
LOCATION_ROUTE_CALCULATOR=lifelink-dev-routes
LOG_LEVEL=INFO
POWERTOOLS_SERVICE_NAME=lifelink
SES_SENDER=            (empty)
```

**Every value is a non-secret identifier.** No passwords, no keys, no tokens.
That is the point to make: environment variables are visible to anyone with
`lambda:GetFunctionConfiguration`, so secrets belong in Secrets Manager — and
ours is `lifelink/dev/provider-api-keys`, fetched at runtime.

`LIFELINK_TABLE_PREFIX` is how one codebase addresses `lifelink-dev-*` tables
without hard-coding an environment.

**INSPECT:** `Lambda -> function -> Configuration -> "Environment variables"`.

### Say this
> "Twelve environment variables, and every one is a non-secret identifier —
> table prefix, pool id, client id, queue URLs. Nothing sensitive, which is
> deliberate: environment variables are readable by anyone who can describe the
> function, so a secret there isn't a secret. The one actual secret we have is in
> Secrets Manager and fetched at runtime."

---

## F3. Event source mappings — where concurrency is actually capped

| Consumer | Source | Batch | Window | Max concurrency | Failure handling |
|---|---|---|---|---|---|
| `outbox-publisher` | `outbox` stream, `LATEST` | 10 | 5 s | parallelization 1 | 3 retries, **bisect on error**, on-failure -> `work-dlq`, `ReportBatchItemFailures` |
| `work-worker` | SQS `work` | 5 | 10 s | **2** | redrive after 5 receives |
| `notification-worker` | SQS `notifications` | 5 | 10 s | **2** | redrive after 5 receives |

**INSPECT:** `Lambda -> function -> Configuration -> "Triggers"`.

### Three settings worth explaining

**`MaximumConcurrency: 2`** is the concurrency defence. Without it, a backlog
of queue messages would scale consumers up and consume all 10 of the account's
concurrent executions, leaving none for the API.

**`BisectBatchOnFunctionError: true`** on the stream: if a batch of 10 fails,
Lambda splits it in half and retries each half, repeatedly — isolating the one
bad record instead of blocking the whole batch. Without it, one poison record
stalls the stream shard.

**`ReportBatchItemFailures`** lets the function return *which* records failed,
so successful records in a batch are not reprocessed. Without it, one failure
in five means all five are retried.

### Say this
> "Both queue consumers are capped at two concurrent executions. That's the key
> setting, because we only have ten concurrent executions in the whole account —
> without the cap, a queue backlog would scale the workers up and starve the
> API. On the stream consumer we also enable batch bisection, so a single bad
> record gets isolated by halving the batch and retrying, instead of blocking
> the shard, and partial batch failure reporting so good records in a failed
> batch aren't reprocessed."

---

# SECTION G — SQS and SNS

## G1. Queue configuration

| Setting | Main queues | DLQs |
|---|---|---|
| Visibility timeout | **180 s** | 30 s |
| Message retention | **4 days** (345600 s) | **14 days** (1209600 s) |
| Delay | 0 | 0 |
| Receive wait time | 0 (short polling) | 0 |
| Max message size | 1 MB | 1 MB |
| **Encryption** | **SSE-SQS enabled** | **SSE-SQS enabled** |
| Redrive | `maxReceiveCount: 5` -> DLQ | — |

**Why visibility timeout 180 s for a 29 s function?** Because visibility
timeout must comfortably exceed the function's maximum runtime. If it expired
first, the message would become visible again and be processed **twice
concurrently**. 180 s is over six times the function timeout — generous on
purpose.

**Why 14-day DLQ retention?** A DLQ exists for a human to investigate. Four
days could expire over a long weekend; fourteen is the maximum SQS allows.

**Why `maxReceiveCount: 5`?** Enough retries to survive a transient failure
(a throttle, a brief DynamoDB blip), few enough that a genuinely broken
message reaches the DLQ promptly instead of retrying forever.

**INSPECT:** `SQS -> Queues -> lifelink-dev-work -> Details`, and the
"Dead-letter queue" section.

All four queues currently hold **0 messages**, visible and in flight — the
correct steady state.

### Say this
> "Four queues: two working queues and a dead-letter queue for each. The
> visibility timeout is 180 seconds against a 29-second function timeout —
> deliberately generous, because if visibility expired before the function
> finished, the message would be delivered again and processed twice at once.
> After five failed receives a message moves to the dead-letter queue, which
> retains for fourteen days rather than four, because a DLQ is for a human to
> investigate and four days could expire over a weekend. All four use SQS-managed
> encryption."

---

## G2. SNS alarm topic — a real gap

| | |
|---|---|
| **Topic** | `lifelink-dev-alarms`, display name "LifeLink operational alarms" |
| **Subscriptions confirmed** | **0** |
| **Subscriptions pending** | 0 |
| **Encryption** | not configured (`KmsMasterKeyId` absent) |

**All 8 CloudWatch alarms publish to this topic, and nobody is subscribed.**
Alarms fire into the void.

**INSPECT:** `SNS -> Topics -> lifelink-dev-alarms -> "Subscriptions" tab`
— empty.

**Why it happened:** the template creates the topic and wires the alarms to it,
but a subscription needs an endpoint — an email address or a phone number —
which is personal data that does not belong in a template committed to a
repository. So it was left to be added manually, and never was.

**The fix (not applied — engineering freeze):** add an email subscription in
the Console, or pass the address as a stack parameter.

### Say this — honest and shows understanding
> "Here's a gap. We have eight CloudWatch alarms and they all publish to an SNS
> topic — but the topic has zero subscriptions, so nothing actually notifies
> anyone. The alarms work: they evaluate, they change state, and you can see
> their history in the Console. But there's no delivery.
>
> It happened because a subscription needs an endpoint like an email address,
> and that's personal data I didn't want committed to the template. So it was
> left as a manual step and never done. It's a one-minute fix — add an email
> subscription and confirm it — and it's a good reminder that an alarm without a
> subscription is monitoring theatre."

---

# SECTION H — EventBridge Scheduler

| | `PriorityDispatcherEveryMinute` | `ScheduledMaintenanceEveryTenMinutes` |
|---|---|---|
| Expression | **`rate(1 minute)`** | **`rate(10 minutes)`** |
| Timezone | UTC | UTC |
| State | ENABLED | ENABLED |
| Flexible time window | **OFF** | OFF |
| Target | `lifelink-dev-dispatcher` | `lifelink-dev-maintenance` |
| Invocation role | `...PriorityDispatcherEveryMinuteRole-...` | `...ScheduledMaintenanceEveryTenMinutesRol-...` |
| Retry policy | max age 86400 s, **185 attempts** | same |
| **Dead-letter queue** | **none** | **none** |
| Input | none | none |

**This is `AWS::Scheduler::Schedule` — EventBridge Scheduler, the newer
service — not `AWS::Events::Rule`.** There are **zero** classic EventBridge
rules in this account. Getting this right matters, because they are different
Console pages.

**INSPECT:**
```
Amazon EventBridge -> Scheduler -> Schedules
  (NOT "Rules", which is empty)
```

**Scheduler versus Rules:** Scheduler is purpose-built for scheduled
invocation. It supports one-time schedules, timezones with daylight-saving
handling, flexible time windows to spread load, and a built-in retry policy
with a dead-letter target. EventBridge Rules does scheduling as a side effect
of event matching.

**Flexible time window OFF** means invoke exactly on the interval, not spread
within a window. For a dispatcher whose job is to reduce latency on urgent
requests, a deliberate delay would be wrong.

**The retry policy deserves honesty:** 185 attempts over 24 hours is the AWS
default, not a considered choice, and **no DLQ is configured**. So a target
that fails for a full day fails silently. Combined with the SNS gap in G2, a
dispatcher outage would be invisible.

### Say this
> "Two schedules on EventBridge Scheduler — the dispatcher every minute,
> maintenance every ten. Worth noting it's Scheduler, the newer service, not
> EventBridge Rules; we have no classic rules at all. Scheduler handles
> timezones and daylight saving properly and has a built-in retry policy.
>
> The flexible time window is off deliberately: the dispatcher exists to reduce
> latency on urgent requests, so spreading its invocation within a window would
> work against the point. Honestly, though, the retry policy is just the AWS
> default — 185 attempts over 24 hours — and there's no dead-letter queue, so a
> target failing all day would be silent. That plus the unsubscribed SNS topic
> is the weakest part of our operational setup."

---

# SECTION I — IAM

Full treatment: [../04_AWS_COMPLETE_GUIDE/08_IAM_Complete_Guide.md](../04_AWS_COMPLETE_GUIDE/08_IAM_Complete_Guide.md)
and [06_Showing_IAM_In_Action.md](06_Showing_IAM_In_Action.md).

**INSPECT:**
```
IAM -> Roles -> search "lifelink-dev"   (9 roles)
  -> lifelink-dev-ApiFunctionRole-vBxc6ik9DHz7
     -> "Trust relationships" tab  -> lambda.amazonaws.com
     -> "Permissions" tab          -> 2 managed + 16 inline policies
```

The single most important thing to be ready for: **one `Resource: "*"`
exists**, for `kms:GenerateDataKey` and `kms:Decrypt`, constrained by
`"kms:ViaService": "dynamodb.ap-southeast-2.amazonaws.com"`. Never call it
harmless — explain that it is scoped by **condition** rather than by resource,
and why that was necessary.

---

# SECTION J — Secrets Manager

| | |
|---|---|
| Secret | `lifelink/dev/provider-api-keys` |
| Encryption key | default `aws/secretsmanager` |
| **Rotation** | **not enabled** |
| **Last accessed** | **never** |

**INSPECT:** `Secrets Manager -> Secrets -> lifelink/dev/provider-api-keys`.
Look at the metadata; **do not click "Retrieve secret value"** during a
demonstration.

**Honest position:** the secret exists for external provider API keys in the
inventory ingestion path. It has never been accessed, because no external
provider is integrated in the demonstration environment. Rotation is not
enabled, which would matter if it held a live credential.

---

# SECTION K — Complete configuration inventory

Every non-default, security-relevant, reliability-relevant or cost-relevant
setting found in the live environment.

| # | Service | Setting | Deployed value | In template? | Section |
|---|---|---|---|---|---|
| 1 | S3 | Default encryption | SSE-S3 AES256 (both buckets) | yes | A1 |
| 2 | S3 | Bucket Keys | **false** | no | A1 |
| 3 | S3 | `BlockedEncryptionTypes` | `[SSE-C]` | **no** — `NEEDS-VERIFICATION` | A1 |
| 4 | S3 | Block Public Access | all 4 true | yes | A2 |
| 5 | S3 | Object ownership | `BucketOwnerEnforced` | yes | A3 |
| 6 | S3 | Versioning (frontend) | Enabled | yes | A4 |
| 7 | S3 | Website hosting | not configured | n/a | A5 |
| 8 | S3 | Lifecycle (uploads) | abort incomplete MPU after 7 days | yes | A6 |
| 9 | CloudFront | OAC | `E2QR15L70UVPZT` | yes | B1 |
| 10 | CloudFront | Viewer protocol | redirect-to-https | yes | B2 |
| 11 | CloudFront | Error responses | 403+404 -> `/index.html` 200, TTL 10 | yes | B3 |
| 12 | CloudFront | Cache policy | CachingOptimized (managed) | yes | B4 |
| 13 | CloudFront | Compression | true | yes | B4 |
| 14 | CloudFront | Allowed methods | GET/HEAD/OPTIONS | yes | B4 |
| 15 | CloudFront | Price class | PriceClass_100 | yes | B5 |
| 16 | CloudFront | WAF | **none** | n/a | B5 |
| 17 | CloudFront | Access logging | **disabled** | n/a | B5 |
| 18 | CloudFront | Min TLS | TLSv1 (default cert) | n/a | B5 |
| 19 | DynamoDB | Encryption | SSE-KMS `aws/dynamodb`, all 12 | yes | C1 |
| 20 | DynamoDB | PITR | 8 of 12 | yes | C2 |
| 21 | DynamoDB | Billing mode | PAY_PER_REQUEST, all 12 | yes | C3 |
| 22 | DynamoDB | TTL | 4 tables | yes | C3 |
| 23 | DynamoDB | Streams | `inventory` (NEW_AND_OLD), `outbox` (NEW) | yes | C3 |
| 24 | DynamoDB | Deletion protection | **false, all 12** | yes | C3 |
| 25 | DynamoDB | GSIs | 24 across 12 tables | yes | C3 |
| 26 | CloudWatch | Log retention | **30 days on 2, never on 4** | partial | **C4** |
| 27 | Cognito | Password policy | 12 + symbol | yes | D1 |
| 28 | Cognito | Client secret | **none** (public + PKCE) | yes | D2 |
| 29 | Cognito | OAuth flow | `code` | yes | D2 |
| 30 | Cognito | `PreventUserExistenceErrors` | ENABLED | yes | D2 |
| 31 | Cognito | `ADMIN_USER_PASSWORD_AUTH` | enabled (non-prod) | yes | D2 |
| 32 | Cognito | Token validity | 1 h / 1 h / 30 d | yes | D3 |
| 33 | Cognito | Token revocation | enabled | yes | D3 |
| 34 | Cognito | Groups / custom attributes | **none** | n/a | D4 |
| 35 | Cognito | MFA | OPTIONAL | yes | D5 |
| 36 | Cognito | Deletion protection | INACTIVE | yes | D5 |
| 37 | API Gateway | Throttle | 10 r/s, burst 20 | yes | E1 |
| 38 | API Gateway | CORS | 3 origins, 4 headers | yes | E2 |
| 39 | API Gateway | Authorizer | **none** | n/a | E3 |
| 40 | API Gateway | Integration timeout | 30000 ms | yes | E3 |
| 41 | API Gateway | Access logging | JSON -> CloudWatch | yes | E4 |
| 42 | API Gateway | Detailed metrics | true | yes | E1 |
| 43 | Lambda | Runtime / arch | python3.14 / arm64 | yes | F1 |
| 44 | Lambda | Memory / timeout | 512 MB / 29 s | yes | F1 |
| 45 | Lambda | X-Ray tracing | Active, all 6 | yes | F1 |
| 46 | Lambda | Reserved concurrency | **not set** | n/a | F1 |
| 47 | Lambda | Account concurrency | **10** | account limit | F1 |
| 48 | Lambda | ESM max concurrency | **2** on both queues | yes | F3 |
| 49 | Lambda | Bisect on error | true (stream) | yes | F3 |
| 50 | SQS | Visibility timeout | 180 s | yes | G1 |
| 51 | SQS | Retention | 4 d / 14 d DLQ | yes | G1 |
| 52 | SQS | Encryption | SSE-SQS, all 4 | yes | G1 |
| 53 | SQS | Redrive | maxReceiveCount 5 | yes | G1 |
| 54 | SNS | Subscriptions | **0** | n/a | **G2** |
| 55 | Scheduler | Expressions | 1 min / 10 min, UTC | yes | H |
| 56 | Scheduler | DLQ | **none** | n/a | H |
| 57 | IAM | Roles | 9, per-table inline policies | yes | I |
| 58 | IAM | Wildcard resources | **1**, condition-scoped KMS | yes | I |
| 59 | Secrets Manager | Rotation | **not enabled**, never accessed | yes | J |
| 60 | Location | Map / index / routes | Esri, SingleUse, deployed | yes | [09](09_Showing_Maps_And_Location.md) |

**Items 26, 54 and 56 are the three real operational gaps**, and all three were
found while writing this documentation. Presenting them yourself is far
stronger than being shown them.

---

## Sources for Console navigation labels

Console paths were cross-checked against current AWS documentation:

- [Configuring default encryption (S3)](https://docs.aws.amazon.com/AmazonS3/latest/userguide/default-bucket-encryption.html)
- [Configuring your bucket to use an S3 Bucket Key with SSE-KMS](https://docs.aws.amazon.com/AmazonS3/latest/userguide/configuring-bucket-key.html)
- [Viewing the settings for an S3 Bucket Key](https://docs.aws.amazon.com/AmazonS3/latest/userguide/viewing-bucket-key-settings.html)
- [Enable point-in-time recovery in DynamoDB](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/PointInTimeRecovery_Howitworks.html)
- [Backup and restore for DynamoDB](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Backup-and-Restore.html)

AWS occasionally relabels Console sections. If a label differs from what is
written here, the setting is still in the same tab — and saying "AWS has
renamed this since I wrote my notes" is a perfectly good answer.

---

## Cross-references

- [01_AWS_Console_Navigation.md](01_AWS_Console_Navigation.md)
- [02_Showing_S3_And_CloudFront.md](02_Showing_S3_And_CloudFront.md)
- [../04_AWS_COMPLETE_GUIDE/12_AWS_Security_And_Permissions.md](../04_AWS_COMPLETE_GUIDE/12_AWS_Security_And_Permissions.md)
- [../13_REFERENCE_AND_REVISION/05_Known_Limitations_And_Actual_Status.md](../13_REFERENCE_AND_REVISION/05_Known_Limitations_And_Actual_Status.md)
