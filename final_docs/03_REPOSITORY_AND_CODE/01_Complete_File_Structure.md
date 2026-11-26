# Complete File Structure

Every directory and every important file, with its purpose and category.
Verified against the repository at commit `668a771`.

---

## 1. Top level

```
LifeLink/
├── CLAUDE.md                    # AWS account conventions for this project
├── MASTER_BUILD_PROMPT.md       # the original specification
├── README.md                    # project README
├── requirements-docs.txt        # Python deps for documentation tooling
├── .env.example                 # environment variable template
├── backend/                     # Python application and tests
├── frontend/                    # React application and tests
├── infrastructure/              # the single SAM/CloudFormation template
├── scripts/                     # operational and build tooling
├── data/                        # curated reference datasets
├── docs/                        # original engineering documentation
└── final_docs/                  # this teaching library
```

| Category | Directories |
|---|---|
| **Backend application** | `backend/src/` |
| **Backend tests** | `backend/tests/` |
| **Frontend application** | `frontend/src/` (excluding `test/`) |
| **Frontend tests** | `frontend/src/test/` |
| **Infrastructure** | `infrastructure/` |
| **Deployment / tooling** | `scripts/` |
| **Documentation** | `docs/`, `final_docs/` |
| **Data** | `data/` |

---

## 2. `infrastructure/` — all the AWS resources

| File | Lines | Purpose |
|---|---|---|
| `template.yaml` | 1490 | **Every** AWS resource: 12 tables, 6 functions, the HTTP API, Cognito, CloudFront, S3, SQS, SNS, schedules, alarms, IAM roles |

**This is the most important file in the project for an AWS evaluation.** It is
a SAM template, which is CloudFormation plus a transform that expands
`AWS::Serverless::Function` into a function, a role and permissions. Everything
in AWS exists because this file says so — nothing was clicked together by hand.

---

## 3. `backend/src/` — the application, in four layers

The layering is ADR-0010: **handlers -> services -> repositories -> adapters**,
with a `domain` layer that depends on nothing.

### `handlers/` — the entry points

| File | Lines | Purpose |
|---|---|---|
| `api.py` | 1123 | All 58 route handler functions, plus `build_router()` and `lambda_handler` |
| `router.py` | 255 | The `Route` dataclass, `Router` (add/match/dispatch), `strip_stage_prefix` |
| `workers.py` | 378 | The five worker entry points |

Worker handlers in `workers.py`:

| Function | Invoked by |
|---|---|
| `dispatcher_handler` | EventBridge Scheduler, every minute |
| `maintenance_handler` | EventBridge Scheduler, every ten minutes |
| `outbox_handler` | DynamoDB Stream on the `outbox` table |
| `work_handler` | SQS `lifelink-dev-work` |
| `notification_handler` | SQS `lifelink-dev-notifications` |

### `appcore/` — cross-cutting platform concerns

| File | Purpose |
|---|---|
| `auth.py` | `CognitoTokenVerifier`, `build_context`, and the `@requires()` decorator with its five ordered checks |
| `rbac.py` | `Permission` enum (39 values), `ROLE_PERMISSIONS` (10 roles), `GLOBAL_PERMISSIONS`, `is_organization_scoped` |
| `context.py` | `Principal`, `RequestContext`, `ANONYMOUS`, `new_correlation_id` |
| `responses.py` | The `{data, correlationId}` / `{error, correlationId}` envelope |
| `cors.py` | Preflight detection and response |
| `logging.py` | Structured logging configuration |
| `environment.py` | Environment detection and the guard that refuses unsafe configurations |

### `domain/` — pure business rules, **no AWS imports**

| File | What it decides |
|---|---|
| `freshness.py` | `FRESH`/`AGING`/`STALE`/`OUTDATED` thresholds (6/24/48 h) and `VERIFICATION_VALIDITY_HOURS = 72.0` |
| `geo.py` | Geohash encode/decode, `choose_precision`, `search_cells`, `haversine_km`, `EARTH_RADIUS_KM = 6371.0088`, `MAX_SEARCH_RADIUS_KM = 100.0` |
| `inventory.py` | Availability states and batch arithmetic |
| `reservations.py` | Reservation lifecycle rules |
| `emergency.py` | Emergency request lifecycle |
| `ranking.py` | Provider dispatch ordering |
| `compatibility.py` | ABO/Rh compatibility, driven by versioned reference data |
| `eligibility.py` | Donor eligibility rules |
| `camps.py` | Camp lifecycle and capacity |
| `impact.py` | Donor impact scoring and milestones |
| `blood.py` | Blood groups and components |
| `clock.py` | Time injection, so tests control "now" |
| `errors.py` | `LifeLinkError` and its subclasses, each carrying a stable error code |

**Why this layer has no AWS imports:** rules are what you most want to test,
and tests that touch no AWS run in milliseconds. That is why **566 of the 657
backend tests are unit tests.** It is also the cleanest thing to show a teacher
who asks about testing.

### `repositories/` — DynamoDB access

| File | Tables |
|---|---|
| `schema.py` | Table and GSI definitions (193 lines), `create_table_kwargs` |
| `dynamo.py` | Shared client, serialization, retry behaviour |
| `facility_repo.py` | `facilities` (including the three geohash GSIs) |
| `inventory_repo.py` | `inventory` |
| `reservation_repo.py` | `reservations` (the `TransactWriteItems` writes) |
| `emergency_repo.py` | `emergency` (including append-only `append_event`) |
| `camp_repo.py` | `camps`, `donations` |
| `alert_repo.py` | `alerts` |
| `identity_repo.py` | `organizations` (users and orgs) |
| `platform_repo.py` | `audit`, `outbox`, `idempotency`, `notifications` |

### `services/` — orchestration

| File | Use cases |
|---|---|
| `discovery_service.py` | Facility search, ranking, availability rollups |
| `inventory_service.py` | Batch create/adjust/verify/quarantine |
| `reservation_service.py` | Request, decide, cancel, fulfil, expire |
| `emergency_service.py` | Create, dispatch, respond, certify, confirm, cancel |
| `camp_service.py` | Camps, registrations, check-in, donations |
| `alert_service.py` | Availability alerts and matching |
| `notification_service.py` | Notification composition and delivery records |
| `container.py` | Dependency wiring — builds services with their repositories |

### `reference/`

| File | Purpose |
|---|---|
| `compatibility/abo_rh_v1.json` | ABO/Rh compatibility matrix as **versioned data** (ADR-0008) |

**Why data and not code?** Because a clinical rule that changes should be a
reviewable data change with a version number, not an edit buried in a function.

---

## 4. `backend/tests/` — 657 tests

### `tests/unit/` — 566 tests

| File | Covers |
|---|---|
| `test_authorization.py` | The RBAC matrix and the route-table completeness check |
| `test_cognito_token_verifier.py` | 23 tests — signature, issuer, expiry, `token_use`, audience per token type |
| `test_reservations.py` | Reservation lifecycle, including the counter regression tests |
| `test_inventory_operations.py` | Batch arithmetic and optimistic concurrency |
| `test_unknown_is_not_zero.py` | 40 tests enforcing the honesty rule |
| `test_freshness_and_eligibility.py` | Threshold boundaries |
| `test_geo_and_ranking.py`, `test_geo_coverage.py` | Geohash cells, haversine, ranking |
| `test_compatibility.py` | ABO/Rh matrix |
| `test_emergency.py` | Emergency lifecycle and dispatch |
| `test_camps_and_impact.py` | Camps, donations, impact scoring |
| `test_public_emergency_access.py` | What anonymous callers may and may not see |
| `test_profile_and_org_requests.py` | Self-service limits — a user cannot elevate their own role |
| `test_auth_degradation_and_provisioning.py` | Behaviour when identity data is missing |
| `test_environment_guard.py` | Refusal to run with an unsafe configuration |
| `test_stage_prefix.py` | `strip_stage_prefix` edge cases |
| `test_facility_dataset_validation.py` | 34 tests on the curated dataset |
| `test_dedupe_request_events.py` | 30 tests on the cleanup script's delete predicate |

### `tests/integration/` — 91 tests

Run against **moto**, a local AWS mock — **not** against real AWS.

| File | Covers |
|---|---|
| `test_end_to_end_scenarios.py` | Multi-step user journeys |
| `test_reservation_integration.py` | Reservations against a real table shape |
| `test_inventory_integration.py` | Inventory with indexes |
| `test_camp_discovery_radius.py` | Radius search with real geohash queries |
| `test_camp_reminders.py` | Scheduled reminder logic |
| `test_seed_idempotency.py` | 17 tests proving a second seed run does not duplicate |

---

## 5. `frontend/src/` — the React application

### Entry points and routing

| File | Purpose |
|---|---|
| `main.jsx` | React root, mounts `App` |
| `App.jsx` | 23 routes, lazy-loaded dashboards, `RequireAuth`, per-route `Suspense` and `ErrorBoundary` |
| `index.html` | The HTML shell (in `frontend/`, not `src/`) |

### `api/`

| File | Purpose |
|---|---|
| `client.js` | 231 lines — `ApiError`, `setTokenProvider`, `request()`, and the `api` object with every endpoint |
| `referenceFallback.js` | Local defaults if `/reference` is unreachable |

### `auth/`

| File | Key exports |
|---|---|
| `AuthContext.jsx` | `AuthProvider`, `useAuth` |
| `cognito.js` | `isCognitoConfigured`, `beginSignIn`, `completeSignIn`, `refreshSession`, `loadSession`, `saveSession`, `clearSession`, `isExpired`, `signOutRedirect`, `TOKEN_KEY` |
| `cognitoSignUp.js` | Self-service registration |
| `passwordPolicy.js` | `MIN_LENGTH = 12`, `SYMBOLS`, `PASSWORD_REQUIREMENTS` — **one shared source** so the UI cannot disagree with the pool |
| `redirect.js` | Safe post-login redirect handling |

### `components/` — shared UI

| File | Key exports |
|---|---|
| `ui.jsx` | `Spinner`, `LoadingPanel`, `EmptyPanel`, `ErrorPanel`, `AsyncState`, `Card`, `Button`, `Field`, `Notice`, `NotAReservationNotice`, `DefinitionList`, `ErrorBoundary` |
| `StatusBadges.jsx` | `AvailabilityBadge`, `FreshnessBadge`, `VerificationBadge`, `DataQuality`, `PriorityBadge`, `StatusPill`, `CampStatusPill`, `RequestStatusPill` |
| `FacilityMap.jsx` | The MapLibre map, clustering, popups, the OSM basemap style |
| `mapData.js` | `toCoordinate`, `shortLabel`, `facilitySummary`, `campSummary` — pure, so they are testable without WebGL |
| `provenance.js` | `identitySource`, `inventorySource`, `coordinateSource`, `describeProvenance`, `citation` |
| `DataProvenance.jsx` | Renders provenance |
| `OriginIndicator.jsx` | Shows where the user's location came from |
| `PlaceSearch.jsx` | Place search box, calls `/geocode` |

`NotAReservationNotice` is worth noticing: a component whose only job is to
state that an alert is **not** a reservation. The honesty rules are enforced in
the UI, not just the docs.

### `features/` — one folder per area

| Folder | Pages |
|---|---|
| `home/` | `HomePage`, `InfoPages` (help, privacy, terms), `NotFoundPage` |
| `discovery/` | `FindBloodPage`, `FacilityDetailPage`, `ReservationPanel` |
| `camps/` | `CampsPage`, `CampDetailPage` |
| `emergency/` | `EmergencyRequestPage`, `RequestTrackingPage` |
| `alerts/` | `AlertsPage` |
| `reservations/` | `ReservationQueue.jsx`, `reservationView.js`, `reservationStatus.js` |
| `account/` | `SignInPage`, `SignUpPage`, `AuthCallbackPage`, `ProfilePage`, `MyActivityPage` |
| `dashboards/` | `DonorDashboard`, `BloodBankDashboard`, `HospitalDashboard`, `CampOrganizerDashboard`, `AdminDashboard`, `ExploreDashboard`, plus `BloodBankDashboardTab`, `CampDashboardTab` |

### `hooks/`

| Export | Purpose |
|---|---|
| `useApiData` | Fetch with loading/error/abort handling |
| `useMutation` | Write with pending/error state |
| `useDebounced` | Debounce user input (default 350 ms) |
| `useGeolocation` | Wraps the browser Geolocation API |

### `frontend/src/test/` — 294 tests in 12 files

| File | Tests |
|---|---|
| `reservationView.test.js` | 43 |
| `passwordPolicy.test.js` | 49 |
| `provenance.test.js` | 27 |
| `ReservationQueue.test.jsx` | 22 |
| `MyActivityPage.test.jsx` | 18 |
| `routeIntegrity.test.js` | 8 — fails the build on a dead internal link |
| `StatusBadges.test.jsx`, `apiClient.test.js`, `mapData.test.js`, `maplibreExports.test.js`, `maplibreWorker.test.js`, `redirect.test.js` | the remainder |

`maplibreExports.test.js` exists because MapLibre v6 removed default exports; a
test pins the named-export contract so an upgrade cannot silently break the map.

### Configuration

| File | Purpose |
|---|---|
| `package.json` | Scripts: `dev`, `build`, `test`, `lint` |
| `vite.config.js` | Build and dev-server proxy |
| `eslint.config.js` | ESLint 9 flat config |
| `.env.production.example` | Documents the eight build-time variables |
| `src/styles/tokens.css` | Design tokens |

> **A note on `eslint.config.js`.** A legacy `.eslintrc.json` used to sit beside
> it and was **silently ignored** by ESLint 9, which uses flat config. It was
> deleted: a config file that looks authoritative and changes nothing is worse
> than no config file. Enabling the linter properly found a genuine bug — an
> undefined variable inside an empty `catch` that stopped expired sessions
> from ever being cleared.

---

## 6. `scripts/` — tooling

| Script | Purpose |
|---|---|
| `seed_demo.py` | **Generates** the synthetic dataset deterministically |
| `seed_cloud.py` | **Uploads** it to AWS. Preview by default, `--apply` to write. No delete path |
| `dedupe_request_events.py` | Removes duplicate seeded events. Narrow predicate, dry-run default |
| `deploy_frontend.py` | Builds, syncs to S3, creates a CloudFront invalidation |
| `build_lambda_package.py` | Builds the Lambda zip with `manylinux2014_aarch64` wheels. **Use this, not `sam build`** |
| `local_server.py` | Runs the same router over HTTP for local development |
| `dev.py` | Developer convenience entry point |
| `generate_openapi.py` | Generates `docs/openapi.{json,yaml}`; `--check` fails on drift |
| `security_audit.py` | The secret-scanning and security gate |
| `validate_facility_dataset.py` | Validates `data/real_facilities.json` |
| `provision_demo_logins.py` | Creates the demo Cognito users |
| `reconcile_showcase_batches.py` | Repairs demo inventory batches |
| `build_books.py` + `bookgen/` | Builds the three long-form technical books in `docs/books/` |

---

## 7. `data/` and `docs/`

| Path | Purpose |
|---|---|
| `data/real_facilities.json` | Curated facility dataset, structurally validated by 34 tests |
| `docs/` | 37 engineering documents — see the table at the end of [../README.md](../README.md) |
| `docs/openapi.{json,yaml}` | Generated API specification |
| `docs/books/` | Three long-form technical books |

---

## 8. Spoken answer

### 20–30 seconds

> "The repository has five parts. `infrastructure/template.yaml` defines every
> AWS resource in one file. `backend/src` is the Python application in four
> layers — handlers, services, repositories, and a pure domain layer with no
> AWS imports at all, which is why most of our 657 backend tests run in
> milliseconds. `frontend/src` is the React app, organised one folder per
> feature. `scripts/` holds the seeding and deployment tooling. And `docs/` plus
> `final_docs/` is the documentation."

### Follow-up: "Why is the domain layer separate?"

> Because the rules are the part worth testing hardest, and a rule that imports
> boto3 can only be tested with a mock. Keeping `domain/` free of AWS means 566
> of our tests are plain unit tests with no setup. It also means I can show a
> teacher the freshness thresholds or the haversine formula as ten readable
> lines, rather than buried inside a database call.

---

## 9. Cross-references

- [02_Frontend_Code_Walkthrough.md](02_Frontend_Code_Walkthrough.md)
- [03_Backend_Code_Walkthrough.md](03_Backend_Code_Walkthrough.md)
- [05_Database_Code_Locations.md](05_Database_Code_Locations.md)
- [../13_REFERENCE_AND_REVISION/05_Known_Limitations_And_Actual_Status.md](../13_REFERENCE_AND_REVISION/05_Known_Limitations_And_Actual_Status.md)
