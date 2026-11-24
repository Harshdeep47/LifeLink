# LifeLink — Final Demo Readiness Report

**15 November 2026.**
Frontend: **https://d324z37do52g8f.cloudfront.net**
API: `https://uk6itz2a5b.execute-api.ap-southeast-2.amazonaws.com/dev`
Stack: `lifelink-dev` · Account 426150327442 · ap-southeast-2

Statuses used: **VERIFIED LIVE** · **IMPLEMENTED — NEEDS BROWSER
VERIFICATION** · **BLOCKED BY AWS ACCOUNT POLICY** · **NOT IMPLEMENTED**.

Nothing is marked VERIFIED LIVE on the strength of a unit test.

---

## 1. Root causes

| # | Problem | Root cause |
|---|---|---|
| 1 | `0.0 km` to "Rajindra Civil Blood Centre" from a user who never shared their location | **Two faults.** Twelve facilities were seeded with an offset of exactly `(0.0, 0.0)` from their city centroid, so they sat *on* it — and the interface's default origin is the Patiala centroid. The distance was arithmetically correct and the data was wrong. |
| 2 | "Patiala (default)" read as the user's location | The origin had no provenance. One label served default, manual and GPS, so nothing distinguished "nobody told us" from "we located you". |
| 3 | Map showed no basemap | `AWS::Location::APIKey` is denied by the account SCP, so no tile credential existed. |
| 4 | A blood-bank admin got **403 on its own profile** | `/me` required `registration:manage:own` — a *donor* permission guarding a capability every signed-in user has. Found while verifying this sprint. |
| 5 | Registration produced a donor account with a uuid for a name | No sign-up form existed. Accounts came from Cognito's hosted pages, and provisioning had no name to read. |
| 6 | Sign-out was immediate | No confirmation step. |

---

## 2. Location services

### 2.1 The zero-distance bug — **VERIFIED LIVE**

Fixed in the data, not the display. Each facility now takes a deterministic
offset from its city centre derived from a SHA-256 hash of its own facility id,
with a floor of 0.008° (~0.9 km) so nothing can round to zero. Derived from the
id rather than the shared RNG, so a facility does not move when unrelated seed
data is added or reordered.

**Live, from the default Patiala origin:**

```
Urban Estate Donor Centre (DEMO)      0.89 km  AVAILABLE
Rajindra Civil Blood Centre (DEMO)    3.65 km  PARTIAL
Patiala Community Blood Bank (DEMO)   6.42 km  AVAILABLE
Rajpura Collection Centre (DEMO)     24.77 km  UNAVAILABLE
Nabha Rural Blood Unit (DEMO)        25.01 km  UNAVAILABLE
zero-distance facilities: NONE
```

**From Chandigarh instead** — a completely different ordering, which is the
proof that distance follows the selected origin rather than row order:

```
Sector 16 Regional Blood Centre     1.17 km
Tricity Voluntary Blood Bank        5.87 km
Mohali Satellite Centre             8.60 km
Zirakpur Transfusion Point         11.16 km
```

Re-seeding updated 16 facility rows and added nothing. Organizations,
inventory, camps, reservations and users were untouched — this was the
"specific, justified bug" that warranted modifying existing rows. 24/24
coverage checks passed afterwards.

### 2.2 Origin provenance — **IMPLEMENTED — NEEDS BROWSER VERIFICATION**

The origin now carries where it came from, and the three cases are visually
and verbally distinct (`components/OriginIndicator.jsx`):

| Source | Heading | Appearance |
|---|---|---|
| `default` | **Default search location** — "Showing results near Patiala because no location has been set." | Grey, hollow diamond |
| `manual` | **Searching a place you chose** — names the place | Navy, crosshair |
| `gps` | **Using your current location** — plus accuracy in metres | Green, filled circle |

Only the GPS state claims to be the user's location, and it is set **only
after valid coordinates arrive**. A denied, unavailable or timed-out lookup
leaves the origin untouched and the indicator still saying *default*, with the
error shown beneath it. The duplicate coordinate readout and geolocation
message elsewhere on the page were removed so nothing can contradict the
indicator.

Both discovery pages use the same component and the same `PlaceSearch`, so
camps and blood banks share one origin mechanism.

`useGeolocation` already handled permission-denied, position-unavailable,
timeout and unsupported-browser separately, and reports poor accuracy; that
code was already correct and is unchanged.

### 2.3 Nearest highlighting — **IMPLEMENTED — NEEDS BROWSER VERIFICATION**

- Nearest is computed from the API's returned distances with `reduce`, never
  from row order.
- Only among results that could **actually supply**: `AVAILABLE`, `PARTIAL` or
  `UNKNOWN`. A facility 200 m away with nothing in stock is not the nearest
  useful option, and labelling it "Nearest" would send someone to the wrong
  place.
- `UNKNOWN` is deliberately eligible. A facility that never reported may well
  have stock — that is the entire reason it shows UNKNOWN rather than zero — so
  it ranks below a confirmed match but is not excluded.
- A **Nearest** pill plus a crimson left border on the card.
- Camps get the same treatment, restricted to `UPCOMING`/`ONGOING`, because a
  completed camp nearby is not attendable.
- Sort control: **Recommended** (the backend's weighted ranking), **Distance**,
  **Availability** — with availability ties broken by distance, so equal
  availability still reads nearest-first.

### 2.4 Map basemap — **IMPLEMENTED — NEEDS BROWSER VERIFICATION**

Your option **C**. `AWS::Location::APIKey` stays denied and was not retried.
The basemap is now OpenStreetMap standard raster tiles, which need no
credential and no new dependency.

The obligations that choice carries are met: attribution is displayed and
MapLibre's attribution control left on; `maxzoom` is capped and nothing
prefetches, so tiles are fetched only as a user pans; and it is recorded as a
demonstration basemap, not a production tile solution, in
`KNOWN_LIMITATIONS.md`. If a signed Amazon Location style URL ever becomes
available, `VITE_MAP_STYLE_URL` takes precedence automatically.

Also fixed: `map.on('error')` previously collapsed the whole map to the list
on **any** error, including a single 404 tile. Only a style-load failure is
fatal now. A `'load'` event sets a flag, so "Loading map…" is shown until
tiles genuinely arrive rather than inferring success from the component
mounting.

The map shows: origin marker (navy ●), blood banks (crimson ◆), camps (teal
▲) — **distinct in shape as well as colour**, because colour alone is not a
distinction for a colour-blind reader — a legend naming each, popups with
name, locality, availability and distance (all values HTML-escaped),
click-through to details, and re-centring when the origin moves.

### 2.5 Road distance and directions — **NOT IMPLEMENTED (honest fallback)**

`GET /facilities/{id}/route` exists and calls Amazon Location server-side.
Results carry `roadKm: null`, `etaMinutes: null`, `routingAvailable: false`
unless routing genuinely succeeds. Every distance shown is labelled
**straight-line**. No road distance or ETA is fabricated. Drawing a route on
the map is not implemented.

---

## 3. Authentication and accounts

### 3.1 Profile access for non-donor roles — **VERIFIED LIVE**

New permission `profile:manage:own`, held by all ten roles except the
anonymous `PUBLIC` role, now guards `/me`, `PATCH /me` and
`/me/organization-request`. Reading your own name is not a donor capability.

```
GET /me as BLOOD_BANK_ADMIN → 200
  name: Blood Bank Admin (DEMO)  roles: ['BLOOD_BANK_ADMIN']
  org: org-bb-patiala-1          permissions: 13
own facility batches      → 200
OTHER org facility        → 403
facility reservations     → 200
```

### 3.2 Registration — **IMPLEMENTED — NEEDS BROWSER VERIFICATION**

`/sign-up`, with Sign in / Create account tabs on both pages. Three steps —
details, emailed code, done — kept as three screens rather than one form that
silently becomes a code prompt.

Collects full name, email, password, confirmation and explicit acceptance of
the terms and privacy notice. Password policy is checked client-side first, so
a user is told before a round trip instead of meeting Cognito's error built
from a regex. The name goes into the standard Cognito `name` attribute, which
is what provisioning reads.

Implemented with `fetch` against the Cognito JSON API, **not** by adding the
AWS SDK: `SignUp`, `ConfirmSignUp`, `ResendConfirmationCode`,
`ForgotPassword` and `ConfirmForgotPassword` are unauthenticated for a public
app client, so they need no signing. Sign-*in* deliberately stays with the
hosted UI and PKCE — that flow works and keeps the password exchange off this
origin. **No new dependency was added.**

`UserNotFoundException` on a password reset is deliberately answered vaguely
("if that address has an account, a code has been sent") rather than
confirming whether an address is registered.

### 3.3 Account types without escalation — **VERIFIED LIVE**

Choosing "Blood bank" or "Hospital" creates an ordinary donor account and
records a **pending** request. Verified against the deployed API:

```
POST /me/organization-request {"requestedType":"BLOOD_BANK", ...}
  → status: PENDING   type: BLOOD_BANK   org: Demo Civil Blood Centre

GET /me afterwards
  roles: ['DONOR']   org: None   pending: PENDING
blood bank batches       → 403
facility reservations    → 403

POST .../organization-request {"requestedType":"PLATFORM_ADMIN"}
  → 400 VALIDATION_ERROR, rule: UNKNOWN_REQUESTED_TYPE
```

And the escalation attempt that matters most:

```
PATCH /me {"displayName":"Attacker","roles":["PLATFORM_ADMIN"],
           "organizationId":"org-bb-patiala-1","accountStatus":"ACTIVE"}
  → 200, displayName changed
GET /me → roles: ['DONOR']  org: None  permissions: 12
```

The injected `roles`, `organizationId` and `accountStatus` were ignored
entirely. Two independent reasons: the handler reads only `displayName` from
the body, and the repository's update expression names only `displayName`.
23 tests assert that shape, inspecting the functions' **executable bodies**
rather than their source text — the first version of those tests passed on a
docstring that merely *said* roles were not written.

An existing verified institutional account is never downgraded: provisioning
is skipped entirely when a profile exists.

### 3.4 Profile page — **IMPLEMENTED — NEEDS BROWSER VERIFICATION**

`/profile`: name, email, account type, status, display-name editing, request
status, and the institutional request form. The Cognito subject is never
displayed. If the display name is missing or still equals the subject, the page
says "Not set yet — add one below" rather than showing a uuid as someone's
identity.

### 3.5 Sign-out confirmation — **IMPLEMENTED — NEEDS BROWSER VERIFICATION**

A modal asking "Are you sure you want to sign out?" with Cancel (focused by
default) and Sign out. Cancel leaves the session intact; Sign out uses the
existing Cognito `/logout` redirect, so the pool session cookie is cleared too
— without that, the next sign-in skips the form and looks as though sign-out
never happened.

---

## 4. Reservations — **VERIFIED LIVE (previous sprint), unchanged**

Verified live earlier today and not modified since: holding 7 of 9 units moved
a facility from `AVAILABLE units=9` to `PARTIAL units=2 reserved=7` in public
search, and cancelling restored it. Guards fire: `ALREADY_HOLDING`,
`INSUFFICIENT_UNRESERVED_STOCK` (reporting what *is* free),
`INVENTORY_NOT_REPORTED`. Atomic creation, idempotent retries, no double
release, and active expiry sweeping remain as built.

**Still missing — NOT IMPLEMENTED:** the blood-bank manager's reservation
screen. The API is complete, authorized and organization-scoped
(`GET`/`POST /facilities/{id}/reservations`, `/decision`, `/fulfil`, all
verified 200 for the owning org and 403 cross-org), but staff have no UI, so
`CONFIRMED` and `FULFILLED` are reachable only through the API. This is the
largest remaining gap and I did not reach it.

---

## 5. Files changed

**Backend**
- `appcore/rbac.py` — `PROFILE_MANAGE_OWN` added to all ten roles
- `handlers/api.py` — `PATCH /me`, `POST /me/organization-request`; `/me` now
  returns email and pending request; permissions switched
- `repositories/identity_repo.py` — `update_display_name`,
  `record_organization_request`
- `tests/unit/test_profile_and_org_requests.py` — 23 new tests

**Frontend**
- `components/OriginIndicator.jsx` — new
- `components/PlaceSearch.jsx` — shared manual search
- `components/FacilityMap.jsx` — OSM basemap, legend, loading state, precise
  error handling, camp/origin markers, popups, re-centring
- `components/FacilityMap.css`, `components/Layout.css`, `components/ui.css`,
  `features/discovery/FindBloodPage.css`
- `components/Layout.jsx` — sign-out confirmation, sign-up link, no uuid names
- `components/ui.jsx` — `Card` accepts `className`
- `auth/cognitoSignUp.js` — new
- `auth/cognito.js` — exposes `poolId`
- `features/account/SignUpPage.jsx`, `ProfilePage.jsx` — new
- `features/account/SignInPage.jsx` — tabs
- `features/discovery/FindBloodPage.jsx` — origin provenance, nearest, sort
- `features/camps/CampsPage.jsx` — origin provenance, map, nearest, distance

**Scripts / infra**
- `scripts/seed_demo.py` — deterministic facility offsets
- `scripts/deploy_frontend.py` — injects pool id and map style
- `infrastructure/template.yaml` — the denied API key removed, documented

---

## 6. Tests and gates

| Gate | Result |
|---|---|
| Backend | **547 passed** |
| Frontend | **80 passed** |
| OpenAPI freshness | matches (49 paths, 58 operations) |
| `cfn-lint` | clean |
| `sam validate --lint` | valid |
| Dependency audit | **PASSED** — nothing shipped has a known vulnerability; 8 dev-only |

**627 automated tests.** Three failed mid-sprint because my own tests still
asserted the old `/me` permission; both were corrected.

---

## 7. AWS resources and cost

- **No new resources created.** The only attempt
  (`AWS::Location::APIKey`, free) was denied by SCP in the previous sprint and
  removed; it was **not retried**.
- Fixed cost unchanged: **$0.40/month** (Secrets Manager).
- No table reset. 16 facility rows updated (the coordinate bug); 0 rows added
  or deleted elsewhere. No organization, inventory, camp, reservation or user
  record was deleted.
- No secret in the frontend bundle: every injected value (API base, user pool
  id, public app client id, hosted-UI domain) is a public identifier.
- Nothing pushed to GitHub.

---

## 8. Remaining limitations

1. **BLOCKED BY AWS ACCOUNT POLICY** — Amazon Location tiles. The basemap is
   OpenStreetMap for this demonstration; a route cannot be drawn on the map.
2. **NOT IMPLEMENTED** — blood-bank reservation management UI (API complete).
3. **NOT IMPLEMENTED** — road distance and ETA display; straight-line only,
   labelled as such.
4. **Camp discovery is capped at 20 km**, reported as `effectiveRadiusKm`. The
   real fix is a second, coarser camp geohash index plus a backfill.
5. Forgot-password is implemented in `cognitoSignUp.js` but **has no page**;
   it is reachable through Cognito's hosted UI.
6. Alarms have never fired; point-in-time restore untested; no load testing.
7. The three PDF books predate all of today's work.
8. The compatibility reference remains clinically unreviewed. **Not for
   clinical use.**

---

## 9. Manual browser checks you must perform

I cannot drive a browser from here. Everything above marked VERIFIED LIVE was
checked by HTTP against the deployed API; the rest needs your eyes.

Open **https://d324z37do52g8f.cloudfront.net**

| # | Step | Expected |
|---|---|---|
| 1 | Open **Find blood** without signing in | Origin box reads **"Default search location"** with the explanation — *not* "Patiala (default)", and nothing claims it is your location |
| 2 | Check the nearest result | **Urban Estate Donor Centre, 0.89 km**, with a **Nearest** pill. Nothing shows 0.0 km |
| 3 | Click **Use my location**, allow | Box turns green: **"Using your current location"** with accuracy in metres; results and distances refresh; map re-centres |
| 4 | Click **Use my location**, **deny** | Box stays grey on **"Default search location"** and shows the denial message. It must **not** claim a location |
| 5 | Type "Chandigarh" in **Or search a place**, pick a result | Box turns navy, names the place, distances recalculate |
| 6 | Look at the map | OpenStreetMap basemap visible with attribution; navy ●, crimson ◆, teal ▲ markers; legend bottom-left |
| 7 | Click a marker | Popup with name, locality, availability, straight-line distance. Clicking opens details |
| 8 | Open **Donation camps** | 6 camps near Patiala, 0.4–17.1 km, nearest attendable one badged, sorted nearest-first |
| 9 | **Create account** → register with a real name, enter the emailed code | Account created; sign in; header shows **your name**, never a uuid |
| 10 | Open **My profile** | Name, email, "Individual / Donor", status. Edit the display name and save |
| 11 | Submit an institutional access request | Shows **pending**; you still cannot open a blood bank dashboard |
| 12 | Click **Sign out** | Confirmation dialog. **Cancel** keeps you signed in; **Sign out** returns you signed out |
| 13 | Reserve units on a facility, then search again | Available units drop and `reserved` appears; cancel restores them |

**Step 3 is the one I most need you to try** — browser geolocation is the only
part of this sprint I have no way to exercise.

---

## 10. Demonstration steps

```bash
cd d:/LifeLink
set AWS_PROFILE=lifelink

curl -s https://uk6itz2a5b.execute-api.ap-southeast-2.amazonaws.com/dev/health
python scripts/seed_cloud.py --stack lifelink-dev --verify-only    # expect 24/24

# Fresh token LAST (1-hour lifetime); password in .local-keys/demo-logins.txt
python scripts/provision_demo_logins.py --stack lifelink-dev ^
  --password "<from that file>" --token user-donor-1

start https://d324z37do52g8f.cloudfront.net
```

**The walkthrough:**

1. **Find blood** → O−, PRBC, 4 units, 30 km. Point at the origin box: *"it
   says default, because it has not located me — and it will not pretend
   otherwise."*
2. Read the order out: the **Nearest** badge is on Urban Estate at 0.89 km with
   9 units, fresh and verified. Rajindra Civil is closer in the city but holds
   1 of 4 units, so it is not the nearest *useful* option.
3. Widen to 60 km → **Tricity Voluntary** shows *Not reported* with **no
   number**. Unknown is not zero.
4. Click **Use my location** → the box turns green and distances change.
5. **Donation camps** → 6 camps, 0.4–17.1 km, nearest badged. Search
   "Chandigarh" to move the origin; a different five appear.
6. Open a facility → **Temporary reservation** → hold 7 of 9 units. Search
   again: *Partial, 2 units, 7 reserved.* Cancel; they return.
7. **Create account** with your own name, sign in, open **My profile**, request
   blood-bank access → **pending**, and the dashboard stays shut.
8. **Sign out** → the confirmation dialog.
9. Close on the limits: map tiles are OpenStreetMap because the account blocks
   Amazon Location keys; distances are straight-line; the compatibility
   reference is unreviewed; every record is synthetic.
