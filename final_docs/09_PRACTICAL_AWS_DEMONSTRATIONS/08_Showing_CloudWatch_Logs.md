# Showing CloudWatch Logs

The observability demonstration, built around the one query worth rehearsing.

---

## 1. Why this matters more for serverless

**Open with this:**
> "There's no server to SSH into. If something fails, CloudWatch is the **only**
> place the evidence exists. So observability isn't an optional extra here in
> the way it can feel on a machine you can log into."

---

## 2. Start with the dashboard

```
CloudWatch -> Dashboards -> LifeLink-dev
```

**The best single screen to open a demonstration with** — it shows the system
is real and instrumented in one glance, rather than describing it.

> "One page with the key metrics. During an incident you want one page, not
> twelve."

---

## 3. The query to rehearse

**Thirty seconds, and it is the most impressive thing in this section.**

```
1. On the live site: DevTools -> Network -> make a request
   -> Response -> copy the correlationId

2. CloudWatch -> Logs Insights
   -> Select log group: /aws/lambda/lifelink-dev-api
   -> Query:

      fields @timestamp, @message
      | filter @message like /corr-c77986b2/
      | sort @timestamp asc

3. Run query
```

**Say this:**
> "Same request, both ends. Every API response carries a correlation id, and the
> same id appears in the Lambda's logs. So a failure a user saw in their browser
> becomes an exact server-side log entry in about thirty seconds. That's the
> thing I'd actually use, and it's the reason the response envelope exists."

**Rehearse this.** Fumbling the Logs Insights UI live undoes the effect.

---

## 4. The other queries worth having ready

### Errors in the last hour

```
fields @timestamp, @message
| filter @message like /ERROR/
| sort @timestamp desc
| limit 20
```

### The API Gateway access log — the payoff for JSON

```
Log group: /aws/apigateway/lifelink-dev

fields @timestamp, status, latency, routeKey, ip
| filter status >= 400
| sort @timestamp desc
| limit 20
```

**Say this:**
> "This is why we log in JSON rather than the default text format — Logs
> Insights parses the fields by name. With text I'd be writing regular
> expressions. The field that earns its place is `integrationError`: if the
> gateway can't invoke the Lambda at all, because of a permission problem or a
> throttle, that's where the reason appears and nowhere else."

### Slowest requests

```
fields @timestamp, routeKey, latency
| sort latency desc
| limit 10
```

### Traffic by route

```
stats count(*) by routeKey
```

---

## 5. The log groups — two findings on one screen

```
CloudWatch -> Log groups -> filter "lifelink"
```

| Log group | Retention | Stored |
|---|---|---|
| `/aws/apigateway/lifelink-dev` | **30 days** | 162 KB |
| `/aws/lambda/lifelink-dev-api` | **30 days** | 303 KB |
| `/aws/lambda/lifelink-dev-dispatcher` | **Never expire** | **8.2 MB** |
| `/aws/lambda/lifelink-dev-maintenance` | **Never expire** | 1.4 MB |
| `/aws/lambda/lifelink-dev-outbox-publisher` | **Never expire** | 1.8 KB |
| `/aws/lambda/lifelink-dev-work-worker` | **Never expire** | 957 B |
| `lifelink-dev-notification-worker` | **DOES NOT EXIST** | — |

### Finding 1 — the retention gap. Volunteer it.

> "Here's a gap I found while documenting rather than while building. Our
> template sets thirty-day retention, and it works — but only for the two log
> groups the template actually declares. The other four were created
> automatically by Lambda on first invocation, and an implicitly created log
> group defaults to never expiring. The dispatcher runs every minute and has
> about eight megabytes that will never be deleted.
>
> It isn't drift in CloudFormation's sense, because those resources were never
> in the stack — it's an infrastructure-as-code coverage gap, which is a
> different and more common problem. The fix is to declare a log group per
> function in the template with the retention parameter."

### Finding 2 — proof by absence

> "And notice there are only five Lambda log groups for six functions. The
> notification worker has none — and a log group is created on **first
> invocation**, so its absence proves that function has **never run**.
>
> That's why I won't claim our notification pipeline works end to end.
> In-app notifications do work — there are eighteen rows in the table, written
> directly by the services. But email isn't configured, the sender address is
> empty, and the worker has never been invoked. Proof by absence is quite a
> satisfying diagnostic."

---

## 6. Proving the scheduled jobs run

```
CloudWatch -> Log groups -> /aws/lambda/lifelink-dev-dispatcher -> Log streams
```

**Streams appear roughly every minute.**

> "Configuration tells you what's *supposed* to happen. These timestamps prove
> it actually does — a log stream roughly every minute, which is the dispatcher
> firing on its EventBridge schedule. It's also why this is the biggest log
> group."

---

## 7. The alarms, and the honest gap

```
CloudWatch -> Alarms -> filter "lifelink"     (8 alarms, all OK)
```

| Alarm | Threshold |
|---|---|
| `lifelink-dev-api-errors` | > 5 in 5 min |
| `lifelink-dev-api-latency-p95` | > 3000 ms for 2 periods (**p95**) |
| `lifelink-dev-lambda-throttles` | >= 1 |
| `lifelink-dev-dispatcher-failure` | >= 1 |
| `lifelink-dev-inventory-throttles` | > 5 in 5 min |
| `lifelink-dev-work-queue-age` | > 300 s for 2 periods |
| `lifelink-dev-work-dlq-not-empty` | > 0 |
| `lifelink-dev-notification-dlq-not-empty` | > 0 |

**Open one and show its History tab** — alarm state changes over time, which
proves the alarm is live rather than decorative.

### Explain why the thresholds differ

> "They're not uniform, deliberately. The API alarm triggers above five errors
> in five minutes, because the API serves anonymous traffic and a few errors are
> normal background noise — a malformed request, an expired token. The
> dispatcher alarm triggers on a **single** error, because it runs unattended
> and any failure there is unexpected.
>
> Latency uses the 95th percentile rather than the average, because an average
> hides the tail — if one user in twenty waits five seconds, the average still
> looks healthy.
>
> And all eight treat missing data as **not breaching**, which matters: no data
> means nobody used the system, not that it broke. Without that, a quiet night
> would page you."

### Then the gap — volunteer it

```
the alarm -> Actions   ->   publishes to arn:...:lifelink-dev-alarms
SNS -> Topics -> lifelink-dev-alarms -> Subscriptions   ->   EMPTY
```

> "And here's the honest weakness. All eight alarms publish to this SNS topic,
> and it has **zero subscriptions**. So a problem would be detected and nobody
> would be told.
>
> It happened because a subscription needs an endpoint — an email address — and
> that's personal data I didn't want committed to the template, so it became a
> manual step that never got done. It's a one-minute fix, and it's a good
> reminder that an alarm nobody is subscribed to is monitoring theatre."

**Showing your own gap, with the reason and the fix, is stronger than being
shown it.**

---

## 8. X-Ray

```
CloudWatch -> X-Ray traces -> Service map
```
or `Lambda -> lifelink-dev-api -> Monitor -> Traces`.

**Tracing is `Active` on all six functions.**

> "Logs tell you *that* something was slow; X-Ray tells you *which part* — how
> long the function ran versus how long each DynamoDB call took. The service map
> shows the call graph with latency and error rates on each edge. A slow request
> here could be the function, a DynamoDB query, or an Amazon Location call, and
> this is how you tell them apart."

---

## 9. What is in a log line

`LOG_LEVEL=INFO`, `POWERTOOLS_SERVICE_NAME=lifelink`, configured in
`backend/src/appcore/logging.py`.

**Every log line for a request carries its correlation id** — the join key
between what a user saw and what the server did.

**One honest improvement to mention:**
> "The Lambda log format is `Text` rather than `JSON`, so Logs Insights can't
> auto-parse those fields the way it can for the API Gateway access log.
> Switching `LoggingConfig.LogFormat` to JSON would make the Lambda logs
> queryable by field too. That's an improvement I'd make rather than a current
> strength."

---

## 10. Do not

| Action | Why |
|---|---|
| Delete a log group or stream | destroys evidence |
| **Change retention** | template-controlled — and the gap is a documented finding |
| Disable an alarm | |
| Set an alarm to ALARM state manually | |
| Add an SNS subscription on a projector | would mean typing a real email address in public |

---

## 11. Questions and answers

**"How would you debug a 500 error a user reported?"**
> Start from the correlation id in the response they saw. Logs Insights on
> `/aws/lambda/lifelink-dev-api`, filter for that id, and I get the full
> server-side trace including the stack. If that didn't explain it, the API
> Gateway access log for the same request shows whether the gateway reached the
> function at all — `integrationError` tells you if it couldn't. Then X-Ray if
> the question is where the time went rather than what failed.

**"Do you have custom business metrics?"**
> No, and that's an honest gap rather than a decision. Everything is the metrics
> AWS publishes automatically. Business-level metrics would be genuinely useful
> — how many units are held right now, how long providers take to respond — and
> that would mean emitting Embedded Metric Format lines from the handlers.

**"How much do the logs cost?"**
> Ingestion is the charge that matters, and we're inside the 5 GB free tier at
> about 12 MB total. The risk is the four log groups with no retention: the
> dispatcher runs every minute, so that one grows indefinitely. Trivial today,
> unbounded over years — which is the real reason the gap matters rather than
> tidiness.

**"What would you add first?"**
> An SNS subscription, because it's a one-minute change that makes eight
> existing alarms useful. Then retention on the four log groups. Then JSON log
> format for the Lambdas. Then custom business metrics.

---

## 12. Cross-references

- [CONFIGURATION_WALKTHROUGHS.md](CONFIGURATION_WALKTHROUGHS.md) §C4, §G2
- [../04_AWS_COMPLETE_GUIDE/11_CloudWatch.md](../04_AWS_COMPLETE_GUIDE/11_CloudWatch.md)
- [../08_SECURITY_AND_RELIABILITY/05_Error_Handling_And_Retries.md](../08_SECURITY_AND_RELIABILITY/05_Error_Handling_And_Retries.md)
- [07_Showing_API_Gateway_And_Requests.md](07_Showing_API_Gateway_And_Requests.md)
