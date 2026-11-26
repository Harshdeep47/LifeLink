# Error Handling and Retries

What happens when something fails — at each layer, with the real deployed
configuration.

---

## 1. The error contract

Every failed response:

```json
{ "error": { "code": "STABLE_CODE", "message": "human text", "details": {} },
  "correlationId": "corr-..." }
```

**Three properties that matter:**

| Property | Why |
|---|---|
| A **stable `code`** | the UI branches on behaviour, not on English text |
| A **`correlationId`** | any user-visible failure is traceable to a server log line |
| `details` | field-level validation information |

**Say this:**
> "Every error carries a stable machine-readable code and a correlation id. The
> code means the UI can decide what to do without string-matching English
> messages — `NO_UNRESERVED_STOCK` means something specific. And the correlation
> id is in the server log for the same request, so I can take a failure a user
> saw and find the exact log entry in about thirty seconds."

---

## 2. The error codes

| Status | Code | Meaning | Retryable? |
|---|---|---|---|
| 400 | `VALIDATION_ERROR` | bad input | no |
| 401 | `UNAUTHENTICATED` | no / invalid / expired token | no — re-authenticate |
| 403 | `FORBIDDEN` | role lacks the permission | no |
| 403 | `ACCOUNT_SUSPENDED` | valid token, suspended account | no |
| 404 | `NOT_FOUND` | no such record | no |
| 405 | — | path exists, wrong method | no |
| 409 | `CONCURRENT_MODIFICATION` | optimistic concurrency clash | **yes** |
| 409 | `NO_UNRESERVED_STOCK` | units already held | no — refresh instead |
| 429 | `RATE_LIMITED` | throttled | **yes** |
| 500 | — | unexpected | **yes** |
| 0 | `NETWORK_ERROR` | `fetch` itself failed | **yes** |

### How the client decides

```javascript
get isRetryable() {
  return this.status >= 500 || this.status === 0 ||
         this.code === 'RATE_LIMITED' || this.code === 'CONCURRENT_MODIFICATION'
}
get isAuthError() { return this.status === 401 || this.code === 'UNAUTHENTICATED' }
```

**Two computed properties instead of status-code checks scattered across fifty
components.** That is the design point.

**Why `NO_UNRESERVED_STOCK` is deliberately NOT retryable:** retrying would
fail again, because the units really are held. The correct response is to
refresh availability and let the user choose differently. **Marking a hopeless
retry as retryable is worse than not offering one** — it wastes the user's time
and hides the real situation.

---

## 3. Where errors are translated

**One place.** `backend/src/handlers/router.py` catches any `LifeLinkError` and
maps it to the right HTTP status via `appcore/responses.py`.

```
domain/errors.py    LifeLinkError subclasses, each with a stable code
        |
router.dispatch     from_exception() -> status + envelope
        |
the browser         ApiError with .code, .status, .isRetryable, .isAuthError
```

**Why in the router rather than in each handler:** fifty-eight handlers raising
domain exceptions and one place turning them into HTTP means a handler never
writes a status code, and a new error code gets consistent treatment
automatically.

---

## 4. Retries that happen automatically

| Layer | Retry behaviour |
|---|---|
| **boto3** | automatic retries with exponential backoff on throttles and 5xx |
| **SQS consumers** | failed message returns to the queue; **5 receives** then DLQ |
| **DynamoDB Streams** | **3 retries**, then **bisect the batch**, then the on-failure destination |
| **EventBridge Scheduler** | **185 attempts** over 24 h (the AWS default) |
| **CloudFront** | retries the origin on a connection failure |
| **The frontend** | **no automatic retry** — it *offers* one |

### Why the frontend does not retry automatically

**A deliberate choice worth defending.** An automatic retry on a write risks
double-applying an operation, and it hides a persistent failure from the user.
So the UI shows the error and offers a retry **the user chooses**.

Where automatic retry **is** safe — queue and stream consumers — it is
idempotent by design, protected by the `idempotency` table.

**Say this:**
> "Retries happen automatically on the paths where they're safe — boto3 backs
> off on throttles, SQS redelivers a failed message up to five times, the stream
> consumer retries three times and bisects the batch to isolate a bad record.
> Those are safe because the consumers are idempotent.
>
> The frontend deliberately doesn't retry automatically. An automatic retry on a
> write risks applying something twice, and it hides a persistent failure. So we
> show the error and offer a retry the user chooses — and we only offer it when
> retrying could actually succeed."

---

## 5. Idempotency — what makes automatic retry safe

**ADR-0009.** A conditional put into the `idempotency` table:

```
PutItem  PK = <idempotency key>
         ConditionExpression: attribute_not_exists(PK)
```

The first attempt claims the key; the second fails the condition, and the
handler returns the original result instead of re-applying.

Keys sent by `frontend/src/api/client.js`:

| Route | Key |
|---|---|
| `POST /alerts` | `alert-<timestamp>` |
| `POST /facilities/{id}/batches` | `batch-<facilityId>-<timestamp>` |
| `POST /camps/{id}/register` | **`reg-<campId>`** — no timestamp, so **stable** |
| `POST /emergency-requests` | caller-supplied |

**`reg-<campId>` is the interesting one:** because it has no timestamp,
registering for the same camp twice is idempotent **by the key's design**, not
merely within a retry window.

---

## 6. Dead-letter queues

| Queue | DLQ | After | Retention |
|---|---|---|---|
| `lifelink-dev-work` | `lifelink-dev-work-dlq` | 5 receives | **14 days** |
| `lifelink-dev-notifications` | `lifelink-dev-notifications-dlq` | 5 receives | **14 days** |
| outbox stream | on-failure -> `lifelink-dev-work-dlq` | 3 retries + bisect | 14 days |

**Why 14 days and not 4:** a DLQ exists for a **human** to investigate. Four
days could expire over a long weekend; fourteen is the maximum SQS allows.

**Both DLQs currently hold 0 messages**, with alarms at `> 0`.

### `BisectBatchOnFunctionError` — why it matters

If a batch of 10 stream records fails, Lambda splits it in half and retries each
half recursively, **isolating the one poison record** instead of blocking the
shard. Without it, a single bad record stalls the stream until it expires.

### `ReportBatchItemFailures`

The function returns **which** records failed, so successful records in a batch
are not reprocessed. Without it, one failure in five means all five retry.

---

## 7. The alarms — and the gap

| Alarm | Condition |
|---|---|
| `lifelink-dev-api-errors` | > 5 in 5 min |
| `lifelink-dev-api-latency-p95` | > 3000 ms for 2 periods |
| `lifelink-dev-lambda-throttles` | >= 1 |
| `lifelink-dev-dispatcher-failure` | >= 1 |
| `lifelink-dev-inventory-throttles` | > 5 in 5 min |
| `lifelink-dev-work-queue-age` | > 300 s for 2 periods |
| `lifelink-dev-work-dlq-not-empty` | > 0 |
| `lifelink-dev-notification-dlq-not-empty` | > 0 |

All currently `OK`. All `TreatMissingData: notBreaching` — **no data means
nobody used the system, not that it broke.**

### The gap

**All eight publish to an SNS topic with ZERO subscriptions. Detection works;
notification does not.**

Combined with **no DLQ on either EventBridge schedule**, a sustained dispatcher
failure would be detected and unreported.

**Volunteer this:**
> "Here's the weakest part of our reliability story. We have eight alarms with
> thresholds I can justify, and they all publish to an SNS topic with no
> subscriptions — so a problem would be detected and nobody would be told. And
> neither scheduled job has a dead-letter queue, so dropped invocations leave no
> record.
>
> The fix is a one-minute change: add an email subscription and confirm it. It
> happened because a subscription needs a real endpoint, which is personal data I
> didn't want in the template, so it became a manual step that never got done.
> An alarm nobody's subscribed to is monitoring theatre."

---

## 8. Graceful degradation — the pattern

**Every external dependency degrades one feature, not the application.**

| Failure | What survives |
|---|---|
| OSM tiles unavailable | blank basemap; **markers still render** |
| Amazon Location routing fails | facility list, contacts, **straight-line distance**; UI says directions unavailable |
| Amazon Location geocoding fails | device geolocation still works |
| Cognito unavailable | the **9 anonymous routes** still work |
| Notification worker fails | notification rows still written by the services |
| Queue backlog | writes still commit; background work is delayed |

**Nothing in the critical path — finding a blood bank and seeing its contact
details — depends on a non-AWS service.**

**And the honesty rule applies to failures too:** when routing fails the UI
says directions are unavailable rather than substituting the straight-line
distance. **A wrong distance looks exactly like data.**

---

## 9. Error handling in the frontend

| Mechanism | Purpose |
|---|---|
| `ErrorBoundary` (in `ui.jsx`) | a crash in one page shows a panel, not a blank app |
| **per-route** `ErrorBoundary` | so one page's failure cannot take down the shell |
| `AsyncState` | handles loading / error / **empty** / data consistently |
| `ErrorPanel` with `onRetry` | offers a retry when `isRetryable` |
| `map-fallback` | when WebGL is unavailable |

**`AsyncState` is the one to mention:** it means every page handles those four
states the same way, and **no page forgets the empty case** — which otherwise
shows as a blank area that looks broken.

> **And the lesson from the empty `catch`:** `no-empty` with
> `allowEmptyCatch: false` is an ESLint **error**, because an empty catch block
> hid a `ReferenceError` that stopped expired sessions from ever being cleared.
> **Error handling that swallows programming mistakes is worse than none.**

---

## 10. Status

| Aspect | Status |
|---|---|
| Error envelope and stable codes | `DEPLOYED` |
| Correlation id on every response | `DEPLOYED`, **verified live** |
| `isRetryable` / `isAuthError` | `TEST-VERIFIED` |
| Idempotency table | `DEPLOYED` — empty, as expected |
| DLQs configured | `DEPLOYED` — both empty |
| Batch bisection | `DEPLOYED` |
| 8 alarms | `DEPLOYED`, all `OK` |
| **Alarm notification** | **`NOT-IMPLEMENTED` — 0 SNS subscriptions** |
| **Schedule DLQs** | **`NOT-IMPLEMENTED`** |
| **DLQ recovery rehearsed** | **`NEEDS-VERIFICATION`** — no message has ever reached a DLQ |

**That last row is honest and worth saying:** the DLQs are configured and have
never been exercised, so the recovery procedure is documented rather than
practised.

---

## 11. Spoken answers

### "What happens when Lambda fails?" — 30 seconds
> "It depends on the invocation type, and that distinction is the point. A
> synchronous API call returns an error to the caller with a stable code and a
> correlation id. An SQS-triggered invocation doesn't lose the message — it goes
> back on the queue, is retried, and after five failed receives moves to a
> dead-letter queue that retains for fourteen days. The stream consumer retries
> three times and bisects the batch to isolate a bad record."

### 1–2 minutes
> "There are three layers.
>
> In the request path, domain errors carry stable codes and the router maps them
> to HTTP statuses in one place, so a handler never writes a status code. Every
> response — success or failure — carries a correlation id that's also in the
> CloudWatch log, so a failure a user saw is traceable in about thirty seconds.
>
> In the asynchronous path, retries are automatic because consumers are
> idempotent — protected by a conditional put into an idempotency table. SQS
> redelivers up to five times then dead-letters; the stream consumer retries
> three times and bisects the batch so one poison record doesn't stall the
> shard. DLQ retention is fourteen days rather than the four we use on the main
> queues, because a DLQ is for a human and four days could expire over a
> weekend.
>
> In the frontend we deliberately don't retry automatically — that risks
> double-applying a write and hides a persistent failure. We offer a retry, and
> only when retrying could actually succeed: `NO_UNRESERVED_STOCK` isn't
> retryable, because the units really are held and the right response is to
> refresh.
>
> And the honest gap: all eight alarms publish to an SNS topic with no
> subscriptions. The detection works; nothing reaches a person. Plus neither
> scheduled job has a dead-letter queue. That's the weakest part of the setup
> and it's a one-minute fix."

---

## 12. Follow-up questions

**"How would you recover a dead-lettered message?"**
> SQS has a redrive feature that moves messages from the DLQ back to the source
> queue once the cause is fixed. The honest caveat is that we've never had to do
> it — no message has ever reached either DLQ — so the procedure is documented
> rather than practised, and I'd expect to learn something the first time.

**"What if the same error keeps happening?"**
> In the request path, nothing retries automatically, so the user sees a
> consistent failure rather than a hanging page. In the async path, five receives
> then dead-letter, with an alarm on the DLQ becoming non-empty. The design
> intent is that a persistent failure becomes visible rather than silently
> looping — which it would, if the alarm reached anyone.

**"Why not just retry everything automatically?"**
> Because retrying a non-idempotent write can apply it twice, and retrying
> something that can't succeed just delays telling the user. Our rule is that
> automatic retry belongs where the operation is idempotent, which is the queue
> and stream consumers. In the request path we offer a retry and let the user
> decide — and we only offer it when the error is actually retryable.

---

## 13. Cross-references

- [06_Security_And_Threat_Scenarios.md](06_Security_And_Threat_Scenarios.md)
- [../04_AWS_COMPLETE_GUIDE/09_SNS_SQS_And_Notifications.md](../04_AWS_COMPLETE_GUIDE/09_SNS_SQS_And_Notifications.md)
- [../04_AWS_COMPLETE_GUIDE/11_CloudWatch.md](../04_AWS_COMPLETE_GUIDE/11_CloudWatch.md)
- [../05_DATABASE_AND_DATA/06_Concurrency_And_Data_Integrity.md](../05_DATABASE_AND_DATA/06_Concurrency_And_Data_Integrity.md)
- `docs/OPERATIONS_RUNBOOK.md`, `docs/TROUBLESHOOTING.md`, `docs/EDGE_CASE_REGISTER.md`
