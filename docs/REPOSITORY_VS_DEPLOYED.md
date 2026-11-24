# Repository versus deployed — what is where

**24 November 2026, 08:33 UTC**

> **The repository and the deployed application are in sync.** Both were
> deployed today and verified against the live system. This document previously
> existed because they had diverged; it is kept because the distinction it
> draws still matters, and because it records how the two are kept honest.

**Live** `https://d324z37do52g8f.cloudfront.net`
**API** `https://uk6itz2a5b.execute-api.ap-southeast-2.amazonaws.com/dev`
**Stack** `lifelink-dev` · `ap-southeast-2` · account `426150327442`
**Repository** `github.com/Harshdeep47/LifeLink`, branch `main`, release commit
[`f9765af`](https://github.com/Harshdeep47/LifeLink/commit/f9765af20c22be144c8926d65c3602f63923e1c9)
(`f9765af20c22be144c8926d65c3602f63923e1c9`)

### Proof of sync, not assertion

| Layer | Deployed | Local | Match |
|---|---|---|---|
| Frontend bundle | `index-AW8_zfLM.js` | `index-AW8_zfLM.js` | ✅ |
| Frontend stylesheet | `index-B1I_r_bR.css` | `index-B1I_r_bR.css` | ✅ |
| Lambda code (all six) | `Em9NdRR2EmRe/VAOdAq+iKsydKmXuiDqnZNKVkVT94g=` | package built from `backend/src` | ✅ |
| Infrastructure | stack `UPDATE_COMPLETE` 08:33:22 | `template.yaml`, unchanged | ✅ |

The frontend hash was read from the **live** `index.html`. The Lambda SHA is
CloudFormation's own digest of the package built from the current source.

---

## How to read this document

Five categories, used consistently across the library:

| Tag | Meaning |
|---|---|
| **LIVE-VERIFIED** | Exercised against the deployed system and observed working |
| **TEST-VERIFIED** | Proven by an automated test that was run, with a count |
| **DEPLOYED** | Running on AWS now |
| **NEEDS-BROWSER** | Not verified by anyone in a real browser |
| **BLOCKED** | Prevented by something outside this repository |

### What "verified" does and does not mean

- **LIVE-VERIFIED** means a request was made against the deployed system and
  the response read. Counter figures quoted below were read **straight from
  DynamoDB** and compared with what the API reported.
- **TEST-VERIFIED** means an assertion ran and passed. For UI that means jsdom:
  real components, real handlers, mocked HTTP. It is strong evidence the wiring
  is right and **no** evidence about layout, CSS or anything a human eye sees.
- **NEEDS-BROWSER** means exactly that. No browser automation was available in
  this environment, so no claim of browser verification is made anywhere.

---

## 1. Deployments performed today

Two backend changesets and one frontend publish, each reviewed before it ran.

| # | What | Identifier | Result |
|---|---|---|---|
| 1 | Frontend | invalidation `I76XJI99TM91I1THIOYYR9BXFN` | 13 files, invalidation **Completed** |
| 2 | Backend | changeset `samcli-deploy1795507818` | `UPDATE_COMPLETE` 08:15:37 |
| 3 | Backend | changeset `samcli-deploy1795508812` | `UPDATE_COMPLETE` 08:33:22 |

Each backend changeset was inspected **before execution** by diffing the
deployed processed template against the changeset's, not by reading the
changeset summary alone. Both times the result was identical:

- 67 resources → 67. No additions, no removals, no replacements.
- 12 DynamoDB tables → 12, **not one differing property**; deletion and
  update-replace policies identical.
- No IAM role or policy differed. API Gateway `Body` identical.
- The only difference was the six Lambdas' `Code.S3Key`.
- No new billable resource. The existing SAM artifact bucket was reused.

Parameters were passed explicitly from the deployed values. This mattered:
`CognitoDomainPrefix`'s template default would have **replaced the Cognito
user pool domain**, and `CorsAllowOrigins`' default would have dropped the
CloudFront origin and broken CORS on the live site.

> **Packaging note.** `sam build` must **not** be used on a Windows host here.
> It installs the local platform's wheels, and `cryptography` — needed for
> RS256 token verification — would be a Windows binary that cannot load on
> arm64 Lambda. Use `python scripts/build_lambda_package.py --verify`, which
> fetches `manylinux2014_aarch64` wheels. Both deployments used it.

## 2. What shipped today

| Feature | State |
|---|---|
| Facility-side reservation queue (`ReservationQueue`) | **DEPLOYED** · TEST-VERIFIED · LIVE-VERIFIED at the API · NEEDS-BROWSER |
| Requester's own holds (`/activity`, `MyActivityPage`) | **DEPLOYED** · TEST-VERIFIED · LIVE-VERIFIED at the API · NEEDS-BROWSER |
| Record provenance display | **DEPLOYED** · TEST-VERIFIED · NEEDS-BROWSER |
| "Emergency request" navigation relabel | **DEPLOYED** · string confirmed in the live bundle |
| Expired-session clearing | **DEPLOYED** · TEST-VERIFIED · NEEDS-BROWSER |
| Sign-up password rules matching the user pool | **DEPLOYED** · LIVE-VERIFIED (§4) |
| Cognito ID-token audience check | **DEPLOYED** · TEST-VERIFIED · partly LIVE-VERIFIED (§4) |
| **Reservation counter fix** | **DEPLOYED** · TEST-VERIFIED · **LIVE-VERIFIED** (§3) |

## 3. The reservation counter defect

Found during this session's live verification, after the first backend
deployment. Full post-mortem:
[RESERVATION_COUNTER_DEFECT](RESERVATION_COUNTER_DEFECT.md).

In one line: `releases = reservation.status in HOLDING_STATES` asked whether a
hold *was* holding units rather than whether it *stops* holding them, so
confirming a reservation released its units — permitting **overselling**, and
leaving the confirmed hold impossible to cancel or fulfil.

Fixed, 6 regression tests added (4 failed before the fix), deployed as
changeset 3, then verified live — 37 checks, counters read from DynamoDB:

| Path | heldUnits | unreserved |
|---|---|---|
| baseline | 0 | 12 |
| `PENDING` (hold 2) | 2 | 10 |
| `CONFIRMED` | **2** | 10 |
| `FULFILLED` | 0 | 12 |
| `CONFIRMED → CANCELLED` | 2 → 0 | 10 → 12 |
| `PENDING → CANCELLED` | 2 → 0 | 12 |

`heldUnits` equalled the API's `reservedUnits` at all ten checkpoints.
Overselling re-tested live: a donor held all 3 units of `A+/PRBC`, a different
requester was refused `NO_UNRESERVED_STOCK`, and succeeded once released.

**One stale row remains** — `01M86AA2WV2KDXR0B0ZKR80F18`, stored `CONFIRMED`,
effective `EXPIRED`, holding nothing. Left alone rather than hand-edited; see
§8 of the post-mortem.

## 4. Authentication, verified live

Real tokens obtained from the deployed user pool via
`ADMIN_USER_PASSWORD_AUTH`. **19 checks, all passing.**

The token shapes confirm why the audience fix was needed:

| Token | `client_id` | `aud` |
|---|---|---|
| Access | present | **absent** — so `verify_aud` cannot be used |
| ID | **absent** — the claim the old check skipped | present |

- real access token → `/me` 200; real ID token → `/me` 200
- no token, garbage token, rewritten-`aud` token, self-signed token for another client → all 401
- donor on `/admin/audit` → 403; donor on another facility's queue → 403
- blood bank admin on **its own** facility queue → 200
- suspended account with a valid token → **403 `ACCOUNT_SUSPENDED`**

> **Honest limitation.** The specific case the fix addresses — a *validly
> pool-signed* ID token for a **different** app client — could not be produced
> live, because the pool has exactly **one** app client. That is also precisely
> why the flaw was never exploitable. The two negative tests above are refused
> at the *signature* step, so they do not isolate the audience check. The
> isolated proof is `test_an_id_token_for_another_client_is_refused`, verified
> by reverting the fix and watching three tests fail.

**Password policy, verified live.** Cognito refused `Password1` with
`InvalidPasswordException: Password not long enough` — the password the
*previous* frontend told users was acceptable. The deployed form now states and
enforces the real policy: 12 characters with upper, lower, digit and symbol.

## 5. What is verified, and how

| Gate | Result |
|---|---|
| Backend tests | **610** (536 unit, 74 integration) |
| Frontend tests | **294** (12 files) |
| **Total** | **904** |
| `ruff check` | clean |
| `npm run lint` | clean, 0 errors |
| `npm run build` | clean |
| `cfn-lint` | clean |
| `sam validate --lint` | clean (SAM CLI 1.174.0) |
| Dependency audit | passed; 8 development-only findings |
| Live API checks | **19 auth + 37 workflow = 56**, all passing |

### Live workflow coverage

LIVE-VERIFIED: login (3 roles), `/me`, My Activity (`/me/reservations`,
`/emergency-requests`), facility batches, availability, reservation create,
provider confirm, provider fulfil, requester cancel from both `PENDING` and
`CONFIRMED`, oversell refusal, camp search (6 camps, `effectiveRadiusKm` 20),
donor refused the emergency provider queue, donor refused priority
certification, suspended-account refusal.

## 6. Still NEEDS-BROWSER

No browser automation was available, so **nothing below has been seen working
by anyone**. Everything here is deployed and covered by component tests.

Hard-refresh first (**Ctrl-F5**) — asset hashes changed.

| # | Check | Expect |
|---|---|---|
| 1 | `/dashboard/blood-bank` as blood bank staff | "Reservation requests" above the batch forms |
| 2 | Accept / Decline / Record units issued | Decline demands a reason before it will send |
| 3 | A lapsed request | *Decline* shown, *Accept* not |
| 4 | `/activity` as a donor | Holds listed with a coarse countdown ("1 h 58 m left") |
| 5 | **Cancel hold** | Leaves the live list; units return to search results |
| 6 | Navigation | "Emergency request", not "Request blood" |
| 7 | A facility page | **Two** provenance pills — identity *and* stock |
| 8 | Sign-up with an 11-character password | Refused **before** submission, naming the real rule |
| 9 | Let a token expire, reload | Session clears; no repeated expiry error |
| 10 | Phone width | Queue and activity rows stack; no horizontal scroll |
| 11 | Both maps | Clustering, named pins, card↔marker selection, Directions |
| 12 | Console | No worker warning, no uncaught MapLibre errors |

## 7. Dated reports versus living documents

A convention worth stating, because it explains why some documents contain
numbers that are no longer current.

**Living documents** describe the system as it is and are kept accurate:
[README](../README.md), [ARCHITECTURE](ARCHITECTURE.md),
[ARCHITECTURE_DECISIONS](ARCHITECTURE_DECISIONS.md),
[DATABASE_DESIGN](DATABASE_DESIGN.md),
[API_DOCUMENTATION](API_DOCUMENTATION.md), [SECURITY](SECURITY.md),
[TESTING](TESTING.md), [DEPLOYMENT](DEPLOYMENT.md),
[KNOWN_LIMITATIONS](KNOWN_LIMITATIONS.md),
[ENVIRONMENT_VARIABLES](ENVIRONMENT_VARIABLES.md),
[CLOUD_DEMONSTRATION_GUIDE](CLOUD_DEMONSTRATION_GUIDE.md),
[REAL_FACILITY_DATA](REAL_FACILITY_DATA.md) and this document.

**Dated reports** record what was true on a given day and are **deliberately
not rewritten** — falsifying them would destroy the record of how the project
actually went, which is the most useful thing about them:
[DEPLOYMENT_RECORD](DEPLOYMENT_RECORD.md),
[RESERVATION_COUNTER_DEFECT](RESERVATION_COUNTER_DEFECT.md),
[FINAL_POLISH_REPORT](FINAL_POLISH_REPORT.md),
[MAP_DISCOVERY_UX_REPORT](MAP_DISCOVERY_UX_REPORT.md),
[MAP_STABILISATION_REPORT](MAP_STABILISATION_REPORT.md),
[FINAL_PRODUCT_SPRINT_REPORT](FINAL_PRODUCT_SPRINT_REPORT.md),
[FINAL_DEMO_READINESS_REPORT](FINAL_DEMO_READINESS_REPORT.md),
[SPRINT3_FUNCTIONALITY_REPORT](SPRINT3_FUNCTIONALITY_REPORT.md),
[RECOVERY_SPRINT_REPORT](RECOVERY_SPRINT_REPORT.md),
[FINAL_HANDOVER](FINAL_HANDOVER.md), [PROGRESS](PROGRESS.md),
[PHASE_0_INVENTORY](PHASE_0_INVENTORY.md).

A test count in a sprint report is a historical measurement. A test count in
`README` or `TESTING` is a claim about now, and if it disagrees with `pytest`,
it is a defect.

## 8. Keeping this true

After any deployment, update this document and the status table in
[README](../README.md). The checks that establish sync are cheap:

```bash
# frontend: does the live page reference the local build?
curl -s https://d324z37do52g8f.cloudfront.net/ | grep -oE 'assets/index-[^"]+\.js'
ls frontend/dist/assets/ | grep -E '^index-.*\.js$'

# backend: do all six functions share one SHA, and is it today's package?
aws lambda list-functions --profile lifelink --region ap-southeast-2 \
  --query 'Functions[?starts_with(FunctionName,`lifelink`)].[FunctionName,CodeSha256]' --output text
```
