# CloudWatch

Logs, metrics, alarms, tracing and a dashboard — plus the retention gap and
the notification gap, both found while writing this documentation.

---

## 1. What CloudWatch is

**Simple version.** AWS's built-in monitoring: it collects logs and metrics
from your services, lets you query them, and raises alarms.

**The analogy.** A flight recorder plus a cockpit warning panel. Logs are the
recorder; metrics and alarms are the panel.

**Mechanism.** Most AWS services publish metrics automatically. Lambda writes
anything your code prints to stdout into a **log group** named
`/aws/lambda/<function>`. Alarms watch a metric over a period and change state
when a threshold is crossed.

**Why it matters for a serverless project specifically:** there is no server to
SSH into. If something fails, CloudWatch is the **only** place the evidence
exists. That is worth stating — it is why observability is not optional here in
the way it might feel optional on a machine you can log into.

---

## 2. The five things CloudWatch does here

| Part | LifeLink |
|---|---|
| **Logs** | 6 log groups |
| **Metrics** | automatic from Lambda, API Gateway, DynamoDB, SQS |
| **Alarms** | 8, all currently `OK` |
| **Dashboard** | `LifeLink-dev` |
| **X-Ray tracing** | `Active` on all six functions |

---

## 3. Log groups — and the retention gap

| Log group | Retention | Stored |
|---|---|---|
| `/aws/apigateway/lifelink-dev` | **30 days** | 162 KB |
| `/aws/lambda/lifelink-dev-api` | **30 days** | 303 KB |
| `/aws/lambda/lifelink-dev-dispatcher` | **Never expire** | **8.2 MB** |
| `/aws/lambda/lifelink-dev-maintenance` | **Never expire** | 1.4 MB |
| `/aws/lambda/lifelink-dev-outbox-publisher` | **Never expire** | 1.8 KB |
| `/aws/lambda/lifelink-dev-work-worker` | **Never expire** | 957 B |
| `/aws/lambda/lifelink-dev-notification-worker` | **does not exist** | — |

### Two findings in that table

**1. The retention gap.** The template sets `LogRetentionDays: 30` and declares
**two** log groups explicitly. The other four were **auto-created by Lambda** on
first invocation — and a log group AWS creates implicitly defaults to **never
expiring**. The template's retention setting cannot apply to a resource the
template does not declare.

This is an **infrastructure-as-code coverage gap**, which is a sharper
description than "drift": those resources were never in the stack at all.

**The fix (not applied — engineering freeze):** declare an
`AWS::Logs::LogGroup` per function with
`RetentionInDays: !Ref LogRetentionDays`.

**2. The missing log group is evidence.**
`lifelink-dev-notification-worker` has **no log group**, which means it has
**never been invoked**. A log group is created on first invocation, so its
absence is proof of absence. That is a genuinely useful diagnostic technique.

### Say this
> "Here's a gap I found while documenting rather than while building. Our
> template sets thirty-day log retention, and it works — but only for the two
> log groups the template actually declares. The other four were created
> automatically by Lambda on first invocation, and an implicitly created log
> group defaults to never expiring. The dispatcher runs every minute and has
> about eight megabytes that will never be deleted.
>
> It isn't drift in CloudFormation's sense, because those resources were never
> in the stack — it's a coverage gap, which is a more common problem. The fix is
> to declare a log group per function in the template.
>
> There's a nice side-effect in that data, though: the notification worker has
> no log group at all, which proves it's never been invoked. A log group is
> created on first invocation, so its absence is evidence."

---

## 4. The eight alarms

| Alarm | Metric | Condition | Treat missing |
|---|---|---|---|
| `lifelink-dev-api-errors` | `AWS/Lambda Errors` | **> 5** in 1 x 5 min (Sum) | notBreaching |
| `lifelink-dev-api-latency-p95` | `AWS/Lambda Duration` | **> 3000 ms** for 2 x 5 min (**p95**) | notBreaching |
| `lifelink-dev-lambda-throttles` | `AWS/Lambda Throttles` | **>= 1** in 1 x 5 min | notBreaching |
| `lifelink-dev-dispatcher-failure` | `AWS/Lambda Errors` | **>= 1** in 1 x 5 min | notBreaching |
| `lifelink-dev-inventory-throttles` | `AWS/DynamoDB ThrottledRequests` | **> 5** in 1 x 5 min | notBreaching |
| `lifelink-dev-work-queue-age` | `AWS/SQS ApproximateAgeOfOldestMessage` | **> 300 s** for 2 x 5 min (Max) | notBreaching |
| `lifelink-dev-work-dlq-not-empty` | `AWS/SQS ApproximateNumberOfMessagesVisible` | **> 0** (Max) | notBreaching |
| `lifelink-dev-notification-dlq-not-empty` | same, notifications DLQ | **> 0** (Max) | notBreaching |

**All eight are currently `OK`.** All eight have exactly one action: publish to
`lifelink-dev-alarms`.

### The thresholds, and why they differ

**This is where a teacher can probe whether the numbers were reasoned about:**

| Choice | Reasoning |
|---|---|
| API errors **> 5**, dispatcher **>= 1** | The API serves anonymous traffic, so a handful of errors is normal background noise — a bad request, an expired token. The dispatcher runs unattended on a schedule; **any** error there is unexpected |
| Latency uses **p95**, not Average | An average hides the tail. If 1 in 20 users waits five seconds, the average still looks fine. p95 is what users actually experience at the bad end |
| Latency needs **2 periods**, errors need 1 | One slow five-minute window is noise; two in a row is a trend. An error spike is worth knowing about immediately |
| DLQ alarms at **> 0** | A dead-letter queue should always be empty. One message in it is a real event |
| `TreatMissingData: notBreaching` | **Important.** No data means nobody used the system, not that it broke. Without this, a quiet night would raise alarms |

**Say this:**
> "The thresholds aren't uniform, deliberately. The API alarm triggers above
> five errors in five minutes, because the API serves anonymous traffic and a
> few errors are normal — a malformed request, an expired token. The dispatcher
> alarm triggers on a single error, because it runs unattended and any failure
> there is unexpected.
>
> Latency uses the 95th percentile rather than the average, because an average
> hides the tail — if one user in twenty waits five seconds, the average still
> looks healthy. And all eight treat missing data as not breaching, which
> matters: no data means nobody used the system, not that it's broken. Without
> that, a quiet night would page you."

### The alarm gap

**All eight publish to an SNS topic with zero subscriptions.** The alarms
evaluate correctly and keep a visible state history, but **nothing reaches a
human.** See
[09_SNS_SQS_And_Notifications.md](09_SNS_SQS_And_Notifications.md) §5.

---

## 5. X-Ray tracing

`TracingConfig: {Mode: Active}` on all six functions, with
`AWSXrayWriteOnlyAccess` attached to each execution role.

**What X-Ray gives you.** A trace of one request across services, with timing
per segment: how long API Gateway took, how long the function ran, how long
each DynamoDB call took. A **service map** shows the call graph with latency
and error rates on each edge.

**Why it matters here.** A slow request could be the function, a DynamoDB
query, or an Amazon Location call. Logs tell you *that* it was slow; X-Ray
tells you *which part*.

**`Active` versus `PassThrough`:** `Active` means the function samples traces
itself even when the caller did not request one. `PassThrough` only traces when
an upstream service already decided to.

**Console:** `CloudWatch -> X-Ray traces -> Service map`, or
`Lambda -> function -> Monitor -> Traces`.

---

## 6. The dashboard

`LifeLink-dev` — one page combining the key metrics so an operator does not
have to assemble them.

**Console:** `CloudWatch -> Dashboards -> LifeLink-dev`.

**Why a dashboard when the metrics exist anyway?** Because during an incident
you want one page, not twelve. It is also the best single screen to open at the
start of a demonstration — it shows the system is real and instrumented in one
glance.

---

## 7. Logs Insights — the queries to practise

**This is the skill most worth having for a demonstration.**

```
CloudWatch -> Logs Insights -> select a log group -> run a query
```

### Trace one browser request to its log line

The single most impressive thirty seconds available:

```
fields @timestamp, @message
| filter @message like /corr-c77986b2/
| sort @timestamp asc
```

Copy the `correlationId` from the response in the browser's Network tab, paste
it here, and you have joined a click to a server log entry.

### Find errors

```
fields @timestamp, @message
| filter @message like /ERROR/
| sort @timestamp desc
| limit 20
```

### API Gateway access log — because it is JSON

```
fields @timestamp, status, latency, routeKey, ip
| filter status >= 400
| sort @timestamp desc
| limit 20
```

**This query is the payoff for choosing a JSON log format.** With the default
text format you would be writing regular expressions instead of naming fields.

### Slowest requests

```
fields @timestamp, routeKey, latency
| sort latency desc
| limit 10
```

### Count by route

```
stats count(*) by routeKey
```

---

## 8. What the logs actually contain

`backend/src/appcore/logging.py` configures structured logging, and
`POWERTOOLS_SERVICE_NAME=lifelink` with `LOG_LEVEL=INFO` are set on every
function.

Every log line for a request carries its **correlation id**, which is the same
id returned to the browser in the response envelope. That is the join key
between what a user saw and what the server did.

**Log format is `Text`, not `JSON`,** on the Lambda functions — so Logs
Insights cannot auto-parse Lambda fields the way it can for the API Gateway
access log. Switching `LoggingConfig.LogFormat` to `JSON` would make the Lambda
logs queryable by field too. Worth mentioning as an improvement rather than
presenting the current state as optimal.

---

## 9. Console demonstration

| Step | Path | What to show |
|---|---|---|
| 1 | `CloudWatch -> Dashboards -> LifeLink-dev` | the whole system on one page |
| 2 | `CloudWatch -> Alarms` | 8 alarms, all `OK`; open one and show its **History** tab |
| 3 | the alarm's **Actions** | it publishes to the SNS topic |
| 4 | `SNS -> lifelink-dev-alarms -> Subscriptions` | **empty** — volunteer the gap |
| 5 | `CloudWatch -> Log groups` | filter `lifelink`; show the **Retention** column and the never-expire gap |
| 6 | `/aws/lambda/lifelink-dev-dispatcher` | log streams roughly every minute — proof the schedule fires |
| 7 | `Logs Insights` | run the correlation-id query against a request you just made |
| 8 | `CloudWatch -> X-Ray traces -> Service map` | the call graph with latencies |

**Step 7 is the one to rehearse.** Make a request on the live site, copy the
correlation id from the Network tab, find it in Logs Insights. It demonstrates
end-to-end understanding in half a minute.

**Do not** delete log groups or streams, change retention, or disable an alarm.

---

## 10. Spoken answers

### 20–30 seconds
> "CloudWatch is where everything observable lives. Six log groups, one per
> function plus the API Gateway access log. Eight alarms covering Lambda errors,
> p95 latency, throttles, DynamoDB throttles, queue age and both dead-letter
> queues. X-Ray tracing is active on all six functions, and there's a dashboard
> that puts the key metrics on one page. Because it's serverless, there's no
> server to log into — CloudWatch is the only place the evidence exists."

### 1–2 minutes
> "The part I'd demonstrate is correlation ids. Every API response includes one,
> and the same id appears in the Lambda's CloudWatch logs. So if a user reports
> something failing, I take the id from the response in their browser's Network
> tab, paste it into Logs Insights, and I have the server side of that exact
> request in about thirty seconds. That's the thing I'd actually use.
>
> On alarms, the thresholds aren't uniform. The API alarm triggers above five
> errors in five minutes because a few errors are normal background noise; the
> dispatcher alarm triggers on one, because it runs unattended and any error
> there is unexpected. Latency uses p95 rather than the average, because an
> average hides the tail.
>
> Two honest gaps. Four of our six Lambda log groups never expire, because the
> template only sets retention on the two it declares and the rest were
> auto-created by Lambda. And all eight alarms publish to an SNS topic with no
> subscriptions, so the detection works but nothing reaches a person. I'd fix
> the subscription first — it's a one-minute change that makes eight alarms
> useful."

---

## 11. Follow-up questions

**"How would you debug a 500 error a user reported?"**
> Start from the correlation id in the response they saw. Logs Insights on
> `/aws/lambda/lifelink-dev-api`, filter for that id, and I get the full
> server-side trace including the stack. If that didn't explain it, the API
> Gateway access log for the same request shows whether the gateway reached the
> function at all — the `integrationError` field tells you if it couldn't. Then
> X-Ray if the question is where the time went rather than what failed.

**"What would you add?"**
> Three things, in order. First, an SNS subscription so the alarms notify
> someone. Second, log retention on the four log groups that don't have it.
> Third, switching the Lambda log format from Text to JSON, so Logs Insights can
> parse those logs by field the way it already does for the API Gateway access
> log. After that, custom business metrics — reservations created, dispatches
> sent — which would need EMF or `put_metric_data` and which we don't have at
> all.

**"Do you have any custom metrics?"**
> No. Everything is the metrics AWS publishes automatically. Business-level
> metrics would be genuinely useful — how many reservations are held right now,
> how long until providers respond — and that would mean emitting Embedded
> Metric Format lines from the handlers. It's an honest gap rather than a
> decision.

**"How much do the logs cost?"**
> Ingestion is the charge that matters, and we're inside the 5 GB free tier at
> about 12 MB total. The risk is the four log groups with no retention: the
> dispatcher runs every minute, so that one grows indefinitely. Trivial today,
> unbounded over years.

---

## 12. Cross-references

- [05_AWS_Lambda.md](05_AWS_Lambda.md)
- [09_SNS_SQS_And_Notifications.md](09_SNS_SQS_And_Notifications.md)
- [13_AWS_Cost_And_Scalability.md](13_AWS_Cost_And_Scalability.md)
- [../09_PRACTICAL_AWS_DEMONSTRATIONS/08_Showing_CloudWatch_Logs.md](../09_PRACTICAL_AWS_DEMONSTRATIONS/08_Showing_CloudWatch_Logs.md)
- [../08_SECURITY_AND_RELIABILITY/05_Error_Handling_And_Retries.md](../08_SECURITY_AND_RELIABILITY/05_Error_Handling_And_Retries.md)
