# EventBridge and Step Functions

What LifeLink uses for scheduling, and an explicit statement about what it
does **not** use.

---

## 1. The headline: Step Functions is NOT used

**Zero occurrences in `infrastructure/template.yaml`. There are no state
machines in this account.**

This document covers Step Functions **only as a comparison and a conceptual
topic**, which is exactly what it deserves.

> **Important correction to repeat if you hear it stated otherwise.** Earlier in
> this project's history, ADR-0006 was mistakenly cited as rejecting Step
> Functions by name. **It does not mention them.** ADR-0006 is about choosing an
> application-level priority dispatcher over three separate SQS queues.
>
> **The honest evidence that Step Functions is unused is the template itself.**
> If asked, say: "We don't use Step Functions — you can check the template,
> there are none. Our scheduling is EventBridge Scheduler." Do not cite an ADR
> that does not exist.

---

## 2. What LifeLink actually uses: EventBridge Scheduler

**`AWS::Scheduler::Schedule` — the newer, purpose-built scheduling service.
Not `AWS::Events::Rule`.**

| | `PriorityDispatcherEveryMinute` | `ScheduledMaintenanceEveryTenMinutes` |
|---|---|---|
| Expression | **`rate(1 minute)`** | **`rate(10 minutes)`** |
| Timezone | UTC | UTC |
| State | ENABLED | ENABLED |
| Flexible time window | **OFF** | OFF |
| Target | `lifelink-dev-dispatcher` | `lifelink-dev-maintenance` |
| Invocation role | `...PriorityDispatcherEveryMinuteRole-...` | `...ScheduledMaintenanceEveryTenMinutesRol-...` |
| Retry policy | max event age 86400 s, **185 attempts** | same |
| **Dead-letter queue** | **none** | **none** |
| Input payload | none | none |

**Verified:** `aws events list-rules` returns an **empty list**. There are no
classic EventBridge rules at all.

### Why this distinction matters practically

They are **different Console pages**. If you look under
`EventBridge -> Rules` you will find nothing and look unprepared. The correct
path is:

```
Amazon EventBridge -> Scheduler -> Schedules
```

---

## 3. EventBridge has three distinct parts — know which you mean

"EventBridge" is an umbrella name covering things people conflate:

| Part | What it does | LifeLink |
|---|---|---|
| **Event Bus** | routes events between services by pattern matching | **not used** |
| **Rules** | match events on a bus, or run on a schedule | **not used** (0 rules) |
| **Scheduler** | purpose-built scheduled invocation | **used — 2 schedules** |
| **Pipes** | point-to-point source-to-target with filtering | **not used** |

### Scheduler versus Rules — why Scheduler

| | **Scheduler** | Rules (schedule type) |
|---|---|---|
| Purpose | built for scheduling | scheduling as a side effect of event matching |
| One-time schedules | **yes** (`at(...)`) | no |
| Timezones + daylight saving | **yes** | UTC only |
| Flexible time window | **yes** — spread invocations to smooth load | no |
| Built-in retry policy + DLQ | **yes** | limited |
| Scale | millions of schedules | bounded by rule quotas |

**Say this:**
> "We use EventBridge Scheduler rather than EventBridge Rules. Scheduler is
> purpose-built for this — it handles timezones and daylight saving properly,
> supports one-time schedules, has a flexible time window to spread load, and
> has its own retry policy. Rules can run on a schedule, but scheduling is a
> side effect of their event-matching design. There are no classic rules in our
> account at all, so the Console page to look at is EventBridge, then Scheduler,
> then Schedules."

---

## 4. The two scheduled jobs and what they do

### `lifelink-dev-dispatcher` — every minute

`handlers.workers.dispatcher_handler`

Finds emergency requests awaiting dispatch (via `GSI1-dispatch`), ranks
candidate providers using `domain/ranking.py`, records dispatch events, and
queues notifications.

**Why every minute?** Because this is the **emergency** path. A blood request
with a deadline cannot wait ten minutes to be sent to providers. One minute is
the shortest `rate()` interval available and the latency cost is acceptable.

**Why `FlexibleTimeWindow: OFF`?** Because deliberately spreading the
invocation within a window would add latency to the exact path whose purpose is
to reduce it.

**Why a schedule rather than invoking the dispatcher synchronously when a
request is created?** Because a request also becomes dispatchable through
*time* — a deadline approaching, a provider failing to respond, a previous
dispatch expiring. A poll handles creation **and** all the time-driven
transitions with one mechanism. ADR-0006 chose this application-level
dispatcher over three priority SQS queues, because ranking needs to consider
distance, availability and freshness together, which a queue's ordering cannot
express.

**That is the strongest answer in this document.** A queue orders by arrival; a
ranked dispatcher orders by suitability.

### `lifelink-dev-maintenance` — every ten minutes

`handlers.workers.maintenance_handler`

Expires reservations past their hold window, expires alerts, rolls up facility
freshness timestamps, and recomputes derived state.

**Why ten minutes?** Because a reservation that should have expired showing as
active for a few minutes is a cosmetic problem, not a safety one — the API and
the UI both compute effective status from the clock rather than trusting the
stored status. `reservationView.js` has `isStaleHold()` for exactly this.

**That design choice is why a ten-minute interval is safe**, and it is worth
saying: the schedule is a cleanup convenience, not a correctness dependency.

---

## 5. The honest gaps in the scheduling setup

| Gap | Consequence |
|---|---|
| **Retry policy is the AWS default** | 185 attempts over 24 hours — not a considered choice |
| **No dead-letter queue on either schedule** | A target that fails for a full day fails **silently** |
| Combined with the SNS topic having 0 subscriptions | **a dispatcher outage would be invisible** |

**Say this:**
> "Two honest weaknesses here. The retry policy on both schedules is just the
> AWS default — 185 attempts over twenty-four hours — rather than something we
> reasoned about. And neither schedule has a dead-letter queue, so if the target
> kept failing we'd get no record of the dropped invocations.
>
> Combined with our alarm topic having no subscribers, that means a dispatcher
> outage would be invisible. There *is* an alarm —
> `lifelink-dev-dispatcher-failure` fires on a single error — so the detection
> exists; it's the notification that's missing. That's the weakest part of our
> operational setup and I'd fix the SNS subscription first, because it's a
> one-minute change that makes four other alarms useful."

---

## 6. Step Functions — the conceptual comparison

**What it is.** A managed workflow service. You define a state machine in JSON
or YAML, and AWS executes it step by step, keeping durable state between steps,
retrying individual steps, and handling branching, parallelism and waits.

**What it is genuinely good at:**

| Capability | Why it is hard without it |
|---|---|
| **Durable long-running workflows** | A workflow that waits hours or days for a human cannot be a Lambda, which caps at 15 minutes |
| **Visual execution history** | You can see exactly which step a particular execution failed at |
| **Per-step retry and catch** | Each step gets its own retry policy and error handling |
| **Saga / compensation** | Undo earlier steps when a later one fails |
| **Wait states** | "Wait 48 hours, then check again" costs nothing while waiting |

**Why LifeLink does not need it:**

| LifeLink workflow | Why a state machine is unnecessary |
|---|---|
| Emergency dispatch | A **poll** handles creation and all time-driven transitions with one mechanism. The state lives in the `emergency` table, where it must be queryable anyway |
| Reservation lifecycle | State transitions are driven by **user actions** and a clock, not by an orchestrated sequence |
| Outbox publishing | A stream plus a queue, with retries at the event source |
| Maintenance | A periodic sweep |

**The deeper reason, and the best thing to say:**

> "Step Functions is for orchestrating a sequence where you need durable state
> *between* the steps. Our workflows don't have that shape. An emergency
> request's state isn't orchestration state — it's domain state that lives in
> DynamoDB because the UI has to query it anyway. The transitions are driven by
> users acting and by time passing, not by a controller walking through steps.
>
> If I'd modelled it as a state machine, I'd have the same state in two places:
> in the execution and in the table. That's worse, not better.
>
> Where I would reach for it: if we added a multi-day donor eligibility
> workflow with human approval steps and timeouts, or a compensating transaction
> that had to undo several writes across services. Neither exists here."

### If asked "would Step Functions have been better?"

Give a real answer, not a defensive one:

> "For one thing, maybe. The emergency dispatch flow has retries and timeouts,
> and Step Functions' visual execution history would make debugging a specific
> request's journey much easier than reading CloudWatch logs — that's a genuine
> benefit we don't have.
>
> What it would cost is that the dispatcher currently handles every open request
> in one invocation per minute, ranked together. With Step Functions I'd have one
> execution per request, which means I'd lose the ability to rank across requests
> — and there'd be a per-state-transition charge. For a system with a hard
> concurrency limit of ten, one long-lived execution per request is also the
> wrong shape.
>
> So: better observability, worse fit for cross-request ranking. We chose the
> poll."

---

## 7. Console demonstration

```
Amazon EventBridge -> Scheduler -> Schedules        (2 schedules)
  PriorityDispatcherEveryMinute
     Schedule pattern -> rate(1 minute), UTC, flexible window off
     Target           -> lifelink-dev-dispatcher
     Retry policy     -> 185 attempts, max age 24 h, no DLQ
     Permissions      -> the invocation role
```

Then show it is real:

```
CloudWatch -> Log groups -> /aws/lambda/lifelink-dev-dispatcher
  -> log streams appearing roughly every minute
```

**That is the convincing demonstration:** the log stream timestamps prove the
schedule is actually firing, not just configured. The dispatcher log group has
accumulated about 8 MB precisely because it runs every minute.

Also worth showing, to prove the negative:

```
EventBridge -> Rules        -> empty  ("we use Scheduler, not Rules")
Step Functions -> State machines -> empty  ("we don't use it at all")
```

**Showing an empty page is a legitimate demonstration** when the claim is "we
do not use this."

---

## 8. Spoken answers

### 20–30 seconds
> "We have two scheduled jobs on EventBridge Scheduler: a dispatcher every
> minute that sends emergency requests to candidate providers, and a maintenance
> job every ten minutes that expires reservations and alerts. We do not use Step
> Functions at all — there are none in the template. Our workflows are driven by
> user actions and by time, not by orchestrated sequences."

### 1–2 minutes
> "Scheduling is EventBridge Scheduler — worth distinguishing from EventBridge
> Rules, which we have none of. Scheduler is purpose-built: timezones, one-time
> schedules, a retry policy, a flexible time window.
>
> The dispatcher runs every minute because it's the emergency path, and a
> request with a deadline can't wait ten minutes to reach providers. We turned
> the flexible time window off deliberately — spreading the invocation would add
> latency to the one job whose purpose is reducing it.
>
> The design question people ask is why a poll rather than invoking the
> dispatcher when a request is created. The answer is that a request also
> becomes dispatchable through *time* — a deadline approaching, a provider not
> responding, a previous dispatch expiring. A poll handles creation and all the
> time-driven transitions with one mechanism.
>
> And no Step Functions. Step Functions is for workflows needing durable state
> between steps. Our emergency request state isn't orchestration state — it's
> domain state in DynamoDB, because the UI has to query it anyway. Modelling it
> as a state machine would put the same state in two places."

---

## 9. Follow-up questions

**"What's the shortest schedule interval you can have?"**
> One minute with `rate(1 minute)`. If you needed finer granularity you'd keep a
> Lambda running and sleeping, or use a step-functions wait loop, both of which
> are worse. One minute is the floor for scheduled invocation.

**"How much does running something every minute cost?"**
> About 43,000 invocations a month. Scheduler itself has a very large free tier,
> and the Lambda invocations are well inside the free tier too. The real cost is
> CloudWatch Logs ingestion — and that's where our retention gap bites, because
> the dispatcher's log group never expires.

**"What if the dispatcher takes longer than a minute?"**
> Then a second invocation starts while the first is running. The handler is
> written to be safe under that — it uses conditional writes, so two invocations
> processing the same request can't both record a dispatch. The function timeout
> is 29 seconds anyway, so it can't overlap by much.

**"Could you use EventBridge Pipes anywhere?"**
> Possibly for the outbox. Pipes connects a source like a DynamoDB stream to a
> target like SQS with filtering, and no code in between — which is roughly what
> our outbox publisher Lambda does. The reason we kept the Lambda is that it
> makes a routing decision about which queue an event belongs on, and it needs
> to be able to transform the event. Pipes with an enrichment step could do it,
> but it'd be more moving parts for the same outcome.

---

## 10. Cross-references

- [05_AWS_Lambda.md](05_AWS_Lambda.md)
- [09_SNS_SQS_And_Notifications.md](09_SNS_SQS_And_Notifications.md)
- [../06_FEATURE_IMPLEMENTATION/04_Smart_Emergency_Coordination.md](../06_FEATURE_IMPLEMENTATION/04_Smart_Emergency_Coordination.md)
- [../02_SYSTEM_ARCHITECTURE/05_Architecture_Decisions.md](../02_SYSTEM_ARCHITECTURE/05_Architecture_Decisions.md)
- [../09_PRACTICAL_AWS_DEMONSTRATIONS/CONFIGURATION_WALKTHROUGHS.md](../09_PRACTICAL_AWS_DEMONSTRATIONS/CONFIGURATION_WALKTHROUGHS.md) §H
