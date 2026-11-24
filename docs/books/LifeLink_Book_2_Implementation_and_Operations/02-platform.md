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
