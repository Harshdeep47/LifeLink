# LifeLink

**Blood availability, blood bank discovery, voluntary donation and emergency
coordination.**

> **DEMO ENVIRONMENT — SYNTHETIC DATA — NOT REAL BLOOD AVAILABILITY**
>
> Every organization, facility, stock record, camp, donor and emergency request
> in this repository is invented. No real institution is represented and none is
> a partner. LifeLink is not a medical device, provides no clinical advice, does
> not reserve blood, and does not determine clinical urgency or suitability.

---

## What it does

LifeLink connects people who need blood with blood banks, hospitals, donors and
donation camps. **Four user-facing features:**

| # | Feature | Summary |
|---|---|---|
| 1 | **Blood Bank Inventory Management** | Batch-level stock with expiry, quarantine, independent verification and an append-only audit trail |
| 2 | **Location Services and Navigation** | Geospatial search ranked by availability, freshness, verification and distance, with clustering maps and directions |
| 3 | **Blood Donation Camps and Donor Engagement** | Camp lifecycle, registration, attendance, verified donation, impact ledger |
| 4 | **Smart Emergency Coordination** | Hospital-certified clinical priority, deterministic matching, provider responses |

Placing a **temporary reservation** is how a user makes an ordinary request for
units — it is part of feature 1 rather than a fifth feature, and deliberately
not a separate request entity
([ADR-0018](docs/ARCHITECTURE_DECISIONS.md#adr-0018)). It is kept distinct from
Smart Emergency Coordination throughout.

### Supporting architecture

These are engineering components that carry the four features, not additional
products:

| Component | What it provides |
|---|---|
| Frontend and user experience | Responsive, accessible React application with role-based dashboards |
| Security and monitoring | RBAC over 39 permissions and 10 roles, organization isolation, audit trail, structured logging, CloudWatch alarms |
| Cloud infrastructure | AWS SAM template, deployed as stack `lifelink-dev` |

## The design ideas worth knowing

- **Unknown is not zero.** A facility that has reported nothing shows "Not
  reported", never "0 units". The two lead a user to opposite actions.
- **Updated is not verified.** Freshness and independent human verification are
  separate fields, shown as separate badges, always together.
- **An offer is not a reservation.** Browsing holds nothing: a figure in a
  search result is a report from the facility until someone explicitly
  reserves against it. Temporary reservations were added later and *do* hold
  units — a hold is atomic, time-bounded, visible to its owner on the
  "My activity" page, and released on expiry, cancellation or rejection. What
  a hold still is not: clinical approval, a cross-match, or a guarantee of
  release.
- **Dispatch order is not clinical priority.** Fairness scheduling writes a
  different field from the one a clinician certifies.
- **Fail closed.** Missing expiry, unknown compatibility and timestamp-less
  feeds all resolve to a refusal rather than a guess.

## Status

Measured on 24 November 2026, not estimated.

| Item | Status |
|---|---|
| Backend tests | **657 passing** (566 unit, 91 integration) |
| Frontend tests | **294 passing** |
| **Total automated** | **951 passing** |
| Live checks against the deployed API | **56 passing** (19 authentication, 37 workflow) |
| Backend lint | `ruff check` clean |
| Frontend lint | `npm run lint` clean (0 errors; 15 `exhaustive-deps` warnings, see below) |
| Frontend build | `npm run build` clean |
| Infrastructure | `cfn-lint` clean; `sam validate --lint` clean (SAM CLI 1.174.0) |
| **Deployed to AWS** | **Yes — live at https://d324z37do52g8f.cloudfront.net** · see [DEPLOYMENT_RECORD](docs/DEPLOYMENT_RECORD.md) |
| Release commit | [`f9765af`](https://github.com/Harshdeep47/LifeLink/commit/f9765af20c22be144c8926d65c3602f63923e1c9) on `main` |
| Documentation | Three PDF books, 328 pages, rebuilt 24 November 2026, 24 validation checks passing |

> **Deployed and in sync.** Frontend and backend were both deployed on
> 24 November 2026 and verified against the live system — 56 live checks
> passing, including the reservation counter read straight from DynamoDB. The
> live bundle hash and the Lambda code SHA both match this repository. See
> [REPOSITORY_VS_DEPLOYED](docs/REPOSITORY_VS_DEPLOYED.md) for the evidence,
> and [RESERVATION_COUNTER_DEFECT](docs/RESERVATION_COUNTER_DEFECT.md) for the
> overselling defect found and fixed during that verification.

## Quick start

```bash
# 1. Python environment
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r backend/requirements-dev.txt
.venv/Scripts/python.exe -m pip install -r requirements-docs.txt

# 2. Local development keys (gitignored)
python scripts/dev.py keys

# 3. Local DynamoDB-compatible endpoint
python scripts/dev.py db-start

# 4. Tables
python scripts/dev.py create-tables

# 5. Synthetic demo data
python scripts/seed_demo.py
python scripts/seed_demo.py --validate

# 6. API server
python scripts/local_server.py --port 8080

# 7. Frontend, in a second terminal
cd frontend && npm install && npm run dev
```

Then open <http://localhost:5173>.

To sign in, mint a development token and paste it on the sign-in page:

```bash
python scripts/dev.py token user-donor-1
```

See [docs/LOCAL_DEVELOPMENT.md](docs/LOCAL_DEVELOPMENT.md) for the full guide
and [docs/DEMO_GUIDE.md](docs/DEMO_GUIDE.md) for a demonstration script.

## Repository layout

```
backend/          Python domain logic, services, repositories, Lambda handlers
frontend/         React application
infrastructure/   AWS SAM template (validated and deployed as stack lifelink-dev)
scripts/          Local stack, seeding, OpenAPI generation, book build
docs/             Architecture, decisions, runbooks, and the three PDF books
```

## Documentation

| Document | Contents |
|---|---|
| [REPOSITORY_VS_DEPLOYED](docs/REPOSITORY_VS_DEPLOYED.md) | **Read first** — repository and deployment are in sync, with the proof. What is live-verified, test-verified, and what still needs a browser |
| [PROJECT_OVERVIEW](docs/PROJECT_OVERVIEW.md) | What LifeLink is and who it serves |
| [REQUIREMENTS](docs/REQUIREMENTS.md) | Functional and non-functional requirements |
| [ARCHITECTURE](docs/ARCHITECTURE.md) | System design and component responsibilities |
| [ARCHITECTURE_DECISIONS](docs/ARCHITECTURE_DECISIONS.md) | 19 ADRs with rejected alternatives |
| [DATABASE_DESIGN](docs/DATABASE_DESIGN.md) | 12 tables, 24 indexes, 45 access patterns |
| [API_DOCUMENTATION](docs/API_DOCUMENTATION.md) | REST conventions and the endpoint catalogue |
| [SECURITY](docs/SECURITY.md) | Authentication, RBAC, isolation, audit |
| [PRIVACY_AND_DATA_HANDLING](docs/PRIVACY_AND_DATA_HANDLING.md) | What is collected and why |
| [LOCAL_DEVELOPMENT](docs/LOCAL_DEVELOPMENT.md) | Running the stack |
| [DEMO_GUIDE](docs/DEMO_GUIDE.md) | A 15-minute demonstration script |
| [DEMO_DATA](docs/DEMO_DATA.md) | The synthetic dataset |
| [CLOUD_DEMONSTRATION_GUIDE](docs/CLOUD_DEMONSTRATION_GUIDE.md) | Six Cognito/IAM/Lambda/DynamoDB demonstrations with console paths and expected output |
| [REAL_FACILITY_DATA](docs/REAL_FACILITY_DATA.md) | Provenance model for real facility records, and why none is loaded |
| [TESTING](docs/TESTING.md) | Strategy and actual results |
| [DEPLOYMENT](docs/DEPLOYMENT.md) | How to deploy, when approved |
| [AWS_COST_ESTIMATE](docs/AWS_COST_ESTIMATE.md) | Cost structure and assumptions |
| [EDGE_CASE_REGISTER](docs/EDGE_CASE_REGISTER.md) | Every edge case, with its test |
| [OPERATIONS_RUNBOOK](docs/OPERATIONS_RUNBOOK.md) | Alarm response procedures |
| [TROUBLESHOOTING](docs/TROUBLESHOOTING.md) | Symptoms and resolutions |
| [KNOWN_LIMITATIONS](docs/KNOWN_LIMITATIONS.md) | What does not work, and why |
| [ENVIRONMENT_VARIABLES](docs/ENVIRONMENT_VARIABLES.md) | Configuration reference |
| [DOCUMENTATION_VALIDATION](docs/DOCUMENTATION_VALIDATION.md) | Measured book build report |
| [RELEASE_NOTES](docs/RELEASE_NOTES.md) | What changed |
| [PROGRESS](docs/PROGRESS.md) | Build log by phase, with the full defect log |
| [FINAL_HANDOVER](docs/FINAL_HANDOVER.md) | **Start here** — status of all 26 deliverables, and the publish commands |
| [DEPLOYMENT_RECORD](docs/DEPLOYMENT_RECORD.md) | The live deployment, and the 5 defects only deploying could find |
| [RECOVERY_SPRINT_REPORT](docs/RECOVERY_SPRINT_REPORT.md) | CORS, Cognito PKCE, temporary reservations, public emergency requests |
| [SPRINT3_FUNCTIONALITY_REPORT](docs/SPRINT3_FUNCTIONALITY_REPORT.md) | User provisioning, public discovery, maps, camp data |
| [FINAL_DEMO_READINESS_REPORT](docs/FINAL_DEMO_READINESS_REPORT.md) | Zero-distance fix, origin provenance, basemap, sign-up, profile |
| [FINAL_PRODUCT_SPRINT_REPORT](docs/FINAL_PRODUCT_SPRINT_REPORT.md) | Map default-export bug, Explore dashboards, Request blood, footer |
| [MAP_STABILISATION_REPORT](docs/MAP_STABILISATION_REPORT.md) | MapLibre worker root cause and fix |
| [MAP_DISCOVERY_UX_REPORT](docs/MAP_DISCOVERY_UX_REPORT.md) | Clustering, named markers, map/list synchronisation |
| [FINAL_POLISH_REPORT](docs/FINAL_POLISH_REPORT.md) | The two missing reservation screens, an auth bug, a token-audience fix |
| [RESERVATION_COUNTER_DEFECT](docs/RESERVATION_COUNTER_DEFECT.md) | **Latest** — post-mortem: confirming a hold released its units, permitting overselling |

### The teaching library — `final_docs/`

**70 Markdown documents** written for someone learning the project from
nothing: beginner-to-advanced explanations, AWS Console walkthroughs, lab
demonstration scripts and viva preparation.

| Entry point | Purpose |
|---|---|
| [final_docs/README.md](final_docs/README.md) | **Start here** — index and a two-day study path |
| [final_docs/AI_TEACHING_CONTEXT.md](final_docs/AI_TEACHING_CONTEXT.md) | Complete project briefing in one file, for an AI assistant teaching this project |
| [CONFIGURATION_WALKTHROUGHS.md](final_docs/09_PRACTICAL_AWS_DEMONSTRATIONS/CONFIGURATION_WALKTHROUGHS.md) | 60 AWS settings with their deployed values and exact Console paths |
| [Known limitations and actual status](final_docs/13_REFERENCE_AND_REVISION/05_Known_Limitations_And_Actual_Status.md) | What is verified, what is not, and what to admit |

Thirteen sections cover the architecture, a file-by-file source map, every AWS
service, the data model, each feature, security, practical demonstrations, lab
evaluation and interview preparation. Every technical claim was checked against
the running system, the infrastructure template or the source code on
24 November 2026.

**Three things, often confused.** They are complementary, not alternatives:

| | What it is | Kept current by |
|---|---|---|
| **`final_docs/`** | The **teaching layer**. Hand-written Markdown explaining *how to understand, demonstrate and talk about* LifeLink | Written and verified against the live system; not auto-generated |
| **The three PDF books** | The **reference layer**. Long-form technical books, **generated from this repository** — code listings extracted and metrics measured at build time | `python scripts/build_books.py` |
| **The deployed application** | The **running system**: stack `lifelink-dev`, 66 resources in `ap-southeast-2`, live at `d324z37do52g8f.cloudfront.net` | [DEPLOYMENT_RECORD](docs/DEPLOYMENT_RECORD.md) and [REPOSITORY_VS_DEPLOYED](docs/REPOSITORY_VS_DEPLOYED.md) |

Where `final_docs/` and an older document disagree about current status,
`final_docs/` and [DEPLOYMENT_RECORD](docs/DEPLOYMENT_RECORD.md) are
authoritative.

### The three books

| Book | Pages | Topic |
|---|---|---|
| [Book 1](docs/books/LifeLink_Book_1_System_Architecture_and_AWS.pdf) | 80 | System architecture and AWS cloud engineering |
| [Book 2](docs/books/LifeLink_Book_2_Implementation_and_Operations.pdf) | 147 | Implementation and operations |
| [Book 3](docs/books/LifeLink_Book_3_Interview_Viva_and_Engineering.pdf) | 101 | Concepts, viva and interview preparation |

Rebuilt on **26 November 2026**, when the deployment-status and cost
statements in their sources were corrected. Every count, version and size in
them is re-measured from this repository at build time, so they carry the
current figures; see
[DOCUMENTATION_VALIDATION](docs/DOCUMENTATION_VALIDATION.md) for the
validation checks and the facts table.

Markdown sources live beside each PDF. The books are **generated from this
repository**: code listings are extracted at build time, metrics come from
running the test suites, and the build fails if a referenced function has been
renamed.

```bash
python scripts/build_books.py            # rebuild all three, running the suites
python scripts/build_books.py --preview  # also render sample page images
```

## Running the checks

```bash
cd backend && ../.venv/Scripts/python.exe -m pytest tests     # 657 tests
cd backend && ../.venv/Scripts/python.exe -m ruff check src tests
cd frontend && npm test                                        # 294 tests
cd frontend && npm run build
python scripts/generate_openapi.py --check
.venv/Scripts/cfn-lint.exe infrastructure/template.yaml
sam validate --template infrastructure/template.yaml --lint
```

## AWS

The project runs in account `426150327442` in `ap-southeast-2` on the AWS Free
Tier plan. **It is deployed and live** as CloudFormation stack `lifelink-dev`,
most recently on 24 November 2026, at a fixed cost of roughly **$0.40/month**.
The template passes both `cfn-lint` and `sam validate --lint`. Any further
deployment still requires explicit approval and a reviewed changeset — see
[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) and
[docs/DEPLOYMENT_RECORD.md](docs/DEPLOYMENT_RECORD.md).

Deployed resources: 12 DynamoDB tables, **six** Lambda functions (Python 3.14
on arm64), one API Gateway HTTP API, four SQS queues with a dead-letter queue
each, three S3 buckets, one CloudFront distribution, a Cognito user pool and
identity pool, Amazon Location map/place-index/route-calculator, one Secrets
Manager secret, SNS, eight CloudWatch alarms and a dashboard. EventBridge
Scheduler drives the dispatcher and the maintenance sweep.

**AWS Step Functions is not used** — there is no `AWS::StepFunctions` or
`AWS::Events::Rule` resource in the template. Workflow state lives in DynamoDB
and is advanced by the application; the scheduled dispatcher that does it is
[ADR-0006](docs/ARCHITECTURE_DECISIONS.md#adr-0006). No ADR rejects Step
Functions explicitly, so treat its absence as a scoping decision rather than a
recorded one.

One account constraint shapes the architecture: the Lambda concurrency ceiling
is **10**, against a default of 1000. No function reserves concurrency, queue
consumers cap their own parallelism, and the emergency dispatcher is a single
scheduled function rather than per-priority consumers.

## Licence and disclaimers

This is an educational demonstration project.

- The blood compatibility reference data is marked `UNREVIEWED_SYNTHETIC`. It
  has **not** been reviewed by a qualified professional for this deployment and
  must not be relied on clinically.
- Privacy and terms documents are placeholders requiring legal review.
- Recognition certificates are not medical or government documents.
