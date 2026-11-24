# LifeLink — final development, polishing and reliability pass

**24 November 2026** · verified against the code, not against earlier reports

> **Nothing was deployed.** No AWS resource was created, modified or deleted;
> no DynamoDB record was read, written or removed; nothing was pushed to
> GitHub. Every result below was produced locally. **The live site is
> therefore behind this repository** — see §13.

| | Before | After |
|---|---|---|
| Backend tests | 547 | **604** (536 unit, 68 integration) |
| Frontend tests | 127 | **245** |
| **Total** | **674** | **849** |
| `ruff check` | 10 findings | **clean** |
| `npm run lint` | **crashed** — no config file | **clean**, 0 errors |
| `npm run build` | clean | clean |
| `cfn-lint` | clean | clean |
| Dependency audit | passed | passed |

---

## 1. What was already working

Verified by reading the code, not by trusting previous reports.

| Area | State |
|---|---|
| Batch inventory — create, adjust, verify, audit | Working. "Updated" and "verified" are genuinely separate fields and separate actions |
| Discovery and ranking | Working. Ranking weighs availability, freshness, verification and distance — it is **not** a distance sort |
| Geohash search | Working at precision 4/5/6 for facilities |
| Camps — lifecycle, registration, check-in, donation, impact ledger | Working |
| Emergency coordination — creation, hospital certification, matching, provider responses | Working |
| RBAC — 39 permissions, 10 roles, 5 ordered checks | Working, 33 tests |
| Reservations — **the whole backend lifecycle** | Working: atomic pool counter, conditional writes, expiry, audit |
| Cognito PKCE sign-in, open-redirect protection | Working, 44 tests |
| Map — clustering, named pins, directions | Working |
| IAM least privilege | Genuinely good; see §10 |

## 2. What was broken or incomplete

Each item below was confirmed in the code.

### Severity: functional holes

1. **`GET /me/reservations` had no caller anywhere in the frontend.**
   `api.myReservations` existed; no screen used it. A user could place a hold
   and then never find it again — while it kept holding units out of every
   other user's search results. Invisible to its owner, consequential for
   everyone else.
2. **The provider side of the reservation workflow was unreachable.**
   `decideReservation` and `fulfilReservation` existed in the client and no
   screen called them. Requests arrived at a facility with no way to answer.
3. **The interface promised a screen that did not exist.**
   `ReservationPanel.jsx` told requesters that "facility staff manage incoming
   requests from the blood bank dashboard". That dashboard had a facility
   selector, an add-batch form and a batch table. Nothing else.

### Severity: a live bug

4. **`AuthContext.jsx` referenced an undefined `STORAGE_KEY`**, on
   `localStorage`, in a module that stores sessions in `sessionStorage`. The
   resulting `ReferenceError` was swallowed by a bare `catch {}`, so an expired
   token was **never cleared** — the user saw "that sign-in token is not valid
   or has expired" on every page load until signing out by hand. Found by the
   lint that had never run.

### Severity: a latent security weakness

5. **The Cognito token verifier did not audience-check ID tokens.** Detail and
   proof in §10.

### Severity: truth

6. **README stated "An offer is not a reservation. Nothing is ever held. There
   is no reservation counter"** — contradicted by the shipped
   `ReservationsTable` and its pool counter.
7. **README test counts were stale** (296/36 against an actual 547/127).
8. **README claimed "`ruff` clean"** while 10 findings existed.
9. **`npm run lint` was a declared script that crashed** — ESLint 9 needs
   `eslint.config.js`, which was absent. A declared command that errors reads
   as a broken project to anyone who runs it.

### Severity: product clarity

10. **"Request blood" in the navigation pointed at `/emergency`**, conflating
    the ordinary need with Smart Emergency Coordination — the exact separation
    §4 of the brief requires.

### Unnecessary complexity found

11. Dead code: an unused `api` import and an unused `navigate` in
    `SignUpPage`; an unused `navigate` in `CampsPage` (left behind when a camp
    marker stopped navigating away); an unused `ORG_STATUSES` constant in
    `AdminDashboard`; an unused `os` import in `auth.py` (referenced only
    inside a docstring); unused `Attr` and `NotFoundError` imports in
    `reservation_repo.py`.
12. `ReservationStatus` was the only enum in the project using `(str, Enum)`;
    the other twelve use `StrEnum`.

## 3. What was changed

### Closed the functional holes

**`ReservationQueue`** — the facility-side screen, mounted on the blood bank
dashboard above the inventory forms. Requests awaiting a decision come first,
ordered by how soon they lapse, because every row in that pile holds units
nobody has agreed to. Accept, decline (with a mandatory reason the requester
sees) and record-units-issued. It introduces **no new endpoint**: all three
were already deployed, authorized and tested.

**`MyActivityPage`** at `/activity` — holds the user has placed, with a
countdown and a release button, plus emergency requests they raised.

Its scope is deliberately narrow, and the narrowing is the design. Alerts
already have a home on `/alerts`; camp registrations already have a richer
table on the donor dashboard. Repeating either would be exactly the duplication
§2.B of the brief warns against, so the page covers only what had no screen at
all and links to the two that do.

**Actions the backend would refuse are not offered.** `facilityActions()`
mirrors the backend's permitted transitions, so an expired request shows
*Decline* but not *Accept*. Offering a button and then showing the refusal is
worse than not offering it.

### Separated the ordinary need from emergency coordination

Navigation and the entry button now say **"Emergency request"**. A regression
test asserts the label cannot drift back.

### Fixed the auth bug

`clearSession()` — the module's own helper, which removes the right key from
the right storage — plus dropping the session from state so the token provider
stops handing out a token known to be dead. `loadPrincipal` is guarded on
`!token`, so the next run settles to `idle` rather than retrying.

### Made the lint real

Added `eslint.config.js` (flat config, correctness and hook-safety rules, no
style regime — a formatting pass would review as noise and hide anything real).
Pinned `@eslint/js@9.17.0` and `globals@14.0.0`, which had been resolving only
as transitive dependencies. Fixed all 10 resulting errors. Split the script:
`npm run lint` reports, `npm run lint:strict` keeps `--max-warnings 0`.

### Built the mechanism for real facility data

Three independent provenance axes, because one "Synthetic record" pill cannot
answer three questions with different answers. See §8.

### Corrected the documentation

The false reservation claim, the stale test counts, the "ruff clean" claim,
and an explicit note that the deployed site is behind the repository.

## 4. Every important modified file

### Created — frontend

| File | Purpose |
|---|---|
| `src/features/reservations/reservationStatus.js` | Lifecycle states mirroring the backend, in one place |
| `src/features/reservations/reservationView.js` | Pure presentation logic: countdown, available actions, partitioning |
| `src/features/reservations/ReservationQueue.jsx` | **The facility-side screen that was missing** |
| `src/features/account/MyActivityPage.jsx` | **The user-side screen that was missing** |
| `src/components/provenance.js` | Three-axis record provenance |
| `src/components/DataProvenance.jsx` | Provenance, shown to the user |
| `eslint.config.js` | Makes `npm run lint` work at all |

### Created — tests (175 new)

| File | Tests |
|---|---|
| `src/test/reservationView.test.js` | 43 |
| `src/test/ReservationQueue.test.jsx` | 22 |
| `src/test/MyActivityPage.test.jsx` | 18 |
| `src/test/provenance.test.js` | 27 |
| `src/test/routeIntegrity.test.js` | 8 |
| `backend/tests/unit/test_cognito_token_verifier.py` | 23 |
| `backend/tests/unit/test_facility_dataset_validation.py` | 34 |

### Created — data, scripts, docs

`data/real_facilities.json` · `scripts/validate_facility_dataset.py` ·
`docs/REAL_FACILITY_DATA.md` · `docs/CLOUD_DEMONSTRATION_GUIDE.md` ·
`docs/FINAL_POLISH_REPORT.md`

### Modified

| File | Change |
|---|---|
| `backend/src/appcore/auth.py` | **Security fix** (§10); dead import; `noqa` with a reason |
| `backend/src/domain/reservations.py` | `StrEnum`, matching the other twelve enums |
| `backend/src/repositories/reservation_repo.py` | Two dead imports |
| `backend/src/repositories/camp_repo.py` | Import ordering |
| `backend/tests/unit/test_profile_and_org_requests.py` | Import ordering |
| `frontend/src/auth/AuthContext.jsx` | **Bug fix**: expired sessions now actually clear |
| `frontend/src/App.jsx` | `/activity` route, lazy-loaded with its own Suspense boundary |
| `frontend/src/components/Layout.jsx` | "Emergency request"; "My activity" in nav and footer |
| `frontend/src/components/RequestBloodButton.jsx` | Relabelled |
| `frontend/src/components/ui.css` | Queue, activity and provenance styles |
| `frontend/src/features/dashboards/BloodBankDashboard.jsx` | Mounts the queue |
| `frontend/src/features/discovery/FacilityDetailPage.jsx` | Provenance pills and card |
| `frontend/src/features/account/SignUpPage.jsx` | Dead code; entity escape |
| `frontend/src/features/camps/CampsPage.jsx` | Dead `navigate` |
| `frontend/src/features/dashboards/AdminDashboard.jsx` | Dead constant |
| `frontend/src/features/home/InfoPages.jsx` | Entity escape |
| `frontend/package.json` | Lint scripts; two pinned devDependencies |
| `README.md` | Corrected the false claim and the stale status |

## 5. Frontend changes

Two new screens, one bug fix, one relabelling, dead code removed, lint enabled.

On **polish specifically**: the brief asked for a review of navigation,
loading, empty states, errors, validation and responsive behaviour. The
existing primitives (`AsyncState`, `LoadingPanel`, `EmptyPanel`, `ErrorPanel`,
`Field`, `Notice`) were already consistent and used throughout, so the honest
finding is that **this did not need a redesign** — the new screens were built
on those same primitives rather than introducing a parallel style, and
`.queue`/`.activity` deliberately reuse the `.directory` row shape and its
720px collapse.

What was *not* done, and why: no sweeping restyle. The brief said to retain the
existing identity and not to sacrifice functionality for appearance; a visual
overhaul days before an evaluation is risk without a verified benefit.

Empty states added where they were missing: an empty reservation list offers
"Find blood"; an empty emergency list offers the emergency workflow; an account
that uses neither is told so and pointed at the blood bank dashboard.

## 6. Backend changes

One security fix (§10), one enum alignment, three dead imports, two import
orderings, 57 new tests. **No route, handler, schema, table, index or
permission was changed.** This was deliberate: a backend change cannot be
deployed this session, so anything beyond a genuine defect fix would only widen
the gap between this repository and the running system.

## 7. Database changes

**None.** No table, index, key, TTL or billing mode was altered. No record was
read, written or deleted. No seed script was run against anything.

## 8. Data generation changes

No seeded record was changed. What was built is the mechanism that makes real
data safe to add — the detail is in `docs/REAL_FACILITY_DATA.md`.

**Real facility data is blocked, and no real facility was recorded.** Both
public sources were unreachable on 24 November 2026: the Punjab State AIDS
Control Society licensed-blood-centre PDF returned **HTTP 404**, and
`publicservicesmap.in` (which mirrors e-RaktKosh) failed **DNS resolution**.

Search-result summaries did name specific centres with licence numbers and
phone numbers. **Those were not recorded.** A search summary is a description
of a page, not the page; writing a real hospital's licence number into a
dataset on that basis would be asserting a verifiable fact nobody verified,
which is what "do not fabricate facility details or coordinates" rules out. To
proceed, supply a reachable URL or a copy of the document.

**A concern worth stating:** adding real institutions makes this application
*more* hazardous, not less. An invented name beside "9 units O-negative"
invites nobody to act; a real hospital's name beside the same figure invites
someone to drive there, or to telephone a blood bank about stock it never
reported. This is not a reason to refuse — real locations genuinely make
distance behaviour meaningful — but it is why the safeguards are mandatory.

### The three axes

| Axis | Field | Question |
|---|---|---|
| Identity | `dataSource` | Is this a real place? |
| Stock | `inventoryDataSource` | Are these quantities real? |
| Position | `coordinateProvenance` | How precisely is it placed? |

Stock provenance **never inherits** from identity provenance. A registry
listing establishes that a place exists and says nothing about its shelves;
letting a real name raise a synthetic figure's credibility is the most damaging
thing this feature could do. A test asserts the non-inheritance directly.

Enforcement: a record with no source is **refused**, as is a search-engine URL,
a `REPORTED_BY_FACILITY` claim, a `VERIFIED` status, a coordinate outside
Punjab (catching transposed lat/lon), `0,0`, and a duplicate id. 34 tests.

No loader script was written, on purpose: a writer that has never run against
anything, aimed at a live database, is dead code of the risky kind.

## 9. API changes

**None.** No route added, removed or altered. Both new screens call endpoints
that were already deployed. This is why they could be built at all without a
deployment.

## 10. Security improvements

### The finding: ID tokens were not audience-checked

`CognitoTokenVerifier` read:

```python
if self.client_id and claims.get("client_id") not in (None, self.client_id):
    raise UnauthenticatedError("token was not issued for this client")
```

The `None` in that tuple means **a token with no `client_id` claim was
accepted**. Cognito records the app client in different claims by token type:
`client_id` on an access token, `aud` on an **ID token**. An ID token has no
`client_id`, and `verify_aud` is necessarily off (an access token has no `aud`
for PyJWT to check).

So an ID token minted for a **different app client in the same user pool**
passed every gate: genuine signature, genuine issuer, `token_use: "id"`
allowed, audience never examined.

**Honest severity: latent, not currently exploitable.** The template creates
exactly one app client, so there is no second client to mint such a token.
Adding one — a mobile client, a test client — would have opened it silently,
which is the worst way for a security boundary to move.

**Fix:** each token type is audienced against the claim it actually carries,
and a missing claim fails instead of skipping.

**Proof the vulnerability was real:** reverting the fix makes three of the new
tests fail, including `test_an_id_token_for_another_client_is_refused`. That
was run, not assumed.

### Also

- **`CognitoTokenVerifier` had no tests at all.** The production component
  deciding whether any request is authenticated was the one thing unexercised,
  while the local development verifier was covered. Now 23 tests: signature,
  wrong pool, wrong key, `alg: none`, expiry, required claims, `token_use`,
  audience for both token types, audience lists, JWKS client reuse.
- **Expired sessions now actually clear** (§2.4). A dead token was being
  retried on every load.
- **Provenance display** so a user can tell which parts of what they see are
  real before acting on any of it.
- **Dependency audit still passes:** nothing that ships has a known
  vulnerability. 8 development-only findings (vitest, vite, esbuild, eslint
  tooling), unchanged and not shipped.
- **No weakening anywhere:** no permission added to a role, no check removed,
  no test loosened, no error suppressed. The one `noqa` added is for a lint
  style rule and carries its reason.

### IAM, reviewed (not changed)

The existing design is genuinely good and worth defending in an interview:

- **The audit table is write-only in IAM** — `PutItem` and `Query`, no
  `UpdateItem`, no `DeleteItem`. The application physically cannot rewrite its
  own history. An application-level rule could be bypassed by a bug; this
  cannot be, short of redeploying the policy.
- **KMS is scoped by condition, not ARN** — `kms:ViaService` restricted to
  `dynamodb.ap-southeast-2.amazonaws.com`, because the AWS-managed key's id is
  unknown at deploy time. This is why `Resource: '*'` is acceptable there, and
  it is the question an examiner will ask.
- **Read versus write is per table, per function** — six functions, six
  generated roles. The notification worker has read-only access to
  Organizations; `ScheduledMaintenance` has `PutItem` only on Audit.
- **One documented exception:** `ses:SendEmail` on `*`, which is not
  meaningfully resource-scopable for this use.

Walkthroughs in `docs/CLOUD_DEMONSTRATION_GUIDE.md`.

## 11. Tests executed, and the actual results

### Passed

| Suite | Result |
|---|---|
| Backend `pytest` | **604 passed** (536 unit, 68 integration) |
| Frontend `vitest` | **245 passed** across 11 files |
| `ruff check` | **clean** |
| `npm run lint` | **clean**, exit 0 |
| `npm run build` | **clean** |
| `cfn-lint infrastructure/template.yaml` | **clean**, exit 0 |
| `scripts/security_audit.py` | **gate passed** |
| `scripts/validate_facility_dataset.py` | **exit 0** |

### Failed

None at the end. Two failures occurred and were resolved during the work:

1. `routeIntegrity.test.js` initially failed on Windows because
   `import.meta.url` is a dev-server path under Vitest (`/@fs/D:/...`). Fixed
   by resolving from the working directory.
2. `MyActivityPage.test.jsx` — **my test was wrong, not the code.** A regex
   matched both the counted summary and a prose sentence containing the same
   words. Tightened the matcher.

### Skipped

None. No test is skipped or marked `xfail`.

### Not executed

| Item | Why |
|---|---|
| `sam validate --lint` | The `sam` CLI is not installed in this environment. `cfn-lint` was run instead and passes. README corrected to say so |
| Any AWS call | `aws sts get-caller-identity` returns "Your session has expired". Live inspection was optional and read-only, so this blocks nothing in the code |
| Any deployment | Forbidden by the brief |
| Local API end-to-end against moto | Not run. Integration tests (68) already exercise the repository layer against moto |

### Manual verification still required

**Browser workflows were not tested in a browser.** The two new screens are
covered by 40 component tests under jsdom, which press the real buttons and
assert the real client calls — but jsdom is not a browser, and this work is not
deployed, so none of it is on the live site. §13 and §14 list what to check.

## 12. Remaining limitations

1. **The deployed site does not have any of this work.** Nothing was deployed.
2. **No real facility data.** Both sources unreachable (§8).
3. **Browser-side behaviour of the new screens is unverified by me.** Component
   tests are not a browser.
4. **15 ESLint `exhaustive-deps` warnings remain**, all pre-existing, all the
   same pattern (a `||`-defaulted array feeding a `useMemo`). Fixing them means
   `useMemo` surgery across five working files; I judged that a poor trade
   before an evaluation and left the warnings visible rather than silenced.
   `npm run lint:strict` still fails on them, by design.
5. **No blood-bank-side screen for emergency provider responses.** The
   provider queue endpoint exists; the reservation queue closed the reservation
   gap, not this one.
6. **Camp discovery is capped at 20 km** by the camps table's single
   precision-5 geohash index. Reported honestly as `effectiveRadiusKm`. Fixing
   it needs a second coarser index and a backfill — a schema change, so not
   this session.
7. **The identity-pool map path is deployed but unused.** The frontend renders
   OpenStreetMap raster tiles because `AWS::Location::APIKey` is denied by the
   account's SCP. Demonstrate it from the console, not the screen.
8. **The CloudFront SPA fallback returns `index.html` with HTTP 200 for any
   missing asset.** This disguised a real bug once already (the MapLibre
   worker). Restricting it so `/assets/*` returns a true 404 is an
   infrastructure change and needs approval.
9. **Road distance and ETA are still not shown** — straight-line only, labelled
   as such.
10. **The blood compatibility reference is clinically unreviewed.** Not for
    clinical use. All records are synthetic.

## 13. Manual testing instructions

Nothing below is live yet. To see it, run locally:

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173
```

Full local stack, including the API:

```bash
python scripts/dev.py keys          # local JWT keypair
python scripts/dev.py db-start      # local DynamoDB (moto)
python scripts/dev.py create-tables
python scripts/dev.py token         # mint a local dev token
python scripts/local_server.py      # the API
```

### Checks

**The facility-side queue** — sign in as blood bank staff, open
`/dashboard/blood-bank`:

| # | Check | Expect |
|---|---|---|
| 1 | "Reservation requests" appears **above** the batch forms | Requests before records |
| 2 | Awaiting-decision requests come first, soonest-to-lapse first | — |
| 3 | The units-held figure counts only live holds | Expired holds excluded |
| 4 | **Accept** | Status becomes "Accepted — units held" |
| 5 | **Decline** | Demands a reason; the confirm button is disabled until typed |
| 6 | **Record units issued**, on an accepted hold only | — |
| 7 | A lapsed request | Shows *Decline* but **not** *Accept* |
| 8 | Closed requests | Collapsed, "No action available" |

**The user-side page** — sign in as a donor, place a hold from a facility page,
then open `/activity`:

| # | Check | Expect |
|---|---|---|
| 9 | The hold is listed with a coarse countdown | e.g. "1 h 58 m left", never seconds |
| 10 | "not clinical approval" is stated | — |
| 11 | **Cancel hold** | Hold leaves the live list; units return to search results |
| 12 | A finished hold | Appears under "Earlier reservations", no cancel button |
| 13 | An uncertified emergency request | "Not clinically certified", **no** invented priority |

**Separation and provenance:**

| # | Check | Expect |
|---|---|---|
| 14 | Navigation | "Emergency request", not "Request blood" |
| 15 | "My activity" in the nav | Only when signed in |
| 16 | A facility page | Two provenance pills — identity *and* stock |
| 17 | "Where this record comes from" card | Three statements: institution, quantities, location |

**Authentication:**

| # | Check | Expect |
|---|---|---|
| 18 | Sign in, wait for the token to expire, reload | The session **clears**; you are signed out cleanly rather than seeing the expiry error on every load |
| 19 | Narrow to phone width | Queue and activity rows stack; no horizontal scroll |

### Offline checks, runnable now

```bash
python -m pytest backend/tests                      # 604
python -m ruff check backend/src backend/tests      # clean
python scripts/validate_facility_dataset.py         # exit 0
python scripts/security_audit.py                    # gate passed
cd frontend && npm test -- --run                    # 245
cd frontend && npm run lint && npm run build        # clean
```

## 14. AWS configuration and environment variables needing attention

### Immediate

1. **The session is expired.** `aws login`, then confirm with
   `aws sts get-caller-identity --profile lifelink`. No AWS inspection was
   possible this session.
2. **`sam` CLI is not installed.** Needed for `sam validate --lint` and for any
   backend deployment.

### If you choose to deploy

The work in this report is **frontend plus two backend files**:

- **Frontend only** (`python scripts/deploy_frontend.py`) would publish both
  new screens, the relabelled navigation, the provenance display and the auth
  fix. It touches S3 and a CloudFront invalidation — no infrastructure, no
  table, no new resource, no cost change.
- The **security fix in `auth.py`** and the `StrEnum` change need a backend
  deployment (`sam deploy`) to take effect. Until then the deployed verifier
  still accepts an ID token from another app client — which, with one app
  client, nothing can currently produce.

Both are your call; I did neither.

### Environment variables — no change required

`COGNITO_USER_POOL_ID` and `COGNITO_CLIENT_ID` are already set by the template.
`COGNITO_CLIENT_ID` **matters more after the fix**: it is what the audience
check compares against, and with it unset the check is skipped (behaviour left
unchanged deliberately, and covered by a test that names why).

`LIFELINK_ENV` must remain non-`local` in AWS — three refusals in
`backend/src/appcore/environment.py` enforce this, 45 tests.

### Watch for

- **A spend limit pausing the project** makes previously-working calls return
  Access Denied. Check **AWS Settings ▸ Billing** before debugging code.
- **Do not retry `AWS::Location::APIKey`** — denied by the account's SCP.
- Cost is unchanged at **~$0.40/month**; nothing here adds a resource.
