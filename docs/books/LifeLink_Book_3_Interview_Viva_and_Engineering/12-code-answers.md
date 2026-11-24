<!-- pagebreak -->

# 62. Answers Backed by the Actual Code

An interviewer who asks "show me" deserves code rather than description. These
are the eight listings worth being able to talk through line by line, each
extracted from the repository.

## 62.1 The rule that keeps unknown from becoming zero

{{include:backend/src/domain/inventory.py:anchor:if not inventory_known::12}}

*Listing 62.1. From `backend/src/domain/inventory.py`.*

**What to say about it.** The early return is the whole point. If the facility
has never reported, no aggregation runs at all — because aggregating an empty
list would produce zero eligible units and a state of `UNAVAILABLE`, which is
a claim the system is not entitled to make. The freshness is `UNKNOWN` for the
same reason: there is no update time to describe.

## 62.2 Eligibility that fails closed

{{include:backend/src/domain/eligibility.py:anchor:if expires_at is None::8}}

*Listing 62.2. From `backend/src/domain/eligibility.py`.*

**What to say about it.** Three branches, and the ordering matters. A missing
expiry is ineligible when expiry is required. An expiry earlier than the
collection date is flagged as *invalid* rather than merely expired, because
that is incoherent data a facility needs to fix. Only then is an ordinary
expiry check applied.

## 62.3 The conditional write

{{include:backend/src/repositories/inventory_repo.py:anchor:condition = Attr("version").eq(expected_version):8}}

*Listing 62.3. From `backend/src/repositories/inventory_repo.py`.*

**What to say about it.** Two conditions ANDed together. The version check
prevents a lost update. The units check prevents negative stock. The second is
redundant with the domain check that already ran, and that redundancy is
deliberate — between the read and the write, another request may have taken
the stock.

The `on_conflict="version"` argument is what makes the failure surface as a
retryable concurrency error rather than a duplicate.

## 62.4 The capacity transaction

{{include:backend/src/repositories/camp_repo.py:anchor:"ConditionExpression": (:8}}

*Listing 62.4. From `backend/src/repositories/camp_repo.py`.*

**What to say about it.** The condition is evaluated inside the transaction,
atomically with the write. Three clauses: the camp exists, it is under
capacity, and it is in a state that accepts registrations. Two simultaneous
requests for the final seat cannot both satisfy it.

## 62.5 Exactly-once credit

{{include:backend/src/repositories/camp_repo.py:anchor:"SK": f"LEDGER#{donation_id}":10}}

*Listing 62.5. From `backend/src/repositories/camp_repo.py`.*

**What to say about it.** The sort key *is* the idempotency mechanism. A
second verification of the same donation produces the same key, and
`attribute_not_exists(SK)` fails. There is no separate deduplication table and
no window in which a duplicate could slip through.

## 62.6 Priority aging that cannot overrule a clinician

{{include:backend/src/domain/emergency.py:anchor:base = PRIORITY_ORDER[clinical_priority]:14}}

*Listing 62.6. From `backend/src/domain/emergency.py`.*

**What to say about it.** The function reads `clinical_priority` and returns a
new value. It is pure — it cannot mutate anything, so it cannot write back.
The caller stores the result in a different field. The separation is
structural rather than a matter of discipline.

## 62.7 The authorization checks, in order

{{include:backend/src/appcore/auth.py:anchor:if not allow_anonymous and principal is ANONYMOUS::18}}

*Listing 62.7. From `backend/src/appcore/auth.py`.*

**What to say about it.** Four refusals before the handler is reached.
Anonymous on a protected route. Inactive account — placed before the
permission check so the error names the real reason. Missing permission.
Wrong organization, with the error deliberately not naming the owner.

## 62.8 Geohash cell coverage

{{include:backend/src/domain/geo.py:anchor:lat_cells = int(math.ceil:20}}

*Listing 62.8. From `backend/src/domain/geo.py`.*

**What to say about it.** The loop walks the bounding box of the search circle
in cell-sized steps. The intersection test discards corner cells that cannot
contain an in-range point. The hard ceiling on cell count is defensive: the
precision tiers keep the real figure well under it, so tripping it means a
tier was mis-sized rather than that a user asked for something unreasonable.

<!-- pagebreak -->

# 63. Tests Worth Quoting

Showing a test is often more persuasive than describing a behaviour.

## 63.1 The suspended-account test

{{include:backend/tests/unit/test_authorization.py:anchor:def test_suspended_account_is_blocked_despite_valid_token_and_role:14}}

*Listing 63.1. From `backend/tests/unit/test_authorization.py`.*

**Why it is the one to show.** Everything about the caller is correct except
the account status. A system that trusts token claims cannot pass this, and
the docstring says exactly why.

## 63.2 The self-verification test

{{include:backend/tests/unit/test_camps_and_impact.py:anchor:def test_being_staff_does_not_permit_self_verification:10}}

*Listing 63.2. From `backend/tests/unit/test_camps_and_impact.py`.*

**Why it is the one to show.** It grants the verifier the staff role
deliberately, so the test proves the rule holds even when the permission does.

## 63.3 The boundary table

{{include:backend/tests/unit/test_freshness_and_eligibility.py:anchor:(6.0, FreshnessLabel.FRESH):4}}

*Listing 63.3. From `backend/tests/unit/test_freshness_and_eligibility.py`.*

**Why it is the one to show.** Every boundary tested from both sides. This is
only possible because time is injected rather than read.

## 63.4 The coverage property

{{include:backend/tests/unit/test_geo_coverage.py:anchor:missed = []:12}}

*Listing 63.4. From `backend/tests/unit/test_geo_coverage.py`.*

**Why it is the one to show.** It asserts a property across every bearing at
ten radii rather than sampling three cases someone thought of. The failure
message names the bearings that were missed.

## 63.5 The no-double-counting test

{{include:backend/tests/unit/test_emergency.py:anchor:def test_two_providers_accepting_do_not_reserve_the_same_units:14}}

*Listing 63.5. From `backend/tests/unit/test_emergency.py`.*

**Why it is the one to show.** The comment explains that double-counting is
structurally impossible rather than merely avoided, which is a stronger claim
and the one the design actually supports.

<!-- pagebreak -->

# 64. If You Have Five Minutes to Prepare

Read this page.

## 64.1 The pitch

A cloud platform for blood availability, discovery, donation and emergency
coordination. Seven features. React, Python on Lambda, DynamoDB, in one AWS
region. {{fact:test_backend}} backend tests passing. Deployed, with the
repository ahead of the deployed stack, and the documentation says so.

## 64.2 The five rules

Unknown is not zero. Updated is not verified. An offer is not a reservation.
Dispatch order is not clinical priority. Fail closed.

## 64.3 The bug

Geohash search queried the centre cell and its eight neighbours, which covers
about fifteen kilometres. A thirty-kilometre search silently missed a facility
25.6 kilometres away. Found by integration tests with real distances. Fixing
coverage caused a 2,107-query search, which needed a third precision tier.
Tests now assert both coverage and bounded fan-out.

## 64.4 The constraint

Lambda concurrency is {{fact:lambda_concurrency}}, not
{{fact:lambda_concurrency_default}}. No reserved concurrency, capped consumer
parallelism, one scheduled dispatcher rather than per-priority consumers, and
throttling treated as expected rather than exceptional.

## 64.5 The weakness

The blood compatibility reference has not been clinically reviewed. It is
marked `UNREVIEWED_SYNTHETIC`, the loader refuses to start without a review
status, and every response carries the disclaimer. That is the gap that
matters most, and it is a process gap rather than an engineering one.

## 64.6 The closing line

> The hard part was not the AWS. It was deciding, repeatedly, what the system
> should refuse to claim.
