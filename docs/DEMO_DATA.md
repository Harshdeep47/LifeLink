# LifeLink — Demo Data

> Every record described here is **invented**. The coordinates are plausible
> locations in Punjab and Chandigarh; the institutions at them do not exist
> and none is a partner. No verified institutional dataset was supplied for
> this project.

## What is seeded

Figures reported by `python scripts/seed_demo.py` on 2026-11-15.

| Entity | Count | Coverage |
|---|---|---|
| Organizations | 12 | Verified, pending verification and suspended |
| Users | 18 | Nine distinct roles, one suspended account |
| Facilities | 8 | Including one that has never reported inventory |
| Inventory batches | 200 | All 8 groups, all 4 components |
| Camps | 8 | All six lifecycle states |
| Registrations | 12 | Registered, checked in, and a no-show |
| Donations | 8 | Recorded and verified |
| Emergency requests | 10 | P1, P2, P3 and one uncertified |
| Provider responses | 9 | Accepted, rejected and partial |
| Availability alerts | 5 | Active, cancelled and expired |

### Inventory composition

| Dimension | Spread |
|---|---|
| Freshness | 50 fresh, 50 aging, 50 stale, 50 outdated |
| Verification | 66 verified, 134 unverified |
| Status | 161 available, 17 expired, 17 quarantined |
| Expiry | 16 near-expiry (within 48 hours) |

The freshness split is deliberate and even, so all four labels are visible on
screen rather than theoretically reachable. The verification split is
deliberately uneven, because most real stock would not be independently
verified.

## Geography

| City | Facilities | Camps |
|---|---|---|
| Patiala | 2 | 2 |
| Rajpura | 1 | 1 |
| Chandigarh | 2 | 2 |
| Mohali | 1 | 1 |
| Jalandhar | 1 | 1 |
| Ludhiana | 1 | 1 |

Real inter-city distances, which is what makes the radius behaviour
demonstrable — and what caught the geohash coverage bug.

## Deliberately placed cases

| Case | Where | Demonstrates |
|---|---|---|
| Facility with no inventory | `fac-chd-2` Tricity Voluntary | `UNKNOWN` versus zero |
| Unverified facility | `fac-patiala-2`, `fac-chd-2` | Verification filtering |
| Suspended organization | `org-bb-ludh-1`, `org-hosp-susp-1` | Suspension effects |
| Pending organization | `org-bb-chd-2`, `org-hosp-jal-1` | The admin verification queue |
| Suspended user | `user-suspended-1` | Valid token, every action refused |
| Hospital staff without certify | `user-hosp-staff-1` | Role separation |
| Zero-unit batches | AB− and B− | "None in stock" distinct from unknown |
| Expired batches | 17 | Exclusion from availability |
| Quarantined batches | 17 | Exclusion with a reason |
| Near-expiry batches | 16 | Flagged but still eligible |
| Opted-out donor | `user-donor-5` | Notification suppression |
| Uncertified emergency request | `demo-req-uncert-1` | No priority until certified |
| Partial provider response | 2 requests | `INSUFFICIENT_STOCK` handling |

## Marking

Every seeded item carries:

```json
{ "demoData": true, "dataSource": "SYNTHETIC", "environment": "DEVELOPMENT" }
```

The interface shows a non-dismissible banner, and individual records display a
"Synthetic record" pill.

## Guarantees

**Deterministic.** A fixed seed (`20261115`) and a dedicated `Random`
instance, with fixed identifiers like `demo-batch-0001`. A rebuild produces
the same dataset, so screenshots and documentation stay accurate.

**Idempotent.** Re-running produces the same state, not duplicates.

**Validated.** `--validate` runs 24 coverage checks and reports each.

**Resettable.** `--reset` removes every `demoData` item first.

**Guarded.** Three independent refusals prevent seeding anything that might be
production.

## Commands

```bash
python scripts/seed_demo.py             # seed
python scripts/seed_demo.py --reset     # wipe demo data, then seed
python scripts/seed_demo.py --validate  # check coverage only
```

## Validation output

```
[PASS] all 8 blood groups present  (8/8)
[PASS] all 4 components present  (4/4)
[PASS] quarantined stock present
[PASS] consumed/zero stock present
[PASS] expired batches present  (17)
[PASS] near-expiry batches present  (16)
[PASS] verified batches present  (66)
[PASS] unverified batches present  (134)
[PASS] fresh inventory present  (50)
[PASS] aging inventory present  (50)
[PASS] stale inventory present  (50)
[PASS] outdated inventory present  (50)
[PASS] facility with UNKNOWN inventory present  (1)
[PASS] verified and unverified facilities present
[PASS] all 6 camp lifecycle states present  (6/6)
[PASS] verified donations present
[PASS] unverified donations present
[PASS] P1, P2 and P3 requests present  (['P1', 'P2', 'P3'])
[PASS] uncertified request present
[PASS] partial stock response present
[PASS] accepted and rejected responses present
[PASS] suspended user present
[PASS] multiple distinct roles present  (9 roles)
[PASS] every record marked demoData
24/24 checks passed
```

## Production safety

```python
# scripts/seed_demo.py
env must be local, dev, development or test
DYNAMODB_ENDPOINT must be set in local mode
DYNAMODB_ENDPOINT must not contain amazonaws.com
```

Three independent conditions, because one check is a typo away from being
bypassed. Any failure exits non-zero before writing anything.

## Real data

Real institutional data may enter only through verified onboarding, authorized
staff updates, or an approved institutional integration. A map result, a
geocoded address or a business listing is **not** proof of institutional
verification, and the facility directory carries its own verification state
set only by an administrator.
