# LifeLink — Final Product Sprint Report

**16 November 2026** · Live: **https://d324z37do52g8f.cloudfront.net**
API: `https://uk6itz2a5b.execute-api.ap-southeast-2.amazonaws.com/dev`
Stack `lifelink-dev` · 426150327442 · ap-southeast-2

Statuses: **VERIFIED LIVE** · **DEPLOYED — NEEDS BROWSER CONFIRMATION** ·
**BLOCKED BY AWS ACCOUNT POLICY** · **NOT IMPLEMENTED**

---

## 1. The map — exact root cause, with evidence

**Status: DEPLOYED — NEEDS BROWSER CONFIRMATION**

### The cause

**`maplibre-gl` v6 removed the default export.** Its ESM build exposes only
named exports (`Map`, `Marker`, `Popup`, `NavigationControl`). The component
did:

```js
import('maplibre-gl').then(({ default: maplibregl }) => {
  new maplibregl.Map({ ... })        // maplibregl is undefined → TypeError
```

`maplibregl` was `undefined`, so `new maplibregl.Map(...)` threw
`TypeError: Cannot read properties of undefined (reading 'Map')`, which the
component reported as *"The map library could not be loaded."*

**When it broke:** I upgraded maplibre-gl **4.7.1 → 6.18.0** to fix a critical
XSS advisory. v4 *did* have a default export. The map code was written for v4
and the upgrade silently broke it.

### Four pieces of evidence, not a guess

1. `node_modules/maplibre-gl/dist/maplibre-gl.mjs` contains **no `as default`**
   — only `rI as Map`, `bI as Marker`, `BI as Popup`, `aI as NavigationControl`.
2. A test that imports the real package the way the component does:
   `const { default: legacy } = await import('maplibre-gl')` → `legacy` is
   `undefined`, and `new legacy.Map({})` throws `TypeError`. **4 tests, all
   passing.**
3. **The old deployed chunk did not contain the library.** Because nothing
   referenced a named export, Rollup tree-shook almost all of it away:
   `maplibre-gl-E7lpPiJc.js` was 483,987 bytes and **`as Map` was absent**.
4. After the fix the chunk is **1,114,521 bytes and `as Map` is present**.
   The bundle size more than doubling is the diagnosis confirming itself.

### What I had wrong before

My earlier hypotheses — CSP, a stale bundle, a 404 chunk, container height —
were **all wrong**, and I checked each against the deployed site before
discarding it. The missing MapLibre stylesheet was a *real second bug* (built
CSS went 24 KB → 99 KB) but it was never the cause of the fallback.

The reason this took three attempts is that the component **hid the map and
the error together**. That is also fixed: an error now appears as
`Map problem: <reason>` *over* the map, and only a failed chunk load or a
throwing constructor falls back to the list.

### The fix

```js
import('maplibre-gl').then((module) => {
  const maplibregl = module.default ?? module      // works for v4 and v6
  if (typeof maplibregl?.Map !== 'function') throw new TypeError(...)
```

Plus an explicit guard that names what was actually exported, so the next
breaking upgrade produces a diagnosis instead of a euphemism.

### Verified on the deployed site

| Check | Result |
|---|---|
| Live bundle `index-CHVawz_e.js` | contains `tile.openstreetmap.org`, the new guard |
| `maplibre-gl-wLe8ZHKz.js` | **HTTP 200, 1,114,521 bytes** |
| `as Map` in that chunk | **present** (was absent) |
| MapLibre CSS bundled | 99 KB, `maplibregl-canvas` / `-popup` present |
| `tile.openstreetmap.org` tile fetch | HTTP 200 |
| CSP blocking tiles | none — no CSP header is set |

Markers, popups (HTML-escaped), click-through, legend, re-centring, list
toggle and loading state were all built in the previous sprint and ship here.
Basemap remains OpenStreetMap — Amazon Location is still
**BLOCKED BY AWS ACCOUNT POLICY** (`AWS::Location::APIKey` denied by SCP; not
retried).

---

## 2. Explore dashboard — rebuilt

**Status: DEPLOYED — NEEDS BROWSER CONFIRMATION**

You said embedding the full Find Blood form was not acceptable. It is gone.
Each tab is now a dedicated directory view — compact filter bar, map, sortable
list — calling the same APIs.

**Blood banks tab:** 7 statistics (listed, reporting, *not reported — unknown,
not zero*, verified, fresh, aging, stale); filters for name/city, inventory
reporting, verification, freshness; sort by nearest / freshest / name; nearest
highlighted; actions for Details and Request blood.

**Donation camps tab:** 7 statistics (listed, running now, upcoming, capacity,
*registrations — not attendance*, places left, capacity used); filters for
name/city, status, places-left; sort by nearest / most registered / soonest /
most places; nearest **attendable** camp highlighted.

Two judgements worth stating:

- **"Most registered", not "popular".** Popularity would imply attendance or
  donations; the only datum is registrations. A camp with zero registrations
  is never badged.
- **No "total blood available" figure.** Summing units across facilities with
  different freshness and verification states produces something that looks
  authoritative and means very little.

`/find` and `/camps` still work standalone. The `embedded` prop I added
mid-sprint is removed, along with its now-stale comment.

---

## 3. Also fixed this sprint

- **A `setState` during render** in the new blood-bank tab — the same class of
  bug fixed earlier in FindBloodPage. Caught and moved into `useEffect` before
  it shipped.
- **Dead code removed**: an `UnusedLegacyList` function left behind mid-edit.
- **Fallback list now knows about camps** — it previously said "No facilities
  to plot for this search" while six camps rendered beneath it.

---

## 4. Not implemented

Stated plainly rather than part-built.

| Item | Status |
|---|---|
| **My Activity** (reservations with countdown, request tracking, camp registrations) | **NOT IMPLEMENTED.** The pages exist separately: `/alerts`, `/emergency/:id`, profile, role dashboards |
| **Saved places** | **NOT IMPLEMENTED.** Would need a new DynamoDB access pattern; I did not add persistence without discussing the schema |
| **Notification centre** | **NOT IMPLEMENTED** as a page. `GET /me/notifications` exists and works |
| **Blood-bank reservation management UI** | **NOT IMPLEMENTED.** API complete, authorized, tested — staff still have no screen. Largest functional gap |
| **Homepage redesign / hero copy** | **NOT IMPLEMENTED** |
| **Road distance and ETA display** | **NOT IMPLEMENTED.** Straight-line only, labelled as such; nothing is invented |
| Camp discovery beyond 20 km | Capped, reported as `effectiveRadiusKm` |

Request Blood entry points (navigation, Find Blood results, facility detail,
Explore blood-bank tab) and the four-column footer shipped in the previous
sprint and are unchanged.

---

## 5. Tests, deployment, cost

| Gate | Result |
|---|---|
| Backend | **547 passed** |
| Frontend | **84 passed** (4 new MapLibre export tests) |
| OpenAPI | matches the route table |
| `cfn-lint` | clean |
| Dependency audit | **PASSED** — nothing shipped has a known vulnerability; 8 dev-only |
| Live site / API | HTTP 200 / 200 |

**631 tests.**

**Deployment: frontend only, twice.** The deploy script makes exactly four AWS
calls — `describe_stacks` (read), `describe_key` (read), `s3:put_object`
(frontend bucket), `cloudfront:create_invalidation`. It contains no
`delete_*`, `update_stack`, Lambda or DynamoDB call.

- **No AWS resource created, modified or deleted.** No backend deploy — no
  backend source or template changed since the last one.
- **Cost unchanged: $0.40/month.** CloudFront invalidations are 1 path each,
  within the free 1,000/month.
- No table reset; no record deleted.

**Git:** 11 uncommitted paths, one commit (`6d2a5fc`), **nothing pushed**.

---

## 6. What I need you to check in the browser

Hard-refresh (**Ctrl-F5**) — the asset names changed, so a cached bundle would
hide the fix.

| # | Check | Expected |
|---|---|---|
| 1 | **Find blood** → the map panel | **An actual OpenStreetMap basemap.** This is the fix |
| 2 | If it still fails | It now reads `Map problem: <reason>` **over** the map. Send me that line + console — it names the failure directly |
| 3 | Markers | Navy ● origin, crimson ◆ banks, teal ▲ camps; legend bottom-left; click for a popup; zoom and pan |
| 4 | **Donation camps** map | Camp markers |
| 5 | **Explore** → both tabs | Statistics, compact filters, map, directory — **no Find Blood form** |
| 6 | Explore filters/sorting | Result count updates; "Nearest" and "Most registered" badges |
| 7 | Change origin | Map recentres; distances recalculate |
| 8 | Regression pass | Sign in, reserve units (stock drops), cancel (returns), register for a camp, submit an emergency request |

Items 1–7 are new code I cannot exercise without a browser. Item 8 is
unchanged backend behaviour verified live in earlier sprints, re-listed only
because the bundle changed.
