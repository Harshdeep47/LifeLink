<!-- pagebreak -->

# 31. Request Validation

## 31.1 Validation happens in three places, for three reasons

| Layer | Validates | Purpose |
|---|---|---|
| Frontend form | Shape, ranges, required fields | Immediate feedback; never trusted |
| Handler | Types, presence, parseability | Reject malformed input before any work |
| Domain and service | Business rules and invariants | The authoritative decision |

*Table 31.1. Three validation layers.*

The frontend layer exists purely for user experience. Every rule it enforces is
enforced again server-side, because a form is a suggestion.

## 31.2 Parsing helpers that fail usefully

{{include:backend/src/handlers/router.py:def require_int}}

*Listing 31.1. Parameter parsing from `backend/src/handlers/router.py`.*

A missing required parameter and an unparseable one produce different messages,
both naming the parameter. "Invalid request" tells a client developer nothing.

## 31.3 Timestamps are validated, not coerced

{{include:backend/src/handlers/router.py:def parse_iso_param}}

*Listing 31.2. Timestamp parsing at the edge.*

A string without a timezone designator is rejected. Assuming UTC would be a
five-and-a-half-hour error for an Indian deployment, and the kind that makes
expired stock look fresh.

## 31.4 Domain validation returns reasons

Business validation does not return booleans. `evaluate_batch_eligibility`
returns every reason a batch is ineligible; `can_register` returns a named
reason code. Both let the interface explain rather than merely refuse.

<!-- pagebreak -->

# 32. Organization Isolation in Depth

## 32.1 Three layers of scoping

**IAM.** Each background function can reach only its own domain's tables.

**The decorator.** Organization-scoped permissions trigger an ownership
comparison before the handler runs.

**The service.** Where ownership is more subtle than "same organization",
services check explicitly — camp staff scoped to a specific camp, for example.

{{include:backend/src/services/camp_service.py:def _assert_camp_staff}}

*Listing 32.1. Camp-level scoping from
`backend/src/services/camp_service.py`.*

Being camp staff is not enough; the specification requires staff to be scoped
to the camps they are assigned to, so membership of that camp is checked.

## 32.2 Which permissions are global

{{include:backend/src/appcore/rbac.py:anchor:GLOBAL_PERMISSIONS:18}}

*Listing 32.2. Global permissions from `backend/src/appcore/rbac.py`.*

Public reads are global because there is no owning organization to compare
against. Administrative actions are global because verifying an organization is
inherently cross-organizational.

Everything else is scoped, and the decorator enforces it without the handler's
participation.

## 32.3 The test that pins it

{{include:backend/tests/unit/test_authorization.py:def test_cross_organization_error_does_not_leak_owner}}

*Listing 32.3. The error must refuse without disclosing.*

<!-- pagebreak -->

# 33. Expiry and Freshness Logic

## 33.1 Three separate questions

| Question | Function | Depends on |
|---|---|---|
| Can this stock be offered? | `evaluate_batch_eligibility` | Status, units, expiry, now |
| How recent is this figure? | `freshness_label` | `lastUpdatedAt`, now |
| Has a person confirmed it? | `verification_status` | `lastVerifiedAt`, now |

*Table 33.1. Three questions, three functions, no shared state.*

Keeping them separate is what prevents the conflation the specification warns
about. A single `get_status()` returning a blended verdict would invite callers
to render one thing.

## 33.2 Near expiry is a flag, not a state

{{include:backend/src/domain/eligibility.py:def is_near_expiry}}

*Listing 33.1. Near-expiry detection.*

Near-expiry stock is still eligible — it can be used. The flag lets staff
prioritise it and lets the interface warn, without removing it from
availability, which would understate real supply.

Note the `0 <` in the comparison: already-expired stock is not "near expiry",
it is expired, and eligibility already handles it.

## 33.3 Expiry transitions are bookkeeping

The scheduled sweep transitions expired batches to `EXPIRED`. This is
**not** a correctness guard — eligibility already excludes anything past its
expiry regardless of status. The sweep makes the stored status agree with
reality so dashboards and audit trails read sensibly.

That ordering matters: correctness never depends on a scheduled job having run.

<!-- pagebreak -->

# 34. Geospatial Filtering

## 34.1 Encoding

{{include:backend/src/domain/geo.py:def encode_geohash}}

*Listing 34.1. Geohash encoding from `backend/src/domain/geo.py`.*

Standard base-32 geohash: interleaved longitude and latitude bits, five bits
per character. A shared prefix means geographic proximity, which is what makes
a prefix query a proximity query.

## 34.2 Choosing a precision

{{include:backend/src/domain/geo.py:def choose_precision}}

*Listing 34.2. Precision tiers.*

The docstring records the measured numbers that produced these boundaries,
including the two failures that forced the design. Writing "5 km uses precision
6" without saying that the naive boundary needed 195 queries would leave the
next person to re-derive it.

## 34.3 Covering the search circle

{{include:backend/src/domain/geo.py:def search_cells}}

*Listing 34.3. Cell coverage.*

Two properties, both tested. The cell set is a **superset** of the search
circle, so no in-range facility is missed. And cells whose nearest corner lies
outside the radius are skipped, because they cannot contain an in-range point
and querying them is pure waste.

## 34.4 The property test

{{include:backend/tests/unit/test_geo_coverage.py:def test_cell_set_covers_every_point_on_the_radius_boundary}}

*Listing 34.4. Coverage asserted as a property, from
`backend/tests/unit/test_geo_coverage.py`.*

Walking the circle at the search radius and checking every bearing's cell is in
the set. Boundary points are the hardest case and the ones the original
implementation got wrong.

<!-- pagebreak -->

# 35. Ranking Implementation

## 35.1 Weights are validated

{{include:backend/src/domain/ranking.py:class RankingWeights}}

*Listing 35.1. Weight validation from `backend/src/domain/ranking.py`.*

Weights that do not sum to 1.0 produce scores that are not comparable between
searches. The constructor refuses rather than silently normalising, because
silent normalisation would hide a configuration mistake.

## 35.2 Unknown scores zero without becoming zero

```python
AvailabilityState.UNAVAILABLE: 0.0,
# UNKNOWN scores zero on this axis but is NOT treated as "none in stock";
# the state itself is carried through to the response untouched.
AvailabilityState.UNKNOWN: 0.0,
```

*Listing 35.2. The distinction preserved in scoring.*

Both score zero on the availability axis — correctly, since neither is
confirmed supply. But the *state* travels to the response unchanged, so the
interface can render them differently.

## 35.3 Deterministic ordering

{{include:backend/src/domain/ranking.py:def rank_facilities}}

*Listing 35.3. Ranking with deterministic tie-breaks.*

Ties break on distance, then on facility id. Without the final tie-break,
two facilities with identical scores and distances could order differently
between calls, which makes results irreproducible and tests flaky.

<!-- pagebreak -->

# 36. Compatibility Matching

## 36.1 Rules as data

{{include:backend/src/domain/compatibility.py:def _load_reference}}

*Listing 36.1. Reference loading from
`backend/src/domain/compatibility.py`.*

The loader refuses to start if the file lacks a `reviewStatus`. An unlabelled
compatibility table could be mistaken for a reviewed one, and that is the
single most consequential mistake available in this system.

## 36.2 Lookup only

{{include:backend/src/domain/compatibility.py:def check_compatibility}}

*Listing 36.2. The lookup.*

No inference, no similarity, no fallback. A combination absent from the table
returns `UNKNOWN`, and `is_match` is true only for an explicit `COMPATIBLE`.

## 36.3 Fail-closed donor groups

{{include:backend/src/domain/compatibility.py:def compatible_donor_groups}}

*Listing 36.3. Returning an empty tuple on unknown.*

Returning all groups on an unknown combination would be the convenient choice
and a dangerous one. The empty tuple means the matching engine finds nothing,
which is the correct behaviour when the system does not know.

## 36.4 Plasma runs the other way

A table that is merely copied often gets this wrong, so there is a test:

{{include:backend/tests/unit/test_compatibility.py:def test_ab_is_the_universal_plasma_donor}}

*Listing 36.4. Plasma compatibility is the inverse of red cells.*

There is a matching test that O-negative is **not** a universal whole-blood
donor, which is the same error in the other direction.

## 36.5 Non-identical platelets are flagged

Platelets and whole blood are marked `identicalPreferred` in the reference. A
compatible but non-identical platelet match sets `requiresClinicalReview`,
which travels through the matching engine into the provider notification.

<!-- pagebreak -->

# 37. The Notification Service

## 37.1 Consent first

{{include:backend/src/services/notification_service.py:def is_opted_in}}

*Listing 37.1. Consent checking from
`backend/src/services/notification_service.py`.*

Three gates: consent, category preference, and at least one selected channel.
Each returns a distinct reason, so a suppressed notification can be explained
rather than silently discarded.

## 37.2 Transactional notices bypass category opt-out

Account and administrative notices use `force_transactional`. A user who opted
out of camp announcements still needs to be told their account was suspended.
The categories that bypass opt-out are listed explicitly in
`CATEGORY_PREFERENCE_KEY` with a `None` value, so the set is visible rather
than scattered through conditionals.

## 37.3 Duplicate suppression is durable

{{include:backend/src/repositories/platform_repo.py:def mark_sent_marker}}

*Listing 37.2. The suppression marker.*

A conditional put on a dedupe key. A retried job finds the marker and
suppresses. The marker has a TTL so the table does not grow without bound.

## 37.4 Fan-out is sequential, deliberately

{{include:backend/src/services/notification_service.py:def notify_many}}

*Listing 37.3. Sequential fan-out.*

SES in sandbox permits one message per second, so a parallel burst would be
throttled anyway. At a Lambda concurrency ceiling of
{{fact:lambda_concurrency}}, parallel fan-out would also consume capacity the
API needs.

<!-- pagebreak -->

# 38. The Impact Ledger

## 38.1 The ledger is the truth

{{include:backend/src/domain/impact.py:def compute_score}}

*Listing 38.1. Score derivation from `backend/src/domain/impact.py`.*

A cached counter may exist for display, but any disagreement resolves in favour
of the ledger. That makes recalculation safe: it is a read, not a repair.

## 38.2 Exactly once, enforced by a key

{{include:backend/src/repositories/camp_repo.py:def verify_donation_and_credit}}

*Listing 38.2. The crediting transaction from
`backend/src/repositories/camp_repo.py`.*

The ledger row's sort key is `LEDGER#<donationId>` with
`attribute_not_exists(SK)`. A replayed verification cannot create a second
entry for the same donation, because the key is the same and the condition
fails.

## 38.3 Milestones announce once

{{include:backend/src/domain/impact.py:def newly_earned_milestones}}

*Listing 38.3. Only newly crossed milestones.*

Comparing the before and after sets means a donor is congratulated on crossing
a threshold, not every time they donate thereafter.

## 38.4 Interval advice is information, not clearance

{{include:backend/src/domain/impact.py:def donation_interval_advice}}

*Listing 38.4. Interval advice.*

The wording is part of the implementation. Every branch points the user at camp
staff, and a test asserts that no message contains "eligible to donate" or
"you are cleared" — LifeLink cannot assess fitness to donate and must not imply
that it has.

<!-- pagebreak -->

# 39. Certificates

## 39.1 Generated from verified records only

{{include:backend/src/services/camp_service.py:def certificate_data}}

*Listing 39.1. Certificate data from `backend/src/services/camp_service.py`.*

A certificate is refused for an unverified donation. It is private to the
donor — the lookup is keyed on the caller's own user id, so there is no
identifier a user could change to fetch someone else's.

## 39.2 What the document says it is

`documentType` is `RECOGNITION_CERTIFICATE` and the disclaimer states that it
is not a medical certificate, not a government document, and not proof of
eligibility. The interface repeats that under the rendered certificate.

<!-- pagebreak -->

# 40. The Emergency State Machine

## 40.1 Transitions are data

{{include:backend/src/domain/emergency.py:anchor:VALID_TRANSITIONS:34}}

*Listing 40.1. The transition table from
`backend/src/domain/emergency.py`.*

A table rather than scattered conditionals. Adding a state is one entry;
auditing which transitions exist is reading one structure.

## 40.2 Rejection names the alternatives

{{include:backend/src/domain/emergency.py:def assert_transition}}

*Listing 40.2. Transition enforcement.*

The error lists the permitted targets, which turns a debugging session into a
glance.

## 40.3 Conditional writes enforce it at the datastore

The transition table is the domain rule; the `ConditionExpression` on
`status` is the enforcement. Two workers advancing the same request means one
condition fails, and a late provider response cannot revive a cancelled
request because the status no longer matches.

## 40.4 Re-matching is a permitted cycle

`RESPONSES_RECEIVED` may return to `MATCHING_INITIATED`. That is the only
backwards edge in the machine, and it exists because every provider declining
should widen the search rather than fail the request.

<!-- pagebreak -->

# 41. Provider Response Management

## 41.1 A placeholder is created at notification time

{{include:backend/src/repositories/emergency_repo.py:def record_provider_notification}}

*Listing 41.1. The response placeholder from
`backend/src/repositories/emergency_repo.py`.*

Creating the row when the provider is notified gives the submission path
something to condition on. A provider who was never asked has no row, so their
response is refused.

## 41.2 Submission is conditional

{{include:backend/src/repositories/emergency_repo.py:def submit_response}}

*Listing 41.2. Response submission.*

The condition requires the row to exist and still be `AWAITING_RESPONSE`. A
second response from the same provider fails it.

## 41.3 The tally never nets

{{include:backend/src/domain/emergency.py:def tally_responses}}

*Listing 41.3. Response tallying.*

`units_offered` sums what providers said they are willing to supply. It is not
subtracted from anything and not presented as secured supply. Two providers
offering the same four units produce a tally of eight offered across two
accepted responses, and the interface says explicitly that offers are not added
together because they may describe the same physical units.

<!-- pagebreak -->

# 42. Deployment Process

## 42.1 Pre-deployment checklist

| Check | Command | Must show |
|---|---|---|
| Account and region | `aws sts get-caller-identity` | {{fact:aws_account}}, {{fact:aws_region}} |
| Template syntax | `sam validate --lint` | valid |
| Template lint | `cfn-lint infrastructure/template.yaml` | no findings |
| Backend tests | `pytest tests -q` | all passing |
| Frontend tests | `npm test` | all passing |
| Lint | `ruff check src tests` | clean |
| OpenAPI current | `generate_openapi.py --check` | matches |
| No secrets staged | `git diff --cached` | nothing sensitive |
| Environment correct | parameter override | not `prod` by accident |

*Table 42.1. Pre-deployment checks.*

## 42.2 What a first deployment creates

{{fact:cfn_resources}} resources including {{fact:table_count}} DynamoDB
tables, 6 Lambda functions, 2 queues with 2 dead-letter queues, a Cognito user
pool and identity pool, 2 S3 buckets, a CloudFront distribution, 3 Amazon
Location resources, a KMS key, {{fact:cfn_alarms}} alarms and a dashboard.

## 42.3 The frontend is a separate step

The template creates the bucket and distribution; it does not upload the
bundle. Build, sync, invalidate. Keeping them separate means a frontend-only
change does not require a stack update.

## 42.4 Rollback

CloudFormation rolls back automatically on a failed create or update. Retained
resources — tables in production, the audit table everywhere — survive a stack
deletion, which is the point of the retention policy.

<!-- pagebreak -->

# 43. Where to Go Next

## 43.1 Reading order for a newcomer

1. `docs/ARCHITECTURE_DECISIONS.md` — the seventeen decisions and why
2. `docs/DATABASE_DESIGN.md` — the thirty-nine access patterns
3. `backend/src/domain/` — the rules, readable without any AWS knowledge
4. `backend/tests/unit/` — the rules as executable specifications
5. `backend/src/services/inventory_service.py` — a representative service
6. `backend/src/handlers/api.py` — the complete API surface
7. `infrastructure/template.yaml` — the deployment

## 43.2 Making a change safely

1. Write or adjust a test first. The suite runs in seconds.
2. Change the domain layer if it is a rule; the service if it is a workflow;
   the repository if it is storage.
3. Run `pytest tests -q` and `ruff check src tests`.
4. If you touched a route, run `generate_openapi.py`.
5. If you touched something the books quote, run `build_books.py` — an
   outdated anchor fails the build.

## 43.3 The habits worth keeping

**Inject time.** Every function that depends on "now" takes it as a parameter.
It costs one argument and buys deterministic tests.

**Return reasons, not booleans.** A refusal that explains itself is worth
several support conversations.

**Name the rule in the error.** `details: {"rule": "SELF_VERIFICATION_FORBIDDEN"}`
tells a client developer exactly what happened.

**Test refusals.** Much of this suite asserts what the system will not do,
because those are the properties that matter and the ones that silently rot.

**Write the limitation down.** The defect in Chapter 30 was found while writing
a table of known limitations. Documentation written alongside code finds bugs;
documentation written afterwards describes them.
