# LifeLink — Final Handover Report

**Date:** 15 November 2026
**Version:** v0.1.0
**Deployment status:** **DEPLOYED AND LIVE** — https://d324z37do52g8f.cloudfront.net
**GitHub:** not published; nothing pushed

> **This is a dated report, not a current status page.** It records the state
> on 15 November 2026 and is deliberately not rewritten — see
> [REPOSITORY_VS_DEPLOYED](REPOSITORY_VS_DEPLOYED.md) §7 for the convention.
> Several things have changed since: temporary reservations gained both their
> screens, the map gained clustering, a token-audience weakness was fixed, and
> the test suite went from 332 to 849. For current status start at
> [REPOSITORY_VS_DEPLOYED](REPOSITORY_VS_DEPLOYED.md); for what changed last,
> [FINAL_POLISH_REPORT](FINAL_POLISH_REPORT.md).

Statuses: **COMPLETE** (implemented and verified) · **PARTIAL** (implemented,
not fully verified) · **BLOCKED** (needs a dependency or your approval) ·
**NOT IMPLEMENTED**.

Every number in this report names the command that produced it. Nothing is
estimated.

---

## 1. Project overview — COMPLETE

LifeLink is a blood availability and donation coordination platform: it shows
where blood is, how trustworthy that figure is, lets hospitals raise
certified-priority requests, and lets blood banks respond — without ever
pretending to know more than it does.

The engineering substance is five rules the code enforces and the tests
assert:

1. **Unknown is not zero.** A facility that has never reported returns
   `UNKNOWN` with `eligibleUnits: null`. Zero means "we have none"; unknown
   means "call them".
2. **Updated is not verified.** Freshness and human verification are separate
   signals on every figure.
3. **An offer is not a reservation.** A provider response holds no stock.
4. **Dispatch order is not clinical priority.** The dispatcher computes an
   ordering; it never writes the certified clinical priority.
5. **Fail closed.** Missing or invalid data produces a refusal with a reason
   code, never an optimistic default.

Full narrative: [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md). Requirements as
FR-1..FR-41 and NFR-1..NFR-15: [REQUIREMENTS.md](REQUIREMENTS.md).

## 2. Seven-feature implementation status

| # | Feature | Status | Evidence |
|---|---|---|---|
| 1 | Inventory and availability | **COMPLETE** | 22 inventory unit tests + 15 integration tests; live API verified |
| 2 | Location-based discovery | **COMPLETE** | 27 geo/ranking + 34 coverage tests; radius behaviour verified live (10 km→2, 30 km→3, 60 km→6) |
| 3 | Donation camps and donors | **COMPLETE** | 50 camp/impact unit tests + 6 reminder integration tests |
| 4 | Emergency coordination | **COMPLETE** | 30 emergency + 27 compatibility unit tests |
| 5 | Web interface | **COMPLETE** | 28 modules, 36 frontend tests, builds and serves |
| 6 | Security, identity, observability | **COMPLETE** | 33 authorization tests; all 50 routes declare a permission |
| 7 | Infrastructure | **PARTIAL** | Template passes `cfn-lint` and `sam validate --lint`; **never deployed** |

Feature 7 is PARTIAL and stays PARTIAL until something is deployed. A template
that lints is not a template that deploys.

## 3. Architecture summary — COMPLETE

One Lambda serving all 50 routes behind an HTTP API; 11 DynamoDB tables with
23 GSIs; two SQS queues with two dead-letter queues; a transactional outbox on
a DynamoDB stream; four background Lambdas (outbox publisher, work worker,
notification worker, priority dispatcher) plus a maintenance function;
CloudFront over a private S3 bucket; Cognito for sign-in and a separate
identity pool scoped to map tiles only.

Layering is strict and one-directional: handlers parse and delegate, services
orchestrate, domain is pure functions with no I/O and no clock reads,
repositories are the only place DynamoDB types appear. That is why 254 domain
tests run in under a second with no mocks.

**The dominant constraint was a Lambda concurrent-execution ceiling of 10**
(confirmed by `aws lambda get-account-settings`, against a default of 1000).
Consequences: no reserved concurrency anywhere, queue consumers capped at
`MaximumConcurrency: 2`, a scheduled priority dispatcher instead of
per-priority queue consumers, and the API throttled at 10 rps. The structure
needs no change to use a higher limit.

Details: [ARCHITECTURE.md](ARCHITECTURE.md) · 17 decision records with the
rejected alternative in each: [ARCHITECTURE_DECISIONS.md](ARCHITECTURE_DECISIONS.md)
· Book 1 covers it with diagrams.

## 4. Folder structure — COMPLETE

```
LifeLink/
├── backend/
│   ├── src/
│   │   ├── domain/        12 pure modules: blood, camps, clock, compatibility,
│   │   │                  eligibility, emergency, errors, freshness, geo,
│   │   │                  impact, inventory, ranking
│   │   ├── services/      7 orchestration modules + container
│   │   ├── repositories/  9 data modules + schema
│   │   ├── handlers/      api, router, workers
│   │   ├── appcore/       auth, context, logging, rbac, responses
│   │   └── adapters/      location, notifications
│   └── tests/
│       ├── unit/          8 modules, 254 tests
│       └── integration/   3 modules, 42 tests
├── frontend/src/          28 modules
│   ├── api/               client.js — the single fetch point
│   ├── auth/              AuthContext.jsx
│   ├── components/        Layout, StatusBadges, FacilityMap, ui
│   ├── features/          account, alerts, camps, dashboards, discovery,
│   │                      emergency, home — 7 feature folders
│   ├── hooks/             useApi.js
│   ├── styles/            design tokens
│   └── test/              2 suites, 36 tests
├── infrastructure/        template.yaml (59 resources), samconfig.toml
├── scripts/               dev.py, seed_demo.py, local_server.py,
│                          generate_openapi.py, build_books.py, bookgen/
└── docs/                  24 documents, openapi.json/yaml,
                           books/ (3 PDFs + 34 Markdown sources)
```

Measured: 46 backend Python modules, 28 frontend modules, 11 test modules.

## 5. Important backend modules — COMPLETE

| Module | Why it matters |
|---|---|
| [domain/geo.py](../backend/src/domain/geo.py) | `choose_precision()`, `search_cells()`. Bounding-box cell coverage — the neighbour-only version silently lost facilities |
| [domain/freshness.py](../backend/src/domain/freshness.py) | Freshness bands, and `verification_status()` kept deliberately separate |
| [domain/eligibility.py](../backend/src/domain/eligibility.py) | Returns reasons, not booleans; fails closed on an unparseable expiry |
| [domain/inventory.py](../backend/src/domain/inventory.py) | `apply_stock_operation()` pure; `summarise_availability(..., inventory_known)` returns UNKNOWN when false |
| [domain/emergency.py](../backend/src/domain/emergency.py) | Transition table; `compute_effective_priority()` returns a value and never mutates clinical priority |
| [domain/compatibility.py](../backend/src/domain/compatibility.py) | Refuses to load without a review-status field; returns `()` for an unknown group |
| [domain/clock.py](../backend/src/domain/clock.py) | Rejects naive datetimes; every domain function takes `now` as a parameter |
| [appcore/auth.py](../backend/src/appcore/auth.py) | The `@requires` decorator: five ordered checks, and route-audit metadata |
| [appcore/rbac.py](../backend/src/appcore/rbac.py) | 35 permissions over 10 roles |
| [appcore/logging.py](../backend/src/appcore/logging.py) | Recursive redaction over a sensitive-key set |
| [repositories/dynamo.py](../backend/src/repositories/dynamo.py) | Conditional writes; `on_conflict` distinguishes duplicate from version conflict; `to_expression_values()` preserves nulls |
| [repositories/inventory_repo.py](../backend/src/repositories/inventory_repo.py) | Status+expiry range queries; sharded expiry index; the **sole** writer of `lastVerifiedAt` |
| [repositories/camp_repo.py](../backend/src/repositories/camp_repo.py) | Registration + capacity in one transaction; ledger row keyed on donation id |
| [handlers/api.py](../backend/src/handlers/api.py) | 50 routes, every one declaring a permission |
| [handlers/workers.py](../backend/src/handlers/workers.py) | Five background entry points; the dispatcher re-raises so the alarm fires |

## 6. Important frontend modules — COMPLETE

| Module | Why it matters |
|---|---|
| [api/client.js](../frontend/src/api/client.js) | The single fetch point. Attaches correlation id, bearer token, idempotency key; `ApiError` exposes `isRetryable` and `isAuthError` |
| [components/StatusBadges.jsx](../frontend/src/components/StatusBadges.jsx) | `AvailabilityBadge` renders "Not reported" with **no count** for UNKNOWN. This is rule 1 made visible |
| [hooks/useApi.js](../frontend/src/hooks/useApi.js) | `useApiData` with AbortController; `useGeolocation` handles all four failure modes |
| [features/discovery/FindBloodPage.jsx](../frontend/src/features/discovery/FindBloodPage.jsx) | Search, radius control, results carrying both data-quality signals |
| [auth/AuthContext.jsx](../frontend/src/auth/AuthContext.jsx) | Token holding and the role-aware navigation that hides what a role cannot do |
| [features/dashboards/](../frontend/src/features/dashboards/) | Five dashboards — donor, blood bank, hospital, camp organizer, administrator — each showing only what that role may do |

## 7. Database tables and access patterns — COMPLETE

11 tables, one per bounded context; 23 GSIs; **39 enumerated access patterns,
none resolving to a scan on a user-facing path.**

Techniques that carry the design:

- **Composite sort keys** — `STATUS#<status>#<expiresAt>` turns a filter into a
  range condition, so expired and quarantined stock is never read.
- **Three geohash precisions**, selected by radius, each with its own index.
- **Sharded expiry index** (10 shards) so the sweep cannot create a hot
  partition.
- **Deliberate projections** — `INCLUDE` with exactly the attributes
  aggregation needs; `KEYS_ONLY` where only keys are used.

Eight concurrency invariants, each enforced by the datastore rather than by
convention: non-negative stock, no lost update, no duplicate registration, no
oversubscribed camp, impact credited once, no duplicate event processing, no
event lost on crash, no stale update overwriting fresh data.

Full detail: [DATABASE_DESIGN.md](DATABASE_DESIGN.md).

## 8. AWS services and infrastructure templates — PARTIAL

One SAM template, [infrastructure/template.yaml](../infrastructure/template.yaml),
59 resources. Services: Lambda, API Gateway HTTP API, DynamoDB, SQS,
EventBridge, S3, CloudFront, Cognito (user pool + identity pool), Amazon
Location, SES, Secrets Manager, CloudWatch (logs, 8 alarms, a 5-widget
dashboard), IAM.

Validated:

```
cfn-lint infrastructure/template.yaml   → exit 0, no findings
sam validate --lint                     → valid SAM template
```

**PARTIAL because it has never been applied.** Every operational claim about
AWS behaviour in this project is a design expectation supported by two
linters, not an observation.

All regional resources target `ap-southeast-2`. CloudFront is global and
administered through `us-east-1`, which this account's rules permit.

## 9. Authentication and authorization model — COMPLETE

Cognito user pool with OIDC, RS256, authorization-code flow with PKCE. A
separate identity pool issues credentials scoped to map tiles only.

One decorator, `@requires(permission, resource_owner=..., allow_anonymous=...)`,
applying five checks in order:

1. Anonymous allowed?
2. Token valid?
3. **Account status read from the database** — not from the token.
4. Does the principal hold the permission?
5. Does the resource belong to the caller's organization?

**Check 3 is the design decision worth defending.** Reading status from stored
state on every request costs one extra read and makes suspension and
revocation immediate, with no token-revocation machinery and no waiting for
expiry. The demo account `user-suspended-1` exists to demonstrate it: a valid,
unexpired, correctly-signed token, and every action refused.

35 permissions over 10 roles. Check 5 is the IDOR defence, applied centrally
rather than per-handler.

Audit: append-only, with the Lambda role granted `PutItem` and `Query` only —
no `UpdateItem`, no `DeleteItem` — so the application physically cannot
rewrite history. That is tamper resistance within the platform's means, not
cryptographic immutability, and [SECURITY.md](SECURITY.md) says so.

## 10. External integrations and actual status

| Integration | Status | Detail |
|---|---|---|
| Amazon Cognito | **PARTIAL** | Template defined and validated; **never exercised against real Cognito**. Locally the stack mints its own tokens — the *issuer* differs, the *verifier* is the same code path |
| Amazon Location — places | **PARTIAL** | Adapter implemented, server-side only; not exercised against the live service |
| Amazon Location — routes | **PARTIAL** | Implemented; when routing fails the system reports road distance as **unavailable** rather than substituting the straight line |
| Map tiles | **PARTIAL** | Needs identity-pool credentials; locally the map panel shows its unavailable state by design |
| Amazon SES | **PARTIAL** | Adapter implemented; **sandbox** — verified recipients only |
| SMS | **NOT IMPLEMENTED** | **BLOCKED** by the account's service control policy. Requests return `503 CHANNEL_UNAVAILABLE` rather than appearing to send |
| Push notifications | **NOT IMPLEMENTED** | Out of scope for this build |

No analytics provider, no advertising pixel, no error-reporting SaaS, no
runtime CDN for fonts or scripts. The browser talks only to the API,
CloudFront and the tile endpoint.

## 11. Demo environment instructions — COMPLETE

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r backend/requirements-dev.txt
.venv/Scripts/python.exe -m pip install -r requirements-docs.txt

python scripts/dev.py keys           # local signing keypair (gitignored)
python scripts/dev.py db-start       # moto, DynamoDB-compatible, port 8000
python scripts/dev.py create-tables  # 11 tables
python scripts/seed_demo.py          # synthetic data
python scripts/seed_demo.py --validate   # expect 24/24

python scripts/local_server.py --port 8080    # API
cd frontend && npm install && npm run dev     # port 5173
```

`python scripts/dev.py status` reports what is and is not running. No Docker
required. Full guide: [LOCAL_DEVELOPMENT.md](LOCAL_DEVELOPMENT.md). A
fifteen-minute walkthrough: [DEMO_GUIDE.md](DEMO_GUIDE.md).

## 12. Demo accounts and credentials — COMPLETE

**There are no passwords anywhere in this project.** Local sign-in mints a
short-lived JWT signed by a keypair generated on your machine:

```bash
python scripts/dev.py token user-donor-1
```

| Account | Role | Demonstrates |
|---|---|---|
| `user-donor-1` | DONOR | Donation history, impact milestones |
| `user-donor-5` | DONOR, opted out | Notification suppression |
| `user-bb-admin-1` | BLOOD_BANK_ADMIN | Inventory, corrections, verification |
| `user-bb-staff-1` | BLOOD_BANK_STAFF | Stock updates but **not** verification |
| `user-hosp-auth-1` | HOSPITAL_AUTHORIZER | Priority certification |
| `user-hosp-staff-1` | HOSPITAL_STAFF | Raising requests but **not** certifying |
| `user-camp-org-1` | CAMP_ORGANIZER | Camp management, donation verification |
| `user-camp-staff-1` | CAMP_STAFF | Check-in, camp-scoped |
| `user-admin-1` | PLATFORM_ADMIN | Organization verification, suspension, audit |
| `user-suspended-1` | BLOOD_BANK_ADMIN, suspended | **Every action refused despite a valid token** |

Safe handling, verified:

- The keypair lives in `.local-keys/`, which is **gitignored as a whole
  directory** — hardened during this handover, because only `*.pem` was
  covered before and a key generated with another extension would have
  leaked.
- Tokens expire after 12 hours.
- The local auth path requires a key file that does not exist in a deployment.
- `.env` is gitignored; `.env.example` contains placeholders only.
- Verified before documenting the publish commands: of the 233 files a publish
  would add, **zero** match a secret pattern.

## 13. Commands to start the application — COMPLETE

| Step | Command |
|---|---|
| Datastore | `python scripts/dev.py db-start` |
| Tables | `python scripts/dev.py create-tables` |
| API | `python scripts/local_server.py --port 8080` |
| Frontend | `cd frontend && npm run dev` |
| Status | `python scripts/dev.py status` |
| Token | `python scripts/dev.py token <user-id>` |

## 14. Commands to seed and reset demo data — COMPLETE

```bash
python scripts/seed_demo.py              # seed (idempotent)
python scripts/seed_demo.py --reset      # remove all demoData items, then seed
python scripts/seed_demo.py --validate   # 24 coverage checks, no writes
```

Deterministic (seed `20261115`), so screenshots and documentation stay
accurate across rebuilds. Three independent guards refuse to run against
anything that looks like production: the environment name must be local/dev/
development/test, `DYNAMODB_ENDPOINT` must be set, and it must not contain
`amazonaws.com`.

## 15. Commands to run tests — COMPLETE

```bash
cd backend && python -m pytest                      # 604 tests (was 296 when this was written)
cd backend && python -m pytest tests/unit           # 254, under a second
cd backend && python -m pytest tests/integration    # 42, moto
cd frontend && npm run test -- --run                # 245 tests (was 36 when this was written)

python scripts/generate_openapi.py --check          # spec freshness gate
cfn-lint infrastructure/template.yaml
sam validate --lint --template infrastructure/template.yaml
python scripts/build_books.py                       # rebuilds and validates the books
```

## 16. Actual test results — COMPLETE

Run 15 November 2026 on a clean tree.

| Suite | Tests | Result | Time |
|---|---|---|---|
| `tests/unit/test_camps_and_impact.py` | 50 | pass | |
| `tests/unit/test_geo_coverage.py` | 34 | pass | |
| `tests/unit/test_authorization.py` | 33 | pass | |
| `tests/unit/test_freshness_and_eligibility.py` | 31 | pass | |
| `tests/unit/test_emergency.py` | 30 | pass | |
| `tests/unit/test_geo_and_ranking.py` | 27 | pass | |
| `tests/unit/test_compatibility.py` | 27 | pass | |
| `tests/unit/test_inventory_operations.py` | 22 | pass | |
| `tests/integration/test_end_to_end_scenarios.py` | 21 | pass | |
| `tests/integration/test_inventory_integration.py` | 15 | pass | |
| `tests/integration/test_camp_reminders.py` | 6 | pass | |
| **Backend total** | **400** | **all pass** | 12.66 s |
| `src/test/apiClient.test.js` | 18 | pass | |
| `src/test/StatusBadges.test.jsx` | 18 | pass | |
| **Frontend total** | **80** | **all pass** | 2.3 s |
| **Grand total** | **480** | **all pass** | |

Nothing skipped, xfailed or marked expected-failure.

Other gates, same run: OpenAPI matches the route table · `cfn-lint` exit 0 ·
`sam validate --lint` valid · book build 27/27 checks.

**Not done:** load testing (nothing deployed to test), penetration testing,
dependency CVE scanning in CI.

## 17. Edge cases implemented and tested — COMPLETE

[EDGE_CASE_REGISTER.md](EDGE_CASE_REGISTER.md) lists **116** cases with an
honest status each: **72 TESTED**, **39 IMPLEMENTED** (handled, not
individually asserted), **1 PARTIAL**, **4 NOT HANDLED**.

The four not handled are named in the register rather than summarised away.

The cases that shaped the design:

| Case | Behaviour |
|---|---|
| Facility has never reported | `UNKNOWN`, `eligibleUnits: null` — not zero |
| Batch expiry unparseable | Eligibility **refused**, not assumed |
| Two writers on one batch | Version condition; bounded retry; 409 if exhausted |
| Last camp place, two registrants | Transaction; one gets `CAPACITY_EXCEEDED` |
| Same donation verified twice | Ledger row keyed on donation id; credited once |
| Hospital suspended after raising a request | Certification refused — verification re-checked at certification time |
| Suspended user with a valid token | Refused on the next request |
| Stale automated feed arrives late | Rejected by source timestamp |
| Routing provider fails | Road distance reported **unavailable**, straight line not substituted |
| Unknown blood group in compatibility lookup | Empty tuple, no guess |
| Future-dated timestamp | Freshness `UNKNOWN`, not "very fresh" |
| Geolocation denied, unavailable, timed out, insecure context | All four handled distinctly |

## 18. Security review findings — COMPLETE

Documented in [SECURITY.md](SECURITY.md) with residual risk stated per threat.

Strengths found: database-backed authorization makes revocation immediate;
central ownership comparison closes IDOR across all 50 routes; the audit
table's write-only IAM grant means the application cannot rewrite history;
automatic log redaction covers more fields than the schema uses, so adding a
field cannot silently start logging it.

Residual risks stated rather than hidden:

| Risk | Status |
|---|---|
| Stolen token usable until the next request | Accepted; window is one request |
| An account administrator could alter the audit table outside the application | Accepted; IAM limits the application, not an administrator |
| Free-text fields could carry personal data past redaction | Mitigated by interface guidance only |
| The local auth path would be a serious issue if it ever ran in a deployment | Guarded by a key file that does not exist in AWS; **an explicit environment refusal would be stronger** |
| No dependency CVE scanning | **NOT IMPLEMENTED** |
| No penetration test, no professional review | **NOT IMPLEMENTED** |

One security issue was found and fixed during this handover: `.local-keys/`
was not gitignored as a directory, only `*.pem` was. See item 12.

## 19. Cost estimate and assumptions — COMPLETE

[AWS_COST_ESTIMATE.md](AWS_COST_ESTIMATE.md).

> **Measured, 26 November 2026.** Actual billing for 1–25 November 2026:
> **$0.1628 gross usage**, **−$0.1628 credits**, **$0.00 net payable**. A full
> month projects to roughly **$0.45–$0.50 gross**, still $0.00 net while
> credits last. The only recurring charge is the **$0.40 Secrets Manager
> secret**, which has never been accessed. **No Amazon Location index charge
> and no customer-managed KMS key charge were incurred.** About 11% of gross
> usage came from Cost Explorer and verification traffic rather than from
> running the system, and billing data can lag 24 hours. The estimates below
> are the original projections.

| Scenario (original estimate) | Monthly |
|---|---|
| Deployed and idle | **$1.40 fixed** — $1.00 Amazon Location index + $0.40 Secrets Manager |
| Demonstration traffic | **$1.40–4.40** |
| 100,000 users | **~$160** |

Assumptions: Free Tier applies in the first 12 months for API Gateway and SES;
DynamoDB on-demand; 8 alarms fall inside the 10 free; 30-day log retention.

**The cost that grows quietly is CloudWatch Logs ingestion at $0.50/GB**, which
is why retention is set on every log group in the template rather than left at
"never expire".

Not included: a custom domain, WAF, or any advanced feature requiring account
activation. The figures above are AWS list prices applied to modelled volumes.

> **Observed charges, 26 November 2026.** LifeLink is deployed and the actual
> bill is known: **$0.1628 gross usage** for 1–25 November 2026,
> **−$0.1628 credits**, **$0.00 net payable**. A full month projects to about
> **$0.45–$0.50 gross**. The only recurring charge is the **$0.40 Secrets
> Manager secret**, never accessed; the anticipated $1.00 charges were never
> incurred. About 11% of gross usage came from Cost Explorer and verification
> traffic rather than from running the system, and billing data can lag
> 24 hours.

## 20. PDF books and verified page counts — COMPLETE

Built and validated 15 November 2026 by `python scripts/build_books.py`.

| Book | File | Pages | Chapters | Figures | Tables | Listings | Words | Checks |
|---|---|---|---|---|---|---|---|---|
| 1 — System Architecture and AWS Cloud Engineering | `docs/books/LifeLink_Book_1_System_Architecture_and_AWS.pdf` | **78** | 30 | 16 | 45 | 28 | 16,113 | 9/9 |
| 2 — Implementation and Operations Guide | `docs/books/LifeLink_Book_2_Implementation_and_Operations.pdf` | **145** | 50 | 7 | 32 | 132 | 25,686 | 9/9 |
| 3 — Engineering Concepts, Viva and Interview Preparation | `docs/books/LifeLink_Book_3_Interview_Viva_and_Engineering.pdf` | **95** | 61 | 5 | 6 | 13 | 26,172 | 9/9 |
| **Total** | | **318** | **141** | **28** | **83** | **173** | **67,971** | **27/27** |

Editable Markdown sources: `docs/books/<slug>/` — 34 files.

These are generated from the repository, not written about it. Code listings
are extracted at build time by function name or content anchor; metrics come
from running the suites; eight checks run per book and a failure fails the
build. The checks include body-frame-only blank-page detection, listing-caption
counting (a caption without its code is a failure), clipping detection,
unresolved-directive detection and exact table-of-contents page numbers.

Validation report: [DOCUMENTATION_VALIDATION.md](DOCUMENTATION_VALIDATION.md).

Honesty note on the toolchain: anything the build cannot measure is recorded as
`COULD NOT MEASURE`, never as a number. Three book defects were found only by
**reading rendered pages** rather than by a passing check — dropped code
listings, blank pages and a drifted listing — and all three now have checks.

## 21. Documentation locations — COMPLETE

| Document | Covers |
|---|---|
| [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md) | What it is and why |
| [REQUIREMENTS.md](REQUIREMENTS.md) | FR-1..FR-41, NFR-1..NFR-15 |
| [ARCHITECTURE.md](ARCHITECTURE.md) | System shape, layering, invariants |
| [ARCHITECTURE_DECISIONS.md](ARCHITECTURE_DECISIONS.md) | 17 ADRs with rejected alternatives |
| [DATABASE_DESIGN.md](DATABASE_DESIGN.md) | 11 tables, 23 GSIs, 39 access patterns |
| [API_DOCUMENTATION.md](API_DOCUMENTATION.md) | Conventions, error codes, worked examples |
| `openapi.json` / `openapi.yaml` | Generated from the route table |
| [SECURITY.md](SECURITY.md) | Authentication, authorization, threats, residual risk |
| [PRIVACY_AND_DATA_HANDLING.md](PRIVACY_AND_DATA_HANDLING.md) | Data map, redaction, retention, open legal questions |
| [TESTING.md](TESTING.md) | Strategy and what is deliberately not tested |
| [EDGE_CASE_REGISTER.md](EDGE_CASE_REGISTER.md) | 116 cases with status |
| [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md) | Every limitation, stated plainly |
| [LOCAL_DEVELOPMENT.md](LOCAL_DEVELOPMENT.md) | Setup from scratch |
| [DEPLOYMENT.md](DEPLOYMENT.md) | Deployment procedure (**unexecuted**) |
| [OPERATIONS_RUNBOOK.md](OPERATIONS_RUNBOOK.md) | 12 procedures, alarm-indexed |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | Symptom-first diagnosis |
| [ENVIRONMENT_VARIABLES.md](ENVIRONMENT_VARIABLES.md) | Every variable |
| [AWS_COST_ESTIMATE.md](AWS_COST_ESTIMATE.md) | Three scenarios with assumptions |
| [DEMO_GUIDE.md](DEMO_GUIDE.md) | A 15-minute walkthrough |
| [DEMO_DATA.md](DEMO_DATA.md) | What is seeded and why |
| [PROGRESS.md](PROGRESS.md) | Phase log, defect log, verification sweeps |
| [RELEASE_NOTES.md](RELEASE_NOTES.md) | v0.1.0 |
| [DOCUMENTATION_VALIDATION.md](DOCUMENTATION_VALIDATION.md) | Book check results |
| [PHASE_0_INVENTORY.md](PHASE_0_INVENTORY.md) | The original environment inspection |
| [FINAL_HANDOVER.md](FINAL_HANDOVER.md) | This report |

## 22. Known limitations — COMPLETE

Full list: [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md). The ones that bound
what this project can claim:

1. ~~**Nothing is deployed.**~~ **SUPERSEDED — LifeLink is deployed.** The
   original entry read: "Nothing is deployed. Every AWS operational claim is a
   design expectation." The point-in-time restore procedure is still
   **untested**.
   *(Historical, 15 November 2026. LifeLink was deployed later that day and
   again on 24 November; see [DEPLOYMENT_RECORD](DEPLOYMENT_RECORD.md) and
   [REPOSITORY_VS_DEPLOYED](REPOSITORY_VS_DEPLOYED.md). The restore procedure
   is still untested.)*
2. **The blood compatibility reference has not been reviewed by a qualified
   professional.** Marked as such in the data file, the API response, the
   interface and all three books; the loader refuses to start without a review
   status field. **This system must not be used for clinical decisions.**
3. **SMS is not implemented** — denied by the account's service control
   policy.
4. **Email is sandboxed** — verified recipients only.
5. **Account deletion is not implemented.** Suspension is immediate and
   complete as an access control, but no endpoint deletes a user, because the
   policy questions about records other organizations depend on are unanswered.
6. **Retention for donations and audit entries is unbounded** — an open legal
   question, not a decision.
7. **The privacy notice and terms are placeholders requiring legal review.**
8. **No load testing.** The concurrency design is reasoned and unit-tested,
   not measured under load.
9. **Cognito has never been exercised against the real service.** The local
   token issuer differs; the verifier is the same code path.
10. **4 of 116 edge cases are not handled**, each named in the register.
11. **All data is synthetic.** No real institution in the dataset exists, and
    no real personal data has ever been entered, in any environment.

## 23. Deployment status — COMPLETE

**LifeLink is deployed and live.**

| | |
|---|---|
| Website | **https://d324z37do52g8f.cloudfront.net** |
| API | https://uk6itz2a5b.execute-api.ap-southeast-2.amazonaws.com/dev |
| Stack | `lifelink-dev`, `UPDATE_COMPLETE`, 50 resources |
| Account / region | 426150327442 / ap-southeast-2 |
| Fixed cost | **$0.40/month** (Secrets Manager); $120 credits cover it |

Deployment found **five defects that passed every local test and both template
linters**: the Lambda handler path was wrong, the package needed Linux arm64
wheels built without Docker, the outbox publisher lacked one IAM grant,
every route 404ed on the API Gateway stage prefix, and the "unknown is not
zero" rule was broken in one of two code paths. All five are fixed, verified
live, and each is now covered by tests.

Full record, including everything verified against the running system:
[DEPLOYMENT_RECORD.md](DEPLOYMENT_RECORD.md).

## 24. AWS operations performed, and what remains — COMPLETE

Performed under your explicit approval (with the AWS-managed KMS key you chose):

| Operation | Result |
|---|---|
| `sam deploy` | 50 resources created |
| DynamoDB tables | 11 created, 7 with point-in-time recovery |
| Cognito user pool, client, domain, identity pool | Created; 8 demo users provisioned |
| Amazon Location map, place index, route calculator | Created |
| S3 + CloudFront with Origin Access Control | Created; frontend published |
| Secrets Manager secret | Created ($0.40/month) |
| 8 alarms, 1 dashboard, 2 log groups | Created, 30-day retention |
| Synthetic data seeded into deployed DynamoDB | 419 batches, 16 facilities, 24/24 checks |

Still not performed:

| Operation | Why |
|---|---|
| SES production access request | Sandbox is sufficient for the demonstration |
| Service Quotas increase (concurrency 10) | Not needed at demonstration volume |
| Point-in-time restore rehearsal | **Runbook §8 remains marked UNTESTED** |
| Load testing | No measurement taken |
| Custom domain, WAF | Out of scope |

## 25. Steps to publish to GitHub yourself — BLOCKED (awaiting you)

**Nothing has been pushed. No remote was created or modified.**

> **Read this first.** An `origin` remote already exists, pointing at
> `https://github.com/Harshdeep47/LifeLink.git`, and `main` already tracks it.
> **A bare `git push` would publish immediately.** The repository is currently
> one commit ("Initial commit: Add Git ignore configuration") with everything
> else untracked.

Verified for you before writing these commands: 233 files would be added, and
**zero** match a secret pattern. `.env`, `.local-keys/` (hardened during this
handover), `*.pem`, `*.key`, `credentials`, `.venv/`, `node_modules/` and
`dist/` are all excluded.

> **Superseded, 24 November 2026.** This publication sequence was carried out:
> the repository is public at `github.com/Harshdeep47/LifeLink`, and the
> release commit is recorded in [DEPLOYMENT_RECORD](DEPLOYMENT_RECORD.md).
> The suggested commit message below is left exactly as written, and every
> figure in it is historical — the project now has 904 tests, 12 DynamoDB
> tables, 58 routes and 328 pages of books, and it **is** deployed. Do not
> reuse this message.

```bash
cd d:/LifeLink

# 1. See exactly what would be published, before staging anything.
git status --untracked-files=all

# 2. Confirm for yourself that no secret is included.
git status --porcelain --untracked-files=all | grep -iE "\.env$|local-keys|\.pem|\.key$|credential"
#    Expect no output.

# 3. Stage and review.
git add -A
git status
git diff --cached --stat

# 4. Commit.
#    SUPERSEDED: this was done. Every figure in the message below is historical
#    (the project now has 904 tests, 12 tables, 58 routes, 328 pages) and it IS
#    deployed. Left verbatim as a record; do not reuse it.
git commit -m "LifeLink v0.1.0: seven features, 332 tests, three technical books

Blood availability and donation coordination platform.
Backend: Python on Lambda, 11 DynamoDB tables, 50 routes.
Frontend: React 18 and Vite.
Infrastructure: SAM template, validated, not deployed.
Documentation: 318 pages across three generated PDF books.

Not deployed to AWS. All data synthetic. The blood compatibility
reference is unreviewed and must not be used clinically."

# 5. Confirm the remote is the one you intend.
git remote -v

# 6. Publish.
git push -u origin main
```

If you would rather publish somewhere else, replace step 5 with
`git remote set-url origin <your-url>` first.

**Before making the repository public, consider:** the README and books state
plainly what is and is not verified — that the compatibility reference is
unreviewed, that all data is synthetic, that no restore has been rehearsed and
that twelve browser checks remain outstanding. Keep those statements. They are
what make the project defensible rather than overclaiming.

*(Updated 26 November 2026: the deployment-status statements have been
corrected throughout — LifeLink is deployed. The honesty statements about
synthetic data, the unreviewed reference and unverified workflows stand
unchanged.)*

> *Updated 24 November 2026: the repository is now public and the deployment
> statements were corrected at source, since the project is deployed. The
> other two statements stand unchanged, and the principle behind this
> paragraph is the reason the corrections were made by stating the new truth
> rather than by deleting the old caveats.*

## 26. Recommended next steps

In the order I would do them.

**First, two things that cost nothing and remove real risk:**

1. **Make the local auth path refuse to run outside a local environment.**
   Today it is protected by a key file that happens not to exist in AWS. An
   explicit environment check that raises on startup would be a few lines and
   closes the one residual security risk I would not want to leave implicit.
2. **Add dependency CVE scanning** (`pip-audit`, `npm audit`) as a build gate
   alongside the five that already exist.

**Then, if you intend to deploy:**

3. Deploy to a `dev` stack and set a spend limit **first**, in AWS Settings.
   *(Measured on the deployed stack: the only recurring charge is $0.40/month
   for the Secrets Manager secret. The anticipated $1.00 charges were never
   incurred.)*
4. **Rehearse the restore procedure** and then remove the UNTESTED marker from
   [OPERATIONS_RUNBOOK.md](OPERATIONS_RUNBOOK.md) §8. An untested restore is
   not a backup strategy.
5. Exercise Cognito end to end, which is the largest gap between the local and
   deployed paths.
6. Load-test against the concurrency ceiling of 10 and confirm the throttling
   behaviour the design predicts.
7. Request a concurrency increase if the figures justify it. No code change is
   needed.

**Before any real user data:**

8. Get the compatibility reference reviewed by a qualified professional, or
   remove the feature. It is the weakest claim in the project.
9. Get the privacy notice and terms written properly.
10. Decide the retention and deletion questions in
    [PRIVACY_AND_DATA_HANDLING.md](PRIVACY_AND_DATA_HANDLING.md) §11, then
    implement account deletion against those answers.

**Lower priority:**

11. The 4 unhandled edge cases in the register.
12. Push notifications, if the channel is wanted.
13. A custom domain and WAF.

---

## Summary

| Deliverable | Status |
|---|---|
| Seven features implemented and integrated | **COMPLETE** |
| **Deployed to AWS and verified live** | **COMPLETE** — https://d324z37do52g8f.cloudfront.net |
| Synthetic data in the deployed database | **COMPLETE** — 24/24 checks, 419 batches, 16 facilities |
| Cognito authentication verified on the live API | **COMPLETE** — real tokens, RBAC and IDOR refusals confirmed |
| 480 automated tests | **COMPLETE** — all passing, measured |
| Seven verification gates | **COMPLETE** — tests, frontend, OpenAPI, cfn-lint, SAM, dependency audit |
| Local-auth fail-closed refusal | **COMPLETE** — 45 tests; closed a real bypass |
| Dependency vulnerability gate | **COMPLETE** — shipped deps clean; 8 dev-only findings reported |
| Three PDF books, 318 pages | **COMPLETE**, but **predate deployment** — superseded on that point by [DEPLOYMENT_RECORD.md](DEPLOYMENT_RECORD.md) |
| 26 supporting documents | **COMPLETE** |
| Cognito hosted-UI browser redirect | **NOT IMPLEMENTED** — tokens are real, the redirect is not built |
| Map tiles rendering in a browser | **NOT VERIFIED** |
| Point-in-time restore rehearsal | **NOT IMPLEMENTED** — runbook §8 marked UNTESTED |
| Load testing, penetration testing | **NOT IMPLEMENTED** |
| Clinical review of the compatibility data | **NOT IMPLEMENTED** — needs a professional |
| GitHub publication | **NOT IMPLEMENTED** — commands prepared, awaiting you |

The boundaries you set held throughout: nothing was deployed before your
explicit approval and nothing beyond it, nothing was pushed to GitHub, no
destructive operation touched anything but five synthetic batches I had created
minutes earlier (previewed first, reported in full), and nothing is marked
complete that was not verified by a command whose output is recorded here or in
[DEPLOYMENT_RECORD.md](DEPLOYMENT_RECORD.md).
