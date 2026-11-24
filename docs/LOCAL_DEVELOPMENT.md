# LifeLink — Local Development

The full stack runs on a developer machine with no AWS account and no Docker.

## Prerequisites

| Tool | Version used here | Required |
|---|---|---|
| Python | 3.14.2 | Yes |
| Node.js | 26.13.1 | For the frontend |
| AWS SAM CLI | 1.172.1 | Only to validate the template |
| AWS CLI | 2.40.3 | Only to inspect the account |
| Java | 26 | Only for the optional DynamoDB Local path |
| Docker | — | **Not required** |

## First run

```bash
# 1. Python environment
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r backend/requirements-dev.txt
.venv/Scripts/python.exe -m pip install -r requirements-docs.txt

# 2. Development signing keys (gitignored, local only)
python scripts/dev.py keys

# 3. Local DynamoDB-compatible endpoint
python scripts/dev.py db-start

# 4. Tables
python scripts/dev.py create-tables

# 5. Synthetic demo data
python scripts/seed_demo.py
python scripts/seed_demo.py --validate

# 6. API
python scripts/local_server.py --port 8080

# 7. Frontend, in a second terminal
cd frontend && npm install && npm run dev
```

Open <http://localhost:5173>.

`python scripts/dev.py status` reports what is and is not running.

## Signing in

Cognito has no local emulator, so the local stack issues its own tokens:

```bash
python scripts/dev.py token user-donor-1
```

Paste the output on the sign-in page.

> **This is a documented divergence.** The token *issuer* differs locally; the
> token *verifier* is the same code path in both environments, switched only
> by key source. Local development therefore does **not** exercise Cognito
> itself. The sign-in page says so too.

### Demo accounts

| User id | Role | Demonstrates |
|---|---|---|
| `user-donor-1` | DONOR | Verified donations, impact milestones |
| `user-bb-admin-1` | BLOOD_BANK_ADMIN | Inventory, corrections, verification |
| `user-bb-staff-1` | BLOOD_BANK_STAFF | Stock updates but **not** verification |
| `user-hosp-auth-1` | HOSPITAL_AUTHORIZER | Priority certification |
| `user-hosp-staff-1` | HOSPITAL_STAFF | Raising requests but **not** certifying |
| `user-camp-org-1` | CAMP_ORGANIZER | Camp management, donation verification |
| `user-camp-staff-1` | CAMP_STAFF | Check-in and verification, camp-scoped |
| `user-admin-1` | PLATFORM_ADMIN | Organization verification, suspension, audit |
| `user-suspended-1` | BLOOD_BANK_ADMIN, suspended | **Every action refused despite a valid token** |

## Why moto rather than DynamoDB Local

The specification suggests DynamoDB Local, a Java application distributed as a
downloadable archive. In the environment this project was built in, the
download was unavailable.

moto in server mode provides a DynamoDB-compatible HTTP endpoint from a
package already installed for testing. The application code, the boto3 client
and the connection configuration are unchanged — only the endpoint URL
differs, exactly as with the Java version.

| | DynamoDB Local | moto server |
|---|---|---|
| Download | ~60 MB archive | None |
| Runtime | Java | Python, already present |
| Condition expressions | Yes | Yes |
| Transactions | Yes | Yes |
| GSI range queries | Yes | Yes |
| Status here | Available via `dev.py dynamo-start` | **Default** |

Five real bugs were caught by integration tests against moto, which is the
evidence that the emulation is faithful enough for the invariants being tested.

## Daily commands

| Task | Command |
|---|---|
| Status | `python scripts/dev.py status` |
| Start the database | `python scripts/dev.py db-start` |
| Create tables | `python scripts/dev.py create-tables` |
| Drop tables | `python scripts/dev.py drop-tables --yes` |
| Seed | `python scripts/seed_demo.py` |
| Reset and seed | `python scripts/seed_demo.py --reset` |
| Validate the dataset | `python scripts/seed_demo.py --validate` |
| Mint a token | `python scripts/dev.py token <user-id>` |
| Run the API | `python scripts/local_server.py --port 8080` |
| Run the frontend | `cd frontend && npm run dev` |
| Backend tests | `cd backend && ../.venv/Scripts/python.exe -m pytest tests` |
| Frontend tests | `cd frontend && npm test` |
| Lint | `cd backend && ../.venv/Scripts/python.exe -m ruff check src tests` |
| Regenerate OpenAPI | `python scripts/generate_openapi.py` |
| Build the books | `python scripts/build_books.py` |

## What runs where

| Component | Local | AWS |
|---|---|---|
| Database | moto server on `:8000` | DynamoDB |
| API | `local_server.py` on `:8080` | Lambda behind API Gateway |
| Router and handlers | **Identical code** | **Identical code** |
| Identity | Local RSA keypair | Cognito |
| Geocoding | Static offline provider, 10 Punjab places | Amazon Location Places |
| Routing | Null provider, reports unavailable | Amazon Location Routes |
| Map tiles | None; list fallback renders | Amazon Location Maps |
| Email | Files in `.local-outbox/` | Amazon SES |
| Queues | Not run locally | SQS |

The router, handlers, services, domain layer and repositories are the same code
in both. The specification warns against a mock application that behaves
differently from the real architecture; the way to avoid that is to have only
one application.

## Things that will surprise you

**`npm` is not on the Git Bash PATH** on this machine — Node was installed
after the shell started. Use PowerShell, or the full path
`"C:\Program Files\nodejs\npm.cmd"`.

**Do not pass `-q` to pytest.** In this version it suppresses the summary
line, which is how the documentation build once recorded a test count of zero.

**An unused DynamoDB expression placeholder** produces a `ValidationException`
that names nothing useful. If an update suddenly fails, compare the
placeholders in the expression with the keys of the values dictionary.

**Renaming a function breaks the book build.** That is intended — the books
quote real source by name. Update the anchor.

**Do not rename the `appcore` package to `platform`.** It would shadow the
standard-library module that botocore imports, and the resulting error points
somewhere else entirely.

## Resetting everything

```bash
python scripts/dev.py drop-tables --yes
python scripts/dev.py create-tables
python scripts/seed_demo.py
```
