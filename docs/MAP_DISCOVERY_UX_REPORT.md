# LifeLink — Map Discovery & Navigation UX Report

**16 November 2026** · Live: **https://d324z37do52g8f.cloudfront.net**
API: `https://uk6itz2a5b.execute-api.ap-southeast-2.amazonaws.com/dev`

Statuses: **VERIFIED LIVE** · **DEPLOYED — NEEDS BROWSER CONFIRMATION** ·
**BLOCKED BY AWS ACCOUNT POLICY** · **NOT IMPLEMENTED**

---

## 1. What changed, and the one design decision worth explaining

Markers were anonymous dots. They now carry their names, cluster when they
crowd each other, and stay in step with the result list in both directions.

### Clustering: native source, DOM rendering

The data goes into a MapLibre GeoJSON source with `cluster: true`, so grouping
is done by the library at every zoom — including the case this was most needed
for: several facilities at nearly identical coordinates, where individual
markers stack and the ones underneath are unreachable.

The *drawing* uses DOM markers built from whatever the source reports as
visible (MapLibre's own "cluster HTML markers" pattern). **That was a
deliberate choice over symbol layers**, for a concrete reason: text in a
symbol layer requires a glyph (font) endpoint, and our raster basemap has
none. Using symbol labels would have meant adding an external font service as
a new runtime dependency — which the brief forbids and which would have been a
poor trade for marker captions.

It also bounds the DOM in the way that matters: a cluster is **one** element
standing in for many points, and only what is on screen is built. The previous
version created an element per record regardless of visibility.

### What it refuses to do

- **Never moves a marker** to reduce overlap. Crowding is solved by
  clustering; a shifted marker is a lie about where something is.
- **Never plots an unusable coordinate.** `toCoordinate` rejects non-numbers,
  out-of-range values and `0,0` (almost always a surviving default). Dropped
  records are **counted and reported** — "2 records could not be placed… they
  are still listed below" — so a map showing 7 against a list of 9 is
  explained rather than mysterious.
- **Never reports a road distance or ETA.** Distances stay straight-line and
  labelled. Directions hands the destination's real coordinates to Google
  Maps rather than claiming a computed route.

---

## 2. Requirements, point by point

### Clustering (§1) — DEPLOYED

Numbered clusters; clicking one calls `getClusterExpansionZoom` and eases to
exactly the zoom that splits it; `clusterMaxZoom: 15` guarantees every record
is individually reachable; blood banks and camps stay distinct; coordinates
untouched.

### Identification (§2) — DEPLOYED

Each pin is a **glyph plus its name**, so nothing must be clicked to find out
what it is. `title` gives the full name and city on hover. Names are truncated
with an ellipsis, never wrapped, and **captions are hidden below 640 px**,
where at that width they collide more than they inform — the glyph, popup,
`title` and clustering all still work.

Popups show category, name, city, a summary and straight-line distance, plus a
Directions link. Blood banks show availability (`9 units`, `Partial — 2
units`, `None in stock`, **`Not reported`** with no number). Camps show status
and `40/150 registered · 110 places left`. All interpolated values are
HTML-escaped.

### Map ↔ list synchronisation (§3) — DEPLOYED

Both directions:

- Clicking a **result card** sets the selection → the map eases to that
  location, the marker takes a highlighted style, and its popup opens.
- Clicking a **marker** calls back to the page → the matching card gets a
  `--selected` outline.
- One popup at a time: selecting another location clears the previous.
- The map's source is rebuilt from the **same filtered array** the list
  renders, so they cannot disagree.

Wired on Find Blood, Donation Camps, and both Explore tabs.

### Directions (§4) — DEPLOYED

`directionsUrl` builds a Google Maps directions link from the destination's
**stored** latitude and longitude. An origin is included **only when one is
genuinely known** (GPS or a chosen place); with none, it is omitted so Google
uses the device's own location rather than LifeLink asserting an origin it
does not have. Available on cards and in popups.

### Controls (§5) — DEPLOYED

Toggles for blood banks, camps and the search-location marker; **Fit results**
(bounds of the current filtered set); **Reset** (back to the search origin);
**List view**; MapLibre's zoom control; a legend naming all four marker types.
Existing filters on both pages are untouched and drive map and list together.

### Responsive (§6) — DEPLOYED

Toolbar and legend wrap; captions drop on narrow screens; popups capped at
260 px so they do not cover a phone; the list toggle gives a compact
alternative. A `ResizeObserver` calls `map.resize()` — without it a map inside
a tab that becomes visible keeps the canvas size it had while hidden.

### Data integrity and performance (§7) — DEPLOYED

Only stored coordinates; nothing invented; unknown never shown as zero;
markers keyed by record id so a record spanning two tiles is drawn once;
markers removed when they leave view; a single `moveend`/`sourcedata`
subscription; the v6 worker fix and OSM attribution preserved.

---

## 3. Files changed

| File | Why |
|---|---|
| `src/components/mapData.js` | **New** — pure data layer: coordinates, summaries, GeoJSON, bounds, directions |
| `src/components/FacilityMap.jsx` | Rewritten internals: clustering source, named pins, popups, toolbar, sync, resize |
| `src/components/FacilityMap.css` | Pins, captions, clusters, toolbar, popups, mobile rules |
| `src/components/ui.css` | Selectable/selected row styles |
| `src/features/discovery/FindBloodPage.jsx` | Card selection + Directions |
| `src/features/camps/CampsPage.jsx` | Marker selects rather than navigating away |
| `src/features/dashboards/BloodBankDashboardTab.jsx` | Selection + Directions |
| `src/features/dashboards/CampDashboardTab.jsx` | Selection + Directions + map selection |
| `src/test/mapData.test.js` | **New** — 40 tests |

No backend, infrastructure, API or schema change. No new dependency.

---

## 4. Tests

| Gate | Result |
|---|---|
| Frontend | **127 passed** (40 new) |
| Backend | **547 passed** |
| Production build | clean; worker emitted at 519.55 kB |
| Dependency audit | **PASSED** — nothing shipped has a known vulnerability; 8 dev-only |

**674 tests.**

The map needs WebGL and cannot run in jsdom, so the new tests target the layer
where consequential mistakes actually live. Among them:

- `UNKNOWN` availability produces `"Not reported"` and the assertion
  `expect(text).not.toMatch(/\d/)` — it must contain **no number at all**.
- `0,0` is rejected, but a genuine zero on **one** axis is kept.
- A missing `straightLineKm` yields `null`, never a fabricated distance.
- `campSummary` must not contain "attend", "popular" or "donat".
- `directionsUrl` omits the origin rather than inventing one.
- A single point gets padded bounds, so fitting does not zoom to maximum.

---

## 5. Deployment and cost

**Frontend only.** 11 files, invalidation `IA133I3JH13HEIJFGPC839MWWI`.

- **No AWS resource created, modified or deleted.** No backend deploy.
- **Cost unchanged: $0.40/month.**
- No table reset; no record, account or reservation touched.
- Nothing pushed to GitHub. MapLibre v6 retained.

### Verified in the deployed bundle

| Marker | Status |
|---|---|
| `lifelink-points` (clustering source) | present |
| `map-cluster`, `map-pin__label` | present |
| `getClusterExpansionZoom` | present |
| `Fit results`, `Not reported`, `straight-line` | present |
| `google.com/maps/dir` | present |
| `could not be placed` (skipped-record notice) | present |
| `maplibre-gl-worker-Boc9pDRP.mjs` | **HTTP 200, `text/javascript`** |

### Regression checks against the live API — VERIFIED LIVE

| Check | Result |
|---|---|
| Public `/facilities` with a bad token | 200 |
| Protected `/me` with a bad token | 401 |
| Reservation without a token | 401 |
| Facility that never reported | `UNKNOWN`, `eligibleUnits=None` |

No authentication, reservation, inventory or camp behaviour changed — no
backend code was touched.

---

## 6. What needs your browser

I cannot open one. Hard-refresh (**Ctrl-F5**) — asset names changed.

| # | Check | Expected |
|---|---|---|
| 1 | **Find Blood** → map | Named pins, not anonymous dots. Captions beside each glyph |
| 2 | Zoom out | Nearby pins merge into a numbered circle |
| 3 | Click a cluster | Zooms to exactly where it splits |
| 4 | Zoom in fully | Every record separates; nothing permanently hidden |
| 5 | Hover a pin | Full name and city as a tooltip |
| 6 | Click a pin | Popup with category, name, city, availability, distance, **Directions** |
| 7 | Click a **result card** | Map centres there, pin highlights, popup opens |
| 8 | Click a different one | Previous selection clears |
| 9 | **Directions** | Google Maps opens at the right coordinates, with your origin if known |
| 10 | Toggles | Blood banks / Camps / Search location hide and show |
| 11 | **Fit results** / **Reset** | Frames all results / returns to the search origin |
| 12 | Change blood group or radius | Map and list change together |
| 13 | **Donation Camps** | Camp pins (▲ teal), distinct from banks (◆ crimson) |
| 14 | Narrow the window to phone width | Captions drop, toolbar wraps, popups do not cover the screen |
| 15 | Console | No worker warning, no uncaught MapLibre errors |

---

## 7. Remaining limitations

1. **Browser-side behaviour unverified** — everything in §6. The bundle-level
   and API-level evidence is as far as I can take it from here.
2. **Basemap remains OpenStreetMap** — **BLOCKED BY AWS ACCOUNT POLICY**
   (`AWS::Location::APIKey` denied by SCP; not retried). Demonstration tile
   source, not production; attribution displayed, no prefetching.
3. **Road distance and ETA are not displayed** — straight-line only.
   Directions opens an external navigator; LifeLink computes no route.
4. **A latent hazard, unchanged and not fixed:** the SPA fallback answers any
   missing asset with `index.html` and HTTP 200. That is what disguised the
   worker bug and would disguise the next missing asset. Restricting the
   CloudFront error response so `/assets/*` returns a real 404 needs your
   approval, being an infrastructure change.
5. **Camp discovery capped at 20 km**, reported as `effectiveRadiusKm`.
6. Unchanged from earlier sprints: **NOT IMPLEMENTED** — blood-bank
   reservation management UI (API complete), My Activity page, saved places,
   notification centre page.
7. The compatibility reference is clinically unreviewed. **Not for clinical
   use.** All records are synthetic and carry a `(DEMO)` suffix.
