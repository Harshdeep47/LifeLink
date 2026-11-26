# Showing Maps and Location

The demonstration where **precision in wording matters most**, because the easy
summary is wrong in both directions.

---

## 1. Get the claim right before you start

| ❌ Wrong | ✅ Right |
|---|---|
| "Amazon Location is blocked" | "The **browser tile path** is blocked, because Location **API keys** are denied in this account" |
| "We don't use Amazon Location" | "We use it **server-side** for geocoding and routing; only the browser basemap is OpenStreetMap" |
| "The map doesn't work" | "The map works; its **basemap imagery** comes from OpenStreetMap rather than AWS" |

**Both over-claiming and under-claiming are wrong here.** The resources exist
and work; one specific credential path is denied.

---

## 2. Show that the resources exist and work

```
Amazon Location Service  ->  Maps / Place indexes / Route calculators
```

| Resource | Detail |
|---|---|
| `lifelink-dev-map` | style **`VectorEsriNavigation`**, request-based usage |
| `lifelink-dev-places` | data source **Esri**, `IntendedUse: SingleUse` |
| `lifelink-dev-routes` | data source **Esri** |

**Prove they work, read-only:**

```bash
P="--profile lifelink --region ap-southeast-2"

# The map style resolves with SigV4 credentials
aws location get-map-style-descriptor --map-name lifelink-dev-map /dev/null $P
# {"ContentType": "application/json"}

# Real geocoding
aws location search-place-index-for-text \
  --index-name lifelink-dev-places --text "Patiala" --max-results 1 $P
# Summary.DataSource: "Esri",  ResultBBox: [76.4018417, 30.3413895, ...]
```

**Both verified on 24 November 2026.**

**Say this:**
> "The Amazon Location resources are deployed and they work. I just resolved the
> map style descriptor and geocoded Patiala — real Esri data with a bounding
> box. So Amazon Location isn't blocked in our account."

---

## 3. Then explain exactly what IS blocked

**The chain of reasoning is the interesting part:**

> "MapLibre is a **renderer**. It draws tiles; it doesn't supply them, and it
> can't sign AWS requests.
>
> Amazon Location tile requests need SigV4 authentication. So for a browser to
> fetch them, you need either an Amazon Location **API key**, or
> identity-pool credentials plus the Amazon Location auth helper library.
>
> We tried the API key. Creating an `AWS::Location::APIKey` is **denied by our
> account's service control policy** — the error is literally
> `Access denied for operation 'AWS::Location::APIKey'`.
>
> So the browser basemap is OpenStreetMap raster tiles, which need no
> credential, and geocoding and routing still go through Amazon Location
> server-side. That's ADR-0012 superseded by ADR-0019."

### Why this is the best policy-evaluation example in the project

> "It's also my clearest demonstration of how IAM policy evaluation works. A
> service control policy is an **explicit deny at the organization level**, and
> explicit deny comes first — nothing can override it. It didn't matter what our
> own IAM permissions said; the resource creation failed outright and we changed
> the design."

---

## 4. Show the basemap in the code

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

**Prove it in DevTools too:** Network tab -> filter **Img** -> pan the map ->
tile requests to `tile.openstreetmap.org` appear.

**Say this:**
> "You can see it in the Network tab — those are the actual tile requests going
> to OpenStreetMap, not to AWS. And in the config: `maxzoom: 19`, which is one
> of the obligations we meet under their tile usage policy."

### The four obligations, met and visible

| Obligation | How |
|---|---|
| Attribution displayed | in the source definition, and MapLibre's attribution control **left on** |
| No excessive load | **zoom capped at 19** |
| No bulk prefetching | nothing prefetches; tiles load only as a user pans |
| Not a production service | explicitly a demonstration environment |

> "Using OpenStreetMap's public tile servers carries obligations, and I'd rather
> show that we met them than hope nobody asks. Attribution is displayed, we
> deliberately left the attribution control enabled, zoom is capped, and nothing
> prefetches."

---

## 5. Show the server-side integration

```
DevTools -> Network -> use the place search box
  ->  GET /dev/geocode?...  ->  200
```

**Say this:**
> "That's our own endpoint, and behind it the Lambda calls Amazon Location's
> place index. The provider credential never reaches the browser — that's the
> main reason to do geocoding server-side, along with being able to cache and
> rate-limit it.
>
> Road distance and ETA work the same way through `/facilities/{id}/route`."

### The IAM evidence

```
IAM -> lifelink-dev-ApiFunctionRole-... -> Permissions -> ApiFunctionRolePolicy14
```

```json
{ "Action": ["geo:SearchPlaceIndexForText", "geo:SearchPlaceIndexForPosition",
             "geo:CalculateRoute"],
  "Resource": ["arn:...:place-index/lifelink-dev-places",
               "arn:...:route-calculator/lifelink-dev-routes"] }
```

> "Three actions, two named resources. Note there is **no** `geo:GetMapTile`
> here — the API function has no reason to fetch tiles."

### `IntendedUse: SingleUse` — a licensing detail

> "The place index is configured `SingleUse`, which is a **licensing** setting
> rather than a technical one: results may be used for the immediate request and
> not stored. `Storage` would permit caching them and costs more."

---

## 6. `MapReaderRole` — the honest unused resource

```
IAM -> lifelink-dev-MapReaderRole-bmIqIg8VSi3H
```

| Tab | Content |
|---|---|
| **Trust relationships** | `Federated: cognito-identity.amazonaws.com`, `sts:AssumeRoleWithWebIdentity`, **with a condition on our identity pool's `aud`** |
| **Permissions** | 4 read-only `geo:GetMap*` actions on **one** map ARN |

**Say this:**
> "This role was deployed for exactly the browser tile path — it lets a Cognito
> identity exchange its token for temporary AWS credentials scoped to four
> read-only map-tile actions on one map.
>
> It's **never used**, because ADR-0019 replaced the whole approach. It's
> leftover infrastructure from a superseded decision, and it costs nothing.
>
> It's still worth looking at as a federated trust policy, because of that
> condition on `aud`: without it, **any** Cognito identity pool in **any** AWS
> account could assume this role. That's the confused-deputy problem."

**And be careful about one claim:**
> "I should be precise: we know **API keys** are denied. We never tested whether
> the identity-pool-plus-auth-helper path would also be restricted — we didn't
> implement the client side. So I can't tell you that path is blocked, only that
> the API key path is."

---

## 7. Geolocation in the browser

**The question to be ready for:** *"Does the website access the GPS?"*

**Answer: no.**

> "A web page has no hardware access at all. We call
> `navigator.geolocation.getCurrentPosition`, and the **browser** — which is
> native software with OS permissions — asks the user, then asks the operating
> system. The OS works out a position from GPS, nearby Wi-Fi networks, cell
> towers, or the IP address, and hands back a latitude, longitude and accuracy.
> We never learn which method was used."

| Method | Typical accuracy |
|---|---|
| GPS | 5–10 m |
| Wi-Fi | 20–50 m |
| Cellular | 100 m–1 km |
| **IP address** | **1–50 km, often wrong** |

**A practical warning for the demonstration:**
> "If you're demonstrating on a desktop with a wired connection, the browser may
> give an IP-based location tens of kilometres off. That's why we show an origin
> indicator telling the user whether the coordinates came from their device or
> from a place they typed — if the input is wrong and invisible, they'll think
> our results are wrong."

**And the denial path:**
> "If someone denies the permission, nothing breaks. They search for a place
> instead, and the rest of the flow is identical. We treat denial as a normal
> path, not an error, because plenty of people deny location prompts by reflex."

**Also worth noting:** geolocation only works in a **secure context** — HTTPS or
localhost. Our CloudFront distribution redirects all HTTP to HTTPS, so a
security setting is a precondition for the feature working at all.

---

## 8. The honest limits

| Limit | Status |
|---|---|
| Browser Amazon Location tiles | **`NOT-IMPLEMENTED`** — API keys denied |
| Identity-pool tile path | **`NEEDS-VERIFICATION`** — never attempted |
| Map rendering in a real browser | **NOT VERIFIED** by a person — needs WebGL |
| Geolocation permission prompt | **NOT VERIFIED** — a prompt is deliberately outside a page's control |
| Directions in a browser | **NOT VERIFIED** |

**Four of the 12 outstanding manual checks are in this area**, and they cannot
be automated here.

---

## 9. Do not

| Action | Why |
|---|---|
| Create a Location API key | **it will fail** — denied by the SCP. Do not demonstrate a failure you did not plan |
| Change the map style | |
| Delete a Location resource | |
| Change `IntendedUse` on the place index | a licensing setting |
| Make bulk geocoding calls | request-based billing |

---

## 10. Questions and answers

**"How are maps displayed?"**
> MapLibre GL JS renders them in the browser, with basemap tiles from
> OpenStreetMap. We originally planned Amazon Location tiles, but MapLibre can't
> sign AWS requests, so it needs an API key — and creating one is denied by our
> account's service control policy. Geocoding and routing still go through
> Amazon Location server-side.

**"Could you make Amazon Location tiles work?"**
> Possibly, via the other path: identity-pool credentials plus the Amazon
> Location auth helper. We deployed the role for it and never implemented the
> client side, and I'd be honest that we never tested whether the SCP restricts
> that path too.

**"Isn't using OpenStreetMap's servers a problem?"**
> For a production service with real traffic, yes — their policy is clear the
> public tile servers aren't for that. For a demonstration with minimal traffic,
> attribution displayed, zoom capped and no prefetching, it's within acceptable
> use. If this became real, the answers are commercial tiles, self-hosted tiles,
> or solving the Amazon Location credential path.

**"How do you calculate distance?"**
> Two ways, kept as separate fields. Straight-line uses the haversine formula
> locally — great-circle distance on a sphere, mean earth radius 6371
> kilometres. Road distance and ETA come from Amazon Location's route
> calculator. They're separate so they can't be conflated, and if routing fails
> we say directions are unavailable rather than showing the straight-line number
> as a drive.

**"Why does your search return a facility 20 km away when I asked for 20 km?"**
> Because that's correct. We convert the circle into geohash cells, query an
> index for each, and then filter with haversine to the true circle. Without
> that filter the cells would over-cover and we'd return something 28 km away in
> a corner. The index narrows the candidates; the formula gives the right answer.

---

## 11. Cross-references

- [../07_MAPS_AND_INTEGRATIONS/02_Map_Rendering_And_Tiles.md](../07_MAPS_AND_INTEGRATIONS/02_Map_Rendering_And_Tiles.md)
- [../07_MAPS_AND_INTEGRATIONS/01_Browser_Geolocation.md](../07_MAPS_AND_INTEGRATIONS/01_Browser_Geolocation.md)
- [../07_MAPS_AND_INTEGRATIONS/03_Distance_And_Haversine.md](../07_MAPS_AND_INTEGRATIONS/03_Distance_And_Haversine.md)
- [06_Showing_IAM_In_Action.md](06_Showing_IAM_In_Action.md)
- ADR-0012 and ADR-0019 in `docs/ARCHITECTURE_DECISIONS.md`
