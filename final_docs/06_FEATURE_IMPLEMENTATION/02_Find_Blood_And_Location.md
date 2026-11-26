# Feature 2 — Find Blood and Location

Discovery: how a user finds blood near them, and how a database with no
geospatial index answers "within 20 km".

---

## 1. Objective

Given a location, a blood group and a component, show nearby facilities ranked
so the most useful one is first — where "useful" includes **how much the data
can be trusted**.

---

## 2. The user flow

```
/find
  1. Get a location    -> browser Geolocation API, or a place search
  2. Choose filters    -> blood group, component, radius, verifiedOnly, freshness
  3. Search            -> GET /facilities?lat=&lon=&radiusKm=&bloodGroup=&component=
  4. See results       -> list + map, with availability, freshness, verification
  5. Open a facility   -> /facilities/:id — availability matrix, contact, directions
  6. Request a hold    -> POST /facilities/{id}/reservations
```

**Verified live:** the `verifiedOnly` filter returns 11 facilities and the
`FRESH` filter returns 9, out of 16.

---

## 3. The geohash search — the technical centre of this feature

**The problem.** DynamoDB cannot answer "facilities within 20 km of this
point". There is no geospatial index. It can only answer "items whose
partition key equals this value".

**The solution** (ADR-0004), in `backend/src/domain/geo.py`:

```
1. encode_geohash(lat, lon)        a string whose shared prefix means proximity
2. index the prefix                three GSIs, at precision 4, 5 and 6
3. choose_precision(radius_km)     pick a tier from the radius
4. search_cells(lat, lon, radius)  the cells covering the circle
5. Query each cell                 one Query per cell
6. haversine_km(...)               filter the union to the TRUE circle
```

### Why step 6 is not optional

**Geohash cells are rectangles that over-cover the circle.** Without the
haversine filter, a 20 km search would return a facility **28 km away** in the
corner of a cell.

**The index narrows the candidates; the formula gives the correct answer.** That
sentence is the one to remember.

### Why three precisions

| Precision | Approx cell size | Suits |
|---|---|---|
| 4 (`GSI5-geo4`) | ~39 x 20 km | large radius |
| 5 (`GSI1-geo5`) | ~4.9 x 4.9 km | medium |
| 6 (`GSI2-geo6`) | ~1.2 x 0.6 km | small |

A single precision is either far too coarse for a 2 km search — returning much
of Punjab — or far too fine for a 50 km one, needing hundreds of queries.

### The guard

```python
EARTH_RADIUS_KM = 6371.0088
MAX_SEARCH_RADIUS_KM = 100.0
```

`search_cells` **raises** above 100 km, so an unbounded request cannot become a
table scan.

---

## 4. Ranking — and the rule it must not break

`backend/src/domain/ranking.py` orders results by distance, availability and
**data freshness** together.

**Why freshness belongs in the ranking.** A facility 2 km away whose data is
three days old is less useful than one 8 km away that updated an hour ago. The
first might have nothing; the second you can rely on.

**The rule:** ranking affects **order**, never the **facts**. A facility is
never promoted by overstating its availability, and `UNKNOWN` is never ranked
as though it were zero or as though it were stock.

**Related honesty rule:** *dispatch order is not clinical priority.* The same
discipline applies here — ordering is a convenience, not a judgement.

---

## 5. Straight-line versus road distance

**Two separate fields throughout the API, so they can never be conflated.**

| Field | Source | Always available? |
|---|---|---|
| Straight-line distance | **haversine**, computed locally | **yes** |
| Road distance + ETA | **Amazon Location route calculator** via `GET /facilities/{id}/route` | no |

**If routing fails, the UI says directions are unavailable. It never invents a
distance.** The facility list and contact details survive the failure — a
routing outage degrades one field, not the feature.

**Say this:**
> "We keep straight-line and road distance as separate fields all the way
> through, so they can't be confused. Straight-line comes from the haversine
> formula and is always available. Road distance and ETA come from Amazon
> Location and need a network call — and if that fails, the UI says directions
> are unavailable rather than falling back to the straight-line number and
> labelling it as a drive. A wrong distance looks like data."

---

## 6. The map

| Concern | Implementation |
|---|---|
| Renderer | **MapLibre GL JS v6** |
| Basemap tiles | **`https://tile.openstreetmap.org/{z}/{x}/{y}.png`** |
| Clustering | MapLibre source clustering, keyed by record id |
| Markers | facilities and camps, **visually distinguished** |
| Pure logic | `components/mapData.js` — testable without WebGL |

`toCoordinate` refuses nonsense:

```javascript
// 0,0 is in the Gulf of Guinea and is almost always a missing value
// that survived as a default.
if (lat === 0 && lon === 0) return null
```

**A marker at a nonsensical coordinate is worse than a missing marker, because
it looks like data.**

**Why the basemap is OpenStreetMap and not Amazon Location:** MapLibre cannot
sign SigV4 requests, so Location tiles need an API key — and
`AWS::Location::APIKey` is **denied by the account's SCP** (ADR-0019). Full
treatment in
[../07_MAPS_AND_INTEGRATIONS/02_Map_Rendering_And_Tiles.md](../07_MAPS_AND_INTEGRATIONS/02_Map_Rendering_And_Tiles.md).

---

## 7. The API

| Method | Path | Permission | Anonymous? |
|---|---|---|---|
| GET | `/facilities` | `facility:read` | **yes** |
| GET | `/facilities/{id}` | `facility:read` | **yes** |
| GET | `/facilities/{id}/availability` | `inventory:read:public` | **yes** |
| GET | `/facilities/{id}/route` | `facility:read` | **yes** |
| GET | `/geocode` | `facility:read` | **yes** |

**All five discovery endpoints are anonymous-allowed**, which is a deliberate
product decision: someone urgently looking for blood should not have to create
an account first.

**What anonymity does *not* unlock:** detailed batch data
(`inventory:read:detailed`) and reservations both require authentication.

**`meta` on a search response** carries `effectiveRadiusKm` — the radius
actually used, which may differ from the requested one. Verified live: a camp
search near Patiala reported `effectiveRadiusKm: 20`.

---

## 8. Code locations

| Concern | File |
|---|---|
| Geohash, haversine, cells | `backend/src/domain/geo.py` |
| Ranking | `backend/src/domain/ranking.py` |
| Freshness labels | `backend/src/domain/freshness.py` |
| Search orchestration | `backend/src/services/discovery_service.py` |
| Index queries | `backend/src/repositories/facility_repo.py` |
| Search page | `frontend/src/features/discovery/FindBloodPage.jsx` |
| Facility detail | `frontend/src/features/discovery/FacilityDetailPage.jsx` |
| Reservation form | `frontend/src/features/discovery/ReservationPanel.jsx` |
| Map | `frontend/src/components/FacilityMap.jsx`, `mapData.js` |
| Place search | `frontend/src/components/PlaceSearch.jsx` |
| Location origin indicator | `frontend/src/components/OriginIndicator.jsx` |
| Geolocation hook | `frontend/src/hooks/useGeolocation.js` |

---

## 9. Error and edge cases

| Case | Behaviour |
|---|---|
| Location permission denied | place search offered instead; map still works |
| Radius > 100 km | rejected — `MAX_SEARCH_RADIUS_KM` |
| No facilities in radius | empty state, not an error |
| Facility has `UNKNOWN` availability | **"Not reported"**, no number |
| Routing unavailable | "directions unavailable" — **no invented distance** |
| Coordinate missing or `0,0` | marker dropped **and counted** |
| OSM tiles unavailable | blank basemap; markers still render; fallback message |
| Data older than 48 h | `OUTDATED` badge — correct, not a bug |

---

## 10. Status

| Aspect | Status |
|---|---|
| Geohash search | `DEPLOYED`, `TEST-VERIFIED` |
| Haversine | `TEST-VERIFIED` |
| Ranking | `TEST-VERIFIED` |
| Anonymous search | **verified live** (200) |
| `verifiedOnly` / `FRESH` filters | **verified live** (11 / 9 of 16) |
| Geocoding | **verified live** — Amazon Location returned Esri data for "Patiala" |
| Routing | `DEPLOYED` — route calculator exists and responds |
| Map rendering | `DEPLOYED` with OSM tiles |
| **Browser geolocation by a person** | **NOT VERIFIED** — needs a real browser and a real permission prompt |

---

## 11. Spoken answers

### "How does Find Blood work?" — 30 seconds
> "You give it a location, a blood group and a component. The backend converts
> your search circle into a set of geohash cells, queries an index for each
> cell, and then filters the results with the haversine formula to get the true
> circle — because the cells are rectangles that over-cover it. Then it ranks by
> distance, availability and how recently the data was updated, and returns the
> list with freshness and verification badges."

### 1–2 minutes
> "The interesting problem is that DynamoDB can't answer 'within twenty
> kilometres of here' — there's no geospatial index. It can only match a
> partition key.
>
> So we encode each facility's coordinates as a geohash, which is a short string
> where a shared prefix means things are geographically close, and index that.
> A search works out which geohash cells cover the circle, queries those cells,
> and then filters the union with the haversine formula. That second filter
> isn't optional: the cells are rectangles that over-cover the circle, so
> without it a twenty-kilometre search would return something twenty-eight
> kilometres away in the corner of a cell. The index narrows the candidates; the
> formula gives the right answer.
>
> We keep three indexes at precision four, five and six and pick one from the
> radius, because one precision is either far too coarse for a two-kilometre
> search or needs hundreds of queries for a fifty-kilometre one.
>
> And ranking includes data freshness, not just distance. A blood bank two
> kilometres away whose stock figure is three days old is less useful than one
> eight kilometres away that updated an hour ago."

---

## 12. Follow-up questions

**"What's a geohash, exactly?"**
> An encoding of a latitude and longitude into a single string, where each extra
> character narrows the box it refers to. The useful property is that two nearby
> points share a prefix — so "near each other" becomes "same prefix", which is
> something a key-value database can index and query.

**"Why not use a PostGIS database?"**
> That would genuinely be easier for this one feature — a proper geospatial
> index with a real `ST_DWithin` query. We're on DynamoDB for the other reasons:
> no connection pooling problem with Lambda, and near-zero idle cost. The
> geohash approach is the standard way to get radius search on a key-value
> store, and it works — it's just more code than one SQL function.

**"Does the ranking ever hide a facility?"**
> No. Ranking changes order, never the result set or the facts. A facility with
> unknown availability still appears, still shows 'not reported' with no number,
> and is not ranked as though it had zero stock or as though it had stock. The
> filters can exclude facilities — `verifiedOnly` for instance — but that's the
> user's explicit choice, and the response reports how many matched.

**"What if the user denies location permission?"**
> The flow continues. They can search for a place name instead, which goes
> through our `/geocode` endpoint to Amazon Location, and everything else works
> identically. There's an `OriginIndicator` component that shows where the
> current location came from, so the user knows whether they're looking at their
> GPS position or a place they typed.

---

## 13. Cross-references

- [../07_MAPS_AND_INTEGRATIONS/](../07_MAPS_AND_INTEGRATIONS/) — geolocation, tiles, haversine
- [01_Inventory_Management.md](01_Inventory_Management.md) — where availability comes from
- [05_Temporary_Reservations.md](05_Temporary_Reservations.md) — what happens next
- [../05_DATABASE_AND_DATA/05_Database_Access_Patterns.md](../05_DATABASE_AND_DATA/05_Database_Access_Patterns.md)
- `docs/MAP_DISCOVERY_UX_REPORT.md`
