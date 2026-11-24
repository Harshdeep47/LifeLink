# LifeLink — Functionality Recovery Sprint (Sprint 3)

**15 November 2026.** Live: **https://d324z37do52g8f.cloudfront.net**
API: `https://uk6itz2a5b.execute-api.ap-southeast-2.amazonaws.com/dev`

Everything below was verified against the **deployed** system. Where it was
not, it says so.

---

## 1. Root causes

| # | Defect | Root cause |
|---|---|---|
| **P0.1** | `authenticated subject has no LifeLink account` | No just-in-time provisioning. Only 8 manually linked demo subjects existed, so anyone signing up through Cognito had a verified token and no profile — a dead end, because nothing in the product could create one. |
| **P0.2** | Public discovery 401'd for signed-in users | `build_context` **raised** on any authentication failure, before `requires()` could consider `allow_anonymous`. One stale token in a tab returned 401 from blood search, facilities, camps and `/reference`. |
| **P1.1** | Map was an empty placeholder | `VITE_MAP_STYLE_URL` was never set by the deployment. The component was correct and deliberately rendered its list fallback. |
| **P1.2** | Only 1 camp near Patiala | Camps were seeded in distant cities while discovery is limited to 20 km, so almost nothing was in range. |
| **P1.3** | Manual place search missing on camps | The geocoding UI was inline in `FindBloodPage`, not shared. |

Two things reported as broken were **not** defects: browser geolocation was
fully wired (button, origin update, label, all four error modes), and
geocoding worked — both confirmed live.

---

## 2. P0.1 — Just-in-time user provisioning

A verified Cognito subject with no LifeLink profile now gets one created on its
first request: **`DONOR` role, no organization**.

That role assignment is the security property, not a convenience:

- A hospital or blood-bank role would reach other organizations' data, so it is
  never self-assigned. Those are granted by an administrator after
  verification, through the existing approval path. **Verification is not
  bypassed.**
- No organization means every organization-scoped permission check refuses by
  construction rather than by convention.
- Guarded by `attribute_not_exists`, so two concurrent first requests cannot
  create two profiles or overwrite one.
- Reached only for a token already verified against the pool's keys.
- An existing profile is **never** re-provisioned, so a real role is never
  downgraded — asserted by test.

Display name and email come from a one-time `AdminGetUser` lookup, because an
access token carries neither claim (they live on the id token, which the API
never receives). Without it a user saw their own subject uuid as their name. A
failure there does not block sign-in.

**Verified live** with a Cognito user created and deliberately left unlinked:

```
GET /me  →  200
  roles: ['DONOR']   organizationId: None   permissions: 12
GET /admin/audit                  → 403
GET /admin/organizations/pending  → 403
GET /facilities/fac-patiala-1/batches → 403
GET /me/reservations              → 200
```

**Files:** `appcore/auth.py`, `repositories/identity_repo.py`
(`provision_from_token`), `services/container.py`.

## 3. P0.2 — A bad token no longer breaks public pages

`build_context` now **captures** the authentication failure on
`RequestContext.auth_error` instead of raising. `requires()` re-raises it for
every protected route and ignores it for `allow_anonymous` routes.

Nothing was weakened. A protected route still refuses a bad token — and now
with its *real* reason, so a client is told "token has expired" rather than a
generic "authentication required".

**Verified live.** Before, with one unusable token, every one of these was
401:

| Route | With a bad token |
|---|---|
| `GET /reference` | **200** |
| `GET /facilities` | **200** |
| `GET /camps` | **200** |
| `GET /facilities/{id}/availability` | **200** |
| `GET /me` (protected) | **401**, `invalid token: Invalid crypto padding` |
| `GET /me` (no token) | **401** |

24 tests pin both halves, most of them asserting what must still fail.

## 4. P1 — Location, maps and navigation

### What was already working (confirmed, not assumed)

- **Browser geolocation**: `useGeolocation` requests real coordinates, handles
  permission-denied, unavailable, timeout and insecure-context separately, and
  reports poor accuracy. Both discovery pages call it from a "Use my location"
  button and update the origin and its label. It never claims the default
  coordinates are the user's location — the label reads "Patiala (default)"
  until a real fix arrives.
- **Geocoding**: `GET /geocode?q=Amritsar` returns real Amazon Location
  results, server-side, so search text never reaches a provider from the
  browser with an identity attached.

### What was added

- **Manual place search on the camps page**, via a new shared `PlaceSearch`
  component extracted from the blood search. Both pages now determine their
  origin the same way, so denying location permission leaves a working
  alternative on both.
- **Map markers for three things, distinguished by shape and colour**: blood
  banks (crimson diamond), donation camps (teal triangle), and the search
  origin (navy dot) so a user can see what distances are measured from. Shape
  differs as well as colour, and each popup names what it is — colour alone is
  not a distinction for a colour-blind reader.
- **Popups** showing name, locality, availability (or "Not reported") and
  straight-line distance, with all interpolated values HTML-escaped.
- **Click-through**: a facility marker selects the facility; a camp marker
  opens that camp.
- **Re-centring** when the origin moves. Previously choosing "use my location"
  updated the results while the map kept looking at the old place.
- **Camps plotted on the blood-search map too**, so one map answers both "where
  can I get blood?" and "where can I give it?". That fetch is read
  defensively — a camp failure cannot affect the blood search.

### Map tiles: blocked by the account, and this needs you

**The map still renders its facility-list fallback, not tiles.** The cause is
an account restriction, not the code.

MapLibre cannot sign an AWS request by itself, so Amazon Location tiles need
either an API key or SigV4 signing in the browser. I added an
`AWS::Location::APIKey` scoped to map reads on one map resource. CloudFormation
refused it and rolled the stack back:

```
Resource handler returned message: "Access denied for operation
'AWS::Location::APIKey'." (HandlerErrorCode: AccessDenied)
```

The managed service control policy on this account type does not permit
Location API keys. I removed the resource and redeployed; **the P0 fixes
survived the rollback and were re-verified live afterwards.**

Two ways forward, both needing your decision:

1. **Request the restriction be lifted** (AWS Settings → activate advanced
   features, or a support request for `geo:CreateKey`). Then one deploy sets
   the style URL and the map renders — all the marker, popup and
   click-through code is already in place and ships today.
2. **Sign tile requests in the browser** through the existing Cognito identity
   pool, which needs three new npm packages (`@aws-sdk/client-cognito-identity`,
   `@aws-sdk/credential-providers`, `@aws/amazon-location-utilities-auth-helper`).
   I did not add these unilaterally at this hour: they enlarge the bundle
   noticeably and introduce new supply-chain surface into a dependency audit
   that currently reports zero shipped vulnerabilities.

Until then the fallback is genuinely usable — it lists every facility with its
locality and distance, and selecting one works — but it is a list, not a map,
and I am not going to call it a map.

### Routing and directions

`GET /facilities/{id}/route` is implemented server-side via Amazon Location.
When routing fails the response reports road distance as **unavailable** rather
than substituting the straight line, and discovery is unaffected. Travel times
are never fabricated. Drawing the returned route *on* the map depends on tiles
rendering, so it is blocked with the map.

## 5. P1 — Camp data and distances

**31 camps** seeded (23 new), across Patiala, Sanaur, Bahadurgarh, Devigarh,
Ghanaur, Shambhu, Bhadson, Patran, Chandigarh, Mohali, Panchkula, Kharar,
Dera Bassi, Rajpura, Nabha, Ambala, Ludhiana, Jalandhar, Amritsar and
Bathinda — with `UPCOMING`, `ONGOING`, `COMPLETED`, `CANCELLED`,
`PENDING_APPROVAL` and `REJECTED` states, varied capacities (55–180) and dates
from 20 days past to 20 days ahead.

The localities near Patiala were the point: camp discovery is limited to 20 km,
so seeding only distant cities left the feature looking empty.

**Verified live** — distances are distinct and correct:

```
camps near Patiala (20 km): 6 results
  Patiala Railway Colony Camp     ONGOING    0.4 km
  Thapar Campus Drive             UPCOMING   0.7 km
  Patiala University Blood Drive  UPCOMING   1.2 km
  Bahadurgarh Fort Camp           UPCOMING   6.2 km
  Sanaur Village Blood Drive      UPCOMING   7.7 km
  Devigarh Rural Outreach         UPCOMING  17.1 km

camps near Chandigarh (20 km): 5 results, 0.7–17.1 km
```

All six distances distinct. Nothing existing was deleted: the seed added 23
camp items and changed 0 organizations, 0 facilities, 0 inventory rows.
**24/24 coverage checks passed.**

On "zero or identical distances": every facility and camp already had distinct
jittered coordinates and Haversine was already correct. The symptom was the
near-empty result set, not the arithmetic.

## 6. Reservations — what exists and what does not

Built and verified in the previous sprint: the full lifecycle
(`PENDING → CONFIRMED → FULFILLED`, plus `REJECTED`, `CANCELLED`, `EXPIRED`),
atomic creation via `TransactWriteItems` against a pool counter, idempotent
retries, no double release, active expiry sweeping (never TTL alone), and
deduction from **both** availability and public search.

Verified live last sprint: holding 7 of 9 units moved a facility from
`AVAILABLE units=9` to `PARTIAL units=2 reserved=7`, and cancelling restored
it. Guards fire: `ALREADY_HOLDING`, `INSUFFICIENT_UNRESERVED_STOCK` (reporting
what *is* free), `INVENTORY_NOT_REPORTED`. A requester can create, view and
cancel from the interface.

**Still missing: the blood-bank dashboard screen.** The API routes exist, are
authorized and organization-scoped, and are tested —
`GET`/`POST /facilities/{id}/reservations`, `/decision`, `/fulfil` — but staff
have no UI, so `CONFIRMED` and `FULFILLED` are reachable only through the API.
This is the largest gap remaining and I did not get to it.

Your §3.4 asks for `COMPLETED`; the existing model calls that state
`FULFILLED`. I kept the existing name rather than renaming a state that
appears in stored rows, tests and the audit trail.

## 7. Sign-up — not implemented

§2.1 and §2.2 asked for separate Sign In / Sign Up tabs and four registration
types (donor, hospital, blood bank, camp organizer) with an approval path.
**I did not build this.** What exists:

- Sign-in through Cognito with Authorization Code + PKCE (previous sprint).
- Self-service sign-up via Cognito's hosted UI, which now **works end to end**
  because of P0.1: a new account gets a `DONOR` profile automatically.
- Hospital and blood-bank roles still require administrator action, which is
  the correct default — an unverified account cannot grant itself institutional
  access.

So a new user can register and sign in, but through Cognito's own pages rather
than a LifeLink-designed form, and institutional registration has no
self-service request flow. Forgot-password and resend-confirmation are
available through the hosted UI; I have not exercised them.

## 8. Tests and gates

| Gate | Result |
|---|---|
| Backend tests | **524 passed** |
| Frontend tests | **80 passed** |
| OpenAPI freshness | matches the route table |
| `cfn-lint` | exit 0, no findings |
| `sam validate --lint` | valid |
| Dependency audit | **PASSED** — nothing shipped has a known vulnerability; 8 dev-only findings |

**604 automated tests.** New this sprint: 24 auth-degradation and provisioning
tests, 9 camp radius tests.

## 9. Infrastructure and cost

- **No new resources.** The one attempted (`AWS::Location::APIKey`, free) was
  denied by SCP and removed.
- Fixed cost **unchanged at $0.40/month** (Secrets Manager).
- One extra `AdminGetUser` call per newly provisioned user, once per user.
- No table was reset; no seeded data or account was deleted.

## 10. Remaining limitations

1. **Map tiles do not render** — SCP blocks the Location API key. Needs your
   decision (§4). All marker/popup/click code ships and is ready.
2. **Route drawing on the map** is blocked with the map. The routing API works.
3. **Blood-bank reservation dashboard UI** is missing; API is complete.
4. **No LifeLink-designed sign-up form**; Cognito's hosted pages are used.
5. **Institutional self-service registration** has no request flow.
6. **Camp discovery is capped at 20 km**, reported as `effectiveRadiusKm`. The
   proper fix is a second, coarser camp geohash index plus a backfill.
7. **I cannot drive a browser from here.** Everything above was verified by
   HTTP against the deployed API. The items needing your eyes are listed in
   §11.
8. Alarms have never fired; restore is untested; no load testing.
9. The three PDF books predate all of this.
10. The compatibility reference remains clinically unreviewed. **Not for
    clinical use.**

## 11. For you to verify in a browser

I verified the API; these need a human at the screen:

1. **Cognito sign-in** end to end — click "Continue to secure sign-in", sign
   in, land back signed in. *(Most important: this is the one flow I have never
   seen complete.)*
2. **Sign-up** of a brand-new account through the hosted UI, then confirm the
   app shows you as a donor. The API side of this is proven.
3. **"Use my location"** — grant permission, confirm results change and the
   label stops saying "default".
4. **Deny** location permission, then search a city by name on both the blood
   and camps pages.
5. The **map area** will show the facility list. That is expected (§4).

## 12. Demonstration steps

```bash
cd d:/LifeLink
set AWS_PROFILE=lifelink

curl -s https://uk6itz2a5b.execute-api.ap-southeast-2.amazonaws.com/dev/health
python scripts/seed_cloud.py --stack lifelink-dev --verify-only     # expect 24/24

# Fresh token LAST (1-hour lifetime). Password in .local-keys/demo-logins.txt
python scripts/provision_demo_logins.py --stack lifelink-dev ^
  --password "<from that file>" --token user-donor-1

start https://d324z37do52g8f.cloudfront.net
```

**The walkthrough:**

1. **Find blood** → O−, PRBC, 4 units, 30 km from Patiala. The **nearest**
   facility is third because it holds 1 of 4 units; a nearer facility with more
   stock is second because its data is stale. Ranking is not a distance sort.
2. Widen to 60 km → **Tricity Voluntary** reads *Not reported* with **no
   number**. Unknown is not zero.
3. **Donation camps** → 6 camps near Patiala at 0.4–17.1 km, with ongoing and
   upcoming states. Change the radius; search "Chandigarh" to move the origin.
4. Open **Urban Estate Donor Centre** → availability matrix, then **Temporary
   reservation**. Hold 7 of 9 units.
5. **Search again** → that facility is now *Partial, 2 units*, 7 reserved.
   Those units left everyone else's results.
6. **Cancel** → the units come back.
7. Sign in and show role separation: hospital staff cannot certify; an
   authorizer can; a suspended account is refused everything despite a valid
   token.
8. Close on the limits: unreviewed compatibility data, synthetic records, map
   tiles blocked by an account policy.
