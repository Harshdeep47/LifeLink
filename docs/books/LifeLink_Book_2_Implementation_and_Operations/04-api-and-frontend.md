<!-- pagebreak -->

# 13. The Router and Handlers

## 13.1 Why not a web framework

The specification discourages unnecessary frameworks and names FastAPI and
Mangum specifically. An API Gateway proxy integration delivers a dictionary and
expects a dictionary back. A route table plus path-parameter matching is all
that stands between those two facts.

{{include:backend/src/handlers/router.py:class Router}}

*Listing 13.1. The router from `backend/src/handlers/router.py`.*

## 13.2 404 and 405 are different answers

`match` returns whether the *path* exists under some other method. A `DELETE`
to a path that only supports `GET` returns 405 with the method named, not a 404
suggesting the path is wrong. Debugging an integration against an API that
conflates the two wastes real time.

## 13.3 Error translation at the edge

{{include:backend/src/handlers/router.py:def dispatch}}

*Listing 13.2. Dispatch and error handling.*

Domain errors map to their declared status and keep their code. Anything else
becomes a generic 500 with a correlation id — the detail goes to the log, not
to the client, because an exception message can disclose internals.

## 13.4 Handlers are thin

{{include:backend/src/handlers/api.py:def adjust_batch}}

*Listing 13.3. A representative handler from `backend/src/handlers/api.py`.*

Parse, call one service method, format. No business rules. A handler that grew
a conditional would be a sign that a rule had escaped the layer that owns it.

## 13.5 Ownership resolvers

{{include:backend/src/handlers/api.py:def _facility_owner}}

*Listing 13.4. An ownership resolver.*

The handler declares how to find the owning organization; the decorator does
the comparison. This is the division that prevents an IDOR: a handler author
cannot forget a check they do not perform.

## 13.6 The route table

{{fact:route_count}} routes, each with a declared permission and a summary used
to generate the OpenAPI document.

{{routes:alert}}

*Table 13.1. The availability-alert routes, extracted from the live table at
build time.*

<!-- pagebreak -->

# 14. The API Surface

## 14.1 Conventions

| Concern | Convention |
|---|---|
| Resource naming | Plural nouns: `/facilities`, `/camps`, `/alerts` |
| Sub-resources | Nested: `/facilities/{id}/batches/{batchId}` |
| Actions that are not CRUD | A verb segment: `/certify`, `/respond`, `/adjust` |
| Status codes | 200 read, 201 create, 204 delete, 4xx client, 5xx server |
| Errors | `{ error: { code, message, details? } }` |
| Pagination | Cursor in `meta.nextCursor` |
| Idempotency | `Idempotency-Key` header on mutating requests |
| Correlation | `X-Correlation-Id` accepted and echoed |

*Table 14.1. API conventions.*

## 14.2 The OpenAPI document is generated

{{fact:openapi_paths}} paths and {{fact:openapi_operations}} operations, produced
by `scripts/generate_openapi.py` from the live route table.

The specification says not to document endpoints that do not exist. Generating
the document from the router makes that structurally impossible, and a
`--check` mode fails if the committed file has drifted:

```bash
python scripts/generate_openapi.py --check
# OpenAPI document matches the route table.
```

*Listing 14.1. Drift detection.*

Each operation carries an `x-lifelink-permission` extension naming the
permission it requires, so the document doubles as an authorization reference.

## 14.3 Error codes

| Code | Status | Meaning | Retry? |
|---|---|---|---|
| `VALIDATION_ERROR` | 400 | Input failed validation | No |
| `UNAUTHENTICATED` | 401 | Missing or invalid token | After signing in |
| `FORBIDDEN` | 403 | Authenticated, lacks permission | No |
| `ACCOUNT_SUSPENDED` | 403 | Valid token, inactive account | No |
| `CROSS_ORGANIZATION_DENIED` | 403 | Resource belongs elsewhere | No |
| `NOT_FOUND` | 404 | No such resource | No |
| `CONCURRENT_MODIFICATION` | 409 | Lost a write race | **Yes** |
| `DUPLICATE` | 409 | Already exists | No |
| `INSUFFICIENT_STOCK` | 409 | Not enough units | No |
| `INVALID_STATE_TRANSITION` | 409 | Illegal lifecycle move | No |
| `CAPACITY_EXCEEDED` | 409 | Camp is full | No |
| `REQUEST_IN_PROGRESS` | 409 | Identical request in flight | After a pause |
| `RATE_LIMITED` | 429 | Throttled | **Yes, with backoff** |
| `CHANNEL_UNAVAILABLE` | 503 | Notification channel not implemented | No |
| `PROVIDER_UNAVAILABLE` | 503 | External provider failed | **Yes** |

*Table 14.2. The complete error taxonomy and which codes are worth retrying.*

<!-- pagebreak -->

# 15. Frontend Architecture

## 15.1 Structure

```
src/
├── api/client.js            the only module that calls fetch
├── auth/AuthContext.jsx     token and principal state
├── components/              Layout, StatusBadges, FacilityMap, ui primitives
├── features/                home, discovery, camps, emergency, alerts,
│                            dashboards, account
├── hooks/useApi.js          data fetching, mutations, geolocation
└── styles/tokens.css        design tokens
```

*Listing 15.1. Frontend layout: {{fact:frontend_modules}} modules,
{{fact:frontend_lines}} lines.*

## 15.2 One network client

{{include:frontend/src/api/client.js:anchor:async function request:50}}

*Listing 15.2. The request function from `frontend/src/api/client.js`.*

Every call goes through here, so the correlation id, the bearer token and the
idempotency key cannot be forgotten by an individual screen. A network failure
becomes a readable message rather than an echo of a fetch internal, and an
abort is re-raised so a superseded request is dropped silently.

## 15.3 Errors carry their code into the UI

```javascript
get isRetryable() {
  return this.status >= 500 || this.status === 0 ||
         this.code === 'RATE_LIMITED' ||
         this.code === 'CONCURRENT_MODIFICATION'
}
```

*Listing 15.3. Retry classification in the client.*

A component can ask whether retrying is sensible without knowing the error
taxonomy.

## 15.4 Data fetching

{{include:frontend/src/hooks/useApi.js:anchor:export function useApiData:45}}

*Listing 15.4. The data hook from `frontend/src/hooks/useApi.js`.*

The abort matters more than it looks. A user typing in a search box generates
overlapping requests; without cancellation a slow earlier response can land
after a faster later one and overwrite fresher results with staler ones.

## 15.5 Geolocation that never traps the user

{{include:frontend/src/hooks/useApi.js:anchor:export function useGeolocation:60}}

*Listing 15.5. Geolocation with every failure mode handled.*

Permission denied, position unavailable, timeout and a missing API are each
mapped to a distinct status and a message that offers the alternative. The
specification requires never forcing precise location when manual search
exists, and a dead end after a declined permission would do exactly that.

<!-- pagebreak -->

# 16. Components and State

## 16.1 Status badges carry the rules

{{include:frontend/src/components/StatusBadges.jsx:anchor:export function AvailabilityBadge:20}}

*Listing 16.1. The availability badge from
`frontend/src/components/StatusBadges.jsx`.*

The unit count renders only when it is a real measurement. An `UNKNOWN` state
shows "Not reported" and no number, because "0 units" would be a claim the
system cannot support.

## 16.2 Freshness and verification are bundled

{{include:frontend/src/components/StatusBadges.jsx:anchor:export function DataQuality:12}}

*Listing 16.2. The paired badge.*

Bundling them in one component makes it awkward to render one without the
other. A developer in a hurry reaches for `DataQuality`, and gets both.

## 16.3 No status relies on colour alone

Every badge has a text label and a distinct glyph in addition to its colour.
The interface works in greyscale and for a colour-blind user, which is a
requirement rather than a nicety for a service used under pressure.

## 16.4 The async state component

{{include:frontend/src/components/ui.jsx:anchor:export function AsyncState:25}}

*Listing 16.3. One place that decides loading, error, empty or content.*

Every data-driven view passes its hook result straight in, so the four states
look and behave the same everywhere, and the error state always offers a retry
and shows the correlation id.

## 16.5 Error boundaries

A class component — React requires one for this — wraps each routed view so a
failure in one panel does not blank the application.

<!-- pagebreak -->

# 17. Routing and Role-Aware UI

## 17.1 Guards are usability, not security

{{include:frontend/src/App.jsx:anchor:function RequireRole:35}}

*Listing 17.1. The role guard from `frontend/src/App.jsx`.*

The refusal message names the required roles, names the roles the account
actually holds, and states explicitly that the server enforces this
independently. A user who edits the URL gets a clear explanation rather than a
broken screen, and learns that circumventing the guard achieves nothing.

## 17.2 Navigation reflects roles

The header renders dashboard links only for roles the user holds. This is
presentation: the backend refuses regardless. But showing a donor a hospital
dashboard link that fails on click is a poor experience, and hiding it is free.

## 17.3 Lazy-loaded dashboards

Dashboards are the heaviest and least-visited screens, so they are code-split.
The production build shows them as separate chunks of 5 to 9 KB gzipped, none
of which a public visitor downloads.

<!-- pagebreak -->

# 18. The Discovery Screen

## 18.1 The application's most important page

{{include:frontend/src/features/discovery/FindBloodPage.jsx:anchor:const { data: results, loading, error, reload }:20}}

*Listing 18.1. The search query from
`frontend/src/features/discovery/FindBloodPage.jsx`.*

The dependency array lists every filter. Changing any of them cancels the
in-flight request and issues a new one.

## 18.2 Three signals per row

Each result shows availability with a unit count, freshness, and verification,
as three distinct badges, plus the ranking explanation. A user deciding whether
to drive somewhere needs all of it, and collapsing it into a single score would
hide the thing that matters most.

## 18.3 Unknown gets its own notice

When any result has unknown inventory, the page adds an explanatory panel. The
badge alone communicates the state; the panel explains what to do about it,
which is to telephone.

## 18.4 A bug worth recording

An early version set state during render to adopt a browser-provided position:

```javascript
// Wrong: setState during render re-enters the component every pass.
if (geo.status === 'granted' && geo.coords) {
  setOrigin(geo.coords)
}
```

*Listing 18.2. The anti-pattern, corrected to an effect.*

React would re-render, the condition would still hold, and it would set state
again. Moving it into a `useEffect` keyed on the geolocation status fixed it.

<!-- pagebreak -->

# 19. Map Rendering and Fallback

## 19.1 The fallback is the default path

{{include:frontend/src/components/FacilityMap.jsx:anchor:export function FacilityMap:28}}

*Listing 19.1. The map component from
`frontend/src/components/FacilityMap.jsx`.*

With no `VITE_MAP_STYLE_URL` configured — the local default — the component
renders a facility list rather than pointing at someone else's tile server.
The fallback is therefore exercised constantly in development, not kept as
untested emergency code.

## 19.2 Lazy loading

MapLibre is 802 KB. It is imported dynamically inside the effect, so a
deployment without a configured map never downloads it, and the production
build confirms it as a separate chunk.

## 19.3 Runtime failures fall back too

The map registers an `error` handler and a failed dynamic import is caught.
Either sets `renderFailed`, which renders the list with a message explaining
what happened. An empty grey rectangle is not an acceptable outcome.
