# Real facility data

**Status: mechanism complete and tested · no real facility recorded · nothing loaded**

This document covers the request to replace or supplement LifeLink's invented
blood centres with real, publicly-listed ones in Punjab.

---

## 1. What was asked, and what was delivered

| Asked | Delivered |
|---|---|
| Identify real blood banks in Punjab | **Blocked** — see §2 |
| Accurate names, addresses, contacts | **Blocked** — no source could be read |
| Verifiable coordinates | **Blocked**, and see §4 on why "verifiable" is the hard word |
| Record the source of each record | **Done** — mandatory, enforced by a validator |
| Distinguish real from synthetic | **Done** — two independent axes, shown in the UI |
| Never present synthetic stock as real | **Done** — enforced in data *and* in the interface |
| No paid APIs | **Done** — nothing added |

The schema, the validator and the display path are finished and tested, so
adding records is a **data step, not a code step**.

---

## 2. Why no real facility was recorded

Two public sources were identified and both were unreachable from the build
environment on **24 November 2026**:

| Source | Result |
|---|---|
| Punjab State AIDS Control Society — "List of licensed blood centres (Govt.) as on 23-6-2023" (`punjabsacs.punjab.gov.in`) | **HTTP 404** at the indexed URL |
| `publicservicesmap.in`, which mirrors e-RaktKosh records | **DNS resolution failed** (`getaddrinfo EAI_AGAIN`) |

Search-engine result summaries *did* name specific centres — Government
Medical College & Rajindra Hospital Patiala with licence 1318-B, several
Amritsar and Ludhiana centres with e-RaktKosh codes, and others.

**Those were not recorded, deliberately.** A search summary is a description
of a page, not the page. Writing a real hospital's name, licence number and
phone number into a dataset on that basis would mean asserting verifiable
facts about real institutions that nobody verified — which is exactly what the
instruction "do not fabricate facility details or coordinates" rules out. The
honest output of an unreadable source is no record.

**To proceed**, supply either a reachable URL for one of the lists above or a
copy of the document, and the records can be transcribed and validated.

---

## 3. A concern worth stating before real names are added

Adding real institutions to this application makes it **more** hazardous, not
less, and the safeguards in §5 exist because of it.

Today every facility is invented and carries a "(DEMO)" suffix. An invented
name beside "9 units O-negative available" invites nobody to act. A *real*
hospital's name beside the same figure invites someone to drive there, or to
telephone a blood bank about stock it does not have and never reported. The
institution learns about it from the person at its counter.

The project README states plainly that "no real institution is represented".
That is currently a safety property, not merely a disclaimer.

This is not a reason to refuse the request — real locations genuinely make the
map and distance behaviour more meaningful, and the request is reasonable. It
is a reason the safeguards below are mandatory rather than advisory.

---

## 4. Three separate claims, deliberately kept apart

The central design decision. One "Synthetic record" pill cannot answer three
questions that have different answers:

| Axis | Field | Question |
|---|---|---|
| **Identity** | `dataSource` | Is this a real place? |
| **Stock** | `inventoryDataSource` | Are these quantities real? |
| **Position** | `coordinateProvenance` | How precisely is it placed? |

The failure this prevents: a record read from a public registry establishes
that a place **exists**. It says nothing whatever about what is on its shelves
today. Letting a real identity raise the credibility of a synthetic quantity is
the single most damaging thing this feature could do, so stock provenance
**never inherits** from identity provenance.

`frontend/src/components/provenance.js` implements this, and
`inventorySource()` is tested specifically to prove it does not inherit:

```js
// A genuine registry listing must not make stock look reported.
const record = { dataSource: 'PUBLIC_REGISTRY' }
expect(inventorySource(record)).not.toBe(InventorySource.REPORTED_BY_FACILITY)
expect(inventorySource(record)).toBe(InventorySource.UNKNOWN)
```

### On "verifiable coordinates"

No public registry publishes blood-centre coordinates. In practice a
coordinate is one of:

| `coordinateProvenance` | Meaning | Honest to display as |
|---|---|---|
| `SURVEYED` | The facility's own published position | its location |
| `GEOCODED_ADDRESS` | Derived from a printed address | approximate |
| `CITY_CENTROID` | The town centre, because nothing finer was available | indicative only |
| `UNKNOWN` | Not recorded | approximate |

Only `SURVEYED` may be presented as the facility's location. Everything else
causes the interface to say the position is approximate — because a town
centroid presented as a street address is a quiet falsehood that *reads* as
precision. This matters concretely here: the seeder already places synthetic
facilities at real city centroids, and a Patiala facility at the Patiala
centroid once displayed as **0.0 km** from a Patiala search.

Fail closed: an absent value resolves to `UNKNOWN`, never to `SURVEYED`.

---

## 5. The safeguards, and where they are enforced

| Safeguard | Enforced in |
|---|---|
| Every record must carry `sourceName`, `sourceUrl`, `sourceRetrievedOn` | `scripts/validate_facility_dataset.py` |
| A search engine or placeholder URL is not a source | validator |
| `dataSource` must be `PUBLIC_REGISTRY` in this file | validator |
| `inventoryDataSource` must be `SYNTHETIC`; `REPORTED_BY_FACILITY` is refused | validator |
| `coordinateProvenance` must be one of three real values | validator |
| Coordinates must fall inside Punjab (catches transposed lat/lon) | validator |
| `0,0` is refused as a missing value, not a location | validator |
| A listing may never be recorded as LifeLink-`VERIFIED` | validator |
| `facilityId` must be unique | validator |
| Both axes always render together | `DataProvenance.jsx` |
| A real name beside demo stock gets an explicit warning | `DataProvenance.jsx` |
| Only `http(s)` source links become anchors | `citation()` |

### Why a validator rather than care at load time

The dangerous record is not malformed — it is *plausible*. A real-sounding
name with no source and a guessed coordinate loads cleanly, renders cleanly,
and misleads silently. There is no error for the honesty failure, which is why
it is a refusal at the gate instead.

### Run it

```bash
python scripts/validate_facility_dataset.py
```

Exit 0 means loadable. It is offline and read-only: no AWS call, no network
access, no write path.

---

## 6. Procedure to add records

1. **Read the source document directly.** Not a search result, not a cached
   summary.
2. **Transcribe verbatim.** Name exactly as printed. Blank stays blank; never
   fill a gap from memory.
3. **Record `sourceName`, `sourceUrl`, `sourceRetrievedOn`** for every record.
   The URL must be the document the fields were read from.
4. **Set the coordinate and its provenance honestly** (§4). If only the town
   is known, use the town centroid and say `CITY_CENTROID`.
5. **Leave `verificationStatus` unset or `UNVERIFIED`.** Appearing in a
   licence list is not LifeLink confirming the centre operates today.
6. **Set `inventoryDataSource: "SYNTHETIC"`.** Always, in this file.
7. **Validate.** `python scripts/validate_facility_dataset.py`
8. **Do not load into the deployed tables without approval.** No loader is
   provided here on purpose — see §7.

---

## 7. Why there is no loader script

A writer that has never run against anything is dead code of the risky kind,
and this session was explicitly not permitted to deploy or mutate deployed
data. Writing one would have meant shipping an untested write path aimed at a
live database.

When records exist and a load is approved, the load should follow the pattern
already proven in `scripts/seed_cloud.py`: environment guards that inspect the
**real boto3 client** rather than configuration, idempotent conditional writes
keyed on `facilityId`, and no delete path at all. That last point is from
experience — an earlier seeding run reported success while silently writing to
the local database, because a guard checked configuration that was re-set after
the guard ran. A guard on configuration is weaker than a guard on what
configuration produces.

---

## 8. Current state

```
data/real_facilities.json          schema + rules + example · 0 records
scripts/validate_facility_dataset.py   offline validator · exit 0
backend/tests/unit/test_facility_dataset_validation.py   34 tests
frontend/src/components/provenance.js  three-axis logic
frontend/src/test/provenance.test.js   27 tests
frontend/src/components/DataProvenance.jsx   UI, on the facility page
```

61 tests cover this mechanism. **No deployed record was read, written or
changed.**
