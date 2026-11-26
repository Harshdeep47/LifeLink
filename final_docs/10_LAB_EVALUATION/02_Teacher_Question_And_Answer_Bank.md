# Teacher Question and Answer Bank

The questions you will actually be asked, with a 30-second answer, a longer
answer, and the follow-up each one invites.

**Read the answers out loud.** Reading and speaking are different skills, and
the lab tests the second.

---

## A — Hosting and architecture

### "Where is the website hosted?"

**30 s:**
> "The React app is compiled to static files and stored in a private S3 bucket,
> `lifelink-dev-frontend-426150327442`, served worldwide through CloudFront at
> `d324z37do52g8f.cloudfront.net`. The bucket has all public access blocked —
> CloudFront reaches it with an Origin Access Control, so S3 only accepts
> requests signed by our distribution."

**Follow-up: "Show me that the bucket is private."**
> Copy the S3 object URL for `index.html`, paste it in a new tab — **Access
> Denied**. Then open the CloudFront URL — the site loads. Same file, two URLs.

### "Which AWS Region are you using?"

**30 s:**
> "`ap-southeast-2`, Sydney, for everything regional. CloudFront and IAM are
> global services. Our account is a new AWS experience project with a single
> assigned Region derived from the contact address, so Mumbai wasn't available
> even though our data is about Punjab."

**Follow-up: "Isn't that bad for Indian users?"**
> It costs about 150 to 200 milliseconds per API call versus maybe 30 to 50 for
> Mumbai. CloudFront absorbs most of the user-visible impact, because the static
> site is cached at an edge near the user — only API calls make the trip. If I
> could move it, it'd be a parameter change and a redeploy, because everything's
> in one template.

### "Which Availability Zone are you in?"

**The good answer:**
> "We don't choose one, and that's the point of managed serverless services. S3
> and DynamoDB replicate across at least three Availability Zones automatically
> and don't let you choose. If we ran EC2 or RDS we'd be picking subnets and
> deciding whether to pay for a multi-AZ standby. The redundancy is built in and
> we can't misconfigure it — we also can't tune it."

### "Draw or explain your architecture."

**1–2 min:**
> "The React app is static files in S3, served through CloudFront over HTTPS.
> The browser gets a JWT from Cognito using Authorization Code with PKCE, then
> calls an HTTP API, which proxies every request to one Lambda function. That
> function verifies the token itself, loads the user's role from DynamoDB,
> checks the permission, and reads or writes twelve DynamoDB tables.
>
> Work that shouldn't block a response goes into an outbox table in the same
> transaction as the main write; a DynamoDB Stream picks it up and fans it to
> SQS queues, where two worker Lambdas consume it. Two more Lambdas run on
> EventBridge Scheduler — a dispatcher every minute and maintenance every ten.
>
> The constraint that shaped it is that our Lambda concurrency limit is ten, not
> a thousand. So the gateway throttles at ten requests a second and each queue
> consumer is capped at two."

---

## B — The database

### "Where is the database? Show me."

**30 s:**
> "DynamoDB, twelve tables prefixed `lifelink-dev-`, in ap-southeast-2. Let me
> open `lifelink-dev-facilities` — sixteen facilities, every key prefixed
> `FACILITY#`."

**Follow-up: "Show me a record with related data."**
> `lifelink-dev-emergency`, filter `PK = REQUEST#demo-req-p1-1`. You get the
> request, every event in its timeline and every provider response in one
> result, because they share a partition key.

### "Why DynamoDB and not a relational database?"

**1–2 min:**
> "Two reasons that actually decided it. First the connection model: Lambda
> scales to many concurrent executions, and each one wanting a database
> connection is a real problem with RDS — you end up adding RDS Proxy to fix it.
> DynamoDB is stateless HTTPS, so there's nothing to pool. Second, idle cost: an
> RDS instance bills by the hour whether anyone uses it; ours costs effectively
> nothing.
>
> What we gave up is ad-hoc querying. If you asked me for average time from
> emergency request to first response, by district, last quarter — that's one
> SQL statement in Postgres and genuinely awkward here. We designed 24 indexes
> up front for the queries we knew about."

### "Why twelve tables instead of single-table design?"

> "Single-table is the usual DynamoDB advice and it does minimise round trips.
> We chose domain tables mainly for a security reason: separate tables let us
> scope each Lambda role's policy to exactly the tables it needs. That's how our
> dispatcher can read inventory and be physically unable to write it. With one
> table, every role would need access to everything in it. The cost is that
> cross-domain reads are explicit joins in application code."

### "How do you find facilities within 20 km?"

**1–2 min:**
> "DynamoDB can't answer that — there's no geospatial index. So we encode each
> facility's coordinates as a geohash, a string where a shared prefix means
> geographic proximity, and index that.
>
> A search works out which geohash cells cover the circle, queries an index for
> each cell, and then filters the union with the haversine formula. That second
> step isn't optional: the cells are rectangles that over-cover the circle, so
> without it a twenty-kilometre search would return something twenty-eight
> kilometres away in a corner. The index narrows the candidates; the formula
> gives the right answer.
>
> We keep three index tiers at precision four, five and six and pick one from
> the radius, because one precision is either far too coarse for a small search
> or needs hundreds of queries for a large one."

---

## C — Compute

### "Why Lambda and not EC2?"

**30 s:**
> "No server to patch or keep running, and we pay per request — a demonstration
> workload costs cents. Our traffic is request-response with short work, which
> is what Lambda suits. The honest trade-offs are cold starts and a hard
> concurrency ceiling; ours is ten, which is why the gateway throttles at ten
> requests a second."

**Follow-up: "When would EC2 be better?"**
> A persistent WebSocket connection, a job taking an hour, or a process holding
> a large in-memory model. Lambda caps at fifteen minutes and charges for every
> millisecond of a long job. Also a steady high-volume workload — per request
> Lambda is more expensive than a running server; there's a crossover.

### "What happens if Lambda fails?"

**1–2 min:**
> "It depends on the invocation type, and that distinction is the point. A
> synchronous API call returns an error with a stable code and a correlation id.
> An SQS-triggered invocation doesn't lose the message: it goes back on the
> queue, is retried, and after five failed receives moves to a dead-letter queue
> that retains for fourteen days. The stream consumer retries three times and
> bisects the batch to isolate a bad record.
>
> There are alarms on errors and throttles. Honestly though — they publish to an
> SNS topic with no subscriptions, so detection works and nothing reaches a
> person. That's a real gap and a one-minute fix."

### "How does it handle a traffic spike?"

> "CloudFront and S3 wouldn't notice — static files are cached at the edge.
> DynamoDB on-demand scales. The bottleneck is Lambda: with ten concurrent
> executions, the gateway throttles at ten requests a second and everything
> beyond gets a 429. That's deliberate — shedding load at the edge is better
> than exhausting the pool and breaking requests already running.
>
> To scale, you'd raise the account concurrency limit, raise the throttle, and
> probably split the API function by feature so one slow route can't consume the
> pool. The architecture doesn't need to change — the limits do."

---

## D — Authentication and authorization

### "How does authentication work?"

**30 s:**
> "A Cognito user pool. The browser redirects to Cognito's hosted login, the
> user signs in there, and Cognito returns an authorization code that the app
> exchanges for JWTs using PKCE. Every API call carries the access token, and
> our Lambda verifies the RS256 signature against Cognito's public keys. We
> never see or store a password."

### "What's the difference between an access token and an ID token?"

**30 s:**
> "The access token authorizes API calls — it's for the resource server and
> carries scopes. The ID token describes who the user is and is for the client
> application; it carries profile claims like email. We send the access token.
> The detail that matters: Cognito puts the audience in **different claims** —
> `client_id` on an access token and `aud` on an ID token — which is exactly the
> bug we found and fixed."

**Follow-up: "What was the bug?"**
> Code that checks only one of those fields silently fails to validate the other
> token type. We now select the claim based on `token_use`, and normalise it
> because the spec allows `aud` to be an array. Reverting the fix fails three of
> twenty-three unit tests. I should be honest that I can't demonstrate the
> attack, though — our pool has exactly one app client, so a cross-client token
> can't be produced. That's also why it was never exploitable.

### "How does Lambda know who the user is?"

> "It verifies the token signature against the pool's JWKS, takes `sub` from the
> claims, then loads that user's record from the organizations table to get
> their role. **The role is never taken from the token.**"

### "Can someone modify a JWT?"

> "They can change the bytes, but not without breaking the signature. It's
> signed RS256 with Cognito's private key, which we never have, and we verify
> with the public key. We tested a token with a rewritten audience claim and a
> self-signed token for another client — both rejected with 401."

### "What happens when a token expires?"

> "Tokens last an hour. The API returns 401, the client clears the stored
> session and redirects to sign-in, and a refresh token valid for thirty days
> can get new tokens without a password.
>
> We had a real bug here: expired sessions were never cleared, because the code
> referenced an undefined variable and the resulting `ReferenceError` was
> swallowed by an empty catch block. We found it by turning on ESLint, and we
> made empty catch blocks an error — the real failure was that a programming
> mistake could hide inside error handling."

### "Why aren't roles in Cognito groups?"

**The answer to have ready:**
> "Because revocation. A group baked into a one-hour token stays effective for
> up to an hour. A role read from the database applies on the very next request —
> we verified live that a suspended account with a perfectly valid token gets a
> 403.
>
> It also handles something a flat group can't express: a blood bank admin isn't
> an admin in general, they have authority over their own facility. That's a
> role plus an organization plus a relationship — a record, not a flag. The cost
> is one extra read per request."

### "How does IAM differ from Cognito?"

> "They answer different questions. IAM controls what our AWS *services* can do
> — can this Lambda read this DynamoDB table. Cognito identifies our
> *application users* and gives them a JWT. A blood bank admin has no IAM
> identity at all. The one place they meet is the identity pool, which can trade
> a Cognito token for temporary AWS credentials — we deployed that for map tiles
> and ended up not using it."

### "Show me your IAM roles."

> `IAM -> Roles -> search lifelink-dev` — nine roles, zero IAM users.
>
> "Zero users means no access key exists to leak, which is the most common way
> AWS accounts get compromised. Let me open the dispatcher's role: its job is to
> rank blood banks, so it reads inventory — and look, no write actions on that
> table at all. It physically cannot modify stock."

### "You have `Resource: '*'` — isn't that bad practice?"

**Have this ready verbatim:**
> "There's exactly one, and I'd rather point it out than have you find it. It's
> for two KMS actions, because DynamoDB encrypts with the AWS-managed
> `aws/dynamodb` key and that key's ARN contains an id AWS generated — it isn't
> knowable when we write the template, so the policy can't name it.
>
> But it has a `kms:ViaService` condition pinning it to
> `dynamodb.ap-southeast-2.amazonaws.com`, so the permission can only be used
> **through DynamoDB**. If the function tried to call KMS directly to decrypt
> something else, the condition fails and it's denied. It's scoped by condition
> rather than by resource, which is the right tool when the ARN isn't knowable.
>
> To remove it entirely I'd use a customer-managed key, which gives a known ARN,
> for about a dollar a month."

---

## E — Configuration

### "How does S3 Bucket Keys reduce KMS request costs?"

**The honest answer, which is not the flattering one:**
> "It would, if we used SSE-KMS on S3 — and we don't. Both buckets use SSE-S3,
> where AWS manages the keys and no KMS requests happen at all. Bucket Keys are
> disabled, and enabling them here would save nothing.
>
> What they actually do: with SSE-KMS, S3 calls KMS once per object operation —
> every upload and download. A Bucket Key makes S3 fetch a short-lived
> bucket-level key and derive per-object keys locally, cutting KMS requests by
> up to 99%. It only applies to new objects.
>
> I can show you independently that we never used SSE-KMS on S3: in KMS, the
> `alias/aws/s3` alias has no key behind it. AWS creates that automatically on
> first use, so its absence is proof. Our KMS usage is DynamoDB — all twelve
> tables, AWS-managed key."

### "Where did you configure that? Show me."

**The universal answer:**
> "Everything is in `infrastructure/template.yaml` — one SAM template, about
> fifteen hundred lines, deployed as one CloudFormation stack. Nothing was
> clicked together by hand. I can show you the setting in the Console and then
> the line in the template."

Then use [../09_PRACTICAL_AWS_DEMONSTRATIONS/CONFIGURATION_WALKTHROUGHS.md](../09_PRACTICAL_AWS_DEMONSTRATIONS/CONFIGURATION_WALKTHROUGHS.md).

### "Can you change this setting now?"

**Do not change it:**
> "I'd change it in the template and redeploy rather than here — let me show you
> the line. Changing it in the Console creates drift: the live resource would no
> longer match the code that's supposed to define it, so the next deployment
> would either overwrite my change or fail confusingly."

---

## F — Data and correctness

### "Where did the data come from?"

> "A generator script with a fixed random seed, so it produces the same dataset
> every time — 62 organizations, 16 facilities, 487 inventory batches, 46 camps,
> 742 rows in total. Everything is invented: the coordinates are real places in
> Punjab and the institutions at them are fictional, with every record flagged
> as synthetic.
>
> We did try to use real Punjab blood bank data and the public sources were
> unreachable. The alternative would have been inventing plausible details and
> labelling them as real institutions, which is worse than obviously fake data."

### "What happens when inventory is UNKNOWN?"

> "It shows as 'Not reported' with **no number**, never as zero. A blood bank
> that's never reported is not a blood bank with no stock — those lead a doctor
> to opposite actions. One means phone them, the other means don't. We have
> forty automated tests enforcing just that rule."

### "How do you prevent two people reserving the same units?"

> "A pool row holds a counter of units currently held, and a reservation writes
> the reservation row and updates that counter in a single DynamoDB transaction,
> conditioned on there still being enough unreserved units. If two hospitals
> request the last two units at once, one transaction commits and the other
> fails its condition entirely. We verified live — the second requester gets
> `NO_UNRESERVED_STOCK`."

**Follow-up: "Did that always work?"**
> No, and it's the most useful thing I can tell you. The transaction was right
> but the logic deciding when to *release* held units was wrong — it asked 'was
> this holding units' instead of 'does it stop holding units', and both are true
> when you confirm a pending hold. So confirming a reservation released its own
> units, which allows overselling. Over nine hundred tests were passing; we
> found it on the first live run. Six regression tests, four fail against the old
> code, and we re-verified all three paths with counters read straight out of
> DynamoDB.

### "How does the map get the user's location?"

> "The browser's Geolocation API. A web page has no hardware access at all — it
> asks the browser, the browser asks the user for permission and then the
> operating system, which works out a position from GPS, Wi-Fi, cell towers or
> the IP address. We get a latitude, longitude and accuracy, and never learn
> which method was used. If permission is denied, the user searches for a place
> instead and everything else works the same."

### "Why isn't the map using AWS?"

> "The basemap imagery is OpenStreetMap; geocoding and routing **are** Amazon
> Location, server-side. The reason is specific: MapLibre is a renderer and
> can't sign AWS requests, so browser access to Location tiles needs an API
> key — and creating one is denied by our account's service control policy. The
> error is literally 'Access denied for operation AWS::Location::APIKey'.
>
> It's actually my best example of policy evaluation, because a service control
> policy is an explicit deny at the organization level that no IAM policy can
> override."

### "How are notifications delivered?"

> "In-app only. We write a record to the notifications table and the user sees
> it — there are eighteen of those. Email is wired but not configured; the
> sender address is empty. SMS isn't implemented, both by decision and because
> our account's policy blocks it.
>
> The strongest evidence: the notification worker Lambda has **no CloudWatch log
> group**, which means it has never been invoked — a log group is created on
> first invocation."

---

## G — The honesty questions

### "Have you tested this in a browser?"

**Have this ready. It is the most important answer in the bank.**
> "The API and the AWS resources were verified by script — fifty-six live
> checks covering authentication, authorisation and all three reservation
> transition paths. The browser workflows have **not** been independently
> verified by a person. There's no browser automation in this project, and
> twelve manual checks are outstanding — sign-in being the one that matters
> most, because everything else depends on it.
>
> I'd rather tell you that than claim coverage I don't have."

### "What doesn't work?"

**Volunteer the list. Do not make them extract it.**
> "Twelve browser checks outstanding. The demo data ages out after forty-eight
> hours, so it needs re-seeding before a demonstration. Email and SMS don't
> send. The map basemap isn't AWS. Our eight alarms publish to an SNS topic with
> no subscribers, so detection works and nobody is told. Four of six Lambda log
> groups never expire, because our template only sets retention on the two it
> declares. And there's one stale reservation row left over from before the
> counter fix — it holds nothing and the UI shows it as expired.
>
> The last three I found while writing the documentation rather than while
> building."

### "What would you do differently?"

> "Four things. I'd use TypeScript — one of our real bugs was an undefined
> variable it would have caught immediately. I'd declare a log group per Lambda
> in the template, so retention actually applies. I'd add the SNS subscription
> on day one, because an alarm nobody's subscribed to is monitoring theatre. And
> I'd add custom business metrics — how many units are held, how long providers
> take to respond — which we have none of."

### "Is any of this real?"

> "The AWS infrastructure is completely real — 66 deployed resources you can
> inspect, and the site is live. The **data** is entirely synthetic by design,
> because a site showing blood availability could do real harm if someone
> mistook invented figures for real ones. The site is `noindex, nofollow`, the
> description says it's a demonstration environment, `/health` returns
> `demoEnvironment: true`, and every record carries a `demoData` flag."

---

## Cross-references

- [01_Complete_Lab_Demonstration_Script.md](01_Complete_Lab_Demonstration_Script.md)
- [03_Scenario_Based_Questions.md](03_Scenario_Based_Questions.md)
- [05_Last_Minute_Revision.md](05_Last_Minute_Revision.md)
- [../11_INTERVIEW_PREPARATION/](../11_INTERVIEW_PREPARATION/)
- [../13_REFERENCE_AND_REVISION/05_Known_Limitations_And_Actual_Status.md](../13_REFERENCE_AND_REVISION/05_Known_Limitations_And_Actual_Status.md)
