# User and Facility Isolation

How LifeLink stops one organization seeing another's data — the IDOR defence,
and the evidence it works.

---

## 1. The threat

**IDOR — Insecure Direct Object Reference.** A caller passes a record id that
belongs to someone else and receives their data.

```
GET /facilities/fac-SOMEONE-ELSES/reservations
     with a perfectly valid token for a different organization
```

**Why it is such a common real-world vulnerability:** the check has to be
present in **every** handler that takes a record id. Fifty-eight routes, and
missing it in one is a breach. Nothing about the code *looks* wrong when the
check is absent.

---

## 2. The defence: centralise it

**The check is not in the handlers.** It is check 5 of the five in
`@requires(...)`, applied by the shared decorator in
`backend/src/appcore/auth.py`.

```
1. token signature
2. load the user from DynamoDB
3. account status
4. permission
5. ORGANIZATION SCOPING  <- applied centrally, cannot be forgotten
```

`is_organization_scoped(permission)` in `backend/src/appcore/rbac.py` decides
whether it applies.

**Say this:**
> "IDOR is one of the most common real vulnerabilities, and the reason is that
> the check has to be in every handler that takes a record id — fifty-eight
> routes, and missing it in one is a breach. Nothing looks wrong when it's
> absent.
>
> So we don't put it in the handlers. It's the fifth check in the shared
> authorization decorator, applied centrally based on whether the permission is
> organization-scoped. A handler author can't forget it, because they never
> write it."

---

## 3. Which permissions are scoped

| | Count | Examples |
|---|---|---|
| **Global** (not scoped) | **17** | `facility:read`, `camp:read`, `inventory:read:public`, `emergency:create`, `audit:read`, `system:admin`, `profile:manage:own`, `user:manage` |
| **Organization-scoped** | **22** | `inventory:read:detailed`, `inventory:write`, `inventory:correct`, `inventory:quarantine`, `inventory:verify`, `reservation:manage`, `camp:manage` |

**The pattern:** public reads are global; anything touching a specific
organization's records is scoped.

### The pair that shows the model clearly

| Permission | Scoped? | Why |
|---|---|---|
| `inventory:read:public` | **no** | anyone may see public availability for any facility — that is the product |
| `inventory:read:detailed` | **yes** | batch-level data, expiry dates and audit history belong to the facility |

**One feature, two permissions, two different isolation answers.** That is the
model working.

---

## 4. The three layers of isolation

### Layer 1 — the permission itself

A donor does not hold `inventory:read:detailed` at all, so the question of
*whose* inventory never arises. **Check 4 refuses before check 5 runs.**

### Layer 2 — organization scoping

A blood bank admin **does** hold `inventory:read:detailed`, so check 5 decides:
is this facility theirs?

### Layer 3 — `:own` ownership

For personal records, the `:own` suffix means the record must belong to the
**caller**, not merely to their organization.

| Permission | Boundary |
|---|---|
| `reservation:manage:own` | **this user's** reservation |
| `reservation:manage` | **this organization's** facility |
| `alert:manage:own` | this user's alert |
| `registration:manage:own` | this user's camp registration |

**Three distinct boundaries — user, organization, and global — expressed in the
permission name.** That is worth pointing out: the name tells you the scope.

---

## 5. Verified live

| # | Test | Result |
|---|---|---|
| 1 | Donor token on `GET /admin/audit` | **403** |
| 2 | Donor on **another facility's** reservation queue | **403** |
| 3 | Blood bank admin on **their own** facility's queue | **200** |
| 4 | Donor on the emergency **provider queue** | **403** |
| 5 | Donor attempting to **certify** clinical priority | **403** |
| 6 | Donor reading **another organization's** emergency request | **403** |
| 7 | Suspended account with a valid token | **403 `ACCOUNT_SUSPENDED`** |

**Tests 2 and 3 together are the proof.** The *same permission*, the *same
endpoint shape*, different facility — 200 for their own, 403 for someone
else's. That demonstrates scoping rather than a blanket denial.

**Make that pairing explicit in a demonstration.** Showing only the 403 does
not prove scoping works; it could be that the endpoint is simply broken.

---

## 6. The verification story worth telling

During live testing, a probe reported **"0 entries"** for emergency request
`demo-req-p3-2`. That looked like a data bug — a request with no events.

**It was actually a 403.** Organization isolation was working correctly. The
probe script was reading `.data` on an **error** response, where `.data` does
not exist, and reporting the resulting empty value as a count.

**Two lessons:**

1. **Check the status before reading the body.** A working security control can
   look exactly like a broken feature.
2. **The flaw was in the test, not the system** — which is why it is worth
   investigating an anomaly rather than assuming the system is wrong.

**Say this:**
> "There's a nice story here. During live verification a probe reported zero
> entries for an emergency request, which looked like a data bug. It turned out
> to be a 403 — organization isolation working exactly as intended. My script
> was reading the `data` field on an error response, which doesn't have one, and
> reporting the empty result as a count.
>
> Two things I took from that. Always check the status before reading the body.
> And a working security control can look identical to a broken feature, so it's
> worth investigating an anomaly rather than assuming the system is at fault."

---

## 7. Where the data model supports isolation

Isolation is enforced in code, and the **data model makes it checkable**:

| Table | Scoping support |
|---|---|
| `organizations` | holds the user's `organizationId` — read on every request |
| `facilities` | **`GSI3-org`** — facilities belonging to an organization |
| `emergency` | **`GSI2-requester`** — my organization's requests |
| `emergency` | **`GSI3-provider`** — requests awaiting **my** response |
| `reservations` | **`GSI1-requester`** — my reservations |
| `camps` | **`GSI3-organizer`** — camps I organize |

**The important point:** these indexes mean a scoped list is a **query against
the caller's own partition**, not a full read followed by filtering. Isolation
is built into the access path, so a forgotten filter cannot leak rows that were
never fetched.

**That is a stronger property than a post-hoc filter**, and worth stating.

---

## 8. Audit — isolation you can inspect

| | |
|---|---|
| Table | `lifelink-dev-audit`, 22 rows |
| Index | `GSI1-actor` — actions by a user |
| Endpoint | `GET /admin/audit` — `audit:read`, **platform admin only** |
| API role permissions | **`PutItem` and `Query` only** |
| Maintenance role | **`PutItem` only** |

**No `UpdateItem`, no `DeleteItem` for either role.** The application can
append audit records and read them back, and **cannot modify or delete one** —
enforced by IAM, not by convention.

**Say this:**
> "The audit table is the one place where IAM does the work rather than our
> code. The API's role has PutItem and Query on it and no update or delete
> permission at all, and the maintenance role has PutItem only. So the
> application can append audit records and read them, and physically cannot
> alter one. That's an audit trail enforced by permissions rather than by
> everyone remembering not to."

---

## 9. What is deliberately NOT isolated

**Being clear about this is as important as the isolation itself.**

| Visible to everyone | Why |
|---|---|
| Facility names, addresses, contact details | **the product** — people need to find and phone a blood bank |
| Public availability (`inventory:read:public`) | the product |
| Camp listings | the product |
| Facility freshness and verification badges | trust information |

**What is NOT public:**

| Not visible | Permission needed |
|---|---|
| Batch-level inventory, expiry dates, audit history | `inventory:read:detailed` |
| Reservations | `reservation:manage` / `:own` |
| Emergency requests | `emergency:read:own` |
| Other users' details | — |
| The audit log | `audit:read` |

**The boundary:** *what blood banks have, roughly, is public. What they and
their counterparties are doing is not.*

---

## 10. Frontend route guards are not security

`RequireAuth` guards `/profile`, `/activity` and the five dashboards.

**It is a user-experience convenience, not a security boundary.**

| | |
|---|---|
| What it prevents | a signed-out user seeing an empty broken page |
| What it does **not** prevent | anything — the client is under the user's control |
| What actually enforces isolation | **every API call, server-side** |

**If someone removed the guard in DevTools**, they would see the dashboard
shell and every API call would return **401 or 403**.

**Say this:**
> "The route guard is for user experience, not security. If you deleted it in
> DevTools you'd see the dashboard frame and every single API call would come
> back 401 or 403, because authorization happens server-side on every request.
> A client-side guard can never be a security boundary — the client is under the
> user's control."

---

## 11. Status

| Aspect | Status |
|---|---|
| Central organization scoping | `REPO`, `DEPLOYED` |
| `is_organization_scoped` classification | `TEST-VERIFIED` |
| Cross-organization refusal | **verified live** (403) |
| Same-organization success | **verified live** (200) |
| `:own` ownership checks | `TEST-VERIFIED` |
| Audit append-only by IAM | `DEPLOYED` — visible in the role policy |
| Route-table completeness | `TEST-VERIFIED` |
| **Browser-level isolation by a person** | **NOT VERIFIED** |

33 authorization tests in `backend/tests/unit/test_authorization.py`, plus
`test_public_emergency_access.py` covering what anonymous callers may see.

---

## 12. Spoken answers

### 20–30 seconds
> "Isolation is the fifth check in our shared authorization decorator, so it
> can't be forgotten in an individual handler — which is how IDOR bugs normally
> happen. Twenty-two of our thirty-nine permissions are organization-scoped and
> seventeen are global. We verified it live: a blood bank admin gets 200 on
> their own facility's reservation queue and 403 on another facility's."

### 1–2 minutes
> "The threat is IDOR — passing someone else's record id with a valid token and
> getting their data. It's common in the real world precisely because the check
> has to be in every handler that takes an id, and missing it in one of
> fifty-eight is a breach, with nothing looking wrong in the code.
>
> So we centralised it. It's the fifth check in the authorization decorator,
> applied based on whether the permission is organization-scoped — twenty-two of
> ours are, seventeen aren't. Public availability is global, because anyone
> needs to find a blood bank; detailed batch data is scoped, because it belongs
> to the facility. Same feature, two permissions, two different answers.
>
> There's also a third boundary: the `:own` suffix means the record must belong
> to the caller personally, not just their organization. So
> `reservation:manage:own` is the requester cancelling their own hold, and plain
> `reservation:manage` is the blood bank deciding on holds against its facility.
>
> The proof that matters is a pair of live tests: the same admin, the same
> endpoint shape, 200 on their own facility and 403 on another. Showing just the
> 403 wouldn't prove scoping — it could mean the endpoint is broken."

---

## 13. Cross-references

- [02_IAM_Authorization_Flow.md](02_IAM_Authorization_Flow.md)
- [06_Security_And_Threat_Scenarios.md](06_Security_And_Threat_Scenarios.md)
- [../01_START_HERE/03_Project_Features_And_User_Roles.md](../01_START_HERE/03_Project_Features_And_User_Roles.md)
- [../05_DATABASE_AND_DATA/05_Database_Access_Patterns.md](../05_DATABASE_AND_DATA/05_Database_Access_Patterns.md)
- `docs/SECURITY.md`
