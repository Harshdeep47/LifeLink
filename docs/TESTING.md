# LifeLink — Testing

## Actual results

Measured by running the suites on **2026-11-24**. Nothing here is estimated.

```
backend
  pytest tests                 610 passed, 0 failed, 0 skipped   (~20s)
  pytest tests/unit            536 passed
  pytest tests/integration      74 passed
  ruff check                   All checks passed

frontend
  vitest run                   294 passed  (12 files)
  npm run lint                 clean, exit 0  (0 errors, 15 warnings)
  npm run build                succeeded

infrastructure
  cfn-lint template.yaml       no findings
  sam validate --lint          valid SAM template  (SAM CLI 1.174.0)

security
  security_audit.py            gate passed; 8 development-only findings
  validate_facility_dataset.py exit 0
```

**Total: 904 automated tests, all passing.**

Plus **56 live checks** against the deployed API (19 authentication, 37
workflow), which are not part of the suite because they need AWS
credentials and a deployed stack.

> **These test the repository, not the deployed system.** Nothing in the suite
> makes a network call to AWS. The repository and the deployment are currently
> in sync — see [REPOSITORY_VS_DEPLOYED](REPOSITORY_VS_DEPLOYED.md) — but a
> passing suite is never by itself evidence that anything is deployed.

### What a passing suite does and does not prove

| Proven | Not proven |
|---|---|
| Domain rules, at boundaries and on failure paths | That any of it is deployed |
| Repository behaviour against a real DynamoDB API (moto) | Behaviour against the real service under load |
| That UI handlers call the right client methods with the right bodies | That anything renders correctly — jsdom is not a browser |
| That refusals refuse | Appearance, layout, fonts, CSS |

There is no visual or snapshot testing, and no browser automation. Items
needing a human are listed in
[REPOSITORY_VS_DEPLOYED](REPOSITORY_VS_DEPLOYED.md) §5.

## Suites

### Backend — unit, 536

| File | Tests | Covers |
|---|---|---|
| `test_camps_and_impact.py` | 50 | Camp lifecycle, registration rules, self-verification ban, ledger, reminders |
| `test_reservations.py` | 47 | Hold lifecycle, holding states, expiry, illegal transitions, unit caps |
| `test_environment_guard.py` | 45 | Local auth cannot run in AWS — three independent refusals |
| `test_unknown_is_not_zero.py` | 40 | `UNKNOWN` never becomes `0` on either code path |
| `test_geo_coverage.py` | 34 | Cell coverage as a property at ten radii; bounded fan-out; high latitude |
| `test_facility_dataset_validation.py` | 34 | Unsourced or implausible facility records are refused |
| `test_authorization.py` | 33 | RBAC matrix, suspension, cross-organization denial, IDOR |
| `test_freshness_and_eligibility.py` | 31 | Freshness bands at every boundary; update-versus-verification |
| `test_emergency.py` | 30 | Request lifecycle, priority mapping, P3 anti-starvation, response tally |
| `test_compatibility.py` | 27 | ABO/Rh tables, plasma inversion, whole-blood identity, fail-closed UNKNOWN |
| `test_geo_and_ranking.py` | 27 | Geohash encode/decode, Haversine, ranking weights and explanations |
| `test_public_emergency_access.py` | 27 | A member of the public may ask for help but never certify priority |
| `test_auth_degradation_and_provisioning.py` | 24 | A bad token does not break public routes; first-request provisioning |
| `test_cognito_token_verifier.py` | 23 | **The production verifier**: signature, pool, key, expiry, `token_use`, audience per token type |
| `test_profile_and_org_requests.py` | 23 | Self-service profile editing cannot become role escalation |
| `test_inventory_operations.py` | 22 | Stock operations, negative-stock prevention, stale updates |
| `test_stage_prefix.py` | 19 | Route resolution behind the API Gateway stage prefix |

### Backend — integration, 74

Against a real DynamoDB API via moto.

| File | Tests | Covers |
|---|---|---|
| `test_end_to_end_scenarios.py` | 21 | The ten scenarios the specification names |
| `test_reservation_integration.py` | 23 | Atomic pool counter; two callers racing for the last units; **the service's own release decision** (see [RESERVATION_COUNTER_DEFECT](RESERVATION_COUNTER_DEFECT.md)) |
| `test_inventory_integration.py` | 15 | Conditional writes, transactions, index queries |
| `test_camp_discovery_radius.py` | 9 | The 20 km cap, reported rather than hidden |
| `test_camp_reminders.py` | 6 | Reminder index population; regression for a real defect |

### Frontend — 294

| File | Tests | Covers |
|---|---|---|
| `passwordPolicy.test.js` | 49 | The sign-up rules match the deployed Cognito policy, read from the template |
| `redirect.test.js` | 44 | Open-redirect refusal on sign-in return |
| `reservationView.test.js` | 43 | Countdown never negative or fabricated; `CONFIRMED` never called clinical approval |
| `mapData.test.js` | 40 | Coordinate rejection, unknown-not-zero, registrations ≠ attendance, directions URL |
| `provenance.test.js` | 27 | Stock credibility **never inherits** from a real identity |
| `ReservationQueue.test.jsx` | 22 | Accept, decline and fulfil call the real client methods with the real bodies |
| `apiClient.test.js` | 18 | Error translation, headers, retryability, abort handling |
| `StatusBadges.test.jsx` | 18 | Presentation rules: UNKNOWN never zero, paired badges |
| `MyActivityPage.test.jsx` | 18 | Reaches `myReservations`; cancel sends sort-key fields; sections degrade independently |
| `routeIntegrity.test.js` | 8 | **No internal link points at a route that does not exist** |
| `maplibreExports.test.js` | 4 | MapLibre v6 exposes named exports only |
| `maplibreWorker.test.js` | 3 | The worker asset is emitted and its URL is set |

### Two tests worth singling out

**`routeIntegrity`** was proven non-vacuous: injecting a link to
`/definitely-not-a-route` made it fail and name the offending file. A test that
cannot fail is worse than no test, because it buys false confidence.

**The audience fix** was proven to fix something real: reverting it makes three
verifier tests fail, including `test_an_id_token_for_another_client_is_refused`.

## The two tiers, and why both exist

**Unit tests** exercise pure domain functions. No I/O, no AWS, no mocks, no
clock patching — time is injected, so tests pass a fixed instant and assert
exact boundaries. They run in under a second.

**Integration tests** run against a real DynamoDB API surface provided by moto
in-process. Condition expressions, transactions and GSI range queries genuinely
execute.

That distinction is not academic. Five real bugs were found by integration
tests that a fake repository would have passed:

| Bug | Why a fake would have missed it |
|---|---|
| Unused expression placeholder | A fake does not parse expression syntax |
| Version conflict reported as `DuplicateError` | A fake does not evaluate conditions |
| Three further unused placeholders | Same |
| `None` stripped from expression values | A fake serialises differently |
| Reminder index never populated | A fake returns what it was told to return |

The second is the instructive one. A mock-based test asserting "raises on
conflict" would have passed: the code did raise. It raised the wrong error, so
the service's retry path never engaged and the user would have been told a
record already existed.

## The ten end-to-end scenarios

Named for the flows the specification requires, in
`backend/tests/integration/test_end_to_end_scenarios.py`:

1. `TestScenario01_StaffAddInventoryPublicDiscovers`
2. `TestScenario02_StockBecomesStale`
3. `TestScenario03_AlertMatchTriggersNotification`
4. `TestScenario04_CampRegisterCheckInVerify`
5. `TestScenario05_ImpactCreditedExactlyOnce`
6. `TestScenario06_HospitalCertifiesPriority`
7. `TestScenario07_MatchingDiscoversFacilities`
8. `TestScenario08_ProviderResponsesDoNotDoubleCount`
9. `TestScenario09_UnauthorizedActionIsDenied`
10. `TestScenario10_MappingFailureDoesNotBreakDiscovery`

## Testing refusals

A substantial share of the suite asserts what the system declines to do: a
donor verifying their own donation, an organizer managing another
organization's camp, a suspended account acting, a provider responding twice,
a provider who was never notified responding at all, ranking surfacing expired
stock, unknown rendering as zero.

Where a rule could be circumvented by holding the right permission, the test
grants that permission deliberately. `test_being_staff_does_not_permit_self_verification`
gives the donor the camp-staff role specifically to prove the refusal still
holds.

## Determinism

No domain function reads the clock. `backend/tests/conftest.py` defines a fixed
instant and helpers, so time-dependent assertions are exact:

```python
NOW = datetime(2026, 11, 15, 12, 0, 0, tzinfo=UTC)
(6.0, FreshnessLabel.FRESH),   # inclusive upper bound
(6.1, FreshnessLabel.AGING),
```

Every freshness boundary is tested from both sides.

## Property testing

`test_geo_coverage.py` asserts a property rather than examples: walking the
search circle in five-degree steps at ten radii and confirming every bearing's
geohash cell is in the query set. It also bounds the fan-out, which is the test
that caught a 2,107-query search.

## Running the suites

```bash
# Backend, everything
cd backend && ../.venv/Scripts/python.exe -m pytest tests

# One tier
cd backend && ../.venv/Scripts/python.exe -m pytest tests/unit
cd backend && ../.venv/Scripts/python.exe -m pytest tests/integration

# With coverage
cd backend && ../.venv/Scripts/python.exe -m pytest tests --cov=src --cov-report=term-missing

# Frontend
cd frontend && npm test
cd frontend && npm run test:watch

# Lint
cd backend && ../.venv/Scripts/python.exe -m ruff check src tests
```

Note: do **not** add `-q`. In this pytest version quiet mode suppresses the
summary line, which is how the documentation build once recorded a test count
of zero.

## What is not tested

| Area | Reason |
|---|---|
| Load and throughput | At a concurrency ceiling of 10, a load test measures the ceiling |
| Backup restoration | Never rehearsed; PITR is enabled on 8 deployed tables |
| Cognito token issuance, in the automated suite | Local development uses a different issuer; covered instead by 19 live checks against the deployed pool |
| Accessibility with assistive technology | Structural work done; no audit run |
| Deployment rollback | Never exercised; no deployment has failed since the stack went live |
| File upload validation | No upload flow exists |
| Browser workflows | No browser automation available; 12 manual checks remain pending |

Each is listed in [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md).

## Quality gates before declaring work complete

| Gate | Command | Current |
|---|---|---|
| Backend tests | `pytest tests` | 610 passing |
| Frontend tests | `npm test` | 294 passing |
| Backend lint | `ruff check` | clean |
| Frontend lint | `npm run lint` | clean, 0 errors |
| Frontend build | `npm run build` | succeeds |
| OpenAPI current | `generate_openapi.py --check` | matches |
| Template lint | `cfn-lint template.yaml` | no findings |
| Template valid | `sam validate --lint` | valid |
| Demo data coverage | `seed_demo.py --validate` | 24/24 |
| Books build and validate | `build_books.py` | 3/3, 8 checks each |
| No secrets staged | `git diff --cached` | manual |
