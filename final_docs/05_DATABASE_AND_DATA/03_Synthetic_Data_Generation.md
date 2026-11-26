# Synthetic Data Generation

Where LifeLink's demonstration data comes from, how it is made, and the honest
statement about what it is not.

---

## 1. The statement that must come first

**Every organization, facility, batch, camp, request and user in LifeLink is
invented.** There is no verified institutional dataset in this project.

From the generator's own docstring:

> There is NO verified institutional dataset for this project. Every
> organization, facility, batch, camp and request created here is invented.
> Coordinates are plausible locations in Punjab and Chandigarh; the
> institutions at them are not real and are not partners.

**Say this early and plainly if asked about the data.** It is the single most
important honesty point in the project, because a system that displays blood
availability could cause real harm if someone mistook synthetic figures for
real ones.

The deployed site reinforces it in three places:

- `<meta name="robots" content="noindex, nofollow">`
- The page description says "Demonstration environment with synthetic data."
- `GET /health` returns `"demoEnvironment": true`
- Every seeded record carries `demoData: true`, `dataSource: "SYNTHETIC"`,
  `environment: "DEVELOPMENT"`

### Why the data is synthetic — and it was not for lack of trying

Real Punjab blood bank data was attempted from public sources. **The sources
were unreachable.** Rather than invent plausible-looking details and present
them as real institutions — which would be worse than obviously synthetic data
— the dataset was kept clearly fictional and the attempt documented in
`docs/REAL_FACILITY_DATA.md`.

**Say this:**
> "All the data is synthetic, and I want to be clear about that up front,
> because a site showing blood availability could do real harm if someone
> thought the numbers were real. We did try to use real Punjab blood bank data
> from public sources, and the sources weren't reachable. The alternative would
> have been inventing plausible details and labelling them as real institutions,
> which is worse than obviously fake data. So the coordinates are real places in
> Punjab and Chandigarh, and the institutions at them are invented and marked as
> such — every record carries a `demoData` flag."

---

## 2. Two scripts, two jobs

**The distinction matters and is a likely question.**

| Script | Job | Writes to |
|---|---|---|
| `scripts/seed_demo.py` | **generates** the dataset | local DynamoDB |
| `scripts/seed_cloud.py` | **uploads** it to AWS | `lifelink-dev-*` tables |

`seed_demo.py` defaults to a **local** endpoint (`http://localhost:8000`) and
placeholder credentials, set at import time. `seed_cloud.py` imports the
generation logic and then **deliberately clears** those placeholders before
talking to real AWS:

```python
# AFTER any seed_demo import, never before: that module sets a localhost
# endpoint and placeholder credentials at import time, which is correct for the
# local path and fatal here.
os.environ.pop("DYNAMODB_ENDPOINT", None)
for _ph in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
    if os.environ.get(_ph) == "local":
        os.environ.pop(_ph)
```

**That comment is worth reading aloud** — it documents an import-order hazard
that would otherwise be a mystifying failure.

---

## 3. The four properties the generator guarantees

| Property | How |
|---|---|
| **Deterministic** | `SEED = 20261115` fixed, plus fixed record ids |
| **Idempotent** | Re-running produces the **same state**, not duplicates |
| **Resettable** | `--reset` wipes demo data first (`wipe_demo_data()`) |
| **Validated** | `--validate` checks the dataset covers every required case |
| **Production-guarded** | `guard_environment()` refuses to run unless local or dev |

### Why determinism matters more than it sounds

A fixed seed means the same facilities, the same batch numbers, the same camp
dates every time. That has three consequences:

1. **Documentation stays accurate.** A screenshot or a documented record id
   still matches after a re-seed.
2. **Demonstrations are reproducible.** The facility you rehearsed on is still
   there.
3. **Idempotency becomes possible.** Fixed ids are what let a second run
   *overwrite* rather than *append*.

**Say this:**
> "The generator uses a fixed random seed and fixed record ids, so it produces
> the same dataset every time. That matters more than it sounds: it means our
> documentation and screenshots stay accurate after a re-seed, the demo I
> rehearsed on is still there, and — most importantly — a second run overwrites
> the same rows rather than creating duplicates."

### The production guard

`guard_environment()` refuses to run unless the environment is local or
development. The cloud uploader goes further: `dedupe_request_events.py` reads
the stack's `Environment` parameter and **refuses outright** if it is not `dev`
or `development`:

```
REFUSING: stack <name> has Environment='prod'.
This script only runs against a development stack.
```

**A delete tool that checks what it is pointed at before acting** is worth
mentioning.

---

## 4. What gets generated

| Entity | Live count | Notes |
|---|---|---|
| Organizations | **62** | blood banks, hospitals, camp organizers, in various verification states |
| Facilities | **16** | including named `SHOWCASE_FACILITIES` |
| Inventory batches | **487** | the largest table — every blood group x component, with varied freshness |
| Camps | **46** | across statuses and dates |
| Donations | **14** | recorded and verified |
| Emergency requests | **11** | across lifecycle states |
| Provider responses | **13** | |
| Request events | **35** | 10 seeded + 25 genuine |
| Alerts | **4** | |
| Notifications | **18** | |
| Reservations | **9** + 5 pools | |
| **Total rows** | **742** | across all 12 tables |

Geography: `CITIES` covers locations in **Punjab and Chandigarh** with
plausible real coordinates — Patiala, Ludhiana, Amritsar and others.

### The dataset is designed to exercise edge cases, not to look tidy

**This is the point most worth making about the data design.** A dataset where
everything is `AVAILABLE` and `FRESH` demonstrates nothing. The generator
deliberately includes:

| Case | Why it must exist |
|---|---|
| `UNKNOWN` availability | to prove "unknown is not zero" renders as "Not reported" |
| `NOT_STOCKED` | a facility that does not carry a component at all — different from having none |
| Batches at every freshness level | `FRESH`, `AGING`, `STALE`, `OUTDATED` |
| Updated-but-unverified records | to show the two badges are independent axes |
| Organizations pending verification | so the admin dashboard has something to approve |
| A suspended user account | so the `403 ACCOUNT_SUSPENDED` path is demonstrable |
| Emergency requests mid-lifecycle | so the dispatcher and provider queue have work |
| Expired and cancelled reservations | so the full lifecycle is visible |
| Camps full, open, cancelled | so capacity logic shows |

**Say this:**
> "The dataset is deliberately messy. If every facility showed available and
> fresh stock, it would demonstrate nothing. So there are facilities with
> unknown availability, facilities that don't stock a component at all,
> batches at every freshness level, records that were updated but never
> verified, organizations still awaiting verification, and a suspended account —
> because that's the only way to show the 403 for a suspended user. The data
> exists to exercise the edge cases, not to look tidy."

---

## 5. The seeded-event bug — a real lesson in key design

**Worth telling, because it is a genuine design lesson rather than a typo.**

Two code paths write request events:

```python
# backend/src/repositories/emergency_repo.py — the APPLICATION. Correct.
"SK": f"EVENT#{to_iso(now)}#{uuid4()[:8]}"

# scripts/seed_demo.py — the SEEDER. This was the bug.
"SK": f"EVENT#{iso(created_at)}#seed0001"
```

The `seed0001` suffix was fixed, but the **timestamp came from the run clock**.
So each seed run produced a **new sort key** for the same logical event instead
of overwriting the old one.

**The visible symptom:** five seed runs against `lifelink-dev` left
`demo-req-p1-1` carrying **five `REQUEST_CREATED` events**, and the emergency
tracking page — which sorts by sort key and renders every entry — showed
"REQUEST CREATED" five times.

**The fix:**

```python
def seed_event_sk(ordinal: int = 0) -> str:
    return f"EVENT#{ordinal:04d}#seed0001"
```

`EVENT#0000#seed0001` is **deterministic**, so a re-run overwrites. It still
sorts ahead of any ISO year, because `"0" < "1".."9"`. And `occurredAt` keeps
its realistic value, since that is what the API returns.

### Why `append_event` was deliberately NOT changed

**This is the important half.** The application's event writer stays
append-only, because **real history must accumulate**. Making it deterministic
would mean a second genuine event overwrote the first.

Two writers, two different correct behaviours:

| Writer | Key | Behaviour | Correct because |
|---|---|---|---|
| `emergency_repo.append_event` | timestamp + uuid | **appends** | real history must accumulate |
| `seed_demo.seed_event_sk` | fixed ordinal | **overwrites** | re-seeding must be idempotent |

**The live dispatcher proved the distinction during the cleanup** by appending
two genuine events while the duplicate removal was running.

### The cleanup

`scripts/dedupe_request_events.py` removed the rows the old behaviour had
already written. Its predicate is deliberately narrow — **all five** must hold:

1. `entityType` is exactly `REQUEST_EVENT`
2. `demoData` is true
3. The partition key is `REQUEST#demo-req-*`
4. The sort key ends in `#seed0001`
5. **Another row survives for the same request and the same `eventType`**

**Condition 5 is the safety property that matters:** a request can never be
left with no event for a type it had one for, so no timeline loses its history.

Result: **50 duplicates removed, 23 genuine events protected**, with every
delete conditioned on the row still being exactly what was inspected.
`REQUEST_CREATED` per request went from 5 to 1. 30 unit tests cover the
predicate, written from the question *"what must this never delete?"* rather
than *"what should it delete?"* — because the second kind of mistake is
recoverable by re-seeding and the first is not.

---

## 6. §1.20 — genuine event accumulation (do not try to fix this)

**A consequence of re-seeding that must be understood, not deleted.**

Re-seeding revives demo requests into dispatchable states. The live dispatcher
then runs — every minute — and appends **genuine** events with real current
timestamps, while the *seeded* creation event refreshes to the new run's
`occurredAt`.

**The visible oddity:** a timeline can read "created 24 Nov, expired 16 Nov".

**Why it must not be "fixed":**

- Those events are **real history** written by the application. Deleting them
  would mean deleting genuine records.
- Sorting by `occurredAt` instead of sort key would be **worse** — you would
  get a creation event appearing *after* its own expiry.

Recorded as `docs/KNOWN_LIMITATIONS.md` §1.20. A genuine fix would be a
*dataset design* change — seeding requests in terminal states — which would
cost the dispatch and expiry scenarios the demo needs.

**Say this if a teacher spots the odd timeline:**
> "Good catch, and the explanation is more interesting than a bug. Re-seeding
> puts demo requests back into dispatchable states, so our dispatcher — which
> runs every minute — picks them up and writes genuine events with real
> timestamps, while the seeded creation event gets the new run's timestamp. So
> the ordering looks wrong.
>
> We deliberately didn't fix it, for two reasons. Those dispatcher events are
> real application history, so deleting them would mean deleting genuine
> records. And sorting by occurrence time instead of sort key would be worse —
> you'd see a request created after it expired. The real fix is a dataset
> design change, seeding requests in terminal states, and that would cost us the
> dispatch and expiry scenarios we want to demonstrate."

---

## 7. Freshness ages out — the operational consequence

| Threshold | Effect after |
|---|---|
| 48 hours | every facility shows **`Outdated`** |
| 72 hours | every facility shows **"Verification expired"** |

**This is correct behaviour, not a bug.** The system is telling the truth about
data that has not been updated.

**But it means: re-run the seeder shortly before any demonstration.**

```bash
python scripts/seed_cloud.py              # preview, writes nothing
python scripts/seed_cloud.py --apply      # writes
```

**Say this if everything shows Outdated during a demo:**
> "That's the freshness model working. Our thresholds are six hours for fresh,
> twenty-four for aging, forty-eight before we call it outdated, and verification
> has its own seventy-two-hour window. The demo data was seeded more than two
> days ago, so the system is correctly telling you it's stale rather than
> pretending it's current. I'd re-run the seeder before a demo — and honestly,
> a system that quietly showed two-day-old blood stock as current would be the
> actual bug."

---

## 8. Validation

```bash
python scripts/seed_demo.py --validate            # coverage of required cases
python scripts/validate_facility_dataset.py       # validates data/real_facilities.json
```

`backend/tests/unit/test_facility_dataset_validation.py` has **34 tests** on
the curated dataset: coordinate ranges, required fields, no duplicate ids,
plausible values.

`backend/tests/integration/test_seed_idempotency.py` has **17 tests** proving a
second seed run does not duplicate. **5 of the 14 relevant assertions fail
against the pre-fix event key** — which is how we know the test is real.

---

## 9. Spoken answers

### "Where did the synthetic data come from?" — 30 seconds
> "A generator script, `scripts/seed_demo.py`, with a fixed random seed so it
> produces the same dataset every time. It creates 62 organizations, 16
> facilities, 487 inventory batches, 46 camps and the emergency requests — 742
> rows in total. Everything is invented: the coordinates are real places in
> Punjab, the institutions at them are not real and every record is flagged as
> synthetic. A second script uploads it to AWS."

### 1–2 minutes
> "There are two scripts, which is a useful distinction: one generates the data
> locally, and one uploads it to AWS. The generator is deterministic — a fixed
> seed and fixed record ids — which means a re-run overwrites the same rows
> instead of creating duplicates, and our documentation stays accurate.
>
> The data is deliberately messy. If every facility showed available, fresh
> stock, it would demonstrate nothing. So there are facilities with unknown
> availability, facilities that don't stock a component at all, batches at every
> freshness level, organizations awaiting verification, and a suspended account —
> because that's the only way to show the 403 path.
>
> We hit a real bug in the seeding, which taught us something. The seeder built
> its event sort key from the run clock, so each run created a new key instead
> of overwriting — after five runs each demo request had five 'request created'
> events, all displayed. The fix was a deterministic key. But the interesting
> part is that we deliberately did *not* change the application's event writer,
> which stays append-only, because real history has to accumulate. Two writers,
> two opposite correct behaviours."

---

## 10. Follow-up questions

**"Could someone mistake this for real data?"**
> We tried hard to make that impossible. The site is `noindex, nofollow`, the
> page description says it's a demonstration environment with synthetic data,
> `/health` returns `demoEnvironment: true`, and every record carries
> `demoData: true` and `dataSource: "SYNTHETIC"`. The frontend also has a
> provenance component that shows where a record came from, with a rule that
> inventory provenance never inherits from identity provenance — because a demo
> account could in principle enter a real figure, and conflating the two would
> mislabel it.

**"Why 487 inventory batches for 16 facilities?"**
> Because it's eight blood groups times several components times multiple
> batches with different expiry dates and freshness levels. To demonstrate the
> availability matrix and the freshness model, you need coverage across that
> grid, including the gaps — facilities that have nothing of a given type, and
> facilities that have never reported.

**"How do you know re-running the seeder is safe?"**
> Seventeen integration tests prove it. And we know they're real tests, because
> five of the relevant assertions fail against the old event key — the bug they
> were written to catch.

---

## 11. Cross-references

- [04_Database_Seeding_Workflow.md](04_Database_Seeding_Workflow.md)
- [01_DynamoDB_Data_Model.md](01_DynamoDB_Data_Model.md)
- `docs/DEMO_DATA.md`, `docs/REAL_FACILITY_DATA.md`
- `docs/KNOWN_LIMITATIONS.md` §1.20
- [../13_REFERENCE_AND_REVISION/05_Known_Limitations_And_Actual_Status.md](../13_REFERENCE_AND_REVISION/05_Known_Limitations_And_Actual_Status.md)
