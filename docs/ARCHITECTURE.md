# LifeLink — Architecture

A concise reference. Book 1 covers the same ground in depth with diagrams and
the reasoning behind every AWS choice.

## System shape

```
Browser (React, MapLibre)
  ├── CloudFront → S3 (private, Origin Access Control)   static assets
  ├── API Gateway HTTP API → Lambda (one function)       all 58 routes
  ├── Cognito user pool                                  sign-in
  └── Cognito identity pool → Amazon Location            map tiles only

Lambda (API)
  ├── DynamoDB (12 tables, 24 GSIs)
  ├── SQS (work, notifications) + 2 dead-letter queues
  ├── Amazon Location (places, routes)  — server-side only
  └── CloudWatch (structured logs, metrics)

Background
  ├── Outbox publisher    ← DynamoDB stream on the outbox table
  ├── Work worker         ← SQS work queue
  ├── Notification worker ← SQS notification queue
  ├── Priority dispatcher ← EventBridge, every minute
  └── Maintenance         ← EventBridge, every ten minutes
```

All regional resources are in `ap-southeast-2`. CloudFront is global and is
administered through `us-east-1`, which the account's rules permit.

## Layers

| Layer | Directory | Rule |
|---|---|---|
| Handlers | `backend/src/handlers/` | Parse, call one service, format. No business rules, no boto3 |
| Services | `backend/src/services/` | Workflows. Depend on repository interfaces |
| Domain | `backend/src/domain/` | Pure functions. No I/O, no clock reads |
| Repositories | `backend/src/repositories/` | The only place DynamoDB types appear |
| Adapters | `backend/src/adapters/` | External providers behind interfaces |
| Platform | `backend/src/appcore/` | RBAC, context, logging, responses, auth |

Dependencies point inward only. `domain/` has no outgoing dependencies at all,
which is why 566 unit tests run in under two seconds with no mocks.

## Feature ownership

| Feature | Owns | Reads | Never |
|---|---|---|---|
| 1 Inventory | Batches, stock operations, alerts | Facilities | Makes clinical decisions |
| 2 Location | Facility directory, geo index, ranking | Inventory via Feature 1 | Keeps its own stock numbers |
| 3 Camps | Camps, registrations, donations, ledger | Identity | Touches inventory |
| 4 Emergency | Requests, certifications, responses | Inventory, facilities, compatibility | Sets clinical priority itself |
| 5 Frontend | Presentation | Everything via the API | Holds business rules |
| 6 Security | Identity, roles, audit, observability | Everything | Is optional on any path |
| 7 Infrastructure | Deployment topology | — | Is created by hand |

Boundaries are enforced by separate DynamoDB tables with separate IAM grants,
not only by convention.

## Data model

12 tables, one per bounded context. 24 global secondary indexes. 45 enumerated
access patterns, none of which resolves to a scan on a user-facing path.

Key techniques:

- **Composite sort keys** so a range condition replaces a filter expression.
  `STATUS#<status>#<expiresAt>` means ineligible stock is never read.
- **Three geohash precisions**, chosen by search radius, each with its own
  index.
- **Sharded expiry index** so the sweep cannot create a hot partition.
- **Deliberate projections**: `INCLUDE` with the attributes aggregation needs,
  `KEYS_ONLY` where only keys are needed.

Full detail in [DATABASE_DESIGN.md](DATABASE_DESIGN.md).

## Concurrency

Eight invariants, each enforced by the datastore rather than by convention:

| Invariant | Mechanism |
|---|---|
| Stock never negative | Condition on `availableUnits` |
| No lost update | Condition on `version` |
| No duplicate registration | `attribute_not_exists` on the sort key |
| Camp never oversubscribed | Transaction: registration + counter under capacity |
| Impact credited once | Transaction: donation + ledger row keyed on donation id |
| No duplicate event processing | Idempotency claim on event id |
| Event never lost on crash | Outbox row inside the domain transaction |
| Stale update cannot overwrite | Source timestamp compared to stored |

## Event flow

Domain change and outbox row are written in one transaction. A DynamoDB stream
triggers a publisher that sends to SQS and marks the row dispatched. Consumers
claim the event id before doing anything, so at-least-once delivery produces
effectively-once effects.

## Security

One authorization decorator. Five checks: token, principal from the database,
account status, permission, organization ownership. Roles and status come from
stored state, so revocation and suspension are immediate.

See [SECURITY.md](SECURITY.md).

## Observability

Structured JSON logs with automatic redaction, a correlation id propagated
from the browser through queues into background workers, eight actionable
alarms each mapped to a runbook step, and a five-widget dashboard.

## Key constraints shaping the design

| Constraint | Effect |
|---|---|
| Lambda concurrency ceiling of 10 | No reserved concurrency; consumers capped at 2; scheduled dispatcher instead of per-priority consumers |
| Single region | Within-region recovery only |
| SES sandbox | Verified recipients only |
| SMS denied by SCP | Channel not implemented |

## Decisions

Seventeen architecture decision records, each with the alternative that was
rejected, in [ARCHITECTURE_DECISIONS.md](ARCHITECTURE_DECISIONS.md).
