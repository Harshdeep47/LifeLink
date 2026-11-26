# AWS Architecture — the complete resource inventory

Every AWS resource LifeLink actually has, where it lives, and what it is for.
All of it read from the live environment on 24 November 2026.

---

## 1. Account and Region facts

| Fact | Value |
|---|---|
| AWS account | `426150327442` |
| Region for all regional resources | **`ap-southeast-2`** (Asia Pacific, Sydney) |
| Global services in use | CloudFront, IAM |
| Account plan | FREE, `ACTIVE`, credits remaining, expires 2027-05-15 |
| CloudFormation stack | `lifelink-dev`, `UPDATE_COMPLETE`, 66 resources |
| Stack created | 2026-11-15 15:11 UTC |
| Stack last updated | 2026-11-24 08:33 UTC |
| Stack capabilities | `CAPABILITY_IAM` |
| Drift status | **`NOT_CHECKED`** — `NEEDS-VERIFICATION` |

### Why Sydney, when the data is about Punjab?

**This is a near-certain question, and the answer is a constraint, not a
preference.** The account is a new AWS experience project. All regional
resources must be created in the single Region derived from the contact
address, and resources cannot be created in other Regions. Mumbai
(`ap-south-1`) would be the obvious choice for Punjab data on latency grounds,
and it was not available.

The practical consequence: a user in Punjab talking to the API has a
round-trip of roughly 150–200 ms to Sydney. The *static site* does not suffer,
because CloudFront serves it from an edge location near the user. Only API
calls cross the ocean.

**Say it like this:** "Everything regional is in ap-southeast-2 because our
account is restricted to a single assigned Region. If we could choose, Mumbai
would be better for Indian users — about 150 milliseconds better per API call.
CloudFront already solves it for the static files, because those are cached at
the edge."

---

## 2. The 66 resources by type

| Type | Count | Names |
|---|---|---|
| `AWS::DynamoDB::Table` | 12 | `lifelink-dev-{organizations, facilities, inventory, reservations, camps, donations, emergency, alerts, notifications, audit, outbox, idempotency}` |
| `AWS::IAM::Role` | 9 | see [../04_AWS_COMPLETE_GUIDE/08_IAM_Complete_Guide.md](../04_AWS_COMPLETE_GUIDE/08_IAM_Complete_Guide.md) |
| `AWS::CloudWatch::Alarm` | 8 | 8 alarms, all `OK` |
| `AWS::Lambda::Function` | 6 | `lifelink-dev-{api, dispatcher, maintenance, outbox-publisher, work-worker, notification-worker}` |
| `AWS::SQS::Queue` | 4 | `lifelink-dev-{work, work-dlq, notifications, notifications-dlq}` |
| `AWS::Lambda::EventSourceMapping` | 3 | outbox stream, work queue, notification queue |
| `AWS::Cognito::*` | 5 | user pool, user pool client, user pool domain, identity pool, identity pool role attachment |
| `AWS::S3::Bucket` | 2 | `lifelink-dev-frontend-426150327442`, `lifelink-dev-uploads-426150327442` |
| `AWS::Logs::LogGroup` | 2 | `/aws/apigateway/lifelink-dev`, `/aws/lambda/lifelink-dev-api` |
| `AWS::Lambda::Permission` | 2 | API proxy + root invoke permissions |
| `AWS::Scheduler::Schedule` | 2 | `PriorityDispatcherEveryMinute`, `ScheduledMaintenanceEveryTenMinutes` |
| `AWS::ApiGatewayV2::*` | 2 | API `uk6itz2a5b`, stage `dev` |
| `AWS::CloudFront::*` | 2 | distribution `E236QHMFXHDEDL`, OAC `E2QR15L70UVPZT` |
| `AWS::Location::*` | 3 | map, place index, route calculator |
| `AWS::S3::BucketPolicy` | 1 | frontend bucket policy (OAC) |
| `AWS::SNS::Topic` | 1 | `lifelink-dev-alarms` |
| `AWS::CloudWatch::Dashboard` | 1 | `LifeLink-dev` |
| `AWS::SecretsManager::Secret` | 1 | `lifelink/dev/provider-api-keys` |

---

## 3. Stack outputs — the values everything else needs

```
AlarmTopicArn       arn:aws:sns:ap-southeast-2:426150327442:lifelink-dev-alarms
ApiEndpoint         https://uk6itz2a5b.execute-api.ap-southeast-2.amazonaws.com/dev
CognitoLoginUrl     https://lifelink-dev-426150327442.auth.ap-southeast-2.amazoncognito.com/login?...
DeployedRegion      ap-southeast-2
FrontendBucketName  lifelink-dev-frontend-426150327442
FrontendUrl         https://d324z37do52g8f.cloudfront.net
IdentityPoolId      ap-southeast-2:31685707-e3c3-4aa0-b4ca-b753c70b8688
MapName             lifelink-dev-map
UserPoolClientId    5hp4pm3ictvetfupddvl41pnf
UserPoolId          ap-southeast-2_Z91jyFm1d
```

**Demonstration tip.** Open CloudFormation -> `lifelink-dev` -> **Outputs**
and you have every identifier on one screen. It is the single best page to
start an AWS walkthrough from, because it proves the resources belong to one
managed stack rather than being clicked together by hand.

---

## 4. Stack parameters — the eight that must be passed

| Parameter | Deployed value |
|---|---|
| `Environment` | `dev` |
| `LogRetentionDays` | `30` |
| `EnableLocationResources` | `true` |
| `CallbackUrl` | `https://d324z37do52g8f.cloudfront.net/auth/callback` |
| `LogoutUrl` | `https://d324z37do52g8f.cloudfront.net/` |
| `CognitoDomainPrefix` | `lifelink-dev-426150327442` |
| `CorsAllowOrigins` | the three allowed origins |
| `SesSenderAddress` | *(empty)* |

**Two of these are dangerous to omit.** The template's defaults are
development values, so:

- Omitting `CognitoDomainPrefix` would **replace the Cognito user pool
  domain**, breaking every existing login URL.
- Omitting `CorsAllowOrigins` would drop the CloudFront origin, breaking every
  API call from the live site.

Both were avoided during the real deployments by reading the current values off
the running stack and passing them back verbatim.

---

## 5. What is global and what is regional

A teacher may test whether you understand this distinction.

| Service | Scope | Note |
|---|---|---|
| **CloudFront** | **Global** | Edge locations worldwide; the distribution is not "in" a Region |
| **IAM** | **Global** | Roles and policies are account-wide |
| S3 | Regional | The bucket lives in `ap-southeast-2`; the *namespace* is global |
| API Gateway | Regional | |
| Lambda | Regional | |
| DynamoDB | Regional | |
| Cognito | Regional | The pool id literally starts with `ap-southeast-2_` |
| SQS, SNS | Regional | |
| CloudWatch | Regional | Log groups and alarms are per Region |
| Amazon Location | Regional | |
| Secrets Manager | Regional | |

**The S3 subtlety worth knowing:** bucket *names* are globally unique, but the
bucket and its data are in one Region. That is why the bucket name has the
account id appended — to avoid a global name collision.

**The CloudFront subtlety:** when you open CloudFront in the Console, the
Region selector shows "Global". If someone asks "which Region is your CDN
in?", the correct answer is that a CDN is not in a Region — it has hundreds of
edge locations, and `PriceClass_100` limits ours to the cheaper set (North
America, Europe, and some Asian locations).

---

## 6. How a request crosses the boundaries

```
User in Punjab
   |
   |-- static files ----> CloudFront edge (nearest location) ----> S3 Sydney (on cache miss)
   |
   |-- API calls -------> API Gateway Sydney --> Lambda Sydney --> DynamoDB Sydney
   |
   |-- login ----------> Cognito Sydney
   |
   `-- basemap tiles ---> tile.openstreetmap.org (not AWS at all)
```

Only the first hop is geographically close. That is the honest picture, and it
is exactly what a well-informed teacher will probe.

---

## 7. Cost shape

**$0.00 net per month.** Measured gross usage was **$0.1628** for 1-25 November
2026, **fully offset by FREE-plan credits**, projecting to roughly
**$0.45-0.50 gross** for a full month. See
[../04_AWS_COMPLETE_GUIDE/13_AWS_Cost_And_Scalability.md](../04_AWS_COMPLETE_GUIDE/13_AWS_Cost_And_Scalability.md).
Why so little:

| Service | Why it costs almost nothing here |
|---|---|
| Lambda | Per-request billing; a demo makes thousands, not millions, of requests. arm64 is cheaper than x86 |
| DynamoDB | On-demand; 742 rows and low traffic. No provisioned capacity sitting idle |
| S3 | A few megabytes of static files |
| CloudFront | `PriceClass_100` and tiny traffic; free tier covers it |
| API Gateway | HTTP API is about 70% cheaper than REST API |
| Cognito | ESSENTIALS tier; 11 users is far inside the free allowance |
| SQS/SNS | Effectively zero messages |
| CloudWatch | Logs are the main cost, and see the retention gap below |
| Amazon Location | Request-based; only geocode and route calls, which are rare |

**The one cost to watch,** found during this documentation pass: four of the
six Lambda log groups have **no retention policy and never expire**. The
dispatcher alone has accumulated about 8 MB because it runs every minute. Only
the two log groups declared in `infrastructure/template.yaml` have the 30-day
retention that `LogRetentionDays` sets; the other four were auto-created by
Lambda on first invocation and inherited the default of "never expire".

This is a textbook **infrastructure-as-code coverage gap**: the setting exists
in the template, but only for the resources the template declares. It is
recorded as a limitation and was **not** changed, because the project is under
an engineering freeze.

---

## 8. Spoken answers

### 20–30 seconds

> "Everything is one CloudFormation stack called `lifelink-dev` — 66 resources
> in ap-southeast-2, plus CloudFront and IAM which are global. Twelve DynamoDB
> tables, six Lambdas, one HTTP API, a Cognito user pool, four SQS queues, two
> S3 buckets, and eight CloudWatch alarms. The whole thing costs about forty
> cents a month because every service is pay-per-use and nothing is running
> idle."

### 1–2 minutes

> "The entire infrastructure is defined in one SAM template,
> `infrastructure/template.yaml`, about fifteen hundred lines, and deployed as
> a single CloudFormation stack. That matters for two reasons: nothing was
> clicked together by hand, so the deployment is reproducible, and every
> resource can be found from one page — CloudFormation, Outputs — which is
> where I'd start a walkthrough.
>
> Region-wise, everything regional is in Sydney, ap-southeast-2. That's a
> constraint of our account, not a choice: it's a new-AWS-experience project
> with one assigned Region, so Mumbai wasn't available even though our data is
> about Punjab. CloudFront and IAM are global services, so they aren't 'in' a
> Region at all — and CloudFront is what saves us, because the static site is
> cached at an edge location near the user. Only API calls actually travel to
> Sydney.
>
> On cost, the net payable is zero — gross usage is about forty-five to fifty
> cents a month and FREE-plan credits cover it. The one thing I'd fix with more
> time is log retention: our template sets thirty days, but only for the two
> log groups it declares. The other four were created automatically by Lambda
> on first invocation, so they never expire. That's a coverage gap in the
> infrastructure code, and I found it while documenting rather than while
> building — which is a bit humbling but exactly what a review is for."

---

## 9. Follow-up questions

**"Is 66 the number in your template too?"**
> The deployed stack reports 66 resources. The template's own resource count
> should match, but note that SAM *transforms* the template — `AWS::Serverless::Function`
> expands into a Lambda function plus a role plus permissions — so counting
> `Resources:` entries in the source file gives a smaller number than the
> deployed stack. The authoritative count is
> `aws cloudformation describe-stack-resources`.

**"Why is deletion protection off on the tables?"**
> Because this is a demonstration environment that gets re-seeded, and
> deletion protection would block a stack teardown. In production it should be
> on for every table holding real records. It is listed as a known limitation
> rather than defended.

**"You said drift is NOT_CHECKED — is the deployment actually what the
template says?"**
> Honestly: we have not run drift detection, so I can only say the last
> deployment completed successfully and the changeset diff showed only the
> Lambda code keys changing. We do know of one piece of real drift-like
> divergence — the four auto-created log groups — which is not drift in
> CloudFormation's sense, because those resources were never in the stack at
> all. Running `aws cloudformation detect-stack-drift` would be the way to
> answer properly.

**"Could you make this multi-Region?"**
> Not in this account. Cross-Region actions are denied by policy — no
> cross-Region replication, no multi-Region KMS keys, no CloudFormation
> StackSets. Architecturally, DynamoDB global tables plus a second stack and
> Route 53 latency routing would be the normal approach, but Route 53
> latency-based routing is also unavailable here.

---

## 10. Cross-references

- Per-service depth: [../04_AWS_COMPLETE_GUIDE/](../04_AWS_COMPLETE_GUIDE/)
- Regions explained: [../04_AWS_COMPLETE_GUIDE/02_Regions_And_Availability_Zones.md](../04_AWS_COMPLETE_GUIDE/02_Regions_And_Availability_Zones.md)
- Every configuration setting: [../09_PRACTICAL_AWS_DEMONSTRATIONS/CONFIGURATION_WALKTHROUGHS.md](../09_PRACTICAL_AWS_DEMONSTRATIONS/CONFIGURATION_WALKTHROUGHS.md)
- Cost detail: [../04_AWS_COMPLETE_GUIDE/13_AWS_Cost_And_Scalability.md](../04_AWS_COMPLETE_GUIDE/13_AWS_Cost_And_Scalability.md)
