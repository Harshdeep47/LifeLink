# LifeLink — Troubleshooting

Symptoms first. Each entry gives the cause, the check that confirms it, and the
fix.

---

## Local setup

### `ModuleNotFoundError: No module named 'src'`

The backend is run from the wrong directory, or the virtual environment is not
active.

```bash
cd backend
.venv/Scripts/activate          # Windows
python -m pytest
```

`pytest.ini` sets `pythonpath = .`, so pytest works from `backend/`. A plain
`python script.py` from elsewhere will not.

### `AttributeError: module 'platform' has no attribute 'system'`

Something has shadowed the standard library. This is the exact failure the
platform package was renamed to avoid: `backend/src/appcore/` was originally
`backend/src/platform/`, and botocore imports stdlib `platform` at import time.

Confirm:

```bash
cd backend
python -c "import platform; print(platform.__file__)"
```

It must print a path under your Python installation, not under `src/`. If a
`src/platform/` directory has reappeared, that is the cause.

### `ImportError: cannot import name 'ServerMode' from 'moto'`

`moto` is installed without the server extra, or Flask is missing.

```bash
pip install "moto[server]" flask flask-cors
```

### Port already in use (8000, 8080 or 5173)

```bash
netstat -ano | findstr :8000
taskkill /PID <pid> /F
```

`python scripts/dev.py status` reports which of the three ports are in use.

### `npm` is not recognised

Node is installed but not on this shell's PATH. Open a new terminal after
installing, or invoke it by full path. The book build script handles this
itself via `_find_npm()` and `_node_env()` precisely because the PATH is not
reliably inherited by subprocesses on this machine.

---

## Database

### `Could not connect to the endpoint URL: "http://localhost:8000"`

The local DynamoDB-compatible endpoint (moto in server mode) is not running.

```bash
python scripts/dev.py db-start
python scripts/dev.py status
```

### `ResourceNotFoundException: Requested resource not found`

The tables do not exist. moto in server mode keeps state in memory only, so a
restart empties it.

```bash
python scripts/dev.py create-tables
python scripts/seed_demo.py
```

This is the single most common local confusion: restarting the database loses
every table and every row, and the API then returns 500s that look like code
failures.

### `ValidationException: ... expression attribute value ... is not defined`

An expression attribute value was supplied but not referenced, or referenced
but not supplied. Four occurrences of the first kind were found and fixed
during development; a regex detector over the repositories exists to catch new
ones.

Check that every placeholder in the expression appears in
`ExpressionAttributeValues` **and** vice versa.

### A null value silently fails to persist

If an update that sets a field to null is rejected, the serialiser used was
`to_dynamo()` (which strips `None`) rather than `to_expression_values()`
(which preserves it). Repository update paths must use the latter. See
[repositories/dynamo.py](../backend/src/repositories/dynamo.py).

### `ProvisionedThroughputExceededException` locally

moto does not throttle; this indicates the client is pointed at real AWS.
Check `DYNAMODB_ENDPOINT` is set.

---

## API

### 401 on every request

| Cause | Check |
|---|---|
| No `Authorization` header | Inspect the request in the browser network tab |
| Token expired | Local tokens last 12 hours; mint a new one |
| Wrong signing secret | `LOCAL_JWT_SECRET` must match between minting and serving |

```bash
python scripts/dev.py token user-donor-1
```

### 403 `FORBIDDEN` where you expected success

The account lacks the permission the route declares. The route table in
[handlers/api.py](../backend/src/handlers/api.py) names the required
permission for all 50 routes; the role-to-permission map is in
[appcore/rbac.py](../backend/src/appcore/rbac.py).

The common case is a hospital staff account attempting certification:
`emergency:certify:priority` belongs to the authorizing clinician role only,
and this separation is deliberate.

### 403 `ACCOUNT_SUSPENDED` with a valid token

Working as designed. Account status is read from the database on every
request, so suspension takes effect immediately and no token revocation is
involved. `user-suspended-1` in the demo dataset exists to demonstrate this.

### 403 `CROSS_ORGANIZATION_DENIED`

The resource belongs to another organization. Check the `facilityId` or
`campId` in the path against the caller's `organizationId`.

### 409 `CONCURRENT_MODIFICATION`

Two writers raced on the same record and this one lost the version condition.
**This is retryable**: re-read the record and reapply the change. The service
layer already retries a bounded number of times; a 409 reaching the client
means the retries were exhausted, which under normal load means something is
writing in a tight loop.

### 409 `INSUFFICIENT_STOCK` when the screen showed enough

The screen was stale, or another operation consumed the units in between. The
conditional write is the authority, not the read that preceded it. Re-read and
retry.

### 409 `CAPACITY_EXCEEDED` on camp registration

The camp filled. The capacity check is part of the registration transaction,
so this cannot be bypassed by retrying; the only resolution is a different
camp or an increased capacity.

### 503 `CHANNEL_UNAVAILABLE`

An SMS notification was requested. **SMS is not implemented** — the account's
service control policy denies the required actions. The system fails closed
with this code rather than pretending to send. See
[KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md).

### A search returns fewer facilities than expected

Check in this order:

1. Is the radius large enough? Distances between the seeded cities are real —
   Rajpura is 25.6 km from Patiala, so it appears at 30 km and not at 10 km.
2. Are matching batches eligible? Expired, quarantined and zero-unit batches
   are excluded by the index itself.
3. Is a verification filter applied? Two seeded facilities are unverified.
4. Is the facility reporting at all? `fac-chd-2` has never submitted
   inventory and returns `UNKNOWN`, which is **not** the same as being absent
   from results.

A facility that is genuinely missing from a radius it falls inside would be a
recurrence of the geohash coverage defect; `test_geo_coverage.py` asserts
coverage at ten radii specifically to prevent that.

### `availability: "UNKNOWN"` with `eligibleUnits: null`

Working as designed, and the single most important display rule in the system.
The facility has never reported. Unknown is not zero.

---

## Frontend

### Blank page, console shows `Failed to fetch`

The API is not running, or `VITE_API_BASE_URL` points elsewhere.

```bash
python scripts/local_server.py --port 8080
curl http://localhost:8080/health
```

### CORS error in the browser console

`CORS_ALLOWED_ORIGINS` on the API must include the Vite origin
(`http://localhost:5173`). The local server reads it at startup, so it must be
restarted after a change.

### Map renders grey tiles

Map tiles need credentials from the Cognito identity pool, which is not
available locally. The expected local behaviour is the list view with the map
panel showing its unavailable state — not a crash. If the panel crashes, that
is a defect.

### `Cannot update a component while rendering a different component`

A `setState` during render. One occurrence was fixed in
[FindBloodPage.jsx](../frontend/src/features/discovery/FindBloodPage.jsx) by moving the call
into `useEffect`. If it recurs, the stack trace names the component.

### A request fires twice in development

React 18 StrictMode double-invokes effects in development. The `AbortController`
in `useApiData` cancels the first; this is expected and does not occur in a
production build.

---

## Tests

### Tests pass individually but fail together

Shared state between tests. The domain layer has none by construction — it is
pure functions — so this points at an integration test that did not reset its
moto tables. Each integration test module creates its own tables in setup.

### A test that depends on the current time fails on a different day

It should not be possible: no domain function reads the clock. Every one takes
`now` as a parameter, and `clock.py` rejects naive datetimes outright. A
date-dependent failure means a test or a caller is passing the real current
time where it should pass a fixed instant.

### `pytest -q` reports zero tests collected in the book build

Known: `-q` suppresses the summary line this pytest version emits, which broke
the metric extraction. The build no longer passes `-q`, and anything it cannot
parse is recorded as `COULD NOT MEASURE` rather than as a number. If you see
`COULD NOT MEASURE` in a book, that is the honest fallback working, not a
silent zero.

---

## Documentation build

### `python scripts/build_books.py` fails a validation check

Eight checks run per book. The failures and their meanings:

| Failure | Meaning |
|---|---|
| Blank page detected | A chapter heading emitted a page break and the source also contained an explicit page-break comment |
| Listing caption count mismatch | A code listing was captioned but its content was dropped |
| Unresolved directive | An include or fact directive did not resolve |
| Page count below minimum | The book is shorter than the specification requires |
| Figure count below minimum | Diagrams are missing |
| TOC page drift | The two-pass TOC did not converge |
| Missing anchor | An anchor selector no longer matches the source |
| Orphaned heading | A heading rendered with no body on its page |

### `Unresolved directive` pointing at JSX

A false positive the detector used to produce on a JSX object literal inside an
expression. The regex has been narrowed. If it recurs, the pattern in
[bookgen/facts.py](../scripts/bookgen/facts.py) needs tightening again rather
than the source needing to change.

### A listing shows the wrong code

A line-number include drifted after the source file changed. Replace it with an
anchor selector, which matches on content. The build emits a warning for every
remaining line-number include for exactly this reason.

### `generate_openapi.py --check` fails

The committed OpenAPI files no longer match the route table. Regenerate:

```bash
python scripts/generate_openapi.py
```

This is a build gate, not a bug: it means a route changed and the spec was not
regenerated.

---

## AWS

Nothing has been deployed, so none of the following has been observed. These
are the failures the implementation anticipates.

### Sudden `AccessDenied` on operations that previously worked

On this account type, check the spend limit first. A project that exceeds its
limit is paused, and the symptom is access denial rather than a billing
message. Only the project owner can change it, in AWS Settings > Billing.

### `ResourceNotFoundException` for a Lambda in another region

Every regional resource must be in `ap-southeast-2`. The account's service
control policy forbids others. CloudFront is the single exception and is
administered through `us-east-1`.

### Lambda throttling at low traffic

Expected: the concurrent-execution ceiling on this account is **10**, not the
default 1000. Confirm with `aws lambda get-account-settings`. The architecture
is designed for this — no reserved concurrency anywhere, queue consumers capped
at `MaximumConcurrency: 2`, and the API throttled at 10 rps — but a burst can
still hit it.

### SES rejects a recipient

Sandbox mode: only verified addresses can receive. Verify the address, or
request production access.

### `cfn-lint` passes but `sam validate --lint` fails

They check different things. Both are build gates and both must pass.

---

## When nothing here matches

1. Get the correlation id. Every API response carries one, and every log line
   produced by that request — including background work in queues — carries
   the same value.
2. Query by it. One id gives the whole causal chain.
3. Check [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md) before filing a defect;
   the behaviour may be a documented limitation.
4. Check [EDGE_CASE_REGISTER.md](EDGE_CASE_REGISTER.md), which lists 116 cases
   and whether each is tested, implemented or unhandled.
