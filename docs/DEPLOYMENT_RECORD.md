# LifeLink — Deployment Record

**LifeLink is deployed and live.** This document records the actual
deployment, the defects it exposed, and what was verified against the running
system rather than against the template.

> **This record superseded the "never deployed" statements elsewhere in the
> library.** Those were accurate when written, earlier the same day.
>
> **Update, 24 November 2026:** those statements have since been corrected at
> source. `KNOWN_LIMITATIONS.md` no longer claims nothing is deployed, and the
> three PDF books were regenerated after the same correction. The current
> repository-versus-deployed position is in `REPOSITORY_VS_DEPLOYED.md`.

---

## 0. Addendum — the 24 November 2026 deployment

Added after the original record below, which describes the 15 November
deployment and is left unedited.

### What was deployed

| # | What | Identifier | Outcome |
|---|---|---|---|
| 1 | Frontend | invalidation `I76XJI99TM91I1THIOYYR9BXFN` | 13 files to `lifelink-dev-frontend-426150327442`; invalidation **Completed** |
| 2 | Backend | changeset `samcli-deploy1795507818` | stack `UPDATE_COMPLETE` 08:15:37 UTC |
| 3 | Backend | changeset `samcli-deploy1795508812` | stack `UPDATE_COMPLETE` 08:33:22 UTC |

Published to `github.com/Harshdeep47/LifeLink`, branch `main`, as commit
`f9765af20c22be144c8926d65c3602f63923e1c9`. The initial commit was
preserved as its parent; nothing was rewritten or force-pushed.

Region `ap-southeast-2` throughout. Account `426150327442`. Cost unchanged at
**~$0.40/month** — no resource was created, and the existing SAM artifact
bucket was reused.

Final state: six Lambdas on CodeSha256
`Em9NdRR2EmRe/VAOdAq+iKsydKmXuiDqnZNKVkVT94g=`, live bundle
`index-AW8_zfLM.js`, both matching the repository.

### How each changeset was reviewed before it ran

Both were created with `--no-execute-changeset` and inspected by **diffing the
deployed processed template against the changeset's template** — not by
reading the changeset summary, which lists eleven entries because
CloudFormation conservatively flags every resource that *references* a Lambda.
The diff was identical both times:

- 67 resources → 67. No additions, removals or replacements.
- 12 DynamoDB tables → 12, **not one differing property**. Deletion and
  update-replace policies identical.
- No IAM role or policy differed. API Gateway `Body` identical.
- The only difference: the six Lambdas' `Code.S3Key`.

### Two hazards avoided

**Parameters must be passed explicitly.** The template's defaults are
development values. Omitting `CognitoDomainPrefix` would have **replaced the
Cognito user pool domain**; omitting `CorsAllowOrigins` would have dropped the
CloudFront origin and broken CORS on the live site. All seven deployed values
were read from the running stack and passed back verbatim.

**`sam build` must not be used on this host.** It installs the local
platform's wheels, and `cryptography` — required for RS256 token verification
— would be a Windows binary that cannot load on arm64 Lambda. Both deployments
used `python scripts/build_lambda_package.py --verify`, which fetches
`manylinux2014_aarch64` wheels: 505 files, 23.4 MB, no key material, all six
handler entry points verified. `docs/DEPLOYMENT.md` has been corrected.

### What the deployment shipped

The reservation queue and My Activity screens, record provenance display, the
"Emergency request" relabel, the expired-session fix, the sign-up password
policy fix, and the Cognito ID-token audience check — then, after the first
backend deployment, the reservation counter fix (below).

### A defect found by verifying, not by testing

The first live run of `confirm → cancel` failed. Root cause: confirming a
reservation released its held units, permitting **overselling** and leaving the
confirmed hold impossible to cancel or fulfil. Full post-mortem:
[RESERVATION_COUNTER_DEFECT](RESERVATION_COUNTER_DEFECT.md).

Fixed, six regression tests added (four failed before the fix), deployed as
changeset 3, and re-verified live.

This is the second time in this project's history that a defect survived a
green suite and was caught only by exercising the deployed system. The first
set is in §3 below.

### Verified against the running system

**56 live checks, all passing** — 19 authentication, 37 workflow.

| Area | Result |
|---|---|
| Six Lambdas | all `Active` / `Successful`, one shared SHA |
| `health`, `reference`, public facilities, public camps | 200 |
| `/me`, `/admin/audit`, reservation POST without a token | 401 |
| Real access token / real ID token on `/me` | 200 / 200 |
| Garbage, rewritten-`aud`, self-signed-other-client tokens | 401 |
| Donor on `/admin/audit`, and on another facility's queue | 403 / 403 |
| Blood bank admin on its own facility's queue | 200 |
| Suspended account with a valid token | **403 `ACCOUNT_SUSPENDED`** |
| Cognito refuses `Password1` | `InvalidPasswordException` — the password the old frontend accepted |
| `PENDING → CONFIRMED → FULFILLED` | counter 0 → 2 → 2 → 0 |
| `PENDING → CONFIRMED → CANCELLED` | counter 0 → 2 → 2 → 0 |
| `PENDING → CANCELLED` | counter 0 → 2 → 0 |
| `heldUnits` vs API `reservedUnits` | equal at all ten checkpoints |
| Second requester against a fully-held pool | refused `NO_UNRESERVED_STOCK` |
| Camp search near Patiala | 6 camps, `effectiveRadiusKm` 20 |
| Donor on emergency provider queue / certify | 403 / 403 |

Counter figures were read **directly from DynamoDB**, not inferred from the
API.

### Data integrity

Every table's item count was captured before the first deployment and
re-checked after the last: facilities 16, inventory 487, camps 46,
organizations 62, emergency 85, audit 8, donations 14, notifications 18 —
**unchanged**. No table was altered, no record deleted, and no production row
was hand-edited.

Reservations grew from 4 rows to 9 because verification created and closed test
holds. All nine are accounted for: 6 `CANCELLED`, 1 `FULFILLED`, 1 `EXPIRED`,
and 1 stale `CONFIRMED` row that holds nothing
([KNOWN_LIMITATIONS](KNOWN_LIMITATIONS.md) §1.15). **Every pool counter is
zero** — nothing is held.

### Not verified

**No browser.** No browser automation was available, so no UI workflow has
been watched by anyone. Twelve manual checks are listed in
[REPOSITORY_VS_DEPLOYED](REPOSITORY_VS_DEPLOYED.md) §6.

**The audience fix's exact case.** A validly pool-signed ID token for a
*different* app client cannot be produced, because the pool has exactly one app
client — which is also why the flaw was never exploitable. Proven instead by
unit test, verified by reverting the fix.

---

## 1. What is live

| | |
|---|---|
| **Website** | **https://d324z37do52g8f.cloudfront.net** |
| **API** | https://uk6itz2a5b.execute-api.ap-southeast-2.amazonaws.com/dev |
| Stack | `lifelink-dev`, status `UPDATE_COMPLETE` |
| Account | 426150327442 |
| Region | ap-southeast-2 |
| Deployed | 15 November 2026, first create 15:11 UTC |
| Cognito user pool | `ap-southeast-2_Z91jyFm1d` |
| Cognito app client | `5hp4pm3ictvetfupddvl41pnf` |
| Identity pool | `ap-southeast-2:31685707-e3c3-4aa0-b4ca-b753c70b8688` |
| Frontend bucket | `lifelink-dev-frontend-426150327442` |
| CloudFront distribution | `E236QHMFXHDEDL` |
| Amazon Location map | `lifelink-dev-map` |
| Alarm topic | `arn:aws:sns:ap-southeast-2:426150327442:lifelink-dev-alarms` |

Resources created: **50**, from `infrastructure/template.yaml`. 11 DynamoDB
tables, 6 Lambda functions, 1 HTTP API, 4 SQS queues (2 work + 2 dead-letter),
3 S3 buckets, CloudFront with Origin Access Control, 5 Cognito resources, 3
Amazon Location resources, 1 Secrets Manager secret, SNS, 8 alarms, 1
dashboard, 2 log groups.

## 2. Cost

| Item | Monthly |
|---|---|
| Secrets Manager secret | $0.40 |
| **Fixed total** | **$0.40** |

The original design used a customer-managed KMS key for the audit table at
$1.00/month. On the owner's instruction this was changed to the AWS-managed key
`alias/aws/dynamodb`, which carries no monthly charge. The trade is recorded in
[SECURITY.md](SECURITY.md): an AWS-managed key cannot carry its own key policy,
so the audit table loses the KMS-level barrier against an account
administrator. The application-level protection is unchanged — the Lambda role
still holds only `PutItem` and `Query`.

Everything else sits inside free tiers at demonstration volume. Promotional
credits at deployment: **$120, active, expiring 2027-05-15.** The usage-based
items that would grow with real traffic are CloudWatch Logs ingestion
($0.50/GB, mitigated by 30-day retention on every log group) and Amazon
Location map tile loads.

**Charges that survive stack deletion.** Three resources carry
`DeletionPolicy: Retain`: the audit table, and (in production only) the
CloudTrail bucket. After `sam delete` these must be removed by hand or they
continue to incur storage charges. The KMS key that previously had this problem
no longer exists.

## 3. Defects that only deployment could find

Five defects were found by deploying. **Every one of them passed `cfn-lint`,
`sam validate --lint`, and the full local test suite.** They are recorded here
because they are the argument for deploying rather than trusting a validated
template.

### 3.1 The Lambda handler paths were wrong — would never have started

`backend/pyproject.toml` sets `pythonpath = ["src"]`, so modules import each
other as `appcore.auth`. The template declared `CodeUri: ../backend/` with
`Handler: src.handlers.api.lambda_handler`, which in Lambda raises
`ModuleNotFoundError: No module named 'appcore'`.

Fixed: the deployment package contains the *contents* of `src/` at its root and
handlers are addressed as `handlers.api.lambda_handler`.

### 3.2 No Docker, and two dependencies are compiled

`cryptography` (RS256 verification) and `pydantic-core` contain native
extensions. `sam build` installs with the local interpreter and platform —
Windows x86-64 — while the target is Amazon Linux 2023 on arm64. The usual
answer, `sam build --use-container`, needs Docker, which is not installed.

Fixed by [scripts/build_lambda_package.py](../scripts/build_lambda_package.py),
which asks pip for `manylinux2014_aarch64` / cp314 wheels explicitly with
`--only-binary=:all:` so a wrong-platform build fails loudly instead of
silently. Package: 499 files, 23.3 MB.

### 3.3 The outbox publisher could not be created

First deployment failed and rolled back:

```
The function execution role does not have permissions to call SendMessage on SQS
```

The event source mapping declares an `OnFailure` destination of `WorkDlq`, and
Lambda validates that grant when it creates the mapping. The function held
`SendMessage` on `WorkQueue` and `NotificationQueue` but not on the
dead-letter queue. A cross-resource consistency rule only the service enforces;
no linter can see it.

### 3.4 Every route returned 404

The first live request:

```json
{"error": {"code": "NOT_FOUND", "message": "no route for GET /dev/health"}}
```

An HTTP API on a named stage serves `/dev/health` and reports `rawPath` as
`/dev/health`, while the route table is written as `/health`. Locally there is
no stage, so all 50 routes matched; deployed, none did.

Fixed by `strip_stage_prefix()` in
[handlers/router.py](../backend/src/handlers/router.py), which reads the stage
from `requestContext.stage` rather than a constant. Pinned by 19 tests in
`test_stage_prefix.py`.

### 3.5 The headline rule was broken in one of two code paths

A facility that has never reported returned, from the live API:

```json
{"availability": "UNKNOWN", "eligibleUnits": 0}
```

`AvailabilitySummary.eligible_units` was typed `int` and set to `0` for an
unreported facility. The search endpoint special-cased it and published `null`;
the per-facility availability matrix published `0`. A client reading the matrix
would show "0 units" for a facility that has never submitted anything — the
exact misreading the project's first rule exists to prevent.

Fixed in the domain: `eligible_units` is now `int | None` and `None` when the
state is UNKNOWN, so every caller inherits the distinction instead of being
trusted to remember it. Pinned by 40 tests in `test_unknown_is_not_zero.py`,
including all 32 group/component cells and the reverse case — a facility that
reports and has nothing must still say `0`.

**Live confirmation after the fix:**

```
availability : UNKNOWN
eligibleUnits: None
```

## 4. Deployed demonstration data

Seeded through the application's own repositories by
[scripts/seed_cloud.py](../scripts/seed_cloud.py). Every record is synthetic
and carries `demoData: true`, `dataSource: "SYNTHETIC"`,
`environment: "DEVELOPMENT"`.

| Table | Items |
|---|---|
| organizations (orgs + users) | 45 |
| facilities | 16 |
| inventory | 417 batches + 7 showcase = 419 after reconciliation |
| camps | 23 |
| donations | 14 |
| emergency | 29 |
| alerts | 5 |

**24/24 coverage checks passed against the deployed database**, including all
8 blood groups, all 4 components, quarantined and expired stock, four freshness
bands, verified and unverified batches, all 6 camp lifecycle states, P1/P2/P3
requests, a suspended user and 9 distinct roles.

16 fictional facilities across Patiala, Rajpura, Nabha, Chandigarh, Mohali,
Zirakpur, Ambala, Amritsar, Bathinda, Sangrur, Jalandhar and Ludhiana. Every
name carries a `(DEMO)` suffix. The coordinates are real city centres — which
is what makes distance behaviour demonstrable, and what originally exposed the
geohash coverage defect — but **no institution named in the dataset exists**,
and a map pin asserts a demonstration location, never a real facility.

### Seeding safety

Five independent guards, four of which existed before the fifth was found to be
necessary:

1. The stack's own `Environment` parameter must be `dev` or `development`.
2. `DYNAMODB_ENDPOINT` must not be set.
3. The caller's account must match the stack's account.
4. The table prefix must carry the environment name.
5. **The effective boto3 client must actually point at AWS.**

Guard 5 exists because guards 1–4 were not enough. `seed_demo` sets
`DYNAMODB_ENDPOINT` to localhost at import time, and `seed_cloud` imported it
*after* clearing that variable — so the first two runs wrote every record to
the **local** database while reporting success against the deployed stack.
Nothing failed. The console output was indistinguishable from a successful
cloud seed, and only an independent query of the AWS tables (all zero) revealed
it.

The lesson, recorded because it generalises: **a guard on configuration is
weaker than a guard on what configuration produces.** Guard 5 inspects the real
client — its endpoint, its region, its resolved table name — immediately before
the first write.

`seed_cloud.py` has no delete path at all. The one destructive operation needed
lives in a separately named script,
[scripts/reconcile_showcase_batches.py](../scripts/reconcile_showcase_batches.py),
which deletes only `demoData` batches of O-negative PRBC at the seven showcase
facilities that are not `demo-showcase-*`, previews by default, and guards each
delete with a `demoData = true` condition at the database. It removed 5 stale
batches left behind when a change to the batch-numbering logic orphaned them;
487 items were untouched.

## 5. Verified against the running system

Every result below came from an HTTP request to the deployed API, not from a
local run.

### Public discovery

| Check | Result |
|---|---|
| `GET /health` | 200, `environment: "dev"` |
| `GET /reference` | 200, all 8 groups and 4 components |
| Radius 10 km from Patiala | 3 facilities |
| Radius 30 km | 5 |
| Radius 60 km | 11 |
| Radius 120 km | 400 `VALIDATION_ERROR`, "radius cannot exceed 100.0 km" |

### Ranking is not a distance sort

`GET /facilities?lat=30.3398&lon=76.3869&radiusKm=30&bloodGroup=O-&component=PRBC&units=4`

| # | Facility | Distance | State | Units | Freshness |
|---|---|---|---|---|---|
| 1 | Urban Estate Donor Centre (DEMO) | 4.2 km | AVAILABLE | 9 | FRESH |
| 2 | Patiala Community Blood Bank (DEMO) | 2.3 km | AVAILABLE | 12 | STALE |
| 3 | Rajindra Civil Blood Centre (DEMO) | **0.0 km** | **PARTIAL** | **1** | FRESH |
| 4 | Nabha Rural Blood Unit (DEMO) | 22.9 km | UNAVAILABLE | 0 | FRESH |
| 5 | Rajpura Collection Centre (DEMO) | 25.6 km | UNAVAILABLE | 0 | FRESH |

Reading that table is the demonstration:

- The **nearest** facility is **third**, because it can supply 1 of 4 units.
- A facility 1.9 km **nearer** with **more** stock is **second**, because its
  data is stale.
- The winner is slightly farther, sufficient, fresh and independently verified.
- Nabha's stock is **expired** and Rajpura's is **quarantined**; both are
  excluded by the index itself, and report 0 rather than disappearing.

Widening to 60 km adds Zirakpur (53.2 km, 20 units, fresh — plentiful but far),
Ambala as genuinely zero, and:

| Facility | State | Units |
|---|---|---|
| Tricity Voluntary Blood Bank (DEMO) | **UNKNOWN** | **None** |

That last row is the whole project in one line: a facility that has never
reported says so, and reports no number.

### Authentication and authorization

Using a **real Cognito access token**, minted by
[scripts/provision_demo_logins.py](../scripts/provision_demo_logins.py) and
verified by the deployed API against the pool's JWKS.

| Check | Result |
|---|---|
| No token on a protected route | 401 `UNAUTHENTICATED` |
| Malformed token | 401 `UNAUTHENTICATED` |
| Blood bank admin reads own facility's batches | 200, real batch data |
| Blood bank admin reads **another org's** facility | 403 `CROSS_ORGANIZATION_DENIED` |
| Blood bank admin calls a donor-only route | 403 `FORBIDDEN`, `required: registration:manage:own` |

The third and fourth rows together are the IDOR defence working in production.
The fifth is role separation: the token is valid and the account active, and the
request is still refused.

### Frontend hosting

| Check | Result |
|---|---|
| `GET /` via CloudFront | 200, `text/html` |
| Deep link `/find-blood` | 200, serves `index.html` (SPA routing) |
| `assets/index-*.js` | 200, `text/javascript`, `max-age=31536000, immutable` |
| `index.html` cache header | `no-cache, no-store, must-revalidate` |

The bundle is verified at publish time to contain the deployed API host, so it
cannot be built against a stale endpoint —
[scripts/deploy_frontend.py](../scripts/deploy_frontend.py) fails the publish
otherwise.

## 6. The local-auth refusal, in the environment it was written for

The deployed API runs with `LIFELINK_ENV=dev`, and
[appcore/environment.py](../backend/src/appcore/environment.py) refuses local
mode in three independent ways. The defect it closed was real and worse than
first documented: `LIFELINK_ENV` **defaulted to `"local"`**, so a Lambda
deployed without that variable would have selected the *development* token
verifier instead of Cognito. The only thing preventing an authentication bypass
was the absence of a key file from the deployment package.

The package builder now also refuses to ship any `*.pem`, `*.key` or `.env`
file, so there are two independent protections rather than one accident.

`GET /health` reporting `"environment": "dev"` is the live confirmation that
the deployed process took the Cognito branch.

## 7. Limitations of this deployment

Stated plainly, because a working URL invites the assumption that everything
works.

1. **The Cognito hosted-UI redirect is not implemented in the frontend.** The
   sign-in page accepts a pasted token. The *verification* path is the real
   Cognito one — tokens are genuine, signed by the pool and checked against its
   JWKS — but the browser-side authorization-code-with-PKCE exchange does not
   exist, so a presenter pastes a token minted by
   `provision_demo_logins.py`. The `SignInPage` docstring claimed this flow;
   the claim was wrong and is corrected in
   [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md).
2. **`ALLOW_ADMIN_USER_PASSWORD_AUTH` is enabled on this app client**, outside
   production only, so a script can obtain a real token. It is an admin API
   guarded by IAM, not a browser flow, and the template omits it when
   `Environment` is `prod`.
3. **Map tiles are untested in the browser.** The Amazon Location map resource
   exists and the identity pool is configured, but no browser session has been
   observed rendering tiles.
4. **Email is sandboxed.** SES reports `ProductionAccessEnabled: false`, 200
   messages/day, 1/second. Only verified addresses can receive.
5. **SMS is not implemented** — denied by the account's service control policy.
6. **Point-in-time restore is still untested.** PITR is enabled on 7 tables;
   the restore procedure in [OPERATIONS_RUNBOOK.md](OPERATIONS_RUNBOOK.md) §8
   has not been rehearsed.
7. **No load testing.** The Lambda concurrency ceiling on this account is 10,
   and the architecture is built for it, but no measurement has been taken
   under load.
8. **The eight alarms have never fired.** They are configured and mapped to
   runbook steps; none has been triggered, so none has been observed working.
9. **The three PDF books predate deployment** and state that nothing is
   deployed. They have not been regenerated. This file is the correction.
10. **The blood compatibility reference remains unreviewed** by a qualified
    professional. Deployment changes nothing about this. **LifeLink must not be
    used for clinical decisions.**

## 8. Teardown

```bash
cd infrastructure
sam delete --stack-name lifelink-dev --region ap-southeast-2
```

Then remove by hand, because they are retained deliberately:

- DynamoDB table `lifelink-dev-audit`
- The SAM deployment bucket, if no other stack uses it
- The 8 Cognito demo users, if the pool is kept

Verify afterwards that no DynamoDB table, Lambda function or CloudFront
distribution named `lifelink-dev*` remains, and check AWS Settings > Billing.
