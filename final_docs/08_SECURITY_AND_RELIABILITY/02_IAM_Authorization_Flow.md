# Authorization Flow

**Two different authorization systems operate in LifeLink, and conflating them
is the most common mistake.** This document covers both and keeps them
separate.

---

## 1. The two systems

| | **AWS IAM** | **Application RBAC** |
|---|---|---|
| Decides | what our **Lambda functions** may do | what a **user** may do |
| Subject | AWS services | application users |
| Enforced by | the **AWS API** | **our code** (`@requires`) |
| Credential | temporary AWS credentials (SigV4) | a Cognito JWT |
| Rules live in | IAM policies | `backend/src/appcore/rbac.py` |
| Example | "may this Lambda read the inventory table?" | "may this donor read the audit log?" |

**A blood bank admin has no IAM identity at all.** They have a Cognito token,
and our own code decides what they may do.

**Say this if the question is ambiguous:**
> "There are two layers and it's worth being clear which one you're asking
> about. IAM controls what our AWS services can do — can this Lambda function
> read this DynamoDB table. Our application RBAC controls what a user can do,
> and that's enforced in our own code using a role stored in DynamoDB. A blood
> bank admin doesn't exist in IAM at all."

---

## 2. Application RBAC — the five ordered checks

`@requires(...)` in `backend/src/appcore/auth.py` is the **only** place
authorization happens. From the module docstring:

```
1. Token signature and standard claims.
2. Load the user from the database -- roles come from stored state, not
   claims, so a revoked role takes effect on the next request.
3. Account status: a valid JWT from a suspended account is rejected here.
4. Permission check.
5. Organization scoping -- the IDOR defence, applied centrally.
```

| # | Check | Failure | Why in this position |
|---|---|---|---|
| 1 | token signature, `iss`, `exp`, `token_use`, audience | `401` | no point asking anything else about an unauthenticated caller |
| 2 | load the user **from DynamoDB** | `401` | we need stored state before any decision |
| 3 | account status | **`403 ACCOUNT_SUSPENDED`** | a suspended account must be refused **before** permissions are considered |
| 4 | permission held by the role | `403 FORBIDDEN` | |
| 5 | **organization scoping** | `403` | the record-level check, last |

**Why the order is the design, not an accident:** check 3 before check 4 means
a suspended blood bank admin is refused for being suspended, not for lacking a
permission they do in fact hold. The error the caller gets is the true reason.

---

## 3. Why roles come from the database, not the token

**The single most important design decision in authorization.**

| | Role in the token | Role in DynamoDB (ours) |
|---|---|---|
| Revocation takes effect | **up to 1 hour later** | **next request** |
| Suspension takes effect | up to 1 hour later | **next request** |
| Organization scoping | a flat claim cannot express a relationship | a record can |
| Cost | none | **one `GetItem` per request** |

**Verified live:** a suspended account with a freshly issued, perfectly valid
token receives **403 `ACCOUNT_SUSPENDED`**.

**Say this:**
> "Roles aren't in the token. Our Cognito pool has no groups and no custom
> attributes — the role is in DynamoDB and read on every single request.
>
> The reason is revocation. If a role were a claim, revoking someone's access
> would take up to an hour, because that's the token lifetime. Reading it from
> the database means it applies on the very next request. We verified that: a
> suspended account with a completely valid token gets a 403.
>
> It also handles something a flat group can't express. A blood bank admin isn't
> an admin in general — they have authority over their own facility. That's a
> role plus an organization plus a relationship, which is a record, not a flag.
>
> The cost is one extra read per request, a few milliseconds. Worth it."

---

## 4. The permission model

**39 permissions, 10 roles.** See
[../01_START_HERE/03_Project_Features_And_User_Roles.md](../01_START_HERE/03_Project_Features_And_User_Roles.md)
for every role's exact list.

### The naming convention carries meaning

| Pattern | Means | Example |
|---|---|---|
| `thing:action` | general authority | `inventory:write` |
| `thing:action:own` | **only your own records** | `reservation:manage:own` |
| `thing:action:public` | the publicly visible subset | `inventory:read:public` |
| `thing:action:detailed` | the privileged subset | `inventory:read:detailed` |

**The clearest pair:**

| Permission | Who | What |
|---|---|---|
| `reservation:manage:own` | the **requester** | cancel **their own** hold |
| `reservation:manage` | the **blood bank** | decide and fulfil holds **against its facility** |

---

## 5. Organization scoping — the IDOR defence

**IDOR** — Insecure Direct Object Reference — is passing someone else's record
id and getting their data. It is one of the most common real-world web
vulnerabilities, precisely because it is easy to forget in **one** handler out
of fifty-eight.

**So it is not in the handlers.** `is_organization_scoped(permission)` tells the
decorator whether check 5 applies, and the decorator applies it centrally.

| Permissions | Scoped? |
|---|---|
| **17 global** — `facility:read`, `camp:read`, `inventory:read:public`, `audit:read`, `system:admin`, … | **no** |
| **22 organization-scoped** — `inventory:read:detailed`, `inventory:write`, `inventory:verify`, `reservation:manage`, … | **yes** |

**The pattern:** public reads are global; anything touching a specific
organization's records is scoped.

**Verified live:**

| Test | Result |
|---|---|
| Blood bank admin on **their own** facility's reservation queue | **200** |
| Same admin on **another** facility's queue | **403** |
| Donor on another organization's emergency request | **403** |

> **A verification story worth telling.** During live testing a probe reported
> "0 entries" for an emergency request, which looked like a data bug. It was
> actually a **403** — organization isolation working correctly. The probe
> script was reading `.data` on an error response. The lesson: check the status
> before reading the body, or a working security control looks like a broken
> feature.

---

## 6. How "no endpoint was left unprotected" is checked, not claimed

Every route declares its permission in the route table. **A test enumerates
that table and fails the build if any route is missing authorization
metadata.**

```python
Route(method=..., path=..., handler=..., permission=..., allow_anonymous=...)
```

**That turns a claim into a property.** The alternative — reviewing 58
handlers by eye — is exactly how one gets missed.

**Anonymous routes still declare a permission.** The 9 anonymous-allowed routes
name `facility:read`, `inventory:read:public` or `camp:read`, and are served to
a `PUBLIC` principal holding 4 of the 39 permissions.

**Anonymity is not a bypass. It is a principal with few permissions.**

**Say this:**
> "The thing I'd point to is that 'we didn't leave an endpoint open' is checked
> rather than claimed. Every route declares the permission it requires in the
> route table, and there's a test that enumerates the table and fails the build
> if any route is missing authorization metadata. Reviewing fifty-eight handlers
> by eye is exactly how you miss one.
>
> And even our anonymous routes declare a permission. An unauthenticated caller
> isn't an exception path — it's a principal called PUBLIC that holds four of
> our thirty-nine permissions. So the authorization code runs identically; it
> just happens to pass."

---

## 7. AWS IAM authorization — the other system

9 roles, 0 IAM users, 0 access keys. Full detail in
[../04_AWS_COMPLETE_GUIDE/08_IAM_Complete_Guide.md](../04_AWS_COMPLETE_GUIDE/08_IAM_Complete_Guide.md).

### The flow

```
Lambda needs to read DynamoDB
   -> the Lambda service assumed the execution role (sts:AssumeRole)
   -> temporary credentials are in the execution environment
   -> boto3 signs the DynamoDB request with SigV4
   -> AWS evaluates: explicit Deny? SCP? an Allow? -> allow or deny
```

### Policy evaluation, in order

1. **Explicit `Deny` anywhere** -> **denied**. Nothing overrides it.
2. **An Organizations SCP** allows it? If not -> **denied**.
3. **An `Allow`** in an applicable policy? If not -> **denied** (implicit).
4. Otherwise -> **allowed**.

**We hit step 1 for real.** The account's SCP denies creating an
`AWS::Location::APIKey`, and no IAM permission of ours could override it — which
is why ADR-0019 exists and the basemap is OpenStreetMap.

**That is the clearest demonstration of policy evaluation the project has.**

### Least privilege, demonstrated by what a role CANNOT do

| Role | Can write | Read-only on |
|---|---|---|
| `PriorityDispatcherRole` | `emergency`, `notifications` | **`inventory`**, `facilities`, `organizations` |
| `NotificationWorkerRole` | `notifications`, `idempotency` | `organizations` |
| `ScheduledMaintenanceRole` | 7 tables; **`audit`: `PutItem` only** | `organizations` |

**The dispatcher reads stock to rank providers and physically cannot modify
it.** The maintenance role can append audit records and cannot alter one.

---

## 8. Where the two systems meet

**Exactly one place:** the Cognito **identity pool**, which exchanges a user's
token for temporary IAM credentials via `MapReaderRole`.

It was deployed for browser map-tile access (ADR-0012) and **is never used**,
because ADR-0019 replaced that approach.

**It remains the best example of a federated trust policy in the project:**

```json
{ "Principal": { "Federated": "cognito-identity.amazonaws.com" },
  "Action": "sts:AssumeRoleWithWebIdentity",
  "Condition": { "StringEquals": {
      "cognito-identity.amazonaws.com:aud": "ap-southeast-2:31685707-..." }}}
```

**Without that condition, any Cognito identity pool in any AWS account could
assume this role.** That is the confused-deputy problem, and the condition is
the defence.

---

## 9. Live verification — the authorization results

| Test | Result |
|---|---|
| Donor on `GET /admin/audit` | **403** |
| Donor on another facility's reservation queue | **403** |
| Donor on the emergency provider queue | **403** |
| Donor attempting to certify clinical priority | **403** |
| Blood bank admin on **their own** queue | **200** |
| Suspended account, valid token | **403 `ACCOUNT_SUSPENDED`** |
| Anonymous on 9 public routes | **200** |
| Anonymous on `/me` | **401** |

Plus **33 authorization unit tests** in
`backend/tests/unit/test_authorization.py`, including the route-table
completeness check.

---

## 10. Spoken answers

### "How does authorization work?" — 30 seconds
> "Every protected handler is wrapped in a decorator that runs five checks in a
> fixed order: verify the token, load the user from DynamoDB, check their
> account status, check they hold the required permission, and check the record
> belongs to their organization. That's the only place authorization happens, and
> a test enumerates the route table to prove no endpoint is missing it."

### 1–2 minutes
> "It's five checks in one decorator, and the order is deliberate.
>
> First the token signature. Then — and this is the part people don't expect —
> we load the user from DynamoDB rather than reading their role from the token.
> That's because a role in a one-hour token stays effective for up to an hour,
> whereas reading from the database means a revoked role applies on the next
> request.
>
> Third is account status, and it runs *before* the permission check so a
> suspended admin is refused for being suspended rather than for lacking a
> permission they actually hold — the error tells the truth.
>
> Fourth the permission itself, from a set of thirty-nine across ten roles.
>
> Fifth is organization scoping, which is the IDOR defence. Insecure Direct
> Object Reference — passing someone else's record id — is one of the most
> common real vulnerabilities, precisely because it's easy to forget in one
> handler out of fifty-eight. So it isn't in the handlers; it's applied
> centrally based on whether the permission is organization-scoped. Seventeen of
> ours are global and twenty-two are scoped.
>
> We verified it live: a blood bank admin on their own facility's reservation
> queue gets 200, and the same admin on another facility's queue gets 403."

---

## 11. Follow-up questions

**"What if you forgot the decorator on a handler?"**
> The route table test catches it. Every route declares its permission as part
> of registration, and a test enumerates the table and fails if any route lacks
> authorization metadata. It's not possible to register a route without stating
> either a permission or that it allows anonymous access.

**"Can a user escalate their own privileges?"**
> No. `PATCH /me` changes a display name and nothing else — not the role, not
> the organization, not the account status. Getting an institutional role means
> submitting a request that stays pending until a platform admin approves it,
> and there's a test for exactly that.

**"Is 39 permissions too many?"**
> It's more than many projects, and each one earns its place by expressing a
> different act of trust. Inventory alone has seven — public read, detailed
> read, write, correct, quarantine, verify, ingest — because recording stock and
> independently verifying it are genuinely different, and we wanted blood bank
> staff to be able to quarantine stock for safety without being able to attest
> that it's verified. If I were trimming, I'd look at whether `confirm` and
> `certify` on emergency requests should share a permission, which they
> currently do.

**"What's the weakest point?"**
> The API Lambda's IAM role, honestly. It's the union of all fifty-eight
> routes' needs, so a route that only reads facilities runs with permission to
> write inventory. The application-level check stops a *user* doing the wrong
> thing, but a bug in our own code would have broader AWS permissions available
> than that route needs. Splitting the API by feature area would narrow it, at
> the cost of more cold starts against a concurrency limit of ten.

---

## 12. Cross-references

- [01_Cognito_Authentication_Flow.md](01_Cognito_Authentication_Flow.md)
- [04_User_And_Facility_Isolation.md](04_User_And_Facility_Isolation.md)
- [../04_AWS_COMPLETE_GUIDE/08_IAM_Complete_Guide.md](../04_AWS_COMPLETE_GUIDE/08_IAM_Complete_Guide.md)
- [../01_START_HERE/03_Project_Features_And_User_Roles.md](../01_START_HERE/03_Project_Features_And_User_Roles.md)
- [../09_PRACTICAL_AWS_DEMONSTRATIONS/06_Showing_IAM_In_Action.md](../09_PRACTICAL_AWS_DEMONSTRATIONS/06_Showing_IAM_In_Action.md)
