<!-- pagebreak -->

# 20. Scenario Questions: Inventory and Concurrency

Thirty scenario questions across Chapters 20 to 25. Each describes a situation
and asks what the system does, and why.

**S1. Two staff members deduct the last unit at the same moment.**

Both read version 7 with one unit available. Both compute a new state. The
first write commits and moves the row to version 8. The second fails its
condition — version 7 no longer matches, and `availableUnits >= 1` would also
fail — and returns 409 `CONCURRENT_MODIFICATION`. The service re-reads, finds
zero units, and the domain layer raises `INSUFFICIENT_STOCK`. The second user
is told there is no stock, which is true.

**S2. An external hospital feed sends an update that is six hours old.**

Rejected with `STALE_UPDATE_REJECTED`, naming both the source timestamp and
the current `lastUpdatedAt`. A delayed update must not overwrite newer state,
and silently applying it would move a correct figure backwards.

**S3. The same feed sends an update with no timestamp at all.**

Also rejected, and treated as stale. A system that cannot say when it read the
stock does not get to overwrite a known-newer value.

**S4. A batch's expiry date is earlier than its collection date.**

Eligibility reports `INVALID_EXPIRY_DATE`, distinct from `BATCH_EXPIRED`. That
is incoherent data rather than old stock, and conflating them would hide a
data-quality problem the facility needs to fix.

**S5. A batch has no expiry date.**

Ineligible, with `MISSING_EXPIRY_DATE`. Creation refuses outright. The
specification is explicit that missing required dates must not silently produce
eligible stock.

**S6. Staff release a quarantined batch that expired while held.**

It transitions to `EXPIRED`, not `AVAILABLE`. Clearing a quarantine flag must
not resurrect stock that aged out during the hold.

**S7. The expiry sweep has not run for two hours.**

Nothing is wrong. Eligibility excludes anything past its expiry regardless of
stored status, so correctness never depends on the sweep. The sweep is
bookkeeping that makes the stored status agree with reality.

**S8. A facility has never reported inventory.**

Every cell of its availability matrix reads `UNKNOWN` with no unit count. No
inventory query runs at all, because querying and finding nothing would produce
`UNAVAILABLE`, which claims something the system does not know.

**S9. A facility reports it has zero O-negative.**

`UNAVAILABLE` with an explicit zero. Different from S8, rendered differently,
and leading a user to a different action.

**S10. An automated feed updates a batch every minute and nobody checks it.**

Freshness reads Fresh; verification reads Not verified. Both badges appear
together. That pairing is the single most important presentation rule in the
system.

<!-- pagebreak -->

# 21. Scenario Questions: Camps and Donors

**S11. Two donors claim the final seat simultaneously.**

Both pass the advisory capacity check. The transaction decides: one commits the
registration and the counter increment; the other's condition
`registeredCount < capacity` fails and the whole transaction is cancelled. The
second donor gets `CAPACITY_EXCEEDED`.

**S12. A donor registers twice.**

The conditional put on `REG#<userId>` fails and returns `DUPLICATE`. The
service also pre-checks so the message is friendly, but the condition is what
makes it impossible.

**S13. A camp is cancelled after fifty people registered.**

Cancellation transitions the camp and notifies every registered donor in the
same operation, with duplicate suppression keyed per camp and user. The
response reports how many were notified against how many were registered.

**S14. A reminder was scheduled for a camp that has since been cancelled.**

Not sent. The sweep re-checks camp status, registration status, notification
preference, consent, prior sends and schedule validity at send time, not at
schedule time.

**S15. The reminder job runs five hours late.**

Nothing is sent for that window. The schedule-drift tolerance refuses to emit
"starts in 2 hours" about something that started three hours ago.

**S16. A camp organizer donates at their own camp and tries to verify it.**

Refused with `SELF_VERIFICATION_FORBIDDEN`. They hold the permission; the
service checks `verifier_id != donor_id` independently of the permission
matrix. There is a test that grants the donor the staff role specifically to
prove this.

**S17. A donation verification event is delivered twice.**

The first commits the status change and the ledger entry. The second finds the
donation already `VERIFIED` and raises `INVALID_STATE_TRANSITION`; even if it
somehow reached the transaction, the ledger row's `attribute_not_exists`
condition would fail.

**S18. A donor's impact score disagrees with their ledger.**

The ledger wins. The score is always derived by summing ledger entries, so
recalculation is a read rather than a repair.

**S19. Staff try to record a donation for someone who never checked in.**

Refused with `ATTENDANCE_REQUIRED`. The four states are sequential, and each
step requires the previous one.

**S20. A donor who donated three weeks ago registers again.**

Registration succeeds — LifeLink does not block it — and the response carries
interval advice saying only twenty-one days have passed against a usual minimum
of ninety, and that they should speak to camp staff. The system reports elapsed
time; it does not assess fitness to donate.

<!-- pagebreak -->

# 22. Scenario Questions: Emergency Coordination

**S21. A hospital is suspended between raising a request and certifying it.**

Certification is refused with the organization status named. Verification is
re-checked at the moment of certification rather than cached from when the
request was created.

**S22. A hospital is suspended while its request is being matched.**

The dispatcher checks the requesting organization's status, halts matching,
and records a `MATCHING_HALTED_ORG_SUSPENDED` event against the request.

```diagram
type: flow
title: What aging changes and what it does not
node cert Hospital certifies clinical priority P3 style=domain
node store Stored in clinicalPriority immutable by the scheduler style=data
node wait Request waits sixty minutes style=external
node age Scheduler recomputes effectivePriority to P1 style=aws
node order Dispatched ahead of newer work style=domain
node same clinicalPriority is still P3 and is shown as such style=domain
```

*Figure 22.1. Aging moves dispatch order only. The clinical judgement is
untouched.*

**S23. A P3 request has been waiting an hour while P1 traffic continues.**

Aging has promoted its *effective* priority to the top band — one band per
fifteen minutes. Its *clinical* priority is still P3 and is unchanged. The
tracking page states both and explains that only the scheduling order moved.

**S24. Two providers each accept, each offering four units, for a request
needing four.**

Both offers are recorded in full. The tally reports two accepted and eight
units offered. Nothing is netted, because they may be describing the same
physical units, and nothing is reserved. The interface says so explicitly.

**S25. A provider accepts, but the stock has gone.**

The acceptance is refused. Stock is revalidated before an acceptance is
recorded, and the error names `STOCK_REVALIDATION_FAILED` with the current
eligible count.

**S26. A provider responds twice.**

The second fails the condition requiring the response row to still be
`AWAITING_RESPONSE`, and surfaces as a concurrency conflict rather than being
silently accepted.

**S27. An organization that was never notified tries to respond.**

Refused with `PROVIDER_NOT_NOTIFIED`. The placeholder row created at
notification time is what the submission conditions on, so a provider with no
row cannot respond at all.

**S28. A provider responds after the request was cancelled.**

Refused, because responses are rejected for requests in a terminal state. The
transition table has no edge out of `CANCELLED`.

**S29. The compatibility table has no entry for the requested combination.**

No candidates are returned, a `NO_COMPATIBILITY_REFERENCE` event is recorded,
and the response explains that no match was attempted — deliberately, because
the system does not infer compatibility. The rules version and review status
are included.

**S30. An O-negative patient needs red cells and the only nearby stock is A+.**

No match. O-negative recipients may receive only O-negative red cells. The
matching engine queries only compatible donor groups, so the A+ stock is never
considered, and there is a test asserting exactly this.

<!-- pagebreak -->

# 23. Ten Debugging Exercises

Each exercise gives a symptom. Work out the cause before reading on.

**D1. Every write to one table fails with `ValidationException` and no useful
detail.**

*Cause.* An expression attribute value is declared but not referenced by the
expression — or referenced but not declared. DynamoDB rejects the whole request
and does not name the placeholder.

*How to find it.* Compare the placeholders in the update expression with the
keys of `ExpressionAttributeValues`. In this project a script was written to
scan every repository method for the mismatch, which found three more
instances.

*Underlying bug here.* `None` values were being stripped from expression values
by a serialiser intended for items, where dropping null is correct.

**D2. A concurrent update returns "a record with this identity already exists".**

*Cause.* The condition failure is being translated to the wrong error. A
version check and a uniqueness check both raise
`ConditionalCheckFailedException`, and the code assumed the latter.

*Why it matters.* The retry path catches `ConcurrentModificationError`, so it
never engaged, and the user was told something untrue.

*Fix.* An explicit parameter saying what a condition failure means on each
call site.

**D3. A facility twenty-six kilometres away never appears in a thirty-kilometre
search.**

*Cause.* The geohash query covers only the centre cell and its eight
neighbours, which spans less than thirty kilometres at that precision.

*How to find it.* Seed data with known distances and assert against them. The
symptom is silence, so nothing surfaces without an expectation to violate.

**D4. After fixing D3, searches become very slow.**

*Cause.* Covering the full bounding box at the same precision produced 2,107
cell queries for a hundred-kilometre radius.

*Fix.* A coarser precision tier for large radii, boundaries retuned by
measurement, and a test asserting a bounded query count.

**D5. Camp reminders never arrive, but every reminder unit test passes.**

*Cause.* The sweep queries an index the camp was never written into. The
decision function is correct; the camp is not in the result set.

*Lesson.* Testing the decision is not testing the query that feeds it.

**D6. A component re-renders in an infinite loop.**

*Cause.* `setState` called during render rather than in an effect. The state
change re-renders, the condition still holds, and it sets state again.

*Fix.* Move it into `useEffect` with the right dependencies.

**D7. A search shows stale results after the user changes a filter.**

*Cause.* An earlier slow request resolved after a later fast one and
overwrote it.

*Fix.* An `AbortController` per request, cancelled when dependencies change.

**D8. The PDF build produces malformed output with unbalanced tags.**

*Cause.* Successive regex substitutions, where a later pass matches markup
inserted by an earlier one. A colour code like `'#7a0f1d'` looks exactly like a
string literal.

*Fix.* A single tokenising pass instead of chained substitutions.

**D9. A code listing in the documentation shows the wrong code entirely.**

*Cause.* The include was by line number, and an unrelated edit above the range
shifted it.

*Fix.* Anchor-based selectors that locate content by text, plus a build warning
on any remaining line-number include.

**D10. `import platform` resolves to the application package and breaks boto3.**

*Cause.* A package named `platform` on `sys.path` shadows the standard library
module that botocore imports.

*Fix.* Rename. The lesson is to check a package name against the standard
library before anything depends on it.

<!-- pagebreak -->

# 24. Ten Architecture Trade-off Discussions

Each is a decision where the alternative was genuinely defensible.

**T1. Eleven tables versus one.** Query efficiency against IAM-enforceable
isolation. Chose isolation; pay two calls for cross-domain reads.

**T2. Application dispatcher versus priority queues.** Simplicity against
correctness. Three queues do not produce priority ordering, so the apparently
simpler option does not actually work.

**T3. One Lambda versus fifty.** IAM granularity against cold starts and
concurrency. At a ceiling of ten, fifty functions would be harmful.

**T4. Optimistic concurrency versus atomic counters.** Simplicity against
expressiveness. A counter cannot say "never below zero" and loses the audit
pre-image.

**T5. Transactional outbox versus write-then-publish.** Cost against
durability. Double writes on event paths, in exchange for events that cannot
be lost.

**T6. Compatibility as data versus code.** Indirection against reviewability.
Swapping in a clinically reviewed table becomes a data change with a version
bump.

**T7. Facility-scoped reservations versus none at all.** Holding real supply
against the risk of holding it for someone who never arrives. Resolved by
scoping a hold to one facility — so no distributed lock is needed — and by
capping and actively expiring every hold.

**T8. HTTP API versus REST API.** Features against cost and latency. Nothing
in LifeLink needs a REST-only feature.

**T9. Server-side authorization versus a gateway authorizer.** One database
read per request against the ability to check account status and ownership.

**T10. moto versus DynamoDB Local.** Fidelity against availability. The Java
archive could not be downloaded; moto needs no download and the application
code is identical either way.

<!-- pagebreak -->

# 25. Twenty-Five Viva Questions

Short questions with short answers, of the kind asked rapidly in an oral
examination.

| # | Question | Answer |
|---|---|---|
| V1 | How many blood groups does the system support? | Eight |
| V2 | How many components? | Four |
| V3 | What is the Fresh threshold? | Six hours since update |
| V4 | What makes stock ineligible? | Expired, quarantined, withdrawn, zero units, or missing/invalid expiry |
| V5 | Who may certify clinical priority? | Hospital authorizer or hospital admin only |
| V6 | What is the default notification radius? | 10 km, extensible to 20 km |
| V7 | Does the radius limit camp search? | No. It limits notifications only |
| V8 | Points per verified donation? | 100 |
| V9 | Milestone thresholds? | 1, 3, 5, 10 verified donations |
| V10 | Can a donor verify their own donation? | No, enforced in the service layer |
| V11 | Which database? | DynamoDB, {{fact:table_count}} tables |
| V12 | How many secondary indexes? | {{fact:gsi_count}} |
| V13 | How many API routes? | {{fact:route_count}} |
| V14 | How many permissions? | {{fact:permission_count}} across {{fact:role_count}} roles |
| V15 | Which region? | {{fact:aws_region}} |
| V16 | Lambda runtime? | {{fact:lambda_runtime}} on arm64 |
| V17 | Lambda concurrency limit on this account? | {{fact:lambda_concurrency}} |
| V18 | Why no reserved concurrency? | It subtracts from a pool of ten |
| V19 | How is a lost update prevented? | Conditional write on a version attribute |
| V20 | How is a camp prevented from oversubscribing? | A two-item DynamoDB transaction |
| V21 | What is the outbox pattern for? | Writing a domain change and its event atomically |
| V22 | What delivery guarantee does SQS give? | At least once |
| V23 | How many alarms are defined? | {{fact:cfn_alarms}} |
| V24 | Is SMS implemented? | No. Blocked by SCP and account plan; it raises `CHANNEL_UNAVAILABLE` |
| V25 | Has it been deployed? | No. The template is validated only |

*Table 25.1. Rapid-fire viva questions.*
