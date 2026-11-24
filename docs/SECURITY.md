# LifeLink — Security

## Summary

| Control | Mechanism | Verified |
|---|---|---|
| Authentication | Cognito, RS256 JWT, PKCE, per-token-type audience check | Yes, 23 tests on the production verifier |
| Authorization | One decorator, 39 permissions, 10 roles | Yes, 33 tests |
| Account status | Read from the database per request | Yes |
| Organization isolation | Central ownership comparison | Yes |
| Audit | Append-only, write-only IAM grant | Yes |
| Log redaction | Recursive, by key name | Implemented |
| Encryption at rest | SSE everywhere, CMK for audit | In template |
| Encryption in transit | TLS throughout | In template |
| Secrets | Secrets Manager; three categories avoided entirely | In template |

## Authentication

Amazon Cognito issues RS256-signed JWTs. The browser uses Authorization Code
with PKCE and holds no client secret.

Verification checks the signature against the key the `kid` names, the issuer,
the expiry, the presence of a subject, the `token_use` claim, and the audience.

<a name="the-audience-check"></a>
### The audience check

PyJWT's own `verify_aud` is **off**, and it has to be: a Cognito **access
token** carries no `aud` claim at all, so there is nothing for PyJWT to check.
Cognito records the app client in a different claim depending on token type:

| Token type | Claim carrying the app client |
|---|---|
| Access token | `client_id` |
| ID token | `aud` |

The verifier therefore audiences each token type against the claim it actually
carries, and **a missing claim fails** rather than skipping the check.

> **This was a real defect, found and fixed during the final polishing pass.**
> The check previously read
> `claims.get("client_id") not in (None, self.client_id)`. The `None` meant a
> token with no `client_id` claim was **accepted** — and an ID token never has
> one. So an ID token minted for a *different app client in the same user pool*
> passed every gate: genuine signature, genuine issuer, `token_use: "id"`
> allowed, audience never examined.
>
> **Severity: latent, not exploitable as deployed.** The stack creates exactly
> one app client, so nothing could mint such a token. Adding a second — a
> mobile client, a test client — would have opened it silently, which is the
> worst way for a security boundary to move.
>
> **Deployment state:** fixed in this repository, **not yet deployed**. The
> running API still has the weaker check. See
> [REPOSITORY_VS_DEPLOYED](REPOSITORY_VS_DEPLOYED.md) §3.2. Deploy before
> adding a second app client.
>
> The fix is proven rather than asserted: reverting it makes three tests fail,
> including `test_an_id_token_for_another_client_is_refused`.

`CognitoTokenVerifier` previously had **no tests at all** — the production
component deciding whether any request is authenticated was the one thing
unexercised, while the local development verifier was covered. It now has
**23**: signature, wrong user pool, wrong signing key, `alg: none`, an unsigned
token, expiry, each required claim, every `token_use` value, audience for both
token types, audience as a list, and JWKS client reuse.

When `COGNITO_CLIENT_ID` is unset the audience check is skipped. That is the
pre-existing documented contract, left unchanged deliberately so a working
environment is not suddenly refused, and it is covered by a test that names
why. Every deployed environment sets it from the template.

### The critical design decision

**The token proves identity. The database decides authority.**

Roles and account status are read from the stored user record on every request,
not taken from token claims. Consequences:

- A role revoked thirty seconds ago stops working on the next request, not at
  token expiry.
- A valid, unexpired, correctly signed token from a suspended account is
  rejected with `ACCOUNT_SUSPENDED`.

The second is the property a token-trusting system cannot have, and it is
pinned by `test_suspended_account_is_blocked_despite_valid_token_and_role`.

## Authorization

One decorator, five checks, in this order:

1. Token signature and standard claims.
2. Load the principal from the database.
3. **Reject if the account is not ACTIVE.**
4. Check the declared permission.
5. Compare the resource's owning organization with the caller's.

Step 3 precedes step 4 so a suspended administrator receives
`ACCOUNT_SUSPENDED` rather than a misleading `FORBIDDEN`.

### Permissions, not roles

Handlers declare a permission; they never enumerate roles. The matrix lives in
one file, so "who can verify a donation?" has a single answer.

Deliberate exclusions, each with a test:

| Role | Refused | Reason |
|---|---|---|
| `CAMP_ORGANIZER` | All inventory permissions | Specification 5.7 |
| `HOSPITAL_STAFF` | `emergency:certify:priority` | Certification is a clinical act |
| `BLOOD_BANK_STAFF` | `inventory:verify`, `inventory:correct` | Verification needs seniority |
| `DONOR` | `donation:verify` | A donor cannot verify their own donation |
| All but `PLATFORM_ADMIN` | `hospital:verify` | Only an administrator verifies institutions |

An unknown role grants nothing and does not dilute known roles.

## Organization isolation

Three layers:

**IAM.** Each background function can reach only its own domain's tables. The
notification worker has no grant for inventory at all.

**The decorator.** Organization-scoped permissions trigger an ownership
comparison before the handler runs. The handler declares *how* to find the
owner; the decorator does the comparison, so it cannot be forgotten.

**The service.** Where ownership is subtler than "same organization" — camp
staff scoped to a specific camp — the service checks explicitly.

### Error messages do not disclose

The cross-organization refusal says the resource belongs to another
organization without naming which. A test asserts the other organization's
identifier appears in neither the message nor the details.

## Audit

Every privileged operation writes an audit record carrying actor, role,
action, resource type and id, organization, correlation id, timestamp, and
before/after images where meaningful.

For stock changes the audit row is written **in the same transaction** as the
change, so a change with no audit entry is impossible rather than unlikely.

### Tamper resistance, not immutability

The Lambda execution role is granted `PutItem` and `Query` on the audit table —
no `UpdateItem`, no `DeleteItem`. The application physically cannot rewrite
history.

This is **resistance within the platform's means**, not immutability. An
account administrator with sufficient IAM privileges could still alter the
table. Genuine immutability would require S3 Object Lock in compliance mode,
QLDB, or hash-chaining. None is implemented, and the claim is not made.

The table uses a customer-managed KMS key so that decryption is itself logged
in CloudTrail.

## Data protection

| Control | Implementation |
|---|---|
| In transit | TLS via CloudFront and API Gateway |
| At rest | SSE on every table and bucket; CMK for audit |
| Secrets | Secrets Manager; no credentials in code or environment files |
| Buckets | All public access blocked; CloudFront via Origin Access Control |
| Confused deputy | `AWS:SourceArn` condition naming this distribution |
| Browser credentials | Identity pool role scoped to four read-only tile actions |

### Secrets that do not exist

| Not a secret | Why |
|---|---|
| Database credentials | DynamoDB uses IAM |
| Cognito client secret | Browser client uses PKCE |
| Map provider key | Scoped temporary credentials instead |

## Logging

Structured JSON with recursive redaction by key name at any depth. The
redacted set includes passwords, tokens, keys and session material, and also
email, phone, coordinates, address and date of birth — personal data that
accumulates in logs without anyone deciding it should.

API Gateway access logs deliberately exclude request bodies and query strings.

Unhandled exceptions return a generic 500 with a correlation id; the detail
goes to the log, never to the client.

## Input validation

Three layers: the frontend form for feedback, the handler for types and
presence, the domain and service layers for business rules. The first is never
trusted.

Timestamps without a timezone designator are rejected rather than assumed to
be UTC.

## Threat notes

| Threat | Mitigation | Residual risk |
|---|---|---|
| Stolen token | Short access token, immediate revocation via account status | Window until the next request |
| Insider with revoked access | Database-backed authorization | None at the request level |
| Cross-tenant data access | Central ownership comparison, IAM table separation | None found |
| IDOR | Ownership resolved by the decorator | None found |
| Account enumeration | `PreventUserExistenceErrors`; non-disclosing errors | Low |
| Log-based data leakage | Automatic redaction | Free-text fields rely on interface guidance |
| Audit tampering | Write-only IAM grant | An account administrator could still alter it |
| Demo data in production | Three independent seeder guards | None found |
| XSS | React escaping; no `dangerouslySetInnerHTML` | Standard React exposure |
| Local auth path enabled in a deployment | Requires a key file that does not exist in AWS | Low; an explicit refusal would be stronger |

## Compliance

No compliance claim is made. See
[PRIVACY_AND_DATA_HANDLING.md](PRIVACY_AND_DATA_HANDLING.md) — the privacy and
terms documents are placeholders requiring legal review, and the specification
forbids claiming compliance without a proper assessment.

## Security testing performed

33 authorization unit tests (`tests/unit/test_authorization.py`, measured by
`pytest --collect-only`) plus integration coverage of refusals. What has
**not** been done: a penetration test, a dependency CVE scan in CI, and a
review by a security professional.
