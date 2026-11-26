# Backend Code Walkthrough

Python 3.14 on arm64 Lambda. 657 tests, all passing. Four layers plus a pure
domain core.

---

## 1. The layering, and why it exists

ADR-0010: **handlers -> services -> repositories -> adapters**, with `domain`
depending on nothing.

```
handlers/     HTTP in, HTTP out.  Knows about the Lambda event.
   |
services/     One function per use case.  Orchestrates.
   |     \
domain/      repositories/     Rules (no AWS)   |   DynamoDB
                   |
             adapters/          Outside world: Location, notifications
```

| Layer | May import | May **not** import |
|---|---|---|
| `handlers` | services, appcore | repositories directly |
| `services` | domain, repositories, adapters | the Lambda event shape |
| `domain` | **nothing but the standard library** | boto3, repositories, anything AWS |
| `repositories` | boto3, domain types | services |

**The one rule to remember: `domain/` has no AWS imports.** That single
constraint is why 566 of 657 tests are fast unit tests. If a teacher asks
"how do you test this without AWS?", the answer is that the rules were
deliberately put somewhere that does not need AWS.

---

## 2. `handlers/api.py` — the entry point

```python
def lambda_handler(event, context):
    router = build_router()
    return router.dispatch(event, authenticator=...)
```

`build_router()` registers all 58 routes, each with its method, path, handler,
permission and `allow_anonymous` flag. Everything else in the file is one
handler function per route.

A representative handler:

```python
@requires(Permission.RESERVATION_CREATE)
def request_reservation(event, ctx):
    facility_id = event["pathParameters"]["facilityId"]
    body = parse_json_body(event)
    result = services.reservations.request(
        facility_id=facility_id, principal=ctx.principal, **validated(body)
    )
    return created(result, ctx)
```

Four lines of real work. The handler parses and validates input, delegates, and
shapes the response. **No business rule lives in a handler** — that is the
layering being honest rather than aspirational.

---

## 3. `handlers/router.py` — the route table

```python
@dataclass(frozen=True)
class Route:
    method: str
    path: str
    handler: Handler
    permission: Permission | None
    allow_anonymous: bool
    summary: str
    pattern: re.Pattern
```

Three things it does that are worth explaining:

### Path compilation

```python
regex = re.sub(r"\{([a-zA-Z0-9_]+)\}", r"(?P<\1>[^/]+)", path)
```

`/facilities/{facilityId}` becomes `^/facilities/(?P<facilityId>[^/]+)$`.
`[^/]+` means a path parameter cannot contain a slash, so
`/facilities/a/b` does not match `/facilities/{id}`.

### 405 versus 404

```python
def match(self, method, path):
    path_exists = False
    for route in self._routes:
        match = route.pattern.match(path)
        if match:
            if route.method == method.upper():
                return route, match.groupdict(), True
            path_exists = True
    return None, {}, path_exists
```

It remembers that the *path* matched even when the *method* did not, so the API
can answer **405 Method Not Allowed** rather than a misleading 404.

### Stage prefix stripping

Covered in
[../02_SYSTEM_ARCHITECTURE/02_End_To_End_Data_Flow.md](../02_SYSTEM_ARCHITECTURE/02_End_To_End_Data_Flow.md).
The short version: API Gateway reports `/dev/health`, the route table says
`/health`, and `strip_stage_prefix` reconciles them by reading the stage from
the event rather than from a constant. It was written after every route
404'd on the first deployment while working perfectly locally.

**Why no web framework?** The specification discourages unnecessary frameworks
and names FastAPI and Mangum specifically. A route table plus path matching is
all a proxy integration needs, and the same table drives the local development
server — so the two cannot diverge. A framework would add a dependency, cold
start weight, and a second routing concept.

---

## 4. `appcore/auth.py` — authentication and authorization

### `CognitoTokenVerifier`

Verifies RS256 tokens using `PyJWKClient` against the pool's JWKS endpoint
(the keys are cached, so there is not a network call per request). It checks
signature, issuer, expiry, `token_use`, and the audience **per token type**:

```python
presented = claims.get("client_id") if token_use == "access" else claims.get("aud")
allowed = presented if isinstance(presented, (list, tuple)) else [presented]
if self.client_id not in allowed:
    raise UnauthenticatedError("token was not issued for this client")
```

23 tests in `backend/tests/unit/test_cognito_token_verifier.py` cover it, and
reverting the fix fails 3 of them. See
[../08_SECURITY_AND_RELIABILITY/03_JWT_And_Token_Verification.md](../08_SECURITY_AND_RELIABILITY/03_JWT_And_Token_Verification.md).

### `@requires(...)` — the only place authorization happens

The module docstring states the order and why:

```
1. Token signature and standard claims.
2. Load the user from the database -- roles come from stored state, not
   claims, so a revoked role takes effect on the next request.
3. Account status: a valid JWT from a suspended account is rejected here.
4. Permission check.
5. Organization scoping -- the IDOR defence, applied centrally.
```

**Each step rejects with a distinct error**, so the API never leaks why
something failed beyond what the caller is entitled to know:

| Step | Error |
|---|---|
| 1, 2 | `401 UNAUTHENTICATED` |
| 3 | `403 ACCOUNT_SUSPENDED` |
| 4 | `403 FORBIDDEN` |
| 5 | `403` cross-organization |

---

## 5. `appcore/rbac.py` — 39 permissions, 10 roles

```python
class Permission(StrEnum):
    INVENTORY_READ_PUBLIC = "inventory:read:public"
    INVENTORY_READ_DETAILED = "inventory:read:detailed"
    INVENTORY_WRITE = "inventory:write"
    INVENTORY_VERIFY = "inventory:verify"
    ...
    SYSTEM_ADMIN = "system:admin"
```

Plus `ROLE_PERMISSIONS` mapping each of the 10 roles to its set,
`GLOBAL_PERMISSIONS`, and `is_organization_scoped(permission)` — which tells
the decorator whether step 5 applies.

| Role | Count |
|---|---|
| `PUBLIC` | 4 |
| `DONOR` | 13 |
| `BLOOD_BANK_STAFF` | 9 |
| `BLOOD_BANK_ADMIN` | 13 |
| `HOSPITAL_STAFF` | 8 |
| `HOSPITAL_AUTHORIZER` | 9 |
| `HOSPITAL_ADMIN` | 10 |
| `CAMP_STAFF` | 6 |
| `CAMP_ORGANIZER` | 9 |
| `PLATFORM_ADMIN` | 39 |

**The naming convention carries meaning.** A `:own` suffix means the record
must belong to the caller; the bare form means authority over an
organization's records. `inventory:write` and `inventory:verify` are separate
because updating and independently verifying are different acts of trust.

---

## 6. `domain/` — the rules, readable in isolation

### `freshness.py`

```python
FRESH_MAX_HOURS = 6.0
AGING_MAX_HOURS = 24.0
STALE_MAX_HOURS = 48.0
VERIFICATION_VALIDITY_HOURS = 72.0

def freshness_label(last_updated_at, now):
    age = hours_between(last_updated_at, now)
    if age <= FRESH_MAX_HOURS: return FreshnessLabel.FRESH
    if age <= AGING_MAX_HOURS: return FreshnessLabel.AGING
    if age <= STALE_MAX_HOURS: return FreshnessLabel.STALE
    return FreshnessLabel.OUTDATED
```

`verification_status()` is a **separate function with a separate threshold**,
because updated is not verified.

Note `now` is a parameter, not `datetime.now()`. That is `domain/clock.py`'s
discipline: time is injected, so a test can place a record exactly on the
6-hour boundary.

### `geo.py`

```python
EARTH_RADIUS_KM = 6371.0088
MAX_SEARCH_RADIUS_KM = 100.0

def haversine_km(a, b):
    ...
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))
```

Also `encode_geohash`, `decode_geohash`, `geohash_center`, `neighbours`,
`choose_precision(radius_km)`, `search_cells(lat, lon, radius_km)`,
`_cell_intersects_circle`, `within_radius`.

`search_cells` raises if the radius exceeds 100 km, so an unbounded query
cannot scan the table. See
[../07_MAPS_AND_INTEGRATIONS/03_Distance_And_Haversine.md](../07_MAPS_AND_INTEGRATIONS/03_Distance_And_Haversine.md).

### `errors.py`

`LifeLinkError` and subclasses, each carrying a **stable code** that reaches
the browser: `UnauthenticatedError`, `ForbiddenError`,
`AccountSuspendedError`, `CrossOrganizationError`, and the domain ones like
`NO_UNRESERVED_STOCK` and `CONCURRENT_MODIFICATION`. The router translates any
`LifeLinkError` into the right HTTP status in one place.

---

## 7. `repositories/` — DynamoDB

### `schema.py`

Defines every table and GSI in Python (193 lines), with `create_table_kwargs`
used by the local development server and the integration tests to create tables
that match production.

**Why duplicate the template?** Because integration tests need to create real
table shapes against moto, and a hand-written approximation would drift. This
module and `infrastructure/template.yaml` are two consumers of the same intent
— and the integration tests are what catch a mismatch.

### `reservation_repo.py` — the transactional write

The reservation row and the pool counter move together:

```python
client.transact_write_items(TransactItems=[
    {"Put": {... reservation row ..., "ConditionExpression": "attribute_not_exists(PK)"}},
    {"Update": {... pool heldUnits += units ...,
                "ConditionExpression": "heldUnits + :units <= availableUnits"}},
])
```

If the condition fails, **neither** write happens and the caller receives
`NO_UNRESERVED_STOCK`.

### `emergency_repo.py` — append-only history

```python
"SK": f"EVENT#{to_iso(now)}#{event_id}"   # event_id = uuid4()[:8]
```

**This is deliberately append-only and was deliberately left unchanged.** Real
history must accumulate. The seeder uses a *different*, deterministic key
(`EVENT#0000#seed0001`) so that re-seeding overwrites instead of duplicating —
see [../05_DATABASE_AND_DATA/04_Database_Seeding_Workflow.md](../05_DATABASE_AND_DATA/04_Database_Seeding_Workflow.md).

### `inventory_repo.py` — optimistic concurrency

Batch rows carry a `version`, and updates are conditioned on it. A concurrent
modification fails with `CONCURRENT_MODIFICATION` rather than silently
overwriting — and `ApiError.isRetryable` is true for that code, so the UI can
offer a retry.

---

## 8. `services/` — orchestration

`container.py` wires services to repositories, so a test can substitute a fake
repository without patching imports.

### `reservation_service.py` — and the defect it taught

The condition deciding whether a transition **releases** held units:

```python
releases = (
    reservation.status in HOLDING_STATES
    and updated.status not in HOLDING_STATES
)
```

**The original asked only the first half** — "was this holding units?" — which
is true when confirming a `PENDING` hold. So confirming a reservation released
its own hold: the units became available again while the reservation still
claimed them. That permits overselling and leaves the confirmed hold
impossible to cancel or fulfil.

Six regression tests were added; **four failed against the old code.** All
three transition paths were then verified live with counters read directly from
DynamoDB.

**The honest conclusion to state in a viva:** 900+ passing tests did not catch
this. It appeared only when the deployed system was exercised. Two of the four
live defects found in this project were invisible to the test suite.

---

## 9. `handlers/workers.py` — the five background entry points

| Handler | Trigger | Job |
|---|---|---|
| `dispatcher_handler` | Scheduler, 1 min | Rank candidate providers for open emergency requests, record dispatch events |
| `maintenance_handler` | Scheduler, 10 min | Expire reservations and alerts, roll up freshness, recompute derived state |
| `outbox_handler` | DynamoDB Stream on `outbox` | Fan events out to SQS |
| `work_handler` | SQS `work` | Alert matching and deferred work |
| `notification_handler` | SQS `notifications` | Compose and record notifications |

**Workers are idempotent**, because stream and queue delivery is at-least-once.
The `idempotency` table with a conditional put is the mechanism (ADR-0009).

> **Evidence worth knowing:** `lifelink-dev-notification-worker` has **no
> CloudWatch log group**, which means it has never been invoked. Notifications
> are written directly to the `notifications` table; email is unconfigured
> (`SES_SENDER` is empty) and SMS is not implemented. Do not claim the
> notification pipeline has run end to end.

---

## 10. Running and testing

```bash
python -m pytest backend/tests -q                   # 657 passed
python -m pytest backend/tests/unit -q              # 566
python -m pytest backend/tests/integration -q       # 91  (moto, not real AWS)
ruff check .                                        # clean
python scripts/local_server.py                      # same router, local HTTP
python scripts/security_audit.py                    # secret scan + security gate
python scripts/generate_openapi.py --check          # fails on route-table drift
```

---

## 11. Spoken answers

### 20–30 seconds

> "The backend is Python 3.14 on arm64 Lambda, in four layers. Handlers deal
> with HTTP, services orchestrate a use case, repositories talk to DynamoDB,
> and there's a domain layer with the actual rules that imports nothing from
> AWS at all. That last part is why 566 of our 657 tests are plain unit tests.
> Authorization happens in exactly one decorator with five checks in a fixed
> order, and a test enumerates the route table to prove no endpoint is missing
> it."

### 1–2 minutes

> "The design principle is that the rules should be readable on their own. If
> you open `domain/freshness.py` you see four constants and a function —
> that's the entire freshness model, six hours, twenty-four, forty-eight, and a
> separate seventy-two-hour window for verification. No database code, no AWS,
> nothing to mock.
>
> Above that, services orchestrate. The reservation service is where I'd point
> for a real lesson: the condition deciding whether a state change releases
> held units originally asked 'was this reservation holding units' instead of
> 'does it stop holding units'. Both are true when you confirm a pending hold,
> so confirming a reservation released its own units — which allows
> overselling. It passed every test we had. We only found it by exercising the
> deployed system, then wrote six regression tests, four of which fail against
> the old code.
>
> And we deliberately didn't use a web framework. A route table plus path
> matching is all an API Gateway proxy integration needs, and the same table
> drives our local server — so local and deployed behaviour can't drift."

---

## 12. Follow-up questions

**"Why Python 3.14 and not something more conservative?"**
> ADR-0013: our local interpreter is 3.14, Lambda supports `python3.14` as GA
> on Amazon Linux 2023 with deprecation in 2029, and matching local to deployed
> removes a whole class of "works on my machine" problem. We avoided 3.15
> because it is public preview and outside the Lambda SLA.

**"Why arm64?"**
> Graviton is cheaper for identical capability. The catch is that the
> deployment package must contain arm64 Linux wheels — which is exactly why we
> cannot use `sam build` on a Windows machine: it would install a Windows
> binary of `cryptography`, and RS256 token verification would fail to load on
> the function.

**"How do you handle a DynamoDB throttle?"**
> On-demand capacity scales automatically, so throttles are rare. When one
> happens, boto3 retries with backoff, and a persistent failure surfaces as an
> error with a correlation id. There is an alarm,
> `lifelink-dev-inventory-throttles`, at more than 5 in 5 minutes.

**"Is 1123 lines in one file not too much?"**
> It is at the upper end of comfortable. It stays navigable because it is 58
> short handlers in feature order with no business logic in them — the longest
> is about fifteen lines. If it grew further, the natural split is one module
> per feature area, with `build_router()` composing them.

---

## 13. Cross-references

- [01_Complete_File_Structure.md](01_Complete_File_Structure.md)
- [04_API_And_Handler_Mapping.md](04_API_And_Handler_Mapping.md)
- [05_Database_Code_Locations.md](05_Database_Code_Locations.md)
- [../08_SECURITY_AND_RELIABILITY/02_IAM_Authorization_Flow.md](../08_SECURITY_AND_RELIABILITY/02_IAM_Authorization_Flow.md)
- [../05_DATABASE_AND_DATA/06_Concurrency_And_Data_Integrity.md](../05_DATABASE_AND_DATA/06_Concurrency_And_Data_Integrity.md)
