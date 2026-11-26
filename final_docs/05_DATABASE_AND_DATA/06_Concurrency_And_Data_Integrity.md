# Concurrency and Data Integrity

How LifeLink stops two people reserving the same blood, and the real defect
that showed a correct mechanism can still be used incorrectly.

---

## 1. The problem

Blood units are physical. If two hospitals are both told they have a hold on
the same two units of O-negative, one of them will arrive to nothing — in a
situation where that matters.

**DynamoDB has no transactions across unrelated requests and no row locking.**
Two Lambda invocations can read the same item at the same instant, both decide
there is enough stock, and both write. That is the **lost update** problem, and
it has to be solved explicitly.

---

## 2. The four mechanisms

| Mechanism | Where | Protects against |
|---|---|---|
| **Optimistic concurrency** on `version` | `inventory_repo.py` | two staff editing the same batch |
| **Conditional write** on available units | `reservation_repo.py` | overselling |
| **`TransactWriteItems`** | `reservation_repo.py` | a reservation and its counter diverging |
| **Conditional put** `attribute_not_exists` | `platform_repo.py` | a retried request double-applying |

---

## 3. Optimistic concurrency — inventory batches

Each batch row carries a `version` attribute. An update is conditioned on it:

```
UpdateExpression:     SET availableUnits = :new, version = :nextVersion
ConditionExpression:  version = :expectedVersion
```

**What happens with two concurrent editors:**

```
Staff A reads batch, version 7, sees 12 units
Staff B reads batch, version 7, sees 12 units
Staff A writes: deduct 2, condition version = 7  -> SUCCEEDS, version becomes 8
Staff B writes: deduct 3, condition version = 7  -> FAILS (version is now 8)
```

Staff B receives **`409 CONCURRENT_MODIFICATION`**. `ApiError.isRetryable` is
true for that code, so the UI can offer a retry — which re-reads the current
value and lets them decide again against the truth.

**Why "optimistic"?** Because it assumes conflicts are rare and detects them at
write time, rather than locking the row in advance. For human-paced stock
edits, conflicts genuinely are rare, and a lock would be far more expensive.

**Say this:**
> "Inventory batches use optimistic concurrency. Each row has a version number,
> and an update is conditioned on the version you read. If someone else wrote
> first, the version has moved and your condition fails — you get a 409 saying
> there was a concurrent modification, and the UI offers a retry that re-reads
> the current value. It's called optimistic because it assumes conflicts are
> rare and detects them at write time rather than locking the row up front,
> which for human-paced edits is the right trade."

---

## 4. The reservation pool — the hard one

**Two things must change together:**

1. A new `RESERVATION` row.
2. The `RESERVATION_POOL` row's `heldUnits` counter.

If the reservation were written and the counter missed, units would be held
with nothing tracking them. If the counter moved and the reservation failed,
units would be held for nobody.

**So both go in one `TransactWriteItems`:**

```
Put    reservation row     ConditionExpression: attribute_not_exists(PK)
Update pool heldUnits      ConditionExpression: heldUnits + :units <= availableUnits
```

**All-or-nothing.** If either condition fails, neither write happens.

**The concurrent case:**

```
Hospital A and Hospital B both request the last 2 units simultaneously
Transaction A: condition holds (0 + 2 <= 2)  -> COMMITS, heldUnits = 2
Transaction B: condition fails (2 + 2 > 2)   -> ROLLS BACK entirely
```

Hospital B receives **`NO_UNRESERVED_STOCK`**.

**Verified live:** a second requester against a fully-held pool was refused
with exactly that code.

### Why a counter rather than counting the reservations

Counting rows would mean a `Query` and a sum — which is not atomic, so two
concurrent requests could both count the same stale total. A single counter
updated inside a conditional transaction is atomic by construction.

---

## 5. The defect — a correct mechanism used incorrectly

**This is the most valuable story in the project. Tell it.**

The transaction design was right. The logic deciding *when* to release held
units was not.

```python
# The deployed fix
releases = (
    reservation.status in HOLDING_STATES
    and updated.status not in HOLDING_STATES
)
```

**The original had only the first half** — it asked *"was this reservation
holding units?"* rather than *"does it stop holding units?"*

| Transition | Was holding? | Stops holding? | Original behaviour | Correct |
|---|---|---|---|---|
| `PENDING` -> `CONFIRMED` | yes | **no** (still holding) | **released** — wrong | hold |
| `CONFIRMED` -> `FULFILLED` | yes | yes | released | released |
| `PENDING` -> `CANCELLED` | yes | yes | released | released |

**The consequence:** confirming a reservation **released its own hold**. The
units became available to someone else while the reservation still claimed
them — permitting overselling — and the confirmed hold could then be neither
cancelled nor fulfilled correctly.

### How it was found

**Not by the test suite.** The first live run of `confirm -> cancel` failed.
Over 900 tests were passing at the time.

### How it was fixed and proven

| Step | Detail |
|---|---|
| Root cause | the condition asked the wrong question |
| Fix | add the second clause |
| Regression tests | **6 added; 4 failed against the old code** |
| Live verification | all three transition paths, counters read **directly from DynamoDB** |

**The verified counter sequences:**

| Path | `heldUnits` |
|---|---|
| `PENDING -> CONFIRMED -> FULFILLED` | 0 -> 2 -> 2 -> 0 |
| `PENDING -> CONFIRMED -> CANCELLED` | 0 -> 2 -> 2 -> 0 |
| `PENDING -> CANCELLED` | 0 -> 2 -> 0 |

**`heldUnits` in DynamoDB matched the API's `reservedUnits` at all ten
checkpoints.**

### The lesson to state out loud

> "This is the thing I learned most from. The transaction design was correct —
> two writes, all or nothing, with a condition that prevents overselling. But
> the logic deciding *when* to release the held units asked the wrong question.
> It asked 'was this reservation holding units' instead of 'does it stop holding
> units', and both are true when you confirm a pending hold. So confirming a
> reservation released its own units, which allows overselling.
>
> Nine hundred passing tests didn't catch it. We only found it by exercising the
> deployed system. Then we added six regression tests, four of which fail
> against the old code, and verified all three transition paths live with the
> counters read straight out of DynamoDB rather than from the API, so we weren't
> trusting the thing we were testing.
>
> The general lesson is that a correct mechanism can still be invoked under the
> wrong condition — and a green test suite tells you about the cases you thought
> of."

---

## 6. Idempotency

**ADR-0009.** Stream and queue delivery is **at-least-once**, and clients
retry. So an operation must be safe to apply twice.

**Mechanism:** a conditional put into the `idempotency` table.

```
PutItem  PK = <idempotency key>
         ConditionExpression: attribute_not_exists(PK)
```

The first attempt claims the key. The second fails the condition, and the
handler returns the original result instead of re-applying.

**Where the key comes from.** `frontend/src/api/client.js` sends an
`Idempotency-Key` header on creates that must not double-apply:

| Route | Key pattern |
|---|---|
| `POST /alerts` | `alert-<timestamp>` |
| `POST /facilities/{id}/batches` | `batch-<facilityId>-<timestamp>` |
| `POST /camps/{id}/register` | `reg-<campId>` |
| `POST /emergency-requests` | caller-supplied |

**`reg-<campId>` is the interesting one** — it has no timestamp, so it is
stable. Registering for the same camp twice is idempotent *by the key's design*,
not just within a retry window.

**The table is empty (0 rows), which is correct** — claims expire by TTL on
`expiresAtEpoch`.

---

## 7. The transactional outbox

**ADR-0005.** A domain write and its outbound event commit in **one**
transaction, so an event can never exist for a write that rolled back, and can
never be lost after a write that committed.

The consequence is at-least-once delivery, which is why consumers are
idempotent. The two mechanisms are a pair: the outbox guarantees the event
exists, and idempotency makes duplicate delivery harmless.

---

## 8. Consistency, and where it was handled

| Read | Consistency |
|---|---|
| `GetItem` default | eventually consistent |
| `GetItem` with `ConsistentRead=True` | strongly consistent, 2x cost |
| `Query` on a table | can be strongly consistent |
| **`Query` on a GSI** | **always eventually consistent — no option** |
| `TransactWriteItems` | fully atomic |

**The design consequence:** the reservation pool counter is **never read from
an index.** The pool row is read and written by its exact key inside a
transaction. If it were read from a GSI, the counter could be stale at the
exact moment correctness depends on it.

**That is the right answer to "what about eventual consistency?"** — not "it's
fine", but "here is where it would have mattered, and here is what we did."

---

## 9. One stale row — known limitation §1.15

**Volunteer this if reservations come up.**

One `RESERVATION` row has status `CONFIRMED` but its hold window has passed. Its
effective status is `EXPIRED`.

| | |
|---|---|
| Does it hold units? | **No.** Every pool counter is 0 |
| Does it affect anything? | No |
| Why not fixed? | Settling it means hand-editing production data, which cannot be reproduced by re-seeding |
| How the UI handles it | `isStaleHold()` in `reservationView.js` compares the clock to the status and shows it as expired |

**The design point worth making:** the UI does not trust the stored status
alone. It computes effective status from the clock, which is why a stale row is
a cosmetic inconsistency rather than a user-visible wrong answer. That is also
why the maintenance sweep running every ten minutes rather than every second is
safe.

---

## 10. Spoken answers

### "How do you prevent two people reserving the same units?" — 30 seconds
> "A pool row holds a counter of how many units are currently held, and a
> reservation writes the reservation row and updates that counter in a single
> DynamoDB transaction, conditioned on there still being enough unreserved
> units. If two hospitals request the last two units at once, one transaction
> commits and the other fails its condition entirely — the second requester gets
> `NO_UNRESERVED_STOCK`. We verified that live."

### 1–2 minutes
> "There are two separate problems. For inventory batches it's optimistic
> concurrency: each row has a version number and updates are conditioned on it,
> so a second concurrent editor gets a 409 and the UI offers a retry that
> re-reads the current value.
>
> For reservations it's harder, because two things have to change together — the
> reservation row and a counter tracking how many units are held. Those go in a
> single `TransactWriteItems`, conditioned on `heldUnits` plus the requested
> units not exceeding what's available. All or nothing: if the condition fails,
> neither write happens.
>
> And then the honest part. The transaction design was right, but the logic
> deciding *when* to release held units was wrong. It asked 'was this
> reservation holding units' instead of 'does it stop holding units' — and both
> are true when you confirm a pending hold, so confirming a reservation released
> its own units. That allows overselling. Over nine hundred tests were passing;
> we found it by exercising the deployed system. We added six regression tests,
> four of which fail against the old code, and verified all three transition
> paths live with the counters read directly out of DynamoDB rather than through
> the API."

---

## 11. Follow-up questions

**"Why not just lock the row?"**
> DynamoDB has no row locking, and that is a deliberate design choice on
> AWS's part — a distributed lock needs a lock holder, and that becomes a
> bottleneck and a failure mode. Conditional writes achieve the same safety
> without one: instead of preventing the conflict, you detect it at write time
> and reject the loser.

**"What if the transaction partially fails?"**
> It cannot. `TransactWriteItems` is atomic — either every item is written or
> none is. That is the whole reason to use it rather than two separate updates.
> The trade-off is that it costs twice the write units of a plain write and is
> limited to 100 items.

**"How did you verify the counters without trusting your own API?"**
> We read `heldUnits` **directly from DynamoDB** with the AWS CLI and compared
> it to what the API reported as `reservedUnits`, at ten checkpoints across the
> three transition paths. They matched at every one. Reading only through the
> API would have meant trusting the thing under test.

**"Is there any case you still can't handle?"**
> A genuine race between the maintenance sweep expiring a hold and a user
> confirming it in the same instant. Both are conditional writes, so one loses
> cleanly rather than corrupting anything — but which one wins is timing. The
> outcome is always consistent; it is just not deterministic. And there is the
> one stale `CONFIRMED` row from before the fix, which holds nothing and which
> the UI already displays as expired.

---

## 12. Cross-references

- [01_DynamoDB_Data_Model.md](01_DynamoDB_Data_Model.md)
- [05_Database_Access_Patterns.md](05_Database_Access_Patterns.md)
- [../06_FEATURE_IMPLEMENTATION/05_Temporary_Reservations.md](../06_FEATURE_IMPLEMENTATION/05_Temporary_Reservations.md)
- [../08_SECURITY_AND_RELIABILITY/05_Error_Handling_And_Retries.md](../08_SECURITY_AND_RELIABILITY/05_Error_Handling_And_Retries.md)
- Full post-mortem: `docs/RESERVATION_COUNTER_DEFECT.md`
- `docs/KNOWN_LIMITATIONS.md` §1.15
