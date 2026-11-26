# Map Rendering and Tiles

**The document most likely to be stated wrongly.** Get this precisely right:
Amazon Location is **not** blocked. The **browser tile path** is.

---

## 1. The precise truth, in one table

| Thing | Status | Evidence |
|---|---|---|
| `AWS::Location::Map` `lifelink-dev-map` | **deployed and working** | `describe-map` -> style `VectorEsriNavigation` |
| `AWS::Location::PlaceIndex` `lifelink-dev-places` | **deployed and working** | `search-place-index-for-text "Patiala"` returned Esri data |
| `AWS::Location::RouteCalculator` `lifelink-dev-routes` | **deployed and working** | `describe-route-calculator` -> Esri |
| `get-map-style-descriptor` with SigV4 credentials | **works** | returned `{"ContentType": "application/json"}` |
| **`AWS::Location::APIKey`** | **DENIED by the account's SCP** | `Access denied for operation 'AWS::Location::APIKey'` |
| **Browser basemap** | **OpenStreetMap raster tiles** | `tile.openstreetmap.org` in `FacilityMap.jsx` |
| `MapReaderRole` + identity pool | **deployed but never used** | no identity-pool code in the frontend |

### How to say it

| ❌ Wrong | ✅ Right |
|---|---|
| "Amazon Location is blocked" | "The **browser tile path** is blocked, because Location **API keys** are denied in this account" |
| "We don't use Amazon Location" | "We use it **server-side** for geocoding and routing; only the browser tiles come from OpenStreetMap" |
| "The map doesn't work" | "The map works; its **basemap** comes from OpenStreetMap rather than AWS" |

---

## 2. Why the browser cannot use Amazon Location tiles

**The chain of reasoning, which is the interesting part:**

1. **MapLibre is a renderer.** It draws tiles; it does not supply them, and it
   does not sign AWS requests.
2. **Amazon Location tile requests need AWS authentication** — SigV4 signing.
3. MapLibre cannot sign SigV4 itself. So a browser needs **either**:
   - an **Amazon Location API key**, or
   - **identity-pool credentials** plus the Amazon Location auth helper library.
4. **Creating an API key is denied** by the account's service control policy.
5. The identity-pool-plus-auth-helper path was **not implemented** — and
   `MapReaderRole` still exists from when it was planned.

**ADR-0012** chose Amazon Location tiles via an identity pool. **ADR-0019**
superseded the browser half with OpenStreetMap, keeping geocoding and routing
server-side.

### The SCP refusal, verbatim

```
Access denied for operation 'AWS::Location::APIKey'
```

**This is the clearest demonstration of IAM policy evaluation the project
has.** An SCP is an **explicit deny at the organization level** that no IAM
policy can override. It did not matter what our own permissions said — the
resource creation failed, and the design changed.

---

## 3. What the browser actually renders

`frontend/src/components/FacilityMap.jsx`:

```javascript
source: {
  type: 'raster',
  tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
  attribution:
    '&copy; <a href="https://www.openstreetmap.org/copyright" ...>OpenStreetMap</a> contributors',
},
layers: [{ id: 'osm-tiles', type: 'raster', source: 'osm', minzoom: 0, maxzoom: 19 }],
```

**Raster, not vector.** A consequence worth knowing: a vector style needs a
**glyph (font) endpoint** for text labels, and a raster basemap has none —
which is why the code comments mention it. Labels come from the tile images
themselves.

### The OSM tile usage policy, and how it is honoured

Using OpenStreetMap's public tile servers carries obligations. All four are met
and visible in the code:

| Obligation | How |
|---|---|
| Attribution displayed | in the source definition, and MapLibre's attribution control is **left on** |
| No excessive load | **zoom capped at 19** |
| No bulk prefetching | nothing prefetches; tiles load only as the user pans |
| Not treated as a production service | it is a **demonstration** environment |

**Say this:**
> "The basemap is OpenStreetMap's standard raster tiles, which need no
> credential. That carries obligations under their tile usage policy, and we
> meet them: attribution is displayed and we deliberately left MapLibre's
> attribution control enabled, zoom is capped at nineteen, and nothing
> prefetches — tiles are only fetched as a user actually pans. It's also
> explicitly a demonstration environment, not a production service running on
> someone else's infrastructure."

### Configuration

`VITE_MAP_STYLE_URL` is **empty**, which selects the OSM basemap. From
`frontend/.env.production.example`:

> Optional. Leave EMPTY to use the OpenStreetMap raster basemap, which is what
> the deployed site does. An Amazon Location style URL would need a Location
> API key, and those are denied by this account's service control policy — see
> ADR-0019. Setting this to a style the browser cannot authenticate against
> gives a blank map.

**The seam is left open.** If a signed style URL became available, it is one
environment variable.

---

## 4. What Amazon Location IS used for — server-side

| Use | Resource | Endpoint |
|---|---|---|
| **Geocoding / place search** | `lifelink-dev-places` (Esri, `IntendedUse: SingleUse`) | `GET /geocode` |
| **Routing / ETA** | `lifelink-dev-routes` (Esri) | `GET /facilities/{id}/route` |

The API Lambda's role grants exactly three Location actions:

```json
{ "Action": ["geo:SearchPlaceIndexForText",
             "geo:SearchPlaceIndexForPosition",
             "geo:CalculateRoute"],
  "Resource": ["arn:...:place-index/lifelink-dev-places",
               "arn:...:route-calculator/lifelink-dev-routes"] }
```

**Verified live:** `search-place-index-for-text` for "Patiala" returned real
Esri data with a bounding box.

**Why server-side is better anyway:**

| Benefit | Detail |
|---|---|
| **No credential in the browser** | the provider credential never leaves AWS |
| **Cacheable** | a geocode result can be reused |
| **One place to change provider** | the `adapters/` seam |
| Rate limiting | we control the call volume |

**`IntendedUse: SingleUse`** on the place index is a licensing setting: results
may be used for the immediate request and **not stored**. `Storage` would
permit caching results and costs more. Worth knowing — it is a licensing
constraint, not a technical one.

---

## 5. `MapReaderRole` — deployed but unused

```json
{ "Effect": "Allow",
  "Principal": { "Federated": "cognito-identity.amazonaws.com" },
  "Action": "sts:AssumeRoleWithWebIdentity",
  "Condition": { "StringEquals": {
      "cognito-identity.amazonaws.com:aud": "ap-southeast-2:31685707-..." }}}
```

Permissions: four read-only `geo:GetMap*` actions on one map ARN.

**It is never assumed.** No frontend code touches the identity pool — verified
by grep. It is leftover infrastructure from ADR-0012, and it costs nothing.

**Honest framing:**
> "There's a federated IAM role, `MapReaderRole`, deployed for exactly this
> purpose — it lets a Cognito identity exchange its token for temporary AWS
> credentials scoped to four read-only map-tile actions on one map. It's never
> used, because ADR-0019 replaced the whole browser tile approach. It's leftover
> from a superseded decision. It's also a nice example of a federated trust
> policy if you want to look at one, because it has a condition pinning it to
> our specific identity pool — without that, any Cognito identity pool in any
> AWS account could assume it."

**`NEEDS-VERIFICATION`:** whether the identity-pool-plus-auth-helper path would
*work* under this account's SCP was never tested. Only the API key path was
attempted and refused. **Do not claim the identity pool approach is blocked** —
claim only that API keys are.

---

## 6. Clustering and markers

| Concern | Implementation |
|---|---|
| Clustering | MapLibre source clustering, **keyed by record id** so a record spanning two tiles is drawn once |
| Marker kinds | `KIND_FACILITY` and `KIND_CAMP` — **visually distinguished** |
| Popups | facility or camp summary |
| Pure logic | `components/mapData.js` — testable without WebGL |

### Why the logic is separated

The map needs WebGL and **cannot run in jsdom**, so it cannot be unit tested.
So everything that decides *what* the map shows was pulled out:

```javascript
// The map itself needs WebGL and cannot run in jsdom, but everything that
// decides *what* the map shows is ordinary data transformation -- and that is
// where the mistakes with consequences live: a dropped coordinate, a
// fabricated distance, an availability misread as zero.
```

`toCoordinate` refuses nonsense:

```javascript
// 0,0 is in the Gulf of Guinea and is almost always a missing value
// that survived as a default.
if (lat === 0 && lon === 0) return null
```

**A marker at a nonsensical coordinate is worse than a missing marker, because
it looks like data.** Dropped records are **counted**, so the UI can say how
many were omitted rather than silently losing them.

---

## 7. Failure handling

| Failure | Behaviour |
|---|---|
| OSM tiles unavailable | blank basemap; **markers still render**; fallback message |
| WebGL unavailable | `map-fallback` panel instead of a crash |
| MapLibre worker fails to load | **caught** — `maplibreWorker.test.js` exists because a failed worker once looked like a data problem |
| A record has no coordinate | dropped **and counted** |
| Routing fails | "directions unavailable" — **never an invented distance** |

> **A diagnostic lesson from the project:** a MapLibre worker that failed to
> load looked exactly like a data problem — no markers appeared, so it seemed
> the search had returned nothing. There is now a test pinning the worker setup,
> because the failure mode was misleading.

---

## 8. MapLibre v6 — a version detail that needed a test

v6 **removed default exports**; only named imports work.
`frontend/src/test/maplibreExports.test.js` pins that contract, so an upgrade
cannot silently break the map.

**Worth mentioning as a technique:** a test can pin an API-shape contract that
a version number in `package.json` cannot. The version constrains *which*
library; only a test proves the *shape* you depend on still exists.

---

## 9. Status

| Aspect | Status |
|---|---|
| Map rendering with OSM tiles | `DEPLOYED` |
| Clustering, markers, popups | `DEPLOYED`, pure logic `TEST-VERIFIED` |
| Coordinate validation | `TEST-VERIFIED` |
| Amazon Location place index | **verified live** — Esri data for "Patiala" |
| Amazon Location route calculator | `DEPLOYED`, responds |
| Amazon Location map resource | `DEPLOYED`, style descriptor resolves with SigV4 |
| Browser Location tiles | **`NOT-IMPLEMENTED`** — API keys denied (ADR-0019) |
| Identity-pool tile path | **`NEEDS-VERIFICATION`** — never attempted |
| **Map in a real browser** | **NOT VERIFIED** — needs WebGL and a human |

---

## 10. Spoken answers

### "How are maps displayed?" — 30 seconds
> "MapLibre GL JS renders the map in the browser, with basemap tiles from
> OpenStreetMap. We originally planned to use Amazon Location for the tiles, but
> MapLibre can't sign AWS requests itself, so it needs either an API key or
> identity-pool credentials — and creating a Location API key is denied by our
> account's service control policy. So the basemap is OpenStreetMap, while
> geocoding and routing still go through Amazon Location on the server side."

### 1–2 minutes
> "There are two halves, and it's worth separating them.
>
> The basemap — the actual map imagery — comes from OpenStreetMap's raster
> tiles, rendered by MapLibre. That carries obligations under their usage
> policy, and we meet them: attribution displayed, attribution control left on,
> zoom capped, nothing prefetching.
>
> Geocoding and routing come from Amazon Location, server-side. When you search
> for a place, that's our `/geocode` endpoint calling an Amazon Location place
> index backed by Esri — I verified it returns real data for Patiala. Road
> distance and ETA come from a route calculator the same way.
>
> The reason the tiles aren't from Amazon Location is specific and worth getting
> right: MapLibre is a renderer, not a tile source, and it can't sign AWS
> requests. So browser access to Location tiles needs an API key, and creating
> one is denied outright by our account's service control policy — the error is
> literally 'Access denied for operation AWS::Location::APIKey'. That's
> ADR-0019.
>
> It's actually the best example of policy evaluation I have, because a service
> control policy is an explicit deny at the organization level that no IAM
> policy can override. Our own permissions were irrelevant."

---

## 11. Follow-up questions

**"Could you make Amazon Location tiles work?"**
> Possibly, through the other path: the browser gets temporary AWS credentials
> from the Cognito identity pool and uses the Amazon Location auth helper
> library to sign tile requests. We deployed the role for it, `MapReaderRole`,
> but never implemented the client side. I'd want to be honest that we never
> tested whether the SCP also restricts that path — we only know API keys are
> denied.

**"Isn't using OpenStreetMap's servers a problem?"**
> It would be for a production service with real traffic — their policy is
> clear that the public tile servers aren't for that. For a demonstration with
> minimal traffic, with attribution shown, zoom capped and no prefetching, it's
> within acceptable use. If this became real, the right answers are a commercial
> tile provider, self-hosted tiles, or solving the Amazon Location credential
> path.

**"Why raster rather than vector tiles?"**
> Because that's what OpenStreetMap's free tile service offers. Vector would be
> nicer — crisper at every zoom, restylable, smaller — but it also needs a glyph
> endpoint for the text labels, which a raster basemap doesn't have. The code
> comments mention that, because it's a non-obvious consequence of the choice.

**"What happens if the tiles don't load?"**
> You get a blank basemap but the markers still render, because they come from
> our own API rather than from the tile server. There's also a fallback panel for
> when WebGL isn't available at all. We learned to be careful here: a MapLibre
> worker failing to load once looked exactly like a data problem — no markers —
> so there's now a test pinning the worker setup.

---

## 12. Cross-references

- [01_Browser_Geolocation.md](01_Browser_Geolocation.md)
- [03_Distance_And_Haversine.md](03_Distance_And_Haversine.md)
- [04_External_Integrations.md](04_External_Integrations.md)
- [../09_PRACTICAL_AWS_DEMONSTRATIONS/09_Showing_Maps_And_Location.md](../09_PRACTICAL_AWS_DEMONSTRATIONS/09_Showing_Maps_And_Location.md)
- ADR-0012 and ADR-0019 in `docs/ARCHITECTURE_DECISIONS.md`
- `docs/KNOWN_LIMITATIONS.md` §1.6, §1.8
