# Scenario-Based Questions

"What would happen if…" — the unpredictable questions. The pattern for
answering them is more useful than memorising any single answer.

---

## The pattern for any scenario question

**Four steps, in order:**

1. **Name the layer** that would notice first.
2. **Say what actually happens** — the concrete behaviour, not the intention.
3. **Say what the user sees.**
4. **Say what is missing**, if anything.

**Step 4 is what distinguishes a good answer.** Most people stop at step 3.

---

## A — Load and scale

### "A thousand users hit the site at once."

> "CloudFront and S3 wouldn't notice — static files are cached at the edge, and
> a cache hit never touches S3.
>
> The API is where it breaks. Our account's Lambda concurrency limit is ten, so
> the gateway throttles at ten requests a second with a burst of twenty.
> Everything beyond that gets a 429. DynamoDB on-demand would cope fine.
>
> The user sees the site load normally and searches failing with a rate-limit
> error. The client marks 429 as retryable, so the UI offers a retry.
>
> What's missing is any per-IP fairness — we have no WAF, so a flood would hit
> the throttle and legitimate users would get 429s too. To actually scale you'd
> raise the concurrency limit, raise the throttle, and split the API function by
> feature so one slow route can't consume the whole pool."

### "DynamoDB starts throttling."

> "On-demand capacity scales automatically, so throttles are rare — it adapts to
> the previous peak and then ramps. When one happens, boto3 retries with
> exponential backoff, and a persistent failure surfaces as an error with a
> correlation id. There's an alarm at more than five throttles in five minutes
> on the inventory table.
>
> Our realistic hot partition is a single busy facility's inventory, because
> batches share the facility's partition key. A facility with thousands of
> batches would need a time component in the key. At 487 rows it isn't a problem
> yet."

### "Your Lambda hits the concurrency limit."

> "Two different outcomes, and the difference is the point.
>
> Synchronous API invocations get a throttle error, which the gateway returns as
> 429 — load is shed. Asynchronous ones don't lose anything: an SQS message goes
> back on the queue and is retried, and after five receives it dead-letters.
>
> So the user-facing path degrades and the background path just gets slower.
> That's exactly why deferrable work is on a queue. There's an alarm on
> throttles — which, honestly, publishes to an SNS topic with no subscribers."

---

## B — Failures

### "A whole AWS Region goes down."

> "LifeLink would be unavailable. It's a single-Region deployment, and
> multi-Region isn't possible in this account — cross-Region replication,
> multi-Region KMS keys and StackSets are all denied by policy.
>
> CloudFront would keep serving cached static files for a while, so the shell
> might load, but every API call would fail.
>
> Architecturally the answer is DynamoDB global tables, a second stack, and
> Route 53 latency routing. The hard part isn't the infrastructure, it's the
> data: global tables are eventually consistent and resolve conflicts
> last-writer-wins, which is **actively wrong** for our reservation counters —
> two Regions could both accept a hold on the same units. You'd have to pin all
> writes for a facility to one Region."

### "The database is unavailable."

> "Every request that needs data fails with a 500 and a correlation id. There's
> no cache layer, so nothing degrades gracefully — that's an honest gap.
>
> Reads could be made more resilient with DynamoDB Accelerator or an
> application cache, but writes fundamentally can't be: you can't accept a blood
> reservation you're unable to record. For this system, failing closed is the
> right behaviour — telling a hospital their units are held when we couldn't
> record it would be worse than an error."

### "A notification fails to send."

> "It's already failing, and I can prove it: the notification worker Lambda has
> **no CloudWatch log group**, which means it's never been invoked. Email isn't
> configured — the sender address is empty.
>
> What does work is in-app notifications: the services write records directly to
> the notifications table and the user sees them. There are eighteen.
>
> If the worker were running and failed, the message would return to the queue,
> be retried, and after five receives move to a dead-letter queue with
> fourteen-day retention and an alarm on it."

### "The map configuration is missing."

> "`VITE_MAP_STYLE_URL` is empty by design — that selects the OpenStreetMap
> basemap. The example env file warns explicitly that setting it to a style the
> browser can't authenticate against gives a blank map.
>
> If OSM tiles were unavailable you'd get a blank basemap with the **markers
> still rendering**, because those come from our own API. There's also a
> fallback panel for when WebGL isn't available at all.
>
> We learned to be careful here: a MapLibre worker that failed to load once
> looked exactly like a data problem — no markers — so there's now a test
> pinning the worker setup."

### "KMS becomes unavailable."

> "Every DynamoDB read and write fails, because all twelve tables are encrypted
> with the AWS-managed `aws/dynamodb` key and DynamoDB calls KMS to decrypt.
> There's no application-level mitigation; it would be a full outage.
>
> Worth noting that our IAM policy for KMS is condition-bound to DynamoDB, so
> the Lambda can't call KMS for anything else even if it wanted to."

---

## C — Security scenarios

### "Someone steals a user's token."

> "They can act as that user for up to an hour — that's inherent to bearer
> tokens.
>
> What limits it is that the role **isn't in the token**. If we suspend that
> account, the very next request with that same token gets a 403, because
> account status is read from the database on every request. So a stolen token
> **cannot outlive a revocation**, which it would if the role were a claim.
>
> They'd also only get that user's permissions — a donor's token gets a donor's
> thirteen — and they still couldn't reach another organization's records."

### "Someone tries to access another hospital's requests."

> "403. That's the organization scoping check, the fifth of five in our
> authorization decorator, and it's applied centrally rather than per handler —
> which is how IDOR bugs normally happen, by being forgotten in one handler out
> of fifty-eight.
>
> We verified it live: a blood bank admin gets 200 on their own facility's
> reservation queue and 403 on another facility's. The pairing matters — showing
> just the 403 wouldn't prove scoping, it could mean the endpoint is broken."

### "A Lambda function is compromised."

> "The attacker gets that function's execution role with temporary credentials.
> From the API role they could read and write our twelve tables and send to our
> two queues.
>
> They could **not** create AWS resources, touch IAM, read S3, or decrypt
> anything outside DynamoDB — the KMS statement is condition-bound. They
> couldn't escape the account's service control policies. And they couldn't
> alter an audit record, because that role has `PutItem` and `Query` on the
> audit table and no update or delete permission.
>
> The realistic damage is our own data, which is why the audit table is
> append-only from that role."

### "An unauthorized user tries to certify clinical priority."

> "403. `emergency:certify:priority` is held by only three of our ten roles —
> hospital authorizer, hospital admin and platform admin. We verified live that
> a donor attempting it gets 403, and a donor reading the provider queue also
> gets 403.
>
> It's a separate permission because certifying urgency is a medical judgement.
> The system records who certified it and never makes the judgement itself —
> which is also why we say dispatch order is not clinical priority."

### "There's a cross-site scripting vulnerability in your frontend."

**The honest answer:**
> "Then the token would be stolen, because the session is in `localStorage`
> which any JavaScript on our origin can read. That's the real residual risk and
> I won't pretend otherwise.
>
> What reduces the chance is that React escapes interpolated content by default,
> we don't use `dangerouslySetInnerHTML` anywhere, and we load **no third-party
> JavaScript at all** — so the attack surface is only our own code.
>
> The more secure option is an httpOnly cookie, which JavaScript can't read.
> That needs a backend session endpoint and brings CSRF into scope. We accepted
> `localStorage` with a one-hour token. I'd call that a fair criticism rather
> than defend it as optimal."

---

## D — Data correctness scenarios

### "Two staff edit the same inventory batch at the same time."

> "The second one fails. Each batch row carries a `version`, and updates are
> conditioned on the version you read. Staff A writes and the version moves to
> 8; staff B's write still expects 7, so the condition fails and they get a 409
> `CONCURRENT_MODIFICATION`.
>
> That's marked retryable, so the UI offers a retry — and the retry **re-reads
> the current value** rather than blindly re-applying, so the operator decides
> again against the truth."

### "Two hospitals reserve the last two units simultaneously."

> "One succeeds, one gets `NO_UNRESERVED_STOCK`. A pool row holds a counter of
> held units, and the reservation row and that counter are written in one
> DynamoDB transaction conditioned on `heldUnits` plus the request not exceeding
> available units. All or nothing — if the condition fails, neither write
> happens.
>
> Verified live. And this is where we found our worst bug: confirming a
> reservation used to *release* its own hold, which allows overselling. Over
> nine hundred tests were passing."

### "The synthetic data is wrong — a facility shows impossible values."

> "Two defences. `scripts/validate_facility_dataset.py` validates the dataset —
> coordinate ranges, required fields, no duplicate ids — with 34 tests. And
> `toCoordinate` in the frontend refuses nonsense: anything out of range, and
> specifically `0,0`, which is in the Gulf of Guinea and is almost always a
> missing value that survived as a default.
>
> The principle is that a marker at a nonsensical coordinate is worse than a
> missing marker, because it looks like data. Dropped records are counted, so
> the UI can say how many were omitted."

### "Everything shows 'Outdated'."

**Expect this, because it will happen if the data wasn't re-seeded.**
> "That's the freshness model working correctly. Our thresholds are six hours
> for fresh, twenty-four for aging, forty-eight before we call it outdated, and
> verification has its own seventy-two-hour window. The data was seeded more than
> two days ago, so the system is telling you it's stale rather than pretending
> it's current.
>
> I'd re-run the seeder before a demonstration. And honestly, a system that
> quietly showed two-day-old blood stock as current would be the actual bug."

### "A request timeline shows 'created 24 Nov, expired 16 Nov'."

> "Good catch, and the explanation is more interesting than a bug. Re-seeding
> puts demo requests back into dispatchable states, so our dispatcher — which
> runs every minute — picks them up and writes **genuine** events with real
> current timestamps, while the seeded creation event gets the new run's
> timestamp. The timeline sorts by sort key, so the ordering looks wrong.
>
> We deliberately didn't fix it. Those dispatcher events are real application
> history, so deleting them would mean deleting genuine records. And sorting by
> occurrence time would be **worse** — you'd see a request created after it
> expired. It's documented as limitation 1.20. The real fix is a dataset change,
> seeding requests in terminal states, which would cost us the dispatch and
> expiry scenarios."

---

## E — Operational scenarios

### "Configuration drift — someone changed a setting in the Console."

> "The next deployment would either overwrite it or fail confusingly, which is
> exactly why we don't do that. Everything is in one CloudFormation template;
> the right change is to the template plus a redeploy.
>
> We have one divergence I'd call out, and it's subtler than drift: four of our
> six Lambda log groups have no retention policy. Our template sets thirty days,
> but only for the two log groups it **declares** — the others were auto-created
> by Lambda on first invocation, and an implicitly created log group defaults to
> never expiring. That's not drift in CloudFormation's sense, because those
> resources were never in the stack. It's an infrastructure-as-code **coverage
> gap**.
>
> I should also say we've never run drift detection — `StackDriftStatus` reads
> `NOT_CHECKED`."

### "CloudFront serves stale content after a deployment."

> "That's the step people forget. Uploading to S3 doesn't change what users see
> — CloudFront keeps serving its cached copy until the TTL expires or you
> invalidate.
>
> Our deploy script creates an invalidation automatically. And interestingly
> only `index.html` really needs it: Vite puts a content hash in every asset
> filename, so a new build produces new filenames and stale JavaScript can't be
> served. You can see our invalidation history on the distribution, which is
> effectively a deployment log."

### "A message lands in a dead-letter queue."

> "An alarm fires — both DLQs have an alarm at more than zero messages, because
> a DLQ should always be empty. Then you'd inspect the message, fix the cause,
> and use SQS's redrive feature to move it back to the source queue.
>
> Two honest caveats. The alarm publishes to an SNS topic with no subscriptions,
> so nobody would be told. And no message has ever actually reached either DLQ,
> so the recovery procedure is documented rather than practised — I'd expect to
> learn something the first time."

### "A network failure between the browser and the API."

> "`fetch` rejects, and our client converts it to an `ApiError` with status 0
> and code `NETWORK_ERROR`, worded for the user — 'Could not reach LifeLink,
> check your connection' — rather than echoing a fetch internal. It's marked
> retryable, so the UI offers a retry.
>
> One detail: an `AbortError` from a cancelled request is re-thrown unchanged
> rather than converted, so a superseded search never shows the user a
> connection warning."

---

## F — The questions designed to catch you out

### "Show me where you use Step Functions."

> "We don't — there are none. You can check the template; there are zero state
> machines in the account. Our scheduling is EventBridge **Scheduler**, which is
> a different service from EventBridge Rules, and we have no rules either.
>
> Step Functions is for orchestrating a sequence where you need durable state
> *between* steps. Our emergency request state isn't orchestration state — it's
> domain state in DynamoDB, because the UI has to query it anyway. Modelling it
> as a state machine would put the same state in two places."

### "Show me your Cognito authorizer."

> "There isn't one — both routes are `AuthorizationType: NONE`, and I can show
> you the empty Authorization page. All token verification happens in the
> Lambda.
>
> That's deliberate: an authorizer checks the signature, but our authorization
> also needs the role from DynamoDB, the account status and an organization
> check. We'd still need the Lambda to do four of the five, so the logic would
> be split across two places. The cost is that an invalid request still costs a
> Lambda invocation, which is why the gateway throttles at ten per second."

### "Your item count doesn't match what you said."

> "The Console's count comes from `DescribeTable` and it's approximate —
> refreshes roughly every six hours. When I checked with an actual count scan,
> **five of twelve tables** disagreed. The accurate number comes from
> `Select=COUNT`, which I can run."

### "This is just a CRUD app with extra steps."

**Do not be defensive. Pick the parts that are not CRUD:**
> "A lot of it is CRUD, and I wouldn't claim otherwise. The parts that aren't:
> the geohash radius search, because DynamoDB has no geospatial index so we had
> to build one with cells plus a haversine filter. The reservation counter, which
> needs a conditional transaction so two hospitals can't be granted the same
> units — and which is where our worst bug was. And the dispatcher, which ranks
> providers across requests every minute, which is why it's an application-level
> poll rather than a queue: a queue orders by arrival and we need to order by
> suitability."

---

## Cross-references

- [02_Teacher_Question_And_Answer_Bank.md](02_Teacher_Question_And_Answer_Bank.md)
- [../11_INTERVIEW_PREPARATION/02_AWS_Interview_Questions.md](../11_INTERVIEW_PREPARATION/02_AWS_Interview_Questions.md)
- [../08_SECURITY_AND_RELIABILITY/05_Error_Handling_And_Retries.md](../08_SECURITY_AND_RELIABILITY/05_Error_Handling_And_Retries.md)
- `docs/EDGE_CASE_REGISTER.md`, `docs/TROUBLESHOOTING.md`
