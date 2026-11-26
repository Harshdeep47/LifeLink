# Database Seeding Workflow

How to put demonstration data into AWS safely, and the safety properties that
make it safe.

---

## 1. The workflow

```
scripts/seed_demo.py      generates the dataset (deterministic, fixed seed)
        |
        v
scripts/seed_cloud.py     uploads it to lifelink-dev-* tables
        |                 PREVIEW by default; --apply to write
        v
   AWS DynamoDB
```

```bash
# Step 1 — preview. Writes NOTHING.
python scripts/seed_cloud.py

# Step 2 — apply, only after reading the preview.
python scripts/seed_cloud.py --apply
```

**Preview is the default and `--apply` is required to write.** That is the
right way round: the dangerous operation needs the extra word.

---

## 2. What the preview tells you

The preview reports **both** the tables it will write and the tables it will
not touch:

```python
SEEDED_TABLES = (organizations, facilities, inventory, camps,
                 donations, emergency, alerts, notifications)      # 8
UNTOUCHED_TABLES = (reservations, audit, idempotency, outbox)      # 4
```

| Set | Tables | Why |
|---|---|---|
| **Seeded** | 8 | the demonstration dataset |
| **Untouched** | 4 | `reservations` holds state created by *real* use; `audit` is history; `outbox` and `idempotency` are transient |

**Why reporting the untouched set matters.** An operator reading a preview
needs to know what is *not* covered as much as what is. Before this was added,
the preview listed only the tables it wrote — so a reader could reasonably
assume it had accounted for all twelve, and wonder why the numbers did not add
up to the table list.

**`reservations` being untouched is the important one.** It holds reservations
created by actual interaction with the system, including ones made during live
verification. Re-seeding must not disturb them. Verified: after the last seed
run, the reservations table was **identical** — 9 reservations, 5 pools, all
counters 0.

---

## 3. The safety properties

| Property | Mechanism |
|---|---|
| **No delete path** | `seed_cloud.py` has **no** delete capability at all, and its docstring says so |
| **Preview by default** | `--apply` required to write |
| **Idempotent** | fixed ids mean a second run overwrites the same rows |
| **Environment-guarded** | `guard_environment()` refuses anything but local or dev |
| **Marked data** | every row carries `demoData: true`, `dataSource: "SYNTHETIC"`, `environment: "DEVELOPMENT"` |
| **Reports untouched tables** | so the operator knows the scope |

### The deliberate separation of destructive capability

`seed_cloud.py` promises in its own docstring that it has no delete path, **and
that promise is kept literally rather than approximately.** Anything
destructive lives in a separately named script:

| Script | Capability |
|---|---|
| `seed_cloud.py` | write only |
| `dedupe_request_events.py` | **deletes** — and says so in its name |
| `reconcile_showcase_batches.py` | repairs demo batches |

**The principle:** a destructive capability should be visible in the **name** of
the thing that holds it. Someone running `seed_cloud.py` should not have to
read the source to know it cannot delete anything.

**Say this:**
> "The seeder has no delete path at all — that's a deliberate design choice, not
> an omission. If you need to remove something, that's a different script with
> 'dedupe' in the name. The principle is that a destructive capability should be
> obvious from the name of the tool that has it, so nobody runs the seeder
> wondering whether it might wipe something."

---

## 4. Idempotency — and how we know it works

A second run produces the **same state**, not duplicates, because every record
has a **fixed id** derived from the fixed seed. A write to the same `PK`/`SK`
overwrites.

**17 integration tests** in `backend/tests/integration/test_seed_idempotency.py`
prove it. And we know the tests are real: **5 of the relevant assertions fail
against the pre-fix event key** — the exact bug they were written to catch.

### The one place idempotency was broken, and the fix

```python
# BEFORE — the timestamp came from the run clock, so each run made a NEW key
"SK": f"EVENT#{iso(created_at)}#seed0001"

# AFTER — deterministic, so a re-run overwrites
def seed_event_sk(ordinal: int = 0) -> str:
    return f"EVENT#{ordinal:04d}#seed0001"
```

`EVENT#0000#seed0001` still sorts ahead of any ISO year, because
`"0" < "1".."9"`, and `occurredAt` keeps a realistic value since that is what
the API returns.

**Five seed runs before the fix left five `REQUEST_CREATED` events per demo
request**, all displayed on the tracking page because it sorts by sort key and
renders every entry.

---

## 5. The cleanup script, and why its predicate is narrow

`scripts/dedupe_request_events.py` removed the rows the old behaviour had
already written.

**It deletes a row only if all five hold:**

1. `entityType` is exactly `REQUEST_EVENT`
2. `demoData` is **true** — never a row the application or a user created
3. The partition key starts `REQUEST#demo-req-` — the seeder's fixed ids
4. The sort key ends `#seed0001` — a genuine event ends in a random uuid
   fragment and **can never match**
5. **Another row survives for the same request and the same `eventType`**

**Condition 5 is the safety property that matters:** a request can never be
left with no event for a type it had one for, so **no timeline loses its
history.**

Which row is kept, per (request, eventType) group:

- the row with the new deterministic key, if the fixed seeder has been re-run;
  otherwise
- the row with the **earliest `occurredAt`**, because the seeded event is the
  request's creation and the oldest stamp is most faithful to that.

Further protections:

| Protection | Detail |
|---|---|
| Dry-run default | `--apply` required |
| Stack check | reads the stack's `Environment` parameter and **refuses** unless `dev` or `development` |
| Conditioned deletes | each delete is conditioned on the row still being exactly what was inspected, so a concurrent write cannot be clobbered |
| No wildcard, no truncate | no table-level operation, and the scope cannot be widened from the command line |
| Reports skipped rows | anything failing a condition is reported, not silently ignored |

**30 unit tests** cover the predicate, written from the question *"what must
this never delete?"* rather than *"what should it delete?"* — because the
second kind of mistake is recoverable by re-seeding and the first is not.

---

## 6. The order that matters: seed, then clean

**Not obvious, and worth knowing.**

| Order | Result |
|---|---|
| **seed, then clean** | converges in **one pass** |
| clean, then seed | leaves an old-format row that the next seed **duplicates again** |

Because `choose_keeper` prefers the deterministic key, seeding first creates
the canonical `EVENT#0000#seed0001` row, and the cleanup then removes every
old timestamped sibling around it.

**The actual operation performed on 24 November 2026:**

```bash
python scripts/seed_cloud.py --apply            # writes the canonical events
python scripts/dedupe_request_events.py --apply # removes the old duplicates
```

| | Before | After |
|---|---|---|
| `REQUEST_EVENT` rows | 83 | **35** |
| — seeded | 60 | **10** (one per request, all canonical) |
| — genuine | 23 | 25 (*the live dispatcher appended two during the run*) |
| `REQUEST_CREATED` per request | 5 | **1** |
| Requests / responses | 11 / 13 | **unchanged** |
| Reservations | 9 + 5 pools, counters 0 | **identical** |

**50 rows removed, 23 genuine events protected.** Verified live through the API
afterwards.

**That the dispatcher appended two genuine events mid-cleanup is the best
evidence that the predicate was right** — the tool was running against a live
system that was actively writing, and it left the new writes alone.

---

## 7. Before any demonstration

**Demo data ages out.** After 48 hours every facility shows `Outdated`; after
72 hours, "Verification expired". That is the freshness model telling the truth.

```bash
# The one command to run before a demo
python scripts/seed_cloud.py --apply
```

Then verify:

```bash
curl -s https://uk6itz2a5b.execute-api.ap-southeast-2.amazonaws.com/dev/health
# expect {"data":{"status":"ok",...,"demoEnvironment":true},...}
```

**Allow for the dispatcher.** Re-seeding revives demo requests into
dispatchable states, so the dispatcher will append genuine events within a
minute. That is §1.20 and it is expected — see
[03_Synthetic_Data_Generation.md](03_Synthetic_Data_Generation.md) §6.

---

## 8. Local seeding, for development

```bash
python scripts/seed_demo.py              # seed local DynamoDB
python scripts/seed_demo.py --reset      # wipe demo data, then seed
python scripts/seed_demo.py --validate   # check coverage only
```

`seed_demo.py` defaults to a **local** endpoint (`http://localhost:8000`) with
placeholder credentials, set at import time. `--reset` exists only for the
local path — there is no remote equivalent, deliberately.

### The import-order hazard worth knowing

`seed_cloud.py` imports the generation logic from `seed_demo.py`, which means
it inherits those local placeholders. So it clears them **after** the import:

```python
# AFTER any seed_demo import, never before: that module sets a localhost
# endpoint and placeholder credentials at import time, which is correct for the
# local path and fatal here.
os.environ.pop("DYNAMODB_ENDPOINT", None)
for _ph in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
    if os.environ.get(_ph) == "local":
        os.environ.pop(_ph)
```

Without this, a cloud seed would silently try to reach `localhost:8000` with
credentials literally set to `"local"`. **A good example of a comment that
documents a hazard rather than restating the code.**

---

## 9. Spoken answers

### 20–30 seconds
> "Two scripts. One generates the dataset deterministically — fixed seed, fixed
> ids — and one uploads it to AWS. The uploader previews by default and needs an
> explicit `--apply` flag to write anything, and it has no delete path at all.
> It reports both the eight tables it writes and the four it deliberately leaves
> alone, including reservations, because those hold state created by real use."

### 1–2 minutes
> "The safety properties are the interesting part. The uploader previews by
> default — you have to pass `--apply` to write — and it genuinely has no delete
> capability. Anything destructive lives in a separately named script, because a
> destructive capability should be obvious from the name of the tool that has
> it.
>
> It's idempotent, which matters: a second run overwrites the same rows rather
> than duplicating them, because every record has a fixed id. We have seventeen
> integration tests proving that, and we know they're real tests because five
> assertions fail against the old code.
>
> We did have one idempotency bug. The seeder built its event sort key from the
> run clock, so each run created a new key instead of overwriting — after five
> runs each demo request had five 'request created' events, all displayed. The
> fix was a deterministic key, and then a separate cleanup script to remove the
> rows already written.
>
> That cleanup script is the one I'd show, because its delete predicate has five
> conditions and the fifth is the one that matters: it only deletes a row if
> another row survives for the same request and the same event type. So no
> timeline can ever lose its history. It removed fifty duplicates and protected
> twenty-three genuine events — and while it was running, the live dispatcher
> appended two more genuine events, which it correctly left alone."

---

## 10. Follow-up questions

**"What if you ran the seeder against production?"**
> It refuses. `guard_environment()` won't run outside local or development, and
> the cleanup script independently reads the CloudFormation stack's
> `Environment` parameter and refuses if it isn't `dev` or `development` — it
> prints "REFUSING" and exits with a non-zero code. Two independent guards,
> because the consequence is unrecoverable.

**"How do you know the cleanup didn't delete something real?"**
> Three ways. The predicate requires `demoData: true` and a sort key ending in
> `#seed0001`, and a genuine event's key ends in a random uuid fragment, so it
> can never match. Thirty unit tests cover the predicate, written from the
> question "what must this never delete?". And the counts afterwards confirm it:
> twenty-three genuine events before, twenty-five after — because the dispatcher
> added two while we were working — and the requests and responses tables
> unchanged at eleven and thirteen.

**"Why not just delete everything and re-seed?"**
> Because the reservations table holds state created by real interaction with
> the system, including reservations made during live verification, and the
> audit table is history. Wiping and re-seeding would destroy both. Idempotent
> overwriting gets a clean demo dataset without touching anything the
> application itself created.

---

## 11. Cross-references

- [03_Synthetic_Data_Generation.md](03_Synthetic_Data_Generation.md)
- [02_All_Tables_And_Indexes.md](02_All_Tables_And_Indexes.md)
- [../10_LAB_EVALUATION/04_Live_Coding_And_Modification_Demonstrations.md](../10_LAB_EVALUATION/04_Live_Coding_And_Modification_Demonstrations.md)
- `docs/DEMO_DATA.md`, `docs/OPERATIONS_RUNBOOK.md`
