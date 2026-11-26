# Project Features and User Roles

The four features, the ten roles, and the 39 permissions — enumerated from
`backend/src/appcore/rbac.py`, so this is the implementation itself.

---

## 1. The four features, plus two cross-cutting workflows

| # | Feature | Core question it answers |
|---|---|---|
| 1 | **Blood bank inventory management** | What stock does this blood bank have, and how current is that claim? |
| 2 | **Discovery and location** | Where is the blood I need, near me? |
| 3 | **Donation camps and donor engagement** | Where can I donate, and what has my donation achieved? |
| 4 | **Smart emergency coordination** | Who should we ask first, urgently? |
| + | **Temporary reservations** | Can I hold these specific units? *(this **is** the ordinary request path — ADR-0018)* |
| + | **Authentication and accounts** | Who are you, and what may you do? |

---

## 2. The ten roles

| Role | Permissions | Who it is |
|---|---|---|
| `PUBLIC` | **4** | the baseline principal, including anonymous visitors |
| `DONOR` | 13 | a signed-in individual |
| `BLOOD_BANK_STAFF` | 9 | records and quarantines stock |
| `BLOOD_BANK_ADMIN` | 13 | also verifies stock and manages the facility |
| `HOSPITAL_STAFF` | 8 | raises emergency requests |
| `HOSPITAL_AUTHORIZER` | 9 | **can certify clinical priority** |
| `HOSPITAL_ADMIN` | 10 | certify + manage hospital users |
| `CAMP_STAFF` | 6 | checks donors in, records donations |
| `CAMP_ORGANIZER` | 9 | creates and manages camps, assigns staff |
| `PLATFORM_ADMIN` | **39** (all) | approves organizations, reads the audit log |

---

## 3. Exactly what each role holds

### `PUBLIC` — 4 permissions

```
camp:read   emergency:create   facility:read   inventory:read:public
```

**A precise point worth getting right.** `PUBLIC` is the baseline principal
assigned both to anonymous visitors and to a signed-in account with no
institutional role. The **9 anonymous-allowed routes** use only three of these
four: `facility:read`, `inventory:read:public` and `camp:read`.

`emergency:create` is held by `PUBLIC` but its route,
`POST /emergency-requests`, is **not** anonymous-allowed — so an individual with
a plain account can raise a request, while a visitor who is not signed in
cannot.

**That is the design:** anonymity is not an exception path around
authorisation. It is a principal with few permissions, and the route
additionally decides whether being unauthenticated is acceptable.

### `DONOR` — 13 permissions

```
alert:create            alert:manage:own        camp:read
emergency:cancel        emergency:create        emergency:read:own
facility:read           inventory:read:public   profile:manage:own
registration:create     registration:manage:own reservation:create
reservation:manage:own
```

A donor can create a reservation and manage **their own**, create alerts,
register for camps, and raise and cancel an emergency request. They cannot see
detailed inventory, and cannot act on anyone else's records.

### `BLOOD_BANK_STAFF` — 9

```
camp:read       emergency:respond       facility:read
inventory:quarantine    inventory:read:detailed inventory:read:public
inventory:write          profile:manage:own     reservation:manage
```

### `BLOOD_BANK_ADMIN` — 13

Everything staff has, plus:

```
facility:write   inventory:correct   inventory:ingest:api   inventory:verify
```

**The four additions are the interesting part:**

| Permission | Why it is admin-only |
|---|---|
| `inventory:verify` | **Updated is not verified.** Verifying is a more trusted act than recording |
| `inventory:correct` | Correcting a past figure is different from recording a new one — it rewrites a claim |
| `facility:write` | Changing facility details affects how it is discovered |
| `inventory:ingest:api` | Accepting machine-fed data from an external system |

**Note what staff *do* have:** `inventory:quarantine`. Staff can take stock out
of use immediately — a safety action should never need a manager — but cannot
declare it verified.

**That asymmetry is a good detail to point out.** The permission split follows
*trust*, not seniority.

### `HOSPITAL_STAFF` — 8

```
camp:read       emergency:cancel        emergency:create
emergency:read:own      facility:read   inventory:read:detailed
inventory:read:public   profile:manage:own
```

Can raise and cancel requests and see detailed inventory. **Cannot certify
clinical priority.**

### `HOSPITAL_AUTHORIZER` — 9

Hospital staff plus **`emergency:certify:priority`**.

**This is the most restricted permission in the system.** Only three of the ten
roles hold it: `HOSPITAL_AUTHORIZER`, `HOSPITAL_ADMIN` and `PLATFORM_ADMIN`.

**Why it exists as its own role.** Certifying clinical priority is a medical
judgement with consequences. The system **records who certified it** and never
makes the judgement itself. A separate role means a hospital can let many staff
raise requests while only a few may attest to urgency.

**Verified live:** a donor attempting to certify receives **403**.

### `HOSPITAL_ADMIN` — 10

Authorizer plus **`user:manage`** — suspend or reinstate accounts within the
hospital.

### `CAMP_STAFF` — 6

```
camp:checkin    camp:read       donation:record
donation:verify facility:read   profile:manage:own
```

### `CAMP_ORGANIZER` — 9

Camp staff plus:

```
camp:create   camp:manage   camp:staff:assign
```

**Note what an organizer does *not* have: `camp:approve`.** An organizer
creates a camp; a **platform admin** approves it. You cannot approve your own
camp.

### `PLATFORM_ADMIN` — all 39

Including the six nobody else holds:

```
audit:read   camp:approve   facility:verify
hospital:verify   org:approve   org:read   org:suspend
role:assign   system:admin
```

---

## 4. The 39 permissions, grouped

### Inventory — 7

| Permission | Grants |
|---|---|
| `inventory:read:public` | the availability matrix anyone may see |
| `inventory:read:detailed` | individual batches, expiry dates, audit trail |
| `inventory:write` | add, deduct |
| `inventory:correct` | rewrite a past figure |
| `inventory:quarantine` | take stock out of use |
| `inventory:verify` | **independently attest** to a figure |
| `inventory:ingest:api` | accept machine-fed data |

**Seven permissions for one feature.** That is the honesty rules expressed as
authorisation: reading publicly, reading in detail, recording, correcting,
quarantining, verifying and ingesting are seven different acts of trust.

### Reservations — 3

| Permission | Who |
|---|---|
| `reservation:create` | the requester |
| `reservation:manage:own` | the requester, on **their own** hold |
| `reservation:manage` | the **blood bank**, deciding and fulfilling |

**The `:own` suffix is the whole authorisation model in miniature** — and both
are further constrained by the organization scoping check.

### Emergency — 5

`emergency:create`, `emergency:read:own`, `emergency:respond`,
`emergency:cancel`, **`emergency:certify:priority`**

### Camps and donations — 8

`camp:read`, `camp:create`, `camp:manage`, `camp:approve`,
`camp:staff:assign`, `camp:checkin`, `donation:record`, `donation:verify`

### Facilities — 3

`facility:read`, `facility:write`, `facility:verify`

### Alerts, profile, registration — 5

`alert:create`, `alert:manage:own`, `profile:manage:own`,
`registration:create`, `registration:manage:own`

### Organizations and platform — 8

`org:read`, `org:approve`, `org:suspend`, `hospital:verify`, `user:manage`,
`role:assign`, `audit:read`, `system:admin`

---

## 5. Global versus organization-scoped permissions

**A subtlety worth understanding**, because it is how the IDOR defence knows
when to apply.

`is_organization_scoped(permission)` tells the authorisation decorator whether
check 5 — organization scoping — applies.

**17 permissions are global** (not organization-scoped):

```
alert:create   audit:read   camp:approve   camp:read   emergency:create
facility:read  facility:verify   hospital:verify   inventory:read:public
org:approve    org:suspend   profile:manage:own   registration:create
reservation:create   role:assign   system:admin   user:manage
```

**The remaining 22 are organization-scoped.** For example:

| Permission | Scoped? |
|---|---|
| `inventory:read:public` | **no** — anyone may see public availability |
| `inventory:read:detailed` | **yes** — only your own facility's batches |
| `inventory:write` | **yes** |
| `inventory:verify` | **yes** |

**The pattern:** public reads are global; anything touching a specific
organization's records is scoped.

**Verified live:** a blood bank admin listing reservations for **their own**
facility gets **200**; the same admin on **another** facility's queue gets
**403**.

---

## 6. How a role is assigned

**Not in Cognito.** The pool has **zero groups and zero custom attributes**.

```
1. A user signs up          -> Cognito account; the baseline PUBLIC principal
2. They request a role      -> POST /me/organization-request
                               creates a PENDING request
3. A platform admin reviews -> POST /admin/organizations/{id}/status
4. The role is stored       -> lifelink-dev-organizations table
5. Read on EVERY request    -> check 2 of the five authorisation checks
```

**Why this matters:**

- **Immediate revocation.** A role in a one-hour token stays effective for up
  to an hour. A role read from the database is revoked on the **next request**.
- **No self-elevation.** `PATCH /me` updates the **display name only**. You
  cannot give yourself a role; you can only *request* one.

**Self-service role elevation is the most obvious privilege-escalation path in
a system like this, and it is closed by design.**
`backend/tests/unit/test_profile_and_org_requests.py` tests exactly that.

---

## 7. Account status — the third check

A valid token from a **suspended** account is rejected with
**`403 ACCOUNT_SUSPENDED`**, before the permission check even runs.

**Verified live** with a suspended demo account holding a freshly issued,
perfectly valid token.

**Say this:**
> "Account status is check three of five, and it runs before the permission
> check. We verified it live: a suspended account with a completely valid,
> freshly issued token gets a 403 saying the account is suspended — not a 401,
> because the token is genuine. The distinction matters: 401 means we don't
> know who you are; 403 means we know exactly who you are and the answer is no."

---

## 8. The demo accounts

Nine demo accounts exist, all on `@demo.lifelink.invalid`:

| Account | Role |
|---|---|
| `user-donor-1` | `DONOR` |
| `user-bb-staff-1` | `BLOOD_BANK_STAFF` |
| `user-bb-admin-1` | `BLOOD_BANK_ADMIN` |
| `user-hosp-staff-1` | `HOSPITAL_STAFF` |
| `user-hosp-auth-1` | `HOSPITAL_AUTHORIZER` |
| `user-camp-org-1` | `CAMP_ORGANIZER` |
| `user-admin-1` | `PLATFORM_ADMIN` |
| `user-suspended-1` | suspended — **so the 403 path is demonstrable** |
| `jit-newuser-1` | a fresh account with no role |

**`.invalid` is a reserved top-level domain that can never resolve**, so a demo
address cannot accidentally email a real person. A small detail, and a
deliberate one.

> **Privacy:** the pool also contains **two real personal email addresses**. Do
> not read them aloud or screenshot the user list.

---

## 9. Spoken answers

### "What are the user roles?" — 30 seconds
> "Ten roles and 39 permissions. There's a public baseline, a donor, two blood
> bank roles, three hospital roles, two camp roles, and a platform admin who has
> everything. The permissions are fine-grained on purpose — inventory alone has
> seven, because recording stock, correcting it, quarantining it and
> independently verifying it are four different acts of trust."

### 1–2 minutes
> "The role design follows trust rather than seniority, and there are two places
> that shows.
>
> Blood bank staff can quarantine stock — take it out of use — because that's a
> safety action and it should never need a manager's approval. But they can't
> mark stock as *verified*, because verifying is attesting that you checked it
> independently, which is a higher bar than recording it. That's a separate
> permission held only by the admin.
>
> Similarly, hospital staff can raise urgent requests, but certifying clinical
> priority is a separate permission held by only three of the ten roles. That's
> a medical judgement — the system records who made it and never makes it
> itself. We verified live that a donor trying to certify gets a 403.
>
> And none of this is in Cognito. There are no Cognito groups and no custom
> attributes; roles live in DynamoDB and are read on every single request. That
> means revoking someone's role takes effect on their next request rather than
> up to an hour later when their token expires. A user also can't elevate
> themselves — `PATCH /me` only changes a display name; getting a role means
> requesting one and a platform admin approving it."

---

## 10. Cross-references

- [../03_REPOSITORY_AND_CODE/04_API_And_Handler_Mapping.md](../03_REPOSITORY_AND_CODE/04_API_And_Handler_Mapping.md) — every route's permission
- [../08_SECURITY_AND_RELIABILITY/02_IAM_Authorization_Flow.md](../08_SECURITY_AND_RELIABILITY/02_IAM_Authorization_Flow.md)
- [../08_SECURITY_AND_RELIABILITY/04_User_And_Facility_Isolation.md](../08_SECURITY_AND_RELIABILITY/04_User_And_Facility_Isolation.md)
- [../06_FEATURE_IMPLEMENTATION/](../06_FEATURE_IMPLEMENTATION/) — each feature in depth
