<!-- pagebreak -->

# 11. Intermediate Questions: Security

**I21. Where is authorization enforced?**

In one decorator, `@requires`, applied to every protected handler. Nothing else
performs authorization, so the rules live in one reviewable place and a route
that forgets to declare a permission fails a build-time audit rather than
silently going public.

**I22. What order are the checks in, and why?**

Token signature and claims; load the principal from the database; reject if the
account is not active; check the permission; compare the resource's owning
organization with the caller's. Account status comes before permission so a
suspended administrator gets `ACCOUNT_SUSPENDED` rather than a confusing
`FORBIDDEN` — the error should name the real reason.

**I23. Why read roles from the database rather than the token?**

Because a token is a snapshot. A role revoked thirty seconds ago would still
work for the remaining fifty-nine minutes of the token's life. Reading from the
database means a change takes effect on the very next request.

**I24. What is the cost of that?**

One read per request. It is mitigated by a short in-process cache with a
thirty-second TTL, which bounds the staleness explicitly rather than
accidentally.

**I25. Why not use an API Gateway JWT authorizer alone?**

It validates the token but knows nothing about account status or resource
ownership. It would happily admit a suspended user with a valid token. It is a
sensible outer layer but cannot be the only one.

**I26. How is an insecure direct object reference prevented?**

The ownership comparison lives in the decorator, not the handler. A handler
declares *how* to find the owning organization of the resource it touches —
`resource_owner=_facility_owner` — and the decorator does the comparison. A
handler author cannot forget a check they do not perform.

**I27. What does the cross-organization error say?**

"This resource belongs to another organization", without naming which one.
There is a test asserting the other organization's identifier appears in
neither the message nor the details, because an error message is an
information-disclosure channel.

**I28. How are audit records protected?**

The Lambda execution role is granted `PutItem` and `Query` on the audit table —
no `UpdateItem`, no `DeleteItem`. The application physically cannot rewrite
history. That is tamper *resistance*, not immutability: an account
administrator with sufficient IAM privileges could still alter it, and the
documentation says so rather than overclaiming.

**I29. How are logs prevented from leaking personal data?**

Redaction by key name at any nesting depth, applied by the formatter rather
than by each caller. The redacted set includes passwords and tokens, and also
email, phone, coordinates and date of birth — personal data that accumulates in
logs without anyone deciding it should.

**I30. What is PKCE and why is it used?**

Proof Key for Code Exchange. A browser cannot keep a client secret, so instead
it generates a random verifier, sends its hash with the authorization request,
and presents the verifier when exchanging the code. An intercepted
authorization code is useless without the verifier.

<!-- pagebreak -->

# 12. Intermediate Questions: Geospatial and Search

**I31. How does geospatial search work?**

Geohash encodes a latitude and longitude into a string where a shared prefix
means geographic proximity. Facilities store geohashes at three precisions,
each indexed. A search computes which cells cover the circle, queries those
cells, and then filters by exact Haversine distance.

**I32. Why not just compute distance for every facility?**

That is a scan. The geohash prefix is what makes proximity an indexed key query
rather than a full table read.

**I33. Why three precisions?**

Cell size must be comparable to the search radius. Too fine means many queries;
too coarse means reading far more candidates than needed. Precision 6 for up to
three kilometres, 5 up to twenty, 4 beyond that — each backed by its own index.

**I34. How were those boundaries chosen?**

By measurement. A five-kilometre search at precision 6 needed 195 cell queries;
a hundred-kilometre search at precision 5 needed 2,107. Both were untenable,
especially at a Lambda concurrency ceiling of {{fact:lambda_concurrency}}. The
boundaries were moved until the worst case in every tier stayed under a
documented limit.

**I35. Why query neighbouring cells at all?**

Because a facility five hundred metres away can be in an adjacent cell. The
original implementation queried only the centre cell and its eight neighbours,
which is correct only while the radius is smaller than one cell — and silently
wrong beyond that.

**I36. How is the coverage property tested?**

By walking the circle at the search radius in five-degree steps and asserting
every bearing's cell is in the set, at ten different radii. Boundary points are
the hardest case and the ones the original code got wrong.

**I37. How are facilities ranked?**

Availability 30%, freshness 20%, distance 20%, quantity 15%, verification 15%.
The weights are configurable and validated to sum to 1.0. Every result carries
its component contributions and a human-readable explanation.

**I38. Can ranking surface expired stock?**

No. Eligibility is a hard filter applied while building the candidate list;
ranking only reorders survivors. No weighting, however tuned, can promote
something that never entered the list.

**I39. How does unknown availability rank?**

It scores zero on the availability axis — correctly, since it is not confirmed
supply — but the state travels to the response unchanged, so the interface
renders it as "not reported" rather than as unavailable.

**I40. Why is ranking deterministic?**

Ties break on distance, then on facility id. Without the final tie-break, two
facilities with identical scores could order differently between calls, which
makes results irreproducible and tests flaky.

<!-- pagebreak -->

# 13. Advanced Questions: Distributed Systems

Forty advanced questions across Chapters 13 to 18.

**A1. Why can you not have exactly-once delivery?**

Because the acknowledgement can be lost. If a consumer processes a message and
the acknowledgement fails, the broker cannot distinguish "processed but not
acknowledged" from "never processed", so it must redeliver. The achievable
property is at-least-once delivery with idempotent processing, which composes
to effectively-once *effects*.

**A2. What is the outbox pattern solving precisely?**

The dual-write problem. Two systems — a database and a message broker — cannot
be updated atomically without distributed transactions. The outbox turns two
writes into one by putting the message in the same database transaction, then
relays it asynchronously.

**A3. What does the outbox not solve?**

Ordering across aggregates, and duplicate publication. The relay may publish
the same row twice if it dies after sending but before marking it dispatched.
That is why consumers are idempotent.

**A4. How would you handle event ordering if it mattered?**

DynamoDB streams preserve order within a partition key. If strict ordering were
required per aggregate, the outbox partition key would be the aggregate id
rather than the event id. LifeLink does not need it: every consumer is
order-independent, which is a stronger property than being correctly ordered.

**A5. Explain eventual consistency in this system.**

Global secondary indexes are always eventually consistent. A write visible in
the base table may not yet appear through an index. LifeLink handles it three
ways: ignore it where it does not matter, use a strongly consistent base-table
read where it does, and let idempotency absorb it where it could cause
duplicate work.

**A6. Give a concrete example of the third.**

The dispatcher reads pending requests from an index. It may see a request it
already picked up in the previous cycle. That is harmless because the work is
idempotent and the status transition is conditional — the second attempt finds
the status has moved and does nothing.

**A7. What is the CAP trade-off here?**

DynamoDB chooses consistency and partition tolerance for base-table reads with
`ConsistentRead`, and availability for index reads. LifeLink leans on that
split deliberately: decisions that must not be stale use consistent base reads;
browsing uses indexes.

**A8. How do you prevent a hot partition?**

By choosing partition keys that distribute. The expiry sweep is the natural
hazard — "all batches expiring before now" wants one key — so it is sharded
across ten partitions by a hash of the batch id, each swept independently.

**A9. What is optimistic concurrency and when is it the wrong choice?**

Reading a version, computing a change, and writing conditionally on the version
being unchanged. It is wrong under high contention on a single item, where most
attempts fail and the retry traffic dominates. LifeLink's contention is low —
two staff editing one batch — so it is appropriate.

**A10. What would you use instead under high contention?**

Either a different data model that spreads the contention, or a queue that
serialises updates to the hot item. For stock on a single batch, the first is
usually better: if one batch is contended, the batch granularity is probably
wrong.

<!-- pagebreak -->

# 14. Advanced Questions: Scheduling and Fairness

**A11. Why do three SQS queues not give you priority?**

Because three event source mappings are three independent consumers. Nothing
coordinates them. Lambda will run the low-priority consumer while high-priority
messages wait, because each mapping polls its own queue on its own schedule.

**A12. Could you make it work with reserved concurrency?**

Partially, by starving the lower-priority consumers of concurrency. It is
fragile — the proportions have to be tuned and retuned — and on this account
impossible, because reserved concurrency is subtracted from a pool of
{{fact:lambda_concurrency}}.

**A13. How does the application-level dispatcher work?**

One function on a one-minute schedule reads pending work from an index sorted
by effective priority then creation time, recomputes aging, and processes a
bounded batch.

**A14. What is priority aging?**

Raising a long-waiting item's dispatch priority: one band per fifteen minutes
waited. It prevents starvation of the lowest band under sustained high-priority
load.

**A15. Why is aging dangerous in a clinical context, and how is that handled?**

Because promoting a Scheduled request to Critical, if those are the same field,
overrules a doctor. LifeLink stores two fields: `clinicalPriority`, written
only by the certification endpoint, and `effectivePriority`, written only by
the scheduler. A test asserts aging leaves the clinical priority unchanged.

**A16. What is the cost of the scheduler design?**

Up to sixty seconds of latency, and a single point of failure. The first is
acceptable for a workflow whose next steps are human and take minutes; a P1
request also triggers an out-of-band dispatch. The second is covered by an
alarm, and the handler deliberately re-raises on failure so the alarm fires.

**A17. How would you scale the dispatcher?**

Shard by region or by priority band with a coordinator, or move to a workflow
engine like Step Functions. At current volume neither is justified, and the
specification asks that Step Functions be used only where the value justifies
the complexity.

**A18. What is deadline-driven promotion?**

A request due within thirty minutes sorts as highest priority regardless of
band. It is scheduling, not clinical judgement, and it writes the same
scheduler-owned field.

**A19. How do you prevent the dispatcher processing the same request twice?**

Status transitions are conditional on the current status. Two overlapping
dispatcher runs mean one condition fails.

**A20. What happens to a request whose deadline passes mid-workflow?**

The dispatcher checks on each cycle and transitions it to `EXPIRED`. Providers
can no longer respond, because responses are refused for closed requests.

<!-- pagebreak -->

# 15. Advanced Questions: Data Modelling

**A21. Walk through designing the inventory access pattern.**

The question is "what eligible stock of group G, component C does facility F
have?" A naive design queries all batches at F and filters. Better: an index
keyed on `FACILITY#F#G#C` so the partition is already narrowed. Best: add
status and expiry to the sort key so a range condition excludes ineligible rows
during the read rather than after it.

**A22. Why `INCLUDE` rather than `ALL` or `KEYS_ONLY` on that index?**

`KEYS_ONLY` would force a base-table read per batch to get the unit count.
`ALL` would duplicate every attribute including audit metadata nobody reads on
that path. `INCLUDE` with the seven attributes the aggregation needs is the
smallest index that answers the question in one query.

**A23. How do you model a one-to-many relationship in DynamoDB?**

Share a partition. A camp's metadata, registrations and staff all live under
`CAMP#<id>` with different sort key prefixes, so one query returns the lot.
That is single-table design applied within a bounded context.

**A24. How does pagination work, and why cursors?**

Cursor-based: an opaque base64 encoding of DynamoDB's `LastEvaluatedKey` plus a
fingerprint of the query. Offset pagination would require reading and
discarding rows — a scan in disguise. The fingerprint means a cursor presented
against a different query is rejected rather than silently returning the wrong
result set.

**A25. Why does the audit table use a customer-managed KMS key?**

Because key usage is logged in CloudTrail. Anyone decrypting audit records
leaves a trace in a place they do not control through the application.

**A26. Which tables have no point-in-time recovery, and why?**

Idempotency, notifications and outbox. All are TTL-bound and reconstructible.
PITR on them would be spend with no recovery value, and leaving it off is a
decision rather than an oversight.

**A27. How does TTL interact with correctness?**

TTL deletion is eventual — AWS makes no promise about timing. Nothing in
LifeLink depends on a TTL having fired. Alert expiry is checked explicitly at
match time; TTL only reclaims storage.

**A28. What happens if a transaction exceeds its item limit?**

`TransactWriteItems` allows a hundred items. LifeLink's largest transaction is
three. If a future requirement needed more, the right answer would be to
reconsider the aggregate boundary rather than to batch transactions.

**A29. How would you migrate the schema?**

Additive changes are free — DynamoDB is schemaless per item. A breaking change
would need dual-writing both shapes, backfilling, switching reads, then
removing the old shape. The per-context tables limit a migration's blast radius
to one domain.

**A30. What is the biggest weakness of this data model?**

Dashboard aggregates are computed per request. At real scale that becomes slow,
and the correct answer is a materialised read model updated from the event
stream. It is recorded as future work rather than described as if it exists.
