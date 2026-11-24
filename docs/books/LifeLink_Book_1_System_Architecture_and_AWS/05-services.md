<!-- pagebreak -->

# 12. Amazon S3 and CloudFront

## 12.1 What they are

S3 is durable object storage. CloudFront is a content delivery network that
caches at edge locations and terminates TLS close to the user.

## 12.2 Why LifeLink uses them

The frontend is a static bundle: HTML, JavaScript, CSS. Serving it from a web
server would mean operating a web server. S3 stores it, CloudFront distributes
it, and neither needs patching.

LifeLink uses two buckets with different purposes and different policies:

| Bucket | Contents | Public? | Versioning | Lifecycle |
|---|---|---|---|---|
| `frontend` | Built static assets | No — CloudFront only | Yes | Expire old versions after 30 days |
| `uploads` | Private user files | No — presigned URLs only | Yes | Abort incomplete uploads after 7 days |

*Table 12.1. The two buckets.*

## 12.3 Origin Access Control, not public read

The frontend bucket blocks all public access. CloudFront reaches it through
Origin Access Control, and the bucket policy permits exactly one principal —
the CloudFront service — and only when the request comes from this specific
distribution:

{{include:infrastructure/template.yaml:anchor:FrontendBucketPolicy:16}}

*Listing 12.1. The bucket policy. The `AWS:SourceArn` condition is the part
that matters: without it, any CloudFront distribution in any account could read
the bucket.*

## 12.4 Single-page application routing

A React application with client-side routing has a problem on static hosting: a
direct request for `/camps/abc123` asks S3 for an object that does not exist.
S3 returns 403 (because the bucket blocks listing) and the user sees an error
instead of the application.

The distribution maps 403 and 404 to `/index.html` with a 200 status and a
10-second cache, so deep links load the application, which then routes
client-side.

## 12.5 Cache strategy

The AWS managed `CachingOptimized` policy is used for static assets. This is
safe because Vite emits content-hashed filenames: `index-OxJqrZe4.js` changes
whenever its contents change, so a long cache lifetime never serves stale code.
`index.html` itself is the exception and is short-cached.

The API is deliberately **not** behind CloudFront. Caching a blood availability
response would directly undermine the product's purpose, and the freshness
labelling that the whole design turns on would start describing the cache rather
than the facility.

## 12.6 What can fail

| Failure | Effect | Handling |
|---|---|---|
| Origin unreachable | Cached assets still served | CloudFront serves from edge |
| Distribution misconfigured | Application does not load | Caught at deployment validation |
| Presigned URL expires | Upload or download fails | Short expiry by design; client requests a new one |
| Bucket policy wrong | 403 on every asset | `AWS:SourceArn` condition is template-managed |

*Table 12.2. S3 and CloudFront failure modes.*

## 12.7 Cost

S3 storage for a built frontend is a few megabytes — fractions of a cent.
CloudFront's free tier covers 1 TB of transfer monthly. `PriceClass_100`
restricts edge locations to the cheaper regions, which is appropriate for a
system whose users are in one country.

## 12.8 Alternatives

**S3 static website hosting** without CloudFront was considered and rejected:
it requires public bucket access, offers no TLS on a custom domain, and
provides no SPA fallback routing. **AWS Amplify Hosting** would work and is
simpler, but hides the CloudFront and S3 configuration that this project is
partly meant to demonstrate.

<!-- pagebreak -->

# 13. Amazon SQS and Dead-Letter Queues

## 13.1 What it is

A managed message queue with at-least-once delivery, configurable visibility
timeouts, and automatic redrive to a dead-letter queue after a configured number
of failed receives.

## 13.2 Why LifeLink uses it

Three things must happen after a stock change: the response must return
quickly, waiting donors must be matched, and notifications must be delivered.
Only the first is the user's concern. SQS decouples the other two from the
request.

## 13.3 Queue topology

```diagram
type: layered
title: Queues, consumers and dead letters
layer Producers
node api API function style=aws
node pub Outbox publisher style=aws
layer Queues
node work Work queue style=aws
node notif Notification queue style=aws
layer Consumers
node wkw Work worker alert matching style=aws
node nw Notification worker delivery style=aws
layer Failure
node wdlq Work dead letter queue style=external
node ndlq Notification dead letter queue style=external
layer Operations
node alarm CloudWatch alarms on both DLQs style=aws
edge api -> work
edge pub -> work
edge pub -> notif
edge work -> wkw
edge notif -> nw
edge work -> wdlq
edge notif -> ndlq
edge wdlq -> alarm
edge ndlq -> alarm
```

*Figure 13.1. Two queues, two consumers, two dead-letter queues, both alarmed.*

## 13.4 Configuration that matters

| Setting | Value | Reasoning |
|---|---|---|
| Visibility timeout | 180s | Six times the 29s consumer timeout, per AWS guidance |
| `maxReceiveCount` | 5 | Enough for transient failures, not so many that a poison message churns |
| DLQ retention | 14 days | The maximum: a human needs time to investigate |
| Batch size | 5 | Small, so one bad message blocks little |
| `MaximumConcurrency` | 2 | Leaves room in a pool of {{fact:lambda_concurrency}} |
| `FunctionResponseTypes` | `ReportBatchItemFailures` | Only failed messages return to the queue |
| Encryption | SQS-managed SSE | At rest, no key management overhead |

*Table 13.1. SQS settings and why each value was chosen.*

The partial-batch-failure setting deserves emphasis. Without it, one failing
message in a batch of five causes all five to be retried, including the four
that succeeded — which at best duplicates work and at worst, without
idempotency, duplicates effects.

{{include:backend/src/handlers/workers.py:def notification_handler}}

*Listing 13.1. A consumer that reports partial failures, from
`backend/src/handlers/workers.py`. Note the duplicate check before any work and
the per-message failure collection.*

## 13.5 At-least-once is not a defect

SQS guarantees at-least-once delivery. A message *will* occasionally arrive
twice. Treating that as an error to be eliminated is the wrong instinct; the
correct response is to make consumers idempotent, which LifeLink does with a
claim keyed on the event id.

:::key Design for duplicates, not against them
Every consumer in LifeLink asks "have I already done this?" before doing
anything. A duplicate delivery is logged at info level as a suppressed
duplicate, not as a failure, because it is normal operation.
:::

## 13.6 What can fail

| Failure | Effect | Handling |
|---|---|---|
| Consumer raises | Message returns after visibility timeout | Retried up to 5 times |
| Message fails 5 times | Moved to DLQ | Alarm fires within 5 minutes |
| Consumer throttled | Message returns | Retried; concurrency cap limits the blast |
| Backlog grows | Oldest-message age rises | Alarm at 5 minutes |
| Poison message | Isolated by partial batch failure | Reaches DLQ alone, not with its batch |

*Table 13.2. Queue failure modes.*

## 13.7 Cost

The free tier covers 1 million requests monthly. SQS is one of the cheapest
services in the design.

## 13.8 Alternatives

**EventBridge event bus** was considered. It has better routing and schema
support, but SQS gives per-consumer dead-letter queues and visibility-timeout
retry semantics that match the specification's requirements more directly. The
outbox makes switching later a change in one publisher, not a redesign.

**Step Functions** would model the emergency workflow explicitly. Chapter 3
explains why it was not adopted.

<!-- pagebreak -->

# 14. Notifications with SNS and SES

## 14.1 What they are

SNS is pub/sub messaging, used here for operational alarms. SES is an email
sending service, used for user notifications.

## 14.2 The channel model

The specification requires a reusable notification subsystem supporting user
preferences and consent. LifeLink implements channels behind an interface:

| Channel | Implementation | Status |
|---|---|---|
| In-app | DynamoDB record the dashboard reads | Implemented |
| Email | Amazon SES | Implemented, sandbox-limited |
| SMS | — | **NOT IMPLEMENTED** |
| Local file | Writes to `.local-outbox/` | Local development only |

*Table 14.1. Notification channels and their honest status.*

## 14.3 Why SMS is absent

:::warning SMS is not implemented, and is not pretending to be
AWS End User Messaging SMS is a Paid-Plan service, and this account's service
control policy denies `sms-voice:*` outright. Phase 0 verified this by calling
`sns:GetSMSAttributes` and receiving an explicit deny naming the policy.

LifeLink therefore has an `UnavailableSmsChannel` whose only behaviour is to
raise `CHANNEL_UNAVAILABLE` with the reason. It does not silently succeed, and
it does not log a pretend send.
:::

{{include:backend/src/adapters/notifications.py:class UnavailableSmsChannel}}

*Listing 14.1. A channel that refuses honestly, from
`backend/src/adapters/notifications.py`.*

This is a small piece of code making a large point. The alternative — a stub
that logs "SMS sent" — would produce an audit trail and a delivery-status record
that both lie.

## 14.4 Queueing is not delivery

The specification states that a notification must not be claimed as delivered
merely because it reached a queue. The type system carries that distinction:

{{include:backend/src/adapters/notifications.py:class DeliveryResult}}

*Listing 14.2. `QUEUED` and `SENT` are different states, and `delivered` is true
only for the latter.*

## 14.5 Consent and suppression

Before any send, the notification service checks consent, then the category
preference, then a durable duplicate-suppression marker. A suppressed
notification returns an outcome explaining which check stopped it, rather than
failing silently or sending anyway.

| Outcome | Meaning |
|---|---|
| `NO_CONSENT` | The user has never consented; nothing is sent |
| `CATEGORY_OPTED_OUT` | Consented generally, opted out of this category |
| `NO_CHANNELS_SELECTED` | Consented but selected no delivery channel |
| `DUPLICATE_SUPPRESSED` | An identical notification was already sent |

*Table 14.2. Suppression reasons, all reported rather than inferred.*

## 14.6 The SES sandbox

The account's SES is in {{fact:ses_mode}}. For a demonstration this is
adequate, and the limitation is recorded in the known-limitations document
rather than worked around. Production access is a separate request with its own
review.

## 14.7 Cost

SES costs $0.10 per thousand emails after a free allowance. SNS alarm
notifications are effectively free at this volume.

<!-- pagebreak -->

# 15. Amazon Location Service and Map Rendering

## 15.1 What MapLibre is not

MapLibre GL JS is a renderer. It draws vector tiles in a browser. It does not
supply tiles, does not geocode an address, and does not calculate a route.
Conflating the renderer with the data behind it is the most common mistake in
map integrations, and it leads directly to the second most common one:

:::warning Public OpenStreetMap tile servers are not a production tile service
They are run on donated infrastructure for development and light use. Pointing
an application at them is a breach of their usage policy and an operational
dependency on someone else's goodwill. LifeLink does not do it.
:::

## 15.2 What Amazon Location Service provides

Three distinct resources, all verified available in {{fact:aws_region}} and on
the {{fact:aws_plan}} plan during Phase 0:

| Resource | Purpose | Used by |
|---|---|---|
| Map | Vector tiles and style descriptor | Browser, via scoped credentials |
| Place index | Forward and reverse geocoding | Backend only |
| Route calculator | Road distance and travel time | Backend only |

*Table 15.1. The three Location resources.*

## 15.3 Why tiles go direct and geocoding does not

```diagram
type: layered
title: Two different paths to one provider
layer Browser
node ml MapLibre renderer style=user
layer Credentials
node idp Cognito identity pool temporary credentials style=aws
layer Backend
node api API function style=aws
layer Provider
node tiles Location map tiles style=external
node places Location places and routes style=external
edge ml -> idp
edge idp -> tiles
edge ml -> api
edge api -> places
```

*Figure 15.1. Tiles are fetched directly by the browser using scoped temporary
credentials; geocoding and routing go through the backend.*

Tiles must go direct, because proxying thousands of tile requests through
Lambda would be slow and expensive. The identity pool issues credentials scoped
to exactly four read-only tile actions — `GetMapTile`,
`GetMapStyleDescriptor`, `GetMapSprites`, `GetMapGlyphs` — and nothing else. A
browser holding them cannot geocode, cannot route, and cannot read any other
resource.

Geocoding and routing go through the backend because they are lower-volume,
benefit from caching, and should not be exposed to arbitrary client-side use.

## 15.4 Straight-line distance is never presented as road distance

The specification is explicit, and the type system enforces it:

{{include:backend/src/adapters/location.py:class RouteResult}}

*Listing 15.1. A routing result that can say "unavailable" without inventing a
number.*

When routing fails, `RouteResult(available=False)` carries a reason and leaves
distance and duration as `None`. Callers cannot accidentally use a missing
value, and the API response says directions are unavailable instead of
substituting the straight-line figure.

## 15.5 Graceful degradation

The specification requires that a mapping or routing failure must not break
facility discovery. LifeLink degrades in three stages:

1. **Routing fails** — the facility list, distances and contact details all
   survive; the response says directions are unavailable.
2. **Geocoding fails** — place search returns no results with
   `providerAvailable: false`, and the user can enter coordinates directly.
3. **Tiles fail** — the map component renders a usable facility list instead of
   an empty grey rectangle.

In the local environment there is no configured map style at all, so the list
fallback is the *default* path and is exercised constantly rather than being
untested emergency code.

## 15.6 Cost

Amazon Location charges per request: roughly $0.04 per thousand geocoding
requests and $0.50 per thousand map tile loads in this region, with a free tier
for the first months. Map tiles are the dominant cost in any real usage, which
is one more reason the list fallback is a first-class path rather than an
apology.

## 15.7 Alternatives

**OpenRouteService** is permitted by the specification as an optional secondary
routing provider. It was not adopted: a second provider that cannot be verified
end to end in this environment adds a failure mode without adding reliability.
The `RoutingProvider` interface leaves the seam open, which is the point of
having the abstraction.

**Google Maps Platform** would work and has excellent data quality, but
introduces a second vendor relationship, a separate billing arrangement and an
API key that must be kept out of the browser.
