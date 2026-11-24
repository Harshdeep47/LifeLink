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
