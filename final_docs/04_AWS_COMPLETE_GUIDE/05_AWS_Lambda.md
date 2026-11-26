# AWS Lambda

Six functions, one shared deployment package, and the concurrency ceiling of
**10** that shaped the whole architecture.

---

## 1. What Lambda is

**Simple version.** You upload code; AWS runs it when something triggers it,
and you pay only for the milliseconds it runs.

**The analogy.** A traditional server is a taxi you have hired for the day — it
costs you whether or not you are travelling. Lambda is a rideshare: it exists
for the trip and then it is gone.

**Mechanism.** AWS keeps your code packaged. On a trigger it creates (or
reuses) a micro-VM, loads the runtime and your code, and calls your handler.
After the invocation the environment is kept warm for a while in case another
request arrives, then destroyed.

That "kept warm" detail explains two things people find confusing:

- **Cold start:** the first invocation pays for creating the environment and
  importing your modules.
- **Global state persists between invocations in the same environment** — which
  is why our JWKS keys stay cached and are not refetched per request.

---

## 2. Lambda versus EC2 — the comparison teachers ask for

| | Lambda | EC2 |
|---|---|---|
| You manage | your code | OS, patches, runtime, scaling, monitoring |
| Billing | per request + GB-millisecond | per instance-hour, **idle or not** |
| Scaling | automatic | Auto Scaling groups you configure |
| Max run time | 15 minutes | unlimited |
| Cost when idle | **$0** | the full instance bill |
| Cold starts | **yes** | no |
| Long-lived connections | awkward | natural |
| Our cost | cents/month | several dollars/month minimum |

### When EC2 would be the better choice

**Give the balanced answer:**

> "Lambda suits us because our traffic is request-response and bursty, and
> nothing runs for more than a few seconds. If we needed a persistent WebSocket
> connection for live updates, or a job that takes an hour, or a process holding
> a large in-memory model, EC2 or a container would be the right answer —
> Lambda caps at fifteen minutes and charges for every millisecond of a
> long-running job.
>
> The honest downside we live with is cold starts, and a hard concurrency limit.
> Ours is ten. A server doesn't have that problem."

---

## 3. The six functions

| Function | Handler | Trigger |
|---|---|---|
| `lifelink-dev-api` | `handlers.api.lambda_handler` | HTTP API, all 58 routes |
| `lifelink-dev-dispatcher` | `handlers.workers.dispatcher_handler` | EventBridge Scheduler, **every minute** |
| `lifelink-dev-maintenance` | `handlers.workers.maintenance_handler` | EventBridge Scheduler, **every 10 minutes** |
| `lifelink-dev-outbox-publisher` | `handlers.workers.outbox_handler` | DynamoDB Stream on `outbox` |
| `lifelink-dev-work-worker` | `handlers.workers.work_handler` | SQS `lifelink-dev-work` |
| `lifelink-dev-notification-worker` | `handlers.workers.notification_handler` | SQS `lifelink-dev-notifications` |

**All six share one deployment package**, `CodeSha256`
`Em9NdRR2EmRe/VAOdAq+iKsydKmXuiDqnZNKVkVT94g=`, last modified
2026-11-24T08:33Z. They differ only in handler and IAM role.

**Why one package?** Because the domain logic, repositories and services are
shared. Six separate packages would mean six copies of the same code to keep in
step. The cost is a slightly larger package for each function — 8.6 MB, which
is well within limits.

**Evidence worth knowing:** `lifelink-dev-notification-worker` has **no
CloudWatch log group**, which means it has **never been invoked**. Notifications
are written straight to the `notifications` table; email is unconfigured
(`SES_SENDER` is empty) and SMS is not implemented. Do not claim the
notification pipeline has run end to end.

---

## 4. Configuration — identical across all six

| Setting | Value | Why |
|---|---|---|
| Runtime | **`python3.14`** | matches the local interpreter (ADR-0013); GA on AL2023, deprecation 2029-06-30 |
| Architecture | **`arm64`** | Graviton — cheaper for identical capability |
| Memory | **512 MB** | Lambda scales CPU with memory, so this is a speed dial |
| Timeout | **29 s** | just under API Gateway's 30 s, so the function fails first |
| Tracing | **Active** | X-Ray |
| Layers | none | the package is self-contained |
| SnapStart | Off | not available for Python |
| Reserved concurrency | **not set** | see §5 |
| Dead-letter config | none | failures are handled per event source instead |

### Why 512 MB

Memory on Lambda is really a **CPU dial** — AWS allocates proportional CPU. More
memory makes a CPU-bound function *faster*, which can make it *cheaper*,
because you pay for GB-milliseconds and the milliseconds drop. 512 MB is where
this workload stopped getting faster: below it, JSON parsing and RS256 crypto
slow down noticeably; above it, you pay for capacity that idles.

### Why 29 seconds

API Gateway's integration timeout is **30 seconds**, which is a hard limit on
HTTP APIs. If the function could run to 30 s or beyond, the gateway would give
up first and return a bare **504** with no correlation id and no application
error code. At 29 s the function fails first, so the client gets *our* error
envelope with a traceable id.

**That one-second margin is a deliberate design detail and a good answer to
"why not 30?".**

### Why arm64 forces a custom build

`cryptography` — needed for RS256 token verification — ships as a compiled
binary wheel. Running `sam build` on Windows installs the **Windows** wheel,
which cannot load on an arm64 Linux function. The function deploys fine and
then fails at import time.

So `scripts/build_lambda_package.py --verify` fetches
`manylinux2014_aarch64` wheels explicitly: 505 files, 23.4 MB, all six handler
entry points verified before upload.

**`docs/DEPLOYMENT.md` says plainly: do not use `sam build` on this host.**

---

## 5. The concurrency ceiling of 10 — the defining constraint

```
ConcurrentExecutions: 10
UnreservedConcurrentExecutions: 10
```

**The AWS default is 1000. This account's limit is 10.** Verified live.

ADR-0014 treats it as a hard design constraint rather than something to request
an increase for. Every one of these is visible in the deployed configuration:

| Mechanism | Value | Purpose |
|---|---|---|
| API stage throttle | **10 req/s, burst 20** | shed load at the gateway, not by exhausting Lambda |
| SQS event source `MaximumConcurrency` | **2** on both queues | consumers cannot starve the API |
| Function timeout | 29 s | fails fast rather than holding a slot |
| One API function, not 58 | — | 58 functions competing for 10 slots would be worse |
| Deferred work to queues | — | keeps request-path concurrency short-lived |

### What happens when the limit is reached

1. Lambda returns a **throttle** error.
2. For a synchronous API invocation the caller sees a **429**.
3. For an SQS event source, the message is **not lost** — it returns to the
   queue and is retried, and after 5 receives it moves to the DLQ.
4. Alarm `lifelink-dev-lambda-throttles` fires at >= 1 throttle in 5 minutes.

**The asynchronous path degrades gracefully; the synchronous path sheds load.**
That difference is the point of putting deferrable work on a queue.

### Why no reserved concurrency

Reserving concurrency for one function **removes it from the shared pool for
everyone else**. With 10 total, reserving 3 for the dispatcher would leave 7 for
everything including the API. Instead, concurrency is capped where the risk
actually is — at the **event source mappings**, which is the only place a
backlog can drive unbounded scaling.

### Say this
> "The constraint that shaped this architecture is that our account's Lambda
> concurrency limit is ten, not the usual thousand. Rather than treat that as a
> problem to escalate, we designed for it.
>
> The API Gateway stage throttles at exactly ten requests a second — that number
> is derived from the limit, not picked. Both SQS consumers are capped at two
> concurrent executions, so a queue backlog can't scale workers up and starve
> the API. The function timeout is twenty-nine seconds so a slow request
> releases its slot rather than holding it. And we run one API function instead
> of fifty-eight, because fifty-eight functions competing for ten slots would be
> strictly worse.
>
> We deliberately didn't set reserved concurrency on anything, because reserving
> for one function takes it out of the shared pool for the others. We capped at
> the event sources instead, which is where a backlog could actually cause
> runaway scaling."

---

## 6. Cold starts

**What they are.** The first invocation in a new environment pays for creating
the micro-VM, loading the Python runtime, and importing your modules.

**What makes ours what they are:**

| Factor | Effect |
|---|---|
| Python | relatively fast to start |
| arm64 | comparable to x86 |
| 8.6 MB package | modest |
| `cryptography` import | the heaviest import |
| 512 MB | more memory initialises faster |
| One function for all routes | **helps** — it stays warm across every route |

**Mitigations we did not use, and why:**

- **Provisioned concurrency** keeps environments permanently warm, but it is
  billed continuously — which defeats the point of a near-zero-cost demo, and
  it would consume part of a pool of ten.
- **SnapStart** is not available for Python.

**Honest framing:** a cold start on this project is a one-off delay of a few
hundred milliseconds on the first request after a quiet period. For a
demonstration it is invisible. For a latency-critical production API it would
be worth provisioned concurrency.

---

## 7. Event source mappings

| Consumer | Source | Batch | Window | Max concurrency | Failure handling |
|---|---|---|---|---|---|
| `outbox-publisher` | `outbox` stream, `LATEST` | 10 | 5 s | parallelization 1 | 3 retries, **bisect on error**, on-failure -> `work-dlq`, `ReportBatchItemFailures` |
| `work-worker` | SQS `work` | 5 | 10 s | **2** | redrive after 5 receives |
| `notification-worker` | SQS `notifications` | 5 | 10 s | **2** | redrive after 5 receives |

### Three settings worth explaining

**`BisectBatchOnFunctionError: true`** on the stream. If a batch of 10 fails,
Lambda splits it in half and retries each half, recursively — isolating the one
poison record instead of blocking the shard. Without it, a single bad record
stalls the stream until it expires.

**`ReportBatchItemFailures`.** The function returns *which* records failed, so
the successful ones in a batch are not reprocessed. Without it, one failure in
five means all five are retried — and since consumers are idempotent that is
survivable, but wasteful.

**`StartingPosition: LATEST`** on the stream: start from new records, not from
the beginning of the stream's 24-hour history. Correct for an outbox, where
replaying old events would re-publish work already done.

---

## 8. Observability

| Mechanism | Deployed state |
|---|---|
| CloudWatch Logs | one log group per function |
| **Log retention** | **30 days on `/aws/lambda/lifelink-dev-api` only; the other four never expire** |
| X-Ray tracing | **Active** on all six |
| Alarms | `lifelink-dev-api-errors` (>5 in 5 min), `-api-latency-p95` (>3000 ms for 2 periods), `-dispatcher-failure` (>=1), `-lambda-throttles` (>=1) |
| Log format | Text (not JSON) |

**The retention gap is real and worth owning.** The template sets
`LogRetentionDays: 30` and declares **two** log groups. The other four were
auto-created by Lambda on first invocation, and an implicitly created log group
defaults to never expiring. The dispatcher runs every minute and has
accumulated about 8 MB that will never be deleted. See
[../09_PRACTICAL_AWS_DEMONSTRATIONS/CONFIGURATION_WALKTHROUGHS.md](../09_PRACTICAL_AWS_DEMONSTRATIONS/CONFIGURATION_WALKTHROUGHS.md) §C4.

---

## 9. Console demonstration

```
Lambda -> Functions -> filter "lifelink"     (6 functions)
```

| Step | What to show |
|---|---|
| 1 | Six functions, all `python3.14`, all `arm64` |
| 2 | `lifelink-dev-api` -> **Configuration -> General** -> 512 MB, 29 s |
| 3 | **Configuration -> Environment variables** -> 12 non-secret identifiers |
| 4 | **Configuration -> Permissions** -> the execution role, then follow it to IAM |
| 5 | **Configuration -> Triggers** -> the HTTP API |
| 6 | `lifelink-dev-work-worker` -> Triggers -> the SQS mapping with **max concurrency 2** |
| 7 | **Monitor -> Logs** -> recent invocations |
| 8 | **Monitor -> Traces** (X-Ray) -> the service map |

**The best single moment:** open the **Monitor** tab on `lifelink-dev-api`,
then make a request to the live site in another window, and watch the
invocation count rise. That connects the website to the function visibly.

**Do not** use the **Test** button with a fabricated event during a
demonstration — a malformed event produces an error that looks like a broken
function. And do not edit configuration; it is template-controlled.

---

## 10. Spoken answers

### "Why Lambda?" — 30 seconds
> "Because there's no server to patch or keep running, and we pay per request —
> a demonstration workload costs cents. The architecture is request-response
> with short work, which is exactly what Lambda suits. The honest trade-offs are
> cold starts and a hard concurrency ceiling; ours is ten, which is why the API
> Gateway throttles at ten requests a second."

### 1–2 minutes
> "We have six functions sharing one deployment package — they differ only in
> their handler and their IAM role. One serves the API, two run on schedules,
> one consumes a DynamoDB stream, and two consume SQS queues.
>
> All six are Python 3.14 on arm64 with 512 megabytes and a 29-second timeout.
> arm64 because Graviton costs less for identical work. 512 megabytes because
> Lambda allocates CPU in proportion to memory, so it's effectively a speed dial
> — that's where this workload stopped getting faster. And 29 seconds
> deliberately: API Gateway gives up at 30, so we want the function to fail
> first and return our own error with a correlation id rather than a bare
> gateway 504.
>
> One consequence of arm64 worth mentioning: we can't use `sam build` on a
> Windows machine, because it would install a Windows binary of the crypto
> library we need for token verification, and that can't load on an arm64 Linux
> function. We have a build script that fetches the right manylinux wheels
> explicitly."

---

## 11. Follow-up questions

**"What happens if a Lambda fails?"**
> It depends on the invocation type, and that distinction is the point. A
> synchronous API invocation returns an error to the caller — our router turns a
> domain error into the right HTTP status with a correlation id, and an
> unexpected exception becomes a 500. An SQS-triggered invocation doesn't lose
> the message: it returns to the queue, is retried, and after five failed
> receives moves to the dead-letter queue. The stream consumer retries three
> times, bisects the batch to isolate a bad record, and sends what it can't
> process to a DLQ. There are alarms on errors and throttles — though honestly,
> those alarms publish to an SNS topic with no subscriptions, so nothing
> actually notifies anyone yet.

**"Why one function for 58 routes instead of one per route?"**
> Three reasons. With a concurrency limit of ten, fifty-eight functions would
> make contention worse. One function stays warm across all routes, whereas
> fifty-eight each go cold. And it's one package, one role to review, one log
> group to search.
>
> The real cost is that the IAM role is the union of every route's needs, so a
> route that only reads facilities runs with permission to write inventory.
> That's a genuine downside. If the concurrency limit were a thousand and the
> team were bigger, splitting by feature area would be the better call.

**"How do you handle secrets?"**
> Not in environment variables — those are readable by anyone who can describe
> the function. Our one secret is in Secrets Manager,
> `lifelink/dev/provider-api-keys`, fetched at runtime. Every environment
> variable we do set is a non-secret identifier: table prefix, pool id, queue
> URL.

**"Could you reduce the cold start?"**
> Provisioned concurrency would eliminate it, but it bills continuously and
> would consume part of a pool of ten — the wrong trade for a project costing
> nothing net, with gross usage under fifty cents. SnapStart isn't available
> for Python. The practical
> option is trimming imports, and the heaviest is the crypto library we need for
> RS256, which isn't optional.

---

## 12. Cross-references

- [04_API_Gateway.md](04_API_Gateway.md)
- [09_SNS_SQS_And_Notifications.md](09_SNS_SQS_And_Notifications.md)
- [10_EventBridge_And_Step_Functions.md](10_EventBridge_And_Step_Functions.md)
- [11_CloudWatch.md](11_CloudWatch.md)
- [../09_PRACTICAL_AWS_DEMONSTRATIONS/03_Showing_Lambda_And_Execution.md](../09_PRACTICAL_AWS_DEMONSTRATIONS/03_Showing_Lambda_And_Execution.md)
- [../09_PRACTICAL_AWS_DEMONSTRATIONS/CONFIGURATION_WALKTHROUGHS.md](../09_PRACTICAL_AWS_DEMONSTRATIONS/CONFIGURATION_WALKTHROUGHS.md) §F
