# Feature 1 — Blood Bank Inventory Management

How blood banks record stock, and why the design is about **honesty** rather
than counting.

---

## 1. Objective

Let a blood bank publish what stock it holds, in a way that a hospital can
trust — including being clear about what the blood bank has *not* told anyone.

**The hard part is not the arithmetic. It is representing uncertainty
truthfully.**

---

## 2. Batches, not totals

Stock is recorded **per batch**, never as a single number.

| Batch attribute | Why it exists |
|---|---|
| Blood group + component | the unit of clinical need |
| `availableUnits` | the count |
| `expiresAt` | **blood expires** — a total of 12 is useless if 8 expire tomorrow |
| `status` | available, quarantined, expired |
| `lastUpdatedAt` | when someone **typed** a number |
| `lastVerifiedAt` | when someone **independently checked** |
| `version` | optimistic concurrency |
| `batchId` | so an audit trail can name *which* units moved |

**487 batches across 16 facilities** — eight blood groups times several
components times multiple expiry dates, including the gaps.

**Say this:**
> "Stock is per batch, not a single total, for two reasons. Blood expires, so
> 'twelve units' means nothing if eight of them expire tomorrow. And an audit
> trail has to be able to say which specific units were deducted — you can't
> audit a number that just went down."

---

## 3. The five availability states

| State | Means | Rendered as |
|---|---|---|
| **`UNKNOWN`** | **never reported** | **"Not reported"** — no number |
| `NOT_STOCKED` | does not carry this component at all | "Not stocked" |
| `UNAVAILABLE` | carries it, has none | "None in stock" |
| `PARTIAL` | some, below a threshold | "Partial — N units" |
| `AVAILABLE` | has stock | "N units" |

### Why `UNKNOWN` and `UNAVAILABLE` must stay distinct

They lead a doctor to **opposite actions**:

| State | What a doctor does |
|---|---|
| "Not reported" | **phone them** — they might have it |
| "None in stock" | **do not phone them** |

**Rendering `UNKNOWN` as 0 would be a lie with clinical consequences.**

Enforced at five levels:

| Level | File |
|---|---|
| Domain | `backend/src/domain/inventory.py` |
| Repository | a missing attribute is **never** coerced to 0 |
| API | `availability: "UNKNOWN"` with `eligibleUnits: null` |
| Frontend | `components/StatusBadges.jsx`, `components/mapData.js` |
| **Tests** | **`test_unknown_is_not_zero.py` — 40 tests** |

```javascript
// frontend/src/components/mapData.js
if (!state || state === 'UNKNOWN') return 'Not reported'
```

**40 tests for one rule looks excessive until you consider the consequence.**
That is a good line to use.

---

## 4. Updated versus verified — two independent axes

**ADR-0003.** Two timestamps, two thresholds, **two separate badges**.

| Axis | Source | Thresholds |
|---|---|---|
| **Freshness** | `lastUpdatedAt` | `FRESH` <= 6 h, `AGING` <= 24 h, `STALE` <= 48 h, `OUTDATED` > 48 h |
| **Verification** | `lastVerifiedAt` | valid **72 h**, then "Verification expired" |

```python
# backend/src/domain/freshness.py
FRESH_MAX_HOURS = 6.0
AGING_MAX_HOURS = 24.0
STALE_MAX_HOURS = 48.0
VERIFICATION_VALIDITY_HOURS = 72.0
```

**Why not one quality score?** Because data can be recently updated and long
unverified, and collapsing them hides exactly the distinction that matters.

**And the permissions follow:** `inventory:write` and `inventory:verify` are
**separate permissions**. Blood bank *staff* can write; only the *admin* can
verify. Updating and attesting are different acts of trust.

### Two layers, and the rule between them

| Situation | Behaviour |
|---|---|
| `/find` listing | **both badges come from the facility rollup** |
| Filtered by group **and** component | batch data may override **freshness** |
| Any situation | **verification is NEVER overridden by batch data** |

**That last rule is deliberate.** Letting one freshly verified batch make a
whole facility look verified would be a false claim about every other batch.

---

## 5. The eight API endpoints

| Method | Path | Permission |
|---|---|---|
| GET | `/facilities/{id}/availability` | `inventory:read:public` *(anonymous OK)* |
| GET | `/facilities/{id}/batches` | `inventory:read:detailed` |
| POST | `/facilities/{id}/batches` | `inventory:write` |
| GET | `/facilities/{id}/batches/{bid}` | `inventory:read:detailed` |
| POST | `/facilities/{id}/batches/{bid}/adjust` | `inventory:write` |
| GET | `/facilities/{id}/batches/{bid}/audit` | `inventory:read:detailed` |
| POST | `/facilities/{id}/batches/{bid}/verify` | **`inventory:verify`** |
| POST | `/facilities/{id}/inventory/ingest` | `inventory:ingest:api` |

**Seven distinct inventory permissions exist:** `read:public`,
`read:detailed`, `write`, `correct`, `quarantine`, `verify`, `ingest:api`.

**The asymmetry worth pointing out:** staff hold `inventory:quarantine` but not
`inventory:verify`. Taking stock out of use is a **safety** action that should
never need a manager; declaring it verified is a **trust** action that should.

---

## 6. Concurrency

Batch rows carry `version`; updates are conditioned on it.

```
Staff A reads version 7, sees 12 units
Staff B reads version 7, sees 12 units
A writes: deduct 2, condition version = 7 -> SUCCEEDS, version 8
B writes: deduct 3, condition version = 7 -> FAILS
```

B receives **`409 CONCURRENT_MODIFICATION`**, which `isRetryable` marks as
retryable, so the UI offers a retry that **re-reads the current value**.

**The important detail:** the retry does not blindly re-apply. It shows the
operator the current truth and lets them decide again.

---

## 7. Code locations

| Concern | File |
|---|---|
| Availability states, batch arithmetic | `backend/src/domain/inventory.py` |
| Freshness and verification | `backend/src/domain/freshness.py` |
| DynamoDB access | `backend/src/repositories/inventory_repo.py` |
| Orchestration | `backend/src/services/inventory_service.py` |
| Handlers | `backend/src/handlers/api.py` |
| Facility-side UI | `frontend/src/features/dashboards/BloodBankDashboard.jsx` |
| Badges | `frontend/src/components/StatusBadges.jsx` |
| Public view | `frontend/src/features/discovery/FacilityDetailPage.jsx` |

**Indexes:** `GSI1-group-component` (`INCLUDE`, 7 attributes) and
`GSI2-expiry` (`KEYS_ONLY`) — the only two non-`ALL` projections in the
database, because this is the largest table.

---

## 8. Error cases

| Case | Code |
|---|---|
| Negative or absurd unit count | `VALIDATION_ERROR` |
| Deducting more than available | `VALIDATION_ERROR` |
| Expiry date in the past on create | `VALIDATION_ERROR` |
| Another facility's batch | `403` cross-organization |
| Staff attempting to verify | `403 FORBIDDEN` |
| Two concurrent edits | `409 CONCURRENT_MODIFICATION` |
| Batch not found | `404` |

---

## 9. Status

| Aspect | Status |
|---|---|
| Batch CRUD and adjustment | `DEPLOYED`, `TEST-VERIFIED` |
| Optimistic concurrency | `TEST-VERIFIED` |
| Availability states incl. `UNKNOWN` | **40 tests**, `TEST-VERIFIED` |
| Freshness and verification | `TEST-VERIFIED` |
| Public availability endpoint | **verified live** (200 anonymous) |
| Detailed read requires permission | **verified live** |
| **Browser workflow by a person** | **NOT VERIFIED** |
| External API ingestion | route exists; **no provider connected** |

**On ingestion, be precise:** the route and the permission exist, and the
Secrets Manager secret exists for provider credentials — but it has **never
been accessed**, because no external provider is integrated. The seam is built;
nothing is plugged into it.

---

## 10. Spoken answers

### 20–30 seconds
> "Blood banks record stock batch by batch, not as a single total, because blood
> expires and because an audit trail has to name which units moved. Each batch
> carries two timestamps — when it was last updated and when it was last
> independently verified — and those drive two separate badges with different
> thresholds. And a facility that has never reported shows as 'not reported'
> with no number, never as zero."

### 1–2 minutes
> "The hard part of this feature isn't counting units, it's representing
> uncertainty honestly.
>
> There are five availability states, and two of them are easy to conflate:
> unknown and unavailable. Unknown means the blood bank has never reported.
> Unavailable means they reported and have none. Those lead a doctor to
> opposite actions — one means phone them, the other means don't — so we never
> render unknown as zero. There are forty tests enforcing just that rule, which
> sounds excessive until you consider the consequence of getting it wrong.
>
> The second idea is that updated and verified are different. Someone typing a
> number is not the same as someone independently checking it, so we track them
> separately with separate thresholds — six, twenty-four and forty-eight hours
> for freshness, seventy-two for verification — and show two badges rather than
> one quality score. The permissions follow the same logic: writing stock and
> verifying stock are separate permissions, so blood bank staff can record
> figures and only the admin can attest to them.
>
> There's one asymmetry I like: staff *can* quarantine stock, taking it out of
> use, because that's a safety action and it shouldn't need a manager. They just
> can't declare it verified."

---

## 11. Follow-up questions

**"Why do you need the version attribute?"**
> To stop a lost update. Two staff could read the same batch showing twelve
> units and both deduct — without a version check, the second write silently
> overwrites the first and the stock figure is wrong. With it, the second write's
> condition fails, they get a 409, and the UI offers a retry that re-reads the
> current value so they can decide against the truth.

**"What happens when a batch expires?"**
> The `GSI2-expiry` index lets the maintenance sweep find batches past their
> expiry date, and they move to an expired status rather than being deleted —
> the record matters for the audit trail. The index is `KEYS_ONLY` on purpose,
> because the sweep only needs to know which batches to fetch.

**"How does a hospital know whether to trust a number?"**
> That's exactly what the two badges are for. Freshness tells them how long ago
> someone typed it; verification tells them whether anyone independently checked.
> A facility can be fresh and unverified, which is useful to know — and
> importantly, verification is never inferred from a single batch, because that
> would be a false claim about the others.

---

## 12. Cross-references

- [02_Find_Blood_And_Location.md](02_Find_Blood_And_Location.md)
- [05_Temporary_Reservations.md](05_Temporary_Reservations.md)
- [../05_DATABASE_AND_DATA/06_Concurrency_And_Data_Integrity.md](../05_DATABASE_AND_DATA/06_Concurrency_And_Data_Integrity.md)
- [../05_DATABASE_AND_DATA/01_DynamoDB_Data_Model.md](../05_DATABASE_AND_DATA/01_DynamoDB_Data_Model.md)
