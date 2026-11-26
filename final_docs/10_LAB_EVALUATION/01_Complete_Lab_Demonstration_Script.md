# Complete Lab Demonstration Script

A 20-minute demonstration in order, with timings, exact clicks and what to
say. Rehearse it once end to end.

---

## Before you walk in

| # | Check | How |
|---|---|---|
| 1 | **Re-seed the demo data** | `python scripts/seed_cloud.py --apply` — otherwise everything shows `Outdated` |
| 2 | Live site loads | open `https://d324z37do52g8f.cloudfront.net` |
| 3 | API healthy | `curl .../dev/health` -> `"status":"ok"` |
| 4 | Signed into AWS, **Region = `ap-southeast-2`** | top-right selector |
| 5 | **11 tabs pre-opened** | see [../09_PRACTICAL_AWS_DEMONSTRATIONS/01_AWS_Console_Navigation.md](../09_PRACTICAL_AWS_DEMONSTRATIONS/01_AWS_Console_Navigation.md) §3 |
| 6 | DevTools open on the site, Network tab, **Fetch/XHR** filtered | |
| 7 | Browser zoom increased | Console text is small on a projector |
| 8 | **Cognito user list filtered** to `demo.lifelink.invalid` | **two real personal addresses are in that pool** |
| 9 | VS Code open at the repository root | |
| 10 | A terminal in the project directory | |

**Step 1 is the one that ruins a demonstration if skipped.** Freshness expires
at 48 hours and verification at 72.

---

## 0:00–2:00 — The problem and the four features

**No screen yet. Just say it.**

> "LifeLink is a blood availability platform for Punjab. The problem it solves
> isn't a shortage of blood — it's that when a hospital needs blood urgently,
> nobody knows which nearby blood bank actually has it. So they phone around and
> waste time they don't have.
>
> It does four things. Blood banks record stock batch by batch with expiry
> dates. Hospitals search for what they need nearby and can request a temporary
> hold on specific units. Donors find donation camps and register. And a
> hospital can raise an urgent request that the system dispatches to several
> ranked providers automatically.
>
> It's fully serverless on AWS — 66 resources, 12 DynamoDB tables, 6 Lambda
> functions — and the net cost is zero, with gross usage under fifty cents a
> month covered by credits. All the data is synthetic,
> which I'll come back to, because that's deliberate."

---

## 2:00–6:00 — The live application

**Screen: the live site.**

| Time | Do | Say |
|---|---|---|
| 2:00 | Show the home page | "this is served from S3 through CloudFront" |
| 2:30 | Go to **/find**, set a location, search | "the search converts a radius into geohash cells, queries an index, then filters with the haversine formula" |
| 3:15 | **Point at a facility showing "Not reported"** | **the key moment — see below** |
| 4:00 | Point at the two badges — freshness and verification | "two separate axes: when it was updated versus when it was independently verified" |
| 4:30 | Open a facility detail page | the availability matrix |
| 5:00 | Show the map and its markers | "basemap is OpenStreetMap — I'll explain why" |
| 5:30 | **Paste a deep link into a fresh tab** | "no file with that name exists in S3 — CloudFront maps 403 and 404 to index.html" |

### The 3:15 moment — do not skip it

> "Look at this one: **Not reported**, with no number. That's the most important
> design decision in the project.
>
> A blood bank that has never reported its stock is **not** a blood bank with
> zero stock. Those lead a doctor to opposite actions — 'not reported' means
> phone them, 'none in stock' means don't. So we never render unknown as zero.
> There are forty automated tests enforcing just that one rule, which sounds
> excessive until you consider the consequence of getting it wrong."

---

## 6:00–8:00 — The code

**Screen: VS Code.**

| Time | Open | Say |
|---|---|---|
| 6:00 | `backend/src/domain/freshness.py` | "four constants — six, twenty-four, forty-eight hours for freshness, and a separate seventy-two-hour window for verification. That's the whole model, and notice `now` is a parameter so tests can sit exactly on a boundary" |
| 6:45 | `backend/src/appcore/auth.py`, the docstring | "five authorization checks in a fixed order, in one place" |
| 7:15 | `frontend/src/api/client.js`, the `api` object | "every API call in one module, so no component can forget the auth header — the client holds a *function*, not a token" |

**Then the trace**, if time allows:

> "If you asked me where a button goes, I'd grep the button text to find the
> component, find the `api.` call, look it up in the client, and that gives me
> the route and the handler. Five greps, about thirty seconds."

---

## 8:00–13:00 — AWS

**Screen: the AWS Console.**

### 8:00 — CloudFormation first

```
CloudFormation -> lifelink-dev -> Outputs
```

> "I'd start here because it answers a question before you ask it: all 66
> resources came from one CloudFormation template, not clicked together by hand.
> Every identifier is on this one screen, and the Resources tab is effectively a
> clickable index."

### 9:00 — DynamoDB

```
DynamoDB -> lifelink-dev-emergency -> Explore items -> PK = REQUEST#demo-req-p1-1
```

> "Twelve tables, 742 rows. This is the key design in one screen: the request,
> every event in its timeline, and every provider response all share one
> partition key — so one query returns the whole thing, sorted, with no joins.
>
> One thing to flag: the item count in the Console is approximate and refreshes
> about every six hours. Five of our twelve tables disagreed with reality when I
> checked, so if a number looks off, that's why."

Then `facilities -> Indexes`:

> "Five indexes here, and three of them are geohash tiers at precision four,
> five and six. We pick one based on the search radius, because one precision is
> either far too coarse for a two-kilometre search or needs hundreds of queries
> for fifty."

### 10:30 — Lambda, with the live site beside it

```
Lambda -> lifelink-dev-api -> Monitor
```

**Make a request on the live site. Watch the invocation count rise.**

> "That's the actual connection. There's no server — that function existed for a
> few hundred milliseconds to handle my request.
>
> And the number that shaped this whole architecture: our account's Lambda
> concurrency limit is **ten**, not the usual thousand. So the API Gateway
> throttles at exactly ten requests a second, both queue consumers are capped at
> two concurrent executions, and the timeout is twenty-nine seconds so a slow
> request releases its slot before API Gateway gives up at thirty."

### 11:30 — IAM, the least-privilege proof

```
IAM -> lifelink-dev-PriorityDispatcherRole-... -> Permissions -> JSON
```

> "Nine IAM roles, zero IAM users — so there's no access key anywhere to leak,
> which is the most common way AWS accounts get compromised.
>
> This is the dispatcher's role. Its job is to rank blood banks for an emergency
> request, so it reads inventory levels. Look at the actions on the inventory
> table: Get, Query, Scan, Describe. **No write actions at all.** The dispatcher
> physically cannot modify stock — not because the code doesn't try, but because
> the permission doesn't exist.
>
> And there's exactly one wildcard resource in our policies, for KMS, because
> DynamoDB's AWS-managed key has an ARN we can't know at template time. It's
> constrained with a `kms:ViaService` condition pinning it to DynamoDB, so it
> can't be used to decrypt anything else."

### 12:30 — Cognito, the empty Groups tab

```
Cognito -> lifelink-dev -> Groups    ->  EMPTY
```

> "This is the screen I most want you to see, and it's empty. No Cognito groups,
> no custom attributes. All authorization data is in DynamoDB and read on **every
> request**.
>
> If a role were a claim in the token, revoking someone's access would take up
> to an hour, because that's the token lifetime. Reading it from the database
> means it applies on the very next request. We verified that live: a suspended
> account holding a perfectly valid token gets a 403, not a 401."

---

## 13:00–15:00 — The correlation id trace

**Screen: DevTools and CloudWatch, side by side.**

```
1. DevTools -> Network -> the request -> Response -> copy correlationId
2. CloudWatch -> Logs Insights -> /aws/lambda/lifelink-dev-api
   fields @timestamp, @message
   | filter @message like /corr-XXXX/
   | sort @timestamp asc
```

> "Same request from both ends. Every response carries a correlation id and the
> same id is in the Lambda's logs, so a failure a user reports becomes an exact
> server-side log entry in thirty seconds. That's the thing I'd actually use."

**Rehearse this. Fumbling the Logs Insights UI undoes the effect.**

---

## 15:00–17:00 — Proving the tests are real

**Screen: terminal.**

```bash
python -m pytest backend/tests -q        # 657 passed
```

Then **break something**:

```bash
# Edit backend/src/domain/freshness.py:  FRESH_MAX_HOURS = 6.0  ->  100.0
python -m pytest backend/tests/unit/test_freshness_and_eligibility.py -q
# FAILURES, naming the boundary assertions
git checkout backend/src/domain/freshness.py
```

> "Rather than show you tests passing, which doesn't prove much, I'll break a
> rule. I'll widen the fresh-data threshold from six hours to a hundred — and
> the boundary tests fail immediately and name the assertion. That's how we know
> the suite constrains behaviour rather than just exercising it.
>
> 951 tests in total: 657 backend, 294 frontend."

---

## 17:00–19:00 — The limitations, volunteered

**No screen. Look up and say it.**

> "I want to be straight about what isn't done, because I'd rather tell you than
> have you find it.
>
> **The main gap is browser testing.** There's no browser automation in this
> project. The API and the AWS resources were verified by script — fifty-six
> live checks covering authentication, authorisation and the reservation
> workflows. But the browser workflows haven't been independently watched by a
> person; there are twelve manual checks outstanding, and sign-in is the one
> that matters most.
>
> **Second, our alarms notify nobody.** Eight CloudWatch alarms with thresholds
> I can justify, all publishing to an SNS topic with zero subscriptions. The
> detection works; nothing reaches a person. I found that while writing the
> documentation. One-minute fix.
>
> **Third, four of six Lambda log groups never expire.** Our template sets
> thirty-day retention, but only for the two log groups it declares; the rest
> were auto-created by AWS. That's an infrastructure-as-code coverage gap.
>
> **Fourth, email and SMS don't send.** Notifications are in-app only. I can
> prove the notification worker has never run — it has no CloudWatch log group
> at all, and a log group is created on first invocation.
>
> **And the map basemap is OpenStreetMap, not Amazon Location** — because
> creating a Location API key is denied by our account's service control policy.
> The Location resources themselves work; we use them server-side for geocoding
> and routing."

---

## 19:00–20:00 — Close with the defects you found

**This is the strongest close available.**

> "The thing I'd most want to be judged on isn't that the tests pass. It's that
> we found four real defects **after** deployment, and two of them were
> invisible to over nine hundred passing tests.
>
> The worst was in the reservation logic. Confirming a reservation **released
> its own hold** — the units became available to someone else while the
> reservation still claimed them, which allows overselling blood. The condition
> asked 'was this reservation holding units' instead of 'does it stop holding
> units', and both are true when you confirm a pending hold.
>
> We found it on the first live run of confirm-then-cancel. Six regression tests
> were added, four of which fail against the old code, and we re-verified all
> three transition paths with the counters read **directly out of DynamoDB**
> rather than through our own API — because otherwise we'd be trusting the thing
> we were testing.
>
> What I took from that is that a green test suite tells you about the cases you
> thought of."

---

## If you have only 5 minutes

| Time | Show |
|---|---|
| 0:00 | the live site, `/find`, and the **"Not reported"** badge |
| 1:30 | CloudFormation Outputs — "66 resources, one template" |
| 2:15 | DynamoDB `emergency` — one query, request + events + responses |
| 3:00 | Lambda Monitor + a live request — the invocation appearing |
| 4:00 | IAM dispatcher role — "read-only on inventory" |
| 4:30 | the limitations, briefly — browser testing, alarms |

---

## If something goes wrong

| Problem | Do this |
|---|---|
| Everything shows `Outdated` | **say it is correct**: "the data is more than 48 hours old and the system is telling the truth rather than pretending it's current" |
| The Console shows a different item count | "`DescribeTable`'s count refreshes about every six hours — five of our tables disagreed when I checked" |
| Resources "missing" in the Console | **wrong Region** — switch to `ap-southeast-2`, and use it as a teaching point |
| The site will not load | check CloudFront status; fall back to the API with `curl .../dev/health` |
| An AWS page errors | move on; do not debug live. Use the CLI instead |
| The map is blank | OSM tiles unavailable — "markers still render, because they come from our API" |
| No Lambda invocation appears | metrics lag; open **Monitor -> Logs** and show the newest stream instead |
| Asked to change a setting | **"I'd change it in the template and redeploy — let me show you the line"** |

---

## Cross-references

- [02_Teacher_Question_And_Answer_Bank.md](02_Teacher_Question_And_Answer_Bank.md)
- [03_Scenario_Based_Questions.md](03_Scenario_Based_Questions.md)
- [05_Last_Minute_Revision.md](05_Last_Minute_Revision.md)
- [../09_PRACTICAL_AWS_DEMONSTRATIONS/](../09_PRACTICAL_AWS_DEMONSTRATIONS/)
- [05_Last_Minute_Revision.md](05_Last_Minute_Revision.md)
