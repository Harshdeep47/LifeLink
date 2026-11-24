# LifeLink — Recovery Sprint Report

**15 November 2026.** Browser inspection of the live deployment exposed a set
of production defects. This records every one, its root cause, the fix, and
what was verified **against the deployed system** rather than locally.

Live site: **https://d324z37do52g8f.cloudfront.net**
API: `https://uk6itz2a5b.execute-api.ap-southeast-2.amazonaws.com/dev`

---

## 1. Defects found and fixed

### 1.1 CORS: every browser request failed (P1)

**Symptom.** `No 'Access-Control-Allow-Origin' header is present`. The site
loaded, `/health` answered, and opening a facilities URL in the address bar
returned valid JSON — but every `fetch()` failed on preflight. Donation camps
showed `NETWORK_ERROR`.

**Root cause — two faults compounding.** The template read the allowed origin
from the OAuth logout URL:

```yaml
AllowOrigins: [!Ref LogoutUrl]
```

1. `LogoutUrl` is an OAuth redirect target, not a browser origin, and its
   default is `http://localhost:5173/`. The deployed API therefore allowed only
   localhost and refused CloudFront.
2. That value has a **trailing slash**. An `Origin` header never carries a path
   or a trailing slash, so it could not have matched any origin in any
   environment, ever.

Direct address-bar requests sent no `Origin` header, so no CORS check ran —
which is exactly why the API looked healthy while the app was broken.

**Fix.** A dedicated `CorsAllowOrigins` parameter (`CommaDelimitedList`),
decoupled from OAuth. Explicit origins, never `*`: the API is called with an
`Authorization` header, and a wildcard would let any page a signed-in user
visits read authenticated responses. `AllowCredentials` is deliberately unset —
LifeLink authenticates with a bearer token, not cookies.

A second safety net was added in [appcore/cors.py](../backend/src/appcore/cors.py):
routes are declared `Method: ANY`, which matches `OPTIONS`, so a preflight
*can* reach Lambda instead of being answered at the edge. Measurement showed
API Gateway does answer it first here, so the handler is a net rather than the
mechanism. Responsibilities are split so the two layers cannot duplicate a
header (browsers reject a doubled `Access-Control-Allow-Origin` as firmly as a
missing one): Lambda answers **preflight only**, API Gateway adds headers to
everything else.

**Verified live.**

| Check | Result |
|---|---|
| `OPTIONS /facilities` from the CloudFront origin | 204 with allow-origin, allow-methods, allow-headers, max-age |
| `GET /facilities` with `Origin` | 200 + allow-origin |
| `GET /camps` **error** response (400) | 400 **+ allow-origin** — errors carry CORS too |
| `GET /reference` with a disallowed origin | **no** allow-origin header |

### 1.2 Camp discovery silently returned almost nothing (P4)

Fixing CORS made the page load; it did not make the feature work. A 100 km
camp search returned **one** camp.

**Root cause.** `find_nearby_upcoming` selected geohash cells with
`min(radius_km, 20.0)` while filtering by the **full** radius. Camps beyond
20 km sat in cells that were never queried. The same failure mode as the
original facility geohash defect: no error, just a short list.

Removing the cap made it worse, which exposed the deeper cause: **camps carry a
single precision-5 geohash index**, unlike facilities which have three.
`search_cells` coarsens to precision 4 beyond 20 km, and a precision-4 cell
never matches a precision-5 key — so a wide search returned *nothing at all*,
including the camp at the search origin.

**Fix, and an honest limit.** Covering 100 km at precision 5 would need roughly
1,600 queries, so the real fix is a second, coarser camp index — not something
to backfill safely under deadline. The cap therefore stays, but it is now
**reported** as `effectiveRadiusKm` with a notice saying what was actually
searched, and the distance filter uses the same radius it covered. A limit the
caller cannot see is indistinguishable from a bug; a limit that is stated is a
limit. Recorded in [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md).

Pinned by 9 integration tests, including one asserting the origin camp is found
at every radius — the specific regression.

### 1.3 Home page stuck on "Loading reference data…" (P5)

**Root cause.** The page rendered on `reference` being truthy, which is false
both while loading *and* on error. An API failure left a permanent loading
message.

**Fix.** `loading` and `error` are now distinguished, and a static fallback
([referenceFallback.js](../frontend/src/api/referenceFallback.js)) mirrors the
backend's eight groups and four components, with the interface stating when the
fallback is in use. The fallback keeps the compatibility `reviewStatus` as
`UNREVIEWED_SYNTHETIC` — degrading must never quietly upgrade a clinical
caveat.

The backend was never at fault: `/reference` returns all 8 groups and all 4
components, verified live.

### 1.4 The sign-in page published internal account details (P2.2)

**Symptom.** The deployed `/sign-in` was headed "Local development sign-in",
instructed visitors to run `python scripts/dev.py token user-donor-1`, and
listed every seeded account id with its role — including the **platform
administrator** and the **hospital authorizer**.

On a public URL that is a disclosure and an invitation, not a convenience.

**Fix.** All of it is gone from the deployed bundle. The development
token-paste path is now guarded by `import.meta.env.DEV`, a **compile-time**
constant, so the branch is eliminated from the production build rather than
hidden behind a runtime flag. The demo account list was deleted outright.

A false claim in the source was also corrected: the `SignInPage` docstring
asserted it implemented the Cognito redirect with PKCE. It did not. A wrong
comment is worse than a missing feature.

### 1.5 Cognito browser sign-in did not exist (P2.1)

**Implemented**, in [auth/cognito.js](../frontend/src/auth/cognito.js):

- Authorization Code with **PKCE** (S256), against the public app client — a
  browser cannot keep a secret, and PKCE makes an intercepted code useless
  without the verifier that never leaves the origin.
- `state` generated and checked on return, closing login CSRF.
- The exchange runs **once**: React 18 StrictMode double-invokes effects and an
  authorization code is single-use, so a ref guard prevents an `invalid_grant`
  error appearing *after* a successful sign-in.
- The code is stripped from the URL on success, keeping it out of history and
  any `Referer`.
- Tokens in **sessionStorage**, not localStorage. Neither defends against XSS;
  the difference is lifetime, and a token outliving the tab on a shared or lab
  machine is the realistic risk here.
- Expiry detected on use and on an interval, with refresh-token renewal and a
  clean sign-out when renewal fails — so a user is told their session ended
  instead of meeting an unexplained 401.
- Sign-out redirects through Cognito's `/logout`. Clearing local storage alone
  would leave the session cookie, and the next sign-in would skip the form and
  look like it never signed out.

Configuration is written at deploy time from the CloudFormation stack outputs
by [deploy_frontend.py](../scripts/deploy_frontend.py), so the bundle cannot
point at the wrong user pool, and the publish fails if the built bundle does
not contain the deployed API host.

**Manual configuration required from you: none.** The callback and logout URLs
were set on the app client by this deployment
(`CallbackUrl=https://d324z37do52g8f.cloudfront.net/auth/callback`).

### 1.6 "Unknown is not zero" was broken in one of two paths

Found earlier the same day and fixed: the live API returned
`{"availability": "UNKNOWN", "eligibleUnits": 0}` for a facility that had never
reported. `eligible_units` is now `int | None` in the domain type, so every
caller inherits the distinction. 40 tests.

---

## 2. Temporary reservations (P3) — the specification question first

**I have to report an ambiguity, because you asked me to rather than make an
irreversible decision quietly.**

The original specification does not describe a reservation feature. It states
the opposite, repeatedly:

| Spec | Text |
|---|---|
| 374 | "An alert is informational. It is **not a reservation**, allocation, clinical approval or guarantee that the stock will remain available." |
| 727 | "An ACCEPTED response means the provider is willing to proceed… It **does not guarantee stock reservation**, fulfilment or transfusion." |
| 733 | "Revalidate stock before any **later** confirmation or **reservation workflow**." |
| 2134 | "Availability alerts work and are **not treated as reservations**." |

So the capability was **not removed** — it was never specified. The
"LifeLink does not reserve blood" text you saw was a literal implementation of
374 and 727. Line 733 anticipated a reservation workflow as *later* work.

**What I built, and why it does not contradict any of that.** Temporary
reservations are an **additive eighth capability**. The two rules above remain
true and unchanged in code and in wording:

- an availability **alert** still holds nothing;
- a provider's **ACCEPTED** response to an emergency request still holds
  nothing;
- a **reservation** is a separate, explicit act against one facility's stock.

Public-facing text was corrected rather than deleted: "LifeLink does not
reserve blood" became "browsing does not hold anything — you can request a
temporary reservation", and the emergency notice now says that *raising a
request* holds no units, which is still accurate.

### How it works

| Concern | Mechanism |
|---|---|
| Lifecycle | `PENDING → CONFIRMED → FULFILLED`, with `REJECTED`, `CANCELLED`, `EXPIRED`. Enumerated transition table; illegal moves refused with a reason code |
| Which states hold units | **Only `PENDING` and `CONFIRMED`.** Every other rule follows from that one sentence |
| No overselling | One `TransactWriteItems` writes the reservation row **and** increments a per-pool counter under a condition that the total cannot exceed eligible units. DynamoDB evaluates it, so two callers cannot both pass |
| Idempotent retries | The row is written with `attribute_not_exists(SK)`; a double click cannot double-hold. A retry and a lost race are **disambiguated by re-reading**, so someone who clicked twice is not told the stock was taken |
| No double release | Release is conditioned on the current status **and** version, so a hold cannot decrement the counter twice and invent stock |
| Reserved units excluded | Deducted in **both** the availability matrix and public search, with `reservedUnits` reported so a user can see why a figure changed |
| Expiry | Swept actively every 10 minutes **and** treated as expired at read time. DynamoDB TTL is used only for row cleanup — it fires within ~48 hours on a best-effort basis, which is useless for releasing units |
| Partial availability | Refused, not silently reduced, and the response reports how many *are* free. Quietly holding fewer units than asked would let someone travel expecting more |
| Abuse | One active hold per person per pool; maximum 10 units per request; 15-minute to 8-hour bounds |
| Authorization | `reservation:create` / `reservation:manage:own` for requesters, `reservation:manage` (organization-scoped) for facility staff |
| Audit | Every transition recorded with actor, resource, correlation id |
| Not clinical | Every response carries `isClinicalApproval: false` and a notice stating it is not a cross-match and not a guarantee of release |

**Files:** [domain/reservations.py](../backend/src/domain/reservations.py),
[repositories/reservation_repo.py](../backend/src/repositories/reservation_repo.py),
[services/reservation_service.py](../backend/src/services/reservation_service.py),
6 API routes, [ReservationPanel.jsx](../frontend/src/features/discovery/ReservationPanel.jsx).

**Infrastructure:** one new DynamoDB table, `lifelink-dev-reservations`,
on-demand with two GSIs and point-in-time recovery. **No new fixed cost** —
on-demand tables have no monthly charge. Total fixed cost is unchanged at
**$0.40/month**.

### Verified against the live deployment

| Step | Result |
|---|---|
| Availability before hold (`fac-patiala-3`, O− PRBC) | `eligible 9, reserved 0, unreserved 9` |
| Create 3-unit hold, 60 min | `PENDING`, `holdsUnits: true`, `isClinicalApproval: false` |
| Availability after hold | `eligible 9, reserved 3, unreserved 6` |
| Second hold, same user, same pool | refused, `ALREADY_HOLDING` |
| Request 9 units where 1 is free | refused, `INSUFFICIENT_UNRESERVED_STOCK`, reports `unreservedUnits: 1` |
| Hold at a facility that never reported | refused, `INVENTORY_NOT_REPORTED` |
| `GET /me/reservations` | returns the hold |
| Hold 7 of 9, then public search for 4 units | **`AVAILABLE units=9` → `PARTIAL units=2 reserved=7`** |
| Cancel | `CANCELLED`, `holdsUnits: false`, `releasedAt` set |
| Availability after cancel | back to `eligible 9, reserved 0, unreserved 9` |
| Unauthenticated reservation attempt | 401 |

That `AVAILABLE 9 → PARTIAL 2` line is the feature working: units left the
public search because someone held them, and the availability **state** was
recomputed rather than the number merely edited.

---

## 3. Public emergency requests (P7)

Checked against the specification rather than assumed. The spec contemplates
this directly: "a public user cannot self-declare a hospital as verified"
(6.3) is a constraint on **certification**, and `VERIFICATION_PENDING` exists
in the lifecycle (6.8) for a request no verified hospital has vouched for.

`EMERGENCY_CREATE` was granted to the `PUBLIC` role and `allow_anonymous=True`
set on that one route. The service already derived verification state from the
caller's organization, and an anonymous caller has none — so a public request
**cannot arrive pre-certified**.

**Verified live, anonymously:**

```json
{"status": "VERIFICATION_PENDING",
 "clinicalPriority": null,
 "hospitalVerificationState": "PENDING_VERIFICATION"}
```

Anonymous certification attempt: **401**.

27 tests pin the boundary, including a whitelist assertion that no *other*
route became anonymous — `allow_anonymous=True` on the wrong handler is a
one-word change with no visible symptom.

---

## 4. Interface (P6)

**Red striped banner removed** from every page. The requirement behind it is
unchanged and still met, by three means harder to ignore than a banner people
learn to skip: every facility and camp name carries a `(DEMO)` suffix **from
the data itself**; a quiet persistent line sits in the footer — *"Academic
project prototype. Demonstration records are simulated."*; and the Help and
About pages say it in full.

**Blue development-style panels rebalanced, not deleted.** Informational
notices are now neutral with a hairline border; **warning and danger keep their
colour**, so a real problem stands out again. Previously a page with three
explanatory notes looked like a page reporting three problems. Explanatory
content about freshness, verification, unknown availability, distance
calculation, clinical limits and reservation behaviour was **moved into smaller
type, not removed** — a new `.inline-note` style puts an explanation beside the
thing it explains.

**Honest scope note:** this is a measured de-escalation of alarming UI and a
corrected disclosure, not a full visual redesign. The existing design tokens
(white/light-grey surfaces, deep crimson accent, navy text) were already in
place and are unchanged. I did not rebuild tables, cards or layouts.

---

## 5. Security preserved (P8)

Nothing was weakened to make anything work. Re-verified live:

| Check | Result |
|---|---|
| Own organization's facility batches | 200 with real data |
| **Another** organization's facility | **403 `CROSS_ORGANIZATION_DENIED`** |
| Donor-only route with a blood-bank token | **403 `FORBIDDEN`** |
| Protected route, no token | 401 |
| Protected route, malformed token | 401 |
| Anonymous certification | 401 |
| Reservation without a token | 401 |

Still in force: Cognito JWT verification against the pool's JWKS; roles and
account status read from the database on every request (so suspension is
immediate); organization isolation via the central ownership resolver; the
`appcore/environment.py` refusal that prevents local auth in AWS three
independent ways; least-privilege IAM; recursive log redaction; no secret in
the bundle (all injected values are public identifiers).

The new table's IAM grant went only to the three functions that need it.

---

## 6. Tests and gates

| Gate | Result |
|---|---|
| Backend tests | **500 passed** |
| Frontend tests | **80 passed** |
| OpenAPI freshness | matches the route table (48 paths, 56 operations) |
| `cfn-lint` | exit 0, no findings |
| `sam validate --lint` | valid SAM template |
| Dependency audit | **PASSED** — nothing that ships has a known vulnerability; 8 dev-only findings reported |

**580 automated tests, all passing.** New this sprint: 47 reservation unit
tests, 17 reservation integration tests (including the overselling race), 9
camp radius tests, 27 public-access boundary tests.

---

## 7. Remaining limitations

Stated plainly.

1. **Camp discovery searches up to 20 km**, reported as `effectiveRadiusKm`.
   The proper fix is a second, coarser camp geohash index.
2. **Map tiles have not been seen rendering in a browser.** The Amazon Location
   map and identity pool exist and are configured.
3. **The PKCE flow has not been exercised in a browser by me.** The code paths
   are implemented and the configuration is injected and verified present in
   the bundle, but I cannot drive a browser here — I verified the API side with
   real Cognito tokens instead. **Please try signing in before the
   presentation**; if it fails, the token-paste fallback still works locally.
4. **Facility staff reservation management has API routes and tests but no
   dashboard UI.** `GET/POST .../reservations`, `/decision` and `/fulfil` are
   live and authorized; a blood bank cannot yet confirm or reject a hold from a
   screen.
5. **`FULFILLED` is reachable only via the API**, for the same reason.
6. **No alarm has ever fired**; point-in-time restore is still **untested**; no
   load testing.
7. **The three PDF books predate all of today's work** and are not regenerated.
8. **The compatibility reference remains clinically unreviewed.** LifeLink must
   not be used for clinical decisions.
9. **8 development-only dependency vulnerabilities** accepted (vitest, vite,
   eslint toolchain); none ships to a browser or Lambda.

---

## 8. Demonstration steps for tomorrow

```bash
cd d:/LifeLink
set AWS_PROFILE=lifelink

# 1. Is it alive?
curl -s https://uk6itz2a5b.execute-api.ap-southeast-2.amazonaws.com/dev/health

# 2. Is the data intact? (expect 24/24)
python scripts/seed_cloud.py --stack lifelink-dev --verify-only

# 3. A fresh sign-in token, LAST (they expire in 1 hour).
#    Password is in .local-keys/demo-logins.txt
python scripts/provision_demo_logins.py --stack lifelink-dev ^
  --password "<from that file>" --token user-donor-1

# 4. Open the site
start https://d324z37do52g8f.cloudfront.net
```

**The five-minute version:**

1. **Find blood** → O−, PRBC, 4 units, 30 km from Patiala. Read the order out:
   the **nearest** facility is third because it has 1 of 4 units; a **nearer**
   facility with **more** stock is second because its data is stale; expired
   and quarantined stock shows as *none in stock*, not missing.
2. Widen to 60 km → **Tricity Voluntary** shows *Not reported* with **no
   number**. Unknown is not zero.
3. Open **Urban Estate Donor Centre** → the availability matrix, then the
   **Temporary reservation** panel. Hold 7 of 9 units.
4. Search again → that facility is now **Partial, 2 units**, with 7 reserved.
   *"Those units left everyone else's search because someone is holding them."*
5. **Cancel** the hold → the units come back.
6. Sign in and show role separation: hospital **staff** cannot certify priority;
   a hospital **authorizer** can; a **suspended** account is refused everything
   despite a valid token.
7. Close on the limits: unreviewed compatibility data, synthetic records, an
   untested restore procedure.
