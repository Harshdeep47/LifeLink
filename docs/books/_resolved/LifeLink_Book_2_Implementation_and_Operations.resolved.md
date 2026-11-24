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
| Backend source | 43 | 12806 |
| Backend tests | 22 files | 5516 |
| Frontend source | 60 | 12750 |
| Infrastructure | 1 template | 1490 |

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
mocks and no AWS, which is why 22 test files run in
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
| Python | 3.14.2 | Yes |
| Node.js | 26.13.1 | For the frontend |
| Java | 26 | Only for the optional DynamoDB Local path |
| AWS SAM CLI | 1.172.1 | For template validation |
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

```python
@dataclass
class LocalTokenVerifier:
    """Local-development verifier (ADR-0011).

    Issues and verifies RS256 tokens with the same claim shape as Cognito using a
    dev keypair. The *verification path* is identical in structure to production;
    only the key source differs. This is a documented divergence, never presented
    as having tested Cognito itself.
    """

    public_key_pem: bytes
    issuer: str = "lifelink-local"

    def __post_init__(self) -> None:
        # A missing key file used to produce an empty byte string here, which
        # made every token fail to verify with a confusing error rather than
        # saying the key was absent. Refuse at construction instead: an
        # authenticator that cannot verify anything must not be built.
        if not self.public_key_pem or not self.public_key_pem.strip():
            raise EnvironmentConfigurationError(
                "the local development verifier was constructed without a public "
                "key. Run 'python scripts/dev.py keys' to generate the local "
                "keypair, or set LOCAL_JWT_PUBLIC_KEY to its path."
            )

    def verify(self, token: str) -> dict:
        try:
            claims = jwt.decode(
                token,
                self.public_key_pem,
                algorithms=["RS256"],
                issuer=self.issuer,
                options={"verify_aud": False, "require": ["exp", "iss", "sub"]},
            )
        except jwt.ExpiredSignatureError:
            raise UnauthenticatedError("token has expired") from None
        except jwt.InvalidTokenError as exc:
            raise UnauthenticatedError(f"invalid token: {exc}") from None
        return claims
```

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

```python
def parse_iso(value: str | datetime | None) -> datetime | None:
    """Parse ISO-8601 into an aware UTC datetime. Returns None for None/empty.

    A string without timezone information is rejected rather than assumed to be UTC --
    silently guessing the zone is how expiry bugs get introduced (spec 12.1).
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("naive datetime is not accepted")
        return value.astimezone(UTC)
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp '{value}' has no timezone designator")
    return parsed.astimezone(UTC)
```

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

```python
def verification_status(
    last_verified_at: datetime | None,
    now: datetime,
    validity_hours: float = VERIFICATION_VALIDITY_HOURS,
) -> VerificationStatus:
    """Independent human verification state -- deliberately separate from freshness."""
    if last_verified_at is None:
        return VerificationStatus.UNVERIFIED
    age = hours_between(last_verified_at, now)
    if age < 0:
        return VerificationStatus.UNVERIFIED
    if age <= validity_hours:
        return VerificationStatus.VERIFIED
    return VerificationStatus.VERIFICATION_EXPIRED
```

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

```python
def evaluate_batch_eligibility(
    *,
    status: BatchStatus | str,
    available_units: int | None,
    expires_at: datetime | None,
    collected_at: datetime | None,
    now: datetime,
    require_expiry: bool = True,
) -> EligibilityResult:
    """Decide whether a batch may be presented as available stock.

    Fails closed: anything ambiguous is ineligible. Spec 3.4 is explicit that
    invalid or missing dates must not silently produce eligible stock.
    """
    reasons: list[str] = []

    status = BatchStatus(status) if not isinstance(status, BatchStatus) else status

    if status == BatchStatus.QUARANTINED:
        reasons.append(REASON_QUARANTINED)
    elif status == BatchStatus.WITHDRAWN:
        reasons.append(REASON_WITHDRAWN)
    elif status == BatchStatus.CONSUMED:
        reasons.append(REASON_CONSUMED)
    elif status == BatchStatus.EXPIRED:
        reasons.append(REASON_EXPIRED)

    if available_units is None or available_units < 0:
        reasons.append(REASON_NEGATIVE_UNITS)
    elif available_units == 0:
        reasons.append(REASON_NO_UNITS)

    if expires_at is None:
        if require_expiry:
            reasons.append(REASON_MISSING_EXPIRY)
    else:
        if collected_at is not None and expires_at <= collected_at:
            # Expiry before collection is incoherent data, not merely expired stock.
            reasons.append(REASON_INVALID_EXPIRY)
        elif expires_at <= now and REASON_EXPIRED not in reasons:
            reasons.append(REASON_EXPIRED)

    return EligibilityResult(eligible=not reasons, reasons=tuple(reasons))
```

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

```python
def summarise_availability(
    *,
    batches: list[Batch],
    blood_group: BloodGroup,
    component: Component,
    requested_units: int,
    now: datetime,
    inventory_known: bool = True,
) -> AvailabilitySummary:
    """Aggregate eligible stock for one (group, component) at one facility.

    ``inventory_known=False`` means this facility has never reported inventory.
    That produces UNKNOWN -- never zero. The spec is explicit that unknown must
    not be silently converted, because "we have no data" and "they have none"
    lead a user to completely different actions.
    """
    relevant = [
        b for b in batches if b.blood_group == blood_group and b.component == component
    ]

    if not inventory_known:
        return AvailabilitySummary(
            blood_group=blood_group,
            component=component,
            state=AvailabilityState.UNKNOWN,
            # Not 0. "We do not know" and "there are none" lead a user to
            # opposite actions: one calls the facility, the other does not.
            eligible_units=None,
            batch_count=0,
            freshness=FreshnessLabel.UNKNOWN,
            near_expiry_units=0,
            earliest_expiry=None,
        )

    eligible_units = 0
    near_expiry_units = 0
    expiries: list[datetime] = []
    newest_update: datetime | None = None
    eligible_batches = 0

    for b in relevant:
        result = evaluate_batch_eligibility(
            status=b.status,
            available_units=b.available_units,
            expires_at=b.expires_at,
            collected_at=b.collected_at,
            now=now,
        )
        if not result.eligible:
            continue
        eligible_batches += 1
        eligible_units += b.available_units
        if b.expires_at is not None:
            expiries.append(b.expires_at)
            if is_near_expiry(b.expires_at, now):
                near_expiry_units += b.available_units
        if newest_update is None or b.last_updated_at > newest_update:
            newest_update = b.last_updated_at

    if eligible_units == 0:
        state = AvailabilityState.UNAVAILABLE
    elif requested_units > 0 and eligible_units < requested_units:
        state = AvailabilityState.PARTIAL
    else:
        state = AvailabilityState.AVAILABLE

    # Freshness of the summary reflects the most recently updated relevant batch.
    # If nothing is eligible we still report the freshness of the underlying data
    # so the user can tell "stale data" apart from "genuinely none in stock".
    if newest_update is None and relevant:
        newest_update = max(b.last_updated_at for b in relevant)

    return AvailabilitySummary(
        blood_group=blood_group,
        component=component,
        state=state,
        eligible_units=eligible_units,
        batch_count=eligible_batches,
        freshness=freshness_label(newest_update, now),
        near_expiry_units=near_expiry_units,
        earliest_expiry=min(expiries) if expiries else None,
    )
```

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

```python
def apply_stock_operation(
    *,
    batch: Batch,
    operation: StockOperation,
    units: int | None,
    now: datetime,
    source: str,
    reason: str | None = None,
) -> StockChange:
    """Compute the post-operation batch, refusing to produce an invalid state.

    Never allows a negative available quantity -- the spec forbids it outright,
    and the repository re-asserts it in a condition expression so a concurrent
    writer cannot slip past this check.
    """
    if operation in (StockOperation.ADD, StockOperation.DEDUCT, StockOperation.CORRECT):
        if units is None:
            raise ValidationError(f"{operation.value} requires a unit count")
        if units < 0:
            raise ValidationError("unit count cannot be negative")
        if operation != StockOperation.CORRECT and units == 0:
            raise ValidationError(f"{operation.value} requires a non-zero unit count")

    previous_units = batch.available_units
    previous_status = batch.status
    new_units = previous_units
    new_status = batch.status
    quarantine_reason = batch.quarantine_reason

    if operation == StockOperation.ADD:
        if batch.status != BatchStatus.AVAILABLE:
            raise InvalidStateTransitionError(
                f"cannot add units to a {batch.status.value} batch",
                details={"status": batch.status.value},
            )
        new_units = previous_units + units  # type: ignore[operator]

    elif operation == StockOperation.DEDUCT:
        if batch.status != BatchStatus.AVAILABLE:
            raise InvalidStateTransitionError(
                f"cannot deduct units from a {batch.status.value} batch",
                details={"status": batch.status.value},
            )
        if units > previous_units:  # type: ignore[operator]
            raise InsufficientStockError(
                f"cannot deduct {units} units; only {previous_units} available",
                details={"requested": units, "available": previous_units},
            )
        new_units = previous_units - units  # type: ignore[operator]
        if new_units == 0:
            new_status = BatchStatus.CONSUMED

    elif operation == StockOperation.CORRECT:
        # A correction sets an absolute value and is only for authorised staff
        # fixing a data error. It is audited distinctly from add/deduct.
        new_units = units  # type: ignore[assignment]
        if new_units == 0 and batch.status == BatchStatus.AVAILABLE:
            new_status = BatchStatus.CONSUMED
        elif new_units > 0 and batch.status == BatchStatus.CONSUMED:
            new_status = BatchStatus.AVAILABLE

    elif operation == StockOperation.QUARANTINE:
        if batch.status not in (BatchStatus.AVAILABLE,):
            raise InvalidStateTransitionError(
                f"cannot quarantine a {batch.status.value} batch"
            )
        if not reason:
            raise ValidationError("quarantine requires a reason")
        new_status = BatchStatus.QUARANTINED
        quarantine_reason = reason

    elif operation == StockOperation.RELEASE_QUARANTINE:
        if batch.status != BatchStatus.QUARANTINED:
            raise InvalidStateTransitionError("batch is not quarantined")
        # Releasing never resurrects expired stock.
        if batch.expires_at is not None and batch.expires_at <= now:
            new_status = BatchStatus.EXPIRED
        else:
            new_status = BatchStatus.AVAILABLE
        quarantine_reason = None

    elif operation == StockOperation.WITHDRAW:
        if batch.status in (BatchStatus.CONSUMED, BatchStatus.WITHDRAWN):
            raise InvalidStateTransitionError(
                f"cannot withdraw a {batch.status.value} batch"
            )
        new_status = BatchStatus.WITHDRAWN

    elif operation == StockOperation.EXPIRE:
        if batch.expires_at is None or batch.expires_at > now:
            raise InvalidStateTransitionError("batch has not reached its expiry time")
        new_status = BatchStatus.EXPIRED

    if new_units < 0:
        raise InsufficientStockError("operation would produce negative stock")

    updated = replace(
        batch,
        available_units=new_units,
        status=new_status,
        quarantine_reason=quarantine_reason,
        last_updated_at=now,
        update_source=source,
        version=batch.version + 1,
    )

    return StockChange(
        batch=updated,
        units_delta=new_units - previous_units,
        operation=operation,
        previous_units=previous_units,
        previous_status=previous_status,
        reason=reason,
    )
```

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

```python
def permissions_for(roles: list[str] | set[str] | tuple[str, ...]) -> frozenset[Permission]:
    """Union of permissions across all of a user's roles."""
    granted: set[Permission] = set()
    for raw in roles:
        try:
            role = Role(raw)
        except ValueError:
            continue  # unknown role grants nothing
        granted |= ROLE_PERMISSIONS.get(role, frozenset())
    return frozenset(granted)
```

*Listing 4.1. Role-to-permission resolution from `backend/src/appcore/rbac.py`.*

There are 39 permissions across 10
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

```python
@dataclass(frozen=True, slots=True)
class Principal:
    """The authenticated caller, as resolved from the database -- not from token claims.

    Roles come from the stored user record so that a role revoked mid-session
    takes effect on the next request rather than when the token happens to expire.
    """

    user_id: str
    email: str | None
    roles: tuple[str, ...]
    organization_id: str | None
    account_status: str
    display_name: str | None = None

    @property
    def is_active(self) -> bool:
        return self.account_status == "ACTIVE"

    @property
    def permissions(self) -> frozenset[Permission]:
        return permissions_for(self.roles)

    def has(self, permission: Permission) -> bool:
        return permission in self.permissions
```

*Listing 4.2. The principal from `backend/src/appcore/context.py`.*

The docstring records the reason: roles come from the stored user record so a
revoked role takes effect on the next request. A `Principal` built from token
claims would be stale for up to an hour.

## 4.5 Logging that cannot leak

```python
SENSITIVE_KEYS: frozenset[str] = frozenset({
    "password", "passwd", "secret", "token", "accesstoken", "refreshtoken",
    "idtoken", "authorization", "apikey", "api_key", "sessiontoken",
    "secretaccesskey", "privatekey", "credential", "credentials",
    "ssn", "aadhaar", "pan", "otp", "pin",
    # Contact details and precise location are personal data; they are logged
    # only in redacted form. Spec 4.2 also warns against storing precise
    # coordinates unnecessarily.
    "email", "phone", "mobile", "contactnumber", "contactemail",
    "latitude", "longitude", "address", "dateofbirth", "dob",
})

REDACTED = "[REDACTED]"
MAX_STRING_LENGTH = 2000
```

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

```python
def decode_cursor(cursor: str | None, query_fingerprint: str) -> dict | None:
    from domain.errors import ValidationError

    if not cursor:
        return None
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        parsed = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
    except Exception:
        raise ValidationError("malformed pagination cursor") from None
    if parsed.get("q") != query_fingerprint:
        raise ValidationError(
            "pagination cursor does not belong to this query",
            details={"hint": "restart pagination without a cursor"},
        )
    return parsed.get("k")
```

*Listing 4.5. Cursor decoding from `backend/src/appcore/responses.py`.*

The cursor embeds a fingerprint of the query that produced it. Presenting a
cursor from one search against a different search is rejected rather than
silently returning results from the wrong result set — a bug that would be
nearly impossible to notice in testing and quite possible to hit in production.

<!-- pagebreak -->

# 5. Authentication Middleware

## 5.1 The decorator

```python
def requires(
    permission: Permission | None = None,
    *,
    resource_owner: ResourceOwnerResolver | None = None,
    allow_anonymous: bool = False,
):
    """Wrap a handler with authentication, permission and organization checks.

    ``resource_owner`` is how IDOR is prevented: the handler declares how to find
    the owning organization of the thing being touched, and the comparison happens
    here rather than inside the handler where it can be forgotten.
    """

    def decorator(handler: Callable[[dict, RequestContext], dict]):
        @functools.wraps(handler)
        def wrapper(event: dict, context: RequestContext) -> dict:
            principal = context.principal

            # A protected route must still refuse a bad token. If
            # build_context captured a failure, surface it here with its
            # original reason -- "token has expired" is far more useful to a
            # client than a generic "authentication required".
            if not allow_anonymous and context.auth_error is not None:
                raise context.auth_error

            if not allow_anonymous and principal is ANONYMOUS:
                raise UnauthenticatedError("authentication required")

            # A valid token from a suspended account must not act (spec 8.1).
            if principal is not ANONYMOUS and not principal.is_active:
                raise AccountSuspendedError(
                    "this account is not active",
                    details={"accountStatus": principal.account_status},
                )

            if permission is not None and not principal.has(permission):
                raise ForbiddenError(
                    "you do not have permission to perform this action",
                    details={"required": permission.value},
                )

            if permission is not None and is_organization_scoped(permission) and resource_owner:
                owner_org = resource_owner(event, context)
                if owner_org is not None:
                    if principal.organization_id is None:
                        raise CrossOrganizationError(
                            "this action requires organization membership"
                        )
                    if owner_org != principal.organization_id:
                        # Deliberately does not reveal which organization owns it.
                        raise CrossOrganizationError(
                            "this resource belongs to another organization"
                        )

            return handler(event, context)

        wrapper.__lifelink_permission__ = permission  # type: ignore[attr-defined]
        wrapper.__lifelink_protected__ = True  # type: ignore[attr-defined]
        wrapper.__lifelink_allows_anonymous__ = allow_anonymous  # type: ignore[attr-defined]
        return wrapper

    return decorator
```

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

```python
def build_context(
    event: dict,
    authenticator: Authenticator | None = None,
) -> RequestContext:
    """Construct the per-request context from an API Gateway-style event."""
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    correlation_id = headers.get("x-correlation-id") or new_correlation_id()

    principal = ANONYMOUS
    auth_error: Exception | None = None
    if authenticator is not None:
        try:
            principal = authenticator.authenticate(headers.get("authorization"))
        except LifeLinkError as exc:
            # Deliberately captured, not raised.
            #
            # This used to raise here, which meant a single unusable token --
            # expired, malformed, or belonging to a subject with no LifeLink
            # profile -- returned 401 from *every* route, including the public
            # ones. A signed-in user whose session had gone stale could not
            # browse blood availability, see facilities, or load the reference
            # data the home page needs. The failure had nothing to do with the
            # page they were on.
            #
            # The authorization decision belongs to requires(), which knows
            # whether the route tolerates an anonymous caller. It re-raises this
            # for every protected route, so nothing is weakened: a bad token
            # still cannot reach a protected handler.
            auth_error = exc
            principal = ANONYMOUS

    request_context = event.get("requestContext") or {}
    identity = request_context.get("identity") or {}
    http = request_context.get("http") or {}

    return RequestContext(
        correlation_id=correlation_id,
        principal=principal,
        source_ip=identity.get("sourceIp") or http.get("sourceIp"),
        user_agent=headers.get("user-agent"),
        idempotency_key=headers.get("idempotency-key"),
        auth_error=auth_error,
    )
```

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

```python
def to_expression_values(values: dict) -> dict:
    """Serialize ExpressionAttributeValues, preserving None.

    Deliberately different from ``to_dynamo``, which drops None so that an
    optional attribute is simply absent from a stored item. That is wrong here:
    an update expression that references ``:reason`` must be given ``:reason``,
    and silently dropping it makes DynamoDB reject the entire request with
    ValidationException. A None becomes a NULL attribute instead.
    """
    serialized: dict[str, Any] = {}
    for key, value in values.items():
        if value is None:
            serialized[key] = None
        elif isinstance(value, float):
            serialized[key] = Decimal(str(value))
        elif isinstance(value, dict):
            serialized[key] = {k: to_dynamo(v) for k, v in value.items()}
        elif isinstance(value, (list, tuple)):
            serialized[key] = [to_dynamo(v) for v in value]
        else:
            serialized[key] = to_dynamo(value)
    return serialized
```

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

```python
def put(self, item: dict, *, condition=None, on_conflict: str = "duplicate") -> dict:
    """Write an item, optionally guarded by a condition.

    ``on_conflict`` says what a failed condition *means*, because the two
    cases need different errors and different client behaviour:

    * ``"duplicate"`` -- the condition was a uniqueness check
      (``attribute_not_exists``), so a failure means the record already
      exists. The caller should not retry.
    * ``"version"`` -- the condition was an optimistic-concurrency check, so
      a failure means someone else wrote first. The caller should re-read and
      retry, which is what the service layer does on
      ConcurrentModificationError.

    Returning DuplicateError for a version conflict would be actively
    harmful: the retry path would never trigger and the user would be told
    the record already exists.
    """
    kwargs: dict[str, Any] = {"Item": clean(item)}
    if condition is not None:
        kwargs["ConditionExpression"] = condition
    try:
        self.table.put_item(**kwargs)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code == "ConditionalCheckFailedException" and condition is not None:
            if on_conflict == "version":
                raise ConcurrentModificationError(
                    "the record changed while this operation was in flight",
                    details={"table": self.logical_table, "hint": "re-read and retry"},
                ) from exc
            raise DuplicateError(
                "a record with this identity already exists",
                details={"table": self.logical_table},
            ) from exc
        raise translate_client_error(exc, context=self.logical_table) from exc
    return item
```

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

```python
def translate_client_error(exc: ClientError, *, context: str = "") -> LifeLinkError:
    code = exc.response.get("Error", {}).get("Code", "")
    if code == "ConditionalCheckFailedException":
        return ConcurrentModificationError(
            f"the record changed while this operation was in flight{': ' + context if context else ''}",
            details={"hint": "re-read the record and retry"},
        )
    if code == "TransactionCanceledException":
        reasons = exc.response.get("CancellationReasons", []) or []
        codes = [r.get("Code") for r in reasons]
        if "ConditionalCheckFailed" in codes:
            return ConcurrentModificationError(
                "a concurrent change prevented this transaction from completing",
                details={"reasons": codes},
            )
        if "TransactionConflict" in codes:
            return ConcurrentModificationError(
                "another transaction is modifying these records",
                details={"reasons": codes},
            )
        return LifeLinkError(f"transaction cancelled: {codes}")
    if code in ("ProvisionedThroughputExceededException", "ThrottlingException",
                "RequestLimitExceeded"):
        from domain.errors import RateLimitedError

        return RateLimitedError("the datastore is throttling requests; retry shortly")
    if code == "ResourceNotFoundException":
        from domain.errors import NotFoundError

        return NotFoundError(f"storage table not found{': ' + context if context else ''}")
    return LifeLinkError(f"datastore error ({code}){': ' + context if context else ''}")
```

*Listing 6.3. Mapping DynamoDB errors onto the domain taxonomy.*

Transaction cancellations are unpacked: a `ConditionalCheckFailed` reason
becomes a concurrency error, a `TransactionConflict` becomes the same with a
different detail, and anything else is reported with its reason codes rather
than as an opaque failure.

## 6.5 Scans are forbidden on user-facing paths

`query_all` exists and pages to completion, but with a hard ceiling:

```python
def query_all(self, *, key_condition, index_name: str | None = None,
              filter_expression=None, max_items: int = 1000) -> list[dict]:
    """Page through a query to completion, with a hard ceiling.

    The ceiling exists so a pathological partition cannot turn one request
    into an unbounded read -- which at this account's concurrency limit would
    be felt immediately.
    """
    collected: list[dict] = []
    start_key = None
    while True:
        items, start_key = self.query(
            key_condition=key_condition,
            index_name=index_name,
            exclusive_start_key=start_key,
            filter_expression=filter_expression,
        )
        collected.extend(items)
        if not start_key or len(collected) >= max_items:
            break
    return collected[:max_items]
```

*Listing 6.4. Bounded pagination.*

The ceiling means a pathological partition cannot turn one request into an
unbounded read. At a Lambda concurrency ceiling of 10,
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

```python
def batch_to_item(batch: Batch) -> dict[str, Any]:
    return {
        "PK": _batch_pk(batch.facility_id),
        "SK": _batch_sk(batch.batch_id),
        "entityType": "BATCH",
        "batchId": batch.batch_id,
        "facilityId": batch.facility_id,
        "organizationId": batch.organization_id,
        "bloodGroup": batch.blood_group.value,
        "component": batch.component.value,
        "availableUnits": batch.available_units,
        "status": batch.status.value,
        "collectedAt": to_iso(batch.collected_at),
        "expiresAt": to_iso(batch.expires_at),
        "lastUpdatedAt": to_iso(batch.last_updated_at),
        "lastVerifiedAt": to_iso(batch.last_verified_at),
        "updateSource": batch.update_source,
        "version": batch.version,
        "quarantineReason": batch.quarantine_reason,
        "GSI1PK": _gsi1_pk(batch.facility_id, batch.blood_group.value, batch.component.value),
        "GSI1SK": _gsi1_sk(batch.status.value, batch.expires_at),
        "GSI2PK": f"EXPIRY_SHARD#{expiry_shard(batch.batch_id)}",
        "GSI2SK": to_iso(batch.expires_at) or "9999-12-31T23:59:59Z",
    }
```

*Listing 7.1. Item construction from `backend/src/repositories/inventory_repo.py`.*

Every index attribute is computed from the batch's own fields. There is no code
path that writes a `GSI1SK` independently of the status and expiry it encodes,
so the index cannot drift out of agreement with the item.

## 7.3 The conditional write

```python
def apply_change(self, change: StockChange, *, expected_version: int) -> Batch:
    """Persist a stock change with an optimistic-concurrency guard.

    The condition asserts the version we read is still current AND, for
    deductions, that enough units remain. A concurrent writer that got there
    first fails this check and surfaces as 409 rather than silently
    overwriting -- the lost-update problem, closed.
    """
    batch = change.batch
    item = batch_to_item(batch)

    condition = Attr("version").eq(expected_version)
    if change.units_delta < 0:
        # Re-assert non-negativity at the storage layer.
        condition = condition & Attr("availableUnits").gte(abs(change.units_delta))

    # A failed condition here is a version conflict, not a duplicate, so the
    # caller gets ConcurrentModificationError and its retry path engages.
    self.put(item, condition=condition, on_conflict="version")
    return batch
```

*Listing 7.2. The optimistic-concurrency write.*

Two conditions: the version is unchanged, and for deductions enough units
remain. The second is redundant with the domain check that already ran — and
that redundancy is the point. Between the read and the write, another request
may have taken the stock.

## 7.4 Verification writes only verification fields

```python
def record_verification(
    self, *, facility_id: str, batch_id: str, verified_at: datetime,
    verified_by: str, expected_version: int
) -> dict:
    """Write ONLY the verification fields.

    ADR-0003: this is the single code path permitted to set
    ``lastVerifiedAt``. No other repository method touches it, so an
    automated feed can never imply human verification.
    """
    # Every declared placeholder must be referenced by an expression, or
    # DynamoDB rejects the whole request with ValidationException. The
    # condition below builds its own placeholders, so none is added here.
    return self.update(
        pk=_batch_pk(facility_id),
        sk=_batch_sk(batch_id),
        update_expression="SET lastVerifiedAt = :at, verifiedBy = :by, #v = :next",
        expression_values={
            ":at": to_iso(verified_at),
            ":by": verified_by,
            ":next": expected_version + 1,
        },
        expression_names={"#v": "version"},
        condition=Attr("version").eq(expected_version),
    )
```

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

```python
def adjust_stock(
    self,
    *,
    context: RequestContext,
    facility_id: str,
    batch_id: str,
    operation: str,
    units: int | None,
    now: datetime,
    reason: str | None = None,
    source: str = "MANUAL",
    max_retries: int = 3,
) -> dict:
    """Apply a stock operation with optimistic concurrency and bounded retry.

    A concurrent writer causes the conditional write to fail; we re-read and
    recompute rather than retrying the stale decision, then give up with a
    409 so the caller is never told a stale result succeeded.
    """
    log = get_logger(__name__, context)
    try:
        op = StockOperation(operation.strip().upper())
    except ValueError:
        raise ValidationError(
            f"unknown stock operation '{operation}'",
            details={"allowed": [o.value for o in StockOperation]},
        ) from None

    attempt = 0
    while True:
        attempt += 1
        batch = self._inventory.get_batch(facility_id, batch_id)
        if batch is None:
            raise NotFoundError("batch not found", details={"batchId": batch_id})

        expected_version = batch.version
        change = apply_stock_operation(
            batch=batch, operation=op, units=units, now=now, source=source, reason=reason
        )

        audit_item = self._audit.build_item(
            actor_id=context.actor_id,
            actor_role=",".join(context.principal.roles),
            action=f"INVENTORY_{op.value}",
            resource_type="BATCH",
            resource_id=batch_id,
            organization_id=batch.organization_id,
            correlation_id=context.correlation_id,
            occurred_at=now,
            before={"units": change.previous_units, "status": change.previous_status.value},
            after={"units": change.batch.available_units, "status": change.batch.status.value},
            metadata={"reason": reason, "source": source},
        )
        audit_item = {
            **audit_item,
            "PK": f"BATCH#{batch_id}",
            "SK": f"AUDIT#{to_iso(now)}#{audit_item['eventId']}",
        }

        outbox_item = self._outbox.build_event(
            event_type="InventoryStockChanged",
            payload={
                "batchId": batch_id,
                "facilityId": facility_id,
                "bloodGroup": batch.blood_group.value,
                "component": batch.component.value,
                "unitsDelta": change.units_delta,
                "availableUnits": change.batch.available_units,
                "status": change.batch.status.value,
                "operation": op.value,
            },
            correlation_id=context.correlation_id,
            occurred_at=now,
            aggregate_id=batch_id,
        )

        try:
            updated = self._inventory.apply_change_with_audit(
                change,
                expected_version=expected_version,
                audit_item=audit_item,
                outbox_item=outbox_item,
            )
        except ConcurrentModificationError:
            if attempt > max_retries:
                log.warning(
                    "giving up after concurrent modification",
                    event="inventory.conflict.exhausted",
                    batchId=batch_id, attempts=attempt,
                )
                raise
            log.info("retrying after concurrent modification",
                     event="inventory.conflict.retry", batchId=batch_id, attempt=attempt)
            continue

        self._facilities.touch_inventory_timestamp(facility_id, updated_at=to_iso(now))
        log.info("stock adjusted", event="inventory.stock.adjusted",
                 batchId=batch_id, operation=op.value, delta=change.units_delta)
        return self._present_batch(updated, now)
```

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

```python
def facility_availability(
    self,
    *,
    facility_id: str,
    now: datetime,
    groups: list[BloodGroup] | None = None,
    components: list[Component] | None = None,
    requested_units: int = 1,
) -> dict:
    """Availability matrix for one facility.

    ``inventoryKnown`` is read from the facility record. A facility that has
    never reported inventory yields UNKNOWN for every combination, never
    zero -- the distinction the spec insists on.
    """
    facility = self._facilities.get_facility(facility_id)
    if facility is None:
        raise NotFoundError("facility not found", details={"facilityId": facility_id})

    inventory_known = bool(facility.get("inventoryKnown", False))
    groups = groups or list(ALL_GROUPS)
    components = components or list(ALL_COMPONENTS)

    matrix: list[dict] = []
    for group in groups:
        for component in components:
            batches = (
                self._inventory.list_eligible_batches(facility_id, group, component, now=now)
                if inventory_known
                else []
            )
            summary = summarise_availability(
                batches=batches,
                blood_group=group,
                component=component,
                requested_units=requested_units,
                now=now,
                inventory_known=inventory_known,
            )
            # Reserved units are deducted so a held unit is not offered
            # twice. reservedUnits is reported alongside, because a user
            # who can see *why* a figure dropped trusts it more than one
            # who just sees a smaller number.
            reserved = 0
            free = summary.eligible_units
            if self._reservations is not None and inventory_known:
                free, reserved = self._reservations.adjust_availability(
                    facility_id, group, component, summary.eligible_units, now=now
                )
            matrix.append(
                {
                    "bloodGroup": group.value,
                    "component": component.value,
                    "availability": summary.state.value,
                    "eligibleUnits": summary.eligible_units,
                    "reservedUnits": reserved,
                    # None when the facility has never reported: unknown
                    # minus a hold is still unknown, not zero.
                    "unreservedUnits": free,
                    "batchCount": summary.batch_count,
                    "freshness": summary.freshness.value,
                    "nearExpiryUnits": summary.near_expiry_units,
                    "earliestExpiry": to_iso(summary.earliest_expiry),
                }
            )

    last_updated = facility.get("inventoryLastUpdatedAt")
    last_verified = facility.get("inventoryLastVerifiedAt")
    from domain.clock import parse_iso

    return {
        "facilityId": facility_id,
        "facilityName": facility.get("name"),
        "inventoryKnown": inventory_known,
        # Separate concepts, separately reported (ADR-0003).
        "inventoryLastUpdatedAt": last_updated,
        "inventoryFreshness": freshness_label(parse_iso(last_updated), now).value,
        "inventoryLastVerifiedAt": last_verified,
        "verificationStatus": verification_status(parse_iso(last_verified), now).value,
        "availability": matrix,
        "disclaimer": (
            "Availability is reported by the facility and is not a clinical "
            "guarantee or a reservation. Confirm with the facility before travelling."
        ),
        "demoData": facility.get("demoData", False),
    }
```

*Listing 8.2. The availability matrix.*

Note `inventory_known` being read from the facility record and passed through.
When it is false, no inventory query runs at all and every cell returns
`UNKNOWN`. Querying and finding nothing would produce `UNAVAILABLE`, which
means something different.

## 8.4 External ingestion

```python
def ingest_external_update(
    self,
    *,
    context: RequestContext,
    facility_id: str,
    batch_id: str,
    units: int,
    source_timestamp: datetime | None,
    source_system: str,
    now: datetime,
) -> dict:
    """Apply an external institutional API update (spec 3.6).

    Rejects a delayed update that would overwrite newer state, and never
    implies verification -- an automated feed updates ``lastUpdatedAt`` only.
    """
    log = get_logger(__name__, context)
    batch = self._inventory.get_batch(facility_id, batch_id)
    if batch is None:
        raise NotFoundError("batch not found", details={"batchId": batch_id})

    if is_stale_update(source_timestamp, batch.last_updated_at):
        log.warning("rejected stale external update", event="inventory.ingest.stale",
                    batchId=batch_id, sourceSystem=source_system)
        raise ValidationError(
            "this update is older than the current inventory state and was rejected",
            details={
                "sourceTimestamp": to_iso(source_timestamp),
                "currentLastUpdatedAt": to_iso(batch.last_updated_at),
                "rule": "STALE_UPDATE_REJECTED",
            },
        )

    return self.adjust_stock(
        context=context,
        facility_id=facility_id,
        batch_id=batch_id,
        operation=StockOperation.CORRECT.value,
        units=units,
        now=now,
        reason=f"external update from {source_system}",
        source=f"API:{source_system}",
    )
```

*Listing 8.3. External API ingestion.*

Two protections. A stale update — one whose source timestamp predates the
stored `lastUpdatedAt` — is rejected with a named rule rather than applied. And
the update is routed through `adjust_stock` with a source of `API:<system>`,
so it updates `lastUpdatedAt` and never touches `lastVerifiedAt`.

## 8.5 The presentation layer

```python
def _present_batch(self, batch: Batch, now: datetime) -> dict:
    eligibility = evaluate_batch_eligibility(
        status=batch.status,
        available_units=batch.available_units,
        expires_at=batch.expires_at,
        collected_at=batch.collected_at,
        now=now,
    )
    return {
        "batchId": batch.batch_id,
        "facilityId": batch.facility_id,
        "organizationId": batch.organization_id,
        "bloodGroup": batch.blood_group.value,
        "component": batch.component.value,
        "availableUnits": batch.available_units,
        "status": batch.status.value,
        "collectedAt": to_iso(batch.collected_at),
        "expiresAt": to_iso(batch.expires_at),
        "nearExpiry": is_near_expiry(batch.expires_at, now),
        "eligible": eligibility.eligible,
        "ineligibleReasons": list(eligibility.reasons),
        # These four are always reported together and never merged.
        "lastUpdatedAt": to_iso(batch.last_updated_at),
        "freshness": freshness_label(batch.last_updated_at, now).value,
        "lastVerifiedAt": to_iso(batch.last_verified_at),
        "verificationStatus": verification_status(batch.last_verified_at, now).value,
        "updateSource": batch.update_source,
        "version": batch.version,
        "quarantineReason": batch.quarantine_reason,
    }
```

*Listing 8.4. Batch presentation.*

Four fields are always emitted together: `lastUpdatedAt`, `freshness`,
`lastVerifiedAt` and `verificationStatus`. Returning freshness without
verification would let a client render one and not the other, which is the
conflation the whole design exists to prevent.

<!-- pagebreak -->

# 9. The Discovery Service

## 9.1 Filter, then rank — never the other way round

```python
def search_facilities(
    self,
    *,
    latitude: float,
    longitude: float,
    now: datetime,
    radius_km: float = DEFAULT_RADIUS_KM,
    blood_group: str | None = None,
    component: str | None = None,
    requested_units: int = 1,
    only_available: bool = False,
    min_freshness: str | None = None,
    verified_only: bool = False,
    weights: RankingWeights | None = None,
    limit: int = 20,
    context=None,
) -> dict:
    log = get_logger(__name__, context)

    if radius_km <= 0:
        raise ValidationError("radius must be greater than zero")
    if radius_km > MAX_SEARCH_RADIUS_KM:
        raise ValidationError(
            f"radius cannot exceed {MAX_SEARCH_RADIUS_KM} km",
            details={"maximum": MAX_SEARCH_RADIUS_KM},
        )
    try:
        Coordinates(latitude, longitude)
    except ValueError as exc:
        raise ValidationError(str(exc)) from None

    group = parse_group(blood_group) if blood_group else None
    comp = parse_component(component) if component else None
    if (group is None) != (comp is None):
        raise ValidationError(
            "blood group and component must be supplied together",
            details={"reason": "availability is only meaningful for a specific pair"},
        )

    nearby = self._facilities.find_nearby(
        latitude=latitude, longitude=longitude, radius_km=radius_km
    )
    log.info("facility search", event="discovery.search",
             radiusKm=radius_km, candidates=len(nearby))

    enriched: list[dict] = []
    ranking_inputs: list[RankingInput] = []

    for facility in nearby:
        facility_id = facility["facilityId"]
        inventory_known = bool(facility.get("inventoryKnown", False))
        last_updated = parse_iso(facility.get("inventoryLastUpdatedAt"))
        last_verified = parse_iso(facility.get("inventoryLastVerifiedAt"))
        fresh = freshness_label(last_updated, now)
        verified = verification_status(last_verified, now)

        if verified_only and verified.value != "VERIFIED":
            continue
        if min_freshness and not self._meets_freshness(fresh.value, min_freshness):
            continue

        availability = AvailabilityState.UNKNOWN
        eligible_units: int | None = None
        reserved_units = 0

        if group is not None and comp is not None:
            if inventory_known:
                batches = self._inventory.list_eligible_batches(
                    facility_id, group, comp, now=now
                )
                summary = summarise_availability(
                    batches=batches,
                    blood_group=group,
                    component=comp,
                    requested_units=requested_units,
                    now=now,
                    inventory_known=True,
                )
                availability = summary.state
                eligible_units = summary.eligible_units
                if summary.freshness.value != "UNKNOWN":
                    fresh = summary.freshness

                # Deduct temporary holds. A reserved unit must not be
                # offered to the next searcher, and the state is
                # recomputed from what is left rather than kept from the
                # pre-deduction figure: holding the last 2 of 2 units
                # makes the facility UNAVAILABLE, not AVAILABLE.
                if self._reservations is not None:
                    free, held = self._reservations.adjust_availability(
                        facility_id, group, comp, eligible_units, now=now
                    )
                    reserved_units = held
                    if free is not None and held > 0:
                        eligible_units = free
                        if free <= 0:
                            availability = AvailabilityState.UNAVAILABLE
                        elif requested_units > 0 and free < requested_units:
                            availability = AvailabilityState.PARTIAL
                        else:
                            availability = AvailabilityState.AVAILABLE
            else:
                # Never fabricate a zero for a facility that has not reported.
                availability = AvailabilityState.UNKNOWN

            if only_available and availability not in (
                AvailabilityState.AVAILABLE,
                AvailabilityState.PARTIAL,
            ):
                continue

        record = {
            "facilityId": facility_id,
            "name": facility.get("name"),
            "facilityType": facility.get("facilityType"),
            "address": facility.get("address"),
            "city": facility.get("city"),
            "latitude": float(facility["latitude"]),
            "longitude": float(facility["longitude"]),
            # Labelled unambiguously: this is NOT road distance.
            "straightLineKm": facility.get("straightLineKm"),
            "roadKm": None,
            "etaMinutes": None,
            "routingAvailable": False,
            "availability": availability.value,
            # Net of temporary holds; reservedUnits says how many were
            # deducted, so a user can see why a figure changed.
            "eligibleUnits": eligible_units,
            "reservedUnits": reserved_units,
            "inventoryKnown": inventory_known,
            "inventoryLastUpdatedAt": facility.get("inventoryLastUpdatedAt"),
            "freshness": fresh.value,
            "inventoryLastVerifiedAt": facility.get("inventoryLastVerifiedAt"),
            "verificationStatus": verified.value,
            "facilityVerificationStatus": facility.get("verificationStatus", "UNVERIFIED"),
            "contactPhone": facility.get("contactPhone"),
            "operatingHours": facility.get("operatingHours"),
            "demoData": facility.get("demoData", False),
        }
        enriched.append(record)
        ranking_inputs.append(
            RankingInput(
                facility_id=facility_id,
                availability=availability,
                eligible_units=eligible_units,
                requested_units=requested_units,
                freshness=fresh,
                verification=verified,
                distance_km=float(facility.get("straightLineKm") or 0.0),
                search_radius_km=radius_km,
            )
        )

    ranked = rank_facilities(ranking_inputs, weights or DEFAULT_WEIGHTS)
    by_id = {r["facilityId"]: r for r in enriched}
    ordered: list[dict] = []
    for entry in ranked[:limit]:
        record = by_id[entry.facility_id]
        record["rankScore"] = entry.score
        record["rankComponents"] = entry.components
        record["rankExplanation"] = entry.explanation
        ordered.append(record)

    return {
        "origin": {"latitude": latitude, "longitude": longitude},
        "radiusKm": radius_km,
        "bloodGroup": group.value if group else None,
        "component": comp.value if comp else None,
        "requestedUnits": requested_units,
        "totalCandidates": len(nearby),
        "results": ordered,
        "rankingWeights": {
            "availability": (weights or DEFAULT_WEIGHTS).availability,
            "quantity": (weights or DEFAULT_WEIGHTS).quantity,
            "freshness": (weights or DEFAULT_WEIGHTS).freshness,
            "verification": (weights or DEFAULT_WEIGHTS).verification,
            "distance": (weights or DEFAULT_WEIGHTS).distance,
        },
        "notice": (
            "Distances shown are straight-line unless a road distance is given. "
            "Ranking is an operational aid, not a clinical recommendation."
        ),
    }
```

*Listing 9.1. Facility search from
`backend/src/services/discovery_service.py`.*

Eligibility filtering happens while building the candidate list. Ranking runs
afterwards on survivors only. No weighting, however it is tuned, can surface an
expired or quarantined batch, because such batches never enter the list.

## 9.2 Ranking is explainable

```python
def score_facility(item: RankingInput, weights: RankingWeights = DEFAULT_WEIGHTS) -> RankedFacility:
    availability = _availability_score(item.availability)
    quantity = _quantity_score(item.eligible_units, item.requested_units)
    fresh = freshness_score(item.freshness)
    verified = verification_score(item.verification)
    distance = _distance_score(item.distance_km, item.search_radius_km)

    components = {
        "availability": round(availability * weights.availability, 4),
        "quantity": round(quantity * weights.quantity, 4),
        "freshness": round(fresh * weights.freshness, 4),
        "verification": round(verified * weights.verification, 4),
        "distance": round(distance * weights.distance, 4),
    }
    total = round(sum(components.values()), 4)

    explanation: list[str] = []
    if item.availability == AvailabilityState.UNKNOWN:
        explanation.append("Inventory for this facility is unknown, not zero.")
    elif item.availability == AvailabilityState.PARTIAL:
        explanation.append(
            f"Partial stock: {item.eligible_units} of {item.requested_units} units."
        )
    if item.freshness in (FreshnessLabel.STALE, FreshnessLabel.OUTDATED):
        explanation.append(f"Inventory data is {item.freshness.value.lower()}.")
    if item.verification == VerificationStatus.UNVERIFIED:
        explanation.append("No independent verification on record.")
    explanation.append(f"{item.distance_km:.1f} km straight-line distance.")

    return RankedFacility(
        facility_id=item.facility_id,
        score=total,
        availability=item.availability,
        components=components,
        explanation=explanation,
    )
```

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

```python
def route_to_facility(self, *, origin: Coordinates, facility_id: str) -> dict:
    """Road route and ETA, degrading honestly when routing is unavailable.

    The straight-line figure is always returned and always labelled as such.
    A failed route yields ``routingAvailable: false`` with a reason -- never a
    fabricated road distance (spec 2.7, 4.5).
    """
    facility = self._facilities.get_facility(facility_id)
    if facility is None:
        raise NotFoundError("facility not found", details={"facilityId": facility_id})

    from domain.geo import haversine_km

    destination = Coordinates(float(facility["latitude"]), float(facility["longitude"]))
    straight_line = round(haversine_km(origin, destination), 2)

    result = self._router.route(origin, destination)
    payload = {
        "facilityId": facility_id,
        "facilityName": facility.get("name"),
        "straightLineKm": straight_line,
        "routingAvailable": result.available,
        "provider": result.provider,
    }
    if result.available:
        payload.update({"roadKm": result.road_km, "etaMinutes": result.duration_minutes})
    else:
        payload.update(
            {
                "roadKm": None,
                "etaMinutes": None,
                "unavailableReason": result.unavailable_reason,
                "notice": (
                    "Road directions are unavailable right now. The distance shown "
                    "is straight-line only and does not reflect road travel."
                ),
            }
        )
    return payload
```

*Listing 9.3. Routing with honest degradation.*

Straight-line distance is always present and always labelled. Road distance
appears only when a provider returned one. When it did not, the response says
so, names the reason, and warns that the figure shown is not a driving
distance.

<!-- pagebreak -->

# 10. The Alert Service

## 10.1 An alert is a standing question

```python
def create_alert(
    self,
    *,
    context: RequestContext,
    blood_group: str,
    component: str,
    required_units: int,
    latitude: float,
    longitude: float,
    now: datetime,
    radius_km: float = DEFAULT_ALERT_RADIUS_KM,
    required_by: datetime | None = None,
    notify_channels: list[str] | None = None,
) -> dict:
    log = get_logger(__name__, context)
    group = parse_group(blood_group)
    comp = parse_component(component)

    if required_units <= 0:
        raise ValidationError("required units must be at least one")
    if radius_km <= 0 or radius_km > MAX_ALERT_RADIUS_KM:
        raise ValidationError(
            f"search radius must be between 1 and {MAX_ALERT_RADIUS_KM} km",
            details={"maximum": MAX_ALERT_RADIUS_KM},
        )
    try:
        Coordinates(latitude, longitude)
    except ValueError as exc:
        raise ValidationError(str(exc)) from None

    max_expiry = now + timedelta(hours=MAX_ALERT_LIFETIME_HOURS)
    if required_by is None:
        expires_at = now + timedelta(hours=24)
    elif required_by <= now:
        raise ValidationError("the required-by deadline is already in the past")
    else:
        expires_at = min(required_by, max_expiry)

    alert_id = str(ULID())
    alert = self._alerts.create_alert(
        {
            "alertId": alert_id,
            "userId": context.actor_id,
            "bloodGroup": group.value,
            "component": comp.value,
            "requiredUnits": required_units,
            "latitude": latitude,
            "longitude": longitude,
            "radiusKm": radius_km,
            "requiredBy": to_iso(required_by),
            "expiresAt": to_iso(expires_at),
            "expiresAtEpoch": int(expires_at.timestamp()),
            "notifyChannels": notify_channels or ["IN_APP"],
            "isReservation": False,
        },
        now=now,
    )

    self._audit.record(
        actor_id=context.actor_id,
        actor_role=",".join(context.principal.roles),
        action="ALERT_CREATED",
        resource_type="ALERT",
        resource_id=alert_id,
        correlation_id=context.correlation_id,
        occurred_at=now,
        after={"bloodGroup": group.value, "component": comp.value,
               "requiredUnits": required_units},
    )
    log.info("availability alert created", event="alert.created", alertId=alert_id)

    # Match immediately so a user with stock already nearby is told at once.
    matches = self.match_alert(alert_id=alert_id, now=now, context=context)

    return {
        **self._present(alert),
        "immediateMatches": matches.get("matches", []),
        "notice": INFORMATIONAL_NOTICE,
    }
```

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

```python
def match_alert(self, *, alert_id: str, now: datetime, context=None) -> dict:
    """Find facilities with eligible stock for one alert and notify once each.

    Stock is revalidated here rather than trusted from whatever event
    triggered the match, so a batch consumed in the meantime does not
    produce a notification about stock that no longer exists.
    """
    log = get_logger(__name__, context)
    alert = self._alerts.get_alert(alert_id)
    if alert is None:
        raise NotFoundError("alert not found", details={"alertId": alert_id})

    if alert.get("status") != AlertStatus.ACTIVE.value:
        return {"alertId": alert_id, "matches": [], "skipped": "ALERT_NOT_ACTIVE"}

    required_by = alert.get("requiredBy")
    if required_by:
        from domain.clock import parse_iso

        if parse_iso(required_by) <= now:
            self._alerts.set_status(
                alert_id, status=AlertStatus.DEADLINE_PASSED, now=now,
                reason="required-by deadline passed",
            )
            return {"alertId": alert_id, "matches": [], "skipped": "DEADLINE_PASSED"}

    group = parse_group(alert["bloodGroup"])
    comp = parse_component(alert["component"])
    required_units = int(alert["requiredUnits"])

    nearby = self._facilities.find_nearby(
        latitude=float(alert["latitude"]),
        longitude=float(alert["longitude"]),
        radius_km=float(alert.get("radiusKm", DEFAULT_ALERT_RADIUS_KM)),
    )

    matches: list[dict] = []
    for facility in nearby:
        facility_id = facility["facilityId"]
        if not facility.get("inventoryKnown"):
            continue  # unknown is not a match
        if self._alerts.has_recent_match(alert_id, facility_id):
            continue  # duplicate suppression

        from domain.inventory import summarise_availability

        batches = self._inventory.list_eligible_batches(facility_id, group, comp, now=now)
        summary = summarise_availability(
            batches=batches,
            blood_group=group,
            component=comp,
            requested_units=required_units,
            now=now,
            inventory_known=True,
        )
        if summary.state not in (AvailabilityState.AVAILABLE, AvailabilityState.PARTIAL):
            continue

        self._alerts.record_match_notification(
            alert_id=alert_id,
            facility_id=facility_id,
            units=summary.eligible_units,
            now=now,
            availability_state=summary.state.value,
        )
        matches.append(
            {
                "facilityId": facility_id,
                "facilityName": facility.get("name"),
                "availability": summary.state.value,
                "eligibleUnits": summary.eligible_units,
                "requiredUnits": required_units,
                "straightLineKm": facility.get("straightLineKm"),
                "freshness": summary.freshness.value,
                "isReservation": False,
            }
        )

    if matches:
        partial = any(m["availability"] == AvailabilityState.PARTIAL.value for m in matches)
        headline = (
            f"Partial match for {group.value} {comp.value}"
            if partial
            else f"{group.value} {comp.value} available nearby"
        )
        body_lines = [
            f"{len(matches)} facility/facilities near you report eligible "
            f"{group.value} {comp.value} stock.",
            "",
        ]
        for m in matches[:5]:
            body_lines.append(
                f"- {m['facilityName']}: {m['eligibleUnits']} unit(s), "
                f"{m['straightLineKm']} km (straight-line), data {m['freshness'].lower()}"
            )
        body_lines += ["", INFORMATIONAL_NOTICE]

        self._notifications.notify(
            user_id=alert["userId"],
            category="ALERT_MATCH",
            subject=headline,
            body="\n".join(body_lines),
            now=now,
            metadata={"alertId": alert_id, "matchCount": len(matches)},
            # One notification per alert per facility set, per hour.
            dedupe_key=f"alert-match#{alert_id}#{now.strftime('%Y%m%d%H')}",
        )
        log.info("alert matched", event="alert.matched",
                 alertId=alert_id, matchCount=len(matches))

    return {"alertId": alert_id, "matches": matches, "notice": INFORMATIONAL_NOTICE}
```

*Listing 10.2. Alert matching.*

The match re-reads eligible stock rather than trusting whatever event triggered
it. Between a stock-change event being published and a worker processing it,
the stock may already have gone.

Three guards before any notification: the alert must still be active, its
deadline must not have passed, and the facility must not already have been
matched to this alert.

## 10.3 The reverse lookup

```python
def match_on_stock_change(self, *, facility_id: str, blood_group: str, component: str,
                          now: datetime, context=None) -> dict:
    """Reverse lookup: stock changed here -- who was waiting for it?

    Uses the alert match index (AP-10) so this is a bounded query rather than
    a scan over every open alert.
    """
    facility = self._facilities.get_facility(facility_id)
    if facility is None:
        return {"matched": 0, "reason": "FACILITY_NOT_FOUND"}

    geohash5 = encode_geohash(float(facility["latitude"]), float(facility["longitude"]), 5)
    group = parse_group(blood_group)
    comp = parse_component(component)

    candidates = self._alerts.find_matching_alerts(
        geohash5=geohash5, blood_group=group, component=comp, now=now
    )
    notified = 0
    for alert in candidates:
        outcome = self.match_alert(
            alert_id=alert["alertId"], now=now, context=context
        )
        if outcome.get("matches"):
            notified += 1
    return {"candidates": len(candidates), "notified": notified}
```

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

```python
def record_donation(self, *, context: RequestContext, camp_id: str, donor_id: str,
                    blood_group: str, component: str, units: int, now: datetime) -> dict:
    """Record that a donation took place. Still unverified at this point."""
    camp = self._require_camp(camp_id)
    self._assert_camp_staff(context, camp_id, camp)

    registration = self._camps.get_registration(camp_id, donor_id)
    if registration is None:
        raise NotFoundError("this donor is not registered for this camp")
    if registration.get("attendanceStatus") != "CHECKED_IN":
        raise ValidationError(
            "a donation cannot be recorded before the donor is checked in",
            details={"rule": "ATTENDANCE_REQUIRED"},
        )
    if units <= 0:
        raise ValidationError("units must be at least one")

    from domain.blood import parse_component, parse_group

    donation_id = str(ULID())
    donation = self._donations.record_donation(
        {
            "donationId": donation_id,
            "donorId": donor_id,
            "campId": camp_id,
            "bloodGroup": parse_group(blood_group).value,
            "component": parse_component(component).value,
            "units": units,
            "recordedBy": context.actor_id,
        },
        now=now,
    )
    self._audit.record(
        actor_id=context.actor_id,
        actor_role=",".join(context.principal.roles),
        action="DONATION_RECORDED",
        resource_type="DONATION",
        resource_id=donation_id,
        organization_id=camp.get("organizerOrganizationId"),
        correlation_id=context.correlation_id,
        occurred_at=now,
        after={"donorId": donor_id, "units": units},
    )
    return {
        "donationId": donation_id,
        "status": donation["status"],
        "notice": (
            "Recorded but not yet verified. Impact points are awarded only "
            "after independent verification by authorized staff."
        ),
    }
```

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

```python
def assert_can_verify_donation(
    *,
    verifier_id: str,
    donor_id: str,
    verifier_is_camp_staff: bool,
    donation_status: DonationStatus,
) -> None:
    """The spec's hardest rule in this feature: donors cannot verify themselves.

    Checked before the authorization decorator's role check is even relevant --
    being camp staff does not entitle someone to verify their own donation.
    """
    if verifier_id == donor_id:
        raise ForbiddenError(
            "a donor cannot verify their own donation",
            details={"rule": "SELF_VERIFICATION_FORBIDDEN"},
        )
    if not verifier_is_camp_staff:
        raise ForbiddenError(
            "only authorized camp staff may verify donations",
            details={"rule": "VERIFIER_NOT_CAMP_STAFF"},
        )
    if donation_status == DonationStatus.VERIFIED:
        raise InvalidStateTransitionError(
            "donation is already verified",
            details={"rule": "ALREADY_VERIFIED"},
        )
```

*Listing 11.2. The rule from `backend/src/domain/camps.py`.*

Holding `donation:verify` is necessary but not sufficient. A camp organiser who
donated at their own camp has the permission and is refused anyway, and there
is a test that grants the donor the staff role specifically to prove the
refusal still holds.

## 11.3 Exactly-once credit

```python
def verify_donation(self, *, context: RequestContext, camp_id: str, donor_id: str,
                    donation_id: str, now: datetime) -> dict:
    """Verify a donation and credit the impact ledger exactly once.

    The self-verification rule is checked here in the service, not only in
    the permission layer: holding DONATION_VERIFY does not entitle someone
    to verify their own donation.
    """
    log = get_logger(__name__, context)
    camp = self._require_camp(camp_id)
    is_staff = self._camps.is_camp_staff(camp_id, context.actor_id) or (
        camp.get("organizerUserId") == context.actor_id
    )

    donation = self._donations.get_donation(donor_id, donation_id)
    if donation is None:
        raise NotFoundError("donation not found", details={"donationId": donation_id})

    assert_can_verify_donation(
        verifier_id=context.actor_id,
        donor_id=donor_id,
        verifier_is_camp_staff=is_staff,
        donation_status=DonationStatus(donation.get("status", "RECORDED")),
    )

    previous_count = verified_donation_count(self._ledger_entries(donor_id))

    result = self._donations.verify_donation_and_credit(
        donor_id=donor_id,
        donation_id=donation_id,
        verifier_id=context.actor_id,
        points=POINTS_PER_VERIFIED_DONATION,
        now=now,
    )

    entries = self._ledger_entries(donor_id)
    new_count = verified_donation_count(entries)
    gained = newly_earned_milestones(previous_count, new_count)

    self._audit.record(
        actor_id=context.actor_id,
        actor_role=",".join(context.principal.roles),
        action="DONATION_VERIFIED",
        resource_type="DONATION",
        resource_id=donation_id,
        organization_id=camp.get("organizerOrganizationId"),
        correlation_id=context.correlation_id,
        occurred_at=now,
        after={"donorId": donor_id, "pointsAwarded": POINTS_PER_VERIFIED_DONATION},
    )

    if gained:
        labels = ", ".join(MILESTONE_LABELS[m] for m in gained)
        self._notifications.notify(
            user_id=donor_id,
            category="ACCOUNT_NOTICE",
            subject=f"Milestone reached: {labels}",
            body=(
                f"Your donation has been verified. You have reached: {labels}.\n\n"
                "Thank you for donating. This is a recognition record only and is "
                "not a medical or government document."
            ),
            now=now,
            metadata={"donationId": donation_id},
            dedupe_key=f"milestone#{donor_id}#{new_count}",
            force_transactional=True,
        )

    log.info("donation verified", event="donation.verified",
             donationId=donation_id, donorId=donor_id)

    return {
        **result,
        "impactScore": compute_score(entries),
        "verifiedDonations": new_count,
        "newMilestones": [MILESTONE_LABELS[m] for m in gained],
        "notice": "Impact points are credited once per verified donation.",
    }
```

*Listing 11.3. Verification and crediting.*

The service reads the ledger before and after so it can report newly crossed
milestones without re-announcing old ones. The exactly-once property itself is
enforced one layer down, by a transaction whose ledger row is keyed on the
donation id with a not-exists condition.

## 11.4 Reminders re-check everything

```python
def should_send_reminder(
    *,
    camp_status: CampStatus,
    registration_status: RegistrationStatus,
    notifications_enabled: bool,
    consent_given: bool,
    already_sent: bool,
    scheduled_for: datetime,
    now: datetime,
    tolerance_minutes: int = 10,
) -> bool:
    """Re-checked immediately before each send, never trusted from scheduling time.

    The spec requires rechecking camp status, registration status, preferences,
    consent, prior sends and schedule validity -- all five are here, so a camp
    cancelled after the reminder was queued cannot produce a reminder.
    """
    if already_sent:
        return False
    if not notifications_enabled or not consent_given:
        return False
    if camp_status in (CampStatus.CANCELLED, CampStatus.REJECTED, CampStatus.COMPLETED):
        return False
    if registration_status != RegistrationStatus.REGISTERED:
        return False
    drift_minutes = abs((now - scheduled_for).total_seconds()) / 60.0
    return drift_minutes <= tolerance_minutes
```

*Listing 11.4. The five re-checks.*

A reminder scheduled yesterday for a camp cancelled this morning must not be
sent. Every precondition is evaluated at send time, not at schedule time, and
the schedule-drift tolerance means a job that fires hours late does not emit a
"starts in 2 hours" message about something that started already.

<!-- pagebreak -->

# 12. The Emergency Service

## 12.1 A new request has no priority

```python
def create_request(
    self,
    *,
    context: RequestContext,
    blood_group: str,
    component: str,
    required_units: int,
    latitude: float,
    longitude: float,
    required_by: datetime | None,
    contact_name: str,
    contact_phone: str,
    now: datetime,
    patient_reference: str | None = None,
    requesting_institution: str | None = None,
    consent_given: bool = False,
    notes: str | None = None,
) -> dict:
    log = get_logger(__name__, context)
    group = parse_group(blood_group)
    comp = parse_component(component)

    if not consent_given:
        raise ValidationError(
            "consent is required before a request can be submitted",
            details={"field": "consentGiven"},
        )
    if required_units <= 0 or required_units > MAX_UNITS_PER_REQUEST:
        raise ValidationError(
            f"required units must be between 1 and {MAX_UNITS_PER_REQUEST}",
            details={"maximum": MAX_UNITS_PER_REQUEST},
        )
    if not contact_name.strip() or not contact_phone.strip():
        raise ValidationError("a contact name and phone number are required")
    if required_by is not None and required_by <= now:
        raise ValidationError("the required-by deadline is already in the past")
    try:
        Coordinates(latitude, longitude)
    except ValueError as exc:
        raise ValidationError(str(exc)) from None

    # Duplicate suppression by fingerprint (spec 6.2).
    fingerprint = self._fingerprint(
        actor_id=context.actor_id,
        group=group.value,
        component=comp.value,
        units=required_units,
        latitude=latitude,
        longitude=longitude,
    )
    idempotency_key = context.idempotency_key or f"emergency#{fingerprint}"
    existing = self._idempotency.claim(
        idempotency_key, now=now, operation="emergency.create"
    )
    if existing is not None:
        return {**existing.get("result", {}), "deduplicated": True}

    organization_id = context.organization_id
    verification_state = HospitalVerificationState.PENDING_VERIFICATION
    if organization_id:
        org = self._identity.get_organization(organization_id)
        if org and org.get("organizationType") == OrganizationType.HOSPITAL.value:
            verification_state = self._map_org_status(org.get("status"))

    request_id = str(ULID())
    # A new request carries NO clinical priority. It stays uncertified until
    # an authorized hospital actor certifies it (spec 6.4).
    payload = {
        "requestId": request_id,
        "bloodGroup": group.value,
        "component": comp.value,
        "requiredUnits": required_units,
        "latitude": latitude,
        "longitude": longitude,
        "requiredBy": to_iso(required_by),
        "contactName": contact_name.strip(),
        "contactPhone": contact_phone.strip(),
        "patientReference": patient_reference,
        "requestingInstitution": requesting_institution,
        "requesterOrganizationId": organization_id,
        "createdBy": context.actor_id,
        "consentGiven": True,
        "consentRecordedAt": to_iso(now),
        "notes": notes,
        "status": RequestStatus.REQUEST_CREATED.value,
        "clinicalPriority": None,
        "effectivePriority": ClinicalPriority.P3.value,
        "hospitalVerificationState": verification_state.value,
        "fingerprint": fingerprint,
    }

    outbox_item = self._outbox.build_event(
        event_type="EmergencyRequestCreated",
        payload={
            "requestId": request_id,
            "bloodGroup": group.value,
            "component": comp.value,
            "requiredUnits": required_units,
        },
        correlation_id=context.correlation_id,
        occurred_at=now,
        aggregate_id=request_id,
    )
    self._emergency.create_request_with_outbox(payload, outbox_item, now=now)

    self._emergency.transition(
        request_id=request_id,
        from_status=RequestStatus.REQUEST_CREATED,
        to_status=RequestStatus.VERIFICATION_PENDING,
        actor_id=context.actor_id,
        now=now,
    )

    self._audit.record(
        actor_id=context.actor_id,
        actor_role=",".join(context.principal.roles),
        action="EMERGENCY_REQUEST_CREATED",
        resource_type="EMERGENCY_REQUEST",
        resource_id=request_id,
        organization_id=organization_id,
        correlation_id=context.correlation_id,
        occurred_at=now,
        after={"bloodGroup": group.value, "requiredUnits": required_units},
    )

    result = {
        "requestId": request_id,
        "status": RequestStatus.VERIFICATION_PENDING.value,
        "clinicalPriority": None,
        "hospitalVerificationState": verification_state.value,
        "notice": COORDINATION_NOTICE,
        "nextStep": (
            "Awaiting hospital certification of clinical priority by an "
            "authorized hospital user."
        ),
    }
    self._idempotency.complete(idempotency_key, result=result, now=now)
    log.info("emergency request created", event="emergency.created", requestId=request_id)
    return result
```

*Listing 12.1. Request creation from
`backend/src/services/emergency_service.py`.*

`clinicalPriority` is explicitly `None`. Nothing the requester submits can set
it. The response says so and names the next step.

Duplicate submissions are caught by a fingerprint of actor, group, component,
quantity and rounded coordinates. Rounding to three decimal places means GPS
jitter does not defeat the check while a genuinely different location still
produces a different fingerprint.

## 12.2 Certification re-checks the hospital

```python
def certify_priority(
    self, *, context: RequestContext, request_id: str, priority_label: str,
    now: datetime, justification: str | None = None
) -> dict:
    """Certify clinical priority. Authorized hospital roles only.

    Re-checks hospital verification at the moment of certification, so a
    hospital suspended after the request was raised cannot certify it.
    """
    log = get_logger(__name__, context)
    request = self._require_request(request_id)
    priority = parse_priority_label(priority_label)

    if context.organization_id is None:
        raise ForbiddenError("priority certification requires hospital membership")

    org = self._identity.get_organization(context.organization_id)
    if org is None:
        raise ForbiddenError("certifying organization not found")
    if org.get("organizationType") != OrganizationType.HOSPITAL.value:
        raise ForbiddenError(
            "only a hospital may certify clinical priority",
            details={"organizationType": org.get("organizationType")},
        )
    if org.get("status") != OrganizationStatus.VERIFIED.value:
        # Spec 6.3: a suspended or unverified hospital loses this capability.
        raise ForbiddenError(
            "this hospital is not currently verified and cannot certify priority",
            details={"organizationStatus": org.get("status")},
        )

    current = RequestStatus(request["status"])
    if current != RequestStatus.VERIFICATION_PENDING:
        raise ValidationError(
            f"a request in state {current.value} cannot be certified",
            details={"status": current.value},
        )

    self._emergency.certify_priority(
        request_id=request_id,
        clinical_priority=priority,
        actor_id=context.actor_id,
        actor_role=",".join(context.principal.roles),
        organization_id=context.organization_id,
        now=now,
    )
    self._emergency.transition(
        request_id=request_id,
        from_status=current,
        to_status=RequestStatus.HOSPITAL_CERTIFIED,
        actor_id=context.actor_id,
        now=now,
        effective_priority=priority.value,
        extra={"hospitalVerificationState": HospitalVerificationState.VERIFIED.value},
    )
    self._audit.record(
        actor_id=context.actor_id,
        actor_role=",".join(context.principal.roles),
        action="EMERGENCY_PRIORITY_CERTIFIED",
        resource_type="EMERGENCY_REQUEST",
        resource_id=request_id,
        organization_id=context.organization_id,
        correlation_id=context.correlation_id,
        occurred_at=now,
        after={"clinicalPriority": priority.value},
        metadata={"justification": justification},
    )
    log.info("priority certified", event="emergency.certified",
             requestId=request_id, priority=priority.value)
    return {
        "requestId": request_id,
        "clinicalPriority": priority.value,
        "status": RequestStatus.HOSPITAL_CERTIFIED.value,
        "certifiedBy": context.actor_id,
        "certifiedAt": to_iso(now),
        "notice": (
            "Clinical priority was certified by authorized hospital personnel. "
            "LifeLink does not determine clinical urgency."
        ),
    }
```

*Listing 12.2. Priority certification.*

Four checks before the write: the caller belongs to an organization, that
organization exists, it is a hospital, and it is *currently* verified. The last
is why a hospital suspended after the request was raised cannot certify it.

## 12.3 Matching uses the reference table

```python
def run_matching(self, *, context: RequestContext, request_id: str, now: datetime,
                 radius_km: float = DEFAULT_MATCH_RADIUS_KM) -> dict:
    """Deterministic, explainable matching (spec 6.5).

    Compatible donor groups come from the versioned reference table. An
    UNKNOWN combination yields no candidates rather than a guess.
    """
    log = get_logger(__name__, context)
    request = self._require_request(request_id)
    current = RequestStatus(request["status"])

    if current in (RequestStatus.CANCELLED, RequestStatus.EXPIRED,
                   RequestStatus.RESOLVED):
        return {"requestId": request_id, "skipped": current.value}

    required_by = parse_iso(request.get("requiredBy"))
    if is_expired(required_by, now):
        self._expire(request_id, current, now, actor_id="system")
        return {"requestId": request_id, "skipped": RequestStatus.EXPIRED.value}

    # Re-check the requesting hospital has not been suspended mid-workflow.
    requester_org = request.get("requesterOrganizationId")
    if requester_org:
        org = self._identity.get_organization(requester_org)
        if org and org.get("status") == OrganizationStatus.SUSPENDED.value:
            self._emergency.append_event(
                request_id=request_id,
                event_type="MATCHING_HALTED_ORG_SUSPENDED",
                actor_id="system",
                now=now,
                detail={"organizationId": requester_org},
            )
            return {"requestId": request_id, "skipped": "REQUESTER_SUSPENDED"}

    if current == RequestStatus.HOSPITAL_CERTIFIED:
        self._emergency.transition(
            request_id=request_id,
            from_status=current,
            to_status=RequestStatus.MATCHING_INITIATED,
            actor_id=context.actor_id,
            now=now,
            effective_priority=request.get("effectivePriority"),
        )
        current = RequestStatus.MATCHING_INITIATED

    recipient_group = parse_group(request["bloodGroup"])
    component = parse_component(request["component"])
    reference = get_reference()
    donor_groups = compatible_donor_groups(
        recipient_group=recipient_group, component=component, reference=reference
    )

    if not donor_groups:
        self._emergency.append_event(
            request_id=request_id,
            event_type="NO_COMPATIBILITY_REFERENCE",
            actor_id="system",
            now=now,
            detail={"bloodGroup": recipient_group.value, "component": component.value},
        )
        return {
            "requestId": request_id,
            "candidates": [],
            "reason": "NO_COMPATIBILITY_DATA",
            "compatibilityRulesVersion": reference.version,
            "notice": (
                "No compatibility rule exists for this combination, so no "
                "match was attempted. This is deliberate: the system does "
                "not infer compatibility."
            ),
        }

    candidates: list[dict] = []
    for donor_group in donor_groups:
        facilities = self._discovery.find_facilities_with_stock(
            latitude=float(request["latitude"]),
            longitude=float(request["longitude"]),
            radius_km=radius_km,
            blood_group=donor_group,
            component=component,
            required_units=int(request["requiredUnits"]),
            now=now,
        )
        verdict = check_compatibility(
            recipient_group=recipient_group,
            donor_group=donor_group,
            component=component,
            reference=reference,
        )
        for facility in facilities:
            candidates.append(
                {
                    "facilityId": facility["facilityId"],
                    "facilityName": facility["name"],
                    "organizationId": None,
                    "donorBloodGroup": donor_group.value,
                    "availability": facility["availability"],
                    "eligibleUnits": facility["eligibleUnits"],
                    "straightLineKm": facility["straightLineKm"],
                    "freshness": facility["freshness"],
                    "verificationStatus": facility["verificationStatus"],
                    "rankScore": facility.get("rankScore"),
                    "isIdenticalGroup": donor_group == recipient_group,
                    "requiresClinicalReview": verdict.requires_clinical_review,
                }
            )

    # Deterministic ordering: identical group first, then rank, then distance.
    candidates.sort(
        key=lambda c: (
            not c["isIdenticalGroup"],
            -(c.get("rankScore") or 0),
            c["straightLineKm"],
        )
    )
    selected = candidates[:MAX_PROVIDERS_PER_REQUEST]

    for candidate in selected:
        facility = self._facilities.get_facility(candidate["facilityId"])
        provider_org = (facility or {}).get("organizationId")
        if not provider_org:
            continue
        candidate["organizationId"] = provider_org
        self._emergency.record_provider_notification(
            request_id=request_id,
            provider_org_id=provider_org,
            facility_id=candidate["facilityId"],
            now=now,
        )
        self._notify_provider(
            provider_org=provider_org,
            request=request,
            candidate=candidate,
            now=now,
            request_id=request_id,
        )

    if selected:
        self._emergency.transition(
            request_id=request_id,
            from_status=RequestStatus.MATCHING_INITIATED,
            to_status=RequestStatus.PROVIDERS_NOTIFIED,
            actor_id=context.actor_id,
            now=now,
            effective_priority=request.get("effectivePriority"),
            extra={"providersNotifiedCount": len(selected)},
        )

    log.info("matching complete", event="emergency.matched",
             requestId=request_id, candidates=len(candidates), notified=len(selected))

    return {
        "requestId": request_id,
        "compatibilityRulesVersion": reference.version,
        "compatibilityReviewStatus": reference.review_status,
        "compatibleDonorGroups": [g.value for g in donor_groups],
        "candidatesConsidered": len(candidates),
        "providersNotified": len(selected),
        "candidates": selected,
        "notice": COORDINATION_NOTICE,
        "compatibilityDisclaimer": reference.disclaimer,
    }
```

*Listing 12.3. The matching engine.*

Compatible donor groups come from `compatible_donor_groups`, which reads the
versioned JSON reference. When the lookup yields nothing the engine records a
`NO_COMPATIBILITY_REFERENCE` event and returns no candidates, along with the
rules version and review status.

Candidates are ordered deterministically: identical blood group first, then
rank score, then distance. Determinism matters because a matching engine that
returns different results for identical inputs cannot be audited.

## 12.4 Responses are offers

```python
def submit_response(
    self,
    *,
    context: RequestContext,
    request_id: str,
    response_type: str,
    units_offered: int = 0,
    now: datetime,
    note: str | None = None,
) -> dict:
    """Record a provider's response.

    Revalidates stock before accepting an ACCEPTED response, so a provider
    cannot accept against stock that has already gone. The response records
    willingness only -- it never reserves units (ADR-0017).
    """
    log = get_logger(__name__, context)
    request = self._require_request(request_id)
    current = RequestStatus(request["status"])

    try:
        kind = ProviderResponseType(response_type.strip().upper())
    except ValueError:
        raise ValidationError(
            f"unknown response type '{response_type}'",
            details={"allowed": [r.value for r in ProviderResponseType]},
        ) from None

    if current in (RequestStatus.CANCELLED, RequestStatus.EXPIRED, RequestStatus.RESOLVED):
        # Spec 12.4: a late response must not revive a closed request.
        raise ValidationError(
            f"this request is {current.value} and no longer accepts responses",
            details={"status": current.value},
        )

    if context.organization_id is None:
        raise ForbiddenError("responding requires organization membership")

    # A provider may only respond for its own organization (spec 12.4).
    placeholder = self._emergency.get(
        f"REQUEST#{request_id}", f"RESPONSE#{context.organization_id}"
    )
    if placeholder is None:
        raise ForbiddenError(
            "your organization was not asked to respond to this request",
            details={"rule": "PROVIDER_NOT_NOTIFIED"},
        )

    if kind == ProviderResponseType.ACCEPTED:
        if units_offered <= 0:
            raise ValidationError("an accepted response must offer at least one unit")
        revalidated = self._revalidate_stock(
            facility_id=placeholder["facilityId"],
            blood_group=parse_group(request["bloodGroup"]),
            component=parse_component(request["component"]),
            required_units=units_offered,
            now=now,
        )
        if not revalidated["sufficient"]:
            log.warning("stock disappeared before acceptance",
                        event="emergency.stock.vanished", requestId=request_id)
            raise ValidationError(
                "the stock backing this acceptance is no longer available",
                details={
                    "rule": "STOCK_REVALIDATION_FAILED",
                    "eligibleUnitsNow": revalidated["eligibleUnits"],
                    "unitsOffered": units_offered,
                },
            )

    self._emergency.submit_response(
        request_id=request_id,
        provider_org_id=context.organization_id,
        response_type=kind.value,
        units_offered=units_offered,
        actor_id=context.actor_id,
        now=now,
        note=note,
    )

    if current == RequestStatus.PROVIDERS_NOTIFIED:
        self._emergency.transition(
            request_id=request_id,
            from_status=current,
            to_status=RequestStatus.RESPONSES_RECEIVED,
            actor_id=context.actor_id,
            now=now,
            effective_priority=request.get("effectivePriority"),
        )

    self._audit.record(
        actor_id=context.actor_id,
        actor_role=",".join(context.principal.roles),
        action="EMERGENCY_PROVIDER_RESPONDED",
        resource_type="EMERGENCY_REQUEST",
        resource_id=request_id,
        organization_id=context.organization_id,
        correlation_id=context.correlation_id,
        occurred_at=now,
        after={"responseType": kind.value, "unitsOffered": units_offered},
    )

    responses = self._emergency.list_responses(request_id)
    tally = tally_responses([r for r in responses if r.get("responseType")])

    return {
        "requestId": request_id,
        "responseType": kind.value,
        "unitsOffered": units_offered,
        "tally": {
            "accepted": tally.accepted,
            "rejected": tally.rejected,
            "insufficient": tally.insufficient,
            "needsClarification": tally.clarification,
            "totalUnitsOffered": tally.units_offered,
        },
        "notice": (
            "An accepted response means the provider is willing to proceed. "
            "It is not a reservation, allocation or guarantee of fulfilment."
        ),
    }
```

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

```python
class Router:
    def __init__(self):
        self._routes: list[Route] = []

    def add(
        self,
        method: str,
        path: str,
        handler: Handler,
        *,
        permission: Permission | None = None,
        allow_anonymous: bool = False,
        summary: str = "",
    ) -> None:
        self._routes.append(
            Route(
                method=method.upper(),
                path=path,
                handler=handler,
                permission=permission,
                allow_anonymous=allow_anonymous,
                summary=summary,
                pattern=Route.compile_path(path),
            )
        )

    @property
    def routes(self) -> list[Route]:
        return list(self._routes)

    def match(self, method: str, path: str) -> tuple[Route | None, dict, bool]:
        """Find a route. Returns (route, path_params, path_exists_other_method)."""
        path_exists = False
        for route in self._routes:
            match = route.pattern.match(path)
            if match:
                if route.method == method.upper():
                    return route, match.groupdict(), True
                path_exists = True
        return None, {}, path_exists

    def dispatch(self, event: dict, *, authenticator=None) -> dict:
        """Execute a request end to end, translating domain errors to HTTP."""
        method = (
            event.get("httpMethod")
            or (event.get("requestContext", {}).get("http", {}) or {}).get("method", "GET")
        )
        raw_path = event.get("path") or event.get("rawPath") or "/"
        path = strip_stage_prefix(raw_path, event).rstrip("/") or "/"

        # Preflight is answered before routing, because there is no OPTIONS
        # route to find and a 404 without CORS headers is what a browser
        # reports as "No 'Access-Control-Allow-Origin' header is present".
        # API Gateway would normally answer this at the edge, but our routes
        # are declared Method: ANY, which matches OPTIONS and takes precedence.
        headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
        if is_preflight(method, headers):
            return preflight_response(headers.get("origin"))

        route, params, path_exists = self.match(method, path)

        if route is None:
            if path_exists:
                return error(
                    "METHOD_NOT_ALLOWED",
                    f"{method} is not supported for this path",
                    status=405,
                )
            return error("NOT_FOUND", f"no route for {method} {path}", status=404)

        try:
            context = build_context(event, authenticator)
        except LifeLinkError as exc:
            return from_exception(exc)

        log = get_logger(__name__, context)
        enriched = {**event, "pathParameters": {**(event.get("pathParameters") or {}), **params}}

        try:
            result = route.handler(enriched, context)
            log.info(
                f"{method} {path} -> {result.get('statusCode', 200)}",
                event="http.request",
                method=method,
                path=path,
                status=result.get("statusCode", 200),
            )
            return result
        except LifeLinkError as exc:
            log.warning(
                f"{method} {path} -> {exc.http_status} {exc.code}",
                event="http.error",
                method=method,
                path=path,
                code=exc.code,
            )
            return from_exception(exc, correlation_id=context.correlation_id)
        except Exception:
            # Never leak an internal error's details to the client (spec 8.3).
            log.exception("unhandled error", event="http.unhandled",
                          method=method, path=path)
            return error(
                "INTERNAL_ERROR",
                "an unexpected error occurred",
                status=500,
                correlation_id=context.correlation_id,
            )
```

*Listing 13.1. The router from `backend/src/handlers/router.py`.*

## 13.2 404 and 405 are different answers

`match` returns whether the *path* exists under some other method. A `DELETE`
to a path that only supports `GET` returns 405 with the method named, not a 404
suggesting the path is wrong. Debugging an integration against an API that
conflates the two wastes real time.

## 13.3 Error translation at the edge

```python
def dispatch(self, event: dict, *, authenticator=None) -> dict:
    """Execute a request end to end, translating domain errors to HTTP."""
    method = (
        event.get("httpMethod")
        or (event.get("requestContext", {}).get("http", {}) or {}).get("method", "GET")
    )
    raw_path = event.get("path") or event.get("rawPath") or "/"
    path = strip_stage_prefix(raw_path, event).rstrip("/") or "/"

    # Preflight is answered before routing, because there is no OPTIONS
    # route to find and a 404 without CORS headers is what a browser
    # reports as "No 'Access-Control-Allow-Origin' header is present".
    # API Gateway would normally answer this at the edge, but our routes
    # are declared Method: ANY, which matches OPTIONS and takes precedence.
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    if is_preflight(method, headers):
        return preflight_response(headers.get("origin"))

    route, params, path_exists = self.match(method, path)

    if route is None:
        if path_exists:
            return error(
                "METHOD_NOT_ALLOWED",
                f"{method} is not supported for this path",
                status=405,
            )
        return error("NOT_FOUND", f"no route for {method} {path}", status=404)

    try:
        context = build_context(event, authenticator)
    except LifeLinkError as exc:
        return from_exception(exc)

    log = get_logger(__name__, context)
    enriched = {**event, "pathParameters": {**(event.get("pathParameters") or {}), **params}}

    try:
        result = route.handler(enriched, context)
        log.info(
            f"{method} {path} -> {result.get('statusCode', 200)}",
            event="http.request",
            method=method,
            path=path,
            status=result.get("statusCode", 200),
        )
        return result
    except LifeLinkError as exc:
        log.warning(
            f"{method} {path} -> {exc.http_status} {exc.code}",
            event="http.error",
            method=method,
            path=path,
            code=exc.code,
        )
        return from_exception(exc, correlation_id=context.correlation_id)
    except Exception:
        # Never leak an internal error's details to the client (spec 8.3).
        log.exception("unhandled error", event="http.unhandled",
                      method=method, path=path)
        return error(
            "INTERNAL_ERROR",
            "an unexpected error occurred",
            status=500,
            correlation_id=context.correlation_id,
        )
```

*Listing 13.2. Dispatch and error handling.*

Domain errors map to their declared status and keep their code. Anything else
becomes a generic 500 with a correlation id — the detail goes to the log, not
to the client, because an exception message can disclose internals.

## 13.4 Handlers are thin

```python
@requires(Permission.INVENTORY_WRITE, resource_owner=_facility_owner)
def adjust_batch(event: dict, context: RequestContext) -> dict:
    body = parse_body(event)
    batch = get_services().inventory.adjust_stock(
        context=context,
        facility_id=path_param(event, "facilityId"),
        batch_id=path_param(event, "batchId"),
        operation=body.get("operation", ""),
        units=body.get("units"),
        reason=body.get("reason"),
        source=body.get("source", "MANUAL"),
        now=now_utc(),
    )
    return success(batch, correlation_id=context.correlation_id)
```

*Listing 13.3. A representative handler from `backend/src/handlers/api.py`.*

Parse, call one service method, format. No business rules. A handler that grew
a conditional would be a sign that a rule had escaped the layer that owns it.

## 13.5 Ownership resolvers

```python
def _facility_owner(event: dict, context: RequestContext) -> str | None:
    facility_id = (event.get("pathParameters") or {}).get("facilityId")
    if not facility_id:
        return None
    facility = get_services().repos.facilities.get_facility(facility_id)
    return (facility or {}).get("organizationId")
```

*Listing 13.4. An ownership resolver.*

The handler declares how to find the owning organization; the decorator does
the comparison. This is the division that prevents an IDOR: a handler author
cannot forget a check they do not perform.

## 13.6 The route table

58 routes, each with a declared permission and a summary used
to generate the OpenAPI document.

| Method | Path | Permission |
|---|---|---|
| `GET` | `/alerts` | `alert:manage:own` |
| `POST` | `/alerts` | `alert:create` |
| `DELETE` | `/alerts/{alertId}` | `alert:manage:own` |
| `GET` | `/alerts/{alertId}` | `alert:manage:own` |

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

49 paths and 58 operations, produced
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

*Listing 15.1. Frontend layout: 60 modules,
12750 lines.*

## 15.2 One network client

```javascript
async function request(method, path, { body, params, idempotencyKey, signal } = {}) {
  const headers = {
    Accept: 'application/json',
    'X-Correlation-Id': newCorrelationId(),
  }

  const token = tokenProvider()
  if (token) headers.Authorization = `Bearer ${token}`
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (idempotencyKey) headers['Idempotency-Key'] = idempotencyKey

  let response
  try {
    response = await fetch(`${BASE_URL}${path}${buildQuery(params)}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    })
  } catch (cause) {
    if (cause?.name === 'AbortError') throw cause
    // A network failure is distinct from a server error and is worded for the
    // user rather than echoing a fetch internal.
    throw new ApiError(
      'Could not reach LifeLink. Check your connection and try again.',
      { code: 'NETWORK_ERROR', status: 0 },
    )
  }

  if (response.status === 204) return null

  let payload = null
  const text = await response.text()
  if (text) {
    try {
      payload = JSON.parse(text)
    } catch {
      throw new ApiError('The server returned an unreadable response.', {
        code: 'MALFORMED_RESPONSE',
        status: response.status,
      })
    }
  }

  if (!response.ok) {
    const error = payload?.error ?? {}
    throw new ApiError(error.message ?? `Request failed (${response.status})`, {
      code: error.code,
      status: response.status,
      details: error.details,
```

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

```javascript
export function useApiData(fetcher, deps = [], { enabled = true, initialData = null } = {}) {
  const [data, setData] = useState(initialData)
  const [loading, setLoading] = useState(enabled)
  const [error, setError] = useState(null)
  const [reloadToken, setReloadToken] = useState(0)
  const controllerRef = useRef(null)

  const reload = useCallback(() => setReloadToken((n) => n + 1), [])

  useEffect(() => {
    if (!enabled) {
      setLoading(false)
      return undefined
    }

    // Cancel whatever is in flight before starting a newer request.
    controllerRef.current?.abort()
    const controller = new AbortController()
    controllerRef.current = controller

    let active = true
    setLoading(true)
    setError(null)

    fetcher(controller.signal)
      .then((result) => {
        if (active) {
          setData(result)
          setLoading(false)
        }
      })
      .catch((cause) => {
        if (!active || cause?.name === 'AbortError') return
        setError(cause)
        setLoading(false)
      })

    return () => {
      active = false
      controller.abort()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, enabled, reloadToken])

  return { data, loading, error, reload, setData }
```

*Listing 15.4. The data hook from `frontend/src/hooks/useApi.js`.*

The abort matters more than it looks. A user typing in a search box generates
overlapping requests; without cancellation a slow earlier response can land
after a faster later one and overwrite fresher results with staler ones.

## 15.5 Geolocation that never traps the user

```javascript
export function useGeolocation() {
  const [state, setState] = useState({
    status: 'idle', // idle | locating | granted | denied | unavailable | timeout | error
    coords: null,
    accuracy: null,
    message: null,
  })

  const request = useCallback(() => {
    if (!('geolocation' in navigator)) {
      setState({
        status: 'unavailable',
        coords: null,
        accuracy: null,
        message: 'This browser does not provide location. Enter a place name instead.',
      })
      return
    }

    setState((prev) => ({ ...prev, status: 'locating', message: null }))

    navigator.geolocation.getCurrentPosition(
      (position) => {
        setState({
          status: 'granted',
          coords: {
            latitude: position.coords.latitude,
            longitude: position.coords.longitude,
          },
          accuracy: position.coords.accuracy,
          message:
            position.coords.accuracy > 2000
              ? 'Your location is only roughly known. Results may be imprecise.'
              : null,
        })
      },
      (geoError) => {
        const map = {
          1: {
            status: 'denied',
            message:
              'Location permission was declined. You can search by place name instead.',
          },
          2: {
            status: 'unavailable',
            message: 'Your position could not be determined. Try searching by place name.',
          },
          3: {
            status: 'timeout',
            message: 'Finding your location took too long. Try again or search by name.',
          },
        }
        const mapped = map[geoError.code] ?? {
          status: 'error',
          message: 'Location could not be read. Search by place name instead.',
        }
        setState({ coords: null, accuracy: null, ...mapped })
      },
      { enableHighAccuracy: false, timeout: 10000, maximumAge: 60000 },
    )
```

*Listing 15.5. Geolocation with every failure mode handled.*

Permission denied, position unavailable, timeout and a missing API are each
mapped to a distinct status and a message that offers the alternative. The
specification requires never forcing precise location when manual search
exists, and a dead end after a declined permission would do exactly that.

<!-- pagebreak -->

# 16. Components and State

## 16.1 Status badges carry the rules

```javascript
export function AvailabilityBadge({ state, units }) {
  const entry = AVAILABILITY[state] ?? AVAILABILITY.UNKNOWN
  const isUnknown = state === 'UNKNOWN' || state == null

  return (
    <span className={`badge badge--${entry.className}`}>
      <span aria-hidden="true" className="badge__glyph">{entry.glyph}</span>
      <span>{entry.label}</span>
      {/* A unit count is shown only when it is a real measurement. */}
      {!isUnknown && typeof units === 'number' && (
        <span className="badge__count">{units} unit{units === 1 ? '' : 's'}</span>
      )}
    </span>
  )
}

export function FreshnessBadge({ level }) {
  const entry = FRESHNESS[level] ?? FRESHNESS.UNKNOWN
  const className = (level ?? 'UNKNOWN').toLowerCase()
  return (
```

*Listing 16.1. The availability badge from
`frontend/src/components/StatusBadges.jsx`.*

The unit count renders only when it is a real measurement. An `UNKNOWN` state
shows "Not reported" and no number, because "0 units" would be a claim the
system cannot support.

## 16.2 Freshness and verification are bundled

```javascript
export function DataQuality({ freshness, verification }) {
  return (
    <span className="data-quality">
      <FreshnessBadge level={freshness} />
      <VerificationBadge status={verification} />
    </span>
  )
}

export function PriorityBadge({ priority }) {
  if (!priority) {
    return (
```

*Listing 16.2. The paired badge.*

Bundling them in one component makes it awkward to render one without the
other. A developer in a hurry reaches for `DataQuality`, and gets both.

## 16.3 No status relies on colour alone

Every badge has a text label and a distinct glyph in addition to its colour.
The interface works in greyscale and for a colour-blind user, which is a
requirement rather than a nicety for a service used under pressure.

## 16.4 The async state component

```javascript
export function AsyncState({
  loading,
  error,
  isEmpty,
  onRetry,
  loadingMessage,
  emptyTitle = 'Nothing to show',
  emptyMessage,
  emptyAction,
  children,
}) {
  if (loading) return <LoadingPanel message={loadingMessage} />
  if (error) return <ErrorPanel error={error} onRetry={onRetry} />
  if (isEmpty) {
    return <EmptyPanel title={emptyTitle} message={emptyMessage} action={emptyAction} />
  }
  return children
}

export function Card({
  title,
  subtitle,
  actions,
  children,
  tone = 'default',
```

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

```javascript
function RequireRole({ roles, children }) {
  const { isAuthenticated, status, hasRole, roles: userRoles } = useAuth()
  const location = useLocation()

  if (status === 'loading') return <LoadingPanel message="Checking your account…" />
  if (!isAuthenticated) {
    return <Navigate to="/sign-in" state={{ from: location.pathname }} replace />
  }
  if (!hasRole(...roles)) {
    return (
      <div className="stack">
        <Notice tone="danger" title="This dashboard is not available to your account">
          <p>
            It requires one of: <strong>{roles.join(', ')}</strong>.
          </p>
          <p className="text-sm">
            Your account holds: {userRoles.length ? userRoles.join(', ') : 'no roles'}.
          </p>
          <p className="text-sm">
            The server enforces this independently, so changing the address bar will
            not grant access.
          </p>
        </Notice>
      </div>
    )
  }
  return children
}

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route
          path="/"
```

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

```javascript
const { data: results, loading, error, reload } = useApiData(
  (signal) =>
    api.searchFacilities(
      {
        lat: origin.latitude,
        lon: origin.longitude,
        radiusKm,
        bloodGroup,
        component,
        units,
        onlyAvailable: onlyAvailable ? 'true' : undefined,
        verifiedOnly: verifiedOnly ? 'true' : undefined,
        limit: 50,
      },
      signal,
    ),
  [origin.latitude, origin.longitude, radiusKm, bloodGroup, component, units, onlyAvailable, verifiedOnly],
)

const choosePlace = useCallback((place) => {
```

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

```javascript
export function FacilityMap({
  facilities = [],
  camps = [],
  origin,
  onSelect,
  onSelectCamp,
  selectedId,
  height = 420,
}) {
  const containerRef = useRef(null)
  const mapRef = useRef(null)
  const markersRef = useRef(new Map())
  const originMarkerRef = useRef(null)
  const popupRef = useRef(null)
  // Held in refs as well as state: the draw callback runs inside MapLibre
  // event handlers, which close over whatever was current when registered.
  const selectedRef = useRef(selectedId)
  const originRef = useRef(origin)
  const collectionRef = useRef({ type: 'FeatureCollection', features: [] })

  const [renderFailed, setRenderFailed] = useState(false)
  const [tilesLoaded, setTilesLoaded] = useState(false)
  const [mapError, setMapError] = useState(null)
  const [showList, setShowList] = useState(false)
  const [showFacilities, setShowFacilities] = useState(true)
  const [showCamps, setShowCamps] = useState(true)
  const [showOrigin, setShowOrigin] = useState(true)

```

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

```python
def _claim(event_id: str, operation: str, now) -> bool:
    """Returns True when this worker should do the work.

    False means an earlier delivery already completed it, which is the expected
    outcome for a duplicate rather than a failure.
    """
    if not event_id:
        # Without an id there is no way to deduplicate; process and rely on the
        # handler's own idempotency.
        return True
    services = get_services()
    existing = services.repos.idempotency.claim(
        f"worker#{operation}#{event_id}", now=now, operation=operation
    )
    return existing is None
```

*Listing 20.1. Claiming work from `backend/src/handlers/workers.py`.*

A message without an id is processed and relies on the handler's own
idempotency. A message with an id is claimed once; the second delivery finds a
completed claim and returns without doing anything.

## 20.3 Partial batch failures

Each queue consumer returns `batchItemFailures` listing only the messages that
failed. Without that, one bad message in a batch of five returns all five to
the queue, re-running four that already succeeded.

## 20.4 The outbox publisher

```python
def outbox_handler(event: dict, lambda_context=None) -> dict:
    """Publish outbox rows to SQS and mark them dispatched.

    The outbox row was written in the same transaction as its domain change
    (ADR-0005), so by the time this runs the event cannot have been lost. The
    worst case is publishing it twice, which consumers absorb.
    """
    import boto3

    now = now_utc()
    services = get_services()
    sqs = boto3.client("sqs")

    import os

    queues = {
        "work": os.environ.get("WORK_QUEUE_URL", ""),
        "notification": os.environ.get("NOTIFICATION_QUEUE_URL", ""),
    }
    failures: list[dict] = []

    for record in event.get("Records", []):
        if record.get("eventName") not in ("INSERT", "MODIFY"):
            continue

        image = record.get("dynamodb", {}).get("NewImage", {})
        if not image:
            continue

        # DynamoDB Streams uses the low-level attribute-value format.
        def plain(attribute: dict):
            if "S" in attribute:
                return attribute["S"]
            if "N" in attribute:
                value = attribute["N"]
                return int(value) if "." not in value else float(value)
            if "BOOL" in attribute:
                return attribute["BOOL"]
            if "M" in attribute:
                return {k: plain(v) for k, v in attribute["M"].items()}
            if "L" in attribute:
                return [plain(v) for v in attribute["L"]]
            if "NULL" in attribute:
                return None
            return None

        row = {k: plain(v) for k, v in image.items()}
        if row.get("dispatched"):
            continue

        event_id = row.get("eventId", "")
        event_type = row.get("eventType", "")
        correlation_id = row.get("correlationId") or new_correlation_id()
        log = get_logger(__name__, system_context(correlation_id))

        target = EVENT_ROUTING.get(event_type)
        if target is None:
            log.warning("no route for event type; marking dispatched to avoid a stuck row",
                        event="outbox.unrouted", eventType=event_type)
            # Best effort: if this fails the row stays pending and the
            # reconciliation alarm picks it up, which is the safe outcome.
            with contextlib.suppress(Exception):
                services.repos.outbox.mark_dispatched(event_id, now=now)
            continue

        queue_url = queues.get(target, "")
        if not queue_url:
            log.error("queue url not configured", event="outbox.no_queue", target=target)
            failures.append({"itemIdentifier": record.get("eventID", "")})
            continue

        try:
            sqs.send_message(
                QueueUrl=queue_url,
                MessageBody=json.dumps(
                    {
                        "eventId": event_id,
                        "eventType": event_type,
                        "eventVersion": row.get("eventVersion", 1),
                        "occurredAt": row.get("occurredAt"),
                        "correlationId": correlation_id,
                        "aggregateId": row.get("aggregateId"),
                        "payload": row.get("payload", {}),
                    },
                    default=str,
                ),
            )
            services.repos.outbox.mark_dispatched(event_id, now=now)
            log.info("outbox event dispatched", event="outbox.dispatched",
                     eventType=event_type, target=target)
        except Exception as exc:
            # Leaving the row undispatched is the safe failure: the
            # reconciliation job and the pending-rows alarm will surface it.
            log.exception("outbox dispatch failed", event="outbox.failed",
                          eventId=event_id, error=str(exc)[:300])
            failures.append({"itemIdentifier": record.get("eventID", "")})

    return {"batchItemFailures": failures}
```

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

```python
def dispatcher_handler(event: dict, lambda_context=None) -> dict:
    """Priority dispatcher (ADR-0006), on a one-minute schedule.

    Recomputes effective priority with aging so P3 cannot starve, then processes
    in priority-then-FIFO order. Hospital-certified clinical priority is never
    modified here.
    """
    context = system_context()
    log = get_logger(__name__, context)
    services = get_services()
    now = now_utc()

    try:
        outcome = services.emergency.run_dispatcher(context=context, now=now, batch_size=10)
        expired = services.emergency.expire_overdue(context=context, now=now)
        log.info("dispatcher complete", event="scheduler.dispatch.done",
                 processed=len(outcome.get("processed", [])),
                 aged=len(outcome.get("priorityAged", [])),
                 expired=expired.get("expired", 0))
        return {"statusCode": 200, "dispatch": outcome, "expiry": expired}
    except Exception as exc:
        log.exception("dispatcher failed", event="scheduler.dispatch.failed",
                      error=str(exc)[:300])
        # Re-raised so the Lambda error metric fires its alarm. A silently
        # failing dispatcher means emergency requests stop being matched.
        raise
```

*Listing 20.3. The dispatcher re-raises on failure.*

Most handlers absorb errors and report them. This one re-raises specifically so
the Lambda error metric increments and its alarm fires. A silently failing
dispatcher means emergency requests stop being matched while every other
indicator looks healthy — the worst failure mode in the system.

## 20.6 Maintenance isolates its steps

```python
def maintenance_handler(event: dict, lambda_context=None) -> dict:
    """Expiry sweep, camp status transitions and camp reminders.

    Each step is independent: one failing must not prevent the others, so
    failures are collected and reported rather than raised immediately.
    """
    context = system_context()
    log = get_logger(__name__, context)
    services = get_services()
    now = now_utc()
    results: dict[str, Any] = {}
    errors: list[str] = []

    try:
        results["expiry"] = services.inventory.sweep_expired(context=context, now=now)
    except Exception as exc:
        errors.append(f"expiry: {exc}")
        log.exception("expiry sweep failed", event="scheduler.expiry.failed")

    try:
        results["reminders"] = services.camps.send_due_reminders(now=now, context=context)
    except Exception as exc:
        errors.append(f"reminders: {exc}")
        log.exception("reminder sweep failed", event="scheduler.reminders.failed")

    try:
        # Reservation expiry is swept actively rather than left to DynamoDB
        # TTL: TTL deletes within roughly 48 hours on a best-effort basis,
        # which would keep units held long after the hold ended.
        results["reservations"] = services.reservations.expire_due(
            now=now, correlation_id=context.correlation_id
        )
    except Exception as exc:
        errors.append(f"reservations: {exc}")
        log.exception("reservation expiry failed", event="scheduler.reservations.failed")

    try:
        results["alerts"] = services.alerts.expire_due_alerts(now=now, context=context)
    except Exception as exc:
        errors.append(f"alerts: {exc}")
        log.exception("alert expiry failed", event="scheduler.alerts.failed")

    log.info("maintenance complete", event="scheduler.maintenance.done",
             results=results, errorCount=len(errors))

    if errors:
        raise RuntimeError(f"maintenance completed with {len(errors)} failures: {errors}")
    return {"statusCode": 200, **results}
```

*Listing 20.4. Independent steps.*

The expiry sweep, the reminder sweep and alert expiry are independent. One
failing must not prevent the others, so failures are collected and raised at
the end rather than aborting on the first.

<!-- pagebreak -->

# 21. Idempotency in Practice

## 21.1 Three outcomes, three behaviours

```python
def claim(self, key: str, *, now: datetime, operation: str) -> dict | None:
    """Try to claim a key.

    Returns None when the claim succeeded (first execution). Returns the
    stored record when the work was already done, so the caller can replay
    the original result instead of repeating a side effect.
    """
    expires = now + timedelta(hours=IDEMPOTENCY_TTL_HOURS)
    item = {
        "PK": key,
        "SK": "CLAIM",
        "status": "IN_PROGRESS",
        "operation": operation,
        "claimedAt": to_iso(now),
        "expiresAtEpoch": int(expires.timestamp()),
    }
    try:
        self.put(item, condition=Attr("PK").not_exists())
        return None
    except Exception:
        existing = self.get_consistent(key, "CLAIM")
        if existing is None:
            # The row vanished between the failed put and this read (TTL).
            # Treat as a fresh claim rather than failing the request.
            self.put(item)
            return None

        if existing.get("status") == "COMPLETED":
            return existing

        claimed_at = existing.get("claimedAt")
        if claimed_at:
            from domain.clock import parse_iso

            age = (now - parse_iso(claimed_at)).total_seconds() / 60.0
            if age > STALE_CLAIM_MINUTES:
                # The previous attempt almost certainly died. Retake it.
                self.put(item)
                return None

        raise RequestInProgressError(
            "an identical request is currently being processed",
            details={"idempotencyKey": key},
        ) from None
```

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

```python
@staticmethod
def _fingerprint(*, actor_id: str, group: str, component: str, units: int,
                 latitude: float, longitude: float) -> str:
    """Fingerprint for duplicate detection.

    Coordinates are rounded so a few metres of GPS jitter does not defeat
    duplicate detection, but a genuinely different location still produces a
    different fingerprint.
    """
    import hashlib

    raw = f"{actor_id}|{group}|{component}|{units}|{latitude:.3f}|{longitude:.3f}"
    return hashlib.sha256(raw.encode()).hexdigest()[:24]
```

*Listing 21.2. Request fingerprinting.*

<!-- pagebreak -->

# 22. Audit Logging

## 22.1 What is audited

Inventory changes and verification, organization approval and suspension,
hospital priority certification, donation verification, camp approval and
cancellation, emergency lifecycle transitions, account suspension, and role
changes.

## 22.2 The record

```python
def record(
    self,
    *,
    actor_id: str,
    actor_role: str | None,
    action: str,
    resource_type: str,
    resource_id: str,
    correlation_id: str,
    occurred_at: datetime,
    organization_id: str | None = None,
    before: dict | None = None,
    after: dict | None = None,
    metadata: dict | None = None,
) -> dict:
    event_id = str(uuid.uuid4())
    timestamp = to_iso(occurred_at)
    item = {
        "PK": f"RESOURCE#{resource_type}#{resource_id}",
        "SK": f"{timestamp}#{event_id}",
        "GSI1PK": f"ACTOR#{actor_id}",
        "GSI1SK": f"{timestamp}#{event_id}",
        "eventId": event_id,
        "actorId": actor_id,
        "actorRole": actor_role,
        "action": action,
        "resourceType": resource_type,
        "resourceId": resource_id,
        "organizationId": organization_id,
        "correlationId": correlation_id,
        "occurredAt": timestamp,
        "before": before,
        "after": after,
        "metadata": metadata,
    }
    self.put(item)
    return item
```

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
| Unit | 536 | Under a second | Domain logic is correct in isolation |
| Integration | 74 | Seconds | The real datastore enforces the invariants |
| Frontend | 294 | ~2 seconds | Presentation rules hold |

*Table 23.1. Test suites, measured on the run that produced this book.
Overall: 610 backend tests, all passing;
904 including the frontend suite.*

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

```python
NOW = datetime(2026, 11, 15, 12, 0, 0, tzinfo=UTC)
```

*Listing 23.1. The fixed instant from `backend/tests/conftest.py`.*

Because no domain function reads the clock, tests pass an instant and assert
exact boundaries:

```python
@pytest.mark.parametrize(
    ("age_hours", "expected"),
    [
        (0.0, FreshnessLabel.FRESH),
        (5.9, FreshnessLabel.FRESH),
        (6.0, FreshnessLabel.FRESH),       # inclusive upper bound of 0-6h
        (6.1, FreshnessLabel.AGING),
        (23.9, FreshnessLabel.AGING),
        (24.0, FreshnessLabel.AGING),      # inclusive upper bound of >6-24h
        (24.1, FreshnessLabel.STALE),
        (47.9, FreshnessLabel.STALE),
        (48.0, FreshnessLabel.STALE),      # inclusive upper bound of >24-48h
        (48.1, FreshnessLabel.OUTDATED),
        (720.0, FreshnessLabel.OUTDATED),
    ],
)
```

*Listing 23.2. Boundary testing of the freshness bands.*

Every boundary is tested from both sides: 6.0 hours is FRESH, 6.1 is AGING.

## 23.4 The integration fixture

```python
def aws(monkeypatch):
    """A fresh mocked AWS environment with all LifeLink tables created."""
    from moto import mock_aws

    with mock_aws():
        from repositories.dynamo import Tables, _resource, reset_resource_cache, table_name
        from repositories.schema import create_table_kwargs

        reset_resource_cache()
        client = _resource().meta.client
        for logical in Tables.all():
            client.create_table(**create_table_kwargs(logical, table_name(logical)))

        yield client

        reset_resource_cache()
```

*Listing 23.3. The mocked AWS environment.*

Tables are created from the same `create_table_kwargs` the local bootstrap
uses, so the test schema cannot drift from the real one.

## 23.5 Testing what the system refuses

A substantial share of the suite asserts refusals rather than successes:

```python
def test_a_donor_cannot_verify_their_own_donation(self, seeded, camp_service, now):
    organizer = make_context(
        user_id="u-camp-org", roles=("CAMP_ORGANIZER",), organization_id="org-camp-1"
    )
    admin = make_context(user_id="u-admin", roles=("PLATFORM_ADMIN",), organization_id=None)
    donor = make_context(user_id="u-donor-1", roles=("DONOR",), organization_id=None)

    camp = camp_service.create_camp(
        context=organizer, name="Self Camp", description="scenario 9",
        latitude=30.3398, longitude=76.3869, address="1", city="Patiala",
        starts_at=hours_ahead(26), ends_at=hours_ahead(34), capacity=5, now=now,
    )
    camp_id = camp["campId"]
    camp_service.approve_camp(context=admin, camp_id=camp_id, approve=True, now=now)
    camp_service.register(context=donor, camp_id=camp_id, now=now)
    camp_service.check_in(context=organizer, camp_id=camp_id, donor_id="u-donor-1", now=now)
    recorded = camp_service.record_donation(
        context=organizer, camp_id=camp_id, donor_id="u-donor-1",
        blood_group="O-", component="WHOLE_BLOOD", units=1, now=now,
    )

    # The donor is even granted the verify role here, and is still refused.
    self_verifier = make_context(
        user_id="u-donor-1", roles=("DONOR", "CAMP_STAFF"), organization_id="org-camp-1"
    )
    with pytest.raises(ForbiddenError) as exc:
        camp_service.verify_donation(
            context=self_verifier, camp_id=camp_id, donor_id="u-donor-1",
            donation_id=recorded["donationId"], now=now,
        )
    assert exc.value.details["rule"] == "SELF_VERIFICATION_FORBIDDEN"
```

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

```javascript
it('renders UNKNOWN as "Not reported", never as a zero count', () => {
  render(<AvailabilityBadge state="UNKNOWN" units={0} />)
  expect(screen.getByText('Not reported')).toBeInTheDocument()
  expect(screen.queryByText(/0 units/)).not.toBeInTheDocument()
})
```

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

`infrastructure/template.yaml` — 1490 lines,
59 resources, 8 alarms. Validated by
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

```python
def _handle(self, method: str) -> None:
    from handlers.api import ROUTER
    from services.container import get_services

    parsed = urlparse(self.path)
    length = int(self.headers.get("Content-Length") or 0)
    raw_body = self.rfile.read(length).decode("utf-8") if length else ""

    query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
    event = {
        "httpMethod": method,
        "path": parsed.path,
        "queryStringParameters": query,
        "headers": dict(self.headers),
        "body": raw_body,
        "requestContext": {
            "identity": {"sourceIp": self.client_address[0]},
            "http": {"method": method, "sourceIp": self.client_address[0]},
        },
    }

    try:
        services = get_services()
        result = ROUTER.dispatch(event, authenticator=services.authenticator)
    except Exception as exc:  # last-resort guard so the dev server stays up
        result = {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(
                {"error": {"code": "LOCAL_SERVER_ERROR", "message": str(exc)[:500]}}
```

*Listing 26.1. Event translation in `scripts/local_server.py`.*

It builds an API Gateway-shaped event and calls the same router the Lambda
handler calls. There is no separate local application that could drift from the
deployed one; only the transport differs.

## 26.3 Table creation comes from one definition

```python
def create_table_kwargs(logical: str, table_name: str) -> dict[str, Any]:
    """boto3 ``create_table`` arguments for one logical table."""
    definition = TABLE_DEFINITIONS[logical]
    kwargs: dict[str, Any] = {
        "TableName": table_name,
        "KeySchema": [
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        "AttributeDefinitions": [
            {"AttributeName": name, "AttributeType": kind}
            for name, kind in definition["attributes"].items()
        ],
        "BillingMode": "PAY_PER_REQUEST",
    }
    if definition["indexes"]:
        kwargs["GlobalSecondaryIndexes"] = definition["indexes"]
    return kwargs
```

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

Expected at a ceiling of 10. Confirm the ceiling has
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

```python
    # Reminder sweep index. Populated here rather than by callers,
    # because a camp that is missing from this index silently never
    # produces reminders -- and nothing else would reveal that.
    "GSI4PK": "REMINDER#WINDOW",
    "GSI4SK": starts_at,
}
```

*Listing 30.1. The fix in `backend/src/repositories/camp_repo.py`, with a
comment explaining why it must live here rather than in callers.*

It is now covered by `backend/tests/integration/test_camp_reminders.py`, whose
first test asserts the property directly rather than inferring it from the
sweep appearing to work:

```python
def test_a_camp_created_through_the_service_is_in_the_reminder_index(
    self, seeded, camp_service, repos, now
):
    camp = create_camp(camp_service, now)

    rows = repos.camps.query_all(
        key_condition=Key("GSI4PK").eq("REMINDER#WINDOW"),
        index_name="GSI4-reminder",
    )
    ids = {row.get("campId") for row in rows}
    assert camp["campId"] in ids, (
        "a camp created through the API must appear in the reminder index, "
        "or it will silently never produce reminders"
    )
```

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

```python
def require_int(params: dict, name: str, *, default: int | None = None) -> int:
    from domain.errors import ValidationError

    raw = params.get(name)
    if raw is None or raw == "":
        if default is not None:
            return default
        raise ValidationError(f"query parameter '{name}' is required")
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise ValidationError(f"query parameter '{name}' must be an integer") from None
```

*Listing 31.1. Parameter parsing from `backend/src/handlers/router.py`.*

A missing required parameter and an unparseable one produce different messages,
both naming the parameter. "Invalid request" tells a client developer nothing.

## 31.3 Timestamps are validated, not coerced

```python
def parse_iso_param(value: str | None, field: str):
    from domain.clock import parse_iso
    from domain.errors import ValidationError

    if value is None or value == "":
        return None
    try:
        return parse_iso(value)
    except ValueError as exc:
        raise ValidationError(f"'{field}' is not a valid ISO-8601 timestamp: {exc}") from None
```

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

```python
def _assert_camp_staff(self, context: RequestContext, camp_id: str, camp: dict) -> None:
    if "PLATFORM_ADMIN" in context.principal.roles:
        return
    if camp.get("organizerUserId") == context.actor_id:
        return
    if not self._camps.is_camp_staff(camp_id, context.actor_id):
        raise ForbiddenError(
            "you are not assigned to this camp",
            details={"rule": "STAFF_SCOPED_TO_CAMP"},
        )
```

*Listing 32.1. Camp-level scoping from
`backend/src/services/camp_service.py`.*

Being camp staff is not enough; the specification requires staff to be scoped
to the camps they are assigned to, so membership of that camp is checked.

## 32.2 Which permissions are global

```python
GLOBAL_PERMISSIONS: frozenset[Permission] = frozenset({
    Permission.INVENTORY_READ_PUBLIC,
    Permission.FACILITY_READ,
    Permission.CAMP_READ,
    Permission.ALERT_CREATE,
    Permission.RESERVATION_CREATE,
    Permission.PROFILE_MANAGE_OWN,
    Permission.REGISTRATION_CREATE,
    Permission.EMERGENCY_CREATE,
    Permission.ORG_APPROVE,
    Permission.ORG_SUSPEND,
    Permission.HOSPITAL_VERIFY,
    Permission.FACILITY_VERIFY,
    Permission.CAMP_APPROVE,
    Permission.USER_MANAGE,
    Permission.ROLE_ASSIGN,
    Permission.AUDIT_READ,
    Permission.SYSTEM_ADMIN,
```

*Listing 32.2. Global permissions from `backend/src/appcore/rbac.py`.*

Public reads are global because there is no owning organization to compare
against. Administrative actions are global because verifying an organization is
inherently cross-organizational.

Everything else is scoped, and the decorator enforces it without the handler's
participation.

## 32.3 The test that pins it

```python
def test_cross_organization_error_does_not_leak_owner(self):
    p = principal(roles=(Role.BLOOD_BANK_ADMIN,), organization_id="org-1")
    with pytest.raises(CrossOrganizationError) as exc:
        _write_inventory({"ownerOrg": "org-secret"}, ctx(p))
    assert "org-secret" not in str(exc.value)
    assert "org-secret" not in str(exc.value.details)
```

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

```python
def is_near_expiry(expires_at: datetime | None, now: datetime, within_hours: float = 48.0) -> bool:
    """Near-expiry stock is still eligible but is flagged so staff can prioritise it."""
    if expires_at is None:
        return False
    remaining = (expires_at - now).total_seconds() / 3600.0
    return 0 < remaining <= within_hours
```

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

```python
def encode_geohash(latitude: float, longitude: float, precision: int = 9) -> str:
    """Standard geohash encoding (base-32, interleaved lon/lat bits)."""
    if not (1 <= precision <= 12):
        raise ValueError("precision must be 1..12")
    lat_range = [-90.0, 90.0]
    lon_range = [-180.0, 180.0]
    out: list[str] = []
    bits = 0
    bit_count = 0
    even = True  # longitude first

    while len(out) < precision:
        if even:
            mid = (lon_range[0] + lon_range[1]) / 2
            if longitude > mid:
                bits = (bits << 1) | 1
                lon_range[0] = mid
            else:
                bits <<= 1
                lon_range[1] = mid
        else:
            mid = (lat_range[0] + lat_range[1]) / 2
            if latitude > mid:
                bits = (bits << 1) | 1
                lat_range[0] = mid
            else:
                bits <<= 1
                lat_range[1] = mid
        even = not even
        bit_count += 1
        if bit_count == 5:
            out.append(_BASE32[bits])
            bits = 0
            bit_count = 0
    return "".join(out)
```

*Listing 34.1. Geohash encoding from `backend/src/domain/geo.py`.*

Standard base-32 geohash: interleaved longitude and latitude bits, five bits
per character. A shared prefix means geographic proximity, which is what makes
a prefix query a proximity query.

## 34.2 Choosing a precision

```python
def choose_precision(radius_km: float) -> int:
    """Pick a geohash precision whose cell size is comparable to the radius.

    Each cell costs one indexed query, so precision directly sets the fan-out of
    a search. Three tiers, each backed by its own GSI, with boundaries chosen so
    that the worst case in every tier stays well under MAX_SEARCH_CELLS:

        <= 3 km   precision 6  (~1.05 x 0.61 km cells)  worst case ~60 cells
        <= 20 km  precision 5  (~4.2 x 4.88 km cells)   worst case ~95 cells
        > 20 km   precision 4  (~33.8 x 19.5 km cells)  worst case ~71 cells

    The boundaries are deliberately lower than the cell size alone would
    suggest. Measured during integration testing, a 5 km search at precision 6
    needed 195 queries and a 100 km search at precision 5 needed 2,107 -- both
    untenable in general, and especially at this account's Lambda concurrency
    ceiling of 10.
    """
    if radius_km <= 3:
        return 6
    if radius_km <= 20:
        return 5
    return 4
```

*Listing 34.2. Precision tiers.*

The docstring records the measured numbers that produced these boundaries,
including the two failures that forced the design. Writing "5 km uses precision
6" without saying that the naive boundary needed 195 queries would leave the
next person to re-derive it.

## 34.3 Covering the search circle

```python
def search_cells(latitude: float, longitude: float, radius_km: float) -> tuple[int, list[str]]:
    """Every cell that can contain a point within ``radius_km`` of the origin.

    Returns (precision, cells).

    This walks the bounding box of the search circle in cell-sized steps rather
    than returning only the centre cell's eight neighbours. The neighbour-only
    shortcut is correct only while the radius is smaller than one cell; beyond
    that it silently omits facilities that are genuinely in range, which in a
    blood search means a usable facility simply never appears. The cell set is
    always a superset of the true result, and exact Haversine filtering then
    removes the corners of the box.
    """
    if radius_km <= 0:
        raise ValueError("radius must be positive")
    if radius_km > MAX_SEARCH_RADIUS_KM:
        raise ValueError(f"radius exceeds maximum of {MAX_SEARCH_RADIUS_KM} km")

    precision = choose_precision(radius_km)
    center_hash = encode_geohash(latitude, longitude, precision)
    lat_min, lat_max, lon_min, lon_max = decode_geohash(center_hash)
    lat_step = lat_max - lat_min
    lon_step = lon_max - lon_min

    # Degrees of latitude/longitude spanned by the radius at this latitude.
    lat_degrees = radius_km / 110.574
    cos_lat = max(0.01, math.cos(math.radians(latitude)))
    lon_degrees = radius_km / (111.320 * cos_lat)

    lat_cells = int(math.ceil(lat_degrees / lat_step))
    lon_cells = int(math.ceil(lon_degrees / lon_step))

    cells: list[str] = [center_hash]
    seen = {center_hash}
    for i in range(-lat_cells, lat_cells + 1):
        for j in range(-lon_cells, lon_cells + 1):
            if i == 0 and j == 0:
                continue
            lat = latitude + i * lat_step
            lon = longitude + j * lon_step
            if not (-90.0 <= lat <= 90.0):
                continue
            if lon > 180.0:
                lon -= 360.0
            elif lon < -180.0:
                lon += 360.0

            # Skip cells whose nearest corner is still outside the circle --
            # these are the corners of the bounding box and can contain no
            # in-range point, so querying them would be pure waste.
            if not _cell_intersects_circle(
                lat, lon, precision, latitude, longitude, radius_km
            ):
                continue

            cell = encode_geohash(lat, lon, precision)
            if cell not in seen:
                seen.add(cell)
                cells.append(cell)

    if len(cells) > MAX_SEARCH_CELLS:
        # Defensive: the precision tiers keep this well under the limit, so
        # tripping it means a tier was mis-sized rather than a bad request.
        raise ValueError(
            f"search would require {len(cells)} cell queries "
            f"(limit {MAX_SEARCH_CELLS}); reduce the radius"
        )
    return precision, cells
```

*Listing 34.3. Cell coverage.*

Two properties, both tested. The cell set is a **superset** of the search
circle, so no in-range facility is missed. And cells whose nearest corner lies
outside the radius are skipped, because they cannot contain an in-range point
and querying them is pure waste.

## 34.4 The property test

```python
@pytest.mark.parametrize("radius_km", [1, 3, 5, 10, 15, 20, 30, 50, 75, 100])
def test_cell_set_covers_every_point_on_the_radius_boundary(self, radius_km):
    """Walk the circle at the search radius; each point's cell must be covered.

    Points exactly on the boundary are the hardest case and the ones a
    neighbour-only cell set gets wrong.
    """
    precision, cells = search_cells(PATIALA.latitude, PATIALA.longitude, radius_km)
    covered = set(cells)

    lat_degrees = radius_km / 110.574
    lon_degrees = radius_km / (111.320 * math.cos(math.radians(PATIALA.latitude)))

    missed = []
    for degrees in range(0, 360, 5):
        theta = math.radians(degrees)
        # Slightly inside the radius so the point is genuinely in range.
        lat = PATIALA.latitude + 0.999 * lat_degrees * math.sin(theta)
        lon = PATIALA.longitude + 0.999 * lon_degrees * math.cos(theta)
        cell = encode_geohash(lat, lon, precision)
        if cell not in covered:
            missed.append((degrees, cell))

    assert not missed, (
        f"radius {radius_km}km missed {len(missed)} bearings, "
        f"e.g. {missed[:3]}"
    )
```

*Listing 34.4. Coverage asserted as a property, from
`backend/tests/unit/test_geo_coverage.py`.*

Walking the circle at the search radius and checking every bearing's cell is in
the set. Boundary points are the hardest case and the ones the original
implementation got wrong.

<!-- pagebreak -->

# 35. Ranking Implementation

## 35.1 Weights are validated

```python
@dataclass(frozen=True, slots=True)
class RankingWeights:
    """The spec's proposed initial weighting. Configurable; must sum to 1.0."""

    availability: float = 0.30
    quantity: float = 0.15
    freshness: float = 0.20
    verification: float = 0.15
    distance: float = 0.20

    def __post_init__(self):
        total = (
            self.availability
            + self.quantity
            + self.freshness
            + self.verification
            + self.distance
        )
        if abs(total - 1.0) > 1e-9:
            raise ValueError(f"ranking weights must sum to 1.0, got {total}")
```

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

```python
def rank_facilities(
    items: list[RankingInput], weights: RankingWeights = DEFAULT_WEIGHTS
) -> list[RankedFacility]:
    """Rank already-eligibility-filtered facilities, best first.

    Callers must filter out hard-ineligible facilities BEFORE calling this.
    Ties break on distance, then id, so ordering is deterministic and testable.
    """
    scored = [score_facility(i, weights) for i in items]
    by_id = {i.facility_id: i for i in items}
    scored.sort(key=lambda r: (-r.score, by_id[r.facility_id].distance_km, r.facility_id))
    return scored
```

*Listing 35.3. Ranking with deterministic tie-breaks.*

Ties break on distance, then on facility id. Without the final tie-break,
two facilities with identical scores and distances could order differently
between calls, which makes results irreproducible and tests flaky.

<!-- pagebreak -->

# 36. Compatibility Matching

## 36.1 Rules as data

```python
def _load_reference(filename: str) -> CompatibilityReference:
    path = REFERENCE_DIR / filename
    if not path.is_file():
        raise ValidationError(
            f"compatibility reference '{filename}' not found",
            details={"searched": str(path)},
        )
    data = json.loads(path.read_text(encoding="utf-8"))

    # Fail fast rather than silently treating an unlabelled table as authoritative.
    for required in ("version", "reviewStatus", "rules", "disclaimer"):
        if required not in data:
            raise ValidationError(
                f"compatibility reference is missing required field '{required}'",
                details={"file": filename},
            )

    return CompatibilityReference(
        version=data["version"],
        review_status=data["reviewStatus"],
        reviewed_by=data.get("reviewedBy"),
        source_citation=data.get("sourceCitation", ""),
        disclaimer=data["disclaimer"],
        rules=data["rules"],
        identical_preferred=frozenset(data.get("identicalPreferred", [])),
    )
```

*Listing 36.1. Reference loading from
`backend/src/domain/compatibility.py`.*

The loader refuses to start if the file lacks a `reviewStatus`. An unlabelled
compatibility table could be mistaken for a reviewed one, and that is the
single most consequential mistake available in this system.

## 36.2 Lookup only

```python
def check_compatibility(
    *,
    recipient_group: BloodGroup,
    donor_group: BloodGroup,
    component: Component,
    reference: CompatibilityReference | None = None,
) -> CompatibilityResult:
    """Table lookup only. No inference of any kind."""
    ref = reference or get_reference()
    donors = ref.compatible_donor_groups(recipient_group, component)

    identical_preferred = component.value in ref.identical_preferred
    is_identical = recipient_group == donor_group

    if donors is None:
        verdict = CompatibilityVerdict.UNKNOWN
    elif donor_group.value in donors:
        verdict = CompatibilityVerdict.COMPATIBLE
    else:
        verdict = CompatibilityVerdict.INCOMPATIBLE

    requires_review = (
        verdict == CompatibilityVerdict.COMPATIBLE
        and identical_preferred
        and not is_identical
    )

    return CompatibilityResult(
        verdict=verdict,
        rules_version=ref.version,
        review_status=ref.review_status,
        identical_preferred=identical_preferred,
        requires_clinical_review=requires_review,
        disclaimer=ref.disclaimer,
    )
```

*Listing 36.2. The lookup.*

No inference, no similarity, no fallback. A combination absent from the table
returns `UNKNOWN`, and `is_match` is true only for an explicit `COMPATIBLE`.

## 36.3 Fail-closed donor groups

```python
def compatible_donor_groups(
    *,
    recipient_group: BloodGroup,
    component: Component,
    reference: CompatibilityReference | None = None,
) -> tuple[BloodGroup, ...]:
    """Groups the matching engine may search for. Empty tuple when UNKNOWN.

    Returning empty rather than "all groups" on an unknown combination is the
    fail-closed behaviour the spec requires.
    """
    ref = reference or get_reference()
    donors = ref.compatible_donor_groups(recipient_group, component)
    if donors is None:
        return ()
    return tuple(BloodGroup(g) for g in donors)
```

*Listing 36.3. Returning an empty tuple on unknown.*

Returning all groups on an unknown combination would be the convenient choice
and a dangerous one. The empty tuple means the matching engine finds nothing,
which is the correct behaviour when the system does not know.

## 36.4 Plasma runs the other way

A table that is merely copied often gets this wrong, so there is a test:

```python
def test_ab_is_the_universal_plasma_donor(self):
    for recipient in BloodGroup:
        result = check_compatibility(
            recipient_group=recipient,
            donor_group=BloodGroup.AB_POS,
            component=Component.FFP,
        )
        assert result.is_match is True, f"AB+ plasma should suit {recipient}"
```

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

```python
def is_opted_in(self, user_id: str, category: str) -> tuple[bool, str | None]:
    prefs = self.get_preferences(user_id)
    if not prefs.get("consentGiven"):
        return False, "NO_CONSENT"
    key = CATEGORY_PREFERENCE_KEY.get(category)
    if key is not None and not prefs.get(key, True):
        return False, "CATEGORY_OPTED_OUT"
    if not prefs.get("channels"):
        return False, "NO_CHANNELS_SELECTED"
    return True, None
```

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

```python
def mark_sent_marker(self, *, user_id: str, dedupe_key: str, now: datetime) -> bool:
    """Claim a duplicate-suppression marker.

    Returns True when this is the first send for the key. Camp reminders and
    alert notifications both use this so a retried job cannot double-notify.
    """
    expires = now + timedelta(days=30)
    try:
        self.put(
            {
                "PK": f"USER#{user_id}",
                "SK": f"SENT#{dedupe_key}",
                "sentAt": to_iso(now),
                "expiresAtEpoch": int(expires.timestamp()),
            },
            condition=Attr("SK").not_exists(),
        )
        return True
    except Exception:
        return False
```

*Listing 37.2. The suppression marker.*

A conditional put on a dedupe key. A retried job finds the marker and
suppresses. The marker has a TTL so the table does not grow without bound.

## 37.4 Fan-out is sequential, deliberately

```python
def notify_many(
    self, *, user_ids: list[str], category: str, subject: str, body: str,
    now: datetime, metadata: dict | None = None, dedupe_prefix: str | None = None
) -> list[NotificationOutcome]:
    """Fan out to several users, one at a time.

    Deliberately sequential: SES in sandbox permits one message per second,
    so a burst would be throttled anyway, and the concurrency ceiling makes
    parallel fan-out counterproductive here.
    """
    outcomes: list[NotificationOutcome] = []
    for user_id in user_ids:
        dedupe = f"{dedupe_prefix}#{user_id}" if dedupe_prefix else None
        outcomes.append(
            self.notify(
                user_id=user_id,
                category=category,
                subject=subject,
                body=body,
                now=now,
                metadata=metadata,
                dedupe_key=dedupe,
            )
        )
    return outcomes
```

*Listing 37.3. Sequential fan-out.*

SES in sandbox permits one message per second, so a parallel burst would be
throttled anyway. At a Lambda concurrency ceiling of
10, parallel fan-out would also consume capacity the
API needs.

<!-- pagebreak -->

# 38. The Impact Ledger

## 38.1 The ledger is the truth

```python
def compute_score(entries: list[LedgerEntry]) -> int:
    """Total score is always derived from the ledger, never stored as truth.

    A cached counter may exist for display, but any disagreement is resolved in
    favour of the ledger -- which is what makes the recalculation edge case safe.
    """
    return sum(e.points for e in entries)
```

*Listing 38.1. Score derivation from `backend/src/domain/impact.py`.*

A cached counter may exist for display, but any disagreement resolves in favour
of the ledger. That makes recalculation safe: it is a read, not a repair.

## 38.2 Exactly once, enforced by a key

```python
def verify_donation_and_credit(
    self,
    *,
    donor_id: str,
    donation_id: str,
    verifier_id: str,
    points: int,
    now: datetime,
) -> dict:
    """Verify the donation and write the ledger entry in one transaction.

    The ledger row is keyed on the donation id with a not-exists condition,
    so a replayed verification event cannot credit twice. This is the
    mechanism behind the spec's "credited exactly once" acceptance criterion.
    """
    donations_table = table_name(self.logical_table)
    timestamp = to_iso(now)

    operations = [
        {
            "Update": {
                "TableName": donations_table,
                "Key": to_dynamo({"PK": f"USER#{donor_id}", "SK": f"DONATION#{donation_id}"}),
                "UpdateExpression": (
                    "SET #s = :verified, verifiedBy = :by, verifiedAt = :at"
                ),
                "ConditionExpression": "attribute_exists(SK) AND #s = :recorded",
                "ExpressionAttributeNames": {"#s": "status"},
                "ExpressionAttributeValues": to_expression_values(
                    {
                        ":verified": "VERIFIED",
                        ":recorded": "RECORDED",
                        ":by": verifier_id,
                        ":at": timestamp,
                    }
                ),
            }
        },
        {
            "Put": {
                "TableName": donations_table,
                "Item": to_dynamo(
                    clean(
                        {
                            "PK": f"USER#{donor_id}",
                            "SK": f"LEDGER#{donation_id}",
                            "entityType": "LEDGER_ENTRY",
                            "donationId": donation_id,
                            "donorId": donor_id,
                            "points": points,
                            "reason": "VERIFIED_DONATION",
                            "occurredAt": timestamp,
                            "verifiedBy": verifier_id,
                        }
                    )
                ),
                "ConditionExpression": "attribute_not_exists(SK)",
            }
        },
    ]

    transact_write(operations)
    return {
        "donationId": donation_id,
        "donorId": donor_id,
        "status": "VERIFIED",
        "pointsAwarded": points,
        "verifiedAt": timestamp,
    }
```

*Listing 38.2. The crediting transaction from
`backend/src/repositories/camp_repo.py`.*

The ledger row's sort key is `LEDGER#<donationId>` with
`attribute_not_exists(SK)`. A replayed verification cannot create a second
entry for the same donation, because the key is the same and the condition
fails.

## 38.3 Milestones announce once

```python
def newly_earned_milestones(previous_count: int, new_count: int) -> list[Milestone]:
    """Milestones crossed by this donation -- used to avoid re-announcing old ones."""
    before = set(earned_milestones(previous_count))
    after = set(earned_milestones(new_count))
    gained = after - before
    return [m for m in MILESTONE_THRESHOLDS if m in gained]
```

*Listing 38.3. Only newly crossed milestones.*

Comparing the before and after sets means a donor is congratulated on crossing
a threshold, not every time they donate thereafter.

## 38.4 Interval advice is information, not clearance

```python
def donation_interval_advice(
    last_donation_at: datetime | None,
    now: datetime,
    interval_days: int = MIN_DONATION_INTERVAL_DAYS,
) -> DonationIntervalAdvice:
    """Informational interval guidance.

    This is deliberately NOT a medical eligibility decision. LifeLink cannot
    assess fitness to donate; it only reports elapsed time and points the user at
    camp staff. The wording here is part of that commitment.
    """
    if last_donation_at is None:
        return DonationIntervalAdvice(
            eligible_by_interval=True,
            days_since_last=None,
            next_eligible_date=None,
            message=(
                "No previous verified donation on record. Camp staff will assess "
                "your eligibility on the day."
            ),
        )

    days = (now - last_donation_at).days
    next_date = last_donation_at + timedelta(days=interval_days)
    if days >= interval_days:
        return DonationIntervalAdvice(
            eligible_by_interval=True,
            days_since_last=days,
            next_eligible_date=next_date,
            message=(
                f"{days} days since your last verified donation. Final eligibility "
                "is determined by camp staff, not by this app."
            ),
        )
    return DonationIntervalAdvice(
        eligible_by_interval=False,
        days_since_last=days,
        next_eligible_date=next_date,
        message=(
            f"Only {days} days since your last verified donation. The usual minimum "
            f"interval is {interval_days} days. Please speak to camp staff before "
            "registering."
        ),
    )
```

*Listing 38.4. Interval advice.*

The wording is part of the implementation. Every branch points the user at camp
staff, and a test asserts that no message contains "eligible to donate" or
"you are cleared" — LifeLink cannot assess fitness to donate and must not imply
that it has.

<!-- pagebreak -->

# 39. Certificates

## 39.1 Generated from verified records only

```python
def certificate_data(self, *, context: RequestContext, donation_id: str) -> dict:
    """Certificate payload, generated from verified records only.

    Private to the donor and explicitly labelled as recognition -- not a
    medical certificate, government document or proof of eligibility.
    """
    donation = self._donations.get_donation(context.actor_id, donation_id)
    if donation is None:
        raise NotFoundError("donation not found", details={"donationId": donation_id})
    if donation.get("status") != DonationStatus.VERIFIED.value:
        raise ValidationError(
            "certificates are issued only for verified donations",
            details={"status": donation.get("status")},
        )
    user = self._identity.get_user(context.actor_id) or {}
    camp = self._camps.get_camp(donation["campId"]) or {}
    return {
        "certificateId": f"CERT-{donation_id}",
        "donorName": user.get("displayName", "Donor"),
        "donationId": donation_id,
        "campName": camp.get("name"),
        "donatedAt": donation.get("recordedAt"),
        "verifiedAt": donation.get("verifiedAt"),
        "units": donation.get("units"),
        "component": donation.get("component"),
        "documentType": "RECOGNITION_CERTIFICATE",
        "disclaimer": (
            "This is a recognition document issued by LifeLink. It is not a "
            "medical certificate, not a government document, and not proof of "
            "medical eligibility to donate."
        ),
    }
```

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

```python
VALID_TRANSITIONS: dict[RequestStatus, frozenset[RequestStatus]] = {
    RequestStatus.REQUEST_CREATED: frozenset(
        {RequestStatus.VERIFICATION_PENDING, RequestStatus.CANCELLED, RequestStatus.EXPIRED}
    ),
    RequestStatus.VERIFICATION_PENDING: frozenset(
        {RequestStatus.HOSPITAL_CERTIFIED, RequestStatus.CANCELLED, RequestStatus.EXPIRED}
    ),
    RequestStatus.HOSPITAL_CERTIFIED: frozenset(
        {RequestStatus.MATCHING_INITIATED, RequestStatus.CANCELLED, RequestStatus.EXPIRED}
    ),
    RequestStatus.MATCHING_INITIATED: frozenset(
        {RequestStatus.PROVIDERS_NOTIFIED, RequestStatus.CANCELLED, RequestStatus.EXPIRED}
    ),
    RequestStatus.PROVIDERS_NOTIFIED: frozenset(
        {RequestStatus.RESPONSES_RECEIVED, RequestStatus.CANCELLED, RequestStatus.EXPIRED}
    ),
    RequestStatus.RESPONSES_RECEIVED: frozenset(
        {
            RequestStatus.AVAILABILITY_CONFIRMED,
            RequestStatus.MATCHING_INITIATED,  # re-match when every provider declined
            RequestStatus.CANCELLED,
            RequestStatus.EXPIRED,
        }
    ),
    RequestStatus.AVAILABILITY_CONFIRMED: frozenset(
        {RequestStatus.RESOLVED, RequestStatus.CANCELLED, RequestStatus.EXPIRED}
    ),
    RequestStatus.RESOLVED: frozenset(),
    RequestStatus.CANCELLED: frozenset(),
    RequestStatus.EXPIRED: frozenset(),
}


def can_transition(current: RequestStatus, target: RequestStatus) -> bool:
```

*Listing 40.1. The transition table from
`backend/src/domain/emergency.py`.*

A table rather than scattered conditionals. Adding a state is one entry;
auditing which transitions exist is reading one structure.

## 40.2 Rejection names the alternatives

```python
def assert_transition(current: RequestStatus, target: RequestStatus) -> None:
    """Raise unless the transition is permitted. Called by every state change."""
    if not can_transition(current, target):
        raise InvalidStateTransitionError(
            f"cannot move request from {current.value} to {target.value}",
            details={
                "from": current.value,
                "to": target.value,
                "allowed": sorted(s.value for s in VALID_TRANSITIONS[current]),
            },
        )
```

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

```python
def record_provider_notification(
    self, *, request_id: str, provider_org_id: str, facility_id: str, now: datetime
) -> dict:
    """A provider has been asked to respond. Creates the response placeholder."""
    item = {
        "PK": _pk(request_id),
        "SK": f"RESPONSE#{provider_org_id}",
        "GSI3PK": f"PROVIDER#{provider_org_id}",
        "GSI3SK": f"PENDING#{to_iso(now)}#{request_id}",
        "entityType": "PROVIDER_RESPONSE",
        "requestId": request_id,
        "providerOrganizationId": provider_org_id,
        "facilityId": facility_id,
        "responseType": None,
        "notifiedAt": to_iso(now),
        "status": "AWAITING_RESPONSE",
    }
    self.put(item)
    return item
```

*Listing 41.1. The response placeholder from
`backend/src/repositories/emergency_repo.py`.*

Creating the row when the provider is notified gives the submission path
something to condition on. A provider who was never asked has no row, so their
response is refused.

## 41.2 Submission is conditional

```python
def submit_response(
    self,
    *,
    request_id: str,
    provider_org_id: str,
    response_type: str,
    units_offered: int,
    actor_id: str,
    now: datetime,
    note: str | None = None,
) -> dict:
    """Record a provider's response.

    ``unitsOffered`` is a statement of willingness, not a reservation -- it
    never decrements inventory (ADR-0017). Two providers may each offer the
    same count and both are recorded in full; nothing nets them against a
    shared counter because no such counter exists.

    The condition ensures a provider cannot respond twice, and that a
    provider who was never notified cannot respond at all.
    """
    updated = self.update(
        pk=_pk(request_id),
        sk=f"RESPONSE#{provider_org_id}",
        update_expression=(
            "SET responseType = :t, unitsOffered = :u, respondedAt = :at, "
            "respondedBy = :by, #s = :status, note = :note, GSI3SK = :gsi3sk"
        ),
        expression_values={
            ":t": response_type,
            ":u": units_offered,
            ":at": to_iso(now),
            ":by": actor_id,
            ":status": "RESPONDED",
            ":note": note,
            ":gsi3sk": f"RESPONDED#{to_iso(now)}#{request_id}",
        },
        expression_names={"#s": "status"},
        condition=Attr("SK").exists() & Attr("status").eq("AWAITING_RESPONSE"),
    )
    self.append_event(
        request_id=request_id,
        event_type="PROVIDER_RESPONDED",
        actor_id=actor_id,
        now=now,
        detail={
            "providerOrganizationId": provider_org_id,
            "responseType": response_type,
            "unitsOffered": units_offered,
        },
    )
    return updated
```

*Listing 41.2. Response submission.*

The condition requires the row to exist and still be `AWAITING_RESPONSE`. A
second response from the same provider fails it.

## 41.3 The tally never nets

```python
def tally_responses(responses: list[dict]) -> ResponseTally:
    """Summarise responses without mutating or reserving any stock."""
    accepted = rejected = insufficient = clarification = units = 0
    for r in responses:
        kind = ProviderResponseType(r["responseType"])
        if kind == ProviderResponseType.ACCEPTED:
            accepted += 1
            units += int(r.get("unitsOffered") or 0)
        elif kind == ProviderResponseType.REJECTED:
            rejected += 1
        elif kind == ProviderResponseType.INSUFFICIENT_STOCK:
            insufficient += 1
            # Partial offers still count toward what is on the table.
            units += int(r.get("unitsOffered") or 0)
        else:
            clarification += 1
    return ResponseTally(accepted, rejected, insufficient, clarification, units)
```

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
| Account and region | `aws sts get-caller-identity` | 426150327442, ap-southeast-2 |
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

59 resources including 12 DynamoDB
tables, 6 Lambda functions, 2 queues with 2 dead-letter queues, a Cognito user
pool and identity pool, 2 S3 buckets, a CloudFront distribution, 3 Amazon
Location resources, a KMS key, 8 alarms and a dashboard.

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

```python
freshness_plan = [
    (1, "fresh"), (3, "fresh"),
    (10, "aging"), (18, "aging"),
    (30, "stale"), (40, "stale"),
    (72, "outdated"), (120, "outdated"),
]
```

*Listing 44.2. The freshness spread from `scripts/seed_demo.py`.*

Fifty batches in each freshness band, so the four labels are all visible on
screen rather than theoretically reachable. Similar deliberate placement
covers quarantined stock, expired stock, near-expiry stock, zero-unit batches,
and a facility that has reported nothing at all.

## 44.4 The production guard

```python
def guard_environment() -> None:
    """Refuse to seed anything that might be production (spec 11.3)."""
    env = os.environ.get("LIFELINK_ENV", "local").lower()
    if env not in ("local", "dev", "development", "test"):
        print(f"REFUSING TO SEED: LIFELINK_ENV is '{env}'.")
        print("Synthetic demo data must never be seeded into staging or production.")
        raise SystemExit(2)
    endpoint = os.environ.get("DYNAMODB_ENDPOINT", "")
    if env in ("local", "test") and not endpoint:
        print("REFUSING TO SEED: local mode requires DYNAMODB_ENDPOINT to be set.")
        print("This prevents a local seed run from writing to real AWS tables.")
        raise SystemExit(2)
    if endpoint and "amazonaws.com" in endpoint:
        print("REFUSING TO SEED: DYNAMODB_ENDPOINT points at real AWS.")
        raise SystemExit(2)
```

*Listing 44.3. Three independent refusals.*

Three checks rather than one, because a single condition is one typo away from
being bypassed. The environment name must be local, dev or test; a local
endpoint must be configured; and the endpoint must not point at real AWS.

## 44.5 Validation as a first-class command

```python
checks.append(("all 8 blood groups present",
               groups_present >= {g.value for g in ALL_GROUPS},
               f"{len(groups_present)}/8"))
checks.append(("all 4 components present",
```

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

```python
def build_document() -> dict:
    from handlers.api import ROUTER

    paths: dict[str, dict] = {}
    tags_seen: dict[str, str] = {}

    for route in sorted(ROUTER.routes, key=lambda r: (r.path, r.method)):
        tag = tag_for(route.path)
        tags_seen.setdefault(tag, tag)

        parameters = []
        for name in re.findall(r"\{([a-zA-Z0-9_]+)\}", route.path):
            parameters.append(
                {
                    "name": name,
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                }
            )

        responses: dict[str, dict] = {
            "200": {
                "description": "Success",
                "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Envelope"}}},
            }
        }
        if route.method == "POST":
            responses["201"] = {
                "description": "Created",
                "content": {
                    "application/json": {"schema": {"$ref": "#/components/schemas/Envelope"}}
                },
            }
        if route.method == "DELETE":
            responses["204"] = {"description": "Deleted, no content"}

        for status, codes in ERROR_CODES.items():
            # Only document the statuses a route can actually produce.
            if status == 401 and route.allow_anonymous:
                continue
            if status == 403 and route.permission is None:
                continue
            responses[str(status)] = {
                "description": f"Error. Possible codes: {', '.join(codes)}",
                "content": {
                    "application/json": {"schema": {"$ref": "#/components/schemas/Error"}}
                },
            }

        operation = {
            "summary": route.summary or f"{route.method} {route.path}",
            "operationId": operation_id(route.method, route.path),
            "tags": [tag],
            "parameters": parameters,
            "responses": responses,
        }

        if route.permission is not None:
            operation["description"] = (
                f"Requires permission `{route.permission.value}`. "
                + (
                    "Anonymous access is permitted for this route."
                    if route.allow_anonymous
                    else "Authentication is required."
                )
                + " Authorization is enforced server-side on every request, including "
                "account status and resource ownership."
            )
            operation["x-lifelink-permission"] = route.permission.value

        if route.allow_anonymous:
            operation["security"] = [{}, {"bearerAuth": []}]
        else:
            operation["security"] = [{"bearerAuth": []}]

        if route.method in ("POST", "PUT", "PATCH"):
            operation["requestBody"] = {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {"type": "object", "additionalProperties": True}
                    }
                },
            }
            operation.setdefault("parameters", []).append(
                {
                    "name": "Idempotency-Key",
                    "in": "header",
                    "required": False,
                    "schema": {"type": "string"},
                    "description": (
                        "Client-supplied key. Repeating a request with the same key "
                        "returns the original result instead of repeating the effect."
                    ),
                }
            )

        paths.setdefault(route.path, {})[route.method.lower()] = operation

    return {
        "openapi": "3.0.3",
        "info": {
            "title": "LifeLink API",
            "version": "0.1.0",
            "description": (
                "Blood availability, facility discovery, voluntary donation and "
                "emergency coordination.\n\n"
                "**This document is generated from the live route table** "
                "(`backend/src/handlers/api.py`) by `scripts/generate_openapi.py`, "
                "so it cannot describe an endpoint that does not exist.\n\n"
                "Every response uses one envelope: `{ data, meta?, correlationId }` on "
                "success and `{ error: { code, message, details? } }` on failure. "
                "Clients should branch on `error.code`, which is stable, rather than on "
                "the message, which is not.\n\n"
                "**What this API does not do.** It does not reserve or allocate blood, "
                "does not determine clinical urgency, and does not certify clinical "
                "suitability. Availability figures are reported by facilities and carry "
                "both a freshness label and a separate independent-verification status."
            ),
            "contact": {"name": "LifeLink project"},
        },
        "servers": [
            {"url": "http://127.0.0.1:8080", "description": "Local development"},
            {
                "url": "https://{apiId}.execute-api.{region}.amazonaws.com/{stage}",
                "description": "AWS deployment (not currently deployed)",
                "variables": {
                    "apiId": {"default": "example"},
                    "region": {"default": "ap-southeast-2"},
                    "stage": {"default": "dev"},
                },
            },
        ],
        "tags": [{"name": tag} for tag in sorted(tags_seen)],
        "components": {
            "securitySchemes": {
                "bearerAuth": {
                    "type": "http",
                    "scheme": "bearer",
                    "bearerFormat": "JWT",
                    "description": (
                        "Amazon Cognito access token in AWS; a locally issued "
                        "development token when running locally. Roles and account "
                        "status are read from the database on every request, not from "
                        "token claims, so a suspended account is rejected immediately."
                    ),
                }
            },
            "schemas": {"Envelope": ENVELOPE_SCHEMA, "Error": ERROR_SCHEMA},
        },
        "paths": paths,
    }
```

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

```python
event = {
    "httpMethod": method,
    "path": parsed.path,
    "queryStringParameters": query,
    "headers": dict(self.headers),
    "body": raw_body,
    "requestContext": {
        "identity": {"sourceIp": self.client_address[0]},
        "http": {"method": method, "sourceIp": self.client_address[0]},
    },
}

```

*Listing 46.1. Event construction from `scripts/local_server.py`.*

The shape matches what API Gateway delivers, so the router and every handler
behave identically. The specification warns against a mock application that
behaves differently from the real architecture; the way to avoid that is to
have only one application.

## 46.2 CORS in development

```python
def _cors_headers(self) -> dict:
    origin = self.headers.get("Origin", "")
    allow = origin if origin in ALLOWED_ORIGINS else ALLOWED_ORIGINS[0]
    return {
        "Access-Control-Allow-Origin": allow,
        "Access-Control-Allow-Methods": "GET,POST,PUT,PATCH,DELETE,OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type,Authorization,Idempotency-Key,X-Correlation-Id",
        "Access-Control-Max-Age": "600",
        "Vary": "Origin",
    }
```

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

```python
class LifeLinkError(Exception):
    """Base class. ``code`` is part of the API contract; ``message`` is for humans."""

    code = "INTERNAL_ERROR"
    http_status = 500

    def __init__(self, message: str, *, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "details": self.details}
```

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

```python
def translate_client_error(exc: ClientError, *, context: str = "") -> LifeLinkError:
    code = exc.response.get("Error", {}).get("Code", "")
    if code == "ConditionalCheckFailedException":
        return ConcurrentModificationError(
            f"the record changed while this operation was in flight{': ' + context if context else ''}",
            details={"hint": "re-read the record and retry"},
        )
    if code == "TransactionCanceledException":
        reasons = exc.response.get("CancellationReasons", []) or []
        codes = [r.get("Code") for r in reasons]
        if "ConditionalCheckFailed" in codes:
            return ConcurrentModificationError(
                "a concurrent change prevented this transaction from completing",
                details={"reasons": codes},
            )
        if "TransactionConflict" in codes:
            return ConcurrentModificationError(
                "another transaction is modifying these records",
                details={"reasons": codes},
            )
        return LifeLinkError(f"transaction cancelled: {codes}")
    if code in ("ProvisionedThroughputExceededException", "ThrottlingException",
                "RequestLimitExceeded"):
        from domain.errors import RateLimitedError

        return RateLimitedError("the datastore is throttling requests; retry shortly")
    if code == "ResourceNotFoundException":
        from domain.errors import NotFoundError

        return NotFoundError(f"storage table not found{': ' + context if context else ''}")
    return LifeLinkError(f"datastore error ({code}){': ' + context if context else ''}")
```

*Listing 47.4. DynamoDB errors mapped onto the domain taxonomy.*

Nothing above the repository layer sees a `ClientError`. Transaction
cancellations are unpacked so a conditional-check failure becomes a
concurrency error rather than an opaque "transaction cancelled".

## 47.5 The boundary

```python
except LifeLinkError as exc:
    return from_exception(exc)

log = get_logger(__name__, context)
enriched = {**event, "pathParameters": {**(event.get("pathParameters") or {}), **params}}

try:
    result = route.handler(enriched, context)
    log.info(
        f"{method} {path} -> {result.get('statusCode', 200)}",
        event="http.request",
        method=method,
        path=path,
        status=result.get("statusCode", 200),
```

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

```css
/* Status: data freshness */
--fresh: #0f7a4f;
--fresh-bg: #e6f5ee;
--aging: #8a6a00;
--aging-bg: #fdf6e3;
--stale: #a04a00;
--stale-bg: #fdefe3;
--outdated: #7a1420;
--outdated-bg: #fbeaec;

```

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

```python
def _extract_region(path: Path, selector: str) -> str:
    """Extract a region of a file for inclusion in a book.

    Selectors, in order of preference:

        def name / class name   a Python definition, located by parsing
        anchor:TEXT:N           N lines starting at the first line containing TEXT
        anchor:TEXT:until:END   from the first line containing TEXT to the next END
        START-END               raw line numbers

    Raw line numbers are supported but discouraged, and the builder warns about
    them. They silently point at the wrong code the moment a file is edited
    above the range -- which happened during this project and put an unrelated
    SQS block under a caption about IAM grants.
    """
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    anchor = re.fullmatch(r"anchor:(.+?):(\d+)", selector)
    if anchor:
        needle = anchor.group(1)
        count = int(anchor.group(2))
        for index, line in enumerate(lines):
            if needle in line:
                return "\n".join(lines[index:index + count])
        raise ValueError(f"{path}: no line contains anchor text {needle!r}")

    anchor_until = re.fullmatch(r"anchor:(.+?):until:(.+)", selector)
    if anchor_until:
        needle = anchor_until.group(1)
        terminator = anchor_until.group(2)
        start_index = None
        for index, line in enumerate(lines):
            if needle in line:
                start_index = index
                break
        if start_index is None:
            raise ValueError(f"{path}: no line contains anchor text {needle!r}")
        for index in range(start_index + 1, len(lines)):
            if terminator in lines[index]:
                return "\n".join(lines[start_index:index])
        return "\n".join(lines[start_index:])

    range_match = re.fullmatch(r"(\d+)-(\d+)", selector)
    if range_match:
        start = int(range_match.group(1))
        end = int(range_match.group(2))
        if start < 1 or end > len(lines) or start > end:
            raise ValueError(
                f"{path}: line range {selector} is outside the file (1-{len(lines)})"
            )
        return "\n".join(lines[start - 1:end])

    # Named Python definition.
    named = re.fullmatch(r"(?:def|class)\s+([A-Za-z_][A-Za-z0-9_]*)", selector.strip())
    if named and path.suffix == ".py":
        target = named.group(1)
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if node.name == target:
                    start = node.lineno
                    # Include a preceding decorator if present.
                    if node.decorator_list:
                        start = min(d.lineno for d in node.decorator_list)
                    end = node.end_lineno or start
                    return "\n".join(lines[start - 1:end])
        raise ValueError(f"{path}: no definition named '{target}'")

    raise ValueError(f"{path}: unrecognised selector '{selector}'")
```

*Listing 49.1. Region extraction from `scripts/bookgen/facts.py`.*

The docstring records the incident that motivated it. A listing captioned "the
audit IAM grant" was selected by line number; an unrelated edit to the template
shifted the file, and the listing silently began showing SQS queue
configuration under a caption about IAM policy.

The failure mode is the worst kind: the output was well-formed, plausible and
wrong. Line-number includes now produce a build warning.

## 49.4 Facts are measured

```python
def collect_test_results(run_tests: bool = True) -> dict[str, str]:
    """Run the real suites and record what they actually report.

    If a suite is not run, the facts say so rather than carrying a stale number.
    """
    facts: dict[str, str] = {}
    backend = ROOT / "backend"
    python = ROOT / ".venv" / "Scripts" / "python.exe"
    if not python.exists():
        python = Path(sys.executable)

    if not run_tests:
        facts["test_backend"] = "NOT MEASURED IN THIS BUILD"
        facts["test_total"] = "NOT MEASURED IN THIS BUILD"
        facts["test_unit"] = "NOT MEASURED IN THIS BUILD"
        facts["test_integration"] = "NOT MEASURED IN THIS BUILD"
        facts["test_frontend"] = "NOT MEASURED IN THIS BUILD"
        facts["test_status"] = "NOT MEASURED IN THIS BUILD"
        return facts

    # Deliberately NOT using -q: in this pytest version quiet mode suppresses
    # the "N passed" summary line, and a missing summary previously produced a
    # recorded count of zero -- a false test result, which is exactly what the
    # specification forbids. Anything unparseable is now reported as such.
    # Vitest colours its summary, so "Tests  36 passed" arrives with ANSI escape
    # sequences between the words and a naive regex never matches.
    ansi = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

    def count(output: str, pattern: str = r"(\d+) passed") -> str:
        match = re.search(pattern, ansi.sub("", output))
        return match.group(1) if match else "COULD NOT MEASURE"

    code, output = _run([str(python), "-m", "pytest", "tests"], backend)
    failed = re.search(r"(\d+) failed", output)
    skipped = re.search(r"(\d+) skipped", output)
    # This measures `pytest tests` in backend/, so it is the BACKEND total.
    # It used to be called `test_total`, which sat beside `test_frontend`
    # and so read as "all tests" -- a reader could reasonably add 604 and
    # 245 and wonder which of the two was wrong. `test_total` is now the
    # genuine sum, computed below.
    facts["test_backend"] = count(output)
    facts["test_failed"] = failed.group(1) if failed else "0"
    facts["test_skipped"] = skipped.group(1) if skipped else "0"
    if facts["test_backend"] == "COULD NOT MEASURE":
        facts["test_status"] = "COULD NOT MEASURE - see the build log"
    elif code == 0:
        facts["test_status"] = "all passing"
    else:
        facts["test_status"] = "FAILURES PRESENT"

    _, out_u = _run([str(python), "-m", "pytest", "tests/unit"], backend)
    facts["test_unit"] = count(out_u)

    _, out_i = _run([str(python), "-m", "pytest", "tests/integration"], backend)
    facts["test_integration"] = count(out_i)

    npm = _find_npm()
    if npm is None:
        facts["test_frontend"] = "COULD NOT MEASURE - npm not found"
    else:
        _, out_f = _run([npm, "test"], ROOT / "frontend", env=_node_env())
        facts["test_frontend"] = count(out_f, r"Tests\s+(\d+) passed")

    # The genuine combined figure. Reported as unmeasurable rather than as a
    # partial sum if either side could not be counted: a total that silently
    # omitted the frontend is exactly the ambiguity this replaces.
    try:
        facts["test_total"] = str(int(facts["test_backend"]) + int(facts["test_frontend"]))
    except (ValueError, KeyError):
        facts["test_total"] = "COULD NOT MEASURE - see test_backend and test_frontend"

    return facts
```

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

```python
def render_layered(spec: DiagramSpec, width: float) -> Drawing:
    """Layered architecture diagram: labelled bands of boxes, top to bottom."""
    layer_count = max(1, len(spec.layers) or (max((n.layer for n in spec.nodes), default=0) + 1))
    by_layer: dict[int, list[Node]] = {}
    for node in spec.nodes:
        by_layer.setdefault(node.layer, []).append(node)

    box_height = 15 * mm
    layer_gap = 9 * mm
    label_width = 26 * mm
```

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