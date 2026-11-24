# LifeLink — API Documentation

The machine-readable specification is [openapi.json](openapi.json) and
[openapi.yaml](openapi.yaml), **generated from the live route table** by
`scripts/generate_openapi.py`. It cannot describe an endpoint that does not
exist, and `--check` fails if the committed file has drifted.

**43 paths, 50 operations.**

---

## Conventions

| Concern | Convention |
|---|---|
| Resource naming | Plural nouns: `/facilities`, `/camps`, `/alerts` |
| Sub-resources | Nested: `/facilities/{facilityId}/batches/{batchId}` |
| Non-CRUD actions | A verb segment: `/certify`, `/respond`, `/adjust` |
| Status codes | 200 read, 201 create, 204 delete, 4xx client, 5xx server |
| Pagination | Cursor in `meta.nextCursor` |
| Idempotency | `Idempotency-Key` header on mutating requests |
| Correlation | `X-Correlation-Id` accepted and echoed |

## Response envelopes

Success:

```json
{
  "data": { },
  "meta": { "count": 20, "nextCursor": "eyJrIjp..." },
  "correlationId": "corr-7f3a..."
}
```

Failure:

```json
{
  "error": {
    "code": "CONCURRENT_MODIFICATION",
    "message": "the record changed while this operation was in flight",
    "details": { "hint": "re-read the record and retry" }
  },
  "correlationId": "corr-7f3a..."
}
```

**Branch on `error.code`.** It is contract. The message is written for a human
and may be reworded.

## Error codes

| Code | Status | Meaning | Retry? |
|---|---|---|---|
| `VALIDATION_ERROR` | 400 | Input failed validation | No |
| `UNAUTHENTICATED` | 401 | Missing, malformed or invalid token | After signing in |
| `FORBIDDEN` | 403 | Authenticated, lacks the permission | No |
| `ACCOUNT_SUSPENDED` | 403 | Valid token, inactive account | No |
| `CROSS_ORGANIZATION_DENIED` | 403 | Resource belongs to another organization | No |
| `NOT_FOUND` | 404 | No such resource | No |
| `CONFLICT` | 409 | Generic state conflict | Sometimes |
| `CONCURRENT_MODIFICATION` | 409 | Lost a write race | **Yes** |
| `DUPLICATE` | 409 | Already exists | No |
| `INSUFFICIENT_STOCK` | 409 | Not enough units | No |
| `INVALID_STATE_TRANSITION` | 409 | Illegal lifecycle move | No |
| `CAPACITY_EXCEEDED` | 409 | Camp is full | No |
| `REQUEST_IN_PROGRESS` | 409 | An identical request is in flight | After a pause |
| `RATE_LIMITED` | 429 | Throttled | **Yes, with backoff** |
| `CHANNEL_UNAVAILABLE` | 503 | Notification channel not implemented | No |
| `PROVIDER_UNAVAILABLE` | 503 | External provider failed | **Yes** |
| `INTERNAL_ERROR` | 500 | Unhandled | **Yes** |

Errors often carry `details.rule` naming the specific rule that refused —
for example `SELF_VERIFICATION_FORBIDDEN`, `STALE_UPDATE_REJECTED`,
`PROVIDER_NOT_NOTIFIED`, `ATTENDANCE_REQUIRED`.

## Authentication

```
Authorization: Bearer <jwt>
```

A Cognito access token in AWS; a locally minted development token when
running locally. Roles and account status are read from the database on every
request, so a suspended account is rejected immediately regardless of token
validity.

## Endpoint catalogue

### Platform

| Method | Path | Permission |
|---|---|---|
| `GET` | `/health` | public |
| `GET` | `/reference` | public |
| `GET` | `/me` | `registration:manage:own` |

### Feature 2 — Discovery

| Method | Path | Permission |
|---|---|---|
| `GET` | `/facilities` | `facility:read` *(public)* |
| `GET` | `/facilities/{facilityId}` | `facility:read` *(public)* |
| `GET` | `/facilities/{facilityId}/availability` | `inventory:read:public` *(public)* |
| `GET` | `/facilities/{facilityId}/route` | `facility:read` *(public)* |
| `GET` | `/geocode` | `facility:read` *(public)* |

### Feature 1 — Inventory

| Method | Path | Permission |
|---|---|---|
| `GET` | `/facilities/{facilityId}/batches` | `inventory:read:detailed` |
| `POST` | `/facilities/{facilityId}/batches` | `inventory:write` |
| `GET` | `/facilities/{facilityId}/batches/{batchId}` | `inventory:read:detailed` |
| `POST` | `/facilities/{facilityId}/batches/{batchId}/adjust` | `inventory:write` |
| `POST` | `/facilities/{facilityId}/batches/{batchId}/verify` | `inventory:verify` |
| `GET` | `/facilities/{facilityId}/batches/{batchId}/audit` | `inventory:read:detailed` |
| `POST` | `/facilities/{facilityId}/inventory/ingest` | `inventory:ingest:api` |

### Feature 1 — Alerts

| Method | Path | Permission |
|---|---|---|
| `POST` | `/alerts` | `alert:create` |
| `GET` | `/alerts` | `alert:manage:own` |
| `GET` | `/alerts/{alertId}` | `alert:manage:own` |
| `DELETE` | `/alerts/{alertId}` | `alert:manage:own` |

### Feature 1 — Reservations

**This is the ordinary request workflow.** A user asking a blood bank for units
places a reservation; there is no separate blood-request entity. See
[ADR-0018](ARCHITECTURE_DECISIONS.md#adr-0018) for the decision and the
alternatives rejected. Emergency coordination is a different workflow with
different consequences — Feature 4 below.

| Method | Path | Permission |
|---|---|---|
| `POST` | `/facilities/{facilityId}/reservations` | `reservation:create` |
| `GET` | `/me/reservations` | `reservation:manage:own` |
| `DELETE` | `/facilities/{facilityId}/reservations/{reservationId}` | `reservation:manage:own` |
| `GET` | `/facilities/{facilityId}/reservations` | `reservation:manage` |
| `POST` | `/facilities/{facilityId}/reservations/{reservationId}/decision` | `reservation:manage` |
| `POST` | `/facilities/{facilityId}/reservations/{reservationId}/fulfil` | `reservation:manage` |

`reservation:create` and `reservation:manage:own` are the requester's side;
`reservation:manage` is facility staff deciding on someone else's request, and
is additionally organization-scoped — staff at another organization get `403`.

#### Three things that trip up a caller

**1. `bloodGroup` and `component` are required in the body of every mutating
call**, including `DELETE`. They are part of the reservation's sort key, so
omitting one produces `404 NOT_FOUND` ("no such reservation") rather than a
validation error — a confusing failure, which is why the frontend centralises
it in a single helper.

**2. `status` and `storedStatus` can differ.** `status` is the status a reader
should act on; `storedStatus` is the raw row. They diverge when a hold's expiry
has passed but the release sweep has not yet rewritten it. **Use `status`.**
Treating an expired hold as live would send someone to a facility for units
that have already been released.

**3. A refusal carries a machine-readable `rule`.** These are contract; the
message is for a human.

| `rule` | Meaning |
|---|---|
| `INVENTORY_NOT_REPORTED` | The facility has never reported this pool. Unknown is not zero, and units that were never reported cannot be held |
| `NO_UNRESERVED_STOCK` | Everything eligible is already held |
| `INSUFFICIENT_UNRESERVED_STOCK` | Fewer free than requested; `details.unreservedUnits` says how many. A partial hold is never granted silently |
| `ALREADY_HOLDING` | One active hold per person per facility, group and component |
| `UNITS_EXCEED_PER_REQUEST_LIMIT` | Maximum 10 units, so one caller cannot sterilise a facility's stock |
| `RESERVATION_RACE_LOST` | Someone else took the units between the read and the write. This is the race the transaction exists to lose safely |
| `RESERVATION_EXPIRED` | Cannot confirm a hold whose time has passed |
| `INVALID_STATE_TRANSITION` | Not a legal move from the current state |
| `CONCURRENT_MODIFICATION` | The row changed in flight; reload |

#### What a reservation is not

Every reservation response carries a `notice` saying so, and
`isClinicalApproval: false` is returned explicitly:

> A reservation holds units for a limited time. It is not clinical approval,
> not a cross-match, and not a guarantee of release. Compatibility and release
> remain decisions for qualified staff at the facility.

`CONFIRMED` means the facility accepted the request. It does not mean the units
are compatible with, or safe for, any patient.

### Feature 3 — Camps

| Method | Path | Permission |
|---|---|---|
| `GET` | `/camps` | `camp:read` *(public)* |
| `POST` | `/camps` | `camp:create` |
| `GET` | `/camps/mine` | `camp:manage` |
| `GET` | `/camps/{campId}` | `camp:read` *(public)* |
| `POST` | `/camps/{campId}/approve` | `camp:approve` |
| `POST` | `/camps/{campId}/cancel` | `camp:manage` |
| `POST` | `/camps/{campId}/staff` | `camp:staff:assign` |
| `POST` | `/camps/{campId}/register` | `registration:create` |
| `DELETE` | `/camps/{campId}/register` | `registration:manage:own` |
| `POST` | `/camps/{campId}/checkin` | `camp:checkin` |
| `POST` | `/camps/{campId}/donations` | `donation:record` |
| `POST` | `/camps/{campId}/donations/verify` | `donation:verify` |

### Feature 3 — Donor

| Method | Path | Permission |
|---|---|---|
| `GET` | `/me/registrations` | `registration:manage:own` |
| `GET` | `/me/donor-profile` | `registration:manage:own` |
| `GET` | `/me/donations` | `registration:manage:own` |
| `GET` | `/me/donations/{donationId}/certificate` | `registration:manage:own` |

### Feature 4 — Emergency

| Method | Path | Permission |
|---|---|---|
| `POST` | `/emergency-requests` | `emergency:create` |
| `GET` | `/emergency-requests` | `emergency:read:own` |
| `GET` | `/emergency-requests/provider-queue` | `emergency:respond` |
| `GET` | `/emergency-requests/{requestId}` | `emergency:read:own` |
| `POST` | `/emergency-requests/{requestId}/certify` | `emergency:certify:priority` |
| `POST` | `/emergency-requests/{requestId}/respond` | `emergency:respond` |
| `POST` | `/emergency-requests/{requestId}/confirm` | `emergency:certify:priority` |
| `POST` | `/emergency-requests/{requestId}/cancel` | `emergency:cancel` |

### Feature 6 — Account and administration

| Method | Path | Permission |
|---|---|---|
| `GET` | `/me/notification-preferences` | `alert:manage:own` |
| `PUT` | `/me/notification-preferences` | `alert:manage:own` |
| `GET` | `/me/notifications` | `alert:manage:own` |
| `GET` | `/admin/organizations/pending` | `org:read` |
| `POST` | `/admin/organizations/{organizationId}/status` | `hospital:verify` |
| `POST` | `/admin/users/{userId}/status` | `user:manage` |
| `GET` | `/admin/audit` | `audit:read` |

## Worked examples

### Search for blood

```
GET /facilities?lat=30.3398&lon=76.3869&radiusKm=30&bloodGroup=O-&component=PRBC&units=2
```

Each result carries `availability`, `eligibleUnits`, `freshness`,
`verificationStatus`, `straightLineKm`, `roadKm` (null unless routing
succeeded), `rankScore`, `rankComponents` and `rankExplanation`.

A facility that has reported nothing returns `"availability": "UNKNOWN"` with
`"eligibleUnits": null` — never zero.

### Adjust stock

```
POST /facilities/fac-patiala-1/batches/01JD.../adjust
Idempotency-Key: adjust-2026-11-15-001

{ "operation": "DEDUCT", "units": 2, "reason": "issued to ward 4" }
```

Operations: `ADD`, `DEDUCT`, `CORRECT`, `QUARANTINE`, `RELEASE_QUARANTINE`,
`WITHDRAW`, `EXPIRE`.

A concurrent write returns 409 `CONCURRENT_MODIFICATION`; re-read and retry.

### Certify priority

```
POST /emergency-requests/01JD.../certify

{ "priority": "CRITICAL", "justification": "active haemorrhage" }
```

Requires `emergency:certify:priority`. The hospital must be currently
verified — re-checked at this moment, not cached. Accepts `CRITICAL`,
`URGENT`, `SCHEDULED` or the internal codes `P1`, `P2`, `P3`.

### Respond as a provider

```
POST /emergency-requests/01JD.../respond

{ "responseType": "ACCEPTED", "unitsOffered": 4 }
```

Stock is revalidated before an acceptance is recorded. The response records an
**offer**, not a reservation; nothing is decremented.

## Regenerating

```bash
python scripts/generate_openapi.py          # write both files
python scripts/generate_openapi.py --check  # fail if stale
```
