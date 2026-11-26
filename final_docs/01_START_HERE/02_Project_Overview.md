# Project Overview

Scope, scale and current status. The document to read if someone asks "what
state is this project in?"

---

## 1. One-paragraph summary

LifeLink is a serverless blood-availability platform for Punjab, India, built
on AWS. It lets blood banks publish stock batch by batch, hospitals discover
and temporarily reserve units nearby, donors find and register for donation
camps, and hospitals raise urgent requests that are dispatched to ranked
candidate providers. It is deployed, verified by 951 automated tests and 56
live checks, costs **$0.00 net** a month (gross usage ~$0.45-0.50, fully offset
by FREE-plan credits), and runs entirely on **synthetic data**
by design.

---

## 2. Current status — the five categories

**Keep these distinct. A teacher will probe exactly where one ends and the next
begins.**

| Category | Status |
|---|---|
| **In the repository** | commit `668a771` on `main`, clean tree, pushed to GitHub |
| **Deployed to AWS** | 66 resources, stack `UPDATE_COMPLETE` 2026-11-24 08:33 UTC |
| **Repository vs deployed** | **in sync** — all six Lambdas share `CodeSha256 Em9NdRR2EmRe/VAOdAq+iKsydKmXuiDqnZNKVkVT94g=`; the live bundle is `index-AW8_zfLM.js`, matching the build |
| **Verified by automated tests** | **951 passing** (657 backend, 294 frontend) |
| **Verified live against AWS** | **56 checks** — 19 authentication, 37 workflow |
| **Verified in a browser by a person** | **NOT DONE — 12 checks outstanding** |

---

## 3. Scale

| Dimension | Count |
|---|---|
| AWS resources deployed | 66 |
| DynamoDB tables | 12 |
| Global secondary indexes | 24 |
| Lambda functions | 6 |
| API endpoints | 58 (9 anonymous-allowed) |
| Permissions | 39 |
| Roles | 10 |
| Architecture decision records | 19 |
| Backend source modules | ~45 |
| Frontend components and pages | ~50 |
| Automated tests | **951** |
| Engineering documents in `docs/` | 37 |
| Rows of demonstration data | 742 |

### Data

| Entity | Count |
|---|---|
| Organizations | 62 |
| Facilities | 16 |
| Inventory batches | **487** |
| Camps | 46 |
| Emergency requests | 11 |
| Provider responses | 13 |
| Request events | 35 |
| Reservations | 9 (+ 5 pools, all counters 0) |
| Donations | 14 |
| Notifications | 18 |
| Alerts | 4 |
| Audit records | 22 |

---

## 4. What works, verified

### Verified live against the deployed system

| Area | Result |
|---|---|
| Live site | HTTP **200** |
| `GET /health` | **200**, `demoEnvironment: true` |
| Six Lambdas | all `Active` / `Successful`, one shared SHA |
| Public endpoints without a token | **200** |
| `/me` and `/admin/audit` without a token | **401** |
| Real access token / real ID token on `/me` | **200 / 200** |
| Garbage, rewritten-`aud`, self-signed-other-client tokens | **401** |
| Donor on `/admin/audit` | **403** |
| Donor on another facility's reservation queue | **403** |
| Blood bank admin on **their own** facility's queue | **200** |
| Suspended account with a valid token | **403 `ACCOUNT_SUSPENDED`** |
| Cognito refuses `Password1` | `InvalidPasswordException` |
| All three reservation transition paths | counters correct at **10 checkpoints** |
| Second requester against a fully-held pool | refused `NO_UNRESERVED_STOCK` |
| Camp search near Patiala | 6 camps, `effectiveRadiusKm` 20 |
| Donor on emergency provider queue / certify | **403 / 403** |
| Facility search filters | `verifiedOnly` 11, `FRESH` 9 |

### Verified by test and tooling

| Check | Result |
|---|---|
| `pytest backend/tests` | **657 passed**, exit 0 |
| `vitest --run` | **294 passed**, 12 files |
| `ruff check .` | clean |
| `npm run lint` | exit 0 (15 non-blocking warnings) |
| `npm run build` | succeeds |
| `cfn-lint` / `sam validate` | clean |
| `scripts/security_audit.py` | passes |
| `scripts/validate_facility_dataset.py` | passes |
| `generate_openapi.py --check` | "OpenAPI document matches the route table" |
| 37 docs — links / anchors / stale counts | **0 / 0 / 0** |

---

## 5. What does not work, honestly

| # | Limitation | Why |
|---|---|---|
| 1 | **12 browser checks never performed by a person** | no browser automation exists in this project |
| 2 | **Demo data ages out** at 48 h / 72 h | correct behaviour; re-seed before a demo |
| 3 | **Email not sending** | `SES_SENDER` empty; the notification worker has **never been invoked** |
| 4 | **SMS not implemented** | ADR-0015, and blocked by the account's SCP |
| 5 | **Amazon Location browser tiles unavailable** | `AWS::Location::APIKey` denied by the SCP (ADR-0019) |
| 6 | **Alarms notify nobody** | SNS topic has 0 subscriptions |
| 7 | **4 of 6 Lambda log groups never expire** | IaC coverage gap |
| 8 | **Genuine event accumulation** (§1.20) | re-seeding revives requests; the dispatcher writes real events |
| 9 | **One stale `CONFIRMED` reservation** (§1.15) | holds nothing; fixing means hand-editing production |
| 10 | **Real facility data incomplete** | public sources unreachable |
| 11 | **15 ESLint `exhaustive-deps` warnings** | `npm run lint` exits 0 |
| 12 | **`docs/openapi.json` overstates auth** on all 58 operations | generated-document defect |

Items 6, 7 and 12 were found **while writing this documentation library**, and
are recorded rather than fixed because the project is under an engineering
freeze.

---

## 6. The four defects found live, and why they matter

**This is the most credible material the project has**, because it is evidence
of real verification rather than assertion.

| # | Defect | Found by | Proof of fix |
|---|---|---|---|
| 1 | **Expired sessions never cleared** — an undefined variable inside an empty `catch` swallowed a `ReferenceError` | enabling ESLint for the first time | `no-empty` with `allowEmptyCatch: false` now an error |
| 2 | **Password policy mismatch** — the UI said 8 characters and no symbol; the pool required 12 with a symbol | live Cognito refusal | a test that reads `template.yaml`; 49 tests |
| 3 | **Token audience checked for only one token type** | code review | reverting fails 3 of 23 tests |
| 4 | **Confirming a reservation released its own hold** — permitting overselling | the **first live run** of `confirm -> cancel` | 6 regression tests, 4 fail against the old code; all three paths re-verified live |

**Two of these four were invisible to a suite of over 900 passing tests.**

**Say this:**
> "The thing I'd want to be judged on isn't that the tests pass — it's that we
> found four real defects after deployment, and two of them were invisible to
> over nine hundred passing tests. The worst was in the reservation logic:
> confirming a reservation released its own hold, which allows overselling
> blood. We only found it by exercising the deployed system. That taught me that
> a green suite tells you about the cases you thought of."

---

## 7. Cost and account

| | |
|---|---|
| Account | `426150327442` |
| Region | `ap-southeast-2` (Sydney) — **single Region, account-enforced** |
| Plan | FREE, `ACTIVE`, credits remaining, expires 2027-05-15 |
| Monthly cost | **$0.00 net** — gross ~$0.45-0.50, offset by credits. The only non-free item is one Secrets Manager secret (**never accessed**); everything else is inside the free tier |
| KMS keys | 3, **all AWS-managed** — no customer-managed keys |

---

## 8. Technology, in one table

| Layer | Technology |
|---|---|
| Frontend | React 18, Vite 6, React Router, MapLibre GL |
| Frontend tests | Vitest + Testing Library — 294 |
| Backend | Python 3.14, no web framework |
| Backend tests | pytest + moto — 657 |
| Database | DynamoDB |
| Auth | Cognito user pool, Authorization Code + PKCE |
| Infrastructure | AWS SAM / CloudFormation, one 1490-line template |
| Hosting | S3 + CloudFront |
| API | API Gateway **HTTP API** |
| Compute | Lambda `python3.14` on `arm64` |
| Background | EventBridge Scheduler, DynamoDB Streams, SQS |
| Observability | CloudWatch Logs, 8 alarms, X-Ray |

---

## 9. Timeline

| Date | Event |
|---|---|
| 2026-11-15 | Stack created; first deployment |
| 2026-11-15 | v1.0 release commit `f9765af` |
| 2026-11-24 | Frontend redeployed; two backend changesets applied |
| 2026-11-24 | Reservation counter defect found live and fixed |
| 2026-11-24 | Seeded-event duplication fixed; 50 duplicates removed |
| 2026-11-24 | Final commit `668a771`; engineering freeze |
| 2026-11-24 | This documentation library created |

---

## 10. Spoken answer

### "What's the status of your project?" — 30–45 seconds
> "It's deployed and working. Sixty-six AWS resources in ap-southeast-2, and
> the repository and the deployment are in sync — all six Lambda functions share
> the same code hash. Nine hundred and fifty-one automated tests pass, and we
> ran fifty-six checks against the live system covering authentication,
> authorisation and the reservation workflows.
>
> The honest gap is browser testing. There's no browser automation in this
> project, so while the API and the AWS resources are verified by script, the
> browser workflows haven't been independently watched by a person — there are
> twelve manual checks still outstanding. And the demo data ages out after
> forty-eight hours, so it needs re-seeding before a demonstration."

---

## 11. Cross-references

- [01_LifeLink_From_Zero.md](01_LifeLink_From_Zero.md)
- [03_Project_Features_And_User_Roles.md](03_Project_Features_And_User_Roles.md)
- [04_Technology_Stack_Explained.md](04_Technology_Stack_Explained.md)
- [../13_REFERENCE_AND_REVISION/05_Known_Limitations_And_Actual_Status.md](../13_REFERENCE_AND_REVISION/05_Known_Limitations_And_Actual_Status.md)
- Original: `docs/REPOSITORY_VS_DEPLOYED.md`, `docs/PROJECT_OVERVIEW.md`
