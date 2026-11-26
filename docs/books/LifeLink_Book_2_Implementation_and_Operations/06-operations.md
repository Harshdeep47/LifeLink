<!-- pagebreak -->

# 25. Infrastructure Templates

## 25.1 One stack

`infrastructure/template.yaml` — {{fact:cfn_lines}} lines,
{{fact:cfn_resources}} resources, {{fact:cfn_alarms}} alarms. Validated by
`cfn-lint` with no findings and by `sam validate --lint`.

:::warning Deployed, but read this chapter as a description of the template
This template **has** been deployed — stack `lifelink-dev` in
`ap-southeast-2`, live since 15 November 2026. An earlier edition of this
chapter said it never had.

Two cautions. Most of what follows still describes what the template
*creates* rather than observed operational history: the alarms exist but have
never fired in anger, and no restore has been rehearsed. And the repository is
ahead of the deployed stack, so a resource described here may differ from the
running one. The deployment itself is recorded in `DEPLOYMENT_RECORD.md`; the
gap is in `REPOSITORY_VS_DEPLOYED.md`.
:::

## 25.2 Parameters

| Parameter | Default | Effect |
|---|---|---|
| `Environment` | `dev` | Table retention, seeding guard, resource names |
| `LogRetentionDays` | 30 | CloudWatch Logs retention |
| `CognitoDomainPrefix` | `lifelink-dev` | Managed login domain |
| `CallbackUrl` | localhost | OAuth redirect |
| `SesSenderAddress` | empty | Disables email when empty |
| `EnableLocationResources` | `true` | Creates map, place index, route calculator |

*Table 25.1. Template parameters.*

## 25.3 Conditions that change behaviour

```yaml
Conditions:
  IsProduction: !Equals [!Ref Environment, prod]
  CreateLocation: !Equals [!Ref EnableLocationResources, 'true']
  HasSesSender: !Not [!Equals [!Ref SesSenderAddress, '']]
```

*Listing 25.1. The three conditions.*

`IsProduction` drives `DeletionPolicy`. In production a table is retained when
the stack is deleted; in development it is removed, because a developer tearing
down a stack wants it gone.

The audit table is the exception — retained in every environment, because
deleting an audit trail by accident is not a mistake worth allowing.

## 25.4 Globals

```yaml
Globals:
  Function:
    Runtime: python3.14
    Architectures: [arm64]
    Timeout: 29
    MemorySize: 512
    Tracing: Active
```

*Listing 25.2. Shared function configuration.*

The 29-second timeout sits just inside API Gateway's 29-second integration
limit, so a slow request produces a handled timeout rather than the gateway
giving up on a function still running.

## 25.5 Deploying, when it is approved

```bash
sam validate --template infrastructure/template.yaml --lint
cfn-lint infrastructure/template.yaml

sam build --template infrastructure/template.yaml

sam deploy \
  --template infrastructure/template.yaml \
  --stack-name lifelink-dev \
  --region ap-southeast-2 \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides Environment=dev \
  --confirm-changeset

aws s3 sync frontend/dist/ s3://<FrontendBucketName>/ --delete
aws cloudfront create-invalidation --distribution-id <id> --paths "/*"
```

*Listing 25.3. The deployment sequence. `--confirm-changeset` is not optional:
it is the step where a destructive change becomes visible before it happens.*

<!-- pagebreak -->

# 26. Local Development Workflow

## 26.1 Daily commands

| Task | Command |
|---|---|
| Check what is running | `python scripts/dev.py status` |
| Start the database | `python scripts/dev.py db-start` |
| Create tables | `python scripts/dev.py create-tables` |
| Seed data | `python scripts/seed_demo.py` |
| Reset data | `python scripts/seed_demo.py --reset` |
| Validate data | `python scripts/seed_demo.py --validate` |
| Mint a token | `python scripts/dev.py token user-donor-1` |
| Run the API | `python scripts/local_server.py --port 8080` |
| Run the frontend | `cd frontend && npm run dev` |
| Backend tests | `cd backend && pytest tests -q` |
| Frontend tests | `cd frontend && npm test` |
| Lint | `cd backend && ruff check src tests` |
| Regenerate OpenAPI | `python scripts/generate_openapi.py` |
| Build the books | `python scripts/build_books.py` |

*Table 26.1. The complete command set.*

## 26.2 The local server is not a second application

{{include:scripts/local_server.py:anchor:def _handle(self, method: str):30}}

*Listing 26.1. Event translation in `scripts/local_server.py`.*

It builds an API Gateway-shaped event and calls the same router the Lambda
handler calls. There is no separate local application that could drift from the
deployed one; only the transport differs.

## 26.3 Table creation comes from one definition

{{include:backend/src/repositories/schema.py:def create_table_kwargs}}

*Listing 26.2. Schema definitions from
`backend/src/repositories/schema.py`.*

The same definitions drive the local bootstrap and the integration-test
fixture. The CloudFormation template declares the same tables separately, which
is a known duplication — a generator could emit the template resources from
this file, and that is recorded as future work rather than claimed as done.

<!-- pagebreak -->

# 27. Observability in Operation

## 27.1 Reading a log line

```json
{
  "timestamp": "2026-11-15T12:34:56.789Z",
  "level": "INFO",
  "logger": "services.inventory_service",
  "message": "stock adjusted",
  "correlation_id": "web-7f3a...",
  "actor_id": "user-bb-admin-1",
  "organization_id": "org-bb-patiala-1",
  "event": "inventory.stock.adjusted",
  "context": { "batchId": "01JD...", "operation": "DEDUCT", "delta": -2 }
}
```

*Listing 27.1. A representative log line.*

The `event` field is a dotted machine-readable name, stable across wording
changes, which makes metric filters and log queries durable.

## 27.2 Following a request

```bash
# Everything one user action caused, including background work
fields @timestamp, logger, event, message
| filter correlation_id = "web-7f3a..."
| sort @timestamp asc
```

*Listing 27.2. A CloudWatch Logs Insights query.*

Because the correlation id propagates into outbox events and queue messages,
this returns the synchronous request and the asynchronous consequences
together.

## 27.3 Useful queries

| Question | Filter |
|---|---|
| Concurrency conflicts | `event = "inventory.conflict.retry"` |
| Rejected stale feeds | `event = "inventory.ingest.stale"` |
| Suppressed duplicate work | `event like /duplicate/` |
| Dispatcher activity | `event like /emergency.dispatch/` |
| Authorization refusals | `event = "http.error" and code like /FORBIDDEN/` |

*Table 27.1. Diagnostic queries by the event names the code emits.*

<!-- pagebreak -->

# 28. Operational Runbooks

## 28.1 Dead-letter queue alarm

**Symptom.** `lifelink-<env>-work-dlq-not-empty` or the notification
equivalent has fired.

1. Read a sample message: `aws sqs receive-message --queue-url <dlq>`.
2. Take the `correlationId` and `eventId` from the body.
3. Query logs for that correlation id to find the five failures.
4. Classify: a poison message (bad data) or a dependency failure.
5. **Poison message** — record the event id, delete the message, and open a
   defect for the validation gap that let it through.
6. **Dependency failure** — fix the dependency, then redrive the queue.
7. Confirm the alarm clears.

Do not redrive without diagnosis. A poison message will fail five more times
and return.

```diagram
type: flow
title: Dead letter queue triage
node alarm Alarm fires on a non empty dead letter queue style=external
node sample Read a sample message and take its correlation id style=domain
node logs Query logs for the five failures style=domain
node classify Classify poison message or dependency failure style=domain
node act Delete and raise a defect or fix and redrive style=domain
node verify Confirm the alarm clears style=domain
```

*Figure 28.1. Triage order. Redriving before diagnosis simply repeats the
failure.*

## 28.2 Lambda throttling alarm

**Symptom.** `lifelink-<env>-lambda-throttles` has fired.

Expected at a ceiling of {{fact:lambda_concurrency}}. Confirm the ceiling has
not changed, check whether one consumer is monopolising the pool, and consider
a quota increase. The architecture needs no change to use a higher limit.

## 28.3 Dispatcher failure alarm

**Symptom.** `lifelink-<env>-dispatcher-failure` has fired.

**This is the most serious alarm in the system.** Emergency requests are not
being matched.

1. Check the dispatcher's most recent invocation log.
2. If a single request is causing the failure, identify it from the correlation
   id and cancel or correct it.
3. If the failure is systemic (a table unavailable, a permission revoked), fix
   the cause.
4. Verify recovery: the next run should log `scheduler.dispatch.complete`.
5. Check for requests whose deadlines passed during the outage.

## 28.4 Pending outbox rows

**Symptom.** Rows in `lifelink-<env>-outbox` with `dispatched: false` older
than a few minutes.

The domain data is correct — the outbox write was transactional. Only the
publication is behind. Check the publisher's logs and the stream's iterator
age, then let the stream retry or invoke the publisher manually.

## 28.5 Restoring a table

1. Identify the restore point.
2. Restore to a **new** table name: `aws dynamodb restore-table-to-point-in-time`.
3. Verify the restored data before switching anything.
4. Update the stack to point at the restored table, or copy rows back.
5. Record what was lost between the restore point and the incident.

Never restore over a live table. The restore target is always new.

:::warning Untested
This procedure is written from the AWS documentation and has **not been
rehearsed** against the running stack. LifeLink is deployed (24 November 2026)
and point-in-time recovery is enabled on eight of the twelve tables, but no
restore has been exercised.
:::

## 28.6 Suspending an organization

1. `POST /admin/organizations/{id}/status` with `SUSPENDED` and a reason.
2. Effect is immediate: the hospital loses priority certification on its very
   next request, because verification is re-checked at certification time.
3. Verify in the audit trail.
4. Check for in-flight emergency requests from that organization; matching
   halts for them with a recorded event.

<!-- pagebreak -->

# 29. Troubleshooting

| Symptom | Likely cause | Resolution |
|---|---|---|
| `EndpointConnectionError` locally | Local database not running | `python scripts/dev.py db-start` |
| `ResourceNotFoundException` | Tables not created | `python scripts/dev.py create-tables` |
| 401 on every request | Token expired or keys regenerated | Mint a new token |
| 401 with a valid-looking token | Seeded users missing | Run the seeder |
| 403 `ACCOUNT_SUSPENDED` | Using `user-suspended-1` | Expected; that account exists to demonstrate this |
| 403 `CROSS_ORGANIZATION_DENIED` | Token belongs to another organization | Use a user from the owning organization |
| 409 `CONCURRENT_MODIFICATION` | Two writers on one batch | Re-read and retry; expected under contention |
| `ValidationException` from DynamoDB | An expression placeholder is declared but unused | See Chapter 6.2 |
| Empty facility search | Radius too small, or filters too strict | Widen the radius; clear filters |
| Frontend cannot reach the API | Local server not running, or wrong port | Check the Vite proxy target |
| `npm` not found in Git Bash | Node is on the Windows PATH only | Use PowerShell, or add it |
| Book build reports unresolved directives | A referenced function was renamed | Update the anchor or selector |

*Table 29.1. Symptoms and resolutions.*

<!-- pagebreak -->

# 30. Known Limitations

Listed plainly, because a guide that omits them is not useful to the next
person who works on this.

| # | Limitation | Consequence | Status |
|---|---|---|---|
| 1 | Deployed, but with no operational history | Chapters 25–28 describe what the template creates; no alarm has fired and no restore has been rehearsed | — |
| 2 | Compatibility reference is `UNREVIEWED_SYNTHETIC` | Cannot be relied on clinically | Disclosed in every response |
| 3 | SMS not implemented | No SMS notifications | Blocked by SCP and plan |
| 4 | SES sandbox | Email reaches verified recipients only | Account state |
| 5 | Local auth is not Cognito | Cognito itself is not exercised locally | Documented on the sign-in page |
| 6 | No load testing | No measured throughput figure | Meaningless at a ceiling of 10 |
| 7 | No restore rehearsal | RPO/RTO are design assumptions | Nothing deployed to restore |
| 8 | Dashboard aggregates computed per request | Slow at scale | Needs a read model |
| 9 | Table schema duplicated between Python and CloudFormation | Can drift | A generator would fix it |
| 10 | Accessibility partially verified | Structure done, no audit tool run | Needs an audit |
| 11 | No CI pipeline | Tests run manually | Not requested |

*Table 30.1. Known limitations.*

## 30.1 A defect found while writing this chapter

Drafting the limitations table surfaced a real bug, which is an argument for
writing documentation while the code is fresh rather than afterwards.

The camp reminder sweep queries a `GSI4-reminder` index keyed on
`REMINDER#WINDOW`. The demo seeder set that attribute explicitly;
`CampRepository.create_camp` did not. A camp created through the API therefore
never appeared in the sweep's query and would never have produced reminders.

The reminder *logic* was correct and fully unit-tested — all five re-checks
behaved properly. The index population was the gap, and the failure mode was
invisible: no error, no alarm, just reminders that never arrived. Unit tests
passed because they tested the decision function, not the query that feeds it.

{{include:backend/src/repositories/camp_repo.py:anchor:# Reminder sweep index:6}}

*Listing 30.1. The fix in `backend/src/repositories/camp_repo.py`, with a
comment explaining why it must live here rather than in callers.*

It is now covered by `backend/tests/integration/test_camp_reminders.py`, whose
first test asserts the property directly rather than inferring it from the
sweep appearing to work:

{{include:backend/tests/integration/test_camp_reminders.py:def test_a_camp_created_through_the_service_is_in_the_reminder_index}}

*Listing 30.2. The regression test.*

This is the fifth bug in this project found by testing against a real datastore
rather than a fake, and the fourth whose symptom was silence rather than an
error.
