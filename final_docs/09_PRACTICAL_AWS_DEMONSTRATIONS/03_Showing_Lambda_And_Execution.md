# Showing Lambda and Execution

How to demonstrate that the backend is really running, and explain the one
number that shaped the architecture.

---

## 1. The demonstration that lands

**Open two windows side by side:**

| Left | Right |
|---|---|
| Lambda -> `lifelink-dev-api` -> **Monitor** | the live site, `d324z37do52g8f.cloudfront.net` |

Then **use the site** — run a blood search.

Within a minute or two the **Invocations** metric rises.

**Say this:**
> "That's the actual connection between the website and AWS. I just ran a search
> on the site, and here's the invocation appearing on the Lambda function. There
> is no server — that function existed for a few hundred milliseconds to handle
> my request and then stopped."

**Metrics can lag a minute or two.** If so, go to **Monitor -> Logs** and open
the newest log stream — logs appear faster than metrics.

---

## 2. The walkthrough

```
Lambda -> Functions -> filter "lifelink"        (6 functions)
```

| Function | Trigger |
|---|---|
| `lifelink-dev-api` | HTTP API — all 58 routes |
| `lifelink-dev-dispatcher` | Scheduler, **every minute** |
| `lifelink-dev-maintenance` | Scheduler, every 10 minutes |
| `lifelink-dev-outbox-publisher` | DynamoDB Stream |
| `lifelink-dev-work-worker` | SQS |
| `lifelink-dev-notification-worker` | SQS |

**Point out that all six share one code hash**
(`Em9NdRR2EmRe/VAOdAq+iKsydKmXuiDqnZNKVkVT94g=`):

> "All six are the same deployment package — they differ only in their handler
> and their IAM role. The domain logic and repositories are shared, so six
> separate packages would mean six copies to keep in step."

### `lifelink-dev-api` -> Configuration -> General configuration

| Setting | Value | Say |
|---|---|---|
| Runtime | `python3.14` | "matches our local interpreter, so no works-on-my-machine class of bug" |
| Architecture | **`arm64`** | "Graviton — cheaper for identical work" |
| Memory | **512 MB** | "Lambda scales CPU with memory, so it's really a speed dial. This is where our workload stopped getting faster" |
| Timeout | **29 s** | **see §4** |

### Configuration -> Environment variables

12 variables. **Make the point about secrets:**

> "Twelve environment variables and every one is a non-secret identifier — table
> prefix, pool id, client id, queue URLs. That's deliberate: environment
> variables are readable by anyone who can describe the function, so a secret
> here isn't a secret. Our one real secret is in Secrets Manager and fetched at
> runtime."

### Configuration -> Permissions

Shows the execution role. **Click through to IAM** — it is the natural bridge
to [06_Showing_IAM_In_Action.md](06_Showing_IAM_In_Action.md).

### Configuration -> Triggers

| Function | Trigger to show |
|---|---|
| `lifelink-dev-api` | the HTTP API |
| `lifelink-dev-work-worker` | SQS with **Maximum concurrency: 2** |

**That `2` is the setting to stop on** — see §3.

---

## 3. The concurrency limit of 10 — the best architecture story

```bash
aws lambda get-account-settings --profile lifelink
# ConcurrentExecutions: 10
# UnreservedConcurrentExecutions: 10
```

**The AWS default is 1000. Ours is 10.**

Everything below follows from that single number, and all of it is visible:

| Mechanism | Where to show it |
|---|---|
| API stage throttle **10 req/s, burst 20** | API Gateway -> Stages -> dev |
| SQS consumer **Maximum concurrency: 2** | Lambda -> work-worker -> Triggers |
| Timeout **29 s** | Lambda -> Configuration |
| One API function, not 58 | the function list |
| **Reserved concurrency: not set** | Configuration -> Concurrency |

**Say this:**
> "The constraint that shaped this whole architecture is that our account's
> Lambda concurrency limit is ten, not the usual thousand.
>
> So the API Gateway stage throttles at exactly ten requests a second — that
> number is derived from the limit, not picked. Both SQS consumers are capped at
> two concurrent executions, so a queue backlog can't scale workers up and
> starve the API. The timeout is twenty-nine seconds so a slow request releases
> its slot. And we run one API function instead of fifty-eight, because
> fifty-eight competing for ten slots would be strictly worse.
>
> We deliberately set no reserved concurrency, because reserving for one
> function removes it from the shared pool for the others. We capped at the
> event sources instead, which is where a backlog could actually cause runaway
> scaling."

---

## 4. Why the timeout is 29 and not 30

**A small detail that shows care:**

> "API Gateway's integration timeout is thirty seconds, and that's a hard
> ceiling on an HTTP API. If our function could run to thirty or beyond, the
> gateway would give up first and return a bare 504 with no correlation id and
> no application error code. At twenty-nine, the function fails first, so the
> client gets our own error envelope with a traceable id."

---

## 5. The missing log group — proof by absence

```
CloudWatch -> Log groups -> filter "lifelink"
```

**`/aws/lambda/lifelink-dev-notification-worker` does not exist.**

**Say this:**
> "Notice there are only five Lambda log groups for six functions. The
> notification worker has no log group — and a log group is created on first
> invocation, so its absence proves that function has **never run**.
>
> That's why I won't claim our notification pipeline works end to end.
> Notifications are written straight to the DynamoDB table by the services, and
> they do work in-app — there are eighteen of them. But email isn't configured;
> the sender address is empty."

**Proof by absence is an elegant diagnostic** and worth demonstrating.

---

## 6. The retention gap — volunteer it

```
CloudWatch -> Log groups -> the Retention column
```

| Log group | Retention |
|---|---|
| `/aws/apigateway/lifelink-dev` | **30 days** |
| `/aws/lambda/lifelink-dev-api` | **30 days** |
| the other four | **Never expire** |

**Say this:**
> "Here's a gap I found while documenting rather than while building. Our
> template sets thirty-day retention, and it works — for the two log groups the
> template declares. The other four were auto-created by Lambda on first
> invocation, and an implicitly created log group defaults to never expiring.
> The dispatcher runs every minute and has about eight megabytes that will never
> be deleted.
>
> It isn't drift in CloudFormation's sense, because those resources were never
> in the stack at all — it's an infrastructure-as-code coverage gap. The fix is
> to declare a log group per function in the template."

---

## 7. Proving the scheduled jobs actually run

```
CloudWatch -> Log groups -> /aws/lambda/lifelink-dev-dispatcher -> Log streams
```

**Streams appear roughly every minute.**

**Say this:**
> "That's the dispatcher running on its schedule — a log stream roughly every
> minute. Configuration tells you what's *supposed* to happen; the log stream
> timestamps prove it actually does. It's also why this log group is the biggest
> at eight megabytes."

Then show the schedule itself:

```
EventBridge -> Scheduler -> Schedules -> PriorityDispatcherEveryMinute
```

**Not EventBridge -> Rules, which is empty.**

---

## 8. X-Ray

```
Lambda -> lifelink-dev-api -> Monitor -> Traces
```
or `CloudWatch -> X-Ray traces -> Service map`.

**What it adds over logs:**

> "Tracing is active on all six functions. Logs tell you *that* something was
> slow; X-Ray tells you *which part* — how long the function ran versus how long
> each DynamoDB call took. The service map shows the call graph with latency on
> each edge."

---

## 9. Do not

| Action | Why |
|---|---|
| **Use the Test button** with a fabricated event | a malformed event produces an error that looks like a broken function |
| Edit any configuration | template-controlled; creates drift |
| Change memory or timeout | the 29 s value is deliberate |
| Set reserved concurrency | would remove capacity from the shared pool of 10 |
| Delete a log group | |

**If asked to invoke it manually:** the better answer is to use the real site
and watch the invocation, because that demonstrates the whole path rather than
the function in isolation.

---

## 10. Questions and answers

**"Why one function for 58 routes?"**
> Three reasons. With a concurrency limit of ten, fifty-eight functions would
> make contention worse. One function stays warm across all routes, whereas
> fifty-eight each go cold. And it's one package, one role to review, one log
> group to search.
>
> The real cost is that the IAM role is the union of every route's needs, so a
> route that only reads facilities runs with permission to write inventory.
> That's a genuine downside — if the limit were a thousand and the team bigger,
> I'd split by feature area.

**"What's a cold start, and do you have them?"**
> Yes. The first invocation in a new execution environment pays for creating the
> micro-VM, loading Python and importing our modules — a few hundred
> milliseconds, and our heaviest import is the crypto library we need for token
> verification. Running one function for all routes helps, because it stays warm
> across every route. Provisioned concurrency would eliminate it but bills
> continuously and would consume part of a pool of ten.

**"Why arm64?"**
> Graviton is cheaper for identical work. The catch is that the deployment
> package has to contain arm64 Linux wheels — which is exactly why we can't use
> `sam build` on a Windows machine. It would install a Windows binary of the
> crypto library, and that can't load on the function. We have a build script
> that fetches the right manylinux arm64 wheels explicitly.

**"How do you know which function handled a request?"**
> The correlation id. Every API response carries one, and the same id is in the
> log line — so I can take a failure from the browser's Network tab and find the
> exact log entry in Logs Insights in about thirty seconds. I can show you that.

---

## 11. Cross-references

- [CONFIGURATION_WALKTHROUGHS.md](CONFIGURATION_WALKTHROUGHS.md) §F
- [../04_AWS_COMPLETE_GUIDE/05_AWS_Lambda.md](../04_AWS_COMPLETE_GUIDE/05_AWS_Lambda.md)
- [08_Showing_CloudWatch_Logs.md](08_Showing_CloudWatch_Logs.md)
- [06_Showing_IAM_In_Action.md](06_Showing_IAM_In_Action.md)
