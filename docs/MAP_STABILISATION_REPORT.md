# LifeLink — Map Stabilisation Report

**16 November 2026** · Live: **https://d324z37do52g8f.cloudfront.net**
API: `https://uk6itz2a5b.execute-api.ap-southeast-2.amazonaws.com/dev`

---

## 1. Root cause of the worker warning

**Two faults compounding — and the second is why it was so confusing.**

### Fault 1 — MapLibre guesses its worker URL from `import.meta.url`

From the v6 source (`maplibre-gl.mjs`, de-minified):

```js
function tl() {
  let e = import.meta.url;
  if (!/^https?:/.test(e)) return ``;
  let t = e.endsWith(`-dev.mjs`) ? `maplibre-gl-worker-dev.mjs` : `maplibre-gl-worker.mjs`;
  let n = new URL(`./${t}`, e);     // sibling of the library file
  return n.href;
}
async function ll() { let e = An.WORKER_URL || tl(); ... }
```

The library expects `maplibre-gl-worker.mjs` to sit **beside itself**. Vite
bundles the library into our own content-hashed chunk
(`maplibre-gl-wLe8ZHKz.js`), so that resolved to
`/assets/maplibre-gl-worker.mjs` — **a file nothing ever emitted.** The
package ships it in `node_modules/maplibre-gl/dist/`, but nothing copied it
into the build.

### Fault 2 — the SPA fallback turned the 404 into a *successful* HTML response

This is the part that made the error misleading. Measured on the deployed
site, before the fix:

```
GET /assets/maplibre-gl-worker.mjs
  HTTP/1.1 200 OK
  Content-Type: text/html; charset=utf-8
  Content-Length: 699

  <!doctype html><html lang="en">...
```

CloudFront's single-page-app fallback rewrites unknown paths to `index.html`
with **HTTP 200**. So the worker did not get a 404 it could report cleanly —
it got an HTML document with a success status, tried to execute it as a
module, and failed. MapLibre reports that as the generic
*"Worker failed to load. Check that the worker URL is correct."*

### Why the map still worked

The basemap is **raster** (OpenStreetMap tiles). Raster tiles are decoded on
the main thread; the worker handles vector tiles, GeoJSON parsing and
glyph/sprite work. So the worker genuinely failed while everything visible —
tiles, labels, roads, markers, popups — kept working. The warning was
accurate and the map was fine, simultaneously.

**Checked and ruled out:** no CSP header is set; the library chunk serves
correctly (HTTP 200, `text/javascript`); and the error handler was *not*
misreporting — the worker really was failing.

---

## 2. The fix

`src/components/FacilityMap.jsx`, two changes:

```js
import maplibreWorkerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url'
...
if (typeof maplibregl.setWorkerUrl === 'function') {
  maplibregl.setWorkerUrl(maplibreWorkerUrl)
}
```

`?url` makes Vite emit the worker as a real content-hashed asset and hand back
its actual path; `setWorkerUrl` (a public v6 export) tells the library where
it is instead of letting it guess. Set before the first `Map` is constructed,
because the worker pool is created on demand and reads the URL at that moment.

Nothing is suppressed. The error handler is unchanged — it simply has nothing
left to report.

**MapLibre v6 is retained.** No downgrade, so the critical XSS fix that
prompted the v4→v6 upgrade stays in place.

### Verified on the deployed site

| Path | Before | After |
|---|---|---|
| `/assets/maplibre-gl-worker.mjs` (the guess) | 200, **`text/html`**, 699 B | unchanged — nothing requests it now |
| `/assets/maplibre-gl-worker-Boc9pDRP.mjs` | did not exist | **200, `text/javascript`, 519,547 B** |
| First bytes of that file | — | `/** MapLibre GL JS @license 3-Clause BSD...` |
| Bundle reference | — | `index-DLTlZFTd.js` references the hashed worker |

---

## 3. Files modified

| File | Why |
|---|---|
| `src/components/FacilityMap.jsx` | Emit the worker asset; set its URL explicitly |
| `src/test/maplibreWorker.test.js` | **New** — 3 regression tests |

That is the entire change. No other component, no backend, no infrastructure.

---

## 4. Regression tests added

`maplibreWorker.test.js` pins the two things that prevent a silent
recurrence:

1. The worker resolves to a real emitted URL, and **is not** the bare
   `/assets/maplibre-gl-worker.mjs` path the SPA fallback swallowed.
2. `setWorkerUrl` still exists — the fix depends on it, and a future upgrade
   removing it should fail here rather than in a browser.
3. Setting a worker URL does not throw.

These join the 4 export-shape tests from the previous sprint, which caught the
`default` export removal that broke the map entirely.

---

## 5. Test results

| Gate | Result |
|---|---|
| Frontend | **87 passed** (3 new) |
| Backend | **547 passed** |
| Production build | clean; worker emitted at 519.55 kB |
| Dependency audit | **PASSED** — nothing shipped has a known vulnerability; 8 dev-only |
| OpenAPI | matches the route table |
| `cfn-lint` | clean |

**634 tests.**

---

## 6. Deployment

**Frontend only.** 11 files uploaded (the worker is the new eleventh),
CloudFront invalidation `IAMQDSYL4DINK0RCUL7E05H2XI`.

- **No AWS resource created, modified or deleted.** No backend deploy.
- **Cost unchanged: $0.40/month.**
- No DynamoDB table, record, account or reservation touched.
- Nothing pushed to GitHub.

---

## 7. Verified against the live API

### Map data (P1)

Find Blood, O− PRBC, 4 units, 30 km from Patiala:

```
facilities: 5 | numeric coords: True | distinct coords: True
  Urban Estate Donor Centre      30.3473,76.3839   0.89 km  AVAILABLE
  Patiala Community Blood Bank   30.3837,76.3435   6.42 km  AVAILABLE
  Rajindra Civil Blood Centre    30.3556,76.3535   3.65 km  PARTIAL
```

Donation camps, 20 km:

```
camps: 6 | distinct coords: True
  Patiala Railway Colony Camp    30.3398,76.3831   0.36 km  ONGOING
  Thapar Campus Drive            30.3389,76.3800   0.67 km  UPCOMING
  Patiala University Blood Drive 30.3323,76.3773   1.24 km  UPCOMING
```

Every marker has valid, distinct coordinates, and distances are measured from
the requested origin.

### Security and semantics (P3)

| Check | Result |
|---|---|
| Public `/facilities` with a bad token | **200** |
| Protected `/me` with a bad token | **401** |
| Reservation without a token | **401** |
| Anonymous certification | **401** |
| Facility that never reported | `availability=UNKNOWN`, `eligibleUnits=None` |

No authentication, reservation, inventory or camp behaviour changed — no
backend code was touched this sprint.

---

## 8. What still needs your browser

I cannot open a browser, so the console is the one thing I cannot read.
Hard-refresh (**Ctrl-F5**) — asset names changed.

| # | Check | Expected |
|---|---|---|
| 1 | **Find Blood** → map | Basemap renders with **no "Map problem" banner** |
| 2 | Console | No "Worker failed to load"; no uncaught MapLibre errors |
| 3 | Network tab | A request for `maplibre-gl-worker-Boc9pDRP.mjs` returning **200 `text/javascript`** — not `text/html` |
| 4 | Markers | Navy ● origin, crimson ◆ banks, teal ▲ camps; popups on click; zoom and pan |
| 5 | **Donation camps** → map | 6 camp markers, distinguishable from bank markers |
| 6 | Change blood group / radius | List and markers update together |
| 7 | Change location (GPS or city) | Map recentres; distances recalculate; GPS label only after real coordinates |
| 8 | Navigate Find Blood ↔ Camps ↔ back | Map still works; no duplicate initialisation |

---

## 9. Remaining limitations

1. **Browser console unverified** — items in §8. The network-level evidence is
   as far as I can take it from here.
2. **A latent hazard worth knowing about, not fixed:** the SPA fallback
   answers *any* missing asset with `index.html` and HTTP 200. That is what
   disguised this bug, and it will disguise the next missing asset too.
   Restricting the CloudFront custom error response so `/assets/*` returns a
   real 404 would prevent a whole class of confusing failures. That is an
   infrastructure change, so I have not made it — it needs your approval.
3. **Basemap remains OpenStreetMap** — Amazon Location stays
   **BLOCKED BY AWS ACCOUNT POLICY** (`AWS::Location::APIKey` denied by SCP;
   not retried).
4. **Road distance and ETA are not displayed.** Straight-line only, labelled
   as such; nothing invented.
5. Camp discovery capped at 20 km, reported as `effectiveRadiusKm`.
6. Unchanged from previous sprints: no blood-bank reservation management UI;
   no My Activity page; no saved places; the compatibility reference is
   clinically unreviewed — **not for clinical use**.
