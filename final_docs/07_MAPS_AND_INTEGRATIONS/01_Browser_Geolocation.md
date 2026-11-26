# Browser Geolocation

How LifeLink learns where the user is — and the crucial point that **the
website never touches GPS**.

---

## 1. The question a teacher will ask

> **"How does the website know the user's location? Does it access the GPS?"**

**The answer is no, and the reason matters.**

A web page has **no access to hardware**. It cannot read GPS, Wi-Fi or the
cellular radio. What it can do is **ask the browser**, and the browser — which
is native software with operating-system permissions — decides whether to
answer.

```
Web page  ->  navigator.geolocation.getCurrentPosition()
                   |
              the BROWSER asks the user for permission
                   |
              the browser asks the OPERATING SYSTEM
                   |
              the OS combines GPS / Wi-Fi / cellular / IP
                   |
              a coordinate is returned to the page
```

**The page receives a latitude and longitude. It never learns how they were
obtained.**

### Say this
> "The website doesn't access GPS — a web page can't touch hardware at all. We
> call the browser's Geolocation API, and the browser asks the user for
> permission and then asks the operating system. The OS works out the position
> from whatever it has — GPS, nearby Wi-Fi networks, cell towers, or just the IP
> address — and hands back a latitude and longitude plus an accuracy figure. We
> never know which method was used, only how accurate it claims to be."

---

## 2. How each positioning method works

| Method | Mechanism | Typical accuracy | Needs |
|---|---|---|---|
| **GPS** | timing signals from 4+ satellites | 5–10 m | clear sky, a GPS chip |
| **Wi-Fi** | nearby network identifiers matched against a database of known access-point locations | 20–50 m | known networks nearby |
| **Cellular** | triangulation from cell towers | 100 m–1 km | a cellular radio |
| **IP address** | a geolocation database lookup | 1–50 km, often **wrong** | nothing |

**The OS chooses, usually combining several.** A laptop indoors typically gets
Wi-Fi positioning; a phone outdoors gets GPS; a desktop on a wired connection
gets IP, which may place it in a different city entirely.

**That last case is the practical risk for a demonstration** — a desktop may
report a location tens of kilometres off. Which is exactly why place search
exists as an alternative.

---

## 3. The implementation

| File | Role |
|---|---|
| `frontend/src/hooks/useGeolocation.js` | wraps `navigator.geolocation` with permission and error states |
| `frontend/src/components/OriginIndicator.jsx` | shows **where the current location came from** |
| `frontend/src/components/PlaceSearch.jsx` | the alternative — search for a place |
| `frontend/src/features/discovery/FindBloodPage.jsx` | uses them together |

### `OriginIndicator` — a small component with a real purpose

It tells the user whether the coordinates in use came from **their device** or
from **a place they typed**.

**Why that matters.** If the browser returned an IP-based location 30 km away
and the user does not realise it, they will think the search results are wrong
rather than that the input was. Showing the origin makes the input visible.

**This also connects to the provenance system.**
`frontend/src/components/provenance.js` exports `coordinateSource(record)` as
one of **three independent axes** — identity, inventory and coordinate
provenance — deliberately kept separate so one is never inferred from another.

---

## 4. Permission states and what happens in each

| State | Behaviour |
|---|---|
| **`prompt`** | the browser shows its permission dialog |
| **`granted`** | coordinates returned |
| **`denied`** | **no coordinates**; place search offered; everything else works |
| Unavailable (no HTTPS, no support) | place search offered |
| Timeout | treated as unavailable |

### Geolocation requires a secure context

`navigator.geolocation` works only on **HTTPS** (or `localhost`). That is a
browser security rule, not ours.

**A relevant consequence:** the deployed site is HTTPS-only — CloudFront's
viewer protocol policy is `redirect-to-https` — so geolocation works there. On a
plain-HTTP origin it would silently be unavailable.

**Good detail to offer:** a security setting on CloudFront is a precondition
for a product feature.

### Denial is a first-class path, not an error

**The design point:** location denial is **not** treated as a failure. The
search works identically with a place-search coordinate. Nothing is disabled,
nothing shows an error — the user simply provides the location a different way.

**Say this:**
> "If someone denies location permission, nothing breaks. They search for a
> place name instead, which goes through our geocode endpoint to Amazon
> Location, and the rest of the flow is identical. We treat denial as a normal
> path rather than an error, because plenty of people deny location prompts by
> reflex and the feature has to work for them."

---

## 5. What happens with the coordinate

```
useGeolocation()  ->  {lat, lon}
      |
api.searchFacilities({lat, lon, radiusKm, bloodGroup, component})
      |
GET /facilities?lat=30.34&lon=76.40&radiusKm=20&...
      |
domain/geo.py  choose_precision -> search_cells -> Query -> haversine filter
```

The coordinate goes to the backend as **query parameters**. It is used to
compute geohash cells and distances.

**It is not stored on the user's record.** A search location is transient
input, not profile data — which matters for a system handling health-adjacent
information. See `docs/PRIVACY_AND_DATA_HANDLING.md`.

---

## 6. Privacy

| Consideration | Position |
|---|---|
| Permission | the **browser** asks; we cannot bypass it |
| Storage | the search coordinate is **not** stored on the user's record |
| Transmission | HTTPS only |
| Precision | used at the precision given; not deliberately degraded |
| Logging | the correlation id is logged, not the coordinate as personal data |

**Honest note:** a coordinate in a query string will appear in the API Gateway
access log's request line context. For a demonstration with synthetic users
that is acceptable; a production system handling real users' locations should
consider whether search coordinates belong in access logs at all.

**Volunteering that is better than being asked.**

---

## 7. Status

| Aspect | Status |
|---|---|
| `useGeolocation` hook | `REPO`, `DEPLOYED` |
| Place-search fallback | `DEPLOYED`; geocoding **verified live** |
| Origin indicator | `DEPLOYED` |
| HTTPS requirement satisfied | **verified** — CloudFront redirects to HTTPS |
| **Real browser permission prompt** | **NOT VERIFIED** — needs a human and a real browser |
| **Denial path in a browser** | **NOT VERIFIED** |

**These are two of the 12 outstanding manual checks**, and they cannot be
automated here: a permission prompt is deliberately outside a page's control,
which is the whole point of it.

---

## 8. Spoken answers

### 20–30 seconds
> "We use the browser's Geolocation API. The page can't touch hardware — it asks
> the browser, the browser asks the user for permission, and then asks the
> operating system, which works out a position from GPS, Wi-Fi, cell towers or
> the IP address. We get a latitude and longitude and an accuracy figure, and
> never learn which method was used. If permission is denied, the user searches
> for a place name instead and everything else works the same."

### 1–2 minutes
> "The important thing is the layering. A web page has no hardware access at
> all — it can't read GPS. It calls `navigator.geolocation`, and the browser,
> which is native software with OS permissions, decides whether to answer. The
> browser prompts the user, then asks the operating system, which combines
> whatever it has: satellite timing for GPS, nearby Wi-Fi network identifiers
> matched against a database, cell tower triangulation, or an IP lookup.
>
> That last one matters practically. A desktop on a wired connection often gets
> an IP-based location that can be tens of kilometres wrong, and the user won't
> know. So we show an origin indicator telling them whether the coordinates came
> from their device or from a place they typed — because if the input is wrong
> and invisible, they'll think our results are wrong.
>
> One more detail: geolocation only works in a secure context, HTTPS or
> localhost. Our CloudFront distribution redirects all HTTP to HTTPS, so that
> security setting is actually a precondition for the feature working at all."

---

## 9. Follow-up questions

**"Can you get the location without asking?"**
> Not accurately. The only location available without permission is derived
> from the IP address, which we'd have to look up server-side and which is often
> wrong by tens of kilometres. The browser deliberately makes precise location a
> permissioned capability, and that's correct — a page that could silently read
> your position would be a serious privacy problem.

**"How accurate is it?"**
> The API returns an accuracy figure in metres alongside the coordinate, and it
> varies enormously: five to ten metres with GPS outdoors, twenty to fifty with
> Wi-Fi, a kilometre or more from cell towers, and potentially tens of
> kilometres from an IP lookup. We use the coordinate at whatever precision we
> get it.

**"Do you store the user's location?"**
> No. The search coordinate is a query parameter, used to compute geohash cells
> and distances, and not written to the user's record. One honest caveat: a
> coordinate in a query string does end up in the API Gateway access log. For
> synthetic demo users that's fine; for real users I'd think about whether
> search coordinates should be in access logs at all.

**"What if someone fakes their location?"**
> They can — the coordinate is just a query parameter, and anyone can send any
> value. It doesn't matter here, because nothing security-relevant depends on
> it. The worst outcome is that someone sees blood banks near a place they
> aren't. If location drove something sensitive, you'd need attestation, which
> the web platform doesn't really offer.

---

## 10. Cross-references

- [02_Map_Rendering_And_Tiles.md](02_Map_Rendering_And_Tiles.md)
- [03_Distance_And_Haversine.md](03_Distance_And_Haversine.md)
- [../06_FEATURE_IMPLEMENTATION/02_Find_Blood_And_Location.md](../06_FEATURE_IMPLEMENTATION/02_Find_Blood_And_Location.md)
- `docs/PRIVACY_AND_DATA_HANDLING.md`
