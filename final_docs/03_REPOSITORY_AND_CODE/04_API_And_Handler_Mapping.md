# API and Handler Mapping

**The complete, verified mapping of all 58 routes** to their handler function,
required permission, and whether anonymous callers are allowed.

This table was produced by importing `build_router()` from
`backend/src/handlers/api.py` and enumerating the route table, so it is the
implementation itself rather than a description of it.

---

## 1. How to read this

| Column | Meaning |
|---|---|
| Method / Path | the route as declared, before the `/dev` stage prefix is added |
| Handler | the function in `backend/src/handlers/api.py` |
| Permission | the permission `@requires(...)` demands, from `backend/src/appcore/rbac.py` |
| Anon | `yes` means an unauthenticated caller is served as the `PUBLIC` principal |

**Note the design:** an anonymous route *still declares a permission*.
Anonymity is not a bypass — it is a principal (`PUBLIC`) that holds exactly 4
of the 39 permissions. That is why `GET /facilities` can be anonymous and
`GET /facilities/{id}/batches` cannot: `PUBLIC` holds `facility:read` but not
`inventory:read:detailed`.

---

## 2. Platform (2 routes)

| Method | Path | Handler | Permission | Anon |
|---|---|---|---|---|
| GET | `/health` | `health` | — | **yes** |
| GET | `/reference` | `reference_data` | — | **yes** |

These two are the only routes with **no** permission at all. `/reference`
returns enumerations (blood groups, components, statuses) so the frontend never
hard-codes them.

---

## 3. Feature 1 — Inventory (8 routes)

| Method | Path | Handler | Permission | Anon |
|---|---|---|---|---|
| GET | `/facilities/{facilityId}/batches` | `list_batches` | `inventory:read:detailed` | no |
| POST | `/facilities/{facilityId}/batches` | `create_batch` | `inventory:write` | no |
| GET | `/facilities/{facilityId}/batches/{batchId}` | `get_batch` | `inventory:read:detailed` | no |
| POST | `/facilities/{facilityId}/batches/{batchId}/adjust` | `adjust_batch` | `inventory:write` | no |
| GET | `/facilities/{facilityId}/batches/{batchId}/audit` | `batch_audit` | `inventory:read:detailed` | no |
| POST | `/facilities/{facilityId}/batches/{batchId}/verify` | `verify_batch` | **`inventory:verify`** | no |
| POST | `/facilities/{facilityId}/inventory/ingest` | `ingest_inventory` | `inventory:ingest:api` | no |
| GET | `/facilities/{facilityId}/availability` | `facility_availability` | `inventory:read:public` | **yes** |

**The permission split is the teaching point.** There are three different read
permissions and four different write permissions for inventory:

- `inventory:read:public` — the availability matrix anyone can see
- `inventory:read:detailed` — individual batches, expiry dates, audit trail
- `inventory:write` — add, deduct, correct
- `inventory:verify` — **separate**, because verifying is not updating
- `inventory:quarantine`, `inventory:correct` — further separations
- `inventory:ingest:api` — machine ingestion from an external system

`verify_batch` needing its own permission is ADR-0003 in action: **updated is
not verified**. Staff can update stock; verifying it independently is a
different, more trusted act.

---

## 4. Feature 1 — Availability alerts (4 routes)

| Method | Path | Handler | Permission | Anon |
|---|---|---|---|---|
| POST | `/alerts` | `create_alert` | `alert:create` | no |
| GET | `/alerts` | `list_alerts` | `alert:manage:own` | no |
| GET | `/alerts/{alertId}` | `get_alert` | `alert:manage:own` | no |
| DELETE | `/alerts/{alertId}` | `cancel_alert` | `alert:manage:own` | no |

Alerts are **informational only** (ADR-0017) — an alert never holds units. The
`:own` suffix in the permission is the signal that the record must belong to
the caller.

---

## 5. Feature 2 — Discovery, location and reservations (10 routes)

| Method | Path | Handler | Permission | Anon |
|---|---|---|---|---|
| GET | `/facilities` | `search_facilities` | `facility:read` | **yes** |
| GET | `/facilities/{facilityId}` | `get_facility` | `facility:read` | **yes** |
| GET | `/facilities/{facilityId}/route` | `route_to_facility` | `facility:read` | **yes** |
| GET | `/geocode` | `geocode` | `facility:read` | **yes** |
| POST | `/facilities/{facilityId}/reservations` | `request_reservation` | `reservation:create` | no |
| GET | `/facilities/{facilityId}/reservations` | `list_facility_reservations` | **`reservation:manage`** | no |
| DELETE | `/facilities/{facilityId}/reservations/{reservationId}` | `cancel_reservation` | `reservation:manage:own` | no |
| POST | `/facilities/{facilityId}/reservations/{reservationId}/decision` | `decide_reservation` | `reservation:manage` | no |
| POST | `/facilities/{facilityId}/reservations/{reservationId}/fulfil` | `fulfil_reservation` | `reservation:manage` | no |
| GET | `/me/reservations` | `list_my_reservations` | `reservation:manage:own` | no |

**The `:own` versus bare distinction is the whole authorization model in
miniature:**

- `reservation:manage:own` — the **requester** cancelling their own hold
- `reservation:manage` — the **blood bank** deciding on, or fulfilling,
  reservations against its own facility

Both are further constrained by the organization scoping check, which is why a
blood bank admin can list reservations for *their* facility (verified: 200) but
not another facility's (verified: **403**).

---

## 6. Feature 3 — Camps and donors (16 routes)

| Method | Path | Handler | Permission | Anon |
|---|---|---|---|---|
| GET | `/camps` | `search_camps` | `camp:read` | **yes** |
| GET | `/camps/{campId}` | `get_camp` | `camp:read` | **yes** |
| POST | `/camps` | `create_camp` | `camp:create` | no |
| GET | `/camps/mine` | `list_organizer_camps` | `camp:manage` | no |
| POST | `/camps/{campId}/approve` | `approve_camp` | `camp:approve` | no |
| POST | `/camps/{campId}/cancel` | `cancel_camp` | `camp:manage` | no |
| POST | `/camps/{campId}/staff` | `assign_camp_staff` | `camp:staff:assign` | no |
| POST | `/camps/{campId}/register` | `register_for_camp` | `registration:create` | no |
| DELETE | `/camps/{campId}/register` | `cancel_registration` | `registration:manage:own` | no |
| POST | `/camps/{campId}/checkin` | `check_in_donor` | `camp:checkin` | no |
| POST | `/camps/{campId}/donations` | `record_donation` | `donation:record` | no |
| POST | `/camps/{campId}/donations/verify` | `verify_donation` | **`donation:verify`** | no |
| GET | `/me/registrations` | `my_registrations` | `registration:manage:own` | no |
| GET | `/me/donations` | `donation_history` | `registration:manage:own` | no |
| GET | `/me/donations/{donationId}/certificate` | `donation_certificate` | `registration:manage:own` | no |
| GET | `/me/donor-profile` | `donor_profile` | `registration:manage:own` | no |

**Note `camp:approve` is separate from `camp:manage`.** An organizer manages
their own camp; approving it is a platform-admin act. Checking in a donor,
recording a donation, and *verifying* a donation are three different
permissions, so a camp volunteer can check people in without being able to
credit donation impact.

---

## 7. Feature 4 — Emergency coordination (8 routes)

| Method | Path | Handler | Permission | Anon |
|---|---|---|---|---|
| POST | `/emergency-requests` | `create_emergency_request` | `emergency:create` | no |
| GET | `/emergency-requests` | `list_emergency_requests` | `emergency:read:own` | no |
| GET | `/emergency-requests/{requestId}` | `get_emergency_request` | `emergency:read:own` | no |
| POST | `/emergency-requests/{requestId}/cancel` | `cancel_emergency_request` | `emergency:cancel` | no |
| POST | `/emergency-requests/{requestId}/certify` | `certify_priority` | **`emergency:certify:priority`** | no |
| POST | `/emergency-requests/{requestId}/confirm` | `confirm_availability` | `emergency:certify:priority` | no |
| POST | `/emergency-requests/{requestId}/respond` | `respond_to_request` | `emergency:respond` | no |
| GET | `/emergency-requests/provider-queue` | `provider_queue` | `emergency:respond` | no |

**`emergency:certify:priority` is the most restricted permission in the
system.** Only `HOSPITAL_AUTHORIZER`, `HOSPITAL_ADMIN` and `PLATFORM_ADMIN`
hold it. Verified live: a donor attempting to certify receives **403**, and a
donor attempting to read the provider queue also receives **403**.

Why so strict? Because certifying clinical priority is a medical judgement. The
system records who certified it and never makes the judgement itself.

---

## 8. Feature 6 — Account, notifications and administration (10 routes)

| Method | Path | Handler | Permission | Anon |
|---|---|---|---|---|
| GET | `/me` | `whoami` | `profile:manage:own` | no |
| PATCH | `/me` | `update_my_profile` | `profile:manage:own` | no |
| POST | `/me/organization-request` | `request_organization_access` | `profile:manage:own` | no |
| GET | `/me/notifications` | `list_notifications` | `alert:manage:own` | no |
| GET | `/me/notification-preferences` | `get_notification_preferences` | `alert:manage:own` | no |
| PUT | `/me/notification-preferences` | `update_notification_preferences` | `alert:manage:own` | no |
| GET | `/admin/audit` | `read_audit` | **`audit:read`** | no |
| GET | `/admin/organizations/pending` | `list_pending_organizations` | `org:read` | no |
| POST | `/admin/organizations/{organizationId}/status` | `set_organization_status` | `hospital:verify` | no |
| POST | `/admin/users/{userId}/status` | `set_account_status` | **`user:manage`** | no |

`GET /me` is the most useful route for a demonstration: it returns the current
principal **and their effective permissions**, so you can show the
authorization model with one request.

`PATCH /me` updates the **display name only** — a user cannot change their own
role or organization through it. That is deliberate: self-service role
elevation is the most obvious privilege-escalation path in a system like this.
Requesting an institutional role goes through
`POST /me/organization-request`, which creates a **pending** request that a
platform admin must verify.

---

## 9. Frontend to route mapping

Every API call lives in `frontend/src/api/client.js` as one entry in the `api`
object. The chain for any feature is:

```
React component  ->  api.<method>()  ->  client.js request()  ->  HTTP API  ->  handler
```

| Frontend page | `api` method | Route |
|---|---|---|
| `features/discovery/FindBloodPage.jsx` | `searchFacilities` | `GET /facilities` |
| `features/discovery/FacilityDetailPage.jsx` | `getFacility`, `facilityAvailability` | `GET /facilities/{id}`, `/availability` |
| `features/discovery/ReservationPanel.jsx` | `requestReservation` | `POST /facilities/{id}/reservations` |
| `features/reservations/ReservationQueue.jsx` | `facilityReservations`, `decideReservation`, `fulfilReservation` | the facility-side reservation routes |
| `features/dashboards/BloodBankDashboard.jsx` | `listBatches`, `createBatch`, `adjustBatch`, `verifyBatch` | the inventory routes |
| `features/camps/CampsPage.jsx` | `searchCamps` | `GET /camps` |
| `features/camps/CampDetailPage.jsx` | `getCamp`, `registerForCamp` | `GET /camps/{id}`, `POST .../register` |
| `features/emergency/EmergencyRequestPage.jsx` | `createEmergencyRequest` | `POST /emergency-requests` |
| `features/emergency/RequestTrackingPage.jsx` | `getEmergencyRequest` | `GET /emergency-requests/{id}` |
| `features/alerts/AlertsPage.jsx` | `createAlert`, `listAlerts`, `cancelAlert` | the alert routes |
| `features/account/MyActivityPage.jsx` | `myReservations`, `listEmergencyRequests` | `GET /me/reservations`, `GET /emergency-requests` |
| `features/account/ProfilePage.jsx` | `me`, `updateMyProfile` | `GET /me`, `PATCH /me` |
| `features/dashboards/AdminDashboard.jsx` | `pendingOrganizations`, `setOrganizationStatus`, `audit` | the admin routes |

---

## 10. How to find the handler for any button — the five-step method

Practise this; a teacher may ask you to do it live.

1. **Find the component.** The page is under `frontend/src/features/`. Search
   the button's visible text:
   `grep -rn "Request hold" frontend/src/`
2. **Find the `api.` call** in that component's click handler.
3. **Look up the method** in `frontend/src/api/client.js` — it names the
   method and path.
4. **Find the route** in this document's tables, which gives the handler
   function name.
5. **Open the handler** in `backend/src/handlers/api.py`:
   `grep -n "def request_reservation" backend/src/handlers/api.py`

Reverse direction works too: from a route, `grep` the path string in
`frontend/src/api/client.js` to find which page uses it.

---

## 11. A verified documentation discrepancy

`docs/openapi.json` declares `bearerAuth` security on **all 58** operations,
including `/health` — which returns **200 without a token**, verified live.
The generated OpenAPI document therefore overstates the authentication
requirement for the 9 anonymous routes.

**The route table in `backend/src/handlers/api.py` is authoritative.** The same
file's `servers` block also still describes the AWS deployment as "not
currently deployed", which is stale.

Neither was corrected, because the project is under an engineering freeze.
Both are recorded in
[../13_REFERENCE_AND_REVISION/05_Known_Limitations_And_Actual_Status.md](../13_REFERENCE_AND_REVISION/05_Known_Limitations_And_Actual_Status.md).
If a teacher spots it, the right answer is: "Good catch — the generated
document overstates it. The route table is the source of truth, and it marks
nine routes as anonymous."

---

## 12. Spoken answers

### 20–30 seconds

> "There are 58 routes, all served by one Lambda. Every route declares the
> permission it requires in the route table, and nine of them additionally
> allow anonymous callers — health, reference, facility search and detail,
> availability, routing, geocode, and camp search and detail. Even those nine
> still name a permission; an anonymous caller is just a principal with the
> four permissions the PUBLIC role holds."

### 1–2 minutes

> "The route table is the centre of the backend. Each entry has a method, a
> path, a handler function, the permission it requires, and whether anonymous
> access is allowed. Two things follow from that.
>
> First, authorization can't be forgotten. A test enumerates this table and
> fails the build if any route is missing its authorization metadata — so 'we
> didn't leave an endpoint open' is a property we check, not a claim.
>
> Second, the permission names encode the security model. `inventory:write` and
> `inventory:verify` are different permissions, because updating stock and
> independently verifying it are different acts of trust. `reservation:manage:own`
> is the requester cancelling their own hold; plain `reservation:manage` is the
> blood bank deciding on holds against its facility. And
> `emergency:certify:priority` — certifying clinical priority — is held by only
> three of the ten roles, because that's a medical judgement."

---

## 13. Cross-references

- [01_Complete_File_Structure.md](01_Complete_File_Structure.md)
- [03_Backend_Code_Walkthrough.md](03_Backend_Code_Walkthrough.md)
- [../02_SYSTEM_ARCHITECTURE/02_End_To_End_Data_Flow.md](../02_SYSTEM_ARCHITECTURE/02_End_To_End_Data_Flow.md)
- [../08_SECURITY_AND_RELIABILITY/02_IAM_Authorization_Flow.md](../08_SECURITY_AND_RELIABILITY/02_IAM_Authorization_Flow.md)
- Full API reference: `docs/API_DOCUMENTATION.md`
