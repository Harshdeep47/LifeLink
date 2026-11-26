# LifeLink — Privacy and Data Handling

> **This is an engineering document, not a legal one.** It describes what the
> implementation actually does with personal data. It is **not** a privacy
> policy, it is **not** a compliance assessment, and it does **not** claim
> conformance with any statute or standard. The user-facing privacy notice and
> terms of service are **placeholders requiring legal review** before any real
> user data is accepted.

---

## 1. What is collected, and why

| Data | Where stored | Why the system needs it | Who can read it |
|---|---|---|---|
| Email address | `users` table | Account identity; notification delivery | The user; platform administrators |
| Display name | `users` table | Attribution on audit entries, camp staff lists | The user; their organization's staff |
| Blood group (self-declared) | `users` table (donor profile) | Camp eligibility prompts; availability alerts | The user; camp staff at a camp they attend |
| Last donation date | `users` table (donor profile) | Donation-interval eligibility | The user; camp staff at check-in |
| Notification preferences | `users` table | Channel and opt-out handling | The user |
| Alert criteria (group, component, location, radius) | `alerts` table | Matching new stock to a standing request | The user |
| Registration records | `registrations` table | Camp capacity, check-in, attendance | The user; staff of that camp |
| Donation records | `donations` table | Impact ledger, certificates | The user; staff of the recording facility |
| Organization membership and role | `users` table | Authorization | The user; their organization's administrators |
| Request coordinates | `emergency_requests` table | Proximity matching | The requesting organization; notified providers |
| Audit entries | `audit` table | Accountability for privileged actions | Platform administrators only |

**What is not collected:** no phone numbers are collected in the implemented
build (the SMS channel is not implemented — see
[KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md)); no date of birth; no address;
no national identifier; no medical history beyond self-declared blood group
and last donation date; no payment data; no biometrics; no browsing or
analytics telemetry of any kind.

**The redaction list in [logging.py](../backend/src/appcore/logging.py) covers
more fields than the schema uses.** That is deliberate: the redactor is written
against the fields a future version might add, so adding a field cannot
silently start logging it.

## 2. What is not stored that could have been

Three deliberate omissions, each of which made a feature harder to build:

**No donor location history.** A donor's standing alert stores the point and
radius they chose, not a trail of where they have been. The alert matcher
therefore cannot rank by "closest right now"; it matches against the stored
point. This was the right trade: a location trail is the single most sensitive
thing this system could have accumulated, and the feature works without it.

**No clinical data.** The system records a self-declared blood group and never
treats it as verified. It holds no diagnosis, no transfusion history and no
cross-match result. This is why the compatibility reference is marked
unreviewed and why the system refuses to describe its output as a clinical
decision — it does not hold the data a clinical decision needs.

**No raw request bodies in logs.** Structured logs carry field names and
outcomes, never the body. A log line records that a donor profile was updated
and which correlation id did it, not what the values were.

## 3. Redaction

Every log line passes through `redact()` before it is emitted. The function
recurses through nested dicts and lists and replaces the value of any key in
`SENSITIVE_KEYS` with `"[redacted]"`.

The redacted key set includes `email`, `emailAddress`, `phone`,
`phoneNumber`, `latitude`, `longitude`, `lat`, `lon`, `address`, `dob`,
`dateOfBirth`, `password`, `token`, `accessToken`, `refreshToken`,
`authorization`, `secret` and `apiKey`.

Two consequences worth stating plainly:

- **Coordinates are redacted, which makes some debugging harder.** A geo
  search bug cannot be diagnosed from production logs alone, because the
  coordinates are not there. That is the intended trade; the search is instead
  covered by 34 unit tests that assert coverage at ten radii.
- **Redaction is applied at emission, not at construction.** Code that builds a
  log payload may hold the real value in memory; only what reaches CloudWatch
  is redacted. There is no attempt to prevent a developer from deliberately
  logging a sensitive value under a non-sensitive key name, and no test could
  catch that in general. The mitigation is review, not code.

## 4. Authorization as a privacy control

Privacy in this system is mostly an authorization property. The relevant
mechanisms:

**Organization scoping.** Every resource that belongs to an organization is
checked against the caller's organization by the `resource_owner` resolver on
the authorization decorator. A blood bank administrator at one facility cannot
read another facility's batches, audit trail or registrations — not because the
interface hides the link, but because the request is refused with
`CROSS_ORGANIZATION_DENIED`.

**Own-resource permissions.** Permissions ending in `:own`
(`registration:manage:own`, `alert:manage:own`, `emergency:read:own`) resolve
to the caller's own subject identifier. A donor can read their own
registrations and nobody else's.

**Two read tiers for inventory.** `inventory:read:public` returns an
availability summary — a band, a count, freshness and verification state.
`inventory:read:detailed` returns batch-level records including identifiers and
audit history. The public search path holds only the first.

**Status read from the database.** A suspended account is refused on its next
request regardless of a valid token, because the authorization path reads
account status from stored state rather than trusting token claims. This is
what makes a privacy incident actionable: suspending the account stops access
immediately.

## 5. Retention

| Data | Implemented behaviour |
|---|---|
| Notifications | DynamoDB TTL, 90 days |
| Idempotency claims | DynamoDB TTL, 24 hours |
| Outbox rows | DynamoDB TTL, 7 days after dispatch |
| Availability alerts | TTL at the user's chosen expiry, maximum 30 days |
| CloudWatch logs | 30-day retention on every log group in the template |
| Users, donations, audit | **No expiry implemented** |

**The last row is an unresolved question, not a decision.** Donation records
and audit entries are retained indefinitely by the current implementation
because deleting them would break the impact ledger and the accountability
trail respectively. Whether that is the right retention period is a legal
question this project has not answered. It is recorded in
[KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md) as an open item.

## 6. Deletion

**Account deletion is not implemented.** There is no endpoint that deletes a
user. An administrator can set an account to `SUSPENDED`, which stops all
access, but the record remains.

This is a genuine gap, and the reason it is a gap rather than an oversight is
worth stating: a correct deletion would have to decide what happens to
donation records that a facility's own ledger depends on, to audit entries
naming the user as actor, and to camp attendance records that another
organization relies on. Those are policy questions. Implementing deletion
before answering them would have produced either a deletion that silently
leaves data behind or one that corrupts another organization's records.

What exists instead:

- Suspension, which is immediate and complete as an access control.
- A documented data map (§1) so that a manual deletion could be performed
  correctly if required.

## 7. Encryption and transport

| Layer | What the template configures |
|---|---|
| In transit, browser to API | TLS, API Gateway default domain |
| In transit, browser to assets | TLS, CloudFront, `redirect-to-https` |
| In transit, service to service | TLS, AWS SDK default |
| At rest, DynamoDB | Encryption enabled (AWS-owned keys) |
| At rest, S3 | SSE-S3; bucket private, Origin Access Control only |
| At rest, SQS | Server-side encryption enabled |
| Secrets | Secrets Manager; read per invocation, never logged |

No customer-managed KMS keys are configured. The account constraint forbids
multi-region keys, and single-region CMKs were judged unnecessary complexity
for this build; AWS-owned encryption is what the template uses. That is a
documented choice, not an omission.

## 8. Third parties

| Service | What leaves the system | Notes |
|---|---|---|
| Amazon Cognito | Email address, at sign-up | Same AWS account and region |
| Amazon Location Service | Coordinates and search text, server-side only | Same account; the browser never calls it directly for places or routes |
| Amazon SES | Email address and message body | Sandbox: verified recipients only |
| Map tile provider via Location Service | Viewport coordinates | Scoped credentials from the identity pool; tiles only |

**No analytics provider, no advertising pixel, no error-reporting SaaS, no
font or script CDN at runtime.** The frontend bundles its dependencies. This
means the browser makes requests only to the API, to CloudFront and to the map
tile endpoint.

Place search and routing are performed server-side specifically so that a
user's search text and chosen coordinates do not reach a third party from the
browser with an identity attached.

## 9. Data residency

All regional resources are in `ap-southeast-2`, which is the only region this
account permits. There is no cross-region replication, no multi-region table
and no global index outside the region. CloudFront is global by nature, and is
administered through `us-east-1` as the account rules allow; it serves static
assets only and holds no personal data.

A consequence: there is no cross-region disaster recovery, and
[OPERATIONS_RUNBOOK.md](OPERATIONS_RUNBOOK.md) §8 describes within-region
point-in-time restore only. That restore procedure is **untested**: LifeLink
is deployed (24 November 2026) and point-in-time recovery is enabled on eight
of the twelve tables, but no restore has been **rehearsed** against the
running stack.

## 10. Demo data

Everything currently in the local database is synthetic and marked with three
fields (`demoData`, `dataSource: "SYNTHETIC"`, `environment`). The seed script
refuses to run against anything that looks like production, via three
independent checks. See [DEMO_DATA.md](DEMO_DATA.md).

No real personal data has ever been entered into this system, in any
environment, because no environment has ever been deployed.

## 11. What a legal review would need to resolve

Listed so that the gaps are explicit rather than implied:

1. Lawful basis for processing donor blood group and donation history.
2. Retention periods for donation records and audit entries (§5).
3. Whether and how account deletion must be offered, and what happens to
   records other organizations depend on (§6).
4. Whether a donation certificate constitutes a health record.
5. Whether notifying a provider of a request's coordinates and blood group
   requires a separate basis from the requester's own consent.
6. Cross-border implications of `ap-southeast-2` for users elsewhere.
7. The content of the user-facing privacy notice and terms, which are
   currently placeholders.

The implementation does not block on these. It is designed so that answering
them changes configuration and adds an endpoint, rather than requiring the
data model to be rebuilt.
