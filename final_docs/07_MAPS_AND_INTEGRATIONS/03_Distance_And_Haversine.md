# Distance and the Haversine Formula

Two kinds of distance, kept deliberately separate, and the formula that
computes one of them.

---

## 1. Two distances, never conflated

| | Straight-line | Road |
|---|---|---|
| Also called | great-circle, "as the crow flies" | driving distance |
| Computed by | **haversine**, locally in Python | **Amazon Location route calculator** |
| Needs a network call | **no** | **yes** |
| Always available | **yes** | no |
| Used for | search filtering and ranking | "how long will it take me to get there" |
| API field | separate | separate |

**They are separate fields throughout the API so they can never be
conflated.** A straight-line distance of 5 km can be a 12 km drive around a
river.

**If routing fails, the UI says directions are unavailable. It never
substitutes the straight-line figure and calls it a drive.**

**Say this:**
> "We keep them as two separate fields all the way through the API, because
> they're different facts. Straight-line distance comes from the haversine
> formula and is always available, so it drives the search and the ranking. Road
> distance and ETA come from Amazon Location and need a network call — and if
> that fails we say directions are unavailable rather than quietly showing the
> straight-line number as a drive. A wrong distance looks exactly like data."

---

## 2. What haversine is

**The problem.** The earth is roughly a sphere. Pythagoras on latitude and
longitude is wrong, and gets worse with distance and with latitude — because a
degree of longitude is about 111 km at the equator and zero at the poles.

**The haversine formula** gives the great-circle distance between two points on
a sphere, and is numerically stable for small distances (which the older
spherical law of cosines is not).

```python
# backend/src/domain/geo.py
EARTH_RADIUS_KM = 6371.0088

def haversine_km(a, b):
    ...
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))
```

### The formula

```
a = sin²(Δφ/2) + cos φ₁ · cos φ₂ · sin²(Δλ/2)
d = 2R · asin(√a)
```

where φ is latitude in radians, λ is longitude in radians, and R is the
earth's radius.

**In words:** convert both points to radians, take the differences, combine
them with a weighting by the cosines of the latitudes — which is what corrects
for longitude lines converging — then take an arcsine and scale by the radius.

### Why `6371.0088` specifically

That is the **mean earth radius** in kilometres as defined by the
International Union of Geodesy and Geophysics. It is a sphere approximation —
the earth is an oblate spheroid, about 21 km wider at the equator than pole to
pole.

**The accuracy consequence, stated honestly:** haversine on a sphere is
accurate to roughly **0.5%**. Over 20 km that is about 100 m. For "which blood
bank is nearer", that is irrelevant. For surveying it would not be, and
`Vincenty` or `Karney`'s ellipsoidal methods would be used instead.

**Being able to state the error and why it does not matter is better than
quoting the formula.**

---

## 3. Where it is used

### Filtering a geohash search to the true circle

**This is the essential use, not an optional refinement.**

```
1. choose_precision(radius_km)      -> 4, 5 or 6
2. search_cells(lat, lon, radius)   -> the geohash cells covering the circle
3. Query each cell by GSI           -> candidates
4. haversine_km(origin, candidate)  -> FILTER to the true circle
```

**Geohash cells are rectangles that over-cover the circle.** Without step 4, a
20 km search would return a facility **28 km away** in the corner of a cell.

> **The index narrows the candidates; the formula gives the correct answer.**

### Supporting functions in `geo.py`

| Function | Purpose |
|---|---|
| `haversine_km(a, b)` | the distance |
| `within_radius(center, point, radius_km)` | a boolean convenience |
| `_cell_intersects_circle(...)` | prunes cells that cannot contain a match **before** querying them |
| `MAX_SEARCH_RADIUS_KM = 100.0` | the guard — `search_cells` raises above it |

**`_cell_intersects_circle` is the optimisation worth mentioning:** it uses the
same geometry to skip cells entirely, so the number of index queries is smaller
than the naive covering set.

---

## 4. Ranking uses distance, but not only distance

`backend/src/domain/ranking.py` combines:

| Input | Why |
|---|---|
| **Distance** | nearer is better, other things equal |
| **Availability** | a facility with stock beats one without |
| **Data freshness** | a facility that updated an hour ago is more trustworthy than one three days stale |

**Why freshness belongs in the ranking.** A blood bank 2 km away whose figure
is three days old may well have nothing. One 8 km away that updated an hour ago
is more useful.

**The rule it must not break:** ranking affects **order**, never the **facts**.
`UNKNOWN` is never ranked as though it were zero, and no facility is promoted
by overstating its availability. The honesty rule *dispatch order is not
clinical priority* applies here too — order is a convenience, not a judgement.

---

## 5. Road distance and ETA

`GET /facilities/{facilityId}/route` -> Amazon Location route calculator
`lifelink-dev-routes` (Esri data source).

The API Lambda's role grants `geo:CalculateRoute` on that calculator and
nothing else.

**Why server-side:**

| Benefit | Detail |
|---|---|
| No credential in the browser | the provider credential never leaves AWS |
| Cacheable | a route between two fixed points is reusable |
| One place to change provider | the `adapters/` seam |
| Rate limiting | we control the call volume |

**On failure:** the facility list and contact details survive. Only the
directions field degrades. ADR-0012: *"On routing failure the facility list and
contact details survive, and the UI says directions are unavailable rather than
inventing a distance."*

**OpenRouteService was deliberately not adopted** — ADR-0012 notes a second
provider that cannot be verified end to end adds risk without benefit. The
`RoutingProvider` interface leaves the seam open.

---

## 6. Testing

| Test file | Covers |
|---|---|
| `backend/tests/unit/test_geo_and_ranking.py` | haversine values, geohash encode/decode, cell generation, ranking |
| `backend/tests/unit/test_geo_coverage.py` | that cells genuinely cover the circle, and that the filter removes the excess |
| `backend/tests/integration/test_camp_discovery_radius.py` | radius search against real index queries |

**`test_geo_coverage.py` is the interesting one.** It tests the *property* that
matters — no facility inside the radius is missed, and none outside it is
returned — rather than just checking a few known distances. Testing the
property catches a class of bug that spot-checking does not.

**Say this:**
> "The test I'd point to is the coverage test. It would be easy to test the
> haversine function against a few known distances and call it done. But the
> property that actually matters is that the geohash cells cover the whole
> circle — so nothing inside the radius is missed — and that the haversine
> filter removes everything outside it. That's what we test, because a missing
> cell would silently drop real results."

---

## 7. Status

| Aspect | Status |
|---|---|
| `haversine_km` | `TEST-VERIFIED` |
| Geohash cells + coverage property | `TEST-VERIFIED` |
| Radius guard at 100 km | `TEST-VERIFIED` |
| Ranking | `TEST-VERIFIED` |
| Straight-line distance in responses | `DEPLOYED` |
| Road distance / ETA | `DEPLOYED` — route calculator exists and responds |
| Separation of the two fields | `DEPLOYED` |
| **Directions in a browser** | **NOT VERIFIED** by a person |

---

## 8. Spoken answers

### "How do you calculate distance?" — 30 seconds
> "Two different ways, kept separate. Straight-line distance uses the haversine
> formula, which gives the great-circle distance between two points on a sphere
> — we compute it in Python with the mean earth radius, 6371 kilometres. Road
> distance and ETA come from Amazon Location's route calculator on the server
> side. They're separate fields in the API so they can't be confused, and if
> routing fails we say directions are unavailable rather than showing the
> straight-line number."

### 1–2 minutes
> "Haversine solves a real problem: you can't use Pythagoras on latitude and
> longitude, because a degree of longitude is about 111 kilometres at the
> equator and zero at the poles. Haversine gives the great-circle distance on a
> sphere, and it's numerically stable at small distances where the older
> spherical law of cosines isn't.
>
> We use the mean earth radius, 6371.0088 kilometres. That's a sphere
> approximation — the earth is about 21 kilometres wider at the equator than
> pole to pole — so haversine is accurate to roughly half a percent. Over
> twenty kilometres that's about a hundred metres, which is irrelevant for
> deciding which blood bank is nearer. If this were surveying you'd use an
> ellipsoidal method like Vincenty.
>
> The essential use isn't displaying a number, though — it's filtering. Our
> radius search converts the circle into geohash cells and queries an index for
> each one, but the cells are rectangles that over-cover the circle. So without
> the haversine filter, a twenty-kilometre search would return something
> twenty-eight kilometres away in the corner of a cell. The index narrows the
> candidates; the formula gives the right answer."

---

## 9. Follow-up questions

**"Why not just use Pythagoras?"**
> It would be wrong, and wrong in a way that varies. Latitude degrees are
> roughly constant, but longitude degrees shrink as you move away from the
> equator. At Punjab's latitude, around 30 degrees north, a degree of longitude
> is about 96 kilometres rather than 111 — so flat-plane maths would be off by
> roughly 13% in one axis. Haversine handles it correctly by weighting with the
> cosines of the latitudes.

**"Is haversine accurate enough?"**
> For this purpose, comfortably. It's a sphere approximation, so about half a
> percent error — around a hundred metres over twenty kilometres. That's
> irrelevant for ranking blood banks. And it's worth noting that the *road*
> distance matters far more to a user than that error: a five-kilometre
> straight line can be a twelve-kilometre drive around a river, which is why we
> get road distance from a routing service rather than estimating it.

**"What if routing is unavailable?"**
> The facility list, contact details and straight-line distance all survive —
> only the directions field degrades, and the UI says directions are unavailable.
> We deliberately don't fall back to the straight-line figure labelled as a
> drive, because a wrong distance is worse than a missing one: it looks like
> data.

---

## 10. Cross-references

- [01_Browser_Geolocation.md](01_Browser_Geolocation.md)
- [02_Map_Rendering_And_Tiles.md](02_Map_Rendering_And_Tiles.md)
- [../05_DATABASE_AND_DATA/01_DynamoDB_Data_Model.md](../05_DATABASE_AND_DATA/01_DynamoDB_Data_Model.md) §4
- [../06_FEATURE_IMPLEMENTATION/02_Find_Blood_And_Location.md](../06_FEATURE_IMPLEMENTATION/02_Find_Blood_And_Location.md)
