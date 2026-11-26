# LifeLink — Release Notes

## Repository snapshot — 24 November 2026 (before that day's deployment)

> **Corrected 26 November 2026.** This section previously opened "**Not
> deployed.** This section describes the repository, which is ahead of the live
> application." That was accurate when written and is no longer: everything was
> **deployed later the same day**, and the repository and the deployed
> application are now **in sync** — no application or infrastructure code
> changed between the deployed release `f9765af` and the current `668a771`.
>
> See [DEPLOYMENT_RECORD](DEPLOYMENT_RECORD.md) and
> [REPOSITORY_VS_DEPLOYED](REPOSITORY_VS_DEPLOYED.md) for current status.
>
> The gate figures below are a **point-in-time snapshot** taken earlier on
> 24 November and are kept as the historical record. The final verified
> figures are **657 backend and 294 frontend tests**.

Measured on 24 November 2026 by the commands named, not estimated.

| Gate | Result |
|---|---|
| `pytest backend/tests` | **604 passed** (536 unit, 68 integration) |
| `npm test` | **245 passed** (11 files) |
| `ruff check` | clean |
| `npm run lint` | clean, 0 errors |
| `npm run build` | clean |
| `cfn-lint infrastructure/template.yaml` | clean |
| `sam validate --lint` | **not run** — `sam` CLI not installed |
| `security_audit.py` | gate passed; 8 development-only findings |

**849 tests, up from 674.**

### Added

- **`ReservationQueue`** on the blood bank dashboard. Facility staff can
  accept, decline (with a reason the requester sees) and record fulfilment.
  The endpoints were always deployed and authorized; nothing in the interface
  called them, so requests arrived with no way to answer.
- **`MyActivityPage`** at `/activity`. A requester can find, track and release
  their own holds, and see emergency requests they raised. `GET
  /me/reservations` previously had no caller anywhere in the frontend.
- **Record provenance** on the facility page: identity, stock and position
  tracked and displayed as three independent claims, so a real institution name
  can never lend credibility to a demonstration quantity.
- **`eslint.config.js`.** `npm run lint` was a declared script that crashed —
  ESLint 9 needs a flat config and none existed.
- **`scripts/validate_facility_dataset.py`** and `data/real_facilities.json`:
  the provenance schema and an offline validator that refuses any unsourced
  record.
- **[ADR-0018](ARCHITECTURE_DECISIONS.md#adr-0018)** — temporary reservations
  are the ordinary request workflow; no second request entity.
  **[ADR-0019](ARCHITECTURE_DECISIONS.md#adr-0019)** — OpenStreetMap raster
  tiles, because the account SCP denies a Location API key.
- 175 tests, including the first coverage of the production Cognito verifier
  and a route-integrity check that catches dead internal links.

### Fixed

- **Expired sessions were never cleared.** `AuthContext` referenced an
  undefined `STORAGE_KEY` against `localStorage`, in a module that stores
  sessions in `sessionStorage`; the `ReferenceError` was swallowed by a bare
  `catch {}`. The user saw the expiry error on every page load until signing
  out by hand. Found by the lint that had never run.
- **ID tokens were not audience-checked.** The verifier skipped the check when
  `client_id` was absent, and an ID token never has that claim. An ID token for
  a *different* app client in the same user pool passed every gate. Latent
  rather than exploitable — the stack has one app client — but it would have
  opened silently on adding a second. Proven by reverting: three tests fail
  against the old code.
- Ten lint errors, including four dead symbols and two dead imports.
- `ReservationStatus` now uses `StrEnum`, matching the other twelve enums.

### Changed

- **"Request blood" is now "Emergency request"** in navigation and on the entry
  button. The old label routed every ordinary need into the escalated
  workflow. A regression test asserts it cannot drift back.
- `npm run lint` reports; `npm run lint:strict` keeps `--max-warnings 0`.

### Documentation corrected

Four false or stale claims, each verified against the code:

- README stated *"An offer is not a reservation. Nothing is ever held. There is
  no reservation counter"* — contradicted by the shipped reservations table and
  its pool counter.
- `DATABASE_DESIGN` stated *"No reservation or allocation model"* and gave the
  absence of a counter as the reason double-counting was impossible. Both were
  true when written. The reservations table, its two indexes and six access
  patterns (AP-40 to AP-45) are now documented.
- `SECURITY` said 35 permissions and 29 authorization tests; the code has
  **39** and **33**.
- README claimed `ruff` clean while ten findings existed.

`ADR-0017` and `ADR-0012` are marked partly superseded, with their bodies left
unedited — an ADR records what was decided at the time.

### Not done, deliberately

- **No real facility data.** Both public sources were unreachable (HTTP 404 and
  a DNS failure). Recording institution names from search summaries nobody read
  would have been fabrication. See
  [REAL_FACILITY_DATA](REAL_FACILITY_DATA.md).
- **No sweeping restyle.** The existing primitives were already consistent; a
  visual overhaul immediately before an evaluation is risk without verified
  benefit.
- **No third request entity.** [ADR-0018](ARCHITECTURE_DECISIONS.md#adr-0018).

---

## v0.1.0 — 15 November 2026

First complete build. **Not deployed to AWS.** Runs locally against a
DynamoDB-compatible endpoint; the infrastructure template is validated by two
independent tools but has never been applied.

> *Historical: true at v0.1.0. LifeLink was deployed to AWS later the same
> day — see the Unreleased section above and
> [DEPLOYMENT_RECORD](DEPLOYMENT_RECORD.md).*

All figures below were measured on 15 November 2026 by the commands named
beside them, not estimated.

---

### Verification run

| Gate | Command | Result |
|---|---|---|
| Backend tests | `python -m pytest` (in `backend/`) | **296 passed** in 12.46 s |
| Frontend tests | `npm run test -- --run` | **36 passed** in 1.79 s |
| OpenAPI freshness | `python scripts/generate_openapi.py --check` | matches the route table |
| CloudFormation lint | `cfn-lint infrastructure/template.yaml` | exit 0, no findings |
| SAM validation | `sam validate --lint` | valid SAM template |
| Book build | `python scripts/build_books.py` | 3 books, **27/27** checks passed |

---

### What this release contains

**Feature 1 — Inventory and availability.** Batch-level stock with eight blood
groups and four components. Seven stock operations
(`ADD`, `DEDUCT`, `CORRECT`, `QUARANTINE`, `RELEASE_QUARANTINE`, `WITHDRAW`,
`EXPIRE`), each written under a conditional expression so stock cannot go
negative and a lost update cannot occur. Verification is a separate action
from any stock edit, and exactly one repository method is permitted to write
the verification timestamp. Four-state availability — available with a count,
none in stock, not reported, not stocked — with an ingest path that rejects
stale feeds by source timestamp. Standing availability alerts with TTL.

**Feature 2 — Location-based discovery.** Three geohash precisions selected by
search radius, each with its own index. Bounding-box cell coverage with a
nearest-corner intersection test, bounded at 150 cells. Haversine distance,
optional road distance from Amazon Location (reported as unavailable rather
than substituted when routing fails), and a ranked result set that explains
its own ranking.

**Feature 3 — Donation camps.** Six lifecycle states with an enumerated
transition table. Registration and the capacity counter are written in one
transaction, so a camp cannot be oversubscribed by concurrent registrations.
Check-in, donation recording, and a verification step that credits the impact
ledger exactly once via a ledger row keyed on the donation id. Donor profile,
donation history and certificates.

**Feature 4 — Emergency coordination.** Requests carry a clinical priority
only once an authorized clinician certifies them; the hospital's verification
is re-checked at the moment of certification, not cached. Compatible donor
groups come from a reference table that **refuses to load without a review
status field** and returns an empty tuple for an unknown group. Provider
responses record an **offer, not a reservation** — nothing is decremented.
A scheduled dispatcher matches requests by effective priority, computed as a
returned value that never mutates the certified clinical priority.

**Feature 5 — Web interface.** React 18 and Vite 6, 28 modules. MapLibre GL JS
used as a renderer only. Every availability figure carries two independent
signals — freshness band and verification state. A non-dismissible synthetic
data banner. Error boundaries, abortable requests, and a single fetch point
that attaches the correlation id, bearer token and idempotency key.

**Feature 6 — Security, identity and observability.** One authorization
decorator applying five ordered checks over 35 permissions and 10 roles, with
roles and account status read from the database on every request so
suspension and revocation are immediate. Organization scoping on every
owned resource. Append-only audit trail whose IAM grant is `PutItem` and
`Query` only. Structured JSON logs with recursive redaction and a correlation
id propagated from the browser through SQS into background workers.

**Feature 7 — Infrastructure.** A single SAM template, 59 resources, 11
DynamoDB tables with 23 global secondary indexes, two queues with two
dead-letter queues, a transactional outbox on a DynamoDB stream, five Lambda
functions, eight alarms each mapped to a runbook step, and a five-widget
dashboard.

---

### Documentation

Three PDF books, generated from the repository rather than written about it.
Code listings are extracted at build time by function name or content anchor;
metrics are measured by running the suites; eight validation checks run per
book and a failure fails the build.

| Book | Pages | Chapters | Figures | Tables | Listings | Words |
|---|---|---|---|---|---|---|
| 1 — System Architecture and AWS Cloud Engineering | 78 | 30 | 16 | 45 | 28 | 16,113 |
| 2 — Implementation and Operations Guide | 145 | 50 | 7 | 32 | 132 | 25,686 |
| 3 — Engineering Concepts, Viva and Interview Preparation | 95 | 61 | 5 | 6 | 13 | 26,172 |
| **Total** | **318** | **141** | **28** | **83** | **173** | **67,971** |

Editable Markdown sources live beside each PDF in `docs/books/<slug>/`.

Twenty-four documents in `docs/`, including a 116-case edge register, 17
architecture decision records each naming the alternative that was rejected,
and an operations runbook.

---

### Five rules the implementation enforces

Stated here because they are the substance of the build, not decoration:

1. **Unknown is not zero.** A facility that has never reported returns
   `UNKNOWN` with `eligibleUnits: null`. A user who sees zero does not call; a
   user who sees *not reported* calls and may find supply.
2. **Updated is not verified.** Freshness and verification are separate
   signals on every figure. A number thirty seconds old from an automated feed
   proves recency, not accuracy.
3. **An offer is not a reservation.** A provider response records an
   intention. No stock is held, and the interface says so.
4. **Dispatch order is not clinical priority.** The dispatcher computes an
   effective ordering; it never writes to the certified clinical priority.
5. **Fail closed.** Missing or invalid data produces a refusal with a reason
   code, never an optimistic default. Eligibility on a batch with an
   unparseable expiry is refused, not assumed.

---

### Defects found and fixed during this build

Listed because the ones that mattered were silent failures, not exceptions.

| Defect | How it presented | Found by |
|---|---|---|
| Geohash search covered only the centre cell and its neighbours | A facility 25.6 km away never appeared in a 30 km search. No error. | Integration test with real inter-city distances |
| The first fix queried 2,107 cells at 100 km | Correct results, unacceptable fan-out | Bounded-query assertion in the same test file |
| `put()` reported a version conflict as a duplicate | The retry path never engaged; the user was told the record already existed | Reading the conflict handling while documenting it |
| `to_dynamo()` stripped `None` from expression values | Any update setting an optional field to null failed | Writing the null-handling section of Book 2 |
| Four unused expression placeholders | `ValidationException` naming nothing | A regex detector written over the repositories |
| `create_camp` never populated the reminder index | Camp reminders would never fire | Writing the known-limitations table |
| Code listings silently dropped from the PDFs | Caption present, code absent | **Reading a rendered page** — no check caught it |
| Blank pages in all three books | A double page break per chapter | Reading rendered pages; the first validator counted the running header as content |
| A line-number include drifted | A listing captioned "the audit IAM grant" showed queue configuration | Reading the rendered listing |
| Test count recorded as `0` | `-q` suppresses the summary line in this pytest version | Checking a measured figure against a manual run |
| `setState` during render in `FindBloodPage` | React console warning | Browser console |

The last four are documentation-toolchain defects. They are listed with the
code defects deliberately: a book that silently drops a code listing is as
wrong as a search that silently drops a facility.

---

### Known limitations

Full list in [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md). The ones that
affect what this release can honestly claim:

- **Not deployed at the time of this snapshot.** *(Corrected 26 November
  2026: deployment happened later the same day. Operational claims have since
  been verified by 56 live checks against the running system.)* The
  point-in-time restore procedure in the runbook remains **untested** — it has
  never been rehearsed.
- **The blood compatibility reference has not been reviewed by a qualified
  professional.** It is marked as such in the data file, in the API response,
  in the interface and in all three books. The loader refuses to start without
  a review status field. **This system must not be used for clinical
  decisions.**
- **SMS is not implemented.** The account's service control policy denies the
  required actions. Requesting the channel returns
  `503 CHANNEL_UNAVAILABLE` rather than appearing to send.
- **Email is sandboxed.** SES in sandbox mode delivers only to verified
  addresses.
- **Account deletion is not implemented.** Suspension is immediate and
  complete as an access control, but no endpoint deletes a user. The reason is
  unresolved policy questions about records other organizations depend on —
  see [PRIVACY_AND_DATA_HANDLING.md](PRIVACY_AND_DATA_HANDLING.md) §6.
- **Retention for donations and audit entries is unbounded.** An open legal
  question, not a decision.
- **The privacy notice and terms are placeholders requiring legal review.**
- **No load testing has been performed.** The concurrency design is reasoned
  and unit-tested; it has not been measured under load.
- **Four of 116 edge cases are not handled**, each listed explicitly in
  [EDGE_CASE_REGISTER.md](EDGE_CASE_REGISTER.md).
- **All data is synthetic.** No real institution in the dataset exists, and no
  real personal data has been entered in any environment.

---

### Constraints this build was designed around

| Constraint | Measured or confirmed | Effect on the design |
|---|---|---|
| Lambda concurrent executions: **10** | `aws lambda get-account-settings` | No reserved concurrency anywhere; queue consumers capped at 2; a scheduled dispatcher instead of per-priority consumers; API throttled at 10 rps |
| Single region: `ap-southeast-2` | Account configuration | Within-region recovery only; no cross-region replication |
| Free plan | `aws freetier get-account-plan-state` | Service selection restricted to the supported list |
| SMS denied by SCP | Policy check | Channel not implemented |
| DynamoDB Local unavailable in this environment | Download blocked | moto in server mode as the local endpoint (ADR-0011) |

The architecture needs no change to use a higher concurrency limit — the
ceiling shaped the configuration, not the structure.

---

### Not published

This release has not been pushed to any remote. The repository has an `origin`
remote configured and `main` tracks it, so a bare `git push` **would** publish.
Publishing commands are provided in [DEPLOYMENT.md](DEPLOYMENT.md) for the
owner to run deliberately; none has been executed.
