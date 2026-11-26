# Frontend Code Walkthrough

React 18 + Vite 6. 294 tests in 12 files, all passing. This document walks the
code in the order a request flows through it.

---

## 1. Startup

```
frontend/index.html
   -> src/main.jsx          # createRoot, renders <App/>
      -> src/App.jsx        # AuthProvider + BrowserRouter + 23 routes
```

`App.jsx` does four things worth knowing:

1. **Wraps everything in `AuthProvider`** so any component can call `useAuth()`.
2. **Lazy-loads the six dashboards** with `React.lazy`, so a donor never
   downloads the admin dashboard's code.
3. **Gives each route its own `Suspense` and `ErrorBoundary`.** A crash in one
   page shows an error panel instead of a blank white screen for the whole app.
4. **Guards private routes with `RequireAuth`.**

```jsx
const AdminDashboard = lazy(() => import('./features/dashboards/AdminDashboard.jsx'))
...
<Route path="/profile"
       element={<RequireAuth><ErrorBoundary><ProfilePage /></ErrorBoundary></RequireAuth>} />
```

**The per-route `Suspense` detail caught a real bug.** When `/activity` was
added it was lazy-loaded but placed outside any `Suspense` boundary, which
would throw at runtime. Because `Suspense` here is per-route rather than
global, the omission was easy to miss and easy to fix.

### The 23 routes

| Path | Page | Auth |
|---|---|---|
| `/` | `HomePage` | public |
| `/find` | `FindBloodPage` | public |
| `/facilities/:facilityId` | `FacilityDetailPage` | public |
| `/explore` | `ExploreDashboard` | public |
| `/camps` | `CampsPage` | public |
| `/camps/:campId` | `CampDetailPage` | public |
| `/emergency` | `EmergencyRequestPage` | public page, authenticated action |
| `/emergency/:requestId` | `RequestTrackingPage` | authenticated |
| `/alerts` | `AlertsPage` | authenticated |
| `/sign-in`, `/sign-up` | auth pages | public |
| `/auth/callback` | `AuthCallbackPage` | public (handles the OAuth code) |
| `/profile` | `ProfilePage` | **RequireAuth** |
| `/activity` | `MyActivityPage` | **RequireAuth** |
| `/help`, `/privacy`, `/terms` | `InfoPages` | public |
| `/dashboard/donor` | `DonorDashboard` | **RequireAuth** |
| `/dashboard/blood-bank` | `BloodBankDashboard` | **RequireAuth** |
| `/dashboard/hospital` | `HospitalDashboard` | **RequireAuth** |
| `/dashboard/camps` | `CampOrganizerDashboard` | **RequireAuth** |
| `/dashboard/admin` | `AdminDashboard` | **RequireAuth** |
| `*` | `NotFoundPage` | — |

`src/test/routeIntegrity.test.js` (8 tests) scans the source for internal
links and **fails the build** if any points at a path no route serves. It was
proven to work by deliberately injecting `/definitely-not-a-route`, which
failed the test and named the offending file.

---

## 2. Authentication in the browser

### `auth/cognito.js` — the OAuth mechanics

| Export | Purpose |
|---|---|
| `isCognitoConfigured()` | False when the `VITE_COGNITO_*` variables are missing |
| `config()` | Reads the build-time configuration |
| `beginSignIn({returnTo})` | Generates the PKCE verifier/challenge and redirects to the hosted UI |
| `completeSignIn(search)` | Exchanges `?code=...` plus the verifier for tokens |
| `refreshSession(session)` | Uses the refresh token |
| `loadSession` / `saveSession` / `clearSession` | `localStorage` under `TOKEN_KEY = 'lifelink.session'` |
| `isExpired(session, now)` | Pure, so tests control the clock |
| `signOutRedirect()` | Redirects to Cognito logout |

### `auth/AuthContext.jsx` — the React integration

`AuthProvider` loads any stored session, checks expiry, registers the token
provider with the API client, and exposes `useAuth()`.

**The key line, conceptually:**

```javascript
setTokenProvider(() => currentSession?.accessToken ?? null)
```

The API client receives a **function**, never a token. So there is exactly one
copy of the session, and no component can hold a stale one.

> **A real bug found here, worth telling a teacher about.** The expiry branch
> called `localStorage.removeItem(STORAGE_KEY)` — but `STORAGE_KEY` did not
> exist in that scope; the constant is `TOKEN_KEY`. The `ReferenceError` was
> swallowed by an empty `catch`, so **expired sessions were never cleared** and
> the user was left in a broken half-signed-in state. The fix routed it through
> the existing `clearSession()`. Two lessons: an empty `catch` can hide a
> programming error, not just an expected failure — which is why
> `no-empty: ["error", {allowEmptyCatch: false}]` is now an ESLint error — and
> enabling a linter that had never actually run found a real defect on day one.

### `auth/passwordPolicy.js` — one source of truth

```javascript
export const MIN_LENGTH = 12
```

Plus an explicit `SYMBOLS` set and a `PASSWORD_REQUIREMENTS` list the sign-up
page renders.

> **Another real bug.** Three places in the UI said "at least 8 characters" and
> none mentioned a symbol, while the deployed Cognito pool requires **12
> characters including a symbol**. Users following the on-screen rules were
> rejected by Cognito with an unhelpful error. The fix was one shared module
> plus a test that reads `infrastructure/template.yaml` and asserts the UI
> matches the pool. 49 tests now cover it. Verified live: Cognito refuses
> `Password1` with `InvalidPasswordException`.

**That test is the interesting part** — it reads the infrastructure template, so
the UI and the deployed policy cannot drift apart silently again.

---

## 3. `api/client.js` — every network call

Covered in detail in
[../02_SYSTEM_ARCHITECTURE/03_Frontend_To_Backend_Communication.md](../02_SYSTEM_ARCHITECTURE/03_Frontend_To_Backend_Communication.md).
In short: `ApiError` with a stable `code`, `isRetryable` and `isAuthError`;
one `request()` that attaches the token, correlation id, content type and
idempotency key; and an `api` object with one entry per endpoint.

---

## 4. `hooks/` — the four hooks everything uses

| Hook | Signature | Purpose |
|---|---|---|
| `useApiData` | `(fetcher, deps, {enabled, initialData})` | Fetch with `{data, loading, error, reload}`, aborts on unmount |
| `useMutation` | `(mutator)` | Write with `{mutate, pending, error}` |
| `useDebounced` | `(value, delay = 350)` | Debounce typing before searching |
| `useGeolocation` | `()` | Wraps `navigator.geolocation` with permission and error states |

**Why a debounce of 350 ms?** Because facility search hits the API, and
searching on every keystroke would multiply requests against a gateway
throttled to 10 per second.

---

## 5. `components/` — shared UI

### `ui.jsx` — the primitives

`AsyncState` is the one to understand. It takes `{loading, error, data}` and
renders a spinner, an error panel with retry, an empty panel, or the children.
That means every page handles those four states consistently, and no page
forgets the empty case.

`ErrorBoundary` is a class component — required, because React error
boundaries can only be classes.

`NotAReservationNotice` has one job: say that an availability alert is **not**
a reservation. An honesty rule, implemented as a component.

### `StatusBadges.jsx` — where the honesty rules are visible

| Badge | Shows |
|---|---|
| `AvailabilityBadge` | `UNKNOWN` as "Not reported" with **no number** |
| `FreshnessBadge` | `FRESH` / `AGING` / `STALE` / `OUTDATED` |
| `VerificationBadge` | verified or "Verification expired" |
| `DataQuality` | freshness and verification **together, as separate axes** |
| `PriorityBadge`, `StatusPill`, `CampStatusPill`, `RequestStatusPill` | lifecycle states |

`FreshnessBadge` and `VerificationBadge` are deliberately **two badges**. Data
can be recently updated but long unverified, and collapsing them into one
"quality" score would hide exactly the distinction that matters.

### `FacilityMap.jsx` and `mapData.js`

The map cannot run in jsdom because it needs WebGL, so everything that decides
*what* the map shows was pulled into `mapData.js` as pure functions and tested
there: `toCoordinate`, `shortLabel`, `facilitySummary`, `campSummary`.

`toCoordinate` refuses `0,0`:

```javascript
// 0,0 is in the Gulf of Guinea and is almost always a missing value
// that survived as a default.
if (lat === 0 && lon === 0) return null
```

**A marker at a nonsensical coordinate is worse than a missing marker, because
it looks like data.** That sentence is a good one to quote.

The basemap style is defined inline, pointing at
`https://tile.openstreetmap.org/{z}/{x}/{y}.png` with attribution. See
[../07_MAPS_AND_INTEGRATIONS/02_Map_Rendering_And_Tiles.md](../07_MAPS_AND_INTEGRATIONS/02_Map_Rendering_And_Tiles.md).

### `provenance.js` — three independent axes

| Export | Answers |
|---|---|
| `identitySource(record)` | Is this a demo account or a real one? |
| `inventorySource(record)` | Where did this stock figure come from? |
| `coordinateSource(record)` | Where did this location come from? |

**They are independent on purpose.** `inventorySource` **never inherits** from
identity: a demo *account* can still enter a real stock figure, and conflating
the two would mislabel data.

---

## 6. `features/reservations/` — the clearest example of layering in the frontend

| File | Role |
|---|---|
| `reservationStatus.js` | The lifecycle states, mirroring the backend |
| `reservationView.js` | **Pure logic**, 43 tests, no React |
| `ReservationQueue.jsx` | The facility-side screen, 22 tests |

`reservationView.js` exports:

| Function | Decides |
|---|---|
| `remainingMs`, `formatRemaining` | the countdown |
| `holdsUnits` | whether this reservation is currently holding units |
| `isStaleHold` | a hold whose time has passed but whose status has not caught up |
| `statusLabel` | **"Accepted — units held"**, never "approved" |
| `statusTone` | the badge colour |
| `facilityActions` | which buttons a blood bank may press |
| `canRequesterCancel` | whether the requester may cancel |
| `mutationBody` | the request body for a transition |
| `partitionForFacility`, `partitionForRequester` | grouping, differing by viewer |
| `totalHeldUnits` | the sum shown on the dashboard |

**Why extract all this from the component?** Because these are the decisions
with consequences — whether a button appears, whether units are described as
held — and testing them through a rendered component would be slow and
indirect. 43 fast tests cover them instead.

`isStaleHold` deserves a mention: there is one real row in production whose
status is `CONFIRMED` but whose hold has expired. The UI shows it as expired
because `isStaleHold` compares the clock to the status, rather than trusting
the stored status alone. That is documented as known limitation §1.15.

---

## 7. Dashboards, one per role

| Dashboard | For | Shows |
|---|---|---|
| `DonorDashboard` | `DONOR` | impact, registrations, donation history |
| `BloodBankDashboard` | `BLOOD_BANK_*` | **the reservation queue**, then batch management |
| `HospitalDashboard` | `HOSPITAL_*` | emergency requests, certification |
| `CampOrganizerDashboard` | `CAMP_*` | camps, staff, check-in |
| `AdminDashboard` | `PLATFORM_ADMIN` | pending organizations, audit log |
| `ExploreDashboard` | anyone | public overview |

`ReservationQueue` sits **above** the batch forms on the blood bank dashboard,
because a pending hold is time-critical and stock editing is not.

---

## 8. Testing the frontend

```bash
cd frontend
npm run test -- --run     # 294 tests, 12 files
npm run lint              # exit 0, 15 exhaustive-deps warnings
npm run build             # production build
```

**The 15 warnings are real but non-blocking.** They are
`react-hooks/exhaustive-deps` warnings across five working files. Fixing them
means `useMemo`/`useCallback` surgery with no behavioural benefit, so they were
left and documented. `exhaustive-deps` is set to `warn` rather than `error`
precisely so that it reports without blocking.

Testing strategy, which is the point to make in a viva:

| What | How |
|---|---|
| Pure logic | Direct unit tests — `reservationView`, `provenance`, `mapData`, `passwordPolicy` |
| Components | Render and interact — `ReservationQueue`, `MyActivityPage`, `StatusBadges` |
| Contracts | `maplibreExports` pins named exports; `routeIntegrity` forbids dead links |
| **Real browser** | **Not covered. No browser automation exists in this project.** |

---

## 9. Spoken answers

### 20–30 seconds

> "It's a React 18 single-page app built with Vite. Routing is React Router with
> 23 routes; the six role dashboards are lazy-loaded so you only download the
> one you need. All API calls go through one client module that attaches the
> Cognito token. The pattern I'd point to is that anything with a real decision
> in it — like whether a reservation is still holding units, or how to label a
> status — lives in a pure JavaScript module with its own tests, not inside a
> component."

### 1–2 minutes

Add the bug stories, which are the strongest material:

> "Two things in the frontend are worth showing. First, we enabled ESLint
> properly — the project had a `lint` script from the start but no working
> config, and a legacy `.eslintrc.json` that ESLint 9 silently ignored. Turning
> it on found a real bug immediately: an undefined variable inside an empty
> `catch`, which meant expired sessions were never cleared. The error was
> invisible because the empty catch swallowed it.
>
> Second, the password policy. Three screens told users 'at least 8 characters'
> while the Cognito pool required 12 with a symbol, so people were being
> rejected with a confusing error after following our own instructions. We fixed
> it with one shared module — and then wrote a test that reads the
> CloudFormation template and asserts the UI matches the deployed policy, so
> they can't drift apart again. That's the fix I'm most pleased with, because it
> fixes the class of bug rather than the instance."

---

## 10. Cross-references

- [01_Complete_File_Structure.md](01_Complete_File_Structure.md)
- [04_API_And_Handler_Mapping.md](04_API_And_Handler_Mapping.md)
- [06_How_To_Modify_LifeLink.md](06_How_To_Modify_LifeLink.md)
- [../06_FEATURE_IMPLEMENTATION/05_Temporary_Reservations.md](../06_FEATURE_IMPLEMENTATION/05_Temporary_Reservations.md)
