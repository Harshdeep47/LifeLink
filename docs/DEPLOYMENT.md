# LifeLink — Deployment

> **NOTHING HAS BEEN DEPLOYED.**
>
> The infrastructure template is validated by `cfn-lint` and
> `sam validate --lint` with no findings. That is the full extent of the
> verification. Every statement in this document describes what *would*
> happen, and deployment requires explicit approval from the project owner.

---

## Pre-deployment checklist

Run every one of these and confirm the expected result before deploying.

| # | Check | Command | Expected |
|---|---|---|---|
| 1 | Account identity | `aws sts get-caller-identity` | Account `426150327442` |
| 2 | Region | `aws configure get region --profile lifelink` | `ap-southeast-2` |
| 3 | Account plan | `aws freetier get-account-plan-state` | Known; affects service availability |
| 4 | Spend limit | AWS Settings → Billing | Confirmed with the owner |
| 5 | Template syntax | `sam validate --template infrastructure/template.yaml --lint` | Valid (SAM CLI 1.174.0) |
| 6 | Template lint | `cfn-lint infrastructure/template.yaml` | No findings |
| 7 | Backend tests | `cd backend && pytest tests` | 657 passing |
| 8 | Frontend tests | `cd frontend && npm test` | 294 passing |
| 9 | Frontend build | `cd frontend && npm run build` | Succeeds |
| 10 | Lint | `cd backend && ruff check src tests` | Clean |
| 11 | OpenAPI current | `python scripts/generate_openapi.py --check` | Matches |
| 12 | No secrets staged | `git diff --cached` | Nothing sensitive |
| 13 | Environment parameter | — | Not `prod` by accident |
| 14 | Cognito domain prefix | — | Globally unique |

## What the stack creates

59 resources in `ap-southeast-2`:

| Category | Resources |
|---|---|
| Data | 12 DynamoDB tables, 24 global secondary indexes |
| Compute | 6 Lambda functions on `python3.14`, `arm64` |
| API | 1 API Gateway HTTP API with access logging |
| Identity | Cognito user pool, app client, domain, identity pool, map-reader role |
| Messaging | 2 SQS queues, 2 dead-letter queues |
| Storage | 2 private S3 buckets, 1 CloudFront distribution with OAC |
| Location | Map, place index, route calculator |
| Security | KMS key with rotation, Secrets Manager secret |
| Observability | 8 alarms, 1 dashboard, 2 log groups, SNS alarm topic |

## Deploying

> **Do not use `sam build` on a Windows or x86 host.** It installs the local
> platform's wheels, and `cryptography` — required for RS256 token
> verification — becomes a Windows binary that cannot load on arm64 Lambda.
> Authentication would fail at runtime with an import error. Use the project's
> own packager, which fetches `manylinux2014_aarch64` wheels.

```bash
# Build the Lambda package for the target platform (NOT `sam build`)
python scripts/build_lambda_package.py --verify

# Deploy with an explicit changeset review
sam deploy \
  --template infrastructure/template.yaml \
  --stack-name lifelink-dev \
  --region ap-southeast-2 \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides \
      Environment=dev \
      CognitoDomainPrefix=lifelink-dev-<unique> \
      CallbackUrl=https://<distribution>/auth/callback \
      LogoutUrl=https://<distribution>/ \
  --confirm-changeset
```

`--confirm-changeset` is not optional. It is the step where a destructive
change becomes visible before it happens.

## Deploying the frontend

The template creates the bucket and distribution but does not upload the
bundle — keeping them separate means a frontend-only change does not require a
stack update.

```bash
cd frontend
VITE_API_BASE=https://<api-id>.execute-api.ap-southeast-2.amazonaws.com/dev \
VITE_MAP_STYLE_URL=<amazon-location-style-descriptor> \
npm run build

aws s3 sync dist/ s3://<FrontendBucketName>/ --delete
aws cloudfront create-invalidation --distribution-id <id> --paths "/*"
```

## Post-deployment verification

| # | Check | How |
|---|---|---|
| 1 | Stack complete | `aws cloudformation describe-stacks --stack-name lifelink-dev` |
| 2 | Tables exist | `aws dynamodb list-tables` — expect 11 |
| 3 | API responds | `curl https://<api>/dev/health` |
| 4 | Reference data | `curl https://<api>/dev/reference` |
| 5 | Frontend loads | Open the CloudFront URL |
| 6 | Sign-in works | Complete a Cognito login |
| 7 | Alarms exist | `aws cloudwatch describe-alarms --alarm-name-prefix lifelink-dev` |
| 8 | Subscribe to alarms | Confirm an email subscription on the SNS topic |

## Seeding a deployed environment

The demo seeder refuses to run against real AWS. That is deliberate: it checks
the environment name, requires a local endpoint, and refuses an endpoint
pointing at `amazonaws.com`.

To seed a `dev` deployment the guard would need a reviewed change, and the
decision to put synthetic data in a cloud environment should be made
explicitly rather than by convenience.

## Rollback

CloudFormation rolls back automatically on a failed create or update.

On a stack deletion, resources with `DeletionPolicy: Retain` survive: all
tables in production, and the audit table in every environment. A deleted
stack therefore leaves data intact and recreatable infrastructure gone.

## Cost on deployment

About **$1.40 per month** in fixed charges regardless of usage:

| Item | Cost |
|---|---|
| KMS customer-managed key | $1.00/month |
| Secrets Manager secret | $0.40/month |

Everything else is inside free tiers at demonstration volume. The two items
that scale with use are Amazon Location map tile loads and CloudWatch Logs
ingestion. See [AWS_COST_ESTIMATE.md](AWS_COST_ESTIMATE.md).

## Tearing down

```bash
# Empty the buckets first; CloudFormation will not delete non-empty ones
aws s3 rm s3://<FrontendBucketName> --recursive
aws s3 rm s3://<UploadsBucketName> --recursive

aws cloudformation delete-stack --stack-name lifelink-dev
```

Retained resources — the audit table, and all tables in production — must be
deleted manually and deliberately.

## Known deployment risks

| Risk | Mitigation |
|---|---|
| Cognito domain prefix already taken globally | Choose a unique prefix; failure is at create time |
| CloudFront distribution takes 15–20 minutes | Expected; not a failure |
| First deployment exceeds a spend limit | Confirm the limit with the owner beforehand |
| Lambda concurrency of 10 throttles under demonstration load | Expected and alarmed; request an increase if needed |
| SES sandbox blocks email to unverified recipients | Verify recipient addresses, or request production access |
