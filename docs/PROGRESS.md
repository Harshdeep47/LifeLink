# LifeLink — Build Progress Log

Statuses follow spec PART 20: **COMPLETE** (implemented and verified) ·
**PARTIAL** (implemented, not fully verified) · **BLOCKED** ·
**NOT IMPLEMENTED**.

**Last updated:** 2026-11-15, after deployment to AWS and the final verification sweep.

> **A build log, not a status page.** Entries record what was true on the day
> they were written and are not retrospectively edited, because the record of
> how the project went is the useful thing about them. Totals below are
> therefore historical: the suite stood at 332 tests here and stands at **849**
> today. For current figures see [TESTING](TESTING.md); for what is deployed
> versus what is only in the repository, see
> [REPOSITORY_VS_DEPLOYED](REPOSITORY_VS_DEPLOYED.md).

---

## Boundaries in force

| Boundary | Status |
|---|---|
| No AWS deployment / no charges without explicit approval | **Honoured** — deployed only after explicit approval, with the AWS-managed KMS key the owner chose; $0.40/month fixed |
| No GitHub push, no remote changes | **Honoured** — remote `origin` left exactly as found; nothing pushed |
| No destructive operations | **Honoured with one disclosed exception** — 5 synthetic batches I had created ~20 min earlier were deleted to reconcile the dataset with its documented scenarios; previewed first, each one reported, 487 items untouched |
| Never mark unverified work COMPLETE | **Enforced** — see the PARTIAL rows below |
| Never invent test results | **Enforced** — every figure in this log names the command that produced it |

---

## Final verification sweep — 2026-11-15 (post-deployment)

| Gate | Command | Result |
|---|---|---|
| Backend tests | `python -m pytest` in `backend/` | **400 passed**, 0 failed, 12.66 s |
| Frontend tests | `npm run test -- --run` | **80 passed**, 0 failed |
| OpenAPI freshness | `python scripts/generate_openapi.py --check` | matches the route table |
| CloudFormation lint | `cfn-lint infrastructure/template.yaml` | exit 0, no findings |
| SAM validation | `sam validate --lint` | valid SAM template |
| **Dependency audit (new, 7th gate)** | `python scripts/security_audit.py` | **PASSED** — nothing that ships has a known vulnerability; 8 dev-only findings reported |
| Book build | `python scripts/build_books.py` | 3 books, 27/27 checks (run **before** deployment) |

**480 automated tests, all passing.** Nothing skipped or xfailed.

Live verification of the deployed system is recorded separately in
[DEPLOYMENT_RECORD.md](DEPLOYMENT_RECORD.md) §5.

## Deployment — 2026-11-15

| | |
|---|---|
| Website | **https://d324z37do52g8f.cloudfront.net** |
| API | https://uk6itz2a5b.execute-api.ap-southeast-2.amazonaws.com/dev |
| Stack | `lifelink-dev`, 50 resources, `UPDATE_COMPLETE` |
| Fixed cost | $0.40/month, against $120 of credits |

Three deployment attempts were needed. The first rolled back on an IAM grant
Lambda validates only at event-source-mapping creation; the second succeeded
but every route 404ed on the API Gateway stage prefix; the third was clean.

## Phase status

| Phase | Description | Status |
|---|---|---|
| 0 | Workspace and account discovery | **COMPLETE** |
| 1 | Architecture and foundations | **COMPLETE** |
| 2 | Project foundation | **COMPLETE** |
| 3 | Shared platform (auth, RBAC, logging, responses) | **COMPLETE** |
| 4 | Feature 1 — Inventory and alerts | **COMPLETE** |
| 5 | Feature 2 — Location and discovery | **COMPLETE** |
| 6 | Feature 3 — Camps and donors | **COMPLETE** |
| 7 | Feature 4 — Emergency coordination | **COMPLETE** |
| 8 | Feature 5 — Web interface | **COMPLETE** |
| 9 | Features 6 and 7 — Security, observability, infrastructure | **PARTIAL** — built and validated by two linters; **never deployed** |
| 10 | Integration and quality review | **COMPLETE** |
| 11 | Three PDF books | **COMPLETE** |
| 12 | Final local handover | **COMPLETE** |

Phase 9 is **PARTIAL** and will stay PARTIAL until a deployment happens. The
template passes `cfn-lint` and `sam validate --lint`, but a template that
lints is not a template that deploys, and marking it COMPLETE would be exactly
the kind of claim this log exists to prevent.

---

## What was built

| Area | Measured |
|---|---|
| Backend Python modules | 46 |
| Backend test modules | 11 |
| Backend tests | 296 |
| Frontend modules | 28 |
| Frontend tests | 36 |
| API routes | 50, across 43 paths |
| Permissions / roles | 35 / 10 |
| DynamoDB tables / GSIs | 11 / 23 |
| Documented access patterns | 39, none resolving to a scan on a user-facing path |
| CloudFormation resources | 59 |
| Alarms, each mapped to a runbook step | 8 |
| Architecture decision records | 17 |
| Supporting documents in `docs/` | 22 plus this log |
| Book Markdown sources | 34 files |
| Book pages | 318 (78 + 145 + 95) |

---

## Test results by suite (actual runs)

| Suite | Tests | Result |
|---|---|---|
| Domain unit tests (pure, no mocks) | 254 | pass |
| `test_geo_coverage.py` — coverage at 10 radii, bounded fan-out | 34 of the above | pass |
| Repository and service integration (moto) | 42 | pass |
| **Backend total** | **296** | **pass** |
| `apiClient.test.js` | 18 | pass |
| `StatusBadges.test.jsx` | 18 | pass |
| **Frontend total** | **36** | **pass** |

The domain suite runs in under a second with no mocks because `domain/` has no
outgoing dependencies and no module reads the clock.

---

## Book build output (2026-11-15)

| Book | Pages | Chapters | Figures | Tables | Listings | Words | Checks |
|---|---|---|---|---|---|---|---|
| 1 — System Architecture and AWS | 78 | 30 | 16 | 45 | 28 | 16,113 | 9/9 |
| 2 — Implementation and Operations | 145 | 50 | 7 | 32 | 132 | 25,686 | 9/9 |
| 3 — Engineering Concepts and Viva | 95 | 61 | 5 | 6 | 13 | 26,172 | 9/9 |

Facts collected live at build time: 38 backend modules scanned, 50 routes
enumerated from the route table, 296 tests run and parsed.

---

## Running state at handover

Verified live, not assumed:

| Component | Where | State |
|---|---|---|
| DynamoDB-compatible endpoint (moto, server mode) | `localhost:8000` | 11 tables created |
| API | `localhost:8080` | all 50 routes served |
| Frontend | `localhost:5173` | builds and serves |
| Demo data | seeded | 24/24 coverage checks passed |

Live API behaviour confirmed by request, not by reading code:

- Radius 10 km → 2 facilities · 30 km → 3 · 60 km → 6. The facility appearing
  at 30 km is Rajpura, 25.6 km out — the case the original geohash bug missed.
- `fac-chd-2` returns `"availability": "UNKNOWN"` with `"eligibleUnits": null`,
  never zero.

---

## Blockers

None outstanding. Two were resolved by documented decision rather than by a
fix, and both remain true:

| Blocker | Resolution |
|---|---|
| DynamoDB Local download blocked in this environment | moto in server mode as a DynamoDB-compatible endpoint — ADR-0011 |
| SMS delivery denied by the account's service control policy | Channel not implemented; requests return `503 CHANNEL_UNAVAILABLE` rather than appearing to send |

Awaiting the owner's decision, not blocking:

| Item | Needs |
|---|---|
| AWS deployment | Explicit approval; charges would begin |
| GitHub publication | Explicit approval; commands prepared, none executed |
| Privacy notice and terms | Legal review; current text is a placeholder |
| Retention for donations and audit entries | A policy answer |
| Account deletion | A policy answer on records other organizations depend on |

---

## Defect log

Every defect found during the build, and how. The ones that mattered were
silent — no exception, no error, wrong output.

| # | Defect | Presented as | Found by | Fixed |
|---|---|---|---|---|
| 1 | `src/platform/` would shadow stdlib `platform`, which botocore imports | Would have broken every boto3 import | Noticed before anything depended on it | Yes — renamed to `appcore` |
| 2 | Geohash search covered only the centre cell and 8 neighbours (~15 km) | A facility 25.6 km away never appeared in a 30 km search. No error. | Integration test with real inter-city distances | Yes — bounding-box coverage |
| 3 | The fix for #2 queried 2,107 cells at 100 km | Correct results, unacceptable fan-out | Bounded-query assertion | Yes — third precision tier; measured worst case now 79 cells (at 20 km), 65 at 100 km |
| 4 | Four unused DynamoDB expression placeholders | `ValidationException` naming nothing | A regex detector written over the repositories | Yes |
| 5 | `put()` reported a version conflict as `DuplicateError` | The retry path never engaged; user told the record already existed | Reading the conflict handling while documenting it | Yes — `on_conflict` parameter |
| 6 | `to_dynamo()` stripped `None` from expression values | Any update setting an optional field to null failed | Writing Book 2's null-handling section | Yes — separate `to_expression_values()` |
| 7 | `create_camp` never populated the reminder index | Camp reminders would never fire | Writing the known-limitations table | Yes — 6 regression tests |
| 8 | Code highlighter re-matched its own inserted colour codes | Malformed markup, parse failure | Book build failure | Yes — single tokenising pass |
| 9 | Line-number include drifted after an unrelated template edit | A listing captioned "the audit IAM grant" showed queue configuration | Reading the rendered listing | Yes — content anchors, plus a warning on remaining line-number includes |
| 10 | Hand-rolled YAML emitter produced invalid YAML | Multi-line descriptions broke the document | Parsing the output back | Yes — PyYAML plus a round-trip comparison |
| 11 | Test count recorded as `0` | `-q` suppresses the summary line in this pytest version | Checking a measured figure against a manual run | Yes — and unparseable output now records `COULD NOT MEASURE`, never a number |
| 12 | Blank pages in all three books | A chapter heading page break plus an explicit one | Reading rendered pages — the first validator counted the running header as content | Yes; honest page counts fell 102→73, 119→77, 92→53 before the content was expanded |
| 13 | Code listings silently dropped from the PDFs | Caption present, code absent | **Reading a rendered page** | Yes — Book 2 went 91→145 pages; a listing-caption check now guards it |
| 14 | A page containing only the word "wrong." | Widow | Reading rendered pages | Yes — `allowWidows=0` |
| 15 | False-positive directive detection on JSX object literals | Spurious build failure | Build failure on valid source | Yes — narrowed regex |
| 16 | Include selector stopped at the first brace | Anchors containing braces truncated | Build failure | Yes — non-greedy to the closing delimiter |
| 17 | `setState` during render in `FindBloodPage` | React console warning | Browser console | Yes — moved into `useEffect` |

| 18 | Lambda handler paths assumed the wrong import root | `ModuleNotFoundError: No module named 'appcore'` — the function could never have started | First deployment | Yes — package root is now `src/` contents |
| 19 | `sam build` would ship Windows x86 binaries to arm64 Linux | `cryptography` and `pydantic-core` are compiled; no Docker available | Reasoning about the build before running it | Yes — `build_lambda_package.py` pulls manylinux aarch64 wheels explicitly |
| 20 | Outbox publisher lacked `SendMessage` on its own dead-letter queue | **Stack rollback.** Lambda validates the on-failure destination grant at creation; no linter can see it | First deployment attempt | Yes |
| 21 | Every route 404ed when deployed | API Gateway serves `/dev/health`; the route table says `/health`. All 50 routes failed; all passed locally | First live request | Yes — `strip_stage_prefix()`, 19 tests |
| 22 | `LIFELINK_ENV` **defaulted to `"local"`** | A Lambda without that variable set would have used the **development token verifier instead of Cognito**. Only a missing key file prevented an auth bypass | Reading the code while hardening it | Yes — `appcore/environment.py`, 45 tests |
| 23 | Open redirect in the sign-in flow | `https://app//evil.com` yields pathname `//evil.com`, which `<Navigate>` treats as protocol-relative | Investigating the react-router advisory | Yes — `auth/redirect.js`, 44 tests |
| 24 | Critical XSS in `maplibre-gl`, high open redirect in `react-router-dom` | Both ship to browsers | The new dependency gate, on its first run | Yes — upgraded; runtime deps now report 0 vulnerabilities |
| 25 | "Unknown is not zero" broken in one of two code paths | The live API returned `"availability": "UNKNOWN", "eligibleUnits": 0` for a facility that had never reported | Querying the deployed API | Yes — domain type is now `int \| None`, 40 tests |
| 26 | Cloud seeding silently wrote to the **local** database | Console reported success against the deployed stack; AWS tables stayed empty. `seed_demo`'s import re-set `DYNAMODB_ENDPOINT` after the guard had passed | Independently querying the AWS tables | Yes — a fifth guard that inspects the real boto3 client, not the environment |
| 27 | A logic change orphaned 5 synthetic batches | A showcase facility reported 16 units where its scenario specified 9 | Comparing the live API against the documented scenario | Yes — `reconcile_showcase_batches.py`, surgical and opt-in |
| 28 | `AuthContext` referenced an undefined `STORAGE_KEY`, on the wrong storage area | Expired sessions were never cleared; the user saw the expiry error on every page load until signing out by hand. The `ReferenceError` was swallowed by a bare `catch {}` | Enabling ESLint, which had never run — `npm run lint` was a declared script with no config file | Yes — `clearSession()` |
| 29 | The sign-up form validated 8 characters and no symbol; the user pool requires 12 and a symbol | `Password1` passed every rule the page stated and was then refused by Cognito. The validator carried the comment "mirrors the user pool's policy" | Reading the frontend rule against `template.yaml` | Yes — one shared `passwordPolicy.js`, plus a test that reads the template and fails if the two drift |
| 30 | **Confirming a reservation released its held units** | The pool counter dropped to zero while the reservation still held a unit, so another caller could take it — overselling — and the confirmed hold could then be neither cancelled nor fulfilled | The first live `confirm → cancel` anyone had ever run, against the deployed API. 604 tests were green | Yes — release only on leaving the holding states; 6 regression tests, 4 of which failed before the fix |

Items 8–16 are documentation-toolchain defects. They are logged alongside the
code defects deliberately: a book that silently drops a code listing is as
wrong as a search that silently drops a facility, and three of them were found
only by looking at a rendered page rather than at a passing check.

---

## What is not done

| Item | Status | Why |
|---|---|---|
| Cognito hosted-UI browser redirect | **NOT IMPLEMENTED** | Tokens are real Cognito tokens; the browser PKCE exchange is not built |
| Alarms observed firing | **NOT VERIFIED** | All 8 configured; none has been triggered |
| Point-in-time restore rehearsal | **NOT IMPLEMENTED** | Runbook §8 stays marked UNTESTED |
| Load testing | **NOT IMPLEMENTED** | No measurement against the concurrency ceiling of 10 |
| Map tiles in a browser | **NOT VERIFIED** | Resources exist and are configured |
| Background workers under real volume | **NOT VERIFIED** | Deployed and wired; only the API path exercised end to end |
| SMS notifications | **NOT IMPLEMENTED** | Denied by the account's service control policy |
| Email beyond sandbox | **PARTIAL** | SES sandbox: verified recipients, 200/day |
| Account deletion endpoint | **NOT IMPLEMENTED** | Unresolved policy questions about dependent records |
| Clinical review of the compatibility reference | **NOT IMPLEMENTED** | Requires a qualified professional |
| Dev-only dependency vulnerabilities | **ACCEPTED** | 8 findings in vitest/vite/eslint toolchain; none ships |
| Books regenerated post-deployment | **NOT DONE** | 318 pages predate deployment and say so; corrected by DEPLOYMENT_RECORD.md |
| Privacy notice and terms | **PARTIAL** | Placeholders requiring legal review |
| 4 of 116 edge cases | **NOT HANDLED** | Each named in the edge-case register |
| GitHub publication | **NOT DONE** | Commands prepared; never executed |

## Honesty rules the implementation enforces

1. **Unknown is not zero.**
2. **Updated is not verified.**
3. **An offer is not a reservation.**
4. **Dispatch order is not clinical priority.**
5. **Fail closed.**

Each is enforced in code and asserted by tests, not merely stated in
documentation.
