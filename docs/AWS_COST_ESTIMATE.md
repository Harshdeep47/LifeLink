# LifeLink — AWS Cost Estimate

Built from published AWS pricing for `ap-southeast-2`, not from a bill.
**Nothing has been deployed, so no actual spend exists.**

---

## The headline

> **LifeLink is not free to run.**
>
> Two charges apply regardless of usage: a KMS customer-managed key at $1.00
> per month and a Secrets Manager secret at $0.40 per month — **$1.40 per
> month fixed**.
>
> Everything else sits inside free tiers at demonstration volume. The two
> items that scale with real usage are Amazon Location map tile loads and
> CloudWatch Logs ingestion.

## Fixed costs

| Item | Monthly | Avoidable? |
|---|---|---|
| KMS customer-managed key (audit table) | $1.00 | Yes, by using an AWS-managed key — trading a real security property for a dollar |
| Secrets Manager secret | $0.40 | Yes, if no external provider credentials are needed |
| **Total** | **$1.40** | |

## Usage-based costs

| Service | Free tier | Beyond it | Demo exposure |
|---|---|---|---|
| Lambda | 1M requests, 400k GB-s monthly | $0.20/M + $0.0000133/GB-s | Negligible |
| DynamoDB on-demand | 25 GB storage | $1.25/M writes, $0.25/M reads | Low |
| API Gateway HTTP | 1M requests (first 12 months) | ~$1.00/M | Negligible |
| S3 | 5 GB standard | $0.025/GB/month | Pennies |
| CloudFront | 1 TB transfer, 10M requests monthly | $0.085/GB | Negligible |
| Cognito | 50,000 monthly active users | $0.0055/MAU | Zero |
| SQS | 1M requests monthly | $0.40/M | Negligible |
| SES | 3,000 messages (first 12 months) | $0.10/1,000 | Negligible |
| **Amazon Location — map tiles** | Limited | **~$0.50/1,000 tile loads** | **Dominant variable cost** |
| Amazon Location — places | Limited | ~$0.04/1,000 requests | Low |
| Amazon Location — routes | Limited | ~$0.04/1,000 requests | Low |
| **CloudWatch Logs** | 5 GB ingestion monthly | **$0.50/GB ingested** | **Grows quietly** |
| CloudWatch alarms | 10 free | $0.10/alarm/month | 8 alarms — free |
| CloudTrail | First trail free | $2.00/100k events | Production only |

## Modelled scenarios

These are arithmetic from the table above, not measurements.

### Demonstration: 100 searches/day, 10 stock updates/day

| Service | Monthly volume | Cost |
|---|---|---|
| Lambda | ~4,000 invocations | $0 (free tier) |
| DynamoDB | ~300k reads, ~5k writes | $0 (free tier) |
| API Gateway | ~4,000 requests | $0 (free tier) |
| Map tiles | ~6,000 loads | $0–3 depending on free-tier state |
| Logs | ~0.2 GB | $0 (free tier) |
| Fixed | — | $1.40 |
| **Total** | | **$1.40–4.40/month** |

### Pilot: 5,000 searches/day, 500 updates/day, 50 camps

| Service | Monthly volume | Cost |
|---|---|---|
| Lambda | ~200k invocations | $0–2 |
| DynamoDB | ~15M reads, ~250k writes | ~$4 |
| API Gateway | ~200k requests | $0–1 |
| Map tiles | ~300,000 loads | **~$150** |
| Logs | ~8 GB | ~$1.50 |
| SES | ~5,000 emails | ~$0.50 |
| Fixed | — | $1.40 |
| **Total** | | **~$160/month** |

The map tile line dominates. That is why the facility list view is a
first-class feature rather than only a fallback: it is also the cheapest way
to render results.

## Where the cost actually went

| Decision | Saving |
|---|---|
| HTTP API rather than REST API | ~70% per request |
| `arm64` rather than `x86_64` | ~20% per millisecond |
| On-demand rather than provisioned DynamoDB | Everything at rest |
| `INCLUDE` rather than `ALL` index projections | Storage and read units |
| `PriceClass_100` on CloudFront | Cheaper edge locations only |
| Log retention as a parameter, 30-day default | Unbounded log growth |
| Access logs excluding bodies | Volume, and privacy |
| One Lambda rather than fifty | Cold starts, not dollars directly |
| No DAX, no OpenSearch, no Step Functions | Entire service line items |

## Cost controls

| Control | Where |
|---|---|
| Spend limit | AWS Settings → Billing (project owner only) |
| Budgets and anomaly detection | AWS Billing and Cost Management console |
| Log retention | `LogRetentionDays` template parameter |
| API throttling | 10 requests/second, bounding downstream spend |
| Lambda concurrency ceiling of 10 | Incidentally caps runaway compute cost |

## What would change the picture

**Map tiles.** Caching the style descriptor, reducing default zoom, and
defaulting more users to the list view.

**Logs.** Shorter retention, or sampling info-level logs in production while
keeping warnings and errors.

**A read model for dashboards.** Would add storage but cut repeated
aggregation reads.

**A concurrency increase.** Would raise the cost ceiling as well as the
throughput one.

## Account state

The account carries 120 USD of promotional credit expiring 2027-05-15, which
comfortably covers a demonstration deployment. That is a fact about this
account, not a property of the architecture, and it should not be read as the
system being free.
