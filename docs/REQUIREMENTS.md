# LifeLink — Requirements

## Functional requirements

| ID | Requirement | Feature | Status |
|---|---|---|---|
| FR-1 | Record blood stock at batch granularity, group and component tracked independently | 1 | Implemented |
| FR-2 | Compute eligibility dynamically, failing closed on missing or incoherent data | 1 | Implemented |
| FR-3 | Report freshness and independent verification as two separate, simultaneously visible signals | 1 | Implemented |
| FR-4 | Support manual entry, corrections, quarantine, release and external API ingestion | 1 | Implemented |
| FR-5 | Reject a delayed external update that would overwrite newer state | 1 | Implemented |
| FR-6 | Never allow a negative available quantity | 1 | Implemented |
| FR-7 | Let a user register a short-term need and be notified on matching stock | 1 | Implemented |
| FR-8 | Never present an alert as a reservation | 1 | Implemented |
| FR-9 | Discover facilities near a point with geospatial pre-filtering, no scans | 2 | Implemented |
| FR-10 | Filter by group, component, availability, freshness and verification | 2 | Implemented |
| FR-11 | Rank by a documented, configurable, explainable formula | 2 | Implemented |
| FR-12 | Never let ranking override hard eligibility | 2 | Implemented |
| FR-13 | Keep UNKNOWN distinct from zero throughout | 2 | Implemented |
| FR-14 | Distinguish straight-line from road distance | 2 | Implemented |
| FR-15 | Preserve discovery and contact options when routing fails | 2 | Implemented |
| FR-16 | Run the camp lifecycle from proposal to completion | 3 | Implemented |
| FR-17 | Keep registration, attendance, donation and verification distinct | 3 | Implemented |
| FR-18 | Prevent a donor verifying their own donation | 3 | Implemented |
| FR-19 | Credit impact exactly once per verified donation | 3 | Implemented |
| FR-20 | Notify opted-in donors within a configurable radius defaulting to 10 km | 3 | Implemented |
| FR-21 | Never restrict camp *search* by the notification radius | 3 | Implemented |
| FR-22 | Send 24-hour and 2-hour reminders, re-checking every precondition | 3 | Implemented |
| FR-23 | Issue recognition certificates from verified records only, private to the donor | 3 | Implemented |
| FR-24 | Accept emergency requests with validation, consent and duplicate suppression | 4 | Implemented |
| FR-25 | Restrict clinical priority certification to authorized hospital roles | 4 | Implemented |
| FR-26 | Re-check hospital verification during sensitive operations | 4 | Implemented |
| FR-27 | Match deterministically against versioned compatibility reference data | 4 | Implemented |
| FR-28 | Schedule by priority with a fairness mechanism preventing starvation | 4 | Implemented |
| FR-29 | Never let fairness alter clinical priority | 4 | Implemented |
| FR-30 | Record provider responses without double-counting stock | 4 | Implemented |
| FR-31 | Enforce a documented request lifecycle, rejecting invalid transitions | 4 | Implemented |
| FR-32 | Provide role-appropriate dashboards for six roles | 5 | Implemented |
| FR-33 | Make synthetic demo data unmistakable | 5 | Implemented |
| FR-34 | Enforce authorization server-side on every request | 6 | Implemented |
| FR-35 | Reject a valid token from a suspended account | 6 | Implemented |
| FR-36 | Prevent cross-organization access and insecure direct object references | 6 | Implemented |
| FR-37 | Audit every privileged operation with actor, action, resource and time | 6 | Implemented |
| FR-38 | Keep sensitive data out of logs, URLs and error messages | 6 | Implemented |
| FR-39 | Define infrastructure reproducibly | 7 | Implemented and **deployed** as stack `lifelink-dev` |
| FR-40 | Support SMS notifications | 3, 6 | **NOT IMPLEMENTED** — denied by SCP and account plan |
| FR-41 | File upload with validation and presigned URLs | 6 | **NOT IMPLEMENTED** — no upload flow built |

## Non-functional requirements

| ID | Requirement | Target | Verified |
|---|---|---|---|
| NFR-1 | No lost updates under concurrency | Zero | Yes — integration tests |
| NFR-2 | No camp oversubscription | Zero | Yes — integration tests |
| NFR-3 | No duplicate impact credit | Zero | Yes — integration tests |
| NFR-4 | No scans on user-facing paths | Zero | Yes — by design and review |
| NFR-5 | Every route declares a permission | 100% | Yes — 50 of 50 |
| NFR-6 | Unknown never rendered as zero | Always | Yes — unit and UI tests |
| NFR-7 | Geospatial search misses no in-range facility | Always | Yes — property test at 10 radii |
| NFR-8 | Search query fan-out bounded | Under 150 cells | Yes — measured, max 79 |
| NFR-9 | API p95 latency | Under 3s | **Not measured** — deployed but never load-tested |
| NFR-10 | Availability | Single region | **Not measured** |
| NFR-11 | Local runnability without AWS | Full stack | Yes |
| NFR-12 | Keyboard navigable, no colour-only status | Full | Partial — no audit run |
| NFR-13 | Recovery point objective | Seconds via PITR | **Design assumption** |
| NFR-14 | Recovery time objective | Hours | **Design assumption** |
| NFR-15 | Documentation matches implementation | Always | Yes — generated and validated |

## Constraints

| Constraint | Source | Effect on the design |
|---|---|---|
| Single AWS region `ap-southeast-2` | Account | No cross-region replication, keys or routing |
| Lambda concurrency ceiling of 10 | Account, measured | No reserved concurrency; bounded consumers; scheduled dispatcher |
| SES sandbox | Account | Verified recipients only, 200/day |
| SMS denied by SCP `p-2cb1m8xd` | Account | Channel not implemented |
| AWS Free Tier plan | Account | Service availability verified in Phase 0 |
| Deployment approval required per change | Instruction | Each deployment runs from a reviewed CloudFormation changeset |
| GitHub publication | Owner-approved | Published to `github.com/Harshdeep47/LifeLink` on `main` |
| No medically reviewed compatibility reference | Not supplied | Data marked `UNREVIEWED_SYNTHETIC` throughout |

## Traceability

Every functional requirement maps to a feature, an implementation and at least
one test. The mapping from edge cases to tests is in
[EDGE_CASE_REGISTER.md](EDGE_CASE_REGISTER.md); the mapping from the ten
specified end-to-end scenarios to test classes is in
[TESTING.md](TESTING.md).
