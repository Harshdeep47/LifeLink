# LifeLink — Operations Runbook

> **These procedures have not been executed against a deployment.** Nothing
> has been deployed. They are written from the AWS documentation and the
> implementation, and the untested ones are marked.

---

## Alarm index

| Alarm | Severity | Runbook |
|---|---|---|
| `lifelink-<env>-dispatcher-failure` | **Critical** | [§1](#1-dispatcher-failure) |
| `lifelink-<env>-work-dlq-not-empty` | High | [§2](#2-dead-letter-queue-not-empty) |
| `lifelink-<env>-notification-dlq-not-empty` | High | [§2](#2-dead-letter-queue-not-empty) |
| `lifelink-<env>-api-errors` | High | [§3](#3-api-errors) |
| `lifelink-<env>-work-queue-age` | Medium | [§4](#4-queue-backlog) |
| `lifelink-<env>-lambda-throttles` | Medium | [§5](#5-lambda-throttling) |
| `lifelink-<env>-api-latency-p95` | Medium | [§6](#6-latency) |
| `lifelink-<env>-inventory-throttles` | Medium | [§7](#7-dynamodb-throttling) |

---

## 1. Dispatcher failure

**This is the most serious alarm in the system.** Emergency requests are no
longer being matched, while every other indicator looks healthy.

1. Read the most recent dispatcher invocation log:
   `/aws/lambda/lifelink-<env>-dispatcher`.
2. Identify whether one request causes the failure or the failure is systemic.
3. **Single request** — take its id from the log, inspect it, and cancel or
   correct it. Confirm the next run succeeds.
4. **Systemic** — a table unavailable, a permission revoked, a code defect.
   Fix the cause.
5. Verify recovery: the next run logs `scheduler.dispatch.complete`.
6. **Check for damage.** List requests whose `requiredBy` passed during the
   outage and contact those requesters out of band.

The handler re-raises deliberately so that this alarm fires rather than the
failure being absorbed.

## 2. Dead-letter queue not empty

A message failed five times.

1. Read a sample without consuming it:
   ```bash
   aws sqs receive-message --queue-url <dlq-url> --max-number-of-messages 1
   ```
2. Take `correlationId` and `eventId` from the body.
3. Query logs for that correlation id to see all five failures.
4. **Classify:**
   - *Poison message* — malformed or referencing a deleted entity. Record the
     event id, delete the message, and raise a defect for the validation gap
     that let it through.
   - *Dependency failure* — a table, a provider or a permission. Fix the
     cause, then redrive.
5. Redrive only after diagnosis:
   ```bash
   aws sqs start-message-move-task \
     --source-arn <dlq-arn> --destination-arn <source-queue-arn>
   ```
6. Confirm the alarm clears.

**Never redrive before diagnosing.** A poison message will fail five more
times and return.

## 3. API errors

1. Query logs for `event = "http.unhandled"` in the window.
2. Group by route and by exception.
3. A single route failing suggests a defect; all routes failing suggests a
   dependency.
4. Check DynamoDB and Cognito health.
5. If a recent deployment preceded it, consider rolling back.

Domain errors (4xx) do not trigger this alarm — only unhandled exceptions do.

## 4. Queue backlog

The oldest unprocessed message is over five minutes old.

1. Check queue depth and the consumer's invocation and error counts.
2. **Consumer erroring** — see §2.
3. **Consumer throttled** — see §5.
4. **Genuine volume** — consider raising `MaximumConcurrency`, but remember
   the account ceiling of 10 is shared with the API tier.

## 5. Lambda throttling

Expected on this account: the concurrent-execution ceiling is **10** against a
default of 1000.

1. Confirm the ceiling has not changed:
   ```bash
   aws lambda get-account-settings
   ```
2. Identify which function is consuming the pool.
3. If a background consumer is monopolising it, reduce its
   `MaximumConcurrency`.
4. If demand is genuine, request a quota increase in Service Quotas. The
   architecture needs no change to use a higher limit.

## 6. Latency

p95 above three seconds.

1. Check whether DynamoDB latency rose in the same window.
2. Check whether searches with large radii increased — a 100 km search issues
   up to 65 indexed queries.
3. Check cold-start frequency; low traffic means more cold starts.
4. Check for throttling, which presents as latency before it presents as
   errors.

## 7. DynamoDB throttling

1. Identify the table and whether reads or writes are affected.
2. On-demand tables scale automatically but have a burst ceiling.
3. Check for a hot partition — the expiry sweep is the designed hazard and is
   sharded ten ways.
4. Confirm no code path has begun scanning.

---

## 8. Restoring a table

**UNTESTED — never executed against a deployment.**

1. Identify the restore point.
2. Restore to a **new** table name:
   ```bash
   aws dynamodb restore-table-to-point-in-time \
     --source-table-name lifelink-prod-inventory \
     --target-table-name lifelink-prod-inventory-restored \
     --restore-date-time 2026-11-15T10:00:00Z
   ```
3. **Verify the restored data before switching anything.**
4. Either update the stack to point at the restored table, or copy rows back.
5. Record what was lost between the restore point and the incident.

Never restore over a live table. The target is always new.

## 9. Pending outbox rows

Rows with `dispatched: false` older than a few minutes.

The domain data is correct — the outbox write was transactional. Only
publication is behind.

1. Check the publisher's logs and the stream's iterator age.
2. Check `WORK_QUEUE_URL` and `NOTIFICATION_QUEUE_URL` are configured.
3. The stream will retry. For a persistent backlog, invoke the publisher
   manually against the pending rows.

## 10. Suspending an organization

1. ```
   POST /admin/organizations/{id}/status
   { "status": "SUSPENDED", "reason": "<reason>" }
   ```
2. Effect is immediate: a hospital loses priority certification on its very
   next request, because verification is re-checked at certification time.
3. Verify in the audit trail.
4. Check for in-flight emergency requests from that organization — matching
   halts and records a `MATCHING_HALTED_ORG_SUSPENDED` event.

## 11. Suspending a user

1. ```
   POST /admin/users/{userId}/status
   { "status": "SUSPENDED" }
   ```
2. Their existing token stops working on the next request. No sign-out is
   needed and no token revocation is required, because authorization reads
   account status from the database.
3. Verify by querying the audit trail for that user.

## 12. Rotating a secret

1. Update the value in Secrets Manager.
2. Lambda reads it per invocation, so no redeployment is needed.
3. Verify by exercising the affected integration.

---

## Escalation

| Condition | Action |
|---|---|
| Dispatcher down over 15 minutes | Notify the project owner; emergency requests are not being matched |
| Data loss suspected | Stop writes if possible; do not restore over live data |
| Suspected security incident | Suspend the affected accounts first, investigate second |
| Spend limit reached | Only the project owner can change it, in AWS Settings |

## Useful queries

```
# Everything one request caused, including background work
fields @timestamp, logger, event, message
| filter correlation_id = "web-..."
| sort @timestamp asc

# Concurrency conflicts
filter event = "inventory.conflict.retry"

# Rejected stale feeds
filter event = "inventory.ingest.stale"

# Authorization refusals
filter event = "http.error" and message like /FORBIDDEN|SUSPENDED/

# Dispatcher activity
filter event like /emergency.dispatch/
```
