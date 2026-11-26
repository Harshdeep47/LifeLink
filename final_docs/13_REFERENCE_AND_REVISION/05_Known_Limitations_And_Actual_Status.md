# Known Limitations and Actual Status

**The honest status of LifeLink, as of 24 November 2026, commit `668a771`.**

This is the most-referenced document in the library. Learn it. Volunteering
these limitations is worth more than a confident answer that collapses under
one follow-up question.

---

## 1. The status layers — keep these distinct

| Layer | Status |
|---|---|
| In the repository | `668a771` on `main`, clean tree, pushed |
| Deployed to AWS | **66 resources**, stack `UPDATE_COMPLETE` 2026-11-24 08:33 UTC |
| Repository vs deployed | **in sync** — six Lambdas share `CodeSha256 Em9NdRR2EmRe/VAOdAq+iKsydKmXuiDqnZNKVkVT94g=`; live bundle `index-AW8_zfLM.js` |
| Verified by automated tests | **951 passing** (657 backend, 294 frontend) |
| Verified live against AWS | **56 checks** — 19 authentication, 37 workflow |
| **Verified in a browser by a person** | **NOT DONE — 12 checks outstanding** |

---

## 2. The twelve pending browser checks

**No browser automation exists in this project.** These require a human with a
real browser and cannot be scripted here.

| # | Check |
|---|---|
| 1 | **Sign-in end to end** — the Cognito redirect, PKCE exchange and session storage. **The most important one; everything else depends on it** |
| 2 | Sign-up with the 12-character policy, and the error shown on a weak password |
| 3 | Sign-out, and that the session is cleared |
| 4 | Session expiry behaviour after one hour |
| 5 | **Browser geolocation permission prompt** — grant path |
| 6 | Geolocation **denial** path, falling back to place search |
| 7 | Map rendering with WebGL, markers and clustering |
| 8 | Requesting a reservation through the UI |
| 9 | The facility-side reservation queue: accept, reject, fulfil |
| 10 | Raising an emergency request and watching the tracking timeline |
| 11 | Camp registration and cancellation |
| 12 | Role dashboards rendering correctly for each of the six roles |

**What to say:**
> "The API and the AWS resources were verified by script — fifty-six live
> checks. The browser workflows have not been independently watched by a person;
> there's no browser automation in this project and twelve manual checks are
> outstanding, with sign-in the one that matters most. I'd rather tell you that
> than claim coverage I don't have."

---

## 3. Operational limitations

### 3.1 Demo data ages out — re-seed before any demonstration

| Threshold | Effect after |
|---|---|
| 48 hours | every facility shows **`Outdated`** |
| 72 hours | every facility shows **"Verification expired"** |

**This is correct behaviour, not a bug** — the system is telling the truth about
data nobody has updated.

```bash
python scripts/seed_cloud.py --apply
```

> "A system that quietly showed two-day-old blood stock as current would be the
> actual bug."

### 3.2 §1.20 — genuine emergency event accumulation

Re-seeding revives demo requests into dispatchable states, so the **live
dispatcher** (every minute) appends **genuine** events with real current
timestamps while the seeded creation event refreshes. A timeline can read
**"created 24 Nov, expired 16 Nov"**.

**Why it must not be "fixed":**

- Those events are **real application history**. Deleting them would mean
  deleting genuine records.
- Sorting by `occurredAt` instead of sort key would be **worse** — you would see
  a request created *after* its own expiry.

A real fix is a **dataset design** change (seeding requests in terminal states),
which would cost the dispatch and expiry scenarios the demo needs.

### 3.3 §1.15 — one stale `CONFIRMED` reservation

| | |
|---|---|
| Status says | `CONFIRMED` |
| Hold window | **passed** — effective status is `EXPIRED` |
| Units held | **none.** All 5 pool counters read 0 |
| Why not fixed | settling it means hand-editing production data, which re-seeding cannot reproduce |
| How the UI handles it | `isStaleHold()` compares the clock to the status and shows it as expired |

**The design point:** the UI computes effective status rather than trusting the
stored status, which is why this is cosmetic and why a ten-minute maintenance
sweep is safe.

---

## 4. Not implemented

| # | Thing | Why |
|---|---|---|
| 1 | **Email delivery** | `SES_SENDER` is **empty**. The notification worker Lambda has **no CloudWatch log group**, which proves it has **never been invoked** |
| 2 | **SMS** | ADR-0015, **and** blocked by the account's SCP |
| 3 | **Amazon Location browser tiles** | `AWS::Location::APIKey` **denied by the account's SCP** (ADR-0019). The basemap is OpenStreetMap |
| 4 | **Real Punjab facility data** | public sources were unreachable; the dataset is synthetic but structurally validated (34 tests) |
| 5 | External provider inventory ingestion | the route, permission, secret and adapter seam exist; **no provider connected**, and the secret has never been accessed |
| 6 | Custom business metrics | only AWS's automatic metrics exist |
| 7 | WAF | HTTP APIs don't support it directly; it would attach at CloudFront |

**In-app notifications do work** — 18 rows, served by `GET /me/notifications`.

---

## 5. Gaps found while writing this documentation

**These four were discovered during the documentation pass and recorded rather
than fixed, because the project is under an engineering freeze. Presenting them
yourself is stronger than being shown them.**

### 5.1 The alarm SNS topic has ZERO subscriptions

All **8** CloudWatch alarms publish to `lifelink-dev-alarms`, and **nothing
reaches a person**. The alarms genuinely evaluate and keep a visible state
history; only delivery is missing.

**Why:** a subscription needs an endpoint — an email address — which is personal
data that should not be committed to a template. It became a manual step and was
never done. **One-minute fix.**

> "An alarm nobody's subscribed to is monitoring theatre."

### 5.2 Four of six Lambda log groups never expire

| Retention 30 days | Never expire |
|---|---|
| `/aws/apigateway/lifelink-dev`, `/aws/lambda/lifelink-dev-api` | dispatcher (**8.2 MB**), maintenance, outbox-publisher, work-worker |

The template sets `LogRetentionDays: 30` and declares **two** log groups. The
other four were **auto-created by Lambda** on first invocation and inherited
the default of never expiring.

**This is an infrastructure-as-code *coverage gap*, not drift** — those
resources were never in the stack at all. The dispatcher runs every minute, so
that log group grows without bound.

### 5.3 `docs/openapi.json` overstates authentication

It declares `bearerAuth` on **all 58** operations, including `/health`, which
returns **200 without a token** (verified live). The **route table in
`backend/src/handlers/api.py` is authoritative**, and it marks **9** routes
anonymous-allowed. **This one is still open.**

> **Resolved 26 November 2026:** the `servers` block previously described the
> AWS deployment as "not currently deployed". `scripts/generate_openapi.py`
> was corrected and both files regenerated. The `bearerAuth` over-declaration
> remains.

### 5.4 `docs/AWS_COST_ESTIMATE.md` was stale in two ways — **resolved**

| It said | Verified reality |
|---|---|
| "Nothing has been deployed" | **66 resources are deployed** |
| A **customer-managed** KMS key at $1.00/month, total $1.40 fixed | **No customer-managed keys exist.** All 3 KMS keys are `KeyManager: AWS`. The only non-free item is one Secrets Manager secret at **$0.40/month gross**. Measured: **$0.1628 gross** for 1-25 Nov 2026, **$0.00 net** after credits |

> **Resolved 26 November 2026.** A dated current-status section was added to
> the top of that file, with the original estimate retained below it as clearly
> labelled historical information. The same correction was applied across
> `DEPLOYMENT.md`, `RELEASE_NOTES.md`, `EDGE_CASE_REGISTER.md`,
> `PRIVACY_AND_DATA_HANDLING.md`, `TROUBLESHOOTING.md`, `FINAL_HANDOVER.md`,
> the two demo guides, and the three PDF books (11 source references corrected
> and all three rebuilt).

---

## 6. Accepted security trade-offs

| Trade-off | Position |
|---|---|
| **Token in `localStorage`** | XSS-exposed. An httpOnly cookie is more secure but needs a backend session endpoint and brings CSRF into scope. **A fair criticism, not optimal** |
| **MFA is OPTIONAL** | should be **required** for institutional roles in production |
| **`ADMIN_USER_PASSWORD_AUTH` enabled** | non-production test scripting; disable in a production pool |
| **Deletion protection off on all 12 tables** | blocks a stack teardown; should be **on** in production |
| No WAF, CloudFront access logging off | demo trade-offs |
| `MinimumProtocolVersion: TLSv1` | a consequence of the default CloudFront certificate |
| Secret rotation not enabled | the secret has never been accessed |
| API Lambda role is the union of all 58 routes' needs | splitting by feature would narrow it, at the cost of cold starts against a limit of 10 |

---

## 7. `NEEDS-VERIFICATION` — do not claim these

| Item | Why |
|---|---|
| **Stack drift** | `StackDriftStatus: NOT_CHECKED` — never run |
| **The identity-pool map-tile path** | only the **API key** path was attempted and refused. **Do not claim the identity-pool path is blocked** |
| **DLQ recovery** | both DLQs are empty and no message has ever reached one; the procedure is documented, **not practised** |
| **The cross-client token attack** | cannot be demonstrated — the pool has **exactly one app client**, so no such token can be produced. That is also why it was never exploitable. Proven by unit test: reverting fails 3 of 23 |
| `BlockedEncryptionTypes: [SSE-C]` on both buckets | **not in the template**; appears to be an AWS default. Do not claim it as a deliberate choice |

---

## 8. Non-blocking code quality

| Item | Status |
|---|---|
| **15 ESLint `exhaustive-deps` warnings** across five working files | `npm run lint` **exits 0**. `exhaustive-deps` is `warn`, not `error`, deliberately. Fixing them means `useMemo` surgery with no behavioural benefit |
| No TypeScript | would have caught one of the four real defects (an undefined variable). A fair criticism |

---

## 9. The four defects found live — the project's strongest evidence

| # | Defect | Found by | Proof of fix |
|---|---|---|---|
| 1 | **Expired sessions never cleared** — an undefined variable inside an empty `catch` swallowed a `ReferenceError` | enabling ESLint for the first time | `no-empty` with `allowEmptyCatch: false` now an **error** |
| 2 | **Password policy mismatch** — UI said 8 chars and no symbol; the pool required 12 with a symbol | a **live Cognito refusal** | a test that reads `template.yaml`; 49 tests |
| 3 | **Token audience checked for only one token type** | code review | reverting fails **3 of 23** tests |
| 4 | **Confirming a reservation released its own hold** — permitting **overselling** | the **first live run** of `confirm -> cancel` | 6 regression tests, **4 fail** against the old code; all three paths re-verified live with counters read **directly from DynamoDB** |

**Two of these four were invisible to over 900 passing tests.**

> "The thing I'd most want to be judged on isn't that the tests pass — it's that
> we found four real defects after deployment and two were invisible to over
> nine hundred passing tests. What I took from that is that a green suite tells
> you about the cases you thought of."

---

## 10. What is genuinely verified

| Verified live against AWS | Result |
|---|---|
| Live site | **200** |
| `/health` | **200**, `demoEnvironment: true` |
| Six Lambdas | all `Active`, one shared SHA |
| Public endpoints, no token | **200** |
| `/me`, `/admin/audit`, reservation POST without a token | **401** |
| Real access token / real ID token on `/me` | **200 / 200** |
| Garbage, rewritten-`aud`, self-signed-other-client tokens | **401** |
| Donor on `/admin/audit` | **403** |
| Donor on another facility's reservation queue | **403** |
| Blood bank admin on **their own** queue | **200** |
| Suspended account with a valid token | **403 `ACCOUNT_SUSPENDED`** |
| Donor on provider queue / certify | **403 / 403** |
| Cognito refuses `Password1` | `InvalidPasswordException` |
| All three reservation transition paths | counters correct at **10 checkpoints** |
| Second requester against a fully-held pool | **`NO_UNRESERVED_STOCK`** |
| Facility filters | `verifiedOnly` 11, `FRESH` 9 of 16 |
| Camp search near Patiala | 6 camps, `effectiveRadiusKm` 20 |
| Amazon Location place index | real Esri data for "Patiala" |
| Live row counts | 742 across 12 tables |

| Verified by tooling | Result |
|---|---|
| `pytest backend/tests` | **657 passed**, exit 0 |
| `vitest --run` | **294 passed**, 12 files |
| `ruff check .` | clean |
| `npm run lint` | exit 0 (15 warnings) |
| `npm run build` | succeeds |
| `cfn-lint` / `sam validate` | clean |
| `scripts/security_audit.py` | passes |
| `scripts/validate_facility_dataset.py` | passes |
| `generate_openapi.py --check` | "matches the route table" |

---

## 11. The one-breath version

> "Twelve browser checks outstanding, and sign-in is the one that matters.
> Demo data ages out after 48 hours, so re-seed before a demo. Email and SMS
> don't send — the notification worker has never been invoked and I can prove it
> from the missing log group. The map basemap is OpenStreetMap because Location
> API keys are SCP-denied. Our eight alarms publish to a topic with no
> subscribers, so detection works and nobody is told. Four of six Lambda log
> groups never expire. And one stale reservation row holds nothing. The last
> three I found while writing the documentation rather than while building."

---

## Cross-references

- [../10_LAB_EVALUATION/05_Last_Minute_Revision.md](../10_LAB_EVALUATION/05_Last_Minute_Revision.md) — the 30-minute revision sheet
- [../10_LAB_EVALUATION/02_Teacher_Question_And_Answer_Bank.md](../10_LAB_EVALUATION/02_Teacher_Question_And_Answer_Bank.md) §G — the honesty questions
- [../AI_TEACHING_CONTEXT.md](../AI_TEACHING_CONTEXT.md) §20 — the same list for an AI assistant
- [../09_PRACTICAL_AWS_DEMONSTRATIONS/CONFIGURATION_WALKTHROUGHS.md](../09_PRACTICAL_AWS_DEMONSTRATIONS/CONFIGURATION_WALKTHROUGHS.md) §K — the full configuration inventory
- Originals: `docs/KNOWN_LIMITATIONS.md`, `docs/REPOSITORY_VS_DEPLOYED.md`, `docs/RESERVATION_COUNTER_DEFECT.md`
