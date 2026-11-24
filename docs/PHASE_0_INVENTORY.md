# LifeLink — Phase 0: Workspace and Account Discovery

**Status:** COMPLETE
**Date:** 2026-11-15
**Scope:** PART 17, Phase 0 of `MASTER_BUILD_PROMPT.md` — inspect workspace, tools, project state, Git, AWS profile, identity, region, service availability and quotas. No deployment. Produce a project inventory and risk list.

> **No AWS resources were created, modified or deleted during Phase 0.** Every AWS call was a read-only `List*` / `Get*` / `Describe*` operation. No GitHub operation of any kind was performed.

---

## 1. Workspace inventory

Working directory: `d:\LifeLink`

| Path | Type | Size | Notes |
|---|---|---|---|
| `.git/` | directory | — | Existing local repository, preserved |
| `.gitignore` | file | 259 B | Committed in `6d2a5fc`. Reasonable baseline |
| `CLAUDE.md` | file | 7.1 KB | AWS Agent Toolkit rules. **Untracked** |
| `MASTER_BUILD_PROMPT.md` | file | 67.5 KB, 2244 lines | The authoritative specification. **Untracked** |
| `docs/` | directory | — | Created in Phase 0 for this report |

**Verdict: effectively greenfield.** No source code, no `package.json`, no Python package, no infrastructure templates, no tests, no CI configuration. There is no prior work to preserve beyond the three files above, so spec §1.3 ("preserve useful existing work") imposes no constraint other than leaving `.gitignore` and the two Markdown files intact.

### 1.1 Existing `.gitignore` assessment

Covers `.env`/`.env.*` (with a correct `!.env.example` negation), `.aws/`, `credentials`, `*.pem`, `*.key`, `node_modules/`, `venv/`, `.venv/`, `__pycache__/`, `dist/`, `build/`, `.vscode/`, `.idea/`, `*.log`.

Adequate for now. Phase 2 should extend it with: `.aws-sam/`, `samconfig.toml` (if it ends up holding account IDs), `.pytest_cache/`, `.coverage`, `htmlcov/`, `*.egg-info/`, `.ruff_cache/`, `coverage/`, `playwright-report/`, `.DS_Store`, and generated PDF build intermediates.

---

## 2. Git state

| Property | Value |
|---|---|
| Branch | `main`, tracking `origin/main` |
| Commits | 1 — `6d2a5fc` "Initial commit: Add Git ignore configuration" |
| Branches | `main`, `remotes/origin/main` |
| **Remote `origin`** | **`https://github.com/Harshdeep47/LifeLink.git` (fetch + push)** |
| Stashes | none |
| Untracked | `CLAUDE.md`, `MASTER_BUILD_PROMPT.md`, `docs/` |
| History rewrites | none performed |

> ### ⚠️ A GitHub remote already exists
>
> Spec PART 18 says "do not create or modify a GitHub remote" and "do not push". The remote was **already configured before this task began** — it was not added here and has not been modified. It is being left exactly as found.
>
> The operational consequence: `main` tracks `origin/main`, so a bare `git push` would publish. **No push will be performed.** PART 18 and PART 19 are satisfied by leaving the remote untouched and handing over the publish commands at Phase 12 for the user to run themselves.

---

## 3. Toolchain inventory

### 3.1 Present

| Tool | Version | Path | Fit for purpose |
|---|---|---|---|
| Python | **3.14.2** | `C:\Users\Asus\AppData\Local\Python\bin\python.exe` | ✅ Matches the `python3.14` Lambda runtime exactly |
| pip | 25.3 | `python -m pip` (not on `PATH` as `pip`) | ✅ Use `python -m pip` |
| AWS CLI | 2.40.3 | `C:\Program Files\Amazon\AWSCLIV2\aws.exe` | ✅ |
| Git | 2.54.0.windows.1 | `C:\Program Files\Git\cmd\git.exe` | ✅ |
| Java | 26.0.2 | on `PATH` | ✅ Enables DynamoDB Local without Docker |
| winget | present | — | ✅ Available for installing missing tooling |
| Jinja2 | 3.1.6 | site-packages | ✅ Useful for book generation templating |

### 3.2 Missing

| Tool | Needed for | Severity |
|---|---|---|
| **Node.js / npm** | React + Vite frontend (Feature 5), all frontend tests | **BLOCKER** |
| **AWS SAM CLI** | IaC authoring/validation (Feature 7), `sam validate`, `sam local` | **HIGH** |
| **Docker** | `sam local`, containerised DynamoDB Local | MEDIUM — workaround exists |
| **reportlab** | PDF book generation (spec §15.5 names it) | **HIGH** |
| **boto3** | Backend AWS SDK + local adapters | HIGH |
| **pytest** | All backend testing (PART 13) | HIGH |
| **moto** | AWS service mocking in tests | MEDIUM |
| `markdown` / `pypdf` | Markdown→PDF pipeline, PDF validation (§15.6) | HIGH |
| **make** | Spec suggests `make seed-demo` etc. | LOW — §11.3 permits adapting commands |
| pandoc / LaTeX | Alternative PDF path | LOW — not needed if reportlab is used |

Python packages are installable into a project virtualenv with no system-wide change. Node.js, SAM CLI and Docker are system-level installations and need the user's go-ahead.

---

## 4. AWS environment

### 4.1 Identity and region — verified, not assumed

Spec §2.6 requires discovering the live configuration rather than trusting the last known values. Both last-known values were checked and both still hold:

| Property | Spec's last-known value | Discovered value | Match |
|---|---|---|---|
| Profile | `lifelink` | `lifelink` (only profile; no `[default]`) | ✅ |
| Region | `ap-southeast-2` | `ap-southeast-2` | ✅ |

| Property | Value |
|---|---|
| Account | `426150327442` |
| ARN | `arn:aws:sts::426150327442:assumed-role/AccountFullAccessRole/<session>` |
| Credential source | `aws login` social sign-in session (not static IAM keys) |
| Sign-in region | `ap-southeast-2` |
| Live region confirmation | EC2 AZs returned `ap-southeast-2a/2b/2c` |
| Account plan | **FREE**, ACTIVE, 120 USD credits, expiring 2027-05-15 |
| Managed governance | Organizations SCP `p-2cb1m8xd` under `o-p4nwj6qbrw` |

The region has **not** been changed and will not be. No resource will be created outside `ap-southeast-2`, except that CloudFront is global and is administered via `us-east-1` — which the project's own AWS rules explicitly permit.

### 4.2 Existing resources — the account is empty

Read-only enumeration found **zero** pre-existing resources for every service in the spec's baseline: Lambda functions, REST/HTTP APIs, DynamoDB tables, Cognito user pools, SQS queues, SNS topics, SES identities, S3 buckets, CloudFront distributions, Location Service maps/place-indexes/route-calculators, KMS keys, Secrets Manager secrets, CloudWatch log groups, CloudTrail trails, Step Functions state machines, CloudFormation stacks, Route 53 hosted zones.

Present and pre-existing: 1 IAM role (`AccountFullAccessRole`), 1 default EventBridge bus, 1 X-Ray default sampling rule, 9 CloudWatch metrics, 1 budget. All AWS-managed defaults.

**Nothing from a previous LifeLink attempt exists in this account.**

### 4.3 Service availability — all required services are available

Every service in the spec's PART 9 baseline was verified two ways: a live read-only API call in `ap-southeast-2`, and a check against the Free Tier supported-services list for the new AWS experience.

| Service | Spec feature | Live API in region | FREE plan |
|---|---|---|---|
| AWS Lambda | F1–F4, F7 | ✅ | ✅ (no Lambda@Edge) |
| API Gateway (REST + HTTP) | F7 | ✅ | ✅ |
| DynamoDB | F1–F4 | ✅ | ✅ (no DAX) |
| Cognito | F6 | ✅ | ✅ |
| SQS | F1, F4, F7 | ✅ | ✅ |
| SNS | F3, F4 | ✅ | ✅ |
| SES / SESv2 | F3, F4 | ✅ | ✅ (no deliverability dashboard) |
| S3 | F5, F7 | ✅ | ✅ (no Access Grants) |
| CloudFront | F5, F7 | ✅ | ✅ (no Lambda@Edge) |
| **Amazon Location Service** | F2 | ✅ maps, places, routes | ✅ |
| KMS | F6 | ✅ | ✅ |
| Secrets Manager | F6 | ✅ | ✅ |
| CloudWatch + Logs | F6 | ✅ | ✅ |
| CloudTrail | F6 | ✅ | ✅ |
| Step Functions | F4 (if justified) | ✅ | ✅ |
| Route 53 | F7 (if domain) | ✅ | ✅ |
| CloudFormation | F7 | ✅ | ✅ |
| IAM | F6 | ✅ | ✅ |
| X-Ray | F6 | ✅ | ✅ |
| EventBridge | F7 | ✅ | ✅ |

**No service required by the specification is blocked by the FREE plan or missing from the Region.** Amazon Location Service — the single biggest availability risk for Feature 2 — is confirmed available on both counts.

### 4.4 Quotas and limits

| Quota | Value | Default | Assessment |
|---|---|---|---|
| **Lambda concurrent executions** | **10** | 1,000 | **Severely constrained — see Risk R-01** |
| Lambda unreserved concurrency | 10 | — | Reserved concurrency would consume this pool |
| Lambda code storage | 300 GB (0 used) | 75 GB | Fine |
| Lambda deployment package | 50 MB zipped / 250 MB unzipped | — | Fine |
| DynamoDB tables per Region | 2,500 | 2,500 | Fine |
| API Gateway regional APIs | 10,000 | — | Fine |
| **SES sending** | **Sandbox**: 200/day, 1/sec, verified recipients only | — | **See Risk R-02** |
| SES enforcement status | HEALTHY, sending enabled, ESSENTIALS plan | — | — |

### 4.5 Confirmed SCP restriction

`sns:GetSMSAttributes` is **denied by service control policy** `p-2cb1m8xd` (`sms-voice:DescribeSpendLimits`). AWS End User Messaging SMS is a Paid-Plan service and is not available on the FREE plan.

**Consequence: SMS notification delivery is not available.** The spec's notification subsystem (§10.3) does not mandate SMS; it says "contact or notification preference". Email via SES plus in-app notifications satisfy the requirement. The notification service will be built with a pluggable channel interface so SMS can be added later without redesign, and SMS will be documented as NOT IMPLEMENTED rather than silently stubbed.

---

## 5. Risk register

Ranked by impact on delivering the seven features.

| ID | Risk | Impact | Likelihood | Mitigation | Needs user decision |
|---|---|---|---|---|---|
| **R-01** | **Lambda concurrency capped at 10** | **High** — the architecture has API handlers, SQS consumers and a P1/P2/P3 dispatcher all competing for 10 slots. Reserved concurrency for priority lanes would starve the API. Realistic load testing of the matching engine is impossible at this ceiling. | Certain | Design for low concurrency: no reserved concurrency; small SQS batch sizes; application-level dispatcher rather than per-priority reserved capacity (which §6.6 already prefers). Document the limit as a stated constraint in Book 1 and the cost/scaling chapters. A quota increase is requestable but is an account change. | Yes — if a quota increase is wanted |
| **R-02** | **SES is in sandbox** | Medium — email only reaches verified addresses, 200/day, 1/sec. | Certain | Correct for a demo. Notifications will record true delivery status and never claim delivery from a queue write (§10.3). Production access is a separate request; documented as a limitation. | No |
| **R-03** | **SMS unavailable (SCP + Paid Plan)** | Low–Medium | Certain | Pluggable notification channels; SMS documented NOT IMPLEMENTED. | No |
| **R-04** | **Node.js not installed** | **Blocker for Feature 5** — no React, Vite, or frontend tests. | Certain | Install Node.js LTS via winget. | **Yes — approval to install** |
| **R-05** | **AWS SAM CLI not installed** | High for Feature 7 — `sam validate` is a PART 19 acceptance criterion. | Certain | Install SAM CLI via winget; or validate with `cfn-lint` + `aws cloudformation validate-template` (read-only) as a fallback. | **Yes — approval to install** |
| **R-06** | **Docker not installed** | Medium — no `sam local`, no containerised DynamoDB Local. | Certain | Java 26 is installed, so run DynamoDB Local from its JAR instead; use `moto` for unit-level AWS mocking. Avoids Docker entirely. | No — workaround is sound |
| **R-07** | Python deps missing (reportlab, boto3, pytest, moto, markdown, pypdf) | High but routine | Certain | Create `.venv` and install from `requirements-dev.txt`. No system-wide change. | No |
| **R-08** | **Existing GitHub remote makes accidental publishing possible** | High if it happened | Low | No push, no remote change. Handover gives the user the commands to run themselves. | No |
| **R-09** | Scope is very large (7 features, ~100 edge cases, 3 books of 70–130 pages each) | High — risk of shallow coverage or an unverified COMPLETE claim | High | Follow PART 17 phases strictly; status every deliverable COMPLETE/PARTIAL/BLOCKED/NOT IMPLEMENTED per PART 20; never mark COMPLETE without running the check. | No |
| **R-10** | Credential session expiry (cached token expired 2026-11-15T10:33Z; refresh token in use) | Low | Medium | On sudden AccessDenied, re-run `aws login` before suspecting IAM or spend limits. | No |
| **R-11** | FREE plan credits (120 USD, to 2027-05-15) and spend limits could pause the project if deployment happens later | Low while local-only | Low | No deployment this task. Cost estimate produced in Phase 9 per §9.4. | No |
| **R-12** | Map tiles: §2.7 forbids treating public OSM tile servers as production | Medium | Medium | Use Amazon Location Service maps as the tile source with correct attribution; MapLibre is renderer-only. | No |
| **R-13** | No medically reviewed blood compatibility reference is supplied | Medium — §6.5 requires rules from a documented, medically reviewed source | Certain | Implement compatibility as versioned, testable reference **data**, clearly labelled as requiring qualified clinical review before any real use. Never present it as clinically certified. | No — but disclosed in docs |
| **R-14** | Windows host: path separators, CRLF, no `make` | Low | Certain | Python/npm scripts instead of a Makefile; `.gitattributes` for line endings. | No |

---

## 6. Decisions taken in Phase 0

1. **Region stays `ap-southeast-2`.** Verified live; not changed.
2. **Python 3.14** locally and `python3.14` as the Lambda runtime — exact local/Lambda parity, supported until 2029-06-30.
3. **DynamoDB Local via the Java JAR**, not Docker, since Java 26 is present and Docker is not.
4. **Notification channels:** email (SES) + in-app. SMS documented as unavailable, with a pluggable interface.
5. **Task runner:** Python scripts and npm scripts rather than `make`, per §11.3's allowance to adapt commands.
6. **The Git remote is left exactly as found.** No push, no remote modification, no history rewrite.

---

## 7. Phase 0 exit checklist

| Phase 0 requirement (PART 17) | Status |
|---|---|
| Inspect workspace | ✅ |
| Inspect installed tools | ✅ |
| Inspect existing project state | ✅ Greenfield |
| Inspect local Git status | ✅ Remote discovered and flagged |
| Inspect AWS profile configuration safely | ✅ Read-only |
| Verify identity and configured region (read-only) | ✅ Account 426150327442 / ap-southeast-2 |
| Check required service availability and quotas | ✅ All available; concurrency limit found |
| Do not deploy | ✅ Nothing created, modified or deleted |
| Create a project inventory and risk list | ✅ This document |

**Phase 0 is complete.** Four items need a user decision before Phase 1 implementation work can proceed at full speed: R-01 (concurrency), R-04 (Node.js), R-05 (SAM CLI), and confirmation that the no-deploy / no-publish boundary holds for the whole build.
