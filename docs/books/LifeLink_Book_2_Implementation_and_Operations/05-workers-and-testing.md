<!-- pagebreak -->

# 20. Background Workers

## 20.1 Five handlers, five triggers

| Handler | Trigger | Idempotent by |
|---|---|---|
| `notification_handler` | SQS notification queue | Event id claim |
| `work_handler` | SQS work queue | Event id claim |
| `outbox_handler` | DynamoDB stream | The `dispatched` flag |
| `dispatcher_handler` | EventBridge, 1 minute | Status transitions |
| `maintenance_handler` | EventBridge, 10 minutes | Status transitions |

*Table 20.1. The background workers.*

```diagram
type: layered
title: How work reaches each background handler
layer Sources
node api API writes style=aws
node sched EventBridge schedules style=aws
layer Durability
node outbox Outbox table with stream style=data
layer Transport
node wq Work queue style=aws
node nq Notification queue style=aws
layer Handlers
node pub Outbox publisher style=aws
node ww Work worker style=aws
node nw Notification worker style=aws
node disp Dispatcher style=aws
node maint Maintenance style=aws
edge api -> outbox
edge outbox -> pub
edge pub -> wq
edge pub -> nq
edge wq -> ww
edge nq -> nw
edge sched -> disp
edge sched -> maint
```

*Figure 20.1. Trigger paths for the five background handlers.*

## 20.2 The idempotency claim

{{include:backend/src/handlers/workers.py:def _claim}}

*Listing 20.1. Claiming work from `backend/src/handlers/workers.py`.*

A message without an id is processed and relies on the handler's own
idempotency. A message with an id is claimed once; the second delivery finds a
completed claim and returns without doing anything.

## 20.3 Partial batch failures

Each queue consumer returns `batchItemFailures` listing only the messages that
failed. Without that, one bad message in a batch of five returns all five to
the queue, re-running four that already succeeded.

## 20.4 The outbox publisher

{{include:backend/src/handlers/workers.py:def outbox_handler}}

*Listing 20.2. The stream publisher.*

Three details worth noting.

**The attribute-value unpacking.** DynamoDB Streams delivers the low-level
format (`{"S": "value"}`), not plain Python. The `plain` helper converts it
including nested maps and lists.

**An unroutable event is marked dispatched.** An event type with no route would
otherwise sit pending forever and trigger the reconciliation alarm
indefinitely. It is logged as a warning and retired.

**A publish failure leaves the row pending.** That is the safe direction: the
event is still in the outbox and will be found, rather than lost.

## 20.5 The dispatcher fails loudly

{{include:backend/src/handlers/workers.py:def dispatcher_handler}}

*Listing 20.3. The dispatcher re-raises on failure.*

Most handlers absorb errors and report them. This one re-raises specifically so
the Lambda error metric increments and its alarm fires. A silently failing
dispatcher means emergency requests stop being matched while every other
indicator looks healthy — the worst failure mode in the system.

## 20.6 Maintenance isolates its steps

{{include:backend/src/handlers/workers.py:def maintenance_handler}}

*Listing 20.4. Independent steps.*

The expiry sweep, the reminder sweep and alert expiry are independent. One
failing must not prevent the others, so failures are collected and raised at
the end rather than aborting on the first.

<!-- pagebreak -->

# 21. Idempotency in Practice

## 21.1 Three outcomes, three behaviours

{{include:backend/src/repositories/platform_repo.py:def claim}}

*Listing 21.1. The claim, from `backend/src/repositories/platform_repo.py`.*

| Situation | Result | Why |
|---|---|---|
| No existing claim | Proceed | First execution |
| Claim is `COMPLETED` | Return the stored result | Do not repeat the side effect |
| Claim is `IN_PROGRESS`, recent | 409 `REQUEST_IN_PROGRESS` | A concurrent attempt is running |
| Claim is `IN_PROGRESS`, stale | Retake it | The previous attempt almost certainly died |
| Row vanished (TTL) between put and read | Treat as fresh | Avoid failing on a race with expiry |

*Table 21.1. Claim outcomes.*

The stale-claim window matters. Without it, a request whose Lambda was killed
mid-flight would block its own retry for a full 24 hours until TTL expiry.

## 21.2 Where keys come from

| Path | Key |
|---|---|
| Mutating REST request | Client `Idempotency-Key` header |
| Emergency request creation | Header, or a fingerprint of the request content |
| Queue consumer | `eventId` from the envelope |
| Notification send | A dedupe key naming the category and target |

*Table 21.2. Idempotency key sources.*

The emergency fingerprint is worth seeing because duplicate suppression there
must survive GPS jitter without suppressing genuinely different requests:

{{include:backend/src/services/emergency_service.py:def _fingerprint}}

*Listing 21.2. Request fingerprinting.*

<!-- pagebreak -->

# 22. Audit Logging

## 22.1 What is audited

Inventory changes and verification, organization approval and suspension,
hospital priority certification, donation verification, camp approval and
cancellation, emergency lifecycle transitions, account suspension, and role
changes.

## 22.2 The record

{{include:backend/src/repositories/platform_repo.py:def record}}

*Listing 22.1. Audit writing from
`backend/src/repositories/platform_repo.py`.*

Each record carries actor, role, action, resource type and id, organization,
correlation id, timestamp, and before/after images where meaningful.

## 22.3 Audit inside a transaction

For stock changes the audit record is written in the same transaction as the
change, via `build_item`, which constructs the record without writing it. A
stock change with no audit entry is therefore impossible, rather than merely
unlikely.

## 22.4 Querying

Two access patterns, no scan: by resource (`RESOURCE#<type>#<id>`) and by actor
(the `GSI1-actor` index). The admin endpoint requires one or the other and
refuses a bare request with an explanation, because "show me all audit records"
is a scan of the largest table in the system.

<!-- pagebreak -->

# 23. Testing Strategy

## 23.1 Two tiers with different jobs

| Tier | Count | Speed | What it proves |
|---|---|---|---|
| Unit | {{fact:test_unit}} | Under a second | Domain logic is correct in isolation |
| Integration | {{fact:test_integration}} | Seconds | The real datastore enforces the invariants |
| Frontend | {{fact:test_frontend}} | ~2 seconds | Presentation rules hold |

*Table 23.1. Test suites, measured on the run that produced this book.
Overall: {{fact:test_backend}} backend tests, {{fact:test_status}};
{{fact:test_total}} including the frontend suite.*

## 23.2 Why integration tests exist

Four real bugs were caught by integration tests that unit tests with fakes
would have passed:

| Bug | How a fake would have missed it |
|---|---|
| Unused expression placeholder | A fake ignores expression syntax entirely |
| Version conflict reported as `DuplicateError` | A fake does not evaluate conditions |
| Three further unused placeholders | Same |
| `None` stripped from expression values | A fake serialises differently or not at all |

*Table 23.2. Bugs found only by running against a real DynamoDB API surface.*

The second is the instructive one. A mock-based test asserting "raises on
conflict" would have passed, because the code did raise. It raised the wrong
error, so the retry path never engaged.

## 23.3 Determinism without clock patching

{{include:backend/tests/conftest.py:anchor:NOW = datetime:1}}

*Listing 23.1. The fixed instant from `backend/tests/conftest.py`.*

Because no domain function reads the clock, tests pass an instant and assert
exact boundaries:

{{include:backend/tests/unit/test_freshness_and_eligibility.py:anchor:@pytest.mark.parametrize:16}}

*Listing 23.2. Boundary testing of the freshness bands.*

Every boundary is tested from both sides: 6.0 hours is FRESH, 6.1 is AGING.

## 23.4 The integration fixture

{{include:backend/tests/integration/conftest.py:anchor:def aws(monkeypatch):16}}

*Listing 23.3. The mocked AWS environment.*

Tables are created from the same `create_table_kwargs` the local bootstrap
uses, so the test schema cannot drift from the real one.

## 23.5 Testing what the system refuses

A substantial share of the suite asserts refusals rather than successes:

{{include:backend/tests/integration/test_end_to_end_scenarios.py:def test_a_donor_cannot_verify_their_own_donation}}

*Listing 23.4. Testing a refusal. Note that the donor is deliberately granted
the verify role, so the test proves the rule holds even when the permission
does.*

## 23.6 The ten end-to-end scenarios

The specification names ten flows. Each has a test class named for it:

| # | Scenario | Test class |
|---|---|---|
| 1 | Staff add stock, public discovers it | `TestScenario01_StaffAddInventoryPublicDiscovers` |
| 2 | Stock becomes stale, presentation changes | `TestScenario02_StockBecomesStale` |
| 3 | Alert matches and notifies | `TestScenario03_AlertMatchTriggersNotification` |
| 4 | Register, check in, verify | `TestScenario04_CampRegisterCheckInVerify` |
| 5 | Impact credited exactly once | `TestScenario05_ImpactCreditedExactlyOnce` |
| 6 | Hospital certifies priority | `TestScenario06_HospitalCertifiesPriority` |
| 7 | Matching discovers facilities | `TestScenario07_MatchingDiscoversFacilities` |
| 8 | Responses do not double-count | `TestScenario08_ProviderResponsesDoNotDoubleCount` |
| 9 | Unauthorized action denied | `TestScenario09_UnauthorizedActionIsDenied` |
| 10 | Mapping failure does not break discovery | `TestScenario10_MappingFailureDoesNotBreakDiscovery` |

*Table 23.3. The ten scenarios and where to find them in
`backend/tests/integration/test_end_to_end_scenarios.py`.*

## 23.7 Frontend tests

{{include:frontend/src/test/StatusBadges.test.jsx:anchor:it('renders UNKNOWN as:5}}

*Listing 23.5. A presentation rule asserted as a test.*

The frontend suite tests the rules that are easy to regress during a redesign:
UNKNOWN never rendering as zero, freshness and verification always appearing
together, and error codes surviving into the UI.

<!-- pagebreak -->

# 24. Demo Data

## 24.1 What is seeded

| Entity | Count | Coverage |
|---|---|---|
| Organizations | 12 | Verified, pending and suspended |
| Users | 18 | Nine distinct roles, one suspended |
| Facilities | 8 | One with no inventory at all |
| Inventory batches | 200 | All 8 groups, all 4 components |
| Camps | 8 | All six lifecycle states |
| Registrations | 12 | Registered, checked in, no-show |
| Donations | 8 | Recorded and verified |
| Emergency requests | 10 | P1, P2, P3 and uncertified |
| Provider responses | 9 | Accepted, rejected, partial |
| Availability alerts | 5 | Active, cancelled, expired |

*Table 24.1. The synthetic dataset, as reported by the seeder.*

Freshness is spread deliberately: 50 fresh, 50 aging, 50 stale, 50 outdated.
Verification is split 66 verified against 134 unverified, so the distinction is
visible on screen rather than theoretical.

## 24.2 Properties the seeder guarantees

**Deterministic.** A fixed seed and fixed identifiers, so the demonstration is
reproducible and screenshots stay accurate.

**Idempotent.** Re-running produces the same state rather than duplicates.

**Validated.** `--validate` checks 24 coverage properties and reports each.

**Guarded.** Three independent checks refuse to run against anything that might
be production.

## 24.3 The validation output

```
[PASS] all 8 blood groups present  (8/8)
[PASS] all 4 components present  (4/4)
[PASS] quarantined stock present
[PASS] expired batches present  (17)
[PASS] near-expiry batches present  (16)
[PASS] fresh inventory present  (50)
[PASS] aging inventory present  (50)
[PASS] stale inventory present  (50)
[PASS] outdated inventory present  (50)
[PASS] facility with UNKNOWN inventory present  (1)
[PASS] all 6 camp lifecycle states present  (6/6)
[PASS] P1, P2 and P3 requests present
[PASS] partial stock response present
[PASS] suspended user present
[PASS] every record marked demoData
...
24/24 checks passed
```

*Listing 24.1. Actual output of `python scripts/seed_demo.py --validate`.*

## 24.4 Every record is marked

Three fields on every seeded item: `demoData: true`, `dataSource: SYNTHETIC`,
`environment: DEVELOPMENT`. The user interface shows a non-dismissible banner,
and individual records carry a "Synthetic record" pill.

## 24.5 The one place a scan is allowed

Wiping demo data scans every table looking for `demoData`. That is an offline
maintenance operation, not a user-facing path, and the function logs that it
performed a scan so the exception is visible rather than quiet.
