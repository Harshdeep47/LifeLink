# AWS Security and Permissions

How LifeLink is secured at the AWS layer, what is genuinely good, and what is
genuinely missing.

---

## 1. The layers of defence

```
Internet
  |
  |-- CloudFront ----- HTTPS enforced (redirect-to-https)
  |     |              no WAF  <-- gap
  |     `-- OAC ------ S3 reachable ONLY by this distribution
  |
  |-- API Gateway ---- throttle 10 req/s, CORS 3 exact origins
  |     |              no authorizer (deliberate)
  |     `-- Lambda --- 5 ordered authorization checks
  |           |
  |           `-- IAM execution role, per-table scoped
  |                 |
  |                 `-- DynamoDB, encrypted with KMS
  |
  `-- Cognito -------- 12-char password + symbol, PKCE, 1-hour tokens
```

**The principle to state:** no single layer is the security. Each assumes the
ones above it may be bypassed.

---

## 2. Encryption

### At rest

| Store | Method | Key |
|---|---|---|
| **DynamoDB** (all 12 tables) | **SSE-KMS** | AWS-managed `alias/aws/dynamodb` |
| **S3** (both buckets) | **SSE-S3** (`AES256`) | S3-managed, no KMS |
| **SQS** (all 4 queues) | **SSE-SQS** | SQS-managed |
| **Secrets Manager** | KMS | AWS-managed `aws/secretsmanager` |
| CloudWatch Logs | AWS-managed by default | — |

**The account has exactly 3 KMS keys, and all 3 are `KeyManager: AWS`. There
are no customer-managed keys.**

**If asked why not customer-managed:** a CMK costs about $1/month per key and
buys two things — the ability to revoke access to the data by disabling the
key, and control over rotation. For synthetic demonstration data neither is
worth the cost. For real patient-adjacent data, a CMK on the audit and
inventory tables would be the right call, and it would also let us remove the
one wildcard from our IAM policies.

**That last clause is a good detail** — it connects two topics.

### In transit

| Path | Protection |
|---|---|
| Browser -> CloudFront | **HTTPS enforced** (`redirect-to-https`) |
| CloudFront -> S3 | HTTPS, **SigV4-signed** via OAC |
| Browser -> API Gateway | HTTPS only |
| Browser -> Cognito | HTTPS only |
| Lambda -> DynamoDB/SQS/Cognito | HTTPS with SigV4 |
| Browser -> OpenStreetMap tiles | HTTPS |

**Minimum TLS version is `TLSv1`** on CloudFront, which comes with the default
CloudFront certificate. A custom domain with an ACM certificate would allow
requiring TLS 1.2. Honest gap, cheap to state.

---

## 3. Identity and access — the three distinct systems

**Keeping these separate in your head is the single most valuable thing in this
document**, because they are constantly conflated.

| System | Identifies | Credential | Checked by |
|---|---|---|---|
| **IAM** | AWS services | temporary AWS credentials | the AWS API |
| **Cognito user pool** | application users | JWT | **our Lambda code** |
| **Application RBAC** | what a user may do | the role stored in DynamoDB | `@requires()` |

A blood bank admin has **no IAM identity at all**. They have a Cognito token,
and our own code decides what they may do using a role read from DynamoDB.

---

## 4. Least privilege — the evidence

9 IAM roles, **0 IAM users, 0 access keys**. Each Lambda has its own role, and
each role gets a **separate inline policy per table**, scoped to that table's
ARN and its indexes.

**The demonstration that proves it is real rather than decorative:**

| Role | Can write | Can only read | Cannot touch |
|---|---|---|---|
| `PriorityDispatcherRole` | `emergency`, `notifications` | `inventory`, `facilities`, `organizations` | everything else |
| `NotificationWorkerRole` | `notifications`, `idempotency` | `organizations` | everything else |
| `ScheduledMaintenanceRole` | 7 tables, **`audit`: PutItem only** | `organizations` | everything else |

**The dispatcher reads stock levels to rank providers and physically cannot
modify stock.** Not because the code does not try — because the permission does
not exist.

**The maintenance role can append audit records and cannot read or delete
one.** An audit trail enforced by permissions rather than convention.

Full detail: [08_IAM_Complete_Guide.md](08_IAM_Complete_Guide.md).

---

## 5. The one wildcard, and how to defend it

```json
{ "Effect": "Allow",
  "Action": ["kms:GenerateDataKey", "kms:Decrypt"],
  "Resource": "*",
  "Condition": { "StringEquals": {
      "kms:ViaService": "dynamodb.ap-southeast-2.amazonaws.com" }}}
```

**Why it exists:** DynamoDB encrypts with the AWS-managed `aws/dynamodb` key,
whose ARN contains an AWS-generated id not knowable at template-authoring time.

**Why it is constrained:** `kms:ViaService` means these actions can only be
exercised **through DynamoDB in this Region**. The role cannot call KMS
directly to decrypt anything else.

**Never say "it's safe because it's just KMS."** Say it is scoped by
**condition** rather than by **resource**, explain why that was necessary, and
note that a customer-managed key would give a nameable ARN and remove the
wildcard — for about a dollar a month.

---

## 6. Application-level security — the five ordered checks

`@requires(...)` in `backend/src/appcore/auth.py` is the **only** place
authorization happens:

| # | Check | Failure |
|---|---|---|
| 1 | Token signature (RS256 vs JWKS), `iss`, `exp`, `token_use`, audience | `401` |
| 2 | Load the user **from DynamoDB** | `401` |
| 3 | Account status | **`403 ACCOUNT_SUSPENDED`** |
| 4 | Permission held by the role | `403 FORBIDDEN` |
| 5 | **Organization scoping** — the IDOR defence | `403` |

**Check 5 is the one worth dwelling on.** IDOR — Insecure Direct Object
Reference — is passing someone else's record id and getting their data. Putting
the organization check in the shared decorator means it cannot be forgotten in
an individual handler.

**Verified live:**

| Test | Result |
|---|---|
| Donor token on `GET /admin/audit` | **403** |
| Donor on another facility's reservation queue | **403** |
| Blood bank admin on **their own** facility's queue | **200** |
| Suspended account with a **valid** token | **403 `ACCOUNT_SUSPENDED`** |
| No token on `/me` | **401** |
| Garbage token | **401** |
| Token with a rewritten `aud` | **401** |
| Self-signed token for another client | **401** |
| Donor attempting to certify clinical priority | **403** |

**19 authentication checks and 37 workflow checks were run against the live
system — 56 in total, all passing.**

---

## 7. Secrets — where they are and are not

| | |
|---|---|
| **Secrets Manager** | `lifelink/dev/provider-api-keys` — the only secret |
| **Lambda environment variables** | **12, all non-secret identifiers** |
| **Frontend build variables** | all public identifiers by necessity |
| **Git repository** | **no secrets** — enforced by `scripts/security_audit.py` |

**Why no secrets in environment variables:** they are readable by anyone with
`lambda:GetFunctionConfiguration`. A secret there is not a secret.

**Why the frontend values are not secrets:** every one necessarily reaches the
browser. The app client is a **public client with no secret**, which is exactly
why it uses PKCE. The real secrets — execution roles, the Secrets Manager
secret — never leave AWS.

**`scripts/security_audit.py`** is a gate that scans for credentials and
fails the build if it finds any. It passes.

**Honest gaps:** rotation is **not enabled** on the secret, and it has
**never been accessed** — no external provider is connected.

---

## 8. Account-level controls

This is a **new AWS experience** account with managed **service control
policies** (SCPs) and **resource control policies** (RCPs).

**An SCP is an explicit deny at the organization level that no IAM policy can
override.** That is not a theoretical detail here — it shaped the architecture:

| Denied | Consequence |
|---|---|
| `AWS::Location::APIKey` | Browser Amazon Location tiles impossible -> **ADR-0019**, OpenStreetMap instead |
| SMS sending | ADR-0015 reinforced |
| Cross-Region actions | no replication, no multi-Region keys, no StackSets |
| Lambda@Edge | excluded |

**Say this — it is a genuinely good illustration of policy evaluation:**
> "Our account has service control policies, which are explicit denies at the
> organization level that no IAM policy can override. We hit one for real:
> creating an Amazon Location API key is denied, and it didn't matter what our
> own permissions said. The resource creation failed outright, and we changed the
> design — that's ADR-0019, and it's why our basemap is OpenStreetMap rather than
> Amazon Location. It's the clearest demonstration I have of why explicit deny
> sits first in policy evaluation."

Human access is **managed IAM**: team members are invited by email, not created
as IAM users. That is why the account has zero IAM users.

---

## 9. The honest gaps, listed

| Gap | Severity | Note |
|---|---|---|
| **No WAF on CloudFront** | medium | Defensible for a demo; a production system should have rate-based rules and AWS Managed Rules. HTTP APIs don't support WAF directly, so it would attach at CloudFront |
| **CloudFront access logging disabled** | low | API Gateway logging *is* on, so API traffic is logged; static-file requests are not |
| **`MinimumProtocolVersion: TLSv1`** | low | A consequence of the default CloudFront certificate |
| **MFA is OPTIONAL** | medium | For institutional roles — blood bank and hospital admins — it should be required in production |
| **`ADMIN_USER_PASSWORD_AUTH` enabled** | medium | Used for non-production test scripting; should be disabled in a production pool |
| **Deletion protection off on all 12 tables** | medium | Demo trade-off; should be on in production |
| **Secret rotation not enabled** | low | The secret has never been accessed |
| **SNS alarm topic has 0 subscriptions** | **medium** | Detection works; notification does not |
| **4 log groups never expire** | low | IaC coverage gap; a slow cost leak |
| **Stack drift never checked** | low | `NEEDS-VERIFICATION` |

**Presenting this list yourself is much stronger than having items extracted
from you one at a time.**

---

## 10. Threat scenarios

| Threat | Defence |
|---|---|
| Stolen access token | 1-hour expiry; revocation enabled; **role read from DB**, so revoking a role is immediate |
| Forged token | RS256 signature against the pool's JWKS — we can verify but not forge |
| Token from another app client | audience checked per token type |
| Reading another organization's data (IDOR) | check 5, centrally applied. Verified: **403** |
| Privilege escalation via `PATCH /me` | display name **only**; role changes go through a pending request a platform admin must verify |
| Suspended user with a valid token | check 3. Verified: **403 `ACCOUNT_SUSPENDED`** |
| Credential stuffing | 12-char policy, Cognito rate limiting, `PreventUserExistenceErrors` |
| User enumeration | `PreventUserExistenceErrors` — wrong password and unknown email return the same error |
| Public bucket exposure | all four Block Public Access settings on; ACLs disabled; OAC-only bucket policy |
| Bypassing CloudFront to hit S3 | bucket policy requires this distribution |
| Overselling blood units | conditional writes + `TransactWriteItems`. Verified: `NO_UNRESERVED_STOCK` |
| Lambda compromise | role scoped per table; KMS condition-bound; cannot create resources or touch IAM; cannot escape SCPs |
| DDoS / traffic flood | gateway throttle 10 req/s; CloudFront absorbs static traffic. **No WAF** |
| Audit tampering | API role has `PutItem` + `Query` only; maintenance role `PutItem` only |

---

## 11. Spoken answers

### "How is user data protected?" — 30 seconds
> "In layers. Everything is encrypted at rest — DynamoDB with KMS, S3 and SQS
> with service-managed keys — and in transit over HTTPS everywhere. Access is
> controlled twice: IAM decides what our Lambda functions can reach, scoped to
> one table per policy, and our own code decides what a user can do using a role
> stored in DynamoDB and read on every request. And the data itself is entirely
> synthetic, so there's no real personal health information anywhere."

### 1–2 minutes
> "I'd describe three separate systems people often conflate.
>
> IAM controls what our AWS services can do. Nine roles, zero IAM users, zero
> access keys — so there's no long-lived credential to leak, which is the most
> common way AWS accounts get compromised. Each Lambda has its own role with a
> separate policy per table, and where a function only reads, it only has read
> actions: the dispatcher reads inventory to rank blood banks and physically
> cannot modify it.
>
> Cognito identifies application users and issues JWTs. Twelve-character
> passwords with a symbol, Authorization Code with PKCE, one-hour tokens.
>
> And our own authorization layer decides what a user may do. That's five checks
> in a fixed order in a single decorator: signature, load the user from
> DynamoDB, account status, permission, and organization scoping. Loading the
> role from the database rather than the token means revoking access takes
> effect on the next request instead of up to an hour later — and we verified
> that live: a suspended account with a perfectly valid token gets a 403.
>
> The gaps I'd name are no WAF on CloudFront, MFA only optional, and deletion
> protection off on the tables. All defensible for a demo with synthetic data;
> all things I'd change for production."

---

## 12. Follow-up questions

**"What's your biggest security weakness?"**
> Operationally, that our alarms publish to an SNS topic with no subscribers —
> so we'd detect a problem and nobody would be told. Architecturally, the
> absence of a WAF, and that MFA is optional rather than required for
> institutional roles. None of those would matter much with synthetic data; all
> three would matter immediately with real data.

**"How do you know nobody's bypassing your authorization?"**
> Two things. Every route declares its permission in the route table, and a test
> enumerates that table and fails the build if any route lacks authorization
> metadata — so "no endpoint was left open" is checked, not claimed. And we ran
> 19 authentication checks against the live deployed system, including a donor
> trying to read the audit log, a donor trying to read another facility's
> reservation queue, and a suspended account with a valid token. All refused with
> the right status.

**"If an attacker got your Lambda's credentials, what could they do?"**
> They'd have that function's role with temporary credentials. From the API role
> they could read and write our twelve tables and send to our two queues. They
> could not create AWS resources, touch IAM, read S3, or decrypt anything outside
> DynamoDB — the KMS statement is condition-bound to DynamoDB. And they couldn't
> escape the account's service control policies. The realistic damage is our own
> data, which is why the audit table is append-only from that role.

**"Is the data real?"**
> No, and that's a deliberate safety property. Sixteen fictional facilities with
> structurally validated but invented details, 742 rows in total. We tried to
> use real Punjab blood bank data from public sources and the sources were
> unreachable, so rather than fabricate plausible-looking real-world details we
> kept it clearly synthetic and documented it. The site also carries
> `noindex, nofollow` and says it's a demonstration environment with synthetic
> data.

---

## 13. Cross-references

- [08_IAM_Complete_Guide.md](08_IAM_Complete_Guide.md)
- [07_Cognito_Complete_Guide.md](07_Cognito_Complete_Guide.md)
- [../08_SECURITY_AND_RELIABILITY/06_Security_And_Threat_Scenarios.md](../08_SECURITY_AND_RELIABILITY/06_Security_And_Threat_Scenarios.md)
- [../08_SECURITY_AND_RELIABILITY/04_User_And_Facility_Isolation.md](../08_SECURITY_AND_RELIABILITY/04_User_And_Facility_Isolation.md)
- [../09_PRACTICAL_AWS_DEMONSTRATIONS/CONFIGURATION_WALKTHROUGHS.md](../09_PRACTICAL_AWS_DEMONSTRATIONS/CONFIGURATION_WALKTHROUGHS.md)
- Original: `docs/SECURITY.md`, `docs/PRIVACY_AND_DATA_HANDLING.md`
