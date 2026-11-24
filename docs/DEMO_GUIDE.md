# LifeLink — Demonstration Guide

> **For a cloud computing evaluation**, pair this with
> [CLOUD_DEMONSTRATION_GUIDE](CLOUD_DEMONSTRATION_GUIDE.md), which covers
> Cognito, IAM, Lambda execution roles and DynamoDB with console paths and
> expected output. This guide walks the product; that one walks the cloud.

> **Check what is deployed before demonstrating.** The repository is ahead of
> the live site — [REPOSITORY_VS_DEPLOYED](REPOSITORY_VS_DEPLOYED.md). In
> particular the reservation screens are **not** live.

**Live site: https://d324z37do52g8f.cloudfront.net**

Deployed to AWS account 426150327442, `ap-southeast-2`, 15 November 2026.
Every record is synthetic. See [DEPLOYMENT_RECORD.md](DEPLOYMENT_RECORD.md) for
what was verified against the running system.

---

## Before you walk in

```bash
# 1. Confirm the site and API are up (both should print quickly)
curl -s https://d324z37do52g8f.cloudfront.net/ -o /dev/null -w "site %{http_code}\n"
curl -s https://uk6itz2a5b.execute-api.ap-southeast-2.amazonaws.com/dev/health

# 2. Mint a fresh sign-in token (they expire after 1 hour, so do this last)
cd d:/LifeLink
set AWS_PROFILE=lifelink
python scripts/provision_demo_logins.py --stack lifelink-dev ^
  --password "<from .local-keys/demo-logins.txt>" --token user-bb-admin-1
```

The account password is in `.local-keys/demo-logins.txt` (gitignored). Mint
tokens for `user-bb-admin-1`, `user-hosp-auth-1`, `user-admin-1` and
`user-suspended-1` and keep them in a scratch file — **tokens last one hour**,
so mint them shortly before you present.

**If the internet fails**, the whole stack runs locally — see
[LOCAL_DEVELOPMENT.md](LOCAL_DEVELOPMENT.md). Have it already running as a
fallback.

---

## The fifteen-minute script

### 0–1 min — The banner

Open the home page. Point at the striped banner.

> "Every record here is synthetic, and the banner cannot be dismissed. That is
> deliberate: a banner a user can close is one they will close, and then a
> screenshot of invented blood stock looks exactly like real data."

### 1–5 min — The search that makes the argument

Go to **Find blood**. Search **O-negative, PRBC, 4 units, 30 km from Patiala**.

Five results. Read them out in order, because the order *is* the point:

| # | Facility | Distance | State | Units | Freshness |
|---|---|---|---|---|---|
| 1 | Urban Estate Donor Centre | 4.2 km | Available | 9 | Fresh |
| 2 | Patiala Community Blood Bank | 2.3 km | Available | 12 | Stale |
| 3 | Rajindra Civil Blood Centre | **0.0 km** | **Partial** | **1** | Fresh |
| 4 | Nabha Rural Blood Unit | 22.9 km | None in stock | 0 | Fresh |
| 5 | Rajpura Collection Centre | 25.6 km | None in stock | 0 | Fresh |

> "The nearest facility is third. It is right here, and it has one unit of the
> four needed, so sending someone there wastes the only thing that matters.
>
> Second place is *nearer* than first and has *more* units — but its data is
> stale. First place is slightly farther, has enough, and was independently
> verified an hour ago.
>
> Nabha and Rajpura show zero. Nabha's stock is expired; Rajpura's is
> quarantined. Neither is counted as available, and neither silently
> disappears — because a facility vanishing from a list is indistinguishable
> from a facility that was never there."

**This is the single most important screen in the demonstration.** It shows the
system is not sorting by distance.

### 5–7 min — Unknown is not zero

Widen the radius to **60 km**. Eleven results. Scroll to **Tricity Voluntary
Blood Bank**.

> "This one says **Not reported** and shows no number at all. It has never
> submitted inventory. That is a different fact from zero, and it leads to the
> opposite action: a user who sees zero does not call; a user who sees *not
> reported* calls, and may find supply.
>
> The API returns `eligibleUnits: null` for that facility, never `0`. We found
> and fixed a bug in this exact behaviour **after deploying** — the search
> endpoint returned null correctly while the per-facility view returned zero.
> It is now enforced in the domain type, so no caller can get it wrong."

### 7–9 min — Facility detail and the two signals

Open **Rajindra Civil Blood Centre**. Show the availability matrix.

> "Every blood group against every component. Four distinct states per cell:
> available with a count, none in stock, not reported, not stocked. Collapsing
> any two of those loses information a user needs.
>
> And two separate quality signals on every figure — how recently it was
> updated, and whether a person independently verified it. A number thirty
> seconds old from an automated feed proves recency, not accuracy."

Click **Get directions**:

> "Straight-line distance, and it says so. Where routing is unavailable the
> system reports that, rather than presenting a straight line as a driving
> distance."

### 9–11 min — Sign in as a blood bank and change stock

Paste the `user-bb-admin-1` token on the sign-in page. Open the blood bank
dashboard.

Deduct a unit from a batch. Then point at **Verify**.

> "Verify is a separate action from any stock edit. Clicking it asserts that a
> person checked the figures; it does not change them. That separation is what
> makes 'updated' and 'verified' mean different things — and exactly one method
> in the entire codebase is permitted to write the verification timestamp."

If asked how the sign-in works:

> "That is a real Cognito access token, signed by the user pool, verified by
> the API against the pool's published keys. What we did not build is the
> browser redirect to Cognito's hosted login page, so the token is obtained by
> a script and pasted. The verification is genuine; the convenience is missing."

### 11–13 min — Role separation and suspension

Paste the `user-hosp-staff-1` token.

> "Hospital staff can raise requests and see the queue. They cannot certify
> clinical priority, and the dashboard says so rather than showing a button
> that fails."

Paste `user-hosp-auth-1`. The certification buttons appear. Certify a request
as Urgent.

> "That recorded my account, my role, my hospital and the time. It also
> re-checked that this hospital is verified *right now* — a hospital suspended
> since the request was raised cannot certify it."

Paste `user-suspended-1`.

> "This account holds the blood bank admin role. The token is valid, unexpired
> and correctly signed. Every action is refused, because authorization reads
> account status from the database on every request rather than trusting the
> token. A system that trusts token claims cannot do this."

### 13–15 min — Audit, and the honest close

Paste `user-admin-1`. Open the administrator dashboard. Query the audit trail
by actor `user-bb-admin-1` — your stock change from earlier is there.

> "Who, what, which resource, when, and the correlation id that links it back
> to the original request. In AWS the Lambda role has `PutItem` and `Query` on
> this table and nothing else — no update, no delete — so the application
> physically cannot rewrite its own history."

Close with this, not with a feature:

> "Three things I will not claim. The blood compatibility reference has not
> been reviewed by a qualified professional, so this must not be used
> clinically. The data is invented — the coordinates are real cities, the
> institutions are not. And the restore procedure in our runbook has never been
> rehearsed, so it is marked untested rather than described as a backup
> strategy."

---

## Questions you will be asked

**"Is it really deployed?"** Yes — one CloudFormation stack, `lifelink-dev`, in
`ap-southeast-2`, most recently updated on 24 November 2026. The site is
CloudFront over a private S3 bucket; the API is API Gateway HTTP API in front
of **six** Lambda functions; the database is **12 DynamoDB tables with 24
global secondary indexes**. Step Functions is not used.

**"Is this real blood data?"** No. 16 fictional facilities, all named
"(DEMO)", every record tagged `demoData`, `SYNTHETIC`, `DEVELOPMENT`. Real city
coordinates so distances are meaningful; no real institution.

**"What did deploying teach you?"** That a green test suite is not evidence a
thing works. Deploying and then *exercising* it found defects no local check
caught — most recently a reservation that released its held units when a
facility confirmed it, which permitted overselling
(`docs/RESERVATION_COUNTER_DEFECT.md`). The first deployment found five more
that passed every local test and both template linters: the Lambda handler
path was wrong so the function could not start; the deployment package needed
Linux arm64 wheels built without Docker; the outbox publisher lacked one IAM
grant that only Lambda validates; every route 404ed because the API Gateway
stage name prefixes the path; and the
"unknown is not zero" rule was broken in one of two code paths. That is the
argument for deploying rather than trusting a validated template.

**"How do you know it works?"** 480 automated tests — 400 backend, 80 frontend
— plus live verification of the deployed API recorded in
[DEPLOYMENT_RECORD.md](DEPLOYMENT_RECORD.md): radius behaviour, ranking order,
authentication, cross-organization refusal and role separation, all against the
running system.

**"What does it cost?"** $0.40/month fixed, covered by $120 of promotional
credits. The customer-managed KMS key that would have cost $1.00/month was
replaced with an AWS-managed key, and the trade-off is documented.

**"What is the weakest part?"** The compatibility reference, because it is
unreviewed. Then the absence of the Cognito browser redirect. Then that no
alarm has ever fired and the restore has never been rehearsed — both
configured, neither observed.

**"Could it be used for real?"** Not as it stands, and the documentation says
so in the same words.

---

## If something goes wrong

| Symptom | Fix |
|---|---|
| Site loads, no results | Check the API: `curl .../dev/health`. If 200, re-seed: `python scripts/seed_cloud.py --stack lifelink-dev --apply` |
| 401 on every signed-in action | The token expired — they last 1 hour. Mint a new one. |
| 403 where you expected success | Probably correct. Check the role: staff cannot certify; a blood bank cannot read another org's data. |
| Grey map panel | Expected if tiles fail; the list view is the demonstration. Not verified in a browser. |
| Site unreachable | Fall back to local: [LOCAL_DEVELOPMENT.md](LOCAL_DEVELOPMENT.md) |
| Sudden `AccessDenied` everywhere | Check the spend limit in AWS Settings > Billing |

Deeper diagnosis: [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

## Exact commands, in order, for tomorrow

```bash
cd d:/LifeLink
set AWS_PROFILE=lifelink

# Is it alive?
curl -s https://uk6itz2a5b.execute-api.ap-southeast-2.amazonaws.com/dev/health

# Is the data still there? (expects 24/24)
python scripts/seed_cloud.py --stack lifelink-dev --verify-only

# Fresh tokens, minted last
python scripts/provision_demo_logins.py --stack lifelink-dev ^
  --password "<from .local-keys/demo-logins.txt>" --token user-bb-admin-1

# Open the site
start https://d324z37do52g8f.cloudfront.net
```
