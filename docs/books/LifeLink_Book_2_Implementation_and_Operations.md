# 1. Repository and Folder Structure

## 1.1 What is in the repository

```
LifeLink/
├── backend/
│   ├── src/
│   │   ├── domain/          pure business logic, no I/O
│   │   ├── appcore/         RBAC, context, logging, responses, auth
│   │   ├── repositories/    DynamoDB access, one per bounded context
│   │   ├── adapters/        notifications, location providers
│   │   ├── services/        orchestration, one per feature
│   │   ├── handlers/        Lambda entry points and the router
│   │   └── reference/       versioned compatibility data
│   ├── tests/
│   │   ├── unit/            no I/O, no AWS
│   │   └── integration/     real DynamoDB API via moto
│   └── pyproject.toml
├── frontend/
│   └── src/
│       ├── api/             the single network client
│       ├── auth/            authentication context
│       ├── components/      shared UI primitives
│       ├── features/        one folder per feature area
│       ├── hooks/           data fetching and geolocation
│       ├── styles/          design tokens
│       └── test/            Vitest suites
├── infrastructure/
│   └── template.yaml        SAM/CloudFormation, one stack
├── scripts/
│   ├── dev.py               local stack orchestration
│   ├── seed_demo.py         synthetic dataset
│   ├── local_server.py      local HTTP front end for the router
│   ├── generate_openapi.py  OpenAPI from the live route table
│   ├── build_books.py       this book
│   └── bookgen/             the book toolchain
└── docs/                    architecture, decisions, runbooks, books
```

*Listing 1.1. The repository layout.*

| Area | Modules | Lines |
|---|---|---|
| Backend source | {{fact:backend_modules}} | {{fact:backend_lines}} |
| Backend tests | {{fact:backend_test_files}} files | {{fact:backend_test_lines}} |
| Frontend source | {{fact:frontend_modules}} | {{fact:frontend_lines}} |
| Infrastructure | 1 template | {{fact:cfn_lines}} |

*Table 1.1. Size of each area, measured at build time.*

The test-to-source ratio is deliberate. Roughly as many lines of test as of
backend source is not a target anyone set; it is what resulted from testing
every invariant the specification names.

## 1.2 The layering rule

Dependencies point inward only:

```diagram
type: layered
title: Dependency direction
layer Entry
node handlers handlers parse and format only style=domain
layer Orchestration
node services services apply business workflows style=domain
layer Logic
node domain domain pure functions no I/O style=domain
layer Boundaries
node repos repositories DynamoDB only style=data
node adapters adapters external providers style=external
edge handlers -> services
edge services -> domain
edge services -> repos
edge services -> adapters
```

*Figure 1.1. Each arrow is a permitted dependency. There are no arrows pointing
back up, and `domain` has no outgoing arrows at all.*

The consequence that matters day to day: `domain/` imports nothing from
`repositories/`, `adapters/` or `boto3`. It can be tested at full speed with no
mocks and no AWS, which is why {{fact:backend_test_files}} test files run in
seconds.

## 1.3 Why `appcore` is not called `platform`

A small but instructive detail. The shared platform package was originally
named `platform`. Python has a standard-library module of that name, and
`botocore` imports it. With `src` on the path, `import platform` would have
resolved to the application package and broken boto3 in a way that would have
been baffling to debug.

The package was renamed to `appcore` before any code depended on it, and a
verification step confirmed that `import platform` still resolves to the
standard library with `src` on `sys.path`.

:::note The general lesson
Shadowing a standard-library module is a failure that presents as something
else entirely — an AWS SDK import error with no obvious cause. Checking the
name against the standard library costs seconds.
:::

## 1.4 Naming conventions

| Convention | Example | Reason |
|---|---|---|
| Modules: lowercase, singular domain noun | `eligibility.py` | Reads as the subject it owns |
| Repository classes end `Repository` | `InventoryRepository` | Makes the layer obvious at a call site |
| Service classes end `Service` | `EmergencyService` | Same |
| Pure functions take `now` explicitly | `freshness_label(ts, now)` | No hidden clock, so tests are deterministic |
| Error classes end `Error` and carry a `code` | `InsufficientStockError` | Stable contract for clients |
| Frontend files match their default export | `FindBloodPage.jsx` | Navigable without searching |

*Table 1.2. Conventions and the reasoning behind each.*

<!-- pagebreak -->

# 2. Development Environment

## 2.1 Prerequisites

| Tool | Version used | Required |
|---|---|---|
| Python | {{fact:python_version}} | Yes |
| Node.js | {{fact:node_version}} | For the frontend |
| Java | 26 | Only for the optional DynamoDB Local path |
| AWS SAM CLI | {{fact:sam_version}} | For template validation |
| AWS CLI | 2.40.3 | For account inspection |
| Docker | — | **Not required** |

*Table 2.1. Prerequisites.*

Docker is listed because its absence is a deliberate design point. The local
stack runs without it.

## 2.2 Getting running

```bash
# 1. Python environment
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r backend/requirements-dev.txt
.venv/Scripts/python.exe -m pip install -r requirements-docs.txt

# 2. Development signing keys (gitignored, local only)
python scripts/dev.py keys

# 3. Local DynamoDB-compatible endpoint
python scripts/dev.py db-start

# 4. Tables
python scripts/dev.py create-tables

# 5. Synthetic data
python scripts/seed_demo.py
python scripts/seed_demo.py --validate

# 6. API
python scripts/local_server.py --port 8080

# 7. Frontend, in another terminal
cd frontend && npm install && npm run dev
```

*Listing 2.1. The complete local setup.*

`python scripts/dev.py status` reports what is and is not running.

## 2.3 Why moto rather than DynamoDB Local

The specification suggests DynamoDB Local. It is a Java application distributed
as a downloadable archive, and in the environment this project was built in the
download was not available.

moto in server mode provides a DynamoDB-compatible HTTP endpoint from a package
already installed for testing. The application code, the boto3 client and the
connection configuration are all unchanged — only the endpoint URL differs,
exactly as it would with the Java version.

| | DynamoDB Local | moto server |
|---|---|---|
| Download required | Yes, ~60 MB | No |
| Runtime | Java | Python, already present |
| API fidelity | Very high | High; conditions and transactions work |
| Used for | Optional alternative | **Default** |

*Table 2.2. The two local database options. `scripts/dev.py dynamo-start`
still launches the Java version for anyone who prefers it.*

Condition expressions, transactions and GSI range queries all behave correctly
under moto, which is what the integration tests depend on. Four real bugs were
caught by those tests precisely because the emulation is faithful.

## 2.4 Local authentication

Cognito has no local emulator. The local stack issues RS256 tokens signed with
a development keypair, carrying the same claim shape as Cognito.

```bash
python scripts/dev.py token user-donor-1
```

*Listing 2.2. Minting a development token.*

:::warning A documented divergence
The token *issuer* differs locally; the token *verifier* is the same code path
in both environments, switched only by key source. This means local development
does not exercise Cognito itself, and that is stated on the sign-in page of the
application rather than buried here.
:::

{{include:backend/src/appcore/auth.py:class LocalTokenVerifier}}

*Listing 2.3. The local verifier from `backend/src/appcore/auth.py`.*

## 2.5 The demo accounts

| User id | Role | Useful for demonstrating |
|---|---|---|
| `user-donor-1` | DONOR | Verified donations, impact milestones |
| `user-bb-admin-1` | BLOOD_BANK_ADMIN | Inventory, corrections, verification |
| `user-bb-staff-1` | BLOOD_BANK_STAFF | Stock updates but **not** verification |
| `user-hosp-auth-1` | HOSPITAL_AUTHORIZER | Priority certification |
| `user-hosp-staff-1` | HOSPITAL_STAFF | Raising requests but **not** certifying |
| `user-camp-org-1` | CAMP_ORGANIZER | Camp management, donation verification |
| `user-camp-staff-1` | CAMP_STAFF | Check-in and verification, scoped to camps |
| `user-admin-1` | PLATFORM_ADMIN | Organization verification, suspension, audit |
| `user-suspended-1` | BLOOD_BANK_ADMIN, suspended | **Every action refused despite a valid token** |

*Table 2.3. Seeded accounts. The last row exists specifically so the
suspended-account behaviour can be demonstrated rather than asserted.*

<!-- pagebreak -->

# 3. The Domain Layer

## 3.1 What belongs here

Pure functions and immutable data. No I/O, no clock reads, no AWS, no
framework. Twelve modules:

| Module | Owns |
|---|---|
| `blood.py` | Groups, components, statuses, availability states |
| `clock.py` | UTC handling, ISO parsing and formatting |
| `errors.py` | The error taxonomy and HTTP mapping |
| `freshness.py` | Freshness bands and verification status |
| `eligibility.py` | Whether a batch may be presented as available |
| `inventory.py` | Stock operations and availability aggregation |
| `geo.py` | Geohash, neighbours, Haversine, search cells |
| `ranking.py` | Availability-aware facility ranking |
| `camps.py` | Camp lifecycle, registration rules, verification authority |
| `impact.py` | Donation ledger, milestones, interval advice |
| `emergency.py` | Request lifecycle, priority, fairness, response tally |
| `compatibility.py` | Compatibility lookup against versioned data |

*Table 3.1. The domain modules.*

## 3.2 Time is always a parameter

{{include:backend/src/domain/clock.py:def parse_iso}}

*Listing 3.1. ISO parsing from `backend/src/domain/clock.py`. A string without a
timezone is rejected rather than assumed to be UTC.*

That rejection is the kind of decision that looks pedantic until it prevents a
bug. An external feed sending `2026-11-15T09:30:00` could mean UTC or IST — a
five and a half hour difference, enough to make expired stock look fresh.

Every domain function that depends on time takes `now` as an argument. Nothing
in `domain/` calls `datetime.now()`. The result is that time-dependent tests
pass a fixed instant and are deterministic without patching the clock:

```python
NOW = datetime(2026, 11, 15, 12, 0, 0, tzinfo=UTC)
assert freshness_label(hours_ago(6.0), NOW) is FreshnessLabel.FRESH
assert freshness_label(hours_ago(6.1), NOW) is FreshnessLabel.AGING
```

*Listing 3.2. Boundary testing made trivial by injected time.*

## 3.3 Freshness and verification

The specification's most important data-integrity rule gets two separate
functions, because one function returning both would invite callers to treat
them as one concept.

{{include:backend/src/domain/freshness.py:def verification_status}}

*Listing 3.3. Verification status, computed independently of freshness.*

The bands themselves come straight from the specification:

| Time since update | Label |
|---|---|
| 0–6 hours | FRESH |
| >6–24 hours | AGING |
| >24–48 hours | STALE |
| >48 hours | OUTDATED |
| No timestamp, or a future one | UNKNOWN |

*Table 3.2. Freshness bands. The last row is an addition: a future timestamp
indicates clock skew or bad data and must not be rewarded with FRESH.*

## 3.4 Eligibility fails closed

{{include:backend/src/domain/eligibility.py:def evaluate_batch_eligibility}}

*Listing 3.4. Eligibility from `backend/src/domain/eligibility.py`.*

Three properties worth drawing out.

**It returns reasons, not a boolean.** The user interface can explain *why*
something is unavailable, and the API can return machine-readable codes.

**It collects every reason.** A quarantined batch with no units and no expiry
reports all three problems, so a staff member fixing records sees the whole
picture.

**Expiry before collection is a distinct error.** That is incoherent data, not
merely expired stock, and conflating them would hide a data-quality problem.

## 3.5 Availability aggregation and the UNKNOWN rule

{{include:backend/src/domain/inventory.py:def summarise_availability}}

*Listing 3.5. Availability aggregation from `backend/src/domain/inventory.py`.*

The `inventory_known` parameter exists for one reason: to make the difference
between "this facility reports zero" and "this facility reports nothing"
impossible to lose. A facility that has never submitted inventory returns
`UNKNOWN` with no unit count at all.

:::key Why this is a safety property, not a display preference
A user who sees "0 units" concludes the facility has none and does not call.
A user who sees "not reported" calls to find out. One of those is a wasted
journey avoided; the other is a usable supply missed.
:::

## 3.6 Stock operations

{{include:backend/src/domain/inventory.py:def apply_stock_operation}}

*Listing 3.6. Stock operations from `backend/src/domain/inventory.py`.*

The function returns a `StockChange` describing the intended new state. It does
not write anything. That separation means the decision is testable in isolation
and the write is a separate, conditional step that can fail independently.

Note the release-from-quarantine branch: releasing a batch whose expiry has
passed transitions it to `EXPIRED`, not `AVAILABLE`. Without that, clearing a
quarantine flag on old stock would silently resurrect it.

<!-- pagebreak -->

# 4. The Platform Layer

## 4.1 Five modules that everything depends on

| Module | Responsibility |
|---|---|
| `appcore/rbac.py` | Roles, permissions, the authorization matrix |
| `appcore/context.py` | Principal and request context |
| `appcore/auth.py` | Token verification and the `@requires` decorator |
| `appcore/logging.py` | Structured JSON logging with redaction |
| `appcore/responses.py` | Response envelopes, pagination, cursors |

*Table 4.1. The platform modules.*

## 4.2 Permissions, not roles, are the unit of authorization

A handler declares the permission it needs. It never enumerates roles.

{{include:backend/src/appcore/rbac.py:def permissions_for}}

*Listing 4.1. Role-to-permission resolution from `backend/src/appcore/rbac.py`.*

There are {{fact:permission_count}} permissions across {{fact:role_count}}
roles. Keeping the matrix in one file makes questions like "who can verify a
donation?" answerable by reading a single data structure rather than grepping
for decorators.

An unknown role grants nothing and does not dilute known roles — there is a
test for that, because a typo in a stored role string should reduce access, not
silently widen it.

## 4.3 The matrix's deliberate exclusions

| Role | Notably does **not** have | Why |
|---|---|---|
| `CAMP_ORGANIZER` | Any inventory permission | Specification 5.7 is explicit |
| `HOSPITAL_STAFF` | `emergency:certify:priority` | Certification is a clinical act |
| `BLOOD_BANK_STAFF` | `inventory:verify`, `inventory:correct` | Verification needs seniority |
| `DONOR` | `donation:verify` | A donor cannot verify their own donation |
| Everyone except `PLATFORM_ADMIN` | `hospital:verify` | Only an administrator verifies institutions |

*Table 4.2. What each role is refused, with tests asserting each line.*

## 4.4 The principal comes from the database

{{include:backend/src/appcore/context.py:class Principal}}

*Listing 4.2. The principal from `backend/src/appcore/context.py`.*

The docstring records the reason: roles come from the stored user record so a
revoked role takes effect on the next request. A `Principal` built from token
claims would be stale for up to an hour.

## 4.5 Logging that cannot leak

{{include:backend/src/appcore/logging.py:anchor:SENSITIVE_KEYS:14}}

*Listing 4.3. The redaction set from `backend/src/appcore/logging.py`.*

The list includes the obvious secrets and also email, phone, coordinates and
date of birth. Those are personal data, and logs are where personal data
accumulates without anyone having decided it should.

Redaction is recursive and depth-limited, so a nested payload cannot smuggle a
token through by burying it twelve levels down.

## 4.6 Response envelopes

One success shape and one error shape, so a client writes one response handler.

```json
{ "data": { ... }, "meta": { "count": 20, "nextCursor": "..." },
  "correlationId": "corr-..." }

{ "error": { "code": "CONCURRENT_MODIFICATION", "message": "...",
             "details": { "hint": "re-read the record and retry" } },
  "correlationId": "corr-..." }
```

*Listing 4.4. The two envelopes.*

Clients branch on `code`. The message is written for a human and may be
reworded without notice; the code is contract.

## 4.7 Cursors bound to their query

{{include:backend/src/appcore/responses.py:def decode_cursor}}

*Listing 4.5. Cursor decoding from `backend/src/appcore/responses.py`.*

The cursor embeds a fingerprint of the query that produced it. Presenting a
cursor from one search against a different search is rejected rather than
silently returning results from the wrong result set — a bug that would be
nearly impossible to notice in testing and quite possible to hit in production.

<!-- pagebreak -->

# 5. Authentication Middleware

## 5.1 The decorator

{{include:backend/src/appcore/auth.py:def requires}}

*Listing 5.1. The complete authorization decorator.*

```diagram
type: flow
title: What the decorator checks, in order
node tok Verify signature issuer expiry and token use style=aws
node load Load principal from the organizations table style=data
node act Refuse if the account is not ACTIVE style=domain
node perm Refuse if the permission is not held style=domain
node own Refuse if the resource belongs to another organization style=domain
node run Call the handler with an authorized context style=domain
```

*Figure 5.1. The authorization pipeline.*

## 5.2 Reading it line by line

**`if not allow_anonymous and principal is ANONYMOUS`** — unauthenticated
callers are refused unless the route explicitly permits them. The default is
closed.

**`if principal is not ANONYMOUS and not principal.is_active`** — the suspended
account check, placed before the permission check so the error names the real
reason.

**`if permission is not None and not principal.has(permission)`** — the
permission check against the union of the caller's roles.

**`if ... is_organization_scoped(permission) and resource_owner`** — the IDOR
defence. The handler supplied a resolver; the decorator calls it and compares.

**`wrapper.__lifelink_permission__ = permission`** — metadata that makes the
route table auditable. A test walks every route and asserts each is either
decorated or explicitly anonymous.

## 5.3 Building the context

{{include:backend/src/appcore/auth.py:def build_context}}

*Listing 5.2. Context construction.*

An inbound `X-Correlation-Id` is honoured so a client can correlate its own
logs with the server's; otherwise one is generated.

## 5.4 Token verification

Cognito tokens are RS256. The verifier fetches the JWKS once, caches it, and
selects a key by `kid`. It checks the issuer, the expiry, the presence of
`sub`, and that `token_use` is one LifeLink accepts.

Audience verification is disabled deliberately: Cognito access tokens carry
`client_id` rather than `aud`, so the client is checked explicitly instead.
Leaving `verify_aud` on would reject every valid access token, and the usual
"fix" is to stop checking the client at all.

<!-- pagebreak -->

# 6. The Repository Layer

## 6.1 The only place DynamoDB exists

Eight modules, one per bounded context plus a shared base. Services depend on
repository methods; nothing above this layer imports `boto3`.

## 6.2 Serialisation has two modes, and conflating them was a bug

{{include:backend/src/repositories/dynamo.py:def to_expression_values}}

*Listing 6.1. Expression-value serialisation from
`backend/src/repositories/dynamo.py`.*

This function exists because of a real failure. The general `to_dynamo`
serialiser drops `None` from dictionaries, which is correct for items — an
absent attribute should be absent rather than stored as NULL.

Applied to expression attribute values it is wrong, and silently so. An update
expression referencing `:reason` with `reason=None` had its `:reason` value
dropped, leaving the expression referencing a placeholder that was not
supplied. DynamoDB rejected the entire request with `ValidationException`, and
the error gave no hint which placeholder was missing.

Four separate code paths failed this way before the cause was found. The fix is
two explicitly different functions with the distinction documented at both.

## 6.3 Condition failures mean different things

{{include:backend/src/repositories/dynamo.py:def put}}

*Listing 6.2. The `on_conflict` parameter.*

Another bug worth recording. The original `put` translated every condition
failure into `DuplicateError`, on the assumption that a condition meant
`attribute_not_exists`.

For optimistic concurrency the condition is a version check, and a failure
means "someone wrote first — re-read and retry." Reporting it as a duplicate
meant the service's retry path, which catches
`ConcurrentModificationError`, never engaged. The user would have been told a
record already existed when in fact their update simply lost a race.

The code "worked" in the sense that it raised on conflict. It raised the wrong
thing, and only an integration test against a real condition expression could
show that.

## 6.4 Error translation

{{include:backend/src/repositories/dynamo.py:def translate_client_error}}

*Listing 6.3. Mapping DynamoDB errors onto the domain taxonomy.*

Transaction cancellations are unpacked: a `ConditionalCheckFailed` reason
becomes a concurrency error, a `TransactionConflict` becomes the same with a
different detail, and anything else is reported with its reason codes rather
than as an opaque failure.

## 6.5 Scans are forbidden on user-facing paths

`query_all` exists and pages to completion, but with a hard ceiling:

{{include:backend/src/repositories/dynamo.py:def query_all}}

*Listing 6.4. Bounded pagination.*

The ceiling means a pathological partition cannot turn one request into an
unbounded read. At a Lambda concurrency ceiling of {{fact:lambda_concurrency}},
one request consuming a container for thirty seconds is felt by every other
user.

<!-- pagebreak -->

# 7. Inventory Persistence

## 7.1 Key design

| Item | PK | SK |
|---|---|---|
| Batch | `FACILITY#<facilityId>` | `BATCH#<batchId>` |
| Audit entry | `BATCH#<batchId>` | `AUDIT#<timestamp>#<eventId>` |

*Table 7.1. Inventory key schema.*

Batches are keyed by facility so listing a facility's stock is one query. Audit
entries are keyed by batch so a batch's history is one query. The two live in
the same table because they belong to the same bounded context.

## 7.2 Index attributes are derived, never hand-set

{{include:backend/src/repositories/inventory_repo.py:def batch_to_item}}

*Listing 7.1. Item construction from `backend/src/repositories/inventory_repo.py`.*

Every index attribute is computed from the batch's own fields. There is no code
path that writes a `GSI1SK` independently of the status and expiry it encodes,
so the index cannot drift out of agreement with the item.

## 7.3 The conditional write

{{include:backend/src/repositories/inventory_repo.py:def apply_change}}

*Listing 7.2. The optimistic-concurrency write.*

Two conditions: the version is unchanged, and for deductions enough units
remain. The second is redundant with the domain check that already ran — and
that redundancy is the point. Between the read and the write, another request
may have taken the stock.

## 7.4 Verification writes only verification fields

{{include:backend/src/repositories/inventory_repo.py:def record_verification}}

*Listing 7.3. The only code path that writes `lastVerifiedAt`.*

The comment on this method is load-bearing. It is the single place in the
codebase permitted to set that field, which is what makes "an automated update
never implies human verification" an enforceable property rather than an
intention.

<!-- pagebreak -->

# 8. The Inventory Service

## 8.1 Composing a decision with a write

A service method is usually three steps: read current state, ask the domain
layer what the new state should be, write it conditionally.

{{include:backend/src/services/inventory_service.py:def adjust_stock}}

*Listing 8.1. Stock adjustment from
`backend/src/services/inventory_service.py`.*

```diagram
type: sequence
title: A stock deduction that loses a race and recovers
actor client Dashboard
actor svc Inventory service
actor dom Domain layer
actor ddb DynamoDB
msg client -> svc deduct two units
msg svc -> ddb read batch version seven
msg svc -> dom apply stock operation
msg dom -> svc new state version eight
msg svc -> ddb transaction conditional on version seven
msg ddb -> svc condition failed another writer committed
msg svc -> ddb re-read batch version eight
msg svc -> dom recompute from current state
msg svc -> ddb transaction conditional on version eight
msg ddb -> svc committed
msg svc -> client new batch state
note Recomputing is essential. Resubmitting the first decision would fail forever.
```

*Figure 8.1. The retry loop recovering from a concurrent write.*

## 8.2 The retry loop, in detail

The loop re-reads inside each attempt. That is the part people get wrong:
retrying the *same* computed change would fail the same condition forever,
because the condition is on the version that has already moved.

The audit item and the outbox event are constructed inside the loop too, so
they describe the attempt that actually commits rather than the first one that
did not.

After three retries the service gives up and lets `ConcurrentModificationError`
propagate to a 409. That is better than looping: a batch under constant
contention is a situation a human should see.

## 8.3 Availability for a whole facility

{{include:backend/src/services/inventory_service.py:def facility_availability}}

*Listing 8.2. The availability matrix.*

Note `inventory_known` being read from the facility record and passed through.
When it is false, no inventory query runs at all and every cell returns
`UNKNOWN`. Querying and finding nothing would produce `UNAVAILABLE`, which
means something different.

## 8.4 External ingestion

{{include:backend/src/services/inventory_service.py:def ingest_external_update}}

*Listing 8.3. External API ingestion.*

Two protections. A stale update — one whose source timestamp predates the
stored `lastUpdatedAt` — is rejected with a named rule rather than applied. And
the update is routed through `adjust_stock` with a source of `API:<system>`,
so it updates `lastUpdatedAt` and never touches `lastVerifiedAt`.

## 8.5 The presentation layer

{{include:backend/src/services/inventory_service.py:def _present_batch}}

*Listing 8.4. Batch presentation.*

Four fields are always emitted together: `lastUpdatedAt`, `freshness`,
`lastVerifiedAt` and `verificationStatus`. Returning freshness without
verification would let a client render one and not the other, which is the
conflation the whole design exists to prevent.

<!-- pagebreak -->

# 9. The Discovery Service

## 9.1 Filter, then rank — never the other way round

{{include:backend/src/services/discovery_service.py:def search_facilities}}

*Listing 9.1. Facility search from
`backend/src/services/discovery_service.py`.*

Eligibility filtering happens while building the candidate list. Ranking runs
afterwards on survivors only. No weighting, however it is tuned, can surface an
expired or quarantined batch, because such batches never enter the list.

## 9.2 Ranking is explainable

{{include:backend/src/domain/ranking.py:def score_facility}}

*Listing 9.2. Scoring from `backend/src/domain/ranking.py`.*

Each result carries its component contributions and a human-readable
explanation. The specification requires explaining ranking factors to the user,
and a bare score explains nothing.

| Factor | Weight | Rationale |
|---|---|---|
| Availability | 30% | The dominant question |
| Inventory freshness | 20% | Stale data is weak evidence |
| Distance | 20% | Travel time matters in an emergency |
| Quantity | 15% | Partial beats none, full beats partial |
| Independent verification | 15% | Human confirmation is worth something |

*Table 9.1. Default weights, matching the specification's proposal. The weights
are configurable and validated to sum to 1.0.*

## 9.3 Routing never guesses

{{include:backend/src/services/discovery_service.py:def route_to_facility}}

*Listing 9.3. Routing with honest degradation.*

Straight-line distance is always present and always labelled. Road distance
appears only when a provider returned one. When it did not, the response says
so, names the reason, and warns that the figure shown is not a driving
distance.

<!-- pagebreak -->

# 10. The Alert Service

## 10.1 An alert is a standing question

{{include:backend/src/services/alert_service.py:def create_alert}}

*Listing 10.1. Alert creation from `backend/src/services/alert_service.py`.*

Creating an alert immediately attempts a match, because a user whose need is
already satisfiable should be told now rather than when stock next changes.

```diagram
type: sequence
title: Stock arrives and a waiting alert is matched
actor staff Blood bank staff
actor api API
actor out Outbox
actor pub Publisher
actor worker Work worker
actor alerts Alert index
actor donor Donor
msg staff -> api add batch
msg api -> out transaction batch and event
msg out -> pub stream delivers event
msg pub -> worker queue message
msg worker -> alerts query match index for this cell and group
msg alerts -> worker waiting alerts
msg worker -> api revalidate stock now
msg worker -> donor notify with informational notice
note The worker revalidates rather than trusting the event, because stock may already have gone.
```

*Figure 10.1. From a stock addition to a donor notification.*

## 10.2 Matching revalidates

{{include:backend/src/services/alert_service.py:def match_alert}}

*Listing 10.2. Alert matching.*

The match re-reads eligible stock rather than trusting whatever event triggered
it. Between a stock-change event being published and a worker processing it,
the stock may already have gone.

Three guards before any notification: the alert must still be active, its
deadline must not have passed, and the facility must not already have been
matched to this alert.

## 10.3 The reverse lookup

{{include:backend/src/services/alert_service.py:def match_on_stock_change}}

*Listing 10.3. Finding alerts waiting on a facility's stock.*

This is what the `GSI2-match` index exists for. The question "stock arrived
here — who was waiting?" becomes a key query on
`MATCH#<geohash5>#<group>#<component>` rather than a scan over every open
alert.

## 10.4 The word "reservation" appears, in the negative

`INFORMATIONAL_NOTICE` is a module-level constant used in every alert response
and every match notification. Centralising it means the wording cannot drift
between the API and the email, and a reviewer can check one string.

<!-- pagebreak -->

# 11. The Camp Service

## 11.1 Four states, four methods

`register` → `check_in` → `record_donation` → `verify_donation`. Each is a
separate authorized action with its own audit record, and each refuses if the
previous one has not happened.

{{include:backend/src/services/camp_service.py:def record_donation}}

*Listing 11.1. Recording a donation requires prior check-in.*

```diagram
type: sequence
title: The four camp states, each a separate authorized action
actor donor Donor
actor staff Camp staff
actor api API
actor camps Camps table
actor ledger Donations and ledger
msg donor -> api register
msg api -> camps transaction registration and capacity
msg staff -> api check in donor
msg api -> camps attendance recorded
msg staff -> api record donation
msg api -> ledger donation status recorded
msg staff -> api verify donation
msg api -> ledger transaction verified and ledger entry
note Each arrow is refused unless the previous one happened, and a donor may not perform the last.
```

*Figure 11.1. Registration, attendance, donation and verification as four
distinct records.*

## 11.2 Self-verification is refused in the service, not only in the policy

{{include:backend/src/domain/camps.py:def assert_can_verify_donation}}

*Listing 11.2. The rule from `backend/src/domain/camps.py`.*

Holding `donation:verify` is necessary but not sufficient. A camp organiser who
donated at their own camp has the permission and is refused anyway, and there
is a test that grants the donor the staff role specifically to prove the
refusal still holds.

## 11.3 Exactly-once credit

{{include:backend/src/services/camp_service.py:def verify_donation}}

*Listing 11.3. Verification and crediting.*

The service reads the ledger before and after so it can report newly crossed
milestones without re-announcing old ones. The exactly-once property itself is
enforced one layer down, by a transaction whose ledger row is keyed on the
donation id with a not-exists condition.

## 11.4 Reminders re-check everything

{{include:backend/src/domain/camps.py:def should_send_reminder}}

*Listing 11.4. The five re-checks.*

A reminder scheduled yesterday for a camp cancelled this morning must not be
sent. Every precondition is evaluated at send time, not at schedule time, and
the schedule-drift tolerance means a job that fires hours late does not emit a
"starts in 2 hours" message about something that started already.

<!-- pagebreak -->

# 12. The Emergency Service

## 12.1 A new request has no priority

{{include:backend/src/services/emergency_service.py:def create_request}}

*Listing 12.1. Request creation from
`backend/src/services/emergency_service.py`.*

`clinicalPriority` is explicitly `None`. Nothing the requester submits can set
it. The response says so and names the next step.

Duplicate submissions are caught by a fingerprint of actor, group, component,
quantity and rounded coordinates. Rounding to three decimal places means GPS
jitter does not defeat the check while a genuinely different location still
produces a different fingerprint.

## 12.2 Certification re-checks the hospital

{{include:backend/src/services/emergency_service.py:def certify_priority}}

*Listing 12.2. Priority certification.*

Four checks before the write: the caller belongs to an organization, that
organization exists, it is a hospital, and it is *currently* verified. The last
is why a hospital suspended after the request was raised cannot certify it.

## 12.3 Matching uses the reference table

{{include:backend/src/services/emergency_service.py:def run_matching}}

*Listing 12.3. The matching engine.*

Compatible donor groups come from `compatible_donor_groups`, which reads the
versioned JSON reference. When the lookup yields nothing the engine records a
`NO_COMPATIBILITY_REFERENCE` event and returns no candidates, along with the
rules version and review status.

Candidates are ordered deterministically: identical blood group first, then
rank score, then distance. Determinism matters because a matching engine that
returns different results for identical inputs cannot be audited.

## 12.4 Responses are offers

{{include:backend/src/services/emergency_service.py:def submit_response}}

*Listing 12.4. Provider response handling.*

Before an acceptance is recorded, stock is revalidated. If it has gone, the
acceptance is refused with the current figure and a named rule, rather than
recorded against stock that no longer exists.

Nothing in this method decrements inventory, and it touches no reservation
counter — which is why two providers accepting the same request is recorded as
two independent offers rather than eight units of secured supply.

Be precise about this in a viva. A reservation counter *does* exist, for
temporary reservations (ADR-0018), and it is updated atomically. The point is
that the **emergency response path deliberately does not use it**: an offer is
a willingness to proceed, not a claim on units.

<!-- pagebreak -->

# 13. The Router and Handlers

## 13.1 Why not a web framework

The specification discourages unnecessary frameworks and names FastAPI and
Mangum specifically. An API Gateway proxy integration delivers a dictionary and
expects a dictionary back. A route table plus path-parameter matching is all
that stands between those two facts.

{{include:backend/src/handlers/router.py:class Router}}

*Listing 13.1. The router from `backend/src/handlers/router.py`.*

## 13.2 404 and 405 are different answers

`match` returns whether the *path* exists under some other method. A `DELETE`
to a path that only supports `GET` returns 405 with the method named, not a 404
suggesting the path is wrong. Debugging an integration against an API that
conflates the two wastes real time.

## 13.3 Error translation at the edge

{{include:backend/src/handlers/router.py:def dispatch}}

*Listing 13.2. Dispatch and error handling.*

Domain errors map to their declared status and keep their code. Anything else
becomes a generic 500 with a correlation id — the detail goes to the log, not
to the client, because an exception message can disclose internals.

## 13.4 Handlers are thin

{{include:backend/src/handlers/api.py:def adjust_batch}}

*Listing 13.3. A representative handler from `backend/src/handlers/api.py`.*

Parse, call one service method, format. No business rules. A handler that grew
a conditional would be a sign that a rule had escaped the layer that owns it.

## 13.5 Ownership resolvers

{{include:backend/src/handlers/api.py:def _facility_owner}}

*Listing 13.4. An ownership resolver.*

The handler declares how to find the owning organization; the decorator does
the comparison. This is the division that prevents an IDOR: a handler author
cannot forget a check they do not perform.

## 13.6 The route table

{{fact:route_count}} routes, each with a declared permission and a summary used
to generate the OpenAPI document.

{{routes:alert}}

*Table 13.1. The availability-alert routes, extracted from the live table at
build time.*

<!-- pagebreak -->

# 14. The API Surface

## 14.1 Conventions

| Concern | Convention |
|---|---|
| Resource naming | Plural nouns: `/facilities`, `/camps`, `/alerts` |
| Sub-resources | Nested: `/facilities/{id}/batches/{batchId}` |
| Actions that are not CRUD | A verb segment: `/certify`, `/respond`, `/adjust` |
| Status codes | 200 read, 201 create, 204 delete, 4xx client, 5xx server |
| Errors | `{ error: { code, message, details? } }` |
| Pagination | Cursor in `meta.nextCursor` |
| Idempotency | `Idempotency-Key` header on mutating requests |
| Correlation | `X-Correlation-Id` accepted and echoed |

*Table 14.1. API conventions.*

## 14.2 The OpenAPI document is generated

{{fact:openapi_paths}} paths and {{fact:openapi_operations}} operations, produced
by `scripts/generate_openapi.py` from the live route table.

The specification says not to document endpoints that do not exist. Generating
the document from the router makes that structurally impossible, and a
`--check` mode fails if the committed file has drifted:

```bash
python scripts/generate_openapi.py --check
# OpenAPI document matches the route table.
```

*Listing 14.1. Drift detection.*

Each operation carries an `x-lifelink-permission` extension naming the
permission it requires, so the document doubles as an authorization reference.

## 14.3 Error codes

| Code | Status | Meaning | Retry? |
|---|---|---|---|
| `VALIDATION_ERROR` | 400 | Input failed validation | No |
| `UNAUTHENTICATED` | 401 | Missing or invalid token | After signing in |
| `FORBIDDEN` | 403 | Authenticated, lacks permission | No |
| `ACCOUNT_SUSPENDED` | 403 | Valid token, inactive account | No |
| `CROSS_ORGANIZATION_DENIED` | 403 | Resource belongs elsewhere | No |
| `NOT_FOUND` | 404 | No such resource | No |
| `CONCURRENT_MODIFICATION` | 409 | Lost a write race | **Yes** |
| `DUPLICATE` | 409 | Already exists | No |
| `INSUFFICIENT_STOCK` | 409 | Not enough units | No |
| `INVALID_STATE_TRANSITION` | 409 | Illegal lifecycle move | No |
| `CAPACITY_EXCEEDED` | 409 | Camp is full | No |
| `REQUEST_IN_PROGRESS` | 409 | Identical request in flight | After a pause |
| `RATE_LIMITED` | 429 | Throttled | **Yes, with backoff** |
| `CHANNEL_UNAVAILABLE` | 503 | Notification channel not implemented | No |
| `PROVIDER_UNAVAILABLE` | 503 | External provider failed | **Yes** |

*Table 14.2. The complete error taxonomy and which codes are worth retrying.*

<!-- pagebreak -->

# 15. Frontend Architecture

## 15.1 Structure

```
src/
├── api/client.js            the only module that calls fetch
├── auth/AuthContext.jsx     token and principal state
├── components/              Layout, StatusBadges, FacilityMap, ui primitives
├── features/                home, discovery, camps, emergency, alerts,
│                            dashboards, account
├── hooks/useApi.js          data fetching, mutations, geolocation
└── styles/tokens.css        design tokens
```

*Listing 15.1. Frontend layout: {{fact:frontend_modules}} modules,
{{fact:frontend_lines}} lines.*

## 15.2 One network client

{{include:frontend/src/api/client.js:anchor:async function request:50}}

*Listing 15.2. The request function from `frontend/src/api/client.js`.*

Every call goes through here, so the correlation id, the bearer token and the
idempotency key cannot be forgotten by an individual screen. A network failure
becomes a readable message rather than an echo of a fetch internal, and an
abort is re-raised so a superseded request is dropped silently.

## 15.3 Errors carry their code into the UI

```javascript
get isRetryable() {
  return this.status >= 500 || this.status === 0 ||
         this.code === 'RATE_LIMITED' ||
         this.code === 'CONCURRENT_MODIFICATION'
}
```

*Listing 15.3. Retry classification in the client.*

A component can ask whether retrying is sensible without knowing the error
taxonomy.

## 15.4 Data fetching

{{include:frontend/src/hooks/useApi.js:anchor:export function useApiData:45}}

*Listing 15.4. The data hook from `frontend/src/hooks/useApi.js`.*

The abort matters more than it looks. A user typing in a search box generates
overlapping requests; without cancellation a slow earlier response can land
after a faster later one and overwrite fresher results with staler ones.

## 15.5 Geolocation that never traps the user

{{include:frontend/src/hooks/useApi.js:anchor:export function useGeolocation:60}}

*Listing 15.5. Geolocation with every failure mode handled.*

Permission denied, position unavailable, timeout and a missing API are each
mapped to a distinct status and a message that offers the alternative. The
specification requires never forcing precise location when manual search
exists, and a dead end after a declined permission would do exactly that.

<!-- pagebreak -->

# 16. Components and State

## 16.1 Status badges carry the rules

{{include:frontend/src/components/StatusBadges.jsx:anchor:export function AvailabilityBadge:20}}

*Listing 16.1. The availability badge from
`frontend/src/components/StatusBadges.jsx`.*

The unit count renders only when it is a real measurement. An `UNKNOWN` state
shows "Not reported" and no number, because "0 units" would be a claim the
system cannot support.

## 16.2 Freshness and verification are bundled

{{include:frontend/src/components/StatusBadges.jsx:anchor:export function DataQuality:12}}

*Listing 16.2. The paired badge.*

Bundling them in one component makes it awkward to render one without the
other. A developer in a hurry reaches for `DataQuality`, and gets both.

## 16.3 No status relies on colour alone

Every badge has a text label and a distinct glyph in addition to its colour.
The interface works in greyscale and for a colour-blind user, which is a
requirement rather than a nicety for a service used under pressure.

## 16.4 The async state component

{{include:frontend/src/components/ui.jsx:anchor:export function AsyncState:25}}

*Listing 16.3. One place that decides loading, error, empty or content.*

Every data-driven view passes its hook result straight in, so the four states
look and behave the same everywhere, and the error state always offers a retry
and shows the correlation id.

## 16.5 Error boundaries

A class component — React requires one for this — wraps each routed view so a
failure in one panel does not blank the application.

<!-- pagebreak -->

# 17. Routing and Role-Aware UI

## 17.1 Guards are usability, not security

{{include:frontend/src/App.jsx:anchor:function RequireRole:35}}

*Listing 17.1. The role guard from `frontend/src/App.jsx`.*

The refusal message names the required roles, names the roles the account
actually holds, and states explicitly that the server enforces this
independently. A user who edits the URL gets a clear explanation rather than a
broken screen, and learns that circumventing the guard achieves nothing.

## 17.2 Navigation reflects roles

The header renders dashboard links only for roles the user holds. This is
presentation: the backend refuses regardless. But showing a donor a hospital
dashboard link that fails on click is a poor experience, and hiding it is free.

## 17.3 Lazy-loaded dashboards

Dashboards are the heaviest and least-visited screens, so they are code-split.
The production build shows them as separate chunks of 5 to 9 KB gzipped, none
of which a public visitor downloads.

<!-- pagebreak -->

# 18. The Discovery Screen

## 18.1 The application's most important page

{{include:frontend/src/features/discovery/FindBloodPage.jsx:anchor:const { data: results, loading, error, reload }:20}}

*Listing 18.1. The search query from
`frontend/src/features/discovery/FindBloodPage.jsx`.*

The dependency array lists every filter. Changing any of them cancels the
in-flight request and issues a new one.

## 18.2 Three signals per row

Each result shows availability with a unit count, freshness, and verification,
as three distinct badges, plus the ranking explanation. A user deciding whether
to drive somewhere needs all of it, and collapsing it into a single score would
hide the thing that matters most.

## 18.3 Unknown gets its own notice

When any result has unknown inventory, the page adds an explanatory panel. The
badge alone communicates the state; the panel explains what to do about it,
which is to telephone.

## 18.4 A bug worth recording

An early version set state during render to adopt a browser-provided position:

```javascript
// Wrong: setState during render re-enters the component every pass.
if (geo.status === 'granted' && geo.coords) {
  setOrigin(geo.coords)
}
```

*Listing 18.2. The anti-pattern, corrected to an effect.*

React would re-render, the condition would still hold, and it would set state
again. Moving it into a `useEffect` keyed on the geolocation status fixed it.

<!-- pagebreak -->

# 19. Map Rendering and Fallback

## 19.1 The fallback is the default path

{{include:frontend/src/components/FacilityMap.jsx:anchor:export function FacilityMap:28}}

*Listing 19.1. The map component from
`frontend/src/components/FacilityMap.jsx`.*

With no `VITE_MAP_STYLE_URL` configured — the local default — the component
renders a facility list rather than pointing at someone else's tile server.
The fallback is therefore exercised constantly in development, not kept as
untested emergency code.

## 19.2 Lazy loading

MapLibre is 802 KB. It is imported dynamically inside the effect, so a
deployment without a configured map never downloads it, and the production
build confirms it as a separate chunk.

## 19.3 Runtime failures fall back too

The map registers an `error` handler and a failed dynamic import is caught.
Either sets `renderFailed`, which renders the list with a message explaining
what happened. An empty grey rectangle is not an acceptable outcome.

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
This procedure is written from the AWS documentation and has not been executed
against a LifeLink deployment, because nothing has been deployed.
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

<!-- pagebreak -->

# 44. The Seed Data Generator

## 44.1 Why the seeder is production code

A demonstration dataset that is wrong is worse than none: every screenshot,
every walkthrough and every test built on it inherits the error. The seeder is
therefore written with the same care as the application, and validated.

## 44.2 Determinism

```python
SEED = 20261115
self.rng = random.Random(SEED)
```

*Listing 44.1. A fixed seed and a dedicated generator instance.*

A dedicated `Random` instance rather than the module-level functions, so
unrelated code calling `random` cannot perturb the dataset. Identifiers are
fixed strings (`demo-batch-0001`), not generated, so a screenshot taken today
matches a database rebuilt next month.

## 44.3 Deliberate coverage

The dataset is not random data within plausible ranges. Every case the
specification names is placed on purpose:

{{include:scripts/seed_demo.py:anchor:freshness_plan = [:6}}

*Listing 44.2. The freshness spread from `scripts/seed_demo.py`.*

Fifty batches in each freshness band, so the four labels are all visible on
screen rather than theoretically reachable. Similar deliberate placement
covers quarantined stock, expired stock, near-expiry stock, zero-unit batches,
and a facility that has reported nothing at all.

## 44.4 The production guard

{{include:scripts/seed_demo.py:def guard_environment}}

*Listing 44.3. Three independent refusals.*

Three checks rather than one, because a single condition is one typo away from
being bypassed. The environment name must be local, dev or test; a local
endpoint must be configured; and the endpoint must not point at real AWS.

## 44.5 Validation as a first-class command

{{include:scripts/seed_demo.py:anchor:checks.append(("all 8 blood groups present":4}}

*Listing 44.4. One of twenty-four coverage checks.*

`--validate` reports each check individually and exits non-zero if any fails.
The alternative — a seeder that prints "done" — gives no evidence the dataset
covers what the demonstration needs.

## 44.6 Resetting

`--reset` deletes every item marked `demoData` before seeding. That requires a
scan, which is otherwise forbidden, so the function logs that it performed one:

```
OFFLINE MAINTENANCE SCAN: removed 312 demo items
```

*Listing 44.5. A scan that announces itself.*

Making the exception visible in the output is deliberate. A rule with silent
exceptions stops being a rule.

<!-- pagebreak -->

# 45. The OpenAPI Generator

## 45.1 The problem it solves

The specification says to generate an OpenAPI document matching the actual
endpoints, and not to document endpoints that do not exist. A hand-maintained
document satisfies neither requirement for long.

## 45.2 Reading the router

{{include:scripts/generate_openapi.py:def build_document}}

*Listing 45.1. Document construction from `scripts/generate_openapi.py`.*

The generator imports the live route table. An endpoint that does not exist
cannot appear, and one that exists cannot be forgotten.

## 45.3 Error responses are derived, not assumed

Only statuses a route can actually produce are documented. A route marked
anonymous omits 401; a route with no declared permission omits 403. Listing
every status on every operation would be noise that trains readers to ignore
the section.

## 45.4 Permissions in the document

Each operation carries an `x-lifelink-permission` extension naming the
permission required, so the document doubles as an authorization reference.
That is information a hand-written document would never stay accurate about.

## 45.5 Drift detection

```bash
python scripts/generate_openapi.py --check
# OpenAPI document matches the route table.
```

*Listing 45.2. Failing on drift.*

A `--check` mode that exits non-zero when the committed file differs from what
the router would produce. Suitable for a pre-commit hook or CI.

## 45.6 A lesson about hand-rolled formats

The first version emitted YAML with a bespoke serialiser to avoid a
dependency. It produced invalid YAML for multi-line description blocks — the
block-scalar indentation was wrong — and the file looked plausible while being
unparseable.

It now uses PyYAML and **parses the output back**, comparing it to the JSON
document before writing. A machine-readable artifact that cannot be read by a
machine is worse than one that does not exist, because its existence implies
it works.

<!-- pagebreak -->

# 46. The Local Server

## 46.1 Translating HTTP into a Lambda event

{{include:scripts/local_server.py:anchor:event = {:12}}

*Listing 46.1. Event construction from `scripts/local_server.py`.*

The shape matches what API Gateway delivers, so the router and every handler
behave identically. The specification warns against a mock application that
behaves differently from the real architecture; the way to avoid that is to
have only one application.

## 46.2 CORS in development

{{include:scripts/local_server.py:def _cors_headers}}

*Listing 46.2. CORS handling.*

The Vite dev server also proxies `/api` to the local server, which makes the
browser same-origin and avoids CORS entirely. The headers exist for direct
calls — `curl`, Postman — during development.

## 46.3 Staying up

A last-resort try/except around dispatch returns a 500 rather than killing the
server. A development server that dies on an unhandled exception interrupts
work for no benefit; the exception is still logged in full.

## 46.4 What it prints on startup

```
LifeLink local API on http://127.0.0.1:8080
  DynamoDB endpoint : http://localhost:8000
  Routes registered : 50
  CORS origins      : http://localhost:5173
  DEMO ENVIRONMENT - SYNTHETIC DATA - NOT REAL BLOOD AVAILABILITY
```

*Listing 46.3. Startup output.*

The route count is a cheap sanity check: if it is not what you expect, a
module failed to import.

<!-- pagebreak -->

# 47. Error Handling Patterns

## 47.1 The taxonomy as code

{{include:backend/src/domain/errors.py:class LifeLinkError}}

*Listing 47.1. The base error from `backend/src/domain/errors.py`.*

Three properties on every error: a stable `code` for clients, an `http_status`
so the router needs no mapping table, and a `details` dictionary for
machine-readable context.

## 47.2 Specific errors for specific conditions

Fifteen error classes rather than one with a message. The difference matters
at the call site:

```python
except ConcurrentModificationError:
    # Retry: the next attempt may well succeed.
except InsufficientStockError:
    # Do not retry: it will fail identically.
```

*Listing 47.2. Why error type matters more than error message.*

A single exception type would force string matching to make that distinction,
and string matching on error messages breaks the first time someone improves
the wording.

## 47.3 Details carry the rule

```python
raise ForbiddenError(
    "a donor cannot verify their own donation",
    details={"rule": "SELF_VERIFICATION_FORBIDDEN"},
)
```

*Listing 47.3. A named rule in the details.*

The message is for a human; the rule name is for a client developer, who can
branch on it or display a specific explanation.

## 47.4 Translating infrastructure errors

{{include:backend/src/repositories/dynamo.py:def translate_client_error}}

*Listing 47.4. DynamoDB errors mapped onto the domain taxonomy.*

Nothing above the repository layer sees a `ClientError`. Transaction
cancellations are unpacked so a conditional-check failure becomes a
concurrency error rather than an opaque "transaction cancelled".

## 47.5 The boundary

{{include:backend/src/handlers/router.py:anchor:except LifeLinkError as exc::14}}

*Listing 47.5. The edge of the system.*

Domain errors keep their code and status. Anything else becomes a generic 500
with a correlation id — the detail goes to the log, never to the client,
because an exception message can disclose internals.

<!-- pagebreak -->

# 48. The Design Token System

## 48.1 Why tokens rather than values

Every colour, space, radius and font size is a custom property on `:root`.
Changing the brand crimson is one edit. More importantly, a component cannot
invent a colour that is almost but not quite the right one, which is how
interfaces drift.

## 48.2 Status colours are chosen for contrast, not decoration

{{include:frontend/src/styles/tokens.css:anchor:/* Status: data freshness */:10}}

*Listing 48.1. Freshness tokens from `frontend/src/styles/tokens.css`.*

Each status has a foreground and a background chosen together to meet contrast
requirements, rather than a single colour applied to text on white.

## 48.3 No status relies on colour alone

Every badge carries a text label and a distinct glyph. The interface works in
greyscale, in print, and for a colour-blind user. For a service used under
pressure that is a requirement rather than a nicety.

## 48.4 Focus is always visible

```css
:focus-visible {
  outline: none;
  box-shadow: var(--focus-ring);
  border-radius: var(--radius-sm);
}
```

*Listing 48.2. A visible focus ring everywhere.*

`:focus-visible` rather than `:focus` so a mouse click does not leave a ring,
while keyboard navigation always shows one.

## 48.5 Reduced motion is respected

A `prefers-reduced-motion` block reduces every animation and transition to
effectively zero. The only animation in the application is a loading spinner,
but honouring the preference costs four lines.

## 48.6 The demo banner cannot be dismissed

```css
.demo-banner {
  position: sticky;
  top: 0;
  z-index: 60;
```

*Listing 48.3. A banner that stays.*

There is no close button, and the sticky positioning keeps it visible while
scrolling. A banner a user can close is one they will close, after which a
screenshot of invented blood stock is indistinguishable from real institutional
data.

<!-- pagebreak -->

# 49. The Documentation Toolchain

The books you are reading are built by code in this repository, and that code
is part of the implementation rather than incidental to it.

## 49.1 Why generate rather than write

The specification requires the books to be generated from the actual
implementation and to avoid inventing classes, APIs or test results. Prose can
be checked by a reviewer; code listings and metrics cannot be checked at a
glance, and they are exactly what goes stale.

The resolution is to make staleness a build failure.

## 49.2 Directives

Each of the following is written in the source wrapped in double braces. They
are shown here without them, because a directive printed in a book that the
same tool builds would be resolved rather than displayed — a small reminder
that a templating language needs an escape hatch.

| Directive body | Resolves to |
|---|---|
| `include:path:def name` | That function, located by parsing the file |
| `include:path:anchor:TEXT:N` | N lines from the first line containing TEXT |
| `include:path:START-END` | Raw line numbers, discouraged and warned about |
| `fact:name` | A measured value |
| `routes:filter` | A table read from the live router |

*Table 49.1. The directive vocabulary.*

An unresolvable directive is a build failure, so a renamed function breaks the
book build rather than silently leaving a book describing a function that no
longer exists.

## 49.3 Why anchors replaced line numbers

{{include:scripts/bookgen/facts.py:def _extract_region}}

*Listing 49.1. Region extraction from `scripts/bookgen/facts.py`.*

The docstring records the incident that motivated it. A listing captioned "the
audit IAM grant" was selected by line number; an unrelated edit to the template
shifted the file, and the listing silently began showing SQS queue
configuration under a caption about IAM policy.

The failure mode is the worst kind: the output was well-formed, plausible and
wrong. Line-number includes now produce a build warning.

## 49.4 Facts are measured

{{include:scripts/bookgen/facts.py:def collect_test_results}}

*Listing 49.2. Test measurement.*

Two details worth noting.

Quiet mode is deliberately not used, because in this pytest version `-q`
suppresses the summary line — and a missing summary previously produced a
recorded count of **zero**, which would have put a false test result in three
books.

Anything unparseable is recorded as `COULD NOT MEASURE` rather than as a
number. A figure that cannot be measured must not be invented, and zero is an
invention.

## 49.5 Validation

Every build opens the produced PDF and checks it:

| Check | Catches |
|---|---|
| File exists and opens | A build that silently produced nothing |
| Page count | A book far shorter than intended |
| No blank pages in the body | Double page breaks and widows |
| No content outside the page | Clipped tables and overflowing code |
| No unresolved directives | A renamed function or missing fact |
| Diagrams rendered | A diagram DSL change that produced nothing |
| Contents page numbers exact | Layout drift between passes |

*Table 49.2. The seven checks, each of which has caught something.*

## 49.6 The blank-page lesson

The blank-page check is the one worth describing, because the first version of
it did not work.

It measured whether a page had extractable text. Every page passed — because
the running header and footer are drawn on every page, so a page containing
nothing else still yielded sixty characters of text.

The fix measures only the body frame, excluding the header and footer bands.
It immediately found blank pages caused by a chapter heading emitting a page
break when the source already contained one, and the honest page count of each
book dropped substantially once they were removed.

:::key A validation check that cannot fail is not a check
The first version reported PASS on every page of a book that contained blank
pages. It is worth asking, of any check that always passes, whether it is
measuring the thing you believe it is.
:::

## 49.7 Diagrams are vector, not ASCII

{{include:scripts/bookgen/diagrams.py:anchor:def render_layered:10}}

*Listing 49.3. Layered diagram rendering from
`scripts/bookgen/diagrams.py`.*

Diagrams are declared in a small DSL and rendered as ReportLab vector
graphics. The DSL has no free-form positioning — nodes sit on a grid of layers
and columns — which makes overlapping boxes impossible rather than merely
unlikely.

## 49.8 The code highlighter, and a bug worth remembering

The first highlighter applied successive regular expressions: keywords, then
strings, then comments. It produced malformed markup and a parse failure.

The cause is instructive. The keyword pass inserted
`<font color='#7a0f1d'>`, and the string pass then matched `'#7a0f1d'` —
which looks exactly like a string literal — and wrapped it again, producing
nested and unbalanced tags.

The fix is a single tokenising pass that classifies each region once. The
general lesson is that chained substitutions on a string are a pipeline where
each stage can match the previous stage's output.

<!-- pagebreak -->

# 50. A Checklist for the Next Engineer

## 50.1 Before you change anything

- Run the suite: `pytest tests` in `backend`. It takes seconds.
- Read the relevant architecture decision record.
- Find the test that pins the behaviour you are about to change. If there is
  none, that is worth knowing before you start.

## 50.2 While you work

- Put rules in `domain/`, workflows in `services/`, storage in
  `repositories/`. If you are unsure which, the rule is usually: can it be
  tested without AWS? Then it belongs in `domain/`.
- Inject time rather than reading the clock.
- Return reasons rather than booleans.
- Name the rule in the error details.
- If you add a route, declare its permission and run the OpenAPI generator.

## 50.3 Before you commit

| Command | Must show |
|---|---|
| `pytest tests` | all passing |
| `ruff check src tests` | clean |
| `npm test` in `frontend` | all passing |
| `npm run build` in `frontend` | builds |
| `generate_openapi.py --check` | matches |
| `cfn-lint infrastructure/template.yaml` | no findings |
| `build_books.py --no-tests` | all books validated |
| `git diff --cached` | no secrets, no `.env`, no keys |

*Table 50.1. The pre-commit checklist.*

The last row matters most. `.gitignore` covers `.env`, `.local-keys/` and
credentials, but reading the diff is the check that catches what a pattern
missed.

## 50.4 Things that will surprise you

**`-q` hides pytest's summary** in this version, which is why the fact
collector does not use it.

**npm is not on the Git Bash PATH** on this machine. Use PowerShell, or the
full path.

**An unused DynamoDB expression placeholder** produces a `ValidationException`
that names nothing useful. If an update suddenly fails, compare the
placeholders in the expression with the keys of the values dictionary.

**Renaming a function breaks the book build.** That is intended. Update the
anchor.

**The `appcore` package is named that way deliberately.** Do not rename it to
`platform`; it would shadow the standard-library module that botocore imports.
