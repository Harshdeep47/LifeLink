# Last-Minute Revision

**The last 30 minutes before the lab.** Read this, say the five answers out
loud, and stop.

---

## 1. The ten numbers

| Fact | Value |
|---|---|
| AWS account / Region | `426150327442` / **`ap-southeast-2`** (Sydney) |
| Deployed resources | **66**, one CloudFormation stack `lifelink-dev` |
| DynamoDB tables / indexes | **12 / 24** |
| Lambda functions | **6**, `python3.14` on `arm64`, 512 MB, 29 s |
| **Lambda concurrency limit** | **10** (not 1000) — **the key constraint** |
| API routes | **58**, of which **9** allow anonymous |
| Permissions / roles | **39 / 10** |
| Automated tests | **951** (657 backend, 294 frontend) |
| Rows of demo data | **742** |
| Cost | **$0.00 net/month** (gross ~$0.45-0.50, offset by credits) |

**Live URLs:**
- Site: `https://d324z37do52g8f.cloudfront.net`
- API: `https://uk6itz2a5b.execute-api.ap-southeast-2.amazonaws.com/dev`
- Commit: **`668a771`**

---

## 2. The five honesty rules

1. **Unknown is not zero.** Never reported ≠ no stock. **40 tests.**
2. **Updated is not verified.** Two timestamps, two badges, two permissions.
3. **An offer is not a reservation.** "Accepted — units held", never "approved".
4. **Dispatch order is not clinical priority.** Who is asked first, not who
   deserves blood.
5. **Fail closed.** If authorization is unclear, refuse.

---

## 3. The five answers to say out loud now

### "Where is it hosted?"
> "React compiled to static files in a private S3 bucket, served through
> CloudFront. The bucket has all public access blocked — CloudFront reaches it
> with an Origin Access Control, so S3 only accepts requests signed by our
> distribution."

### "Why Lambda and DynamoDB?"
> "Lambda because there's no server to patch and we pay per request. DynamoDB
> because Lambda scales to many concurrent executions and each one wanting a
> database connection is a real problem with RDS, and because an RDS instance
> bills hourly whether used or not. The cost is no joins and no ad-hoc queries —
> we designed 24 indexes up front."

### "How does authentication work?"
> "Cognito user pool. The browser redirects to the hosted login, gets an
> authorization code, and exchanges it for JWTs using PKCE. Our Lambda verifies
> the RS256 signature against Cognito's public keys, then loads the user's role
> **from DynamoDB** — not from the token — so revoking a role takes effect on the
> next request."

### "Have you tested it in a browser?"
> "The API and AWS resources were verified by script — fifty-six live checks.
> The browser workflows have **not** been independently verified by a person;
> there's no browser automation in this project and twelve manual checks are
> outstanding. I'd rather tell you that than claim coverage I don't have."

### "What's your best engineering story?"
> "We found four real defects after deployment, and two were invisible to over
> nine hundred passing tests. The worst: confirming a reservation **released its
> own hold**, which allows overselling blood. Found on the first live run of
> confirm-then-cancel. Six regression tests, four fail against the old code, and
> we re-verified all three paths with counters read **directly out of DynamoDB**
> rather than through our own API."

---

## 4. The eight traps

| Trap | The right answer |
|---|---|
| "You use REST API" | **HTTP API** (`ApiGatewayV2`), ~70% cheaper |
| "Cognito authorizer validates the JWT" | **No authorizer** — both routes `NONE`; the Lambda verifies |
| "You use Step Functions" | **Zero.** Scheduling is EventBridge **Scheduler**, not Rules either |
| "The map uses Amazon Location tiles" | **OpenStreetMap.** Location **API keys** are SCP-denied; we use Location server-side |
| "S3 Bucket Keys save you money" | **Disabled**, and we use **SSE-S3** — they'd save nothing |
| "Roles come from Cognito groups" | **Zero groups, zero custom attributes** — roles in DynamoDB |
| "There's a BloodRequest entity" | **ADR-0018** — ordinary requests **are** reservations |
| "Browser workflows are tested" | **No browser automation exists.** 12 checks outstanding |

---

## 5. Before you walk in

| # | Check |
|---|---|
| 1 | **`python scripts/seed_cloud.py --apply`** — or everything shows `Outdated` |
| 2 | Live site loads |
| 3 | AWS Console, **Region = `ap-southeast-2`** |
| 4 | 11 tabs pre-opened |
| 5 | DevTools open, Network tab, Fetch/XHR filtered |
| 6 | **Cognito user list filtered to `demo.lifelink.invalid`** — two real personal addresses are in that pool |
| 7 | Browser zoom up |

---

## 6. The three things to show if short on time

| # | Show | Why it lands |
|---|---|---|
| 1 | `/find` with a facility showing **"Not reported"** | the design principle, visible |
| 2 | Lambda Monitor beside the live site — the invocation appearing | the website connected to AWS, visibly |
| 3 | IAM dispatcher role — **no write actions on inventory** | least privilege proven by what it **cannot** do |

**If you have one more:** copy a `correlationId` from DevTools and find it in
CloudWatch Logs Insights.

---

## 7. The limitations, in one breath

> "Twelve browser checks outstanding. Demo data ages out after 48 hours. Email
> and SMS don't send — the notification worker has never been invoked and I can
> prove it, it has no log group. The map basemap is OpenStreetMap because
> Location API keys are denied. Our eight alarms publish to an SNS topic with no
> subscribers, so detection works and nobody is told. Four of six Lambda log
> groups never expire. And one stale reservation row holds nothing. The last
> three I found while writing the documentation."

---

## 8. If something breaks

| Problem | Say |
|---|---|
| Everything `Outdated` | "that's the freshness model working — the data is over 48 hours old and we're telling the truth rather than pretending" |
| Console count differs | "`DescribeTable`'s count refreshes about every six hours; five of our tables disagreed when I checked" |
| Resources "missing" | **wrong Region** — and use it as a teaching point |
| Map blank | "markers still render, because they come from our API, not the tile server" |
| A page errors | "I'd check X before claiming anything — let me show you Y instead" |
| Asked to change a setting | **"I'd change it in the template and redeploy — let me show you the line"** |

---

## 9. The two sentences to end on

> "The thing I'd most want to be judged on isn't that the tests pass — it's
> that we found four real defects after deployment and two were invisible to
> over nine hundred passing tests.
>
> What I took from that is that a green suite tells you about the cases you
> thought of."

---

## 10. Now stop reading

You know more than you can say in twenty minutes. The failure mode at this
point is not missing knowledge — it is talking too fast and skipping the
honesty.

**Three things:**

1. **Say the five answers in §3 out loud once more.**
2. **Volunteer the limitations before being asked.** It is the single highest-value
   behaviour available.
3. **When you do not know, say so** — and say what you would check.

---

## Cross-references

- [../13_REFERENCE_AND_REVISION/05_Known_Limitations_And_Actual_Status.md](../13_REFERENCE_AND_REVISION/05_Known_Limitations_And_Actual_Status.md)
- [01_Complete_Lab_Demonstration_Script.md](01_Complete_Lab_Demonstration_Script.md)
- [02_Teacher_Question_And_Answer_Bank.md](02_Teacher_Question_And_Answer_Bank.md)
- [../13_REFERENCE_AND_REVISION/05_Known_Limitations_And_Actual_Status.md](../13_REFERENCE_AND_REVISION/05_Known_Limitations_And_Actual_Status.md)
