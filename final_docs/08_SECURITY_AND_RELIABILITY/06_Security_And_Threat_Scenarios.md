# Security and Threat Scenarios

Specific attacks, what stops them, and — where nothing does — saying so.

---

## 1. The threat table

| # | Threat | Defence | Verified? |
|---|---|---|---|
| 1 | Stolen access token | 1-hour expiry; revocation enabled; **role read from DB**, so revocation is immediate | partly |
| 2 | Forged token | RS256 signature against the pool's JWKS | **live, 401** |
| 3 | Modified claim (e.g. rewritten `aud`) | signature covers the payload | **live, 401** |
| 4 | Token from another app client | audience checked **per token type** | unit tests only — see §3 |
| 5 | Token from another user pool | issuer checked | `TEST-VERIFIED` |
| 6 | **IDOR** — another organization's records | organization scoping, check 5, applied centrally | **live, 403** |
| 7 | Privilege escalation via `PATCH /me` | display name **only**; roles via a pending request | `TEST-VERIFIED` |
| 8 | Suspended user with a valid token | check 3, before the permission check | **live, 403** |
| 9 | User enumeration | `PreventUserExistenceErrors: ENABLED` | config verified |
| 10 | Credential stuffing | 12-char policy + Cognito rate limiting | config verified |
| 11 | Public S3 exposure | 4x Block Public Access, ACLs disabled, OAC-only policy | config verified |
| 12 | Bypassing CloudFront to hit S3 | bucket policy requires **this** distribution | config verified |
| 13 | **Overselling blood units** | conditional write + `TransactWriteItems` | **live, `NO_UNRESERVED_STOCK`** |
| 14 | Lost update on a batch | optimistic concurrency on `version` | `TEST-VERIFIED` |
| 15 | Replayed write | idempotency table, conditional put | `TEST-VERIFIED` |
| 16 | Audit tampering | API role: `PutItem` + `Query` **only** | config verified |
| 17 | Lambda compromise | per-table role; KMS condition-bound; cannot touch IAM; cannot escape SCPs | by design |
| 18 | **Traffic flood / DDoS** | gateway throttle 10/s; CloudFront absorbs static | **no WAF** |
| 19 | XSS stealing the token | React escapes by default; **but the token is in `localStorage`** | **partial** |
| 20 | CSRF | no cookie auth — a Bearer header is not sent automatically | by design |
| 21 | Open redirect after login | `redirect.js` constrains `returnTo` to internal paths | `TEST-VERIFIED` |
| 22 | Secrets in the repository | `scripts/security_audit.py` gate | **passes** |
| 23 | Secrets in env vars | **none** — all 12 are non-secret identifiers | config verified |

---

## 2. The scenarios worth walking through

### Scenario: an attacker steals a user's access token

**What they can do:** act as that user for up to **one hour**.

**What limits the damage:**

| Limit | Detail |
|---|---|
| Short lifetime | 1 hour |
| **Role not in the token** | **suspending the account takes effect on the next request** |
| Revocation | enabled on the app client |
| Scope | only that user's permissions — a donor's token gets a donor's 13 permissions |
| Isolation | still cannot reach another organization's records |

**This is the strongest consequence of reading roles from the database:** a
stolen token **cannot outlive a revocation.**

**Say this:**
> "A stolen access token works for up to an hour — that's inherent to bearer
> tokens. What limits it is that the role isn't in the token. If we suspend that
> account, the very next request with that same token gets a 403, because
> account status is read from the database on every request. So a stolen token
> can't outlive a revocation, which it would if the role were a claim."

### Scenario: an SQL injection attempt

**There is no SQL.** DynamoDB is accessed through the AWS SDK with parameterised
expression attribute values, so there is no query string to inject into.

**But do not stop there** — the honest version:

> "There's no SQL, so SQL injection isn't applicable. What *is* applicable is
> the equivalent class of bug: trusting user input in a key or a condition. We
> construct keys in the repository layer from validated values, and expression
> values are always passed as parameters rather than interpolated. The place I'd
> look hardest in a review is anywhere a path parameter reaches a key
> construction, because a crafted facility id is the DynamoDB-shaped version of
> the same mistake."

**That answer is much better than "we don't use SQL."**

### Scenario: XSS steals the token from `localStorage`

**This is the real residual risk, and it should be acknowledged.**

| | |
|---|---|
| The exposure | the session is in `localStorage`, readable by any JavaScript on the origin |
| What reduces it | React escapes interpolated content by default; no `dangerouslySetInnerHTML`; no third-party scripts in the browser |
| What does **not** reduce it | the storage choice itself |
| The alternative | an httpOnly cookie, which JavaScript cannot read — but needs a backend session endpoint and brings CSRF considerations |

**Say this rather than defending it:**
> "This is the honest residual risk. The session is in `localStorage`, which any
> JavaScript on our origin can read — so an XSS flaw would mean a stolen token.
> What reduces the chance is that React escapes content by default, we don't use
> `dangerouslySetInnerHTML` anywhere, and we load no third-party JavaScript at
> all, so the attack surface is just our own code.
>
> The more secure option is an httpOnly cookie, which JavaScript can't read.
> That needs a backend session endpoint and brings CSRF into scope. For this
> project we accepted `localStorage` with a one-hour token. I'd call that a fair
> criticism rather than defend it as optimal."

### Scenario: a Lambda function is compromised

**What the attacker gets:** that function's execution role, with temporary
credentials.

| From `ApiFunctionRole` they **could** | They **could not** |
|---|---|
| read and write the 12 tables | create any AWS resource |
| send to the 2 queues | touch IAM |
| call `AdminGetUser` on our pool | read S3 |
| geocode and route | decrypt anything outside DynamoDB (the `kms:ViaService` condition) |
| | escape the account's SCPs |
| | **modify or delete an audit record** (`PutItem` + `Query` only) |

**The realistic damage is our own data** — which is exactly why the audit table
is append-only from that role.

### Scenario: a traffic flood

| Layer | Behaviour |
|---|---|
| CloudFront | absorbs static traffic; a cache hit never reaches S3 |
| **API Gateway** | **throttles at 10 req/s, burst 20** -> 429 |
| Lambda | protected by the throttle; alarm on throttles |
| DynamoDB | on-demand scales |
| **WAF** | **none** |

**The honest answer:** the stage throttle is the real defence, and it works by
shedding load rather than absorbing it. **There is no WAF**, so there are no
rate-based rules per IP and no managed rule groups. A distributed flood would
hit the throttle and legitimate users would get 429s too.

For a demonstration site with synthetic data that is acceptable. For production,
WAF via CloudFront would be the first addition.

---

## 3. What cannot be demonstrated — say so

| Claim | Why it cannot be shown |
|---|---|
| **The audience fix blocks a cross-client token** | our pool has **exactly one app client**, so no such token can be produced. That is also why it was never exploitable. Proven by unit test: reverting fails 3 of 23 |
| **DLQ recovery works** | no message has ever reached a DLQ. The procedure is documented, not practised |
| **Browser-level security** | **no browser automation exists in this project.** 12 manual checks outstanding |
| **The identity-pool tile path is blocked** | only the **API key** path was attempted and refused. Do not claim the other path is blocked — `NEEDS-VERIFICATION` |

**Claiming a demonstrated attack you could not construct invites exactly one
follow-up question that destroys it.** Saying the limit plainly is stronger.

---

## 4. The honest gap list

| Gap | Severity | Note |
|---|---|---|
| **No WAF** | medium | HTTP APIs don't support it directly; it would attach at CloudFront |
| **MFA is OPTIONAL** | medium | should be **required** for institutional roles in production |
| **`ADMIN_USER_PASSWORD_AUTH` enabled** | medium | non-prod test scripting; disable in production |
| **Token in `localStorage`** | medium | XSS exposure; the alternative is an httpOnly cookie |
| **Deletion protection off** on all 12 tables | medium | demo trade-off |
| **SNS alarm topic: 0 subscriptions** | medium | detection works, notification does not |
| **No DLQ on either schedule** | low | dropped invocations leave no record |
| CloudFront access logging disabled | low | API Gateway logging **is** on |
| `MinimumProtocolVersion: TLSv1` | low | a consequence of the default CloudFront certificate |
| Secret rotation not enabled | low | the secret has never been accessed |
| 4 log groups never expire | low | IaC coverage gap |
| Stack drift never checked | low | `NEEDS-VERIFICATION` |

**Presenting this list yourself is much stronger than having items extracted
one at a time.**

---

## 5. What is genuinely good

**Do not undersell these:**

| Strength | Evidence |
|---|---|
| **0 IAM users, 0 access keys** | no long-lived credential exists to leak — the most common cause of AWS compromise |
| **Per-table IAM policies** | the dispatcher can read inventory and **physically cannot** write it |
| **Audit append-only by IAM** | `PutItem` + `Query` only; no update, no delete |
| **Roles read per request** | revocation is immediate, verified live |
| **Central IDOR defence** | cannot be forgotten in a handler; verified live 200 vs 403 |
| **Route-table completeness test** | "no endpoint unprotected" is **checked** |
| **No secrets anywhere inappropriate** | `security_audit.py` gate passes |
| **Private S3 behind OAC** | public site, private bucket |
| **One wildcard, condition-bound** | `kms:ViaService` restricts it to DynamoDB |
| **No third-party JavaScript** | the only external browser origin is a map tile server |

---

## 6. Data privacy

| Consideration | Position |
|---|---|
| **All data is synthetic** | 742 rows, every record flagged `demoData: true` |
| Real personal data in the system | **two real email addresses** among 11 Cognito users — **do not display them** |
| Search coordinates | **not stored** on the user's record |
| Site indexing | `noindex, nofollow` |
| Demo email domain | `@demo.lifelink.invalid` — `.invalid` **can never resolve** |
| `/health` | returns `demoEnvironment: true` |

**Honest note:** a search coordinate passed as a query parameter will appear in
the API Gateway access log's request context. Acceptable for synthetic users; a
production system should consider whether search coordinates belong in access
logs.

---

## 7. Spoken answers

### "How is the system secured?" — 30 seconds
> "In layers that each assume the one above might be bypassed. HTTPS everywhere
> and a private S3 bucket behind CloudFront. Cognito for authentication with
> twelve-character passwords and PKCE. Five ordered authorization checks in our
> own code, including an organization scoping check that's the IDOR defence.
> And nine IAM roles with per-table policies, so each Lambda can reach only what
> it needs — our dispatcher can read inventory and physically cannot write it."

### "What's your biggest security weakness?" — 30 seconds
> "Operationally, that our eight alarms publish to an SNS topic with no
> subscribers — so we'd detect a problem and nobody would be told.
> Architecturally, the session token is in `localStorage`, so an XSS flaw would
> mean a stolen token; the more secure option is an httpOnly cookie. And there's
> no WAF. None of those matter much with synthetic data; all three would matter
> immediately with real data."

### 1–2 minutes on the whole topic
> "I'd split it into what's genuinely good and what's genuinely missing.
>
> Good: we have zero IAM users and zero access keys, so there's no long-lived
> credential to leak — which is the most common way AWS accounts get
> compromised. Each Lambda has its own role with a separate policy per table, and
> where a function only reads, it only has read actions. The audit table is
> append-only enforced by IAM rather than by convention. And our authorization
> reads the user's role from the database on every request, so revoking access
> is immediate — a stolen token can't outlive a revocation.
>
> Missing: no WAF, MFA is optional rather than required, the token sits in
> `localStorage` which is XSS-exposed, deletion protection is off on the tables,
> and our alarms notify nobody.
>
> And one thing I want to be straight about: the audience fix in our token
> verification closes a real weakness, but I can't demonstrate the attack,
> because our pool has exactly one app client so a cross-client token can't be
> produced. That's also why it was never exploitable. It's proven by unit test —
> reverting the fix fails three of twenty-three."

---

## 8. Cross-references

- [01_Cognito_Authentication_Flow.md](01_Cognito_Authentication_Flow.md)
- [03_JWT_And_Token_Verification.md](03_JWT_And_Token_Verification.md)
- [04_User_And_Facility_Isolation.md](04_User_And_Facility_Isolation.md)
- [05_Error_Handling_And_Retries.md](05_Error_Handling_And_Retries.md)
- [../04_AWS_COMPLETE_GUIDE/12_AWS_Security_And_Permissions.md](../04_AWS_COMPLETE_GUIDE/12_AWS_Security_And_Permissions.md)
- `docs/SECURITY.md`, `docs/PRIVACY_AND_DATA_HANDLING.md`
